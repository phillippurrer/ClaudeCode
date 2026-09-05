"""Preis- und Waehrungsparser fuer nordische Buchungsseiten.

Der Knackpunkt sind die Trennzeichen: "1 234 kr" (Norwegen), "45.900 kr."
(Island, Punkt = Tausender), "1 234,50 EUR" (Finnland) und "1,234.50" (engl.
Sprachversion derselben Seite) muessen alle denselben Betrag ergeben. Ein
falsch geratenes Dezimalzeichen verschiebt den Preis um Faktor 1000 - deshalb
hier explizite Regeln statt eines Universal-Regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Schmale und geschuetzte Leerzeichen sind auf nordischen Seiten die Regel.
_LEERZEICHEN = "      "

# "kr" allein ist mehrdeutig (NOK/SEK/DKK/ISK) und wird ueber den Laenderhinweis
# aufgeloest. Klappt das nicht, gilt KRONEN: "irgendeine nordische Krone".
# Das ist ehrlicher als auf EUR zurueckzufallen - und vor allem sicherer, denn
# die EUR-Plausibilitaetsspanne beginnt bei 25 und liesse damit jede Kurtaxe
# als Zimmerpreis durchgehen.
KRONEN = "kr"
_WAEHRUNGS_ZEICHEN = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
}
_WAEHRUNGS_CODES = {
    "NOK", "SEK", "DKK", "ISK", "EUR", "USD", "GBP", "CHF", "PLN", "CZK",
}
# Landeskuerzel -> Waehrung, um ein blankes "kr" zuzuordnen.
KR_NACH_LAND = {
    "no": "NOK",
    "se": "SEK",
    "dk": "DKK",
    "is": "ISK",
    "fi": "EUR",
}

_ZAHL = re.compile(r"\d[\d" + _LEERZEICHEN + r"".join(["\\.", ","]) + r"]*\d|\d")


class PreisFehler(ValueError):
    """Text enthaelt keinen brauchbaren Betrag."""


@dataclass(frozen=True)
class Betrag:
    wert: float
    waehrung: str | None = None

    def als_dict(self) -> dict:
        return {"betrag": round(self.wert, 2), "waehrung": self.waehrung}

    def __str__(self) -> str:
        return f"{self.wert:,.2f} {self.waehrung or ''}".strip()


def _zahl_aus(text: str) -> float:
    """Wandelt einen Zahlentext in einen Float, Trennzeichen aufgeloest."""
    roh = text
    for zeichen in _LEERZEICHEN:
        roh = roh.replace(zeichen, "")
    if not roh:
        raise PreisFehler(f"keine Ziffern in '{text}'")

    hat_punkt = "." in roh
    hat_komma = "," in roh

    if hat_punkt and hat_komma:
        # Das zuletzt stehende Zeichen trennt die Nachkommastellen.
        dezimal = "." if roh.rfind(".") > roh.rfind(",") else ","
        tausender = "," if dezimal == "." else "."
        roh = roh.replace(tausender, "").replace(dezimal, ".")
    elif hat_punkt or hat_komma:
        zeichen = "." if hat_punkt else ","
        teile = roh.split(zeichen)
        # Mehrfaches Vorkommen kann nur Tausendertrennung sein (1.234.567).
        if len(teile) > 2 or len(teile[-1]) == 3:
            roh = roh.replace(zeichen, "")
        else:
            roh = roh.replace(zeichen, ".")
    try:
        return float(roh)
    except ValueError:
        raise PreisFehler(f"'{text}' ist kein Betrag") from None


def erkenne_waehrung(text: str, land: str | None = None) -> str | None:
    """Liest den Waehrungscode aus dem Preistext.

    land ist ein ISO-Kuerzel ("no", "is", ...) und loest ein blankes "kr" auf.
    """
    gross = text.upper()
    for code in _WAEHRUNGS_CODES:
        if re.search(rf"\b{code}\b", gross):
            return code
    for zeichen, code in _WAEHRUNGS_ZEICHEN.items():
        if zeichen in text:
            return code
    if re.search(r"\bKR\b\.?|:-", gross):
        return KR_NACH_LAND.get((land or "").lower(), KRONEN)
    return None


def parse_preis(text: str, land: str | None = None) -> Betrag:
    """Liest einen einzelnen Betrag aus einem Preistext."""
    if text is None:
        raise PreisFehler("kein Preistext")
    if isinstance(text, (int, float)):
        return Betrag(float(text), erkenne_waehrung("", land))
    treffer = _ZAHL.search(text)
    if not treffer:
        raise PreisFehler(f"kein Betrag in '{text[:60]}'")
    return Betrag(_zahl_aus(treffer.group()), erkenne_waehrung(text, land))


def parse_alle_preise(text: str, land: str | None = None) -> list[Betrag]:
    """Alle Betraege eines Texts, z.B. bei 'statt 2 400 kr jetzt 1 900 kr'."""
    waehrung = erkenne_waehrung(text, land)
    treffer = []
    for m in _ZAHL.finditer(text or ""):
        try:
            treffer.append(Betrag(_zahl_aus(m.group()), waehrung))
        except PreisFehler:
            continue
    return treffer


def ist_plausibler_zimmerpreis(betrag: Betrag, naechte: int = 1) -> bool:
    """Filtert Zahlen heraus, die keine Zimmerpreise sein koennen.

    DOM-Heuristiken fischen sonst Postleitzahlen, Zimmernummern oder
    Treuepunkte ein. Die Grenzen sind bewusst weit und nur waehrungsabhaengig,
    weil ISK-Betraege zwei Groessenordnungen ueber EUR liegen.
    """
    grenzen = {
        # Untergrenze der vorsichtigsten Kronenwaehrung (DKK), Obergrenze der
        # groesszuegigsten (ISK): so faellt eine Kurtaxe raus, ohne ein
        # echtes ISK-Zimmer zu verlieren.
        KRONEN: (200, 2_000_000),
        "ISK": (5_000, 2_000_000),
        "NOK": (300, 200_000),
        "SEK": (300, 200_000),
        "DKK": (200, 150_000),
        "EUR": (25, 20_000),
        "USD": (25, 20_000),
        "GBP": (25, 20_000),
    }
    unten, oben = grenzen.get(betrag.waehrung or "EUR", (25, 2_000_000))
    return unten <= betrag.wert <= oben * max(naechte, 1)


def pro_nacht(betrag: Betrag, naechte: int) -> Betrag:
    """Rechnet einen Gesamtpreis auf den Schnitt pro Nacht herunter."""
    if naechte < 1:
        raise PreisFehler("naechte muss mindestens 1 sein")
    return Betrag(betrag.wert / naechte, betrag.waehrung)
