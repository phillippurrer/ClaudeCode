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

from .ausstattung import MERKMALE as MERKMAL_REIHENFOLGE
from .ausstattung import finde_groesse_m2, finde_merkmale
from .models import Zimmerkategorie
from .money import (
    Betrag,
    PreisFehler,
    erkenne_waehrung,
    ist_plausibler_zimmerpreis,
    parse_preis,
    pro_nacht,
)

# Schluessel, unter denen Buchungsmaschinen Preise bzw. Namen ablegen.
# grossvalue steht vor netvalue: Fuer den Gast zaehlt der Bruttopreis, den er
# zahlt, nicht der Nettobetrag ohne Umsatzsteuer.
_PREIS_SCHLUESSEL = (
    "totalprice", "total", "price", "amount", "rate", "grossamount",
    "grossvalue", "netvalue", "netamount", "cost", "value", "minprice",
    "fromprice", "averageprice", "averagenightlyrate", "totalamount",
    "pricetotal", "grandtotal",
)
_NAME_SCHLUESSEL = (
    "roomname", "roomtype", "roomtypename", "categoryname", "displayname",
    "name", "title", "label", "description", "shortname",
)
_WAEHRUNG_SCHLUESSEL = ("currency", "currencycode", "waehrung", "curr")

# Felder, die den Preis aufschluesseln statt ihn zu nennen. Hier wird nie
# hineingesucht: Ein Steueranteil ist fuer sich ein plausibler kleiner Betrag
# und gewinnt gegen den Gesamtpreis, sobald der guenstigste gesucht wird. Bei
# der Ranch fuehrte das zu 85,05 EUR fuer zwei Naechte - der halben
# Umsatzsteuer auf 1.430 EUR.
_TEILBETRAG_SCHLUESSEL = (
    "taxvalues", "taxes", "breakdown", "fees", "surcharges", "components",
    "items", "taxvalue", "taxrates", "adjustments",
)
_VERPFLEGUNG_SCHLUESSEL = ("board", "boardtype", "mealplan", "meal", "boardbasis")
_STORNO_SCHLUESSEL = ("refundable", "cancellable", "freecancellation", "isrefundable")
_BESCHREIBUNG_SCHLUESSEL = (
    "description", "shortdescription", "longdescription", "summary", "text",
    "roomdescription", "details", "beschreibung",
)
_AUSSTATTUNG_SCHLUESSEL = (
    "amenities", "features", "facilities", "attributes", "highlights",
    "roomamenities", "services", "ausstattung", "tags",
)
_GROESSE_SCHLUESSEL = (
    "size", "area", "squaremeters", "sqm", "roomsize", "surfacearea",
    "groesse", "flaeche",
)

# Namen, die zwar wie Zimmer klingen, aber Rahmendaten sind.
_NAME_SPERRE = re.compile(
    r"^(total|subtotal|summe|tax|vat|mwst|fee|city ?tax|kurtaxe|resort fee|"
    r"deposit|anzahlung|per night|pro nacht|from|ab)\b",
    re.I,
)


def _klein(schluessel) -> str:
    return str(schluessel).lower().replace("_", "").replace("-", "")


# Sprachschluessel, wie Buchungsmaschinen sie fuer uebersetzte Texte nutzen:
# "en-GB", "de_DE", "fi". Mews liefert Kategorienamen ausschliesslich so.
_SPRACHE = re.compile(r"^[a-z]{2}([-_][A-Za-z]{2,4})?$")
_BEVORZUGT = ("en-GB", "en-US", "en", "de-DE", "de", "fi-FI", "fi")


