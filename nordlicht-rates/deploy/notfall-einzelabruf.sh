#!/bin/sh
# ---------------------------------------------------------------------------
# Plan B: Preise abfragen ohne git, ohne Repo-Zugang, ohne docker build.
#
# Nur noetig, wenn synology-aufgabe.sh an einem dieser Punkte scheitert:
#   - "git: command not found"       (git ist auf DSM nicht vorinstalliert)
#   - "Authentication failed"        (die NAS hat keine GitHub-Zugangsdaten)
#
# Dieses Skript reicht ein eigenstaendiges Python-Programm per stdin in das
# fertige Playwright-Image. Es laedt nichts herunter ausser dem Image selbst.
#
# Bewusst eine abgespeckte Fassung des Pakets: dieselbe Vorgehensweise
# (Deeplink, Mitschnitt der JSON-Antworten, Mews-Widget verfolgen), aber ohne
# die Engine-Konfiguration und ohne die Testabdeckung. Fuer den Dauerbetrieb
# bleibt das Paket der richtige Weg.
# ---------------------------------------------------------------------------
set -u

HOTEL="${HOTEL:-https://theranch.fi/check-availability/}"
CHECK_IN="${CHECK_IN:-2027-02-22}"
NAECHTE="${NAECHTE:-2}"
ADULTS="${ADULTS:-2}"

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PATH

if ! command -v docker >/dev/null 2>&1; then
    echo "FEHLER: docker nicht gefunden - Paket 'Container Manager' installieren."
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "FEHLER: Kein Zugriff auf den Docker-Dienst."
    echo "Die Aufgabe laeuft als '$(id -un 2>/dev/null || echo unbekannt)';"
    echo "im Aufgabenplaner unter 'Allgemein' den Benutzer auf root stellen."
    exit 1
fi

echo "Frage ab: $HOTEL"
echo "Ab $CHECK_IN, $NAECHTE Naechte, $ADULTS Erwachsene"
echo

docker run --rm -i --shm-size=512m --memory=1g \
    -e HOTEL="$HOTEL" -e CHECK_IN="$CHECK_IN" \
    -e NAECHTE="$NAECHTE" -e ADULTS="$ADULTS" \
    mcr.microsoft.com/playwright/python:v1.56.0-noble python - <<'PYTHON'
import asyncio, json, os, re, sys
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

HOTEL = os.environ["HOTEL"]
EIN = date.fromisoformat(os.environ["CHECK_IN"])
NAECHTE = int(os.environ["NAECHTE"])
AUS = EIN + timedelta(days=NAECHTE)
ADULTS = int(os.environ["ADULTS"])

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PREIS_K = ("totalprice", "total", "price", "amount", "rate", "grossamount",
           "minprice", "fromprice", "totalamount")
NAME_K = ("roomname", "roomtype", "roomtypename", "categoryname", "displayname",
          "name", "title", "shortname")
TEXT_K = ("description", "shortdescription", "amenities", "features",
          "facilities", "highlights", "summary")
SPERRE = re.compile(r"^(total|subtotal|tax|vat|fee|city ?tax|deposit|from|ab)\b", re.I)
MERKMALE = {
    "Whirlpool": ("hot tub", "whirlpool", "jacuzzi", "poreallas"),
    "Sauna": ("private sauna", "own sauna", "oma sauna", "sauna in the"),
    "Glasdach": ("glass roof", "glass ceiling", "sky view", "lasikatto"),
    "Kamin": ("fireplace", "takka"),
}

def klein(s): return str(s).lower().replace("_", "").replace("-", "")

def flach(v, tiefe=0):
    if tiefe > 3: return ""
    if isinstance(v, str): return v
    if isinstance(v, (int, float)) and not isinstance(v, bool): return str(v)
    if isinstance(v, list): return " ".join(flach(e, tiefe+1) for e in v[:30])
    if isinstance(v, dict): return " ".join(flach(x, tiefe+1) for x in list(v.values())[:30])
    return ""

