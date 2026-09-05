"""Extraktion aus JSON, State, JSON-LD und DOM-Rohtexten."""

import json

from nordlicht_rates.abruf import angebote_aus_dom
from nordlicht_rates.extract import (
    angebote_aus_json,
    angebote_aus_jsonld,
    angebote_aus_state,
    entdoppel,
)

API_ANTWORT = {
    "currency": "NOK",
    "rooms": [
        {
            "roomName": "Standard Double",
            "price": {"amount": 4590, "currency": "NOK"},
            "boardType": "Breakfast included",
            "refundable": True,
        },
        {
            "roomName": "Arctic Suite",
            "totalPrice": {"amount": 11900, "currency": "NOK"},
            "refundable": False,
        },
        {"name": "City tax", "price": {"amount": 45, "currency": "NOK"}},
    ],
}


def test_json_findet_zimmer_und_ignoriert_gebuehren():
    angebote = angebote_aus_json(API_ANTWORT, naechte=3)
    namen = {a.name for a in angebote}
    assert namen == {"Standard Double", "Arctic Suite"}
    assert all(a.quelle == "netzwerk" for a in angebote)


def test_json_liest_verpflegung_und_storno():
    angebot = next(
        a for a in angebote_aus_json(API_ANTWORT, naechte=3)
        if a.name == "Standard Double"
    )
    assert angebot.verpflegung == "Breakfast included"
    assert angebot.stornierbar is True
    assert angebot.gesamtpreis.waehrung == "NOK"


def test_pro_nacht_wird_gerechnet():
    angebot = next(
        a for a in angebote_aus_json(API_ANTWORT, naechte=3)
        if a.name == "Standard Double"
    )
    assert round(angebot.preis_pro_nacht.wert, 2) == 1530.0


def test_waehrung_wird_vom_elternknoten_geerbt():
    """Viele APIs nennen die Waehrung nur einmal ganz oben."""
    daten = {"currency": "ISK", "rooms": [{"name": "Double", "price": 45900}]}
    angebot = angebote_aus_json(daten, naechte=1)[0]
    assert angebot.gesamtpreis.waehrung == "ISK"
    assert angebot.gesamtpreis.wert == 45900


def test_unplausible_zahlen_fliegen_raus():
    """Zimmernummern und Punktestaende sehen wie Preise aus."""
    daten = {"rooms": [
        {"name": "Room 214", "price": {"amount": 3, "currency": "EUR"}},
        {"name": "Bonuspunkte", "price": {"amount": 12, "currency": "EUR"}},
    ]}
    assert angebote_aus_json(daten, naechte=1) == []


def test_state_aus_next_data():
    html = (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"offers": [
            {"roomType": "Superior Seaview", "totalPrice": 6250, "currency": "NOK"}
        ]}}})
        + "</script></body></html>"
    )
    angebote = angebote_aus_state(html, naechte=2)
    assert angebote[0].name == "Superior Seaview"
    assert angebote[0].quelle == "state"


def test_jsonld_offer():
    html = (
        '<html><head><script type="application/ld+json">'
        + json.dumps({
            "@type": "Hotel",
            "name": "Fjordly Hotel",
            "makesOffer": {
                "@type": "Offer", "name": "Doppelzimmer",
                "price": "1890", "priceCurrency": "NOK",
            },
        })
        + "</script></head></html>"
    )
    angebote = angebote_aus_jsonld(html, naechte=1)
    assert any(a.name == "Doppelzimmer" for a in angebote)


def test_kaputtes_jsonld_wirft_nicht():
    assert angebote_aus_jsonld("<script type='application/ld+json'>{oops</script>") == []
    assert angebote_aus_state("<html>ohne alles</html>") == []


def test_dom_nimmt_den_guenstigeren_von_zwei_preisen():
    """Durchgestrichener Vergleichspreis darf nicht gewinnen."""
    kandidaten = [{
        "name": "Familierom",
        "preis_texte": ["3 100 kr", "2 450 kr"],
        "karten_text": "Familierom 3 100 kr 2 450 kr",
    }]
    angebot = angebote_aus_dom(kandidaten, naechte=2, land="no")[0]
    assert angebot.gesamtpreis.wert == 2450.0
    assert angebot.quelle == "dom"


def test_dom_ohne_plausiblen_preis_liefert_nichts():
    kandidaten = [{"name": "Bytax", "preis_texte": ["25 kr"], "karten_text": "Bytax"}]
    assert angebote_aus_dom(kandidaten, naechte=1, land="no") == []


def test_entdoppeln_bevorzugt_netzwerk_vor_dom():
    """Derselbe Preis aus zwei Ebenen darf nur einmal erscheinen - als der
    verlaesslichere."""
    aus_json = angebote_aus_json(
        {"rooms": [{"name": "Standard Double", "price": {"amount": 4590,
                                                         "currency": "NOK"}}]},
        naechte=1,
    )
    aus_dom = angebote_aus_dom(
        [{"name": "Standard Double", "preis_texte": ["4 590 kr"]}],
        naechte=1, land="no",
    )
    vereint = entdoppel(aus_json + aus_dom)
    assert len(vereint) == 1
    assert vereint[0].quelle == "netzwerk"


def test_entdoppeln_sortiert_nach_preis():
    vereint = entdoppel(angebote_aus_json(API_ANTWORT, naechte=1))
    preise = [a.gesamtpreis.wert for a in vereint]
    assert preise == sorted(preise)