def _lokalisiert(wert) -> str | None:
    """Macht aus einem uebersetzten Feld eine Zeichenkette.

    Mews gibt Namen als {"en-GB": "Sky View Cabin Deluxe", ...} zurueck. Wer
    nur Zeichenketten akzeptiert, uebersieht dort jede einzige Kategorie -
    nicht weil die Daten fehlen, sondern weil sie eine Ebene tiefer liegen.
    """
    if isinstance(wert, str):
        return wert.strip() or None
    if isinstance(wert, dict) and wert:
        sprachen = [k for k in wert if _SPRACHE.match(str(k))]
        if not sprachen:
            return None
        for wunsch in _BEVORZUGT:
            for schluessel in sprachen:
                if str(schluessel).lower() == wunsch.lower():
                    text = wert[schluessel]
                    if isinstance(text, str) and text.strip():
                        return text.strip()
        for schluessel in sprachen:
            text = wert[schluessel]
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


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
            if _klein(schluessel) in _TEILBETRAG_SCHLUESSEL:
                continue
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
) -> list[Zimmerkategorie]:
    """Durchsucht eine beliebige JSON-Struktur nach Zimmer+Preis-Paaren.

    Es gibt kein gemeinsames Schema ueber Buchungsmaschinen hinweg, also wird
    der Baum abgelaufen und jedes Objekt genommen, das sowohl einen Namen als
    auch einen plausiblen Preis traegt.
    """
    gefunden: list[Zimmerkategorie] = []
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

        name = _name_aus(knoten)
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
                    beschreibung = _sammle_text(knoten)
                    gefunden.append(
                        Zimmerkategorie(
                            name=name.strip()[:120],
                            preis_gesamt=preis,
                            preis_pro_nacht=pro_nacht(preis, naechte)
                            if naechte > 1
                            else None,
                            groesse_m2=_groesse_aus(knoten, beschreibung),
                            ausstattung=finde_merkmale(name, beschreibung),
                            verpflegung=_text_oder_none(
                                _erstes_passendes(knoten, _VERPFLEGUNG_SCHLUESSEL)
                            ),
                            stornierbar=_bool_oder_none(
                                _erstes_passendes(knoten, _STORNO_SCHLUESSEL)
                            ),
                            zimmerhinweis=(beschreibung or None)
                            and beschreibung[:200],
                            quelle=quelle,
                        )
                    )

        for wert in knoten.values():
            lauf(wert, tiefe + 1, waehrung)

    lauf(daten, 0, waehrung_fallback)
    return gefunden


def _name_aus(knoten: dict) -> str | None:
    """Der Kategoriename eines Objekts, uebersetzte Felder eingeschlossen."""
    for schluessel, wert in knoten.items():
        if _klein(schluessel) in _NAME_SCHLUESSEL:
            text = _lokalisiert(wert)
            if text:
                return text
    return None


def _flach(wert) -> str:
    """Macht aus Listen, Dicts und Strings einen durchsuchbaren Text."""
    if isinstance(wert, str):
        return wert
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return str(wert)
    if isinstance(wert, list):
        return " ".join(_flach(e) for e in wert[:40])
    if isinstance(wert, dict):
        return " ".join(_flach(v) for v in list(wert.values())[:40])
    return ""


def _sammle_text(knoten: dict) -> str:
    """Beschreibung und Ausstattungsliste eines Knotens als ein Text.

    Buchungsmaschinen legen den Whirlpool mal in ein Feld "amenities", mal
    nur in den Fliesstext der Kategorie - beides wird hier zusammengefasst.
    """
    teile = []
    for schluessel, wert in knoten.items():
        klein = _klein(schluessel)
        if klein in _BESCHREIBUNG_SCHLUESSEL or klein in _AUSSTATTUNG_SCHLUESSEL:
            # Uebersetzte Felder zuerst: Sonst landen alle 34 Sprachfassungen
            # derselben Beschreibung im Text und verdraengen den Rest.
            text = (_lokalisiert(wert) or _flach(wert)).strip()
            if text:
                teile.append(text)
    return " ".join(teile)[:1200]


def _groesse_aus(knoten: dict, beschreibung: str) -> float | None:
    """Groesse zuerst aus einem eigenen Feld, sonst aus dem Text."""
    for schluessel, wert in knoten.items():
        if _klein(schluessel) not in _GROESSE_SCHLUESSEL:
            continue
        if isinstance(wert, (int, float)) and not isinstance(wert, bool):
            if 6 <= float(wert) <= 400:
                return float(wert)
        treffer = finde_groesse_m2(_flach(wert))
        if treffer:
            return treffer
    return finde_groesse_m2(beschreibung)


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


def angebote_aus_jsonld(html: str, *, naechte: int = 1) -> list[Zimmerkategorie]:
    """Liest schema.org-Angebote aus <script type="application/ld+json">."""
    sammler = _SkriptSammler()
    try:
        sammler.feed(html)
    except Exception:
        return []
    ergebnis: list[Zimmerkategorie] = []
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


def angebote_aus_state(html: str, *, naechte: int = 1) -> list[Zimmerkategorie]:
    """Liest den in die Seite eingebetteten Anwendungs-State.

    Bei Next.js/Nuxt-Buchungsstrecken stehen die Raten oft vollstaendig im
    Server-State, noch bevor eine einzige XHR laeuft.
    """
    ergebnis: list[Zimmerkategorie] = []
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