def betrag(v, w=None):
    if isinstance(v, bool) or v is None: return None
    if isinstance(v, (int, float)): return (float(v), w)
    if isinstance(v, str):
        m = re.search(r"\d[\d\s.,]*\d|\d", v)
        if not m: return None
        roh = re.sub(r"\s", "", m.group())
        if "." in roh and "," in roh:
            d = "." if roh.rfind(".") > roh.rfind(",") else ","
            roh = roh.replace("," if d == "." else ".", "").replace(d, ".")
        elif "," in roh or "." in roh:
            z = "," if "," in roh else "."
            t = roh.split(z)
            roh = roh.replace(z, "") if len(t) > 2 or len(t[-1]) == 3 else roh.replace(z, ".")
        try: return (float(roh), w)
        except ValueError: return None
    if isinstance(v, dict):
        for k2, v2 in v.items():
            if klein(k2) in ("currency", "currencycode") and isinstance(v2, str): w = v2.upper()
        for k2, v2 in v.items():
            if klein(k2) in PREIS_K:
                t = betrag(v2, w)
                if t: return t
    return None

def ernte(knoten, gefunden, w=None, tiefe=0):
    if tiefe > 12 or len(gefunden) > 200: return
    if isinstance(knoten, list):
        for e in knoten: ernte(e, gefunden, w, tiefe+1)
        return
    if not isinstance(knoten, dict): return
    for k, v in knoten.items():
        if klein(k) in ("currency", "currencycode") and isinstance(v, str) and len(v) <= 4:
            w = v.upper()
    name = next((v for k, v in knoten.items()
                 if klein(k) in NAME_K and isinstance(v, str) and v.strip()), None)
    preis = None
    for k, v in knoten.items():
        if klein(k) in PREIS_K:
            preis = betrag(v, w)
            if preis: break
    if name and preis and not SPERRE.match(name.strip()):
        wert, wae = preis
        grenze = (5000, 2000000) if wae == "ISK" else (25, 20000 * max(NAECHTE, 1))
        if grenze[0] <= wert <= grenze[1]:
            text = " ".join(flach(v) for k, v in knoten.items() if klein(k) in TEXT_K)
            gross = (name + " " + text).lower()
            aus = [m for m, worte in MERKMALE.items() if any(x in gross for x in worte)]
            gr = re.search(r"(\d{1,3})\s*(?:m²|m2|sqm|neli)", text, re.I)
            gefunden.append({
                "name": name.strip()[:60], "preis": round(wert, 2), "waehrung": wae,
                "ausstattung": aus, "m2": gr.group(1) if gr else None,
            })
    for v in knoten.values(): ernte(v, gefunden, w, tiefe+1)

async def hole(seite, url, treffer):
    async def bei_antwort(a):
        try:
            if "json" not in (a.headers or {}).get("content-type", "").lower(): return
            treffer.append(json.loads(await a.body()))
        except Exception: pass
    seite.on("response", bei_antwort)
    print(f"  -> {url[:110]}")
    await seite.goto(url, wait_until="domcontentloaded", timeout=60000)
    try: await seite.wait_for_load_state("networkidle", timeout=25000)
    except Exception: pass
    await seite.wait_for_timeout(2500)
    return await seite.content()

def kandidaten(url):
    """Ohne Datum in der Adresse zeigt keine Buchungsstrecke Preise. Die
    unveraenderte Seite kommt zuerst - eine Hotelseite wie theranch.fi
    braucht keine Parameter, sondern verweist erst auf ihr Widget."""
    t = "&" if "?" in url else "?"
    return [
        url,
        f"{url}{t}checkin={EIN}&checkout={AUS}&adults={ADULTS}",
        f"{url}{t}arrival={EIN}&departure={AUS}&adults={ADULTS}",
        f"{url}{t}checkInDate={EIN}&checkOutDate={AUS}&adults={ADULTS}",
    ]


