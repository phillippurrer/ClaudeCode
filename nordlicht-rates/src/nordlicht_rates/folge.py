"""Findet die eigentliche Buchungsmaschine, die in eine Hotelseite eingebettet ist.

Hintergrund: Viele Haeuser binden ihre Buchungsstrecke nur als Widget ein.
theranch.fi/check-availability/ zeigt selbst keine Preise - die Zimmer kommen
aus einem Mews-Distributor, der unter app.mews.com/distributor/<GUID> lebt.
Wer nur die Hotelseite laedt, sieht deshalb nie einen Preis.

Statt den Umweg ueber die Widget-Einbettung zu gehen, wird die GUID aus dem
Markup gefischt und der Distributor direkt geoeffnet - mit Datum und
Personenzahl im Deeplink. Das ist auch der Grund, warum das reine Abklopfen
der Mews-API zuvor in Sackgassen lief: Ohne ausgefuehrtes JavaScript gibt der
Distributor nichts heraus, mit Browser dagegen sofort.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

# Standard-UUID, wie Mews sie fuer Distributor-Konfigurationen vergibt.
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# Fall 1: die Distributor-Adresse steht wortwoertlich im Markup.
_MEWS_DIREKT = re.compile(
    r"(?:app\.mews\.com|booking\.mews\.com)/distributor/(" + _UUID + r")", re.I
)
# Fall 2: nur die GUID steht da, meist als data-Attribut oder in der Config.
# Der Schluessel kann eine ganze Liste einleiten ("configurationIds": [a, b, c]),
# deshalb wird ein Fenster dahinter aufgemacht und daraus jede UUID gelesen -
# ein Regex, der nur die erste Zuweisung greift, verliert die uebrigen.
_MEWS_GUID_SCHLUESSEL = re.compile(
    r"(?:configurationIds?|mewsDistributorConfigurationId|distributor-id|"
    r"data-mews-configuration|configuration_id)",
    re.I,
)
_FENSTER = 400
# Fall 3: Notnagel - irgendeine UUID auf einer Seite, die klar Mews nutzt.
_UUID_IRGENDWO = re.compile(_UUID, re.I)

MAX_ZIELE = 3


def finde_mews_distributoren(html: str) -> list[str]:
    """Liefert die Distributor-GUIDs einer Hotelseite, beste Quelle zuerst.

    Ein Haus kann mehrere Konfigurationen haben (etwa Huetten und Zimmer
    getrennt), deshalb eine Liste - der Aufrufer klappert sie ab und fuegt die
    Ergebnisse zusammen.
    """
    if not html:
        return []
    gefunden: list[str] = []

    def aufnehmen(werte):
        for wert in werte:
            klein = wert.lower()
            if klein not in gefunden:
                gefunden.append(klein)

    aufnehmen(_MEWS_DIREKT.findall(html))
    for treffer in _MEWS_GUID_SCHLUESSEL.finditer(html):
        fenster = html[treffer.end(): treffer.end() + _FENSTER]
        aufnehmen(_UUID_IRGENDWO.findall(fenster))
    if not gefunden and "mews" in html.lower():
        # Nur wenn die Seite sonst nichts hergibt: Alle UUIDs einsammeln.
        # Riskant genug, um es auf MAX_ZIELE zu deckeln.
        aufnehmen(_UUID_IRGENDWO.findall(html))
    return gefunden[:MAX_ZIELE]


def mews_distributor_url(guid: str) -> str:
    return f"https://app.mews.com/distributor/{guid}"


# Buchungsstrecken werden haeufig einfach als iframe eingehaengt. Der Frame
# zeigt dann auf die Maschine - erkennbar an diesen Wortteilen im Pfad.
_IFRAME = re.compile(r"<iframe[^>]+src\s*=\s*[\"']([^\"']+)[\"']", re.I)
_BUCHUNGS_WORT = re.compile(
    r"(book|booking|reserv|availab|distributor|rooms|varaa|huone)", re.I
)


def finde_buchungs_frames(html: str, basis_url: str) -> list[str]:
    """iframes, die auf eine Buchungsstrecke zeigen - relativ aufgeloest."""
    if not html or not basis_url:
        return []
    gefunden: list[str] = []
    for roh in _IFRAME.findall(html):
        if roh.startswith(("data:", "about:", "javascript:")):
            continue
        voll = urljoin(basis_url, roh)
        if not _BUCHUNGS_WORT.search(urlparse(voll).path + "?" + (urlparse(voll).query or "")):
            continue
        if voll not in gefunden and voll.rstrip("/") != basis_url.rstrip("/"):
            gefunden.append(voll)
    return gefunden


def folge_ziele(html: str, engine_id: str, basis_url: str = "") -> list[str]:
    """Weiterfuehrende Buchungs-URLs aus dem Markup einer Hotelseite.

    Wird nur benutzt, wenn der erste Abruf nichts gefunden hat - eine Seite,
    die selbst schon Preise zeigt, braucht keinen Umweg.
    """
    ziele: list[str] = []
    # Mews auch dann versuchen, wenn generisch erkannt wurde: Die Hotelseite
    # laeuft ja auf ihrer eigenen Domain, nicht auf app.mews.com.
    if engine_id in ("generic", "mews"):
        ziele += [mews_distributor_url(g) for g in finde_mews_distributoren(html)]

    if engine_id == "generic" and html:
        # Weitere Buchungsmaschinen, die als Widget eingebettet werden.
        for muster in (
            r"https://[\w.-]*upperbooking\.com/[\w/-]+",
            r"https://booking\.profitroom\.com/[\w/-]+",
            r"https://be\.synxis\.com/[\w?=&.-]+",
            r"https://hotels\.cloudbeds\.com/[\w/-]+",
            r"https://[\w.-]*direct-book\.com/[\w/-]+",
        ):
            for treffer in re.findall(muster, html, re.I):
                if treffer not in ziele:
                    ziele.append(treffer)
        for frame in finde_buchungs_frames(html, basis_url):
            if frame not in ziele:
                ziele.append(frame)
    return ziele[:MAX_ZIELE]