def _vereine(behalten: Zimmerkategorie, andere: Zimmerkategorie) -> Zimmerkategorie:
    """Uebernimmt Ausstattung und Groesse der schwaecheren Quelle.

    Die verlaesslichere Quelle gewinnt beim Preis, aber Ausstattung geht nicht
    verloren: Oft steht der Preis nur im JSON und der Whirlpool nur im
    gerenderten Beschreibungstext.
    """
    reihenfolge = list(MERKMAL_REIHENFOLGE)
    behalten.ausstattung = sorted(
        set(behalten.ausstattung) | set(andere.ausstattung),
        key=lambda m: reihenfolge.index(m) if m in reihenfolge else 99,
    )
    behalten.groesse_m2 = behalten.groesse_m2 or andere.groesse_m2
    behalten.zimmerhinweis = behalten.zimmerhinweis or andere.zimmerhinweis
    behalten.verpflegung = behalten.verpflegung or andere.verpflegung
    if behalten.stornierbar is None:
        behalten.stornierbar = andere.stornierbar
    return behalten


def entdoppel(kategorien: list[Zimmerkategorie]) -> list[Zimmerkategorie]:
    """Vereint Treffer aus mehreren Ebenen, verlaesslichste Quelle gewinnt."""
    rang = {"netzwerk": 0, "state": 1, "jsonld": 2, "dom": 3}
    beste: dict[tuple, Zimmerkategorie] = {}
    for kategorie in kategorien:
        preis = kategorie.preis_gesamt
        schluessel = (
            kategorie.name.strip().lower()[:60],
            round(preis.wert, 2) if preis else None,
        )
        vorhanden = beste.get(schluessel)
        if vorhanden is None:
            beste[schluessel] = kategorie
        elif rang.get(kategorie.quelle, 9) < rang.get(vorhanden.quelle, 9):
            beste[schluessel] = _vereine(kategorie, vorhanden)
        else:
            beste[schluessel] = _vereine(vorhanden, kategorie)
    return sorted(
        beste.values(),
        key=lambda k: (k.preis_gesamt.wert if k.preis_gesamt else float("inf")),
    )


# --- Verknuepfung ueber Kennungen ------------------------------------------

_ID_SCHLUESSEL = ("id", "uuid", "guid", "code", "key", "identifier")


def _sammle_namen(daten, namen: dict, tiefe: int = 0, nur_zimmer: bool = False) -> None:
    """Sammelt Kennung -> Name aus allen Objekten des Baums.

    nur_zimmer beschraenkt auf Objekte mit einem Zimmermerkmal (Bettenzahl,
    Raumart). Das ist bei Mews entscheidend: In derselben Antwort stehen
    Tarife, die ebenfalls Kennung und Name tragen. Ohne die Beschraenkung
    landen alle Preise beim Tarif "Cabin rate including breakfast" statt bei
    der Huette.
    """
    if tiefe > 12:
        return
    if isinstance(daten, list):
        for e in daten:
            _sammle_namen(e, namen, tiefe + 1, nur_zimmer)
        return
    if not isinstance(daten, dict):
        return
    if nur_zimmer and not any(
        _klein(schluessel) in _KATEGORIE_MERKMAL for schluessel in daten
    ):
        for wert in daten.values():
            _sammle_namen(wert, namen, tiefe + 1, nur_zimmer)
        return
    kennung = next(
        (v for k, v in daten.items()
         if _klein(k) in _ID_SCHLUESSEL and isinstance(v, str) and v.strip()),
        None,
    )
    name = _name_aus(daten)
    if kennung and name and not _NAME_SPERRE.match(name.strip()):
        namen.setdefault(kennung, (name.strip()[:120], _sammle_text(daten)))
    for v in daten.values():
        _sammle_namen(v, namen, tiefe + 1, nur_zimmer)


