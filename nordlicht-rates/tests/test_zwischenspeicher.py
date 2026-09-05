"""Der Zwischenspeicher und sein Notausgang.

Sechs Stunden Gueltigkeit sind gegenueber kleinen Buchungsmaschinen richtig -
sie sind aber auch der Grund, warum sich eine Korrektur an der Auswertung
zunaechst gar nicht nachpruefen laesst: Der Dienst startet neu, der neue Code
laeuft, und zurueck kommt trotzdem das Ergebnis der alten Fassung.
"""

import asyncio

import pytest

from nordlicht_rates import abruf
from nordlicht_rates.browser import SeitenErgebnis
from nordlicht_rates.cache import TTLCache
from nordlicht_rates.dates import zeitraum


# Ein leeres Ergebnis wird bewusst nicht gespeichert - eine einmalige
# Stoerung soll nicht sechs Stunden lang als "ausgebucht" nachwirken. Fuer
# diese Tests braucht es also einen echten Treffer.
_TREFFER = {
    "rooms": [
        {
            "name": "Glas-Iglu",
            "description": "Iglu mit Glasdach",
            "price": {"currency": "EUR", "totalAmount": 1200},
        }
    ]
}


def _seite_mit_treffer(url):
    return SeitenErgebnis(
        url=url, end_url=url, status=200, html="",
        json_antworten=[
            {"url": url + "api", "status": 200, "daten": _TREFFER, "anfrage": None}
        ],
    )


@pytest.fixture(autouse=True)
def eigener_speicher(monkeypatch):
    """Die uebrige Suite laeuft mit abgeschaltetem Zwischenspeicher (TTL 0),
    damit sich Tests nicht gegenseitig Ergebnisse unterschieben. Hier ist er
    aber der Gegenstand - also bekommt jeder Test einen eigenen."""
    monkeypatch.setattr(abruf, "_CACHE", TTLCache(ttl_s=60))


def _zaehlender_browser(monkeypatch):
    aufrufe = []

    async def hole(self, url, **kwargs):
        aufrufe.append(url)
        return _seite_mit_treffer(url)

    async def stop(self):
        return None

    async def start(self):
        return None

    monkeypatch.setattr(abruf.Browser, "hole", hole)
    monkeypatch.setattr(abruf.Browser, "start", start)
    monkeypatch.setattr(abruf.Browser, "stop", stop)
    return aufrufe


def test_zweiter_abruf_kommt_aus_dem_speicher(monkeypatch):
    aufrufe = _zaehlender_browser(monkeypatch)
    zeit = zeitraum("2027-02-22", naechte=2)
    url = "https://speicher-1.example/"

    asyncio.run(abruf.hole_kategorien(url, zeit))
    vorher = len(aufrufe)
    zweites = asyncio.run(abruf.hole_kategorien(url, zeit))

    assert len(aufrufe) == vorher
    assert zweites.aus_cache is True


def test_frisch_fragt_neu_ab(monkeypatch):
    aufrufe = _zaehlender_browser(monkeypatch)
    zeit = zeitraum("2027-02-22", naechte=2)
    url = "https://speicher-2.example/"

    asyncio.run(abruf.hole_kategorien(url, zeit))
    vorher = len(aufrufe)
    frisches = asyncio.run(abruf.hole_kategorien(url, zeit, frisch=True))

    assert len(aufrufe) > vorher
    assert frisches.aus_cache is False


def test_frisch_schreibt_den_neuen_stand_zurueck(monkeypatch):
    """Sonst muesste jeder weitere Abruf ebenfalls frisch sein - und der
    Zwischenspeicher waere nach einer Korrektur dauerhaft nutzlos."""
    aufrufe = _zaehlender_browser(monkeypatch)
    zeit = zeitraum("2027-02-22", naechte=2)
    url = "https://speicher-3.example/"

    asyncio.run(abruf.hole_kategorien(url, zeit, frisch=True))
    vorher = len(aufrufe)
    danach = asyncio.run(abruf.hole_kategorien(url, zeit))

    assert len(aufrufe) == vorher
    assert danach.aus_cache is True
