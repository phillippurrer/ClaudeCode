"""Zieht Zimmerangebote aus JSON und HTML.

Bewusst reine Funktionen ohne Playwright-Bezug: Genau hier passieren die
Fehler, und nur so lassen sie sich gegen gespeicherte Antworten testen, statt
gegen eine Live-Buchungsstrecke, die morgen anders aussieht.

Reihenfolge der Verlaesslichkeit:
  1. netzwerk  - die JSON-Antwort, aus der die Seite selbst ihre Preise malt
  2. state     - __NEXT_DATA__ / __NUXT__ / window.__INITIAL_STATE__
  3. jsonld    - schema.org-Offer, oft nur ein Ab-Preis
  4. dom       - Textheuristik, letzte Wahl
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

from .models import Zimmerangebot
from .money import (
    Betrag,
    PreisFehler,
    erkenne_waehrung,
    ist_plausibler_zimmerpreis,
    parse_preis,
    pro_nacht,
)

# Schluessel, unter denen Buchungsmaschinen Preise bzw. Namen ablegen.
_PREIS_SCHLUESSEL = (
    "totalprice", "total", "price", "amount", "rate", "grossamount",
    "netamount", "cost", "value", "minprice", "fromprice", "averageprice",
    "averagenightlyrate", "totalamount", "pricetotal", "grandtotal",
)
_NAME_SCHLUESSEL = (
    "roomname", "roomtype", "roomtypename", "categoryname", "displayname",
    "name", "title", "label", "description", "shortname",
)
_WAEHRUNG_SCHLUESSEL = ("currency", "currencycode", "waehrung", "curr")
_VERPFLEGUNG_SCHLUESSEL = ("board", "boardtype", "mealplan", "meal", "boardbasis")
_STORNO_SCHLUESSEL = ("refundable", "cancellable", "freecancellation", "isrefundable")

# Namen, die zwar wie Zimmer klingen, aber Rahmendaten sind.
_NAME_SPERRE = re.compile(
    r"^(total|subtotal|summe|tax|vat|mwst|fee|city ?tax|kurtaxe|resort fee|"
    r"deposit|anzahlung|per night|pro nacht|from|ab)\b",
    re.I,
)


def _klein(schluessel) -> str:
    return str(schluessel).lower().replace("_", "").replace("-", "")


def _betrag_aus_wert(wert, waehrung_fallback=None) -> Betrag | None:
    """Liest einen Preis aus Zahl, String oder verschachteltem Preisobjekt."""
    if isinstance(wert, bool) or wert is None:
        return None
    if isinstance(wert, (int, float)):
        return Betrag(float(wert), waehrung_fallback)
    if isinstance(wert, str):
        try:
            betrag = parse_preis(wert)
        except PreisFehler:
            return None
        return Betrag(betrag.wert, betrag.waehrung or waehrung_fallback)
    if isinstance(wert, dict):
        # {"amount": 1234, "currency": "NOK"} und Verwandte
        waehrung = waehrung_fallback
        for schluessel, inhalt in wert.items():
            if _klein(schluessel) in _WAEHRUNG_SCHLUESSEL and isinstance(inhalt, str):
                waehrung = inhalt.upper()
        for schluessel, inhalt in wert.items():
            if _klein(schluessel) in _PREIS_SCHLUESSEL:
                treffer = _betrag_aus_wert(inhalt, waehrung)
                if treffer:
                    return treffer
    return None


def _erstes_passendes(objekt: dict, schluessel_liste, pruefer=None):
    for schluessel, wert in objekt.items():
        if _klein(schluessel) in schluessel_liste:
            if pruefer is None or pruefer(wert):
                return wert
    return None


def angebote_aus_json(
    daten,
    *,
    naechte: int = 1,
    waehrung_fallback: str | None = None,
    quelle: str = "netzwerk",
    max_tiefe: int = 12,
) -> list[Zimmerangebot]:
    """Durchsucht eine beliebige JSON-Struktur nach Zimmer+Preis-Paaren.

    Es gibt kein gemeinsames Schema ueber Buchungsmaschinen hinweg, also wird
    der Baum abgelaufen und jedes Objekt genommen, das sowohl einen Namen als
    auch einen plausiblen Preis traegt.
    """
    gefunden: list[Zimmerangebot] = []
    gesehen: set[tuple] = set()

    def lauf(knoten, tiefe: int, geerbte_waehrung: str | None):
        if tiefe > max_tiefe or len(gefunden) > 200:
            return
        if isinstance(knoten, list):
            for eintrag in knoten:
                lauf(eintrag, tiefe + 1, geerbte_waehrung)
            return
        if not isinstance(knoten, dict):
            return

        waehrung = geerbte_waehrung
        roh_waehrung = _erstes_passendes(
            knoten, _WAEHRUNG_SCHLUESSEL, lambda w: isinstance(w, str) and len(w) <= 4
        )
        if roh_waehrung:
            waehrung = roh_waehrung.upper()

        name = _erstes_passendes(
            knoten, _NAME_SCHLUESSEL, lambda w: isinstance(w, str) and w.strip()
        )
        preis = None
        for schluessel, wert in knoten.items():
            if _klein(schluessel) in _PREIS_SCHLUESSEL:
                preis = _betrag_aus_wert(wert, waehrung)
                if preis:
                    break

        if name and preis and not _NAME_SPERRE.match(name.strip()):
            preis = Betrag(preis.wert, preis.waehrung or waehrung or waehrung_fallback)
            if ist_plausibler_zimmerpreis(preis, naechte):
                schluessel = (name.strip()[:80], round(preis.wert, 2), preis.waehrung)
                if schluessel not in gesehen:
                    gesehen.add(schluessel)
                    gefunden.append(
                        Zimmerangebot(
                            name=name.strip()[:120],
                            gesamtpreis=preis,
                            preis_pro_nacht=pro_nacht(preis, naechte)
                            if naechte > 1
                            else None,
                            verpflegung=_text_oder_none(
                                _erstes_passendes(knoten, _VERPFLEGUNG_SCHLUESSEL)
                            ),
                            stornierbar=_bool_oder_none(
                                _erstes_passendes(knoten, _STORNO_SCHLUESSEL)
                            ),
                            quelle=quelle,
                        )
                    )

        for wert in knoten.values():
            lauf(wert, tiefe + 1, waehrung)

    lauf(daten, 0, waehrung_fallback)
    return gefunden


def _text_oder_none(wert):
    if isinstance(wert, str) and wert.strip():
        return wert.strip()[:60]
    return None


def _bool_oder_none(wert):
    return wert if isinstance(wert, bool) else None


# --- HTML ------------------------------------------------------------------


class _SkriptSammler(HTMLParser):
    """Sammelt <script>-Inhalte samt type-Attribut."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skripte: list[tuple[str, str]] = []
        self._typ: str | None = None
        self._puffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._typ = dict(attrs).get("type", "text/javascript") or ""
            self._puffer = []

    def handle_data(self, data):
        if self._typ is not None:
            self._puffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._typ is not None:
            self.skripte.append((self._typ, "".join(self._puffer)))
            self._typ = None
            self._puffer = []


