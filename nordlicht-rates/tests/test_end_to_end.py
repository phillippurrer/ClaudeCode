"""End-to-End durch echtes Chromium gegen einen lokalen Buchungsserver.

Der einzige Test, der browser.py wirklich ausfuehrt: Deeplink bauen, Seite
laden, die per fetch() nachgeladene JSON-Antwort mitschneiden, daraus
Kategorien bilden. Der Fake-Server bildet genau dieses Verhalten nach, weil
ein statisches HTML-Fixture den Mitschnitt gar nicht erst pruefen wuerde.

Die Zimmerdaten sind den Kategorien der Northern Lights Ranch nachempfunden -
dem Fall, an dem die bisherige Recherche scheiterte.
"""

import asyncio
from datetime import date, timedelta

import pytest

from fake_hotel import FakeHotel
from nordlicht_rates.abruf import hole_kategorien
from nordlicht_rates.browser import Browser
from nordlicht_rates.dates import zeitraum

# Weit genug in der Zukunft, damit der Test nicht irgendwann an der
# Vergangenheitspruefung scheitert.
ANREISE = (date.today() + timedelta(days=90)).isoformat()


def _lauf(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def hotel():
    with FakeHotel() as basis:
        yield basis


def test_kategorien_kommen_aus_der_json_antwort(hotel):
    zeit = zeitraum(ANREISE, naechte=2)
    d = _lauf(hole_kategorien(f"{hotel}/booking", zeit, cache_nutzen=False)).als_dict()

    assert d["gefunden"] >= 3, d
    assert d["preis_ab"] == 1430.0
    assert d["guenstigste_kategorie"] == "Sky View Cabin Superior"
    assert d["waehrung"] == "EUR"
    # Der Mitschnitt muss gewinnen - sonst haette nur die DOM-Heuristik gegriffen.
    assert any(k["quelle"] == "netzwerk" for k in d["kategorien"])


def test_die_eigentliche_frage_deluxe_mit_whirlpool(hotel):
    """Genau das, was ueber Google Hotels nicht zu ermitteln war: der Preis
    der Kategorie MIT privatem Whirlpool, getrennt von der ohne."""
    zeit = zeitraum(ANREISE, naechte=2)
    d = _lauf(hole_kategorien(f"{hotel}/booking", zeit, cache_nutzen=False)).als_dict()
    nach_name = {k["name"]: k for k in d["kategorien"]}

    superior = nach_name["Sky View Cabin Superior"]
    deluxe = nach_name["Sky View Cabin Deluxe"]
    ultimate = nach_name["Sky View Cabin Ultimate"]

    assert "privater Whirlpool" not in superior.get("ausstattung", [])
    assert "privater Whirlpool" in deluxe["ausstattung"]
    assert {"privater Whirlpool", "eigene Sauna"} <= set(ultimate["ausstattung"])
    assert deluxe["preis_gesamt"] == 1980.0
    assert deluxe["preis_pro_nacht"] == 990.0
    assert deluxe["groesse_m2"] == 25.0


def test_zeitraum_und_belegung_stehen_in_der_antwort(hotel):
    zeit = zeitraum(ANREISE, naechte=2)
    d = _lauf(
        hole_kategorien(f"{hotel}/booking", zeit, adults=2, cache_nutzen=False)
    ).als_dict()
    assert d["naechte"] == 2
    assert d["check_in"] == ANREISE
    assert d["belegung"] == {"adults": 2, "children": 0, "zimmer": 1}


def test_widget_seite_wird_weiterverfolgt(hotel):
    """Der Fall Northern Lights Ranch: Die Hotelseite zeigt selbst keinen
    Preis, die Buchung steckt in einem eingebetteten Frame."""
    zeit = zeitraum(ANREISE, naechte=2)
    ergebnis = _lauf(hole_kategorien(f"{hotel}/widget", zeit, cache_nutzen=False))
    d = ergebnis.als_dict()

    assert d["gefunden"] >= 3, d
    assert d["preis_ab"] == 1430.0
    assert any("eingebettete Buchungsstrecke" in h for h in d["hinweise"]), d["hinweise"]


def test_deeplink_wird_tatsaechlich_angesteuert(hotel):
    """Ohne Datumsparameter liefert der Fake-Server keine Zimmer - dass welche
    ankommen, beweist, dass der Deeplink gebaut und geladen wurde."""
    zeit = zeitraum(ANREISE, naechte=2)
    ergebnis = _lauf(
        hole_kategorien(f"{hotel}/booking", zeit, debug=True, cache_nutzen=False)
    )
    versuche = ergebnis.debug["versuche"]
    assert "checkin=" in versuche[0]["url"]
    assert versuche[0]["json_antworten"] >= 1


def test_erfolgsantwort_bleibt_schlank(hotel):
    """Ohne debug soll kein Diagnoseballast mitkommen."""
    zeit = zeitraum(ANREISE, naechte=2)
    d = _lauf(hole_kategorien(f"{hotel}/booking", zeit, cache_nutzen=False)).als_dict()
    assert d["gefunden"] > 0
    assert "debug" not in d


def test_leeres_ergebnis_liefert_diagnose_mit(hotel):
    zeit = zeitraum(ANREISE, naechte=1)
    d = _lauf(
        hole_kategorien(f"{hotel}/gibtesnicht", zeit, cache_nutzen=False)
    ).als_dict()
    assert d["debug"]["versuche"][0]["kategorien"] == 0


def test_dom_fallback_ohne_json(hotel):
    """Seite ohne API: die Preise stehen nur im HTML."""
    zeit = zeitraum(ANREISE, naechte=1)
    d = _lauf(hole_kategorien(f"{hotel}/nurdom", zeit, cache_nutzen=False)).als_dict()
    namen = {k["name"] for k in d["kategorien"]}
    assert "Dobbeltrom" in namen
    assert "Bytax" not in namen, "Kurtaxe darf nicht als Zimmer durchgehen"
    assert d["kategorien"][0]["quelle"] == "dom"
    # 2 450 statt 3 100 - der guenstigere der beiden Preise der Karte.
    familie = next(k for k in d["kategorien"] if k["name"] == "Familierom")
    assert familie["preis_gesamt"] == 2450.0


def test_sperre_wird_gemeldet_nicht_umgangen(hotel):
    zeit = zeitraum(ANREISE, naechte=1)
    d = _lauf(hole_kategorien(f"{hotel}/gesperrt", zeit, cache_nutzen=False)).als_dict()
    assert d["gefunden"] == 0
    assert any("abgewiesen" in h for h in d["hinweise"]), d.get("hinweise")


def test_leeres_ergebnis_wird_nicht_als_ausgebucht_verkauft(hotel):
    zeit = zeitraum(ANREISE, naechte=1)
    d = _lauf(
        hole_kategorien(f"{hotel}/gibtesnicht", zeit, cache_nutzen=False)
    ).als_dict()
    assert d["gefunden"] == 0
    assert "ausgebucht" in d["hinweis"] and "nicht korrekt gelesen" in d["hinweis"]


def test_ein_browser_fuer_mehrere_haeuser(hotel):
    """Der Reise-Pfad: mehrere Etappen teilen sich eine Browserinstanz."""

    async def mehrere():
        browser = Browser()
        try:
            return await asyncio.gather(
                hole_kategorien(f"{hotel}/booking", zeitraum(ANREISE, naechte=2),
                                browser=browser, cache_nutzen=False),
                hole_kategorien(f"{hotel}/nurdom", zeitraum(ANREISE, naechte=1),
                                browser=browser, cache_nutzen=False),
            )
        finally:
            await browser.stop()

    erst, zweit = _lauf(mehrere())
    assert erst.guenstigste.preis_gesamt.wert == 1430.0
    assert zweit.guenstigste.preis_gesamt.wert == 1890.0


def test_debug_legt_screenshot_und_html_ab(hotel, tmp_path, monkeypatch):
    from nordlicht_rates import config

    monkeypatch.setenv("NORDLICHT_DEBUG_DIR", str(tmp_path))
    config.einstellungen.cache_clear()
    try:
        zeit = zeitraum(ANREISE, naechte=1)
        ergebnis = _lauf(
            hole_kategorien(f"{hotel}/booking", zeit, debug=True, cache_nutzen=False)
        )
        assert ergebnis.debug.get("screenshots"), ergebnis.debug
        bilder = list(tmp_path.glob("*.png"))
        dumps = list(tmp_path.glob("*.html"))
        assert bilder and bilder[0].stat().st_size > 1000
        assert dumps and "Booking" in dumps[0].read_text(encoding="utf-8")
    finally:
        config.einstellungen.cache_clear()


def test_warten_auf_bestimmte_json_antwort(hotel):
    """Netzstille heisst nicht, dass die entscheidende Antwort da ist.

    Der Mews-Distributor startet seine Preisabfrage erst danach; ohne
    gezieltes Warten lieferte derselbe Abruf mal Preise und mal nicht.
    """
    from nordlicht_rates.browser import Browser

    async def hole(warte_auf_json):
        browser = Browser()
        try:
            return await browser.hole(
                f"{hotel}/booking?checkin={ANREISE}&checkout={ANREISE}&adults=2",
                selektoren={},
                json_pfade=["/api/"],
                zusatz_wartezeit_ms=0,
                warte_auf_json=warte_auf_json,
                warte_auf_json_ms=6000,
            )
        finally:
            await browser.stop()

    treffer = _lauf(hole("availability"))
    assert any("availability" in a["url"] for a in treffer.json_antworten)
    assert treffer.fehler is None or "availability" not in (treffer.fehler or "")


def test_ausbleibende_json_antwort_wird_gemeldet(hotel):
    """Wartet der Abruf vergeblich, muss das im Ergebnis stehen - sonst sieht
    ein Zeitproblem wie ein ausgebuchtes Haus aus."""
    from nordlicht_rates.browser import Browser

    async def hole():
        browser = Browser()
        try:
            return await browser.hole(
                f"{hotel}/booking",
                selektoren={},
                json_pfade=["/api/"],
                zusatz_wartezeit_ms=0,
                warte_auf_json="gibtesnicht",
                warte_auf_json_ms=1500,
            )
        finally:
            await browser.stop()

    treffer = _lauf(hole())
    assert "gibtesnicht" in (treffer.fehler or "")

