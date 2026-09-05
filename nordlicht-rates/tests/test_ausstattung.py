"""Ausstattung und Groesse - der eigentliche Entscheidungsgrund bei Glashuetten.

Preis allein trennt Superior und Deluxe nicht brauchbar; ob ein privater
Whirlpool dabei ist, schon.
"""

import pytest

from nordlicht_rates.ausstattung import finde_groesse_m2, finde_merkmale


@pytest.mark.parametrize(
    "text,erwartet",
    [
        ("25 m², private outdoor hot tub available 24/7", "privater Whirlpool"),
        ("Own sauna and hot tub", "eigene Sauna"),
        ("heated glass roof over the bed", "Glasdach"),
        ("Zimmer mit Kamin und Terrasse", "Kamin"),
        ("oma sauna ja poreallas", "eigene Sauna"),
        ("Lasikatto ja takka", "Glasdach"),
        ("Breakfast included", "Fruehstueck inklusive"),
    ],
)
def test_merkmale_mehrsprachig(text, erwartet):
    """Dieselbe Buchungsmaschine liefert je nach Sprache Englisch oder Finnisch."""
    assert erwartet in finde_merkmale(text)


def test_deluxe_und_superior_unterscheiden_sich():
    superior = finde_merkmale("Sky View Cabin Superior, 25 m2, heated glass roof")
    deluxe = finde_merkmale(
        "Sky View Cabin Deluxe, 25 m2 with private outdoor hot tub 24/7, glass roof"
    )
    assert "Glasdach" in superior and "privater Whirlpool" not in superior
    assert "privater Whirlpool" in deluxe


def test_ultimate_hat_sauna_und_whirlpool():
    merkmale = finde_merkmale("35 m2, own sauna and private hot tub, fireplace")
    assert {"privater Whirlpool", "eigene Sauna", "Kamin"} <= set(merkmale)


def test_merkmale_aus_mehreren_texten():
    """Name, Beschreibung und amenities-Liste werden zusammen betrachtet."""
    merkmale = finde_merkmale(
        "Aurora Cabin", "25 m2 cabin", "Glass roof, Private hot tub"
    )
    assert {"Glasdach", "privater Whirlpool"} <= set(merkmale)


def test_reihenfolge_ist_stabil():
    """Zwei Abrufe desselben Zimmers muessen vergleichbar bleiben."""
    a = finde_merkmale("hot tub, sauna, glass roof")
    b = finde_merkmale("glass roof, sauna, hot tub")
    assert a == b


@pytest.mark.parametrize(
    "text,erwartet",
    [
        ("25 m²", 25.0),
        ("25 m2 with hot tub", 25.0),
        ("35 sqm", 35.0),
        ("28 neliötä", 28.0),
        ("Zimmergröße 42 qm", 42.0),
        ("16,5 m²", 16.5),
    ],
)
def test_groesse_schreibweisen(text, erwartet):
    assert finde_groesse_m2(text) == erwartet


def test_groesste_angabe_gewinnt():
    """'25 m² Wohnraum, 4 m² Bad' ist eine 25-m²-Kategorie."""
    assert finde_groesse_m2("25 m² Wohnraum, 4 m² Bad") == 25.0


def test_unsinnige_groessen_werden_verworfen():
    """Grundstuecksflaechen und Badezimmermasse sind keine Zimmergroessen."""
    assert finde_groesse_m2("Anlage auf 12000 m² Waldgrundstück") is None
    assert finde_groesse_m2("2 m² Dusche") is None
    assert finde_groesse_m2("keine Angabe") is None


def test_sauna_der_unterkunft_gegen_gemeinschaftssauna():
    """Der Unterschied, auf den es beim Vergleich ankommt: Halo schreibt
    'private glass igloo with Finnish Sauna' - das gehoert zur Huette.
    Northern Lights Village schreibt 'relax in a traditional Finnish sauna' -
    das ist die Sauna des Hauses und darf nicht als eigene durchgehen."""
    eigene = finde_merkmale(
        "Accommodation in a private glass igloo with Finnish Sauna"
    )
    gemeinsam = finde_merkmale(
        "You can relax in a traditional Finnish sauna and soak in hot tubs."
    )
    assert "eigene Sauna" in eigene
    assert "eigene Sauna" not in gemeinsam
