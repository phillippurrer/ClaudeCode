"""Ergebnistypen. Alles, was ein MCP-Tool zurueckgibt, entsteht hier.

Feldnamen folgen der Konvention des bestehenden NAS-Servers: deutsch,
preis_gesamt statt total, naechte statt nights, hinweis und fehler fuer
alles, was der Nutzer wissen muss.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .money import Betrag


@dataclass
class Zimmerkategorie:
    """Eine buchbare Zimmerkategorie, so wie die Buchungsseite sie zeigt."""

    name: str
    preis_gesamt: Betrag | None = None
    preis_pro_nacht: Betrag | None = None
    groesse_m2: float | None = None
    ausstattung: list[str] = field(default_factory=list)
    verpflegung: str | None = None
    stornierbar: bool | None = None
    verfuegbar: bool = True
    zimmerhinweis: str | None = None
    quelle: str = "dom"  # netzwerk | state | jsonld | dom

    def als_dict(self) -> dict:
        d: dict = {"name": self.name}
        if self.preis_gesamt:
            d["preis_gesamt"] = round(self.preis_gesamt.wert, 2)
            d["waehrung"] = self.preis_gesamt.waehrung
        if self.preis_pro_nacht:
            d["preis_pro_nacht"] = round(self.preis_pro_nacht.wert, 2)
        if self.groesse_m2:
            d["groesse_m2"] = self.groesse_m2
        if self.ausstattung:
            d["ausstattung"] = self.ausstattung
        for schluessel, wert in (
            ("verpflegung", self.verpflegung),
            ("stornierbar", self.stornierbar),
            ("zimmerhinweis", self.zimmerhinweis),
        ):
            if wert is not None:
                d[schluessel] = wert
        d["verfuegbar"] = self.verfuegbar
        # Sagt, wie belastbar der Preis ist: netzwerk/state stammen aus den
        # Daten der Buchungsmaschine, dom ist aus der Darstellung geraten.
        d["quelle"] = self.quelle
        return d


@dataclass
class KategorieErgebnis:
    """Antwort eines Abrufs samt Herkunftsangaben.

    Die Metafelder sind nicht Beiwerk: Ohne sie laesst sich spaeter nicht mehr
    sagen, ob ein Preis vom Haus selbst kam oder aus einer DOM-Heuristik - und
    ob "nichts gefunden" wirklich Ausbuchung war oder nur ein
    Extraktionsfehler.
    """

    hotel: str
    buchungsseite: str
    system: str
    zeitraum: dict
    kategorien: list[Zimmerkategorie] = field(default_factory=list)
    waehrung: str | None = None
    belegung: dict = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)
    debug: dict = field(default_factory=dict)
    dauer_s: float | None = None
    aus_cache: bool = False

    @property
    def guenstigste(self) -> Zimmerkategorie | None:
        mit_preis = [k for k in self.kategorien if k.preis_gesamt]
        if not mit_preis:
            return None
        return min(mit_preis, key=lambda k: k.preis_gesamt.wert)

    def als_dict(self) -> dict:
        billigste = self.guenstigste
        d = {
            "hotel": self.hotel,
            "system": self.system,
            "buchungsseite": self.buchungsseite,
            **self.zeitraum,
            "belegung": self.belegung,
            "gefunden": len(self.kategorien),
            "kategorien": [k.als_dict() for k in self.kategorien],
        }
        if billigste and billigste.preis_gesamt:
            d["guenstigste_kategorie"] = billigste.name
            d["preis_ab"] = round(billigste.preis_gesamt.wert, 2)
            d["waehrung"] = billigste.preis_gesamt.waehrung or self.waehrung
        elif self.waehrung:
            d["waehrung"] = self.waehrung
        if not self.kategorien:
            d["hinweis"] = (
                "Keine Kategorien gefunden - entweder ausgebucht oder die "
                "Buchungsstrecke wurde nicht korrekt gelesen. Mit "
                "buchungsstrecke_pruefen nachsehen, bevor 'ausgebucht' "
                "berichtet wird."
            )
        if self.hinweise:
            d["hinweise"] = self.hinweise
        if self.aus_cache:
            d["aus_cache"] = True
        if self.dauer_s is not None:
            d["dauer_s"] = round(self.dauer_s, 1)
        if self.debug:
            d["debug"] = self.debug
        return d
