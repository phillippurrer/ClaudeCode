"""Zeitraumlogik - falsche Daten sollen sofort auffallen, nicht als leeres
Ergebnis der Buchungsseite."""

from datetime import date

import pytest

from nordlicht_rates.dates import DatumsFehler, formatiere, parse_datum, zeitraum

HEUTE = date(2026, 9, 5)


def test_naechte_ergibt_check_out():
    z = zeitraum("2027-02-14", naechte=3, heute=HEUTE)
    assert z.check_out == date(2027, 2, 17)
    assert z.naechte == 3
    assert z.als_dict()["check_out"] == "2027-02-17"


def test_check_out_ergibt_naechte():
    assert zeitraum("2027-02-14", "2027-02-17", heute=HEUTE).naechte == 3


def test_widerspruch_wird_gemeldet():
    """Beides angeben ist erlaubt - aber nur, wenn es zusammenpasst."""
    with pytest.raises(DatumsFehler, match="widersprechen"):
        zeitraum("2027-02-14", "2027-02-17", naechte=5, heute=HEUTE)


@pytest.mark.parametrize(
    "args,kwargs,muster",
    [
        (("2027-02-14",), {}, "check_out oder naechte"),
        (("14.02.2027",), {"naechte": 2}, "JJJJ-MM-TT"),
        (("2026-01-01",), {"naechte": 2}, "Vergangenheit"),
        (("2027-02-14", "2027-02-14"), {}, "liegt nicht nach"),
        (("2027-02-14",), {"naechte": 60}, "Limit"),
        (("2029-02-14",), {"naechte": 2}, "Zukunft"),
    ],
)
def test_ungueltige_eingaben(args, kwargs, muster):
    with pytest.raises(DatumsFehler, match=muster):
        zeitraum(*args, heute=HEUTE, **kwargs)


def test_formatiere_kuerzel():
    tag = date(2027, 2, 14)
    assert formatiere(tag, "iso") == "2027-02-14"
    assert formatiere(tag, "dmy_punkt") == "14.02.2027"
    assert formatiere(tag, "ymd_kompakt") == "20270214"


def test_parse_datum_akzeptiert_date():
    assert parse_datum(date(2027, 2, 14)) == date(2027, 2, 14)
