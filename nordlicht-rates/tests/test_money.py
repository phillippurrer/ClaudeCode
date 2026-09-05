"""Preisparser - die nordischen Schreibweisen sind der eigentliche Testfall."""

import pytest

from nordlicht_rates.money import (
    Betrag,
    PreisFehler,
    erkenne_waehrung,
    ist_plausibler_zimmerpreis,
    parse_alle_preise,
    parse_preis,
    pro_nacht,
)


@pytest.mark.parametrize(
    "text,land,wert,waehrung",
    [
        ("1 234 kr", "no", 1234.0, "NOK"),          # schmales Leerzeichen NO
        ("1 234 kr", "se", 1234.0, "SEK"),
        ("45.900 kr.", "is", 45900.0, "ISK"),       # Punkt = Tausender (IS)
        ("1 234,50 EUR", None, 1234.50, "EUR"),     # Komma = Dezimal
        ("1,234.50 NOK", None, 1234.50, "NOK"),     # engl. Schreibweise
        ("NOK 2 495", None, 2495.0, "NOK"),
        ("1 899:-", "se", 1899.0, "SEK"),           # schwedisches Suffix
        ("€ 189", "fi", 189.0, "EUR"),
        ("1.234.567 ISK", "is", 1234567.0, "ISK"),  # mehrfacher Tausender
        ("kr 1 250,00", "no", 1250.0, "NOK"),
        ("2 400", None, 2400.0, None),              # ohne Waehrungsangabe
        ("1 890 kr", None, 1890.0, "kr"),           # Krone, Land unbekannt
    ],
)
def test_parse_preis(text, land, wert, waehrung):
    betrag = parse_preis(text, land)
    assert betrag.wert == pytest.approx(wert)
    assert betrag.waehrung == waehrung


def test_dezimal_vor_tausender_nicht_verwechseln():
    """1.234 ist Tausender, 1,50 ist Dezimal - der haeufigste Faktor-1000-Fehler."""
    assert parse_preis("1.234").wert == 1234.0
    assert parse_preis("1,50").wert == 1.50
    assert parse_preis("12,5").wert == 12.5


def test_blankes_kr_bleibt_unspezifisch_statt_geraten():
    """Lieber 'kr' als eine falsch geratene Waehrung - und keinesfalls EUR."""
    assert erkenne_waehrung("1 234 kr", None) == "kr"
    assert erkenne_waehrung("1 234 kr", "no") == "NOK"
    assert erkenne_waehrung("1 234 kr", "is") == "ISK"


def test_kurtaxe_faellt_auch_ohne_landkenntnis_raus():
    """Regression: 25 kr galt als plausibel, weil ohne Land die EUR-Spanne
    (ab 25) griff - eine Kurtaxe wurde so zum guenstigsten 'Zimmer'."""
    assert not ist_plausibler_zimmerpreis(Betrag(25, "kr"))
    assert ist_plausibler_zimmerpreis(Betrag(1890, "kr"))


def test_parse_preis_ohne_zahl():
    with pytest.raises(PreisFehler):
        parse_preis("ausgebucht")


def test_alle_preise_bei_streichpreis():
    betraege = parse_alle_preise("statt 2 400 kr jetzt 1 900 kr", "no")
    assert [b.wert for b in betraege] == [2400.0, 1900.0]
    assert all(b.waehrung == "NOK" for b in betraege)


def test_plausibilitaet_haengt_an_der_waehrung():
    """45.000 ISK ist ein normaler Zimmerpreis, 45.000 EUR nicht."""
    assert ist_plausibler_zimmerpreis(Betrag(45000, "ISK"))
    assert not ist_plausibler_zimmerpreis(Betrag(45000, "EUR"))
    assert not ist_plausibler_zimmerpreis(Betrag(25, "NOK"))   # Kurtaxe


def test_obergrenze_skaliert_mit_naechten():
    """Ein Gesamtpreis fuer 10 Naechte darf hoeher liegen als fuer eine."""
    zehn_naechte = Betrag(45_000, "EUR")
    assert not ist_plausibler_zimmerpreis(zehn_naechte, naechte=1)
    assert ist_plausibler_zimmerpreis(zehn_naechte, naechte=10)


def test_pro_nacht():
    assert pro_nacht(Betrag(4590, "NOK"), 3).wert == pytest.approx(1530.0)
    with pytest.raises(PreisFehler):
        pro_nacht(Betrag(100, "EUR"), 0)
