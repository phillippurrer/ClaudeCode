"""Profitroom - drei Antworten, ein Ergebnis.

Die Daten sind gekuerzte Mitschnitte der echten Buchungsstrecken von Halo
Igloos und Northern Lights Village Levi. Gekuerzt heisst: weniger Zimmer und
kuerzere Texte, aber unveraenderte Struktur - genau die Struktur ist ja das,
woran die Auswertung haengt.
"""

from nordlicht_rates.profitroom import (
    angebote,
    angebots_katalog,
    vorschlaege,
    zimmer_katalog,
)


def _antwort(daten):
    return {"url": "https://booking.profitroom.com/api/x", "daten": daten}


HALO_ZIMMER = [
    {
        "id": 504650,
        "attributes": {"area": {"from": 25, "to": 25, "unit": "m²"}},
        "translations": [{"locale": "en", "messages": [
            {"fieldName": "name", "value": "Hillside Igloos"},
            {"fieldName": "description",
             "value": "<p>Glass igloo on the hillside.</p>"},
        ]}],
    },
    {
        "id": 504700,
        "attributes": {"area": {"from": 32, "to": 32, "unit": "m²"}},
        "translations": [{"locale": "en", "messages": [
            {"fieldName": "name", "value": "Hillside Igloos Premium"},
        ]}],
    },
]

HALO_ANGEBOTE = [
    {
        "id": 1169872,
        "profiles": [{"profileId": 206752, "type": "nonref",
                      "deposit": {"percentage": 100}}],
        "roomIds": [504650, 504700],
        "translations": [{"locale": "en", "messages": [
            {"fieldName": "name", "value": "Best Available Deal"},
            {"fieldName": "description",
             "value": "<ul><li>Accommodation in a private glass igloo with "
                      "Finnish Sauna</li><li>Breakfast and dinner buffet</li>"
                      "<li>Private outdoor hot tub</li></ul>"},
        ]}],
    },
]

HALO_VERFUEGBAR = [
    {"occupancy": {"adults": 2, "children": []}, "proposals": [
        {"proposal": {"OfferID": 1169872, "RoomID": 504650,
                      "price": {"amount": 2480, "currency": "EUR"},
                      "stay": {"from": "2027-02-22", "to": "2027-02-24"}},
         "roomCount": 13},
        {"proposal": {"OfferID": 1169872, "RoomID": 504700,
                      "price": {"amount": 2640, "currency": "EUR"},
                      "stay": {"from": "2027-02-22", "to": "2027-02-24"}},
         "roomCount": 4},
    ]},
]


def test_zimmer_bekommen_namen_groesse_und_preis():
    kategorien = angebote(
        [_antwort(HALO_ZIMMER), _antwort(HALO_ANGEBOTE), _antwort(HALO_VERFUEGBAR)],
        naechte=2,
    )
    nach_name = {k.name: k for k in kategorien}
    assert set(nach_name) == {"Hillside Igloos", "Hillside Igloos Premium"}
    assert nach_name["Hillside Igloos"].preis_gesamt.wert == 2480.0
    assert nach_name["Hillside Igloos"].preis_gesamt.waehrung == "EUR"
    assert nach_name["Hillside Igloos"].preis_pro_nacht.wert == 1240.0
    assert nach_name["Hillside Igloos"].groesse_m2 == 25.0


def test_ausstattung_kommt_auch_aus_der_rate():
    """Sauna und Hot Tub stehen bei Halo nicht beim Zimmer, sondern in der
    Beschreibung der Rate."""
    kategorien = angebote(
        [_antwort(HALO_ZIMMER), _antwort(HALO_ANGEBOTE), _antwort(HALO_VERFUEGBAR)],
        naechte=2,
    )
    merkmale = kategorien[0].ausstattung
    assert "privater Whirlpool" in merkmale
    assert "eigene Sauna" in merkmale


def test_listenpunkte_bleiben_getrennt():
    """Ohne Trennzeichen wuerde aus '</li><li>' ein Wort - und 'Finnish
    SaunaBreakfast' findet keine Merkmalssuche mehr."""
    kategorien = angebote(
        [_antwort(HALO_ZIMMER), _antwort(HALO_ANGEBOTE), _antwort(HALO_VERFUEGBAR)],
        naechte=2,
    )
    assert "SaunaBreakfast" not in (kategorien[0].zimmerhinweis or "")


