"""Die MCP-Tools.

register(mcp) haengt sie an eine bestehende FastMCP-Instanz - so laesst sich
das Modul in den vorhandenen NAS-Server einhaengen, ohne dessen Datei
anzufassen.
"""

from __future__ import annotations

import asyncio

from .abruf import hole_preise
from .browser import Browser
from .config import einstellungen, lade_config
from .dates import DatumsFehler, zeitraum
from .engines import alle_engines, baue_urls, erkenne_engine
from .extract import angebote_aus_json, angebote_aus_jsonld, angebote_aus_state

# Mehr als drei Browserfenster gleichzeitig bringt auf einer NAS nichts und
# kostet nur Arbeitsspeicher.
_MAX_PARALLEL = 3


def _fehler(nachricht: str, **rest) -> dict:
    return {"fehler": nachricht, **rest}


def register(mcp) -> None:
    """Registriert alle Tools an einer FastMCP-Instanz."""

    @mcp.tool()
    async def hotel_direktpreise(
        hotelseite: str,
        check_in: str,
        check_out: str | None = None,
        naechte: int | None = None,
        adults: int = 2,
        children: int = 0,
        zimmer: int = 1,
        hotel_id: str | None = None,
        debug: bool = False,
    ) -> dict:
        """Holt Zimmerpreise direkt von der Buchungsstrecke eines Hotels.

        Fuer die Faelle, in denen hotel_price_search (Google Hotels) nichts
        liefert: kleine Haeuser in Nordnorwegen, Lappland und Island stehen
        oft nicht oder ohne Preis bei Google. Dieses Tool oeffnet die
        Buchungsseite des Hotels in einem echten Browser, springt per Deeplink
        direkt auf die Ergebnisliste und liest die Zimmerkategorien mit.

        Wichtig fuer die Antwort an den Nutzer: Das Feld 'quelle' je Angebot
        sagt, wie sicher der Preis ist. 'netzwerk' und 'state' kommen aus den
        Daten der Buchungsmaschine selbst und sind belastbar; 'dom' ist aus
        der dargestellten Seite geraten und kann einen Vergleichs- statt
        Buchungspreis erwischt haben. Ein leeres Ergebnis heisst nicht
        automatisch "ausgebucht" - siehe Feld 'warnungen'.

        hotelseite: Adresse der Hotel- oder Buchungsseite, z.B.
            "https://www.sorrisniva.no" oder direkt die Buchungsmaschine.
        check_in: Anreise als JJJJ-MM-TT.
        check_out: Abreise als JJJJ-MM-TT (alternativ naechte angeben).
        naechte: Anzahl Naechte (alternativ zu check_out).
        adults: Anzahl Erwachsene, Standard 2.
        children: Anzahl Kinder, Standard 0.
        zimmer: Anzahl Zimmer, Standard 1.
        hotel_id: Kennung des Hauses, falls die Kette sie im Deeplink braucht
            (Scandic, Strawberry, Thon). Steht in der URL der Hotelseite.
        debug: Legt Screenshot und HTML der geladenen Seite ab und gibt die
            Pfade zurueck. Fuer die Fehlersuche, wenn nichts gefunden wird.
        """
        try:
            zeit = zeitraum(check_in, check_out, naechte)
        except DatumsFehler as exc:
            return _fehler(str(exc))
        if not hotelseite or not hotelseite.strip():
            return _fehler("hotelseite fehlt")

        ergebnis = await hole_preise(
            hotelseite.strip(),
            zeit,
            adults=adults,
            children=children,
            zimmer=zimmer,
            hotel_id=hotel_id,
            debug=debug,
        )
        return ergebnis.als_dict()

    @mcp.tool()
    async def reise_preise(
        etappen: list[dict],
        adults: int = 2,
        children: int = 0,
        zimmer: int = 1,
    ) -> dict:
        """Prueft mehrere Hotels einer Reiseroute in einem Durchgang.

        Gedacht fuer eine Rundreise mit mehreren Stationen: statt pro Hotel
        einen Einzelabruf zu starten, laeuft alles in einem Browser, was auf
        der NAS deutlich schneller ist und die Hotelseiten weniger belastet.

        etappen: Liste von Objekten mit den Feldern
            hotelseite (Pflicht), check_in (Pflicht), check_out oder naechte,
            optional ort, hotel_id, adults, children, zimmer.
            Beispiel: [{"ort": "Tromsoe", "hotelseite": "https://...",
                        "check_in": "2027-02-14", "naechte": 3}]
        adults/children/zimmer: Vorgabe fuer Etappen ohne eigene Angabe.
        """
        if not etappen:
            return _fehler("etappen ist leer")
        if len(etappen) > 15:
            return _fehler(
                f"{len(etappen)} Etappen sind zu viele - bitte auf 15 aufteilen"
            )

        vorbereitet, fehler = [], []
        for nummer, etappe in enumerate(etappen, 1):
            if not isinstance(etappe, dict):
                fehler.append({"etappe": nummer, "fehler": "kein Objekt"})
                continue
            seite = (etappe.get("hotelseite") or "").strip()
            if not seite:
                fehler.append({"etappe": nummer, "fehler": "hotelseite fehlt"})
                continue
            try:
                zeit = zeitraum(
                    etappe.get("check_in"),
                    etappe.get("check_out"),
                    etappe.get("naechte"),
                )
            except DatumsFehler as exc:
                fehler.append(
                    {"etappe": nummer, "hotelseite": seite, "fehler": str(exc)}
                )
                continue
            vorbereitet.append((nummer, etappe, seite, zeit))

        ergebnisse = []
        if vorbereitet:
            browser = Browser()
            begrenzer = asyncio.Semaphore(_MAX_PARALLEL)

            async def eine(nummer, etappe, seite, zeit):
                async with begrenzer:
                    treffer = await hole_preise(
                        seite,
                        zeit,
                        adults=etappe.get("adults", adults),
                        children=etappe.get("children", children),
                        zimmer=etappe.get("zimmer", zimmer),
                        hotel_id=etappe.get("hotel_id"),
                        browser=browser,
                    )
                    d = treffer.als_dict()
                    d["etappe"] = nummer
                    if etappe.get("ort"):
                        d["ort"] = etappe["ort"]
                    return d

            try:
                ergebnisse = await asyncio.gather(
                    *(eine(*eintrag) for eintrag in vorbereitet)
                )
            finally:
                await browser.stop()
            ergebnisse = sorted(ergebnisse, key=lambda d: d["etappe"])

        summe, waehrungen, offen = 0.0, set(), []
        for eintrag in ergebnisse:
            if eintrag.get("bestpreis") is not None:
                summe += eintrag["bestpreis"]
                if eintrag.get("waehrung"):
                    waehrungen.add(eintrag["waehrung"])
            else:
                offen.append(eintrag.get("ort") or eintrag.get("hotel"))

        zusammenfassung: dict = {
            "etappen": len(etappen),
            "mit_preis": len(ergebnisse) - len(offen),
            "ohne_preis": offen,
        }
        # Nur summieren, wenn alle Etappen dieselbe Waehrung haben - eine
        # Mischsumme aus NOK und EUR waere schlicht falsch.
        if summe and len(waehrungen) == 1 and not offen:
            zusammenfassung["summe_bestpreise"] = round(summe, 2)
            zusammenfassung["waehrung"] = waehrungen.pop()
        elif len(waehrungen) > 1:
            zusammenfassung["hinweis"] = (
                "Etappen in verschiedenen Waehrungen "
                f"({', '.join(sorted(waehrungen))}) - nicht summiert."
            )

        antwort = {"zusammenfassung": zusammenfassung, "ergebnisse": ergebnisse}
        if fehler:
            antwort["ungueltige_etappen"] = fehler
        return antwort

    @mcp.tool()
    async def buchungsstrecke_pruefen(
        hotelseite: str,
        check_in: str,
        naechte: int = 2,
        adults: int = 2,
    ) -> dict:
        """Diagnose fuer ein Hotel, bei dem keine Preise herauskommen.

        Laedt die Seite, sagt welche Buchungsmaschine erkannt wurde, welche
        Deeplinks probiert wurden, wie viele JSON-Antworten mitgeschnitten
        wurden und was die einzelnen Extraktionsebenen gefunden haetten.
        Legt zusaetzlich Screenshot und HTML ab.

        Damit laesst sich entscheiden, ob das Haus wirklich ausgebucht ist,
        der Deeplink nicht passt oder die Selektoren in engines.yaml
        nachgezogen werden muessen.

        hotelseite: Adresse der Hotel- oder Buchungsseite.
        check_in: Anreise als JJJJ-MM-TT.
        naechte: Anzahl Naechte, Standard 2.
        adults: Anzahl Erwachsene, Standard 2.
        """
        try:
            zeit = zeitraum(check_in, naechte=naechte)
        except DatumsFehler as exc:
            return _fehler(str(exc))

        engine = erkenne_engine(hotelseite)
        kandidaten = baue_urls(engine, hotelseite, zeit, adults=adults)
        browser = Browser()
        try:
            seite = await browser.hole(
                kandidaten[0],
                selektoren=engine.selektoren,
                json_pfade=engine.json_pfade,
                debug=True,
                debug_name=f"diagnose-{engine.id}",
            )
        finally:
            await browser.stop()

        ebenen = {
            "netzwerk": sum(
                len(angebote_aus_json(a["daten"], naechte=zeit.naechte))
                for a in seite.json_antworten
            ),
            "state": len(angebote_aus_state(seite.html or "", naechte=zeit.naechte)),
            "jsonld": len(angebote_aus_jsonld(seite.html or "", naechte=zeit.naechte)),
            "dom_karten": len(seite.dom_kandidaten),
        }
        naechster_schritt = (
            "Zugriff wurde abgewiesen - Preis manuell pruefen."
            if seite.blockiert
            else "JSON kam an, aber nichts extrahiert: Preisschluessel in "
            "extract.py ergaenzen."
            if seite.json_antworten and not ebenen["netzwerk"]
            else "Keine JSON-Antwort: Deeplink in engines.yaml stimmt "
            "vermutlich nicht - Screenshot ansehen, ob die Ergebnisliste "
            "ueberhaupt geladen wurde."
            if not seite.json_antworten
            else "Sieht brauchbar aus - hotel_direktpreise sollte liefern."
        )
        return {
            "engine": engine.id,
            "engine_name": engine.name,
            "deeplink_geprueft": engine.geprueft,
            "hinweis_engine": engine.hinweis,
            "probierte_urls": kandidaten[:3],
            "geladen": seite.end_url,
            "status": seite.status,
            "titel": seite.titel,
            "blockiert": seite.blockiert,
            "json_antworten": [
                {"url": a["url"][:160], "status": a["status"]}
                for a in seite.json_antworten[:10]
            ],
            "treffer_je_ebene": ebenen,
            "screenshot": seite.screenshot,
            "html_dump": seite.html_dump,
            "fehler": seite.fehler,
            "naechster_schritt": naechster_schritt,
        }

    @mcp.tool()
    async def buchungsmaschinen_liste() -> dict:
        """Zeigt die konfigurierten Buchungsmaschinen und ihren Pruefstand.

        'geprueft: false' heisst, dass der Deeplink aus der URL-Struktur
        abgeleitet, aber nie gegen die Live-Seite bestaetigt wurde. Solche
        Eintraege liefern im Zweifel leere Ergebnisse und sollten einmal mit
        buchungsstrecke_pruefen verifiziert werden.
        """
        return {
            "config": str(lade_config().get("version", "?")),
            "einstellungen": {
                "cache_ttl_s": einstellungen().cache_ttl_s,
                "min_abstand_s": einstellungen().min_abstand_s,
                "timeout_ms": einstellungen().timeout_ms,
                "debug_verzeichnis": str(einstellungen().debug_verzeichnis),
            },
            "engines": [
                {
                    "id": e.id,
                    "name": e.name,
                    "geprueft": e.geprueft,
                    "hat_deeplink": bool(e.deeplink or e.deeplink_kandidaten),
                    "hinweis": e.hinweis,
                }
                for e in alle_engines()
            ],
        }
