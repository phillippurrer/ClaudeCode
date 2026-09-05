"""End-to-End durch echtes Chromium gegen einen lokalen Buchungsserver.

Das ist der einzige Test, der browser.py wirklich ausfuehrt: Deeplink bauen,
Seite laden, die per fetch() nachgeladene JSON-Antwort mitschneiden, daraus
Angebote bilden. Der Fake-Server bildet genau dieses Verhalten nach, weil ein
statisches HTML-Fixture den Mitschnitt gar nicht erst pruefen wuerde.
"""

import asyncio
from datetime import date, timedelta

import pytest

from fake_hotel import FakeHotel
from nordlicht_rates.abruf import hole_preise
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


def test_preise_kommen_aus_der_json_antwort(hotel):
    zeit = zeitraum(ANREISE, naechte=3)
    ergebnis = _lauf(hole_preise(f"{hotel}/booking", zeit, cache_nutzen=False))
    d = ergebnis.als_dict()

    assert d["gefunden"] >= 3, d
    assert d["bestpreis"] == 4590.0
    assert d["bestpreis_zimmer"] == "Standard Double"
    assert d["waehrung"] == "NOK"
    # Der Mitschnitt muss gewinnen - sonst haette nur die DOM-Heuristik gegriffen.
    assert any(a["quelle"] == "netzwerk" for a in d["angebote"])


def test_pro_nacht_und_zeitraum_stimmen(hotel):
    zeit = zeitraum(ANREISE, naechte=3)
    d = _lauf(hole_preise(f"{hotel}/booking", zeit, cache_nutzen=False)).als_dict()
    standard = next(a for a in d["angebote"] if a["zimmer"] == "Standard Double")
    assert standard["pro_nacht"] == 1530.0
    assert d["naechte"] == 3
    assert d["check_in"] == ANREISE


def test_deeplink_wird_tatsaechlich_angesteuert(hotel):
    """Ohne Datumsparameter liefert der Fake-Server keine Zimmer - dass welche
    ankommen, beweist, dass der Deeplink gebaut und geladen wurde."""
    zeit = zeitraum(ANREISE, naechte=2)
    ergebnis = _lauf(
        hole_preise(f"{hotel}/booking", zeit, debug=True, cache_nutzen=False)
    )
    versuche = ergebnis.debug["versuche"]
    assert "checkin=" in versuche[0]["url"]
    assert versuche[0]["json_antworten"] >= 1


def test_erfolgsantwort_bleibt_schlank(hotel):
    """Ohne debug soll kein Diagnoseballast mitkommen."""
    zeit = zeitraum(ANREISE, naechte=2)
    d = _lauf(hole_preise(f"{hotel}/booking", zeit, cache_nutzen=False)).als_dict()
    assert d["gefunden"] > 0
    assert "debug" not in d


def test_leeres_ergebnis_liefert_diagnose_mit(hotel):
    """Bei null Treffern ist das Versuchsprotokoll die halbe Miete."""
    zeit = zeitraum(ANREISE, naechte=1)
    d = _lauf(hole_preise(f"{hotel}/gibtesnicht", zeit, cache_nutzen=False)).als_dict()
    assert d["debug"]["versuche"][0]["angebote"] == 0


def test_dom_fallback_ohne_json(hotel):
    """Seite ohne API: die Preise stehen nur im HTML."""
    zeit = zeitraum(ANREISE, naechte=1)
    d = _lauf(hole_preise(f"{hotel}/nurdom", zeit, cache_nutzen=False)).als_dict()
    namen = {a["zimmer"] for a in d["angebote"]}
    assert "Dobbeltrom" in namen
    assert "Bytax" not in namen, "Kurtaxe darf nicht als Zimmer durchgehen"
    assert d["angebote"][0]["quelle"] == "dom"
    # 2 450 statt 3 100 - der guenstigere der beiden Preise der Karte.
    familie = next(a for a in d["angebote"] if a["zimmer"] == "Familierom")
    assert familie["gesamtpreis"] == 2450.0


def test_sperre_wird_gemeldet_nicht_umgangen(hotel):
    zeit = zeitraum(ANREISE, naechte=1)
    ergebnis = _lauf(hole_preise(f"{hotel}/gesperrt", zeit, cache_nutzen=False))
    d = ergebnis.als_dict()
    assert d["gefunden"] == 0
    assert any("abgewiesen" in w for w in d["warnungen"]), d.get("warnungen")


def test_leeres_ergebnis_wird_nicht_als_ausgebucht_verkauft(hotel):
    zeit = zeitraum(ANREISE, naechte=1)
    d = _lauf(hole_preise(f"{hotel}/gibtesnicht", zeit, cache_nutzen=False)).als_dict()
    assert d["gefunden"] == 0
    assert "ausgebucht" in d["ergebnis"] and "nicht korrekt gelesen" in d["ergebnis"]


def test_ein_browser_fuer_mehrere_hotels(hotel):
    """Der Reise-Pfad: mehrere Etappen teilen sich eine Browserinstanz."""

    async def mehrere():
        browser = Browser()
        try:
            return await asyncio.gather(
                hole_preise(f"{hotel}/booking", zeitraum(ANREISE, naechte=2),
                            browser=browser, cache_nutzen=False),
                hole_preise(f"{hotel}/nurdom", zeitraum(ANREISE, naechte=1),
                            browser=browser, cache_nutzen=False),
            )
        finally:
            await browser.stop()

    erst, zweit = _lauf(mehrere())
    assert erst.guenstigstes.gesamtpreis.wert == 4590.0
    assert zweit.guenstigstes.gesamtpreis.wert == 1890.0


def test_debug_legt_screenshot_und_html_ab(hotel, tmp_path, monkeypatch):
    from nordlicht_rates import config

    monkeypatch.setenv("NORDLICHT_DEBUG_DIR", str(tmp_path))
    config.einstellungen.cache_clear()
    try:
        zeit = zeitraum(ANREISE, naechte=1)
        ergebnis = _lauf(
            hole_preise(f"{hotel}/booking", zeit, debug=True, cache_nutzen=False)
        )
        assert ergebnis.debug.get("screenshot"), ergebnis.debug
        bilder = list(tmp_path.glob("*.png"))
        dumps = list(tmp_path.glob("*.html"))
        assert bilder and bilder[0].stat().st_size > 1000
        assert dumps and "Booking" in dumps[0].read_text(encoding="utf-8")
    finally:
        config.einstellungen.cache_clear()
