"""Direktaufruf von der Kommandozeile, ohne MCP-Server.

Gedacht fuer den ersten Lauf und fuer die Kalibrierung: Man will eine Zahl
sehen, bevor man einen Dienst einrichtet. Beispiel:

    python -m nordlicht_rates.cli https://theranch.fi/check-availability/ \\
        --check-in 2027-02-22 --naechte 2

Mehrere Adressen sind erlaubt und teilen sich einen Browser - praktisch, um
zwei Haeuser direkt nebeneinander zu sehen.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .abruf import hole_kategorien
from .browser import Browser
from .dates import DatumsFehler, zeitraum
from .models import KategorieErgebnis

# Merkmale, nach denen die Zusammenfassung am Ende gruppiert. Das ist die
# Frage, an der die Recherche haengt: mit oder ohne eigenen Whirlpool.
_TRENNMERKMAL = "privater Whirlpool"


def _groesse(wert: float | None) -> str:
    """25.0 als '25' zeigen, 16.5 als '16.5'."""
    if not wert:
        return "-"
    return str(int(wert)) if float(wert).is_integer() else str(wert)


def _tabelle(ergebnis: KategorieErgebnis) -> str:
    zeilen = []
    kopf = f"{'Kategorie':<38} {'gesamt':>10} {'/Nacht':>9} {'m2':>5}  Ausstattung"
    zeilen.append(kopf)
    zeilen.append("-" * len(kopf))
    for k in ergebnis.kategorien:
        preis = f"{k.preis_gesamt.wert:,.0f}".replace(",", ".") if k.preis_gesamt else "-"
        waehrung = (k.preis_gesamt.waehrung or "") if k.preis_gesamt else ""
        nacht = f"{k.preis_pro_nacht.wert:,.0f}".replace(",", ".") if k.preis_pro_nacht else "-"
        zeilen.append(
            f"{k.name[:38]:<38} {preis + ' ' + waehrung:>10} {nacht:>9} "
            f"{_groesse(k.groesse_m2):>5}  {', '.join(k.ausstattung) or '-'}"
            f"   [{k.quelle}]"
        )
    return "\n".join(zeilen)


def _vergleich(ergebnis: KategorieErgebnis) -> str:
    """Stellt die guenstigste Kategorie mit und ohne Whirlpool gegenueber."""
    mit = [
        k for k in ergebnis.kategorien
        if _TRENNMERKMAL in k.ausstattung and k.preis_gesamt
    ]
    ohne = [
        k for k in ergebnis.kategorien
        if _TRENNMERKMAL not in k.ausstattung and k.preis_gesamt
    ]
    if not mit or not ohne:
        fehlt = "mit" if not mit else "ohne"
        return (
            f"  Kein Vergleich moeglich - keine Kategorie {fehlt} "
            f"'{_TRENNMERKMAL}' gefunden."
        )
    guenstigste_mit = min(mit, key=lambda k: k.preis_gesamt.wert)
    guenstigste_ohne = min(ohne, key=lambda k: k.preis_gesamt.wert)
    aufpreis = guenstigste_mit.preis_gesamt.wert - guenstigste_ohne.preis_gesamt.wert
    waehrung = guenstigste_mit.preis_gesamt.waehrung or ""
    return (
        f"  ohne Whirlpool: {guenstigste_ohne.name} - "
        f"{guenstigste_ohne.preis_gesamt.wert:,.0f} {waehrung}\n"
        f"  mit  Whirlpool: {guenstigste_mit.name} - "
        f"{guenstigste_mit.preis_gesamt.wert:,.0f} {waehrung}\n"
        f"  Aufpreis:       {aufpreis:,.0f} {waehrung} "
        f"({aufpreis / max(guenstigste_ohne.preis_gesamt.wert, 1) * 100:.0f} %)"
    ).replace(",", ".")


async def _laufe(argumente) -> int:
    try:
        zeit = zeitraum(argumente.check_in, argumente.check_out, argumente.naechte)
    except DatumsFehler as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    browser = Browser()
    ergebnisse = []
    try:
        for adresse in argumente.buchungsseite:
            ergebnisse.append(
                await hole_kategorien(
                    adresse,
                    zeit,
                    adults=argumente.adults,
                    children=argumente.children,
                    zimmer=argumente.zimmer,
                    hotel_id=argumente.hotel_id,
                    debug=argumente.debug,
                    browser=browser,
                    cache_nutzen=not argumente.kein_cache,
                )
            )
    finally:
        await browser.stop()

    if argumente.json:
        print(json.dumps([e.als_dict() for e in ergebnisse], indent=2, ensure_ascii=False))
        return 0 if any(e.kategorien for e in ergebnisse) else 1

    for ergebnis in ergebnisse:
        print()
        print(f"{ergebnis.hotel}  [{ergebnis.system}]")
        print(f"{zeit.check_in} bis {zeit.check_out}, {zeit.naechte} Naechte, "
              f"{argumente.adults} Erwachsene")
        print(f"{ergebnis.buchungsseite}")
        print()
        if ergebnis.kategorien:
            print(_tabelle(ergebnis))
            print()
            print("Vergleich:")
            print(_vergleich(ergebnis))
        else:
            print("  Keine Kategorien gefunden.")
        for hinweis in ergebnis.hinweise:
            print(f"  Hinweis: {hinweis}")
        if ergebnis.debug.get("screenshots"):
            for pfad in ergebnis.debug["screenshots"]:
                print(f"  Screenshot: {pfad}")
        if not ergebnis.kategorien and ergebnis.debug.get("versuche"):
            print("  Probierte Adressen:")
            for versuch in ergebnis.debug["versuche"]:
                print(f"    {versuch['url']}")
                print(f"      Status {versuch['status']}, "
                      f"{versuch['json_antworten']} JSON-Antworten, "
                      f"{versuch['dom_karten']} DOM-Karten")
    print()
    return 0 if any(e.kategorien for e in ergebnisse) else 1


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(
        prog="nordlicht-rates",
        description="Zimmerkategorien mit Preisen aus einer Buchungsmaschine lesen.",
    )
    zerleger.add_argument("buchungsseite", nargs="+",
                          help="URL der Buchungs- oder Hotelseite (mehrere moeglich)")
    zerleger.add_argument("--check-in", required=True, metavar="JJJJ-MM-TT")
    zerleger.add_argument("--check-out", metavar="JJJJ-MM-TT")
    zerleger.add_argument("--naechte", type=int)
    zerleger.add_argument("--adults", type=int, default=2)
    zerleger.add_argument("--children", type=int, default=0)
    zerleger.add_argument("--zimmer", type=int, default=1)
    zerleger.add_argument("--hotel-id", dest="hotel_id",
                          help="Kennung des Hauses bzw. Mews-Distributor-GUID")
    zerleger.add_argument("--debug", action="store_true",
                          help="Screenshot und HTML ablegen")
    zerleger.add_argument("--kein-cache", dest="kein_cache", action="store_true")
    zerleger.add_argument("--json", action="store_true",
                          help="Rohdaten statt Tabelle ausgeben")
    argumente = zerleger.parse_args(argv)
    return asyncio.run(_laufe(argumente))


if __name__ == "__main__":
    sys.exit(main())
