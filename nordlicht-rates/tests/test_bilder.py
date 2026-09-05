"""Auswahl der Fotos.

Getestet wird die Heuristik, nicht der Browser: Ob ein Logo als Zimmerfoto
durchgeht, entscheidet sich hier - und nur hier laesst es sich festhalten.
"""

from nordlicht_rates.bilder import (
    ist_deko,
    variante_waehlen,
    waehle_fotos,
    _grundform,
)


def test_logos_und_symbole_fliegen_raus():
    assert ist_deko("https://h.fi/wp-content/uploads/logo-2021.png")
    assert ist_deko("https://h.fi/img/favicon.ico")
    assert ist_deko("https://h.fi/karte.svg")
    assert ist_deko("https://h.fi/tripadvisor-award.jpg")
    assert not ist_deko("https://h.fi/wp-content/uploads/sky-view-cabin.jpg")


def test_kleine_kacheln_fliegen_raus():
    """Vorschaubilder aus der Galerie zeigen nichts und belegen einen Platz."""
    assert ist_deko("https://h.fi/uploads/iglu-150x150.jpg")
    assert not ist_deko("https://h.fi/uploads/iglu-1024x683.jpg")


def test_srcset_nimmt_die_kleinste_ausreichende_fassung():
    srcset = ("https://h.fi/a-300x200.jpg 300w, https://h.fi/a-768x512.jpg 768w, "
              "https://h.fi/a-1920x1280.jpg 1920w")
    assert variante_waehlen(srcset, 640) == ("https://h.fi/a-768x512.jpg", 768)
    assert variante_waehlen(srcset, 1920) == ("https://h.fi/a-1920x1280.jpg", 1920)


def test_srcset_ohne_ausreichende_fassung_nimmt_die_groesste():
    srcset = "https://h.fi/a-300x200.jpg 300w, https://h.fi/a-480x320.jpg 480w"
    assert variante_waehlen(srcset, 1200) == ("https://h.fi/a-480x320.jpg", 480)


def test_leeres_srcset_meldet_nichts():
    assert variante_waehlen("", 640) is None


def test_dasselbe_motiv_in_fuenf_groessen_zaehlt_einmal():
    """Baukaesten liefern jedes Bild in allen Groessen aus - ohne diese
    Zusammenfassung besteht die Auswahl aus einem einzigen Motiv."""
    kandidaten = [
        {"url": f"https://h.fi/uploads/iglu-{b}x600.jpg", "quelle": "img",
         "breite": b, "hoehe": 600}
        for b in (800, 1024, 1200, 1600, 1920)
    ] + [{"url": "https://h.fi/uploads/sauna.jpg", "quelle": "img",
          "breite": 900, "hoehe": 600}]
    auswahl = waehle_fotos(kandidaten, anzahl=6, zielbreite=640)
    assert len(auswahl) == 2


def test_vorschaubild_der_sozialen_netze_steht_vorn():
    """Das og:image ist das Bild, mit dem das Haus selbst wirbt."""
    kandidaten = [
        {"url": "https://h.fi/gross.jpg", "quelle": "img", "breite": 1920,
         "hoehe": 1080},
        {"url": "https://h.fi/vorschau.jpg", "quelle": "og"},
    ]
    auswahl = waehle_fotos(kandidaten, anzahl=6, zielbreite=640)
    assert auswahl[0]["url"] == "https://h.fi/vorschau.jpg"


def test_flache_kopfleisten_fliegen_raus():
    kandidaten = [{"url": "https://h.fi/streifen.jpg", "quelle": "bg",
                   "breite": 1920, "hoehe": 90}]
    assert waehle_fotos(kandidaten, anzahl=6, zielbreite=640) == []


def test_anzahl_wird_eingehalten():
    kandidaten = [
        {"url": f"https://h.fi/motiv{i}.jpg", "quelle": "img", "breite": 900,
         "hoehe": 600}
        for i in range(20)
    ]
    assert len(waehle_fotos(kandidaten, anzahl=4, zielbreite=640)) == 4


def test_grundform_ignoriert_zwischenspeicher_parameter():
    a = _grundform("https://h.fi/a-1024x683.jpg?v=7")
    b = _grundform("https://h.fi/a-300x200.jpg")
    assert a == b