def angebote_aus_jsonld(html: str, *, naechte: int = 1) -> list[Zimmerangebot]:
    """Liest schema.org-Angebote aus <script type="application/ld+json">."""
    sammler = _SkriptSammler()
    try:
        sammler.feed(html)
    except Exception:
        return []
    ergebnis: list[Zimmerangebot] = []
    for typ, inhalt in sammler.skripte:
        if "ld+json" not in typ:
            continue
        try:
            daten = json.loads(inhalt.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        ergebnis.extend(
            angebote_aus_json(daten, naechte=naechte, quelle="jsonld")
        )
    return ergebnis


_STATE_MUSTER = (
    re.compile(r"__NEXT_DATA__\s*=\s*(\{.*?\})\s*(?:;|</script>)", re.S),
    re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*(?:;|</script>)", re.S),
    re.compile(r"window\.__NUXT__\s*=\s*(\{.*?\})\s*(?:;|</script>)", re.S),
    re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\})\s*(?:;|</script>)", re.S),
)


def angebote_aus_state(html: str, *, naechte: int = 1) -> list[Zimmerangebot]:
    """Liest den in die Seite eingebetteten Anwendungs-State.

    Bei Next.js/Nuxt-Buchungsstrecken stehen die Raten oft vollstaendig im
    Server-State, noch bevor eine einzige XHR laeuft.
    """
    ergebnis: list[Zimmerangebot] = []
    # __NEXT_DATA__ steht in einem eigenen script-Tag mit type application/json.
    sammler = _SkriptSammler()
    try:
        sammler.feed(html)
    except Exception:
        sammler = None
    if sammler:
        for typ, inhalt in sammler.skripte:
            if "application/json" not in typ:
                continue
            try:
                daten = json.loads(inhalt.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            ergebnis.extend(
                angebote_aus_json(daten, naechte=naechte, quelle="state")
            )
    for muster in _STATE_MUSTER:
        for treffer in muster.finditer(html):
            roh = treffer.group(1)
            try:
                daten = json.loads(roh)
            except (json.JSONDecodeError, ValueError):
                continue
            ergebnis.extend(
                angebote_aus_json(daten, naechte=naechte, quelle="state")
            )
    return ergebnis


def entdoppel(angebote: list[Zimmerangebot]) -> list[Zimmerangebot]:
    """Vereint Treffer aus mehreren Ebenen, verlaesslichste Quelle gewinnt."""
    rang = {"netzwerk": 0, "state": 1, "jsonld": 2, "dom": 3}
    beste: dict[tuple, Zimmerangebot] = {}
    for angebot in angebote:
        preis = angebot.gesamtpreis
        schluessel = (
            angebot.name.strip().lower()[:60],
            round(preis.wert, 2) if preis else None,
        )
        vorhanden = beste.get(schluessel)
        if vorhanden is None or rang.get(angebot.quelle, 9) < rang.get(
            vorhanden.quelle, 9
        ):
            beste[schluessel] = angebot
    return sorted(
        beste.values(),
        key=lambda a: (a.gesamtpreis.wert if a.gesamtpreis else float("inf")),
    )
