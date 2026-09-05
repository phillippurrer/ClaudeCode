"""Erkennt Ausstattungsmerkmale und Zimmergroesse aus Text.

Der Anlass ist konkret: Bei den Glashuetten entscheidet nicht der Preis,
sondern ob privater Whirlpool und Sauna dabei sind. Google Hotels gibt das
nicht her, die Buchungsstrecke des Hauses schon - mal als JSON-Feld
"amenities", mal nur im Beschreibungstext der Kategorie.

Die Stichworte decken Englisch, Finnisch und Deutsch ab, weil dieselbe
Buchungsmaschine je nach Spracheinstellung anders ausliefert.
"""

from __future__ import annotations

import re

# Merkmal -> Stichworte. Erster Treffer gewinnt, Reihenfolge egal.
MERKMALE: dict[str, tuple[str, ...]] = {
    "privater Whirlpool": (
        "private hot tub", "outdoor hot tub", "hot tub", "whirlpool",
        "jacuzzi", "poreallas", "kylpytynnyri", "badefass",
    ),
    "eigene Sauna": (
        "private sauna", "own sauna", "in-room sauna", "oma sauna",
        "eigene sauna", "sauna in the",
    ),
    "Glasdach": (
        "glass roof", "glass ceiling", "sky view", "skyview", "panoramic roof",
        "lasikatto", "glasdach", "aurora roof", "glass igloo",
    ),
    "Kamin": ("fireplace", "takka", "kamin", "wood stove"),
    "Terrasse": ("private terrace", "terrace", "terassi", "terrasse", "balcony"),
    "Kueche": ("kitchenette", "kitchen", "keittio", "kueche", "kochnische"),
    "Fruehstueck inklusive": (
        "breakfast included", "incl. breakfast", "with breakfast",
        "aamiainen sisaltyy", "fruehstueck inklusive", "mit fruehstueck",
    ),
}

# "25 m2", "25 m²", "25 sqm", "25 neliota" - Dezimalkomma erlaubt.
_GROESSE = re.compile(
    r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:m²|m2|m\^2|sqm|sq\.?\s?m|qm|neli[oö]|neli[oö]metri[aä]?)",
    re.I,
)

# Zahlenbereich, in dem eine Angabe eine Zimmergroesse sein kann. Darunter
# sind es Badezimmer-Masse, darueber die Flaeche der ganzen Anlage.
_GROESSE_MIN, _GROESSE_MAX = 6.0, 400.0


def _normalisiere(text: str) -> str:
    """Macht Umlaute und Diakritika vergleichbar."""
    ersatz = {
        "ä": "a", "ö": "o", "ü": "u", "å": "a", "ß": "ss",
        "Ä": "a", "Ö": "o", "Ü": "u", "Å": "a",
    }
    for alt, neu in ersatz.items():
        text = text.replace(alt, neu)
    return text.lower()


def finde_merkmale(*texte: str) -> list[str]:
    """Liest Ausstattungsmerkmale aus einem oder mehreren Texten.

    Ergebnis ist stabil sortiert (Reihenfolge von MERKMALE), damit sich zwei
    Abrufe desselben Zimmers vergleichen lassen.
    """
    zusammen = _normalisiere(" ".join(t for t in texte if t))
    if not zusammen.strip():
        return []
    gefunden = []
    for merkmal, stichworte in MERKMALE.items():
        if any(_normalisiere(wort) in zusammen for wort in stichworte):
            gefunden.append(merkmal)
    return gefunden


def finde_groesse_m2(*texte: str) -> float | None:
    """Liest die Zimmergroesse in Quadratmetern.

    Bei mehreren Angaben gewinnt die groesste: Steht "25 m² Wohnraum, 4 m²
    Bad", ist die Kategorie 25 m² gross.
    """
    kandidaten: list[float] = []
    for text in texte:
        if not text:
            continue
        for treffer in _GROESSE.finditer(text):
            try:
                wert = float(treffer.group(1).replace(",", "."))
            except ValueError:
                continue
            if _GROESSE_MIN <= wert <= _GROESSE_MAX:
                kandidaten.append(wert)
    if not kandidaten:
        return None
    groesste = max(kandidaten)
    return round(groesste, 1) if groesste % 1 else float(int(groesste))
