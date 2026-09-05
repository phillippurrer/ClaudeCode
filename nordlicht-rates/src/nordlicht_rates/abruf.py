"""Orchestrierung: von der Hotel-URL zur Kategorieliste.

Ablauf je Abruf:
  1. Buchungssystem anhand des Hosts erkennen
  2. Deeplink-Kandidaten bauen (bester zuerst) und laden
  3. Kategorien aus Netzwerk-JSON, State, JSON-LD und DOM zusammenfuehren
  4. Bleibt es leer: nach einer eingebetteten Buchungsmaschine suchen
     (Mews-Distributor, UpperBooking ...) und dieser folgen

Schritt 4 ist der Grund, warum das Tool ueberhaupt existiert: Haeuser wie die
Northern Lights Ranch zeigen auf der eigenen Seite keinen einzigen Preis, weil
die Zimmer aus einem fremdgehosteten Widget kommen.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlparse

from .browser import Browser, SeitenErgebnis
from .cache import TTLCache
from .config import einstellungen, lade_config
from .dates import Zeitraum
from .engines import Engine, baue_urls, engine_nach_id, erkenne_engine
from .extract import (
    angebote_aus_json,
    angebote_aus_jsonld,
    angebote_aus_state,
    angebote_verknuepft,
    entdoppel,
    struktur,
)
from .ausstattung import finde_groesse_m2, finde_merkmale
from .folge import folge_ziele
from .models import KategorieErgebnis, Zimmerkategorie
from .money import (
    KRONEN,
    PreisFehler,
    ist_plausibler_zimmerpreis,
    parse_alle_preise,
    pro_nacht,
)

_CACHE = TTLCache(ttl_s=einstellungen().cache_ttl_s)

# Hoechstens so viele Seitenaufrufe pro Anfrage, Weiterverfolgung eingerechnet.
# Danach ist die Konfiguration falsch, nicht die Seite langsam.
MAX_SEITEN = 5


def _land_fuer(engine: Engine, url: str) -> str | None:
    """Loest ein blankes 'kr' auf - erst ueber die Engine, dann ueber die TLD."""
    if engine.land:
        return engine.land
    host = (urlparse(url).hostname or "").lower()
    for tld, land in (
        (".no", "no"), (".se", "se"), (".dk", "dk"), (".is", "is"), (".fi", "fi")
    ):
        if host.endswith(tld):
            return land
    return None


def kategorien_aus_dom(
    kandidaten: list[dict], *, naechte: int, land: str | None
) -> list[Zimmerkategorie]:
    """Macht aus den DOM-Rohtexten Kategorien.

    Je Karte wird der kleinste plausible Betrag genommen: Buchungsstrecken
    zeigen daneben gern durchgestrichene Vergleichspreise, und der niedrigere
    ist der tatsaechlich buchbare.
    """
    ergebnis: list[Zimmerkategorie] = []
    for kandidat in kandidaten:
        name = (kandidat.get("name") or "").strip()
        if not name:
            continue
        karten_text = kandidat.get("karten_text") or ""
        betraege = []
        for text in kandidat.get("preis_texte") or []:
            try:
                betraege.extend(parse_alle_preise(text, land))
            except PreisFehler:
                continue
        plausibel = [b for b in betraege if ist_plausibler_zimmerpreis(b, naechte)]
        if not plausibel:
            continue
        guenstigster = min(plausibel, key=lambda b: b.wert)
        ergebnis.append(
            Zimmerkategorie(
                name=name[:120],
                preis_gesamt=guenstigster,
                preis_pro_nacht=pro_nacht(guenstigster, naechte)
                if naechte > 1
                else None,
                groesse_m2=finde_groesse_m2(karten_text),
                ausstattung=finde_merkmale(name, karten_text),
                zimmerhinweis=karten_text[:200] or None,
                quelle="dom",
            )
        )
    return ergebnis


def _sammle(
    seite: SeitenErgebnis, *, naechte: int, land: str | None
) -> list[Zimmerkategorie]:
    kategorien: list[Zimmerkategorie] = []
    for antwort in seite.json_antworten:
        kategorien.extend(
            angebote_aus_json(antwort["daten"], naechte=naechte, quelle="netzwerk")
        )
    if not kategorien:
        # Manche Buchungsmaschinen - Mews etwa - liefern Kategorien und Preise
        # in getrennten Listen, verbunden ueber eine Kennung. Erst wenn der
        # einfache Weg nichts findet, lohnt der teurere Verknuepfungsversuch.
        for antwort in seite.json_antworten:
            kategorien.extend(
                angebote_verknuepft(antwort["daten"], naechte=naechte)
            )
    if seite.html:
        kategorien.extend(angebote_aus_state(seite.html, naechte=naechte))
        kategorien.extend(angebote_aus_jsonld(seite.html, naechte=naechte))
    kategorien.extend(
        kategorien_aus_dom(seite.dom_kandidaten, naechte=naechte, land=land)
    )
    return entdoppel(kategorien)


def _cache_schluessel(url, zeit, adults, children, zimmer) -> str:
    return "|".join(
        [url, zeit.check_in.isoformat(), str(zeit.naechte),
         str(adults), str(children), str(zimmer)]
    )


async def hole_kategorien(
    buchungsseite: str,
    zeit: Zeitraum,
    *,
    adults: int = 2,
    children: int = 0,
    zimmer: int = 1,
    hotel_id: str | None = None,
    engine_id: str | None = None,
    debug: bool = False,
    browser: Browser | None = None,
    cache_nutzen: bool = True,
) -> KategorieErgebnis:
    """Holt die buchbaren Zimmerkategorien einer Hotel-URL fuer einen Zeitraum."""
    begonnen = time.monotonic()
    schluessel = _cache_schluessel(buchungsseite, zeit, adults, children, zimmer)
    if cache_nutzen and not debug:
        gespeichert = _CACHE.hole(schluessel)
        if gespeichert is not None:
            gespeichert.aus_cache = True
            return gespeichert

    engine = (engine_nach_id(engine_id) if engine_id else None) or erkenne_engine(
        buchungsseite
    )
    standard = lade_config().get("defaults", {})

    ergebnis = KategorieErgebnis(
        hotel=(urlparse(buchungsseite).hostname or buchungsseite),
        buchungsseite=buchungsseite,
        system=engine.id,
        zeitraum=zeit.als_dict(),
        belegung={"adults": adults, "children": children, "zimmer": zimmer},
    )
    if not engine.geprueft:
        ergebnis.hinweise.append(
            f"Der Deeplink fuer '{engine.id}' ist nicht gegen die Live-Seite "
            "verifiziert (geprueft: false in engines.yaml). Bei leerem "
            "Ergebnis buchungsstrecke_pruefen aufrufen."
        )

    eigener_browser = browser is None
    browser = browser or Browser()
    versuche: list[dict] = []
    gefunden: list[Zimmerkategorie] = []

    async def lade(url: str, quelle_engine: Engine) -> SeitenErgebnis:
        return await browser.hole(
            url,
            selektoren=quelle_engine.selektoren,
            json_pfade=quelle_engine.json_pfade,
            warte_auf=standard.get("warte_auf", "networkidle"),
            zusatz_wartezeit_ms=standard.get("zusatz_wartezeit_ms", 1200),
            debug=debug,
            debug_name=f"{quelle_engine.id}-{zeit.check_in.isoformat()}",
        )

    try:
        offen = [
            (u, engine)
            for u in baue_urls(
                engine, buchungsseite, zeit,
                adults=adults, children=children, zimmer=zimmer,
                hotel_id=hotel_id,
            )[:3]
        ]
        gesehen: set[str] = set()
        weiterverfolgt = False

        while offen and len(versuche) < MAX_SEITEN:
            url, akt_engine = offen.pop(0)
            if url in gesehen:
                continue
            gesehen.add(url)

            seite = await lade(url, akt_engine)
            land = _land_fuer(akt_engine, url)
            kategorien = _sammle(seite, naechte=zeit.naechte, land=land)
            versuche.append(
                {
                    "url": url,
                    "system": akt_engine.id,
                    "status": seite.status,
                    "json_antworten": len(seite.json_antworten),
                    "dom_karten": len(seite.dom_kandidaten),
                    "kategorien": len(kategorien),
                    "fehler": seite.fehler,
                }
            )
            if debug and seite.screenshot:
                ergebnis.debug.setdefault("screenshots", []).append(seite.screenshot)
                ergebnis.debug.setdefault("html_dumps", []).append(seite.html_dump)
            if not kategorien and seite.json_antworten:
                # Der Aufbau der Antworten sagt, welche Schluesselnamen der
                # Extraktion fehlen. Dieselbe Adresse wird pro Seitenaufruf
                # mehrfach abgefragt - ohne Entdopplung besteht das Protokoll
                # zu drei Vierteln aus Wiederholungen.
                gesehen = {e["url"] for e in ergebnis.debug.get("json_aufbau", [])}
                for antwort in seite.json_antworten:
                    kurz = antwort["url"].split("?")[0][:120]
                    if kurz in gesehen or len(gesehen) >= 14:
                        continue
                    gesehen.add(kurz)
                    eintrag = {"url": kurz, "aufbau": struktur(antwort["daten"])[:500]}
                    # Bei den Antworten, die ueber Preise entscheiden, reichen
                    # Schluesselnamen nicht: Ob eine Einschraenkung wegen
                    # Vorlauf, Mindestdauer oder Zeitraum greift, steht in den
                    # Werten. Nur diese wenigen Antworten, und gekuerzt.
                    if any(
                        wort in kurz.lower()
                        for wort in ("getpricing", "restrictions", "getavailability")
                    ):
                        try:
                            eintrag["inhalt"] = json.dumps(
                                antwort["daten"], ensure_ascii=False
                            )[:2500]
                        except (TypeError, ValueError):
                            pass
                    ergebnis.debug.setdefault("json_aufbau", []).append(eintrag)

            if seite.blockiert:
                ergebnis.hinweise.append(
                    f"Die Seite hat den Zugriff abgewiesen (Status {seite.status}). "
                    "Das wird hier nicht umgangen - Preis bitte manuell pruefen."
                )
                break

            if kategorien:
                gefunden.extend(kategorien)
                ergebnis.buchungsseite = seite.end_url
                ergebnis.system = akt_engine.id
                if seite.titel:
                    ergebnis.hotel = seite.titel
                # Mehrere Mews-Konfigurationen koennen verschiedene Huetten
                # fuehren, deshalb die restlichen Weiterverfolgungen zu Ende
                # gehen - aber keine neuen Deeplink-Varianten mehr probieren.
                offen = [(u, e) for u, e in offen if e.id != engine.id]
                continue

            # Nichts gefunden: steckt die Buchungsstrecke in einem Widget?
            if not weiterverfolgt and seite.html:
                ziele = folge_ziele(seite.html, akt_engine.id, seite.end_url)
                if ziele:
                    weiterverfolgt = True
                    ergebnis.hinweise.append(
                        f"Die Seite zeigt selbst keine Preise; {len(ziele)} "
                        "eingebettete Buchungsstrecke(n) gefunden und geoeffnet."
                    )
                    for ziel in ziele:
                        ziel_engine = erkenne_engine(ziel)
                        for gebaut in baue_urls(
                            ziel_engine, ziel, zeit,
                            adults=adults, children=children, zimmer=zimmer,
                        )[:1]:
                            offen.append((gebaut, ziel_engine))
    finally:
        if eigener_browser:
            await browser.stop()

    if gefunden:
        ergebnis.kategorien = entdoppel(gefunden)[: einstellungen().max_angebote]
        waehrungen = {
            k.preis_gesamt.waehrung
            for k in ergebnis.kategorien
            if k.preis_gesamt and k.preis_gesamt.waehrung
        }
        if len(waehrungen) == 1:
            ergebnis.waehrung = waehrungen.pop()
            if ergebnis.waehrung == KRONEN:
                ergebnis.hinweise.append(
                    "Die Seite schreibt nur 'kr' - ob NOK, SEK, DKK oder ISK "
                    "gemeint ist, geht daraus nicht hervor."
                )
        elif len(waehrungen) > 1:
            ergebnis.hinweise.append(
                "Mehrere Waehrungen auf der Seite gefunden "
                f"({', '.join(sorted(waehrungen))}) - Betraege pruefen."
            )

    ergebnis.dauer_s = time.monotonic() - begonnen
    # Das Versuchsprotokoll ist Diagnosematerial. Bei einem Treffer blaeht es
    # die Antwort nur auf; bei einem leeren Ergebnis ist es die halbe Miete.
    if versuche and (debug or not ergebnis.kategorien):
        ergebnis.debug["versuche"] = versuche
    if not ergebnis.kategorien:
        if sum(v["json_antworten"] for v in versuche) == 0 and not ergebnis.hinweise:
            ergebnis.hinweise.append(
                "Keine JSON-Antwort der Buchungsmaschine mitgeschnitten - "
                "vermutlich wurde die Ergebnisliste nie geladen, der Deeplink "
                "passt also nicht."
            )
    elif cache_nutzen and not debug:
        _CACHE.setze(schluessel, ergebnis)
    return ergebnis