def test_nicht_stornierbare_rate_wird_als_solche_gemeldet():
    kategorien = angebote(
        [_antwort(HALO_ZIMMER), _antwort(HALO_ANGEBOTE), _antwort(HALO_VERFUEGBAR)],
        naechte=2,
    )
    assert kategorien[0].stornierbar is False


def test_guenstigste_rate_je_zimmer_gewinnt():
    zwei_raten = [
        {"occupancy": {"adults": 2}, "proposals": [
            {"proposal": {"OfferID": 1169872, "RoomID": 504650,
                          "price": {"amount": 2480, "currency": "EUR"}},
             "roomCount": 13},
            {"proposal": {"OfferID": 999, "RoomID": 504650,
                          "price": {"amount": 1990, "currency": "EUR"}},
             "roomCount": 13},
        ]},
    ]
    kategorien = angebote(
        [_antwort(HALO_ZIMMER), _antwort(HALO_ANGEBOTE), _antwort(zwei_raten)],
        naechte=2,
    )
    assert len(kategorien) == 1
    assert kategorien[0].preis_gesamt.wert == 1990.0


# Northern Lights Village: aelteres Konto, andere Nummern in /availability als
# in /rooms. Genau dieser Fall darf nicht zu einer falschen Zuordnung fuehren.
NLV_ZIMMER = [
    {
        "id": 116142,
        "attributes": {"area": {"from": 29, "to": 29, "unit": "m²"}},
        "translations": [{"locale": "en", "messages": [
            {"fieldName": "name", "value": "Aurora Cabin"},
            {"fieldName": "description",
             "value": "<p>The laser-heated glass roof opens to the sky.</p>"},
        ]}],
    },
]

NLV_VERFUEGBAR = [
    {"occupancy": {"adults": 2, "children": []}, "proposals": [
        {"proposal": {"OfferID": 208880, "RoomID": 185246,
                      "price": {"amount": 1418, "currency": "EUR"}},
         "roomCount": 24},
        {"proposal": {"OfferID": 231720, "RoomID": 185246,
                      "price": {"amount": 1769, "currency": "EUR"}},
         "roomCount": 24},
    ]},
]


def test_einziges_zimmer_wird_auch_bei_fremder_nummer_zugeordnet():
    kategorien = angebote([_antwort(NLV_ZIMMER), _antwort(NLV_VERFUEGBAR)], naechte=2)
    assert len(kategorien) == 1
    assert kategorien[0].name == "Aurora Cabin"
    assert kategorien[0].preis_gesamt.wert == 1418.0
    assert kategorien[0].groesse_m2 == 29.0


def test_ohne_passende_nummer_lieber_ohne_namen_als_falsch():
    """Bei mehreren Zimmern und nicht passenden Nummern waere jede Zuordnung
    geraten - und ein falscher Zimmername ist schlimmer als gar keiner."""
    kategorien = angebote([_antwort(HALO_ZIMMER), _antwort(NLV_VERFUEGBAR)], naechte=2)
    assert kategorien[0].name == "Zimmer 185246"
    assert kategorien[0].preis_gesamt.wert == 1418.0


def test_ohne_verfuegbarkeit_kein_ergebnis():
    """Zimmerliste allein ist kein Angebot - daraus einen Preis zu erfinden
    waere schlimmer als nichts zu liefern."""
    assert angebote([_antwort(HALO_ZIMMER), _antwort(HALO_ANGEBOTE)], naechte=2) == []


def test_fremde_antworten_stoeren_nicht():
    fremd = [_antwort({"languages": ["en"]}), _antwort([1, 2, 3]), _antwort([])]
    kategorien = angebote(
        fremd + [_antwort(NLV_ZIMMER), _antwort(NLV_VERFUEGBAR)], naechte=2
    )
    assert len(kategorien) == 1


def test_katalogfunktionen_einzeln():
    assert zimmer_katalog(HALO_ZIMMER)[504650]["name"] == "Hillside Igloos"
    assert angebots_katalog(HALO_ANGEBOTE)[1169872]["stornierbar"] is False
    assert vorschlaege(HALO_VERFUEGBAR)[0]["betrag"] == 2480.0
