"""Auswertung der Kartenseite.

Die Beispiele stammen aus echten Beschriftungen: englische und deutsche
Fassung, mit und ohne Stimmenzahl. Genau diese Formen muessen durchkommen -
alles andere ist Fantasie ueber ein Markup, das wir nicht kontrollieren.
"""

from nordlicht_rates.bewertung import (
    aehnlichkeit,
    lies_beschriftung,
    werte_aus,
)


def test_englische_beschriftung():
    assert lies_beschriftung("4.7 stars 1,234 reviews") == (4.7, 1234)


def test_deutsche_beschriftung():
    assert lies_beschriftung("4,7 Sterne 1.234 Rezensionen") == (4.7, 1234)


def test_beschriftung_ohne_stimmenzahl():
    assert lies_beschriftung("4.9 stars") == (4.9, None)


def test_beschriftung_ohne_bewertung():
    assert lies_beschriftung("Preis: 4,50 Euro") == (None, None)


def test_unmoegliche_note_wird_verworfen():
    """Eine 7,5 ist keine Bewertung, sondern ein Zahlenfund am falschen Ort."""
    assert lies_beschriftung("7,5 Sterne")[0] is None


def test_aehnliche_namen_sind_nicht_dasselbe_haus():
    """Der Fall, auf den es ankommt: Beide heissen 'Northern Lights', liegen
    aber 200 km auseinander. Ein reiner Zeichenvergleich haelt sie fuer
    nahezu identisch."""
    ranch = aehnlichkeit("Northern Lights Ranch", "Northern Lights Ranch")
    village = aehnlichkeit("Northern Lights Ranch", "Northern Lights Village Levi")
    assert ranch == 1.0
    assert village < 0.6


def test_zusatz_im_namen_stoert_nicht():
    assert aehnlichkeit("Apukka Resort", "Apukka Resort Rovaniemi") > 0.8


def test_bester_treffer_gewinnt():
    roh = {
        "url": "https://www.google.com/maps/search/x",
        "treffer": [
            {"label": "4.2 stars 80 reviews", "name": "Arctic SnowHotel",
             "karten_text": "Arctic SnowHotel"},
            {"label": "4.8 stars 640 reviews", "name": "Northern Lights Ranch",
             "karten_text": "Northern Lights Ranch\nHotel"},
        ],
    }
    ergebnis = werte_aus(roh, "Northern Lights Ranch")
    assert ergebnis["bewertung"] == 4.8
    assert ergebnis["stimmen"] == 640
    assert ergebnis["namensaehnlichkeit"] == 1.0
    assert "hinweis" not in ergebnis


def test_unsichere_zuordnung_wird_benannt():
    """Lieber eine Auskunft mit Warnung als eine falsche ohne."""
    roh = {"treffer": [{"label": "4.5 stars 20 reviews",
                        "name": "Cafe Kotipizza", "karten_text": "Cafe"}]}
    ergebnis = werte_aus(roh, "Golden Crown Levin Iglut")
    assert ergebnis["gefunden"] is True
    assert "unsicher" in ergebnis["hinweis"]
    assert ergebnis["namensaehnlichkeit"] < 0.55


def test_stimmenzahl_aus_dem_kartentext():
    """Manche Karten tragen die Note in der Beschriftung und die Stimmenzahl
    nur im sichtbaren Text."""
    roh = {"treffer": [{"label": "4.6 stars", "name": "Apukka Resort",
                        "karten_text": "Apukka Resort\n4.6 (1,102)\nResort"}]}
    assert werte_aus(roh, "Apukka Resort")["stimmen"] == 1102


def test_rueckfall_auf_den_seitentext():
    """Auf der Ortsseite gibt es keine Trefferliste, nur die grosse Note."""
    roh = {
        "titel": "Glass Resort - Google Maps",
        "treffer": [],
        "text": "Glass Resort\n4,8\n(312)\nHotel in Rovaniemi",
    }
    ergebnis = werte_aus(roh, "Glass Resort")
    assert ergebnis["bewertung"] == 4.8
    assert ergebnis["stimmen"] == 312
    assert ergebnis["quelle"] if "quelle" in ergebnis else True


def test_nichts_gefunden_ist_kein_leerer_erfolg():
    ergebnis = werte_aus({"treffer": [], "text": "keine Ergebnisse"}, "Irgendwas")
    assert ergebnis["gefunden"] is False
    assert "hinweis" in ergebnis
