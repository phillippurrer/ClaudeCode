"""Erkennt die Buchungsmaschine hinter einer URL und baut den Deeplink.

Der Deeplink ist der eigentliche Trick dieses Moduls: Fast jede Buchungs-
maschine akzeptiert An-/Abreise als Query-Parameter und springt damit direkt
auf die Ergebnisliste. Damit entfaellt das Klicken durch den Kalender - der
mit Abstand bruechigste Teil jeder Buchungsautomatisierung.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse, urlsplit

from .config import lade_config
from .dates import Zeitraum, formatiere


class _DatumsFormatter(string.Formatter):
    """Erlaubt {check_in:iso} und {check_in:dmy_punkt} in engines.yaml."""

    def format_field(self, value, format_spec):
        if isinstance(value, date):
            return formatiere(value, format_spec or "iso")
        return super().format_field(value, format_spec)

    def get_value(self, key, args, kwargs):
        # Unbekannte Platzhalter leer lassen statt zu werfen: ein fehlendes
        # {hotel_id} soll den Deeplink nicht komplett verhindern.
        if isinstance(key, str):
            return kwargs.get(key, "")
        return super().get_value(key, args, kwargs)


_FORMATTER = _DatumsFormatter()


@dataclass
class Engine:
    id: str
    name: str
    deeplink: str | None
    deeplink_kandidaten: list[str]
    json_pfade: list[str]
    selektoren: dict
    land: str | None
    geprueft: bool
    hinweis: str | None

    @property
    def ist_generisch(self) -> bool:
        return self.id == "generic"


def _als_engine(roh: dict) -> Engine:
    return Engine(
        id=roh["id"],
        name=roh.get("name", roh["id"]),
        deeplink=roh.get("deeplink"),
        deeplink_kandidaten=roh.get("deeplink_kandidaten") or [],
        json_pfade=roh.get("json_pfade") or [],
        selektoren=roh.get("selektoren") or {},
        land=roh.get("land"),
        geprueft=bool(roh.get("geprueft", False)),
        hinweis=(roh.get("hinweis") or "").strip() or None,
    )


def alle_engines() -> list[Engine]:
    return [_als_engine(e) for e in lade_config()["engines"]]


def engine_nach_id(engine_id: str) -> Engine | None:
    for engine in alle_engines():
        if engine.id == engine_id:
            return engine
    return None


def erkenne_engine(url: str, seiteninhalt: str | None = None) -> Engine:
    """Waehlt die Engine anhand des Hosts und optional des Seiteninhalts.

    Der Seiteninhalt kommt erst nach dem ersten Laden dazu; deshalb ist die
    Erkennung zweistufig - grob ueber den Host, fein ueber Marker im HTML.
    """
    host = (urlparse(url).hostname or "").lower()
    engines = alle_engines()
    generisch = next((e for e in engines if e.ist_generisch), None)

    for roh, engine in zip(lade_config()["engines"], engines):
        if engine.ist_generisch:
            continue
        muster = (roh.get("erkennung") or {}).get("host_regex")
        if muster and re.search(muster, host):
            return engine

    if seiteninhalt:
        klein = seiteninhalt.lower()
        for roh, engine in zip(lade_config()["engines"], engines):
            if engine.ist_generisch:
                continue
            for marker in (roh.get("erkennung") or {}).get("seiten_marker", []):
                if marker.lower() in klein:
                    return engine

    if generisch is None:
        raise LookupError("engines.yaml hat keinen 'generic'-Eintrag")
    return generisch


def _basis_und_pfad(url: str) -> tuple[str, str]:
    teile = urlsplit(url)
    if not teile.scheme:
        teile = urlsplit("https://" + url)
    basis = f"{teile.scheme}://{teile.netloc}"
    pfad = teile.path.strip("/")
    return basis, pfad


def rate_hotel_id(url: str) -> str:
    """Zieht eine Hotel-Kennung aus der URL, falls der Nutzer keine angibt.

    Ketten-URLs sehen aus wie /hotels/norway/tromso/scandic-ishavshotel -
    das letzte Pfadsegment ist die brauchbarste Vermutung.
    """
    _, pfad = _basis_und_pfad(url)
    segmente = [s for s in pfad.split("/") if s and not s.isdigit()]
    return segmente[-1] if segmente else ""


def _entdopple(url: str) -> str:
    """Entfernt doppelte Slashes im Pfad, ohne das https:// anzutasten.

    Sie entstehen, wenn eine Vorlage {basis}/{pfad} nutzt und {pfad} leer ist.
    """
    teile = urlsplit(url)
    pfad = re.sub(r"//+", "/", teile.path)
    neu = f"{teile.scheme}://{teile.netloc}{pfad}"
    if teile.query:
        neu += f"?{teile.query}"
    if teile.fragment:
        neu += f"#{teile.fragment}"
    return neu


def baue_urls(
    engine: Engine,
    url: str,
    zeit: Zeitraum,
    *,
    adults: int = 2,
    children: int = 0,
    zimmer: int = 1,
    hotel_id: str | None = None,
) -> list[str]:
    """Liefert die anzusteuernden URLs, beste zuerst.

    Die Original-URL steht immer am Ende: Wenn kein Deeplink greift, ist die
    unveraenderte Seite die letzte Chance (dort steht oft schon ein
    Ab-Preis).
    """
    basis, pfad = _basis_und_pfad(url)
    werte = {
        "basis": basis,
        "pfad": pfad,
        "check_in": zeit.check_in,
        "check_out": zeit.check_out,
        "naechte": zeit.naechte,
        "adults": adults,
        "children": children,
        "zimmer": zimmer,
        "hotel_id": hotel_id or rate_hotel_id(url),
    }

    vorlagen = [v for v in ([engine.deeplink] + engine.deeplink_kandidaten) if v]
    gebaut: list[str] = []
    for vorlage in vorlagen:
        try:
            fertig = _FORMATTER.format(vorlage, **werte)
        except (KeyError, ValueError, IndexError):
            continue
        fertig = _entdopple(fertig)
        if fertig not in gebaut:
            gebaut.append(fertig)

    if url not in gebaut:
        gebaut.append(url)
    return gebaut