def _sammle_preise(
    daten, namen: dict, treffer: dict, waehrung=None, tiefe=0, kennung=None
) -> None:
    """Ordnet Preise der Kennung zu, auf die sie verweisen.

    Die Kennung wird nach unten vererbt: Bei Mews steht die categoryId ganz
    aussen, der Betrag drei Ebenen tiefer unter occupancyPrices ->
    rateGroupPrices -> minPrice -> totalAmount. Wer den Verweis nur im selben
    Objekt sucht, findet Preis und Kategorie nie zusammen.
    """
    if tiefe > 12:
        return
    if isinstance(daten, list):
        for e in daten:
            _sammle_preise(e, namen, treffer, waehrung, tiefe + 1, kennung)
        return
    if not isinstance(daten, dict):
        return
    for k, v in daten.items():
        if _klein(k) in _WAEHRUNG_SCHLUESSEL and isinstance(v, str) and len(v) <= 4:
            waehrung = v.upper()

    # Verweist dieses Objekt auf etwas Benanntes, gilt das ab hier auch fuer
    # alles darunter. Jeder String-Wert kommt in Frage, damit das konkrete
    # Feld ("categoryId", "RoomCategoryId", ...) nicht bekannt sein muss.
    #
    # Eine einmal gesetzte Kennung wird dabei nicht mehr ueberschrieben: Die
    # aeussere ist die richtige. Bei Mews steht die categoryId ganz aussen,
    # weiter innen aber eine minRateId, die auf den Tarif zeigt - und der
    # traegt ebenfalls einen Namen. Ohne diesen Vorrang landet der Preis beim
    # Tarif "Cabin rate including breakfast" statt bei der Huette.
    if kennung is None:
        for wert in daten.values():
            if isinstance(wert, str) and wert in namen:
                kennung = wert
                break

    preis = None
    for k, v in daten.items():
        if _klein(k) in _PREIS_SCHLUESSEL:
            preis = _betrag_aus_wert(v, waehrung)
            if preis:
                break
    if preis:
        if kennung:
            treffer.setdefault(kennung, []).append(preis)

    # Beim Abstieg nur die Werte verfolgen, die nicht selbst der Preis waren:
    # In totalAmount stehen neben grossValue auch netValue und die einzelnen
    # Steuerbetraege. Wer dort weitersucht, zaehlt denselben Preis dreimal -
    # einmal brutto, einmal netto, einmal als Steueranteil.
    for schluessel, wert in daten.items():
        if preis is not None and _klein(schluessel) in _PREIS_SCHLUESSEL:
            continue
        if _klein(schluessel) in _TEILBETRAG_SCHLUESSEL:
            continue
        _sammle_preise(wert, namen, treffer, waehrung, tiefe + 1, kennung)


def angebote_verknuepft(
    daten, *, naechte: int = 1, waehrung_fallback: str | None = None,
    quelle: str = "netzwerk",
) -> list[Zimmerkategorie]:
    """Fuer Buchungsmaschinen, die Name und Preis getrennt ausliefern.

    Mews etwa liefert Zimmerkategorien und Preise in eigenen Listen, verbunden
    ueber eine Kennung. Ein Sucher, der beides im selben Objekt erwartet,
    findet dort nichts - obwohl alle Daten da sind.
    """
    # Erst die Objekte, die sich als Zimmer ausweisen. Nur wenn sich gar
    # keines findet, wird ohne diese Huerde gesucht - andere Maschinen als
    # Mews kennen die betreffenden Felder nicht.
    namen: dict = {}
    _sammle_namen(daten, namen, nur_zimmer=True)
    if not namen:
        _sammle_namen(daten, namen)
    if not namen:
        return []
    treffer: dict = {}
    _sammle_preise(daten, namen, treffer, waehrung_fallback)

    ergebnis: list[Zimmerkategorie] = []
    for kennung, betraege in treffer.items():
        name, beschreibung = namen[kennung]
        waehrung = next(
            (b.waehrung for b in betraege if b.waehrung), waehrung_fallback
        )
        summe = Betrag(sum(b.wert for b in betraege), waehrung)
        hinweis = None

        # Genau so viele Betraege wie Naechte: koennte die Aufschluesselung
        # pro Nacht sein - der einzelne Nachtpreis ginge sonst als
        # Gesamtpreis durch, ein Fehler um Faktor naechte.
        #
        # Gleichheit ist dabei die Probe: Nachtpreise desselben Aufenthalts
        # sind fast immer identisch, verschiedene Tarife derselben Kategorie
        # nie. Ohne diese Bedingung wuerden bei zwei Naechten und zwei
        # Tarifgruppen - genau der Fall bei der Ranch - zwei
        # Gesamtpreise addiert.
        gleich_hoch = len({round(b.wert, 2) for b in betraege}) == 1
        if (
            naechte > 1
            and len(betraege) == naechte
            and gleich_hoch
            and ist_plausibler_zimmerpreis(summe, naechte)
        ):
            gesamt = summe
            hinweis = f"Summe aus {naechte} Nachtpreisen"
        else:
            brauchbar = [
                b for b in betraege if ist_plausibler_zimmerpreis(b, naechte)
            ]
            if not brauchbar:
                if not ist_plausibler_zimmerpreis(summe, naechte):
                    continue
                gesamt = summe
                hinweis = f"Summe aus {len(betraege)} Teilbetraegen"
            else:
                gesamt = min(brauchbar, key=lambda b: b.wert)
                if len(brauchbar) > 1:
                    hinweis = (
                        f"guenstigster von {len(brauchbar)} Preisen dieser "
                        "Kategorie"
                    )
        ergebnis.append(
            Zimmerkategorie(
                name=name,
                preis_gesamt=gesamt,
                preis_pro_nacht=pro_nacht(gesamt, naechte) if naechte > 1 else None,
                groesse_m2=finde_groesse_m2(beschreibung),
                ausstattung=finde_merkmale(name, beschreibung),
                zimmerhinweis=hinweis or (beschreibung[:200] or None),
                quelle=quelle,
            )
        )
    return ergebnis


