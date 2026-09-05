"""Zeitraumlogik - falsche Daten sollen sofort auffallen, nicht als leeres
Ergebnis der Buchungsseite."""

from datetime import date

import pytest

from nordlicht_rates.dates import anfrage_betrifft, DatumsFehler, formatiere, parse_datum, zeitraum

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


class TestAnfrageBetrifft:
    """Der teuerste Fehler dieser Sorte kommt ohne Fehlermeldung.

    Ein Mews-Distributor fragt beim Laden zuerst mit seinen Vorgabedaten ab -
    ab heute - und uebernimmt erst danach die Daten aus dem Deeplink.
    Mitgeschnitten werden beide Antworten. Ungefiltert stand die Northern
    Lights Ranch mit 270 EUR und mit 635 EUR pro Nacht fuer dieselbe Huette in
    der Liste, und der Nebensaisonpreis gewann die Sortierung.
    """

    def zeit(self):
        return zeitraum("2027-02-22", naechte=2)

    def test_anfrage_zum_falschen_zeitraum_zaehlt_nicht(self):
        vorgabe = ('{"serviceIds":["x"],"startUtc":"2026-09-04T21:00:00.000Z",'
                   '"endUtc":"2026-11-03T22:00:00.000Z"}')
        assert anfrage_betrifft(vorgabe, self.zeit()) is False

    def test_anfrage_zum_richtigen_zeitraum_zaehlt(self):
        echt = ('{"startUtc":"2027-02-22T00:00:00.000Z",'
                '"endUtc":"2027-02-24T00:00:00.000Z"}')
        assert anfrage_betrifft(echt, self.zeit()) is True

    def test_kalenderabfrage_ueber_den_ganzen_monat_zaehlt(self):
        """Ueberschneidung genuegt - sonst faellt getCalendarData heraus."""
        monat = '{"startUtc":"2027-02-01","endUtc":"2027-03-01"}'
        assert anfrage_betrifft(monat, self.zeit()) is True

    def test_andere_schluesselnamen_werden_erkannt(self):
        assert anfrage_betrifft(
            '{"checkIn":"2026-12-01","checkOut":"2026-12-03"}', self.zeit()
        ) is False
        assert anfrage_betrifft(
            '{"arrival":"2027-02-23","departure":"2027-02-25"}', self.zeit()
        ) is True

    def test_verschachtelte_angabe_wird_gefunden(self):
        tief = '{"query":{"filter":{"startDate":"2026-09-01","endDate":"2026-09-05"}}}'
        assert anfrage_betrifft(tief, self.zeit()) is False

    def test_ohne_anfrage_wird_nichts_verworfen(self):
        """Ein GET hat keinen Rumpf. Eine Antwort wegzuwerfen, ueber die man
        nichts weiss, waere schlechter als sie mitzunehmen."""
        assert anfrage_betrifft(None, self.zeit()) is True
        assert anfrage_betrifft("", self.zeit()) is True

    def test_unlesbare_anfrage_wird_nicht_verworfen(self):
        assert anfrage_betrifft("nicht=json&sondern=formular", self.zeit()) is True

    def test_anfrage_ohne_datum_wird_nicht_verworfen(self):
        assert anfrage_betrifft('{"serviceIds":["x"]}', self.zeit()) is True

    def test_angrenzender_zeitraum_zaehlt_noch(self):
        """Abreisetag und Anreisetag duerfen zusammenfallen."""
        assert anfrage_betrifft(
            '{"startUtc":"2027-02-20","endUtc":"2027-02-22"}', self.zeit()
        ) is True
