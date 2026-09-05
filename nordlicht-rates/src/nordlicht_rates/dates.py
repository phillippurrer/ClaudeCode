"""Datums-Helfer fuer die Buchungsstrecken.

Buchungsmaschinen erwarten mal An-/Abreise, mal Anreise + Naechte. Hier wird
beides ineinander umgerechnet und streng validiert, damit ein Tippfehler im
Datum nicht erst als leeres Ergebnis der Buchungsseite auffaellt.
"""

from __future__ import annotations

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
