"""Buchungsmaschinen, die Name und Preis getrennt ausliefern.

Mews - und damit die Northern Lights Ranch - fuehrt Zimmerkategorien und
Preise in eigenen Listen, verbunden ueber eine Kennung. Ein Sucher, der
beides im selben Objekt erwartet, findet dort nichts, obwohl alle Daten da
sind. Genau daran scheiterte der erste Live-Lauf.
"""

import pytest

from nordlicht_rates.extract import angebote_aus_json, angebote_verknuepft, struktur

# Aufbau, wie ihn eine Mews-artige Distributor-Antwort hat.
MEWS = {
    "RoomCategories": [
        {"Id": "cat-1", "Name": "Sky View Cabin Superior",
         "Description": "25 m2, heated glass roof over the bed"},
        {"Id": "cat-2", "Name": "Sky View Cabin Deluxe",
         "Description": "25 m2 with private outdoor hot tub available 24/7"},
        {"Id": "cat-3", "Name": "Sky View Cabin Ultimate",
         "Description": "35 m2, own sauna and private hot tub"},
    ],
    "RoomCategoryPrices": [
        {"RoomCategoryId": "cat-1", "Price": {"Currency": "EUR", "Value": 1430}},
        {"RoomCategoryId": "cat-2", "Price": {"Currency": "EUR", "Value": 1980}},
        {"RoomCategoryId": "cat-3", "Price": {"Currency": "EUR", "Value": 2450}},
    ],
}


def test_einfacher_sucher_findet_hier_nichts():
    """Belegt, warum es die Verknuepfung ueberhaupt braucht."""
    assert angebote_aus_json(MEWS, naechte=2) == []


def test_verknuepfung_findet_alle_kategorien():
    nach_name = {k.name: k for k in angebote_verknuepft(MEWS, naechte=2)}
    assert set(nach_name) == {
        "Sky View Cabin Superior", "Sky View Cabin Deluxe",
        "Sky View Cabin Ultimate",
    }
    assert nach_name["Sky View Cabin Deluxe"].preis_gesamt.wert == 1980
    assert nach_name["Sky View Cabin Deluxe"].preis_gesamt.waehrung == "EUR"


def test_ausstattung_kommt_aus_der_kategoriebeschreibung():
    """Die Beschreibung steht im Kategorie-Objekt, der Preis woanders -
    beim Zusammenfuehren darf sie nicht verlorengehen."""
    nach_name = {k.name: k for k in angebote_verknuepft(MEWS, naechte=2)}
    superior = nach_name["Sky View Cabin Superior"]
    deluxe = nach_name["Sky View Cabin Deluxe"]
    assert "privater Whirlpool" not in superior.ausstattung
    assert "privater Whirlpool" in deluxe.ausstattung
    assert deluxe.groesse_m2 == 25.0
    assert "eigene Sauna" in nach_name["Sky View Cabin Ultimate"].ausstattung


def test_nachtpreise_werden_summiert():
    """Zwei Betraege bei zwei Naechten sind die Aufschluesselung pro Nacht.
    Ohne Summierung ginge der Nachtpreis als Gesamtpreis durch - ein Fehler
    um den Faktor der Naechtezahl."""
    daten = {
        "categories": [{"id": "a", "name": "Aurora Cabin"}],
        "prices": [
            {"categoryId": "a", "amount": {"currency": "EUR", "value": 715}},
            {"categoryId": "a", "amount": {"currency": "EUR", "value": 715}},
        ],
    }
    k = angebote_verknuepft(daten, naechte=2)[0]
    assert k.preis_gesamt.wert == 1430
    assert k.preis_pro_nacht.wert == 715
    assert "Summe aus 2 Nachtpreisen" in k.zimmerhinweis


def test_einzelpreis_bleibt_einzelpreis():
    """Ein Betrag bei zwei Naechten ist der Gesamtpreis, nicht die Haelfte."""
    daten = {
        "categories": [{"id": "a", "name": "Aurora Cabin"}],
        "prices": [{"categoryId": "a", "amount": {"currency": "EUR", "value": 1430}}],
    }
    k = angebote_verknuepft(daten, naechte=2)[0]
    assert k.preis_gesamt.wert == 1430


def test_ohne_kennungen_kein_ergebnis():
    assert angebote_verknuepft({"rooms": ["a", "b"]}, naechte=1) == []
    assert angebote_verknuepft([], naechte=1) == []


def test_unplausible_betraege_fliegen_raus():
    daten = {
        "categories": [{"id": "a", "name": "Zimmer"}],
        "prices": [{"categoryId": "a", "amount": {"currency": "EUR", "value": 3}}],
    }
    assert angebote_verknuepft(daten, naechte=1) == []


def test_struktur_beschreibt_den_aufbau_kompakt():
    """Fuer die Fehlersuche aus der Ferne: Schluesselnamen statt Datenmenge."""
    kurz = struktur(MEWS)
    assert "RoomCategories" in kurz and "RoomCategoryPrices" in kurz
    assert "x3" in kurz          # Listenlaenge wird genannt
    assert "1430" not in kurz    # aber keine Werte
    assert len(kurz) < 600


def test_struktur_vertraegt_alles():
    for wert in ({}, [], None, 5, "x", {"a": [{"b": [1, 2]}]}):
        assert isinstance(struktur(wert), str)