def struktur(daten, tiefe: int = 0, max_tiefe: int = 3) -> str:
    """Kurzform des Aufbaus einer JSON-Antwort, fuer die Fehlersuche.

    Ganze Antworten zu verschicken ist unzumutbar; die Schluesselnamen sagen
    aber genau das, was fehlt, wenn eine Buchungsmaschine nicht gelesen wird.
    """
    if tiefe > max_tiefe:
        return "..."
    if isinstance(daten, dict):
        teile = []
        for k, v in list(daten.items())[:12]:
            teile.append(f"{k}:{struktur(v, tiefe + 1, max_tiefe)}")
        rest = ",..." if len(daten) > 12 else ""
        return "{" + ",".join(teile) + rest + "}"
    if isinstance(daten, list):
        if not daten:
            return "[]"
        return f"[{struktur(daten[0], tiefe + 1, max_tiefe)} x{len(daten)}]"
    if isinstance(daten, str):
        return "str"
    if isinstance(daten, bool):
        return "bool"
    if isinstance(daten, (int, float)):
        return "zahl"
    return "null"


# Felder, die ein Objekt als Zimmerkategorie ausweisen, auch ohne Preis.
_KATEGORIE_MERKMAL = (
    "normalbedcount", "extrabedcount", "spacetype", "occupancy", "maxoccupancy",
    "bedcount", "roomtype", "categorytype", "resourcecategorytype",
)


def kategorien_ohne_preis(daten, max_tiefe: int = 12) -> list[Zimmerkategorie]:
    """Zimmerkategorien ohne Preisangabe.

    Letzte Stufe, wenn keine Preise zu holen sind: Die Buchungsmaschine nennt
    ihre Kategorien oft trotzdem - mit Namen und Beschreibung. Damit laesst
    sich immerhin beantworten, welche Kategorien es gibt und welche einen
    Whirlpool haben; nur der Preis bleibt offen.

    Bewusst streng: Verlangt wird neben einem Namen ein Feld, das das Objekt
    als Zimmer ausweist (Bettenzahl, Belegung, Raumart). Ohne das faenden
    sich in jeder Antwort Dutzende benannter Objekte, die keine Zimmer sind.
    """
    gefunden: list[Zimmerkategorie] = []
    gesehen: set[str] = set()

    def lauf(knoten, tiefe: int) -> None:
        if tiefe > max_tiefe or len(gefunden) > 60:
            return
        if isinstance(knoten, list):
            for eintrag in knoten:
                lauf(eintrag, tiefe + 1)
            return
        if not isinstance(knoten, dict):
            return

        name = _name_aus(knoten)
        ist_zimmer = any(
            _klein(schluessel) in _KATEGORIE_MERKMAL for schluessel in knoten
        )
        if name and ist_zimmer and not _NAME_SPERRE.match(name.strip()):
            schluessel = name.strip().lower()[:60]
            if schluessel not in gesehen:
                gesehen.add(schluessel)
                beschreibung = _sammle_text(knoten)
                gefunden.append(
                    Zimmerkategorie(
                        name=name.strip()[:120],
                        groesse_m2=finde_groesse_m2(beschreibung),
                        ausstattung=finde_merkmale(name, beschreibung),
                        zimmerhinweis=(beschreibung[:200] or None),
                        verfuegbar=False,
                        quelle="netzwerk",
                    )
                )
        for wert in knoten.values():
            lauf(wert, tiefe + 1)

    lauf(daten, 0)
    return gefunden
