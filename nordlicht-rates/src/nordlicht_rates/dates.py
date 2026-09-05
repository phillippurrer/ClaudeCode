"""Datums-Helfer fuer die Buchungsstrecken.

Buchungsmaschinen erwarten mal An-/Abreise, mal Anreise + Naechte. Hier wird
beides ineinander umgerechnet und streng validiert, damit ein Tippfehler im
Datum nicht erst als leeres Ergebnis der Buchungsseite auffaellt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Mehr als ein Jahr im Voraus oeffnen die wenigsten Haeuser ihre Raten; weiter
# entfernte Anfragen liefern sonst kommentarlos "kein Zimmer frei".
MAX_VORLAUF_TAGE = 500
MAX_NAECHTE = 30


class DatumsFehler(ValueError):
    """Ungueltige Datumsangabe - Meldung ist fuer den Nutzer gedacht."""


def parse_datum(wert: str, feld: str = "datum") -> date:
    """Liest ein Datum im Format JJJJ-MM-TT."""
    if isinstance(wert, date) and not isinstance(wert, datetime):
        return wert
    if not isinstance(wert, str) or not wert.strip():
        raise DatumsFehler(f"{feld} fehlt (erwartet JJJJ-MM-TT)")
    try:
        return datetime.strptime(wert.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise DatumsFehler(
            f"{feld}='{wert}' ist kein Datum im Format JJJJ-MM-TT"
        ) from None


@dataclass(frozen=True)
class Zeitraum:
    check_in: date
    check_out: date

    @property
    def naechte(self) -> int:
        return (self.check_out - self.check_in).days

    def als_dict(self) -> dict:
        return {
            "check_in": self.check_in.isoformat(),
            "check_out": self.check_out.isoformat(),
            "naechte": self.naechte,
        }


def zeitraum(
    check_in: str,
    check_out: str | None = None,
    naechte: int | None = None,
    *,
    heute: date | None = None,
) -> Zeitraum:
    """Baut den Zeitraum aus check_out ODER naechte.

    Genau eine der beiden Angaben muss gesetzt sein; sind beide da, muessen sie
    zueinander passen, sonst waere unklar, welche gilt.
    """
    anreise = parse_datum(check_in, "check_in")
    heute = heute or date.today()

    if check_out is None and naechte is None:
        raise DatumsFehler("check_out oder naechte angeben")

    if check_out is not None:
        abreise = parse_datum(check_out, "check_out")
        if naechte is not None and (abreise - anreise).days != naechte:
            raise DatumsFehler(
                f"check_out={abreise.isoformat()} und naechte={naechte} "
                f"widersprechen sich ({(abreise - anreise).days} Naechte)"
            )
    else:
        if naechte < 1:
            raise DatumsFehler(f"naechte={naechte} muss mindestens 1 sein")
        abreise = anreise + timedelta(days=naechte)

    if abreise <= anreise:
        raise DatumsFehler(
            f"check_out={abreise.isoformat()} liegt nicht nach "
            f"check_in={anreise.isoformat()}"
        )
    if (abreise - anreise).days > MAX_NAECHTE:
        raise DatumsFehler(
            f"{(abreise - anreise).days} Naechte ueberschreiten das Limit "
            f"von {MAX_NAECHTE}"
        )
    if anreise < heute:
        raise DatumsFehler(
            f"check_in={anreise.isoformat()} liegt in der Vergangenheit"
        )
    if (anreise - heute).days > MAX_VORLAUF_TAGE:
        raise DatumsFehler(
            f"check_in={anreise.isoformat()} liegt mehr als "
            f"{MAX_VORLAUF_TAGE} Tage in der Zukunft - so weit oeffnen "
            "die meisten Haeuser ihre Raten nicht"
        )
    return Zeitraum(anreise, abreise)


def formatiere(d: date, muster: str) -> str:
    """Formatiert ein Datum nach dem Muster einer Buchungsmaschine.

    Unterstuetzt die in engines.yaml verwendeten Kuerzel, damit dort kein
    strftime stehen muss.
    """
    muster_map = {
        "iso": "%Y-%m-%d",
        "dmy": "%d-%m-%Y",
        "dmy_punkt": "%d.%m.%Y",
        "dmy_slash": "%d/%m/%Y",
        "mdy_slash": "%m/%d/%Y",
        "ymd_kompakt": "%Y%m%d",
    }
    return d.strftime(muster_map.get(muster, muster))


# Schluesselpaare, unter denen Buchungsmaschinen den abgefragten Zeitraum in
# ihre Anfragen schreiben. Mews nutzt startUtc/endUtc, andere checkIn/checkOut.
_START_SCHLUESSEL = (
    "startutc", "start", "startdate", "checkin", "checkindate", "arrival",
    "arrivaldate", "from", "fromdate", "firsttimeunitstartutc", "datefrom",
)
_ENDE_SCHLUESSEL = (
    "endutc", "end", "enddate", "checkout", "checkoutdate", "departure",
    "departuredate", "to", "todate", "lasttimeunitstartutc", "dateto",
)
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _datum_aus(wert) -> date | None:
    if not isinstance(wert, str):
        return None
    treffer = _ISO.match(wert.strip())
    if not treffer:
        return None
    try:
        return date(*(int(t) for t in treffer.groups()))
    except ValueError:
        return None


def _sammle_zeitraum(daten, tiefe: int = 0) -> tuple[date | None, date | None]:
    if tiefe > 6:
        return None, None
    von = bis = None
    if isinstance(daten, dict):
        for schluessel, wert in daten.items():
            klein = str(schluessel).lower()
            if von is None and klein in _START_SCHLUESSEL:
                von = _datum_aus(wert)
            if bis is None and klein in _ENDE_SCHLUESSEL:
                bis = _datum_aus(wert)
        if von and bis:
            return von, bis
        for wert in daten.values():
            if isinstance(wert, (dict, list)):
                tiefer = _sammle_zeitraum(wert, tiefe + 1)
                von, bis = von or tiefer[0], bis or tiefer[1]
                if von and bis:
                    return von, bis
    elif isinstance(daten, list):
        for eintrag in daten[:20]:
            tiefer = _sammle_zeitraum(eintrag, tiefe + 1)
            von, bis = von or tiefer[0], bis or tiefer[1]
            if von and bis:
                return von, bis
    return von, bis


def anfrage_betrifft(anfrage: str | None, zeit: "Zeitraum") -> bool:
    """Fragt diese Anfrage nach unserem Zeitraum - oder nach einem anderen?

    Der Grund fuer diese Pruefung: Ein Mews-Distributor laedt zuerst mit
    seinen Vorgabedaten - ab heute - und fragt dafuer Verfuegbarkeit und
    Preise ab. Erst danach uebernimmt er die Daten aus dem Deeplink und fragt
    erneut. Mitgeschnitten werden beide Antworten.

    Wer sie zusammenwirft, erhaelt dieselbe Kategorie zweimal mit zwei
    Preisen - einmal Nebensaison, einmal Hochwinter. Fuer die Northern Lights
    Ranch waren das 270 EUR und 635 EUR pro Nacht fuer dieselbe Huette. Und
    weil der niedrigere Preis zuerst kommt, gewinnt er die Sortierung: Das
    Ergebnis waere weniger als die Haelfte des tatsaechlichen Preises
    gewesen, ohne dass irgendetwas nach einem Fehler ausgesehen haette.

    Nennt eine Anfrage keinen Zeitraum, gilt sie als zugehoerig - lieber eine
    Antwort zu viel betrachten als eine gebrauchte verwerfen.
    """
    if not anfrage:
        return True
    try:
        daten = json.loads(anfrage)
    except (TypeError, ValueError):
        return True
    von, bis = _sammle_zeitraum(daten)
    if not von or not bis:
        return True
    # Ueberschneidung genuegt: Kalenderabfragen decken oft einen ganzen Monat
    # ab, in dem unser Aufenthalt nur ein paar Tage ausmacht.
    return von <= zeit.check_out and bis >= zeit.check_in
