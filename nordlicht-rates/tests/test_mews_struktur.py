"""Gegen die tatsaechliche Antwortstruktur von Mews.

Die Fixtures sind den Live-Antworten des Distributors der Northern Lights
Ranch nachgebildet, so wie das Protokoll sie gezeigt hat - insbesondere die
uebersetzten Namensfelder, an denen die Extraktion zuvor scheiterte.
"""

import pytest

from nordlicht_rates.extract import (
    _lokalisiert,
    angebote_aus_json,
    kategorien_ohne_preis,
)

# So liefert getCalendarData die Kategorien: Name und Beschreibung als
# Sprachwoerterbuch, Bettenzahl als Kennzeichen eines Zimmers, kein Preis.
KALENDER = {
    "rates": [
        {"id": "r1", "name": {"en-GB": "Flexible rate"}, "currencyCode": "EUR"},
    ],
    "resourceCategories": [
        {
            "id": "4eca197b",
            "serviceId": "81637f78",
            "name": {"en-GB": "Sky View Cabin Superior"},
            "description": {"en-GB": "25 m2 with heated glass roof over the bed"},
            "ordering": 1,
            "normalBedCount": 2,
            "extraBedCount": 0,
            "spaceType": "Room",
        },
        {
            "id": "da2b13d7",
            "name": {"en-GB": "Sky View Cabin Deluxe",
                     "de-DE": "Sky View Huette Deluxe"},
            "description": {"en-GB": "25 m2, private outdoor hot tub 24/7"},
            "ordering": 2,
            "normalBedCount": 2,
            "extraBedCount": 1,
            "spaceType": "Room",
        },
        {
            "id": "1192e309",
            "name": {"en-GB": "Sky View Cabin Ultimate"},
            "description": {"en-GB": "35 m2 with own sauna and private hot tub"},
            "ordering": 3,
            "normalBedCount": 2,
            "extraBedCount": 0,
            "spaceType": "Room",
        },
    ],
}


@pytest.mark.parametrize(
    "wert,erwartet",
    [
        ({"en-GB": "Deluxe", "de-DE": "Deluxe DE"}, "Deluxe"),
        ({"de-DE": "Nur Deutsch"}, "Nur Deutsch"),
        ({"fi-FI": "Vain suomeksi"}, "Vain suomeksi"),
        ("schon eine Zeichenkette", "schon eine Zeichenkette"),
        ({}, None),
        ({"nichtssagend": "x"}, None),
        (None, None),
        (42, None),
    ],
)
def test_uebersetzte_felder(wert, erwartet):
    assert _lokalisiert(wert) == erwartet


def test_englisch_wird_bevorzugt():
    """Die Ausstattungserkennung ist auf Englisch am treffsichersten."""
    assert _lokalisiert({"cs-CZ": "Chata", "en-GB": "Cabin"}) == "Cabin"


def test_kategorien_ohne_preis_findet_alle_drei():
    """Der Fall Northern Lights Ranch: Mews nennt seine Kategorien, gibt aber
    fuer den Zeitraum keine Raten heraus. Namen und Ausstattung sind damit
    trotzdem zu beantworten - nur der Preis nicht."""
    kategorien = {k.name: k for k in kategorien_ohne_preis(KALENDER)}
    assert set(kategorien) == {
        "Sky View Cabin Superior",
        "Sky View Cabin Deluxe",
        "Sky View Cabin Ultimate",
    }


def test_whirlpool_trennt_die_kategorien_auch_ohne_preis():
    """Die eigentliche Frage, beantwortbar ohne eine einzige Preisangabe."""
    kategorien = {k.name: k for k in kategorien_ohne_preis(KALENDER)}
    superior = kategorien["Sky View Cabin Superior"]
    deluxe = kategorien["Sky View Cabin Deluxe"]
    ultimate = kategorien["Sky View Cabin Ultimate"]

    assert "privater Whirlpool" not in superior.ausstattung
    assert "privater Whirlpool" in deluxe.ausstattung
    assert {"privater Whirlpool", "eigene Sauna"} <= set(ultimate.ausstattung)
    assert superior.groesse_m2 == 25.0
    assert ultimate.groesse_m2 == 35.0


def test_ohne_preis_kein_preis_vorgetaeuscht():
    """Ein fehlender Preis darf nicht als 0 durchgehen."""
    for kategorie in kategorien_ohne_preis(KALENDER):
        assert kategorie.preis_gesamt is None
        assert "preis_gesamt" not in kategorie.als_dict()
        assert kategorie.als_dict()["verfuegbar"] is False


def test_objekte_ohne_zimmermerkmal_werden_uebergangen():
    """Ohne diese Huerde faende sich in jeder Antwort Dutzendes, das kein
    Zimmer ist - Tarife, Staedte, Altersgruppen."""
    daten = {
        "cities": [{"id": "c1", "name": {"en-GB": "Koengaes"}}],
        "ageCategories": [{"id": "a1", "name": {"en-GB": "Adult"}}],
        "rates": [{"id": "r1", "name": {"en-GB": "Flexible rate"}}],
    }
    assert kategorien_ohne_preis(daten) == []


def test_uebersetzter_name_wird_auch_mit_preis_gelesen():
    """Regression: Solange Namen nur als Zeichenkette akzeptiert wurden, ging
    bei Mews jede Kategorie verloren - auch dann, wenn Preise vorlagen."""
    daten = {
        "categoryPrices": [
            {
                "categoryId": "da2b13d7",
                "name": {"en-GB": "Sky View Cabin Deluxe"},
                "description": {"en-GB": "private hot tub"},
                "totalAmount": {"currency": "EUR", "value": 1980},
            }
        ]
    }
    angebote = angebote_aus_json(daten, naechte=2)
    assert len(angebote) == 1
    assert angebote[0].name == "Sky View Cabin Deluxe"
    assert angebote[0].preis_gesamt.wert == 1980
    assert "privater Whirlpool" in angebote[0].ausstattung


def test_alle_sprachfassungen_verdraengen_den_text_nicht():
    """Eine Beschreibung in 34 Sprachen wuerde den Ausstattungstext sprengen;
    es zaehlt eine Fassung."""
    daten = {
        "resourceCategories": [
            {
                "id": "x",
                "name": {"en-GB": "Cabin"},
                "description": {
                    "en-GB": "with private hot tub",
                    **{f"l{i}-XX": "Fuelltext " * 40 for i in range(30)},
                },
                "normalBedCount": 2,
            }
        ]
    }
    kategorie = kategorien_ohne_preis(daten)[0]
    assert "privater Whirlpool" in kategorie.ausstattung
    assert len(kategorie.zimmerhinweis or "") < 210
