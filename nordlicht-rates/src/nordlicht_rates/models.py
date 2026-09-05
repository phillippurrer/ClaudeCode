"""Ergebnistypen. Alles, was ein MCP-Tool zurueckgibt, entsteht hier."""

from __future__ import annotations

from dataclasses import dataclass, field

from .money import Betrag


@dataclass
class Zimmerangebot:
    """Eine Zimmerkategorie mit Preis, so wie die Buchungsseite sie zeigt."""

    name: str
    gesamtpreis: Betrag | None = None
    preis_pro_nacht: Betrag | None = None
    verpflegung: str | None = None
    stornierbar: bool | None = None
    hinweis: str | None = None
    quelle: str = "dom"  # netzwerk | jsonld | state | dom

    def als_dict(self) -> dict:
        d: dict = {"zimmer": self.name, "quelle": self.quelle}
        if self.gesamtpreis:
            d["gesamtpreis"] = self.gesamtpreis.wert
            d["waehrung"] = self.gesamtpreis.waehrung
        if self.preis_pro_nacht:
            d["pro_nacht"] = round(self.preis_pro_nacht.wert, 2)
        for schluessel, wert in (
            ("verpflegung", self.verpflegung),
            ("stornierbar", self.stornierbar),
            ("hinweis", self.hinweis),
        ):
            if wert is not None:
                d[schluessel] = wert
        return d


@dataclass
class PreisErgebnis:
    """Antwort eines Preisabrufs inklusive Herkunftsangaben.

    Die Metafelder sind nicht Beiwerk: Ohne sie laesst sich spaeter nicht mehr
    sagen, ob ein Preis vom Hotel selbst kam oder aus einer DOM-Heuristik, und
    ob "kein Zimmer frei" wirklich Ausbuchung war oder nur ein Extraktions-
    fehler.
    """

    hotel: str
    url: str
    engine: str
    zeitraum: dict
    angebote: list[Zimmerangebot] = field(default_factory=list)
    waehrung: str | None = None
    belegung: dict = field(default_factory=dict)
    warnungen: list[str] = field(default_factory=list)
    debug: dict = field(default_factory=dict)
    dauer_s: float | None = None
    aus_cache: bool = False

    @property
    def guenstigstes(self) -> Zimmerangebot | None:
        mit_preis = [a for a in self.angebote if a.gesamtpreis]
        if not mit_preis:
            return None
        return min(mit_preis, key=lambda a: a.gesamtpreis.wert)

    def als_dict(self) -> dict:
        billig = self.guenstigstes
        d = {
            "hotel": self.hotel,
            "engine": self.engine,
            "url": self.url,
            **self.zeitraum,
            "belegung": self.belegung,
            "gefunden": len(self.angebote),
            "angebote": [a.als_dict() for a in self.angebote],
        }
        if billig and billig.gesamtpreis:
            d["bestpreis"] = billig.gesamtpreis.wert
            d["bestpreis_zimmer"] = billig.name
            d["waehrung"] = billig.gesamtpreis.waehrung or self.waehrung
        elif self.waehrung:
            d["waehrung"] = self.waehrung
        if not self.angebote:
            d["ergebnis"] = (
                "keine Preise gefunden - entweder ausgebucht oder die "
                "Buchungsstrecke wurde nicht korrekt gelesen; mit "
                "buchungsstrecke_pruefen nachsehen"
            )
        if self.warnungen:
            d["warnungen"] = self.warnungen
        if self.aus_cache:
            d["aus_cache"] = True
        if self.dauer_s is not None:
            d["dauer_s"] = round(self.dauer_s, 1)
        if self.debug:
            d["debug"] = self.debug
        return d
