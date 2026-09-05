"""Profitroom: Zimmer, Angebote und Preise wieder zusammenfuehren.

Profitroom betreibt die Buchungsstrecke von Northern Lights Village und Halo
Igloos - und liefert die drei Teile der Antwort in drei getrennten Abrufen:

    /rooms         Name, Groesse und Beschreibung der Zimmer
    /offers        Raten samt Verpflegung und Stornoregel, mit Zimmerliste
    /availability  die Preise, je Zimmer und Rate, ohne einen einzigen Namen

Die allgemeine Auswertung findet in /availability nur Zahlen ohne Bezeichnung
und faellt deshalb auf die dargestellte Seite zurueck. Dort stand dann "Ideas
for your stay" zu 524,50 EUR - der Anreisser eines Fuenf-Naechte-Pakets, also
weder die Kategorie noch der Preis, nach dem gefragt war.

Die Verknuepfung laeuft ueber RoomID. Nicht bei jedem Haus geht das auf:
Aeltere Konten fuehren in /availability andere Nummern als in /rooms. Gibt es
dort nur ein einziges Zimmer, ist die Zuordnung trotzdem eindeutig - sonst
bleibt der Preis lieber ohne Namen stehen, als einen falschen zu tragen.
"""

from __future__ import annotations

import html
import re

from .ausstattung import finde_merkmale
from .models import Zimmerkategorie
from .money import Betrag, pro_nacht

_MARKUP = re.compile(r"<[^>]+>")
# Reihenfolge wie im uebrigen Projekt: erst britisches Englisch, dann was da ist.
_BEVORZUGT = ("en", "en-GB", "en-US", "de", "de-DE", "fi", "fi-FI")


def _sauber(text: str | None) -> str:
    """Beschreibungen kommen als HTML-Fragment. Listenpunkte muessen dabei
    Trennzeichen behalten - sonst klebt 'Finnish SaunaBreakfast' zusammen und
    keine Merkmalssuche findet mehr etwas."""
    if not text:
        return ""
    mit_luecken = re.sub(r"</(li|p|ul|div|br)>|<br\s*/?>", " ", text, flags=re.I)
    return " ".join(html.unescape(_MARKUP.sub(" ", mit_luecken)).split())


def _feld(eintrag: dict, name: str) -> str:
    """Holt ein uebersetztes Feld aus der translations/messages-Struktur."""
    uebersetzungen = eintrag.get("translations") or []
    nach_sprache = {}
    for u in uebersetzungen:
        if not isinstance(u, dict):
            continue
        for nachricht in u.get("messages") or []:
            if isinstance(nachricht, dict) and nachricht.get("fieldName") == name:
                nach_sprache[u.get("locale") or ""] = nachricht.get("value") or ""
    for sprache in _BEVORZUGT:
        if nach_sprache.get(sprache):
            return nach_sprache[sprache]
    return next((w for w in nach_sprache.values() if w), "")


def _ist_zimmerliste(daten) -> bool:
    return (
        isinstance(daten, list)
        and bool(daten)
        and all(isinstance(e, dict) for e in daten)
        and any("translations" in e and "attributes" in e for e in daten)
        and not any("proposals" in e for e in daten)
    )


def _ist_angebotsliste(daten) -> bool:
    return (
        isinstance(daten, list)
        and bool(daten)
        and all(isinstance(e, dict) for e in daten)
        and any("roomIds" in e or "profiles" in e for e in daten)
    )


def _ist_verfuegbarkeit(daten) -> bool:
    return (
        isinstance(daten, list)
        and bool(daten)
        and all(isinstance(e, dict) for e in daten)
        and any("proposals" in e for e in daten)
    )


def zimmer_katalog(daten) -> dict[int, dict]:
    katalog: dict[int, dict] = {}
    for eintrag in daten:
        kennung = eintrag.get("id")
        if not isinstance(kennung, int):
            continue
        flaeche = None
        bereich = ((eintrag.get("attributes") or {}).get("area") or {})
        if isinstance(bereich.get("from"), (int, float)):
            flaeche = float(bereich["from"])
        katalog[kennung] = {
            "name": _sauber(_feld(eintrag, "name")),
            "beschreibung": _sauber(_feld(eintrag, "description")),
            "groesse_m2": flaeche,
        }
    return katalog


