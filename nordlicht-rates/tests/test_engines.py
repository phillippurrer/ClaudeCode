"""Engine-Erkennung und Deeplink-Bau."""

import pytest

from nordlicht_rates.dates import zeitraum
from nordlicht_rates.engines import (
    alle_engines,
    baue_urls,
    erkenne_engine,
    rate_hotel_id,
)

ZEIT = zeitraum("2027-02-14", naechte=3, heute=__import__("datetime").date(2026, 9, 5))


@pytest.mark.parametrize(
    "url,erwartet",
    [
        ("https://book.alion.com", "webhotelier"),
        ("https://www.scandichotels.com/hotels/norway/tromso/ishavshotel", "scandic"),
        ("https://www.strawberryhotels.com/hotels/norway/tromso/clarion", "strawberry"),
        ("https://www.nordicchoicehotels.no/hotell/norge/tromso/", "strawberry"),
        ("https://www.thonhotels.com/hoteller/norge/tromso/", "thon"),
        ("https://app.mews.com/distributor/abc123", "mews"),
        ("https://hotels.cloudbeds.com/reservation/xyz", "cloudbeds"),
        ("https://be.synxis.com/?hotel=1234", "synxis"),
        ("https://booking.profitroom.com/haus", "profitroom"),
        ("https://www.sorrisniva.no/booking", "generic"),
    ],
)
def test_erkennung_ueber_host(url, erwartet):
    assert erkenne_engine(url).id == erwartet


def test_erkennung_ueber_seitenmarker():
    """Eigene Domain, fremde Buchungsmaschine - erst das HTML verraet sie."""
    html = '<html><script src="/assets/siteminder-booking.js"></script></html>'
    assert erkenne_engine("https://hotel-lofoten.no/book", html).id == "siteminder"


def test_deeplink_enthaelt_daten_und_belegung():
    engine = erkenne_engine("https://book.alion.com")
    url = baue_urls(engine, "https://book.alion.com", ZEIT, adults=3, children=1)[0]
    assert url.startswith("https://book.alion.com/results?")
    for teil in ("checkin=2027-02-14", "nights=3", "adults=3", "children=1"):
        assert teil in url


def test_kein_dreifach_slash_im_schema():
    """Regression: eine leere {pfad}-Ersetzung hatte https:/// erzeugt."""
    for url in ("https://book.alion.com", "https://book.alion.com/"):
        for gebaut in baue_urls(erkenne_engine(url), url, ZEIT):
            assert "https:///" not in gebaut
            assert gebaut.startswith("https://")


def test_originalurl_ist_immer_letzter_kandidat():
    """Wenn kein Deeplink greift, muss die unveraenderte Seite drankommen."""
    url = "https://www.sorrisniva.no/booking"
    kandidaten = baue_urls(erkenne_engine(url), url, ZEIT)
    assert kandidaten[-1] == url
    assert len(kandidaten) > 1


def test_hotel_id_wird_aus_pfad_geraten():
    url = "https://www.scandichotels.com/hotels/norway/tromso/scandic-ishavshotel"
    assert rate_hotel_id(url) == "scandic-ishavshotel"
    assert "hotelId=scandic-ishavshotel" in baue_urls(erkenne_engine(url), url, ZEIT)[0]


def test_hotel_id_explizit_schlaegt_raten():
    url = "https://www.thonhotels.com/hoteller/norge/tromso/thon-hotel-polar/"
    gebaut = baue_urls(erkenne_engine(url), url, ZEIT, hotel_id="TPOL")[0]
    assert "hotel=TPOL" in gebaut


def test_alle_engines_haben_pflichtfelder():
    ids = set()
    for engine in alle_engines():
        assert engine.id and engine.name
        assert engine.id not in ids, f"doppelte Engine-ID {engine.id}"
        ids.add(engine.id)
        assert engine.selektoren.get("karte"), f"{engine.id} ohne Kartenselektor"
    assert "generic" in ids, "Auffangnetz fehlt"