async def main():
    antworten = []
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await b.new_context(locale="en-GB", timezone_id="Europe/Helsinki",
                                  viewport={"width": 1440, "height": 1000})
        seite = await ctx.new_page()

        gefunden, html = [], ""
        for url in kandidaten(HOTEL):
            antworten.clear()
            try:
                html = await hole(seite, url, antworten)
            except Exception as exc:
                print(f"     Fehler: {str(exc)[:120]}")
                continue
            for a in antworten: ernte(a, gefunden)
            if gefunden: break

        if not gefunden:
            # Die Buchungsstrecke steckt oft in einem Widget auf fremder
            # Domain - bei der Ranch ein Mews-Distributor, bei anderen
            # Haeusern schlicht ein iframe.
            ziele, gesehen = [], set()
            for m in re.finditer(r"(?:app|booking)\.mews\.com/distributor/(" + UUID + ")", html, re.I):
                if m.group(1).lower() not in gesehen:
                    gesehen.add(m.group(1).lower()); ziele.append(("mews", m.group(1)))
            for m in re.finditer(r"(?:configurationIds?|mewsDistributorConfigurationId|"
                                 r"data-mews-configuration|configuration_id)", html, re.I):
                for g in re.findall(UUID, html[m.end():m.end()+400], re.I):
                    if g.lower() not in gesehen:
                        gesehen.add(g.lower()); ziele.append(("mews", g))
            for m in re.finditer(r"<iframe[^>]+src\s*=\s*[\"']([^\"']+)[\"']", html, re.I):
                voll = urljoin(seite.url, m.group(1))
                if re.search(r"(book|reserv|availab|distributor|rooms|varaa)",
                             urlparse(voll).path, re.I) and voll not in gesehen:
                    gesehen.add(voll); ziele.append(("iframe", voll))

            if ziele:
                print(f"\nHotelseite ohne eigene Preise; "
                      f"{len(ziele)} eingebettete Buchungsstrecke(n) gefunden.")
            for art, wert in ziele[:3]:
                if art == "mews":
                    adressen = [f"https://app.mews.com/distributor/{wert}"
                                f"?mewsStart={EIN}&mewsEnd={AUS}&mewsAdultCount={ADULTS}"]
                else:
                    adressen = kandidaten(wert)
                for adresse in adressen:
                    antworten.clear()
                    try: await hole(seite, adresse, antworten)
                    except Exception as exc:
                        print(f"     Fehler: {str(exc)[:120]}"); continue
                    for a in antworten: ernte(a, gefunden)
                    if gefunden: break
                if gefunden: break
        await b.close()

    einmalig, gesehen = [], set()
    for g in gefunden:
        s = (g["name"].lower(), g["preis"])
        if s not in gesehen:
            gesehen.add(s); einmalig.append(g)
    einmalig.sort(key=lambda g: g["preis"])

    print()
    if not einmalig:
        print("Keine Kategorien gefunden.")
        print(f"({len(antworten)} JSON-Antworten mitgeschnitten, HTML {len(html)} Zeichen)")
        sys.exit(1)
    print(f"{'Kategorie':<42} {'gesamt':>12} {'m2':>4}  Ausstattung")
    print("-" * 90)
    for g in einmalig[:30]:
        print(f"{g['name']:<42} {g['preis']:>9,.0f} {g['waehrung'] or '':<3} "
              f"{g['m2'] or '-':>4}  {', '.join(g['ausstattung']) or '-'}")
    mit = [g for g in einmalig if "Whirlpool" in g["ausstattung"]]
    ohne = [g for g in einmalig if "Whirlpool" not in g["ausstattung"]]
    if mit and ohne:
        print(f"\nohne Whirlpool: {ohne[0]['name']} - {ohne[0]['preis']:,.0f} {ohne[0]['waehrung'] or ''}")
        print(f"mit  Whirlpool: {mit[0]['name']} - {mit[0]['preis']:,.0f} {mit[0]['waehrung'] or ''}")
        print(f"Aufpreis:       {mit[0]['preis'] - ohne[0]['preis']:,.0f}")

asyncio.run(main())
PYTHON