def angebots_katalog(daten) -> dict[int, dict]:
    katalog: dict[int, dict] = {}
    for eintrag in daten:
        kennung = eintrag.get("id")
        if not isinstance(kennung, int):
            continue
        # 'nonref' ist die Angabe, auf die es ankommt: Sie entscheidet, ob eine
        # Umbuchung moeglich bleibt - und steht nicht im Namen der Rate.
        arten = {
            (p or {}).get("type")
            for p in (eintrag.get("profiles") or [])
            if isinstance(p, dict)
        }
        stornierbar = None
        if arten:
            stornierbar = "nonref" not in arten
        katalog[kennung] = {
            "name": _sauber(_feld(eintrag, "name")),
            "beschreibung": " ".join(
                t for t in (_sauber(_feld(eintrag, "intro")),
                            _sauber(_feld(eintrag, "description"))) if t
            ),
            "stornierbar": stornierbar,
            "zimmer": [z for z in (eintrag.get("roomIds") or [])
                       if isinstance(z, int)],
        }
    return katalog


def vorschlaege(daten) -> list[dict]:
    raus: list[dict] = []
    for block in daten:
        for eintrag in block.get("proposals") or []:
            angebot = (eintrag or {}).get("proposal") or {}
            preis = angebot.get("price") or {}
            betrag = preis.get("amount")
            if not isinstance(betrag, (int, float)):
                continue
            raus.append(
                {
                    "zimmer_id": angebot.get("RoomID"),
                    "angebot_id": angebot.get("OfferID"),
                    "betrag": float(betrag),
                    "waehrung": preis.get("currency"),
                    "anzahl": eintrag.get("roomCount"),
                }
            )
    return raus


def angebote(antworten: list[dict], *, naechte: int) -> list[Zimmerkategorie]:
    """Baut aus den drei Profitroom-Antworten die Kategorieliste.

    antworten: die mitgeschnittenen JSON-Antworten, je {"daten": ...}.
    """
    zimmer: dict[int, dict] = {}
    rate: dict[int, dict] = {}
    gefunden: list[dict] = []
    for antwort in antworten:
        daten = antwort.get("daten")
        if _ist_verfuegbarkeit(daten):
            gefunden.extend(vorschlaege(daten))
        elif _ist_angebotsliste(daten):
            rate.update(angebots_katalog(daten))
        elif _ist_zimmerliste(daten):
            zimmer.update(zimmer_katalog(daten))
    if not gefunden:
        return []

    # Je Zimmer der guenstigste Vorschlag. Mehrere Raten fuer dasselbe Zimmer
    # sind der Normalfall - eine mit Halbpension, eine ohne.
    bestes: dict[tuple, dict] = {}
    for vorschlag in gefunden:
        schluessel = (vorschlag["zimmer_id"],)
        vorhanden = bestes.get(schluessel)
        if vorhanden is None or vorschlag["betrag"] < vorhanden["betrag"]:
            bestes[schluessel] = vorschlag

    kategorien = []
    for vorschlag in sorted(bestes.values(), key=lambda v: v["betrag"]):
        beschreibung = rate.get(vorschlag["angebot_id"], {}).get("beschreibung", "")
        angaben = zimmer.get(vorschlag["zimmer_id"])
        if angaben is None and len(zimmer) == 1:
            # Aeltere Konten nummerieren Zimmer in /availability anders als in
            # /rooms. Bei genau einem Zimmer ist die Zuordnung trotzdem
            # eindeutig; bei mehreren waere sie geraten.
            angaben = next(iter(zimmer.values()))
        angaben = angaben or {}
        ratenname = rate.get(vorschlag["angebot_id"], {}).get("name") or ""
        betrag = Betrag(vorschlag["betrag"], vorschlag["waehrung"])
        kategorien.append(
            Zimmerkategorie(
                name=angaben.get("name") or f"Zimmer {vorschlag['zimmer_id']}",
                preis_gesamt=betrag,
                preis_pro_nacht=pro_nacht(betrag, naechte),
                groesse_m2=angaben.get("groesse_m2"),
                ausstattung=finde_merkmale(
                    " ".join([angaben.get("beschreibung", ""), beschreibung])
                ),
                stornierbar=rate.get(vorschlag["angebot_id"], {}).get("stornierbar"),
                zimmerhinweis=(f"Rate: {ratenname}. " if ratenname else "")
                + (beschreibung or angaben.get("beschreibung", ""))[:300] or None,
                verfuegbar=bool(vorschlag.get("anzahl")),
                quelle="netzwerk",
            )
        )
    return kategorien
