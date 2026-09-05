"""Die MCP-Tools.

register(mcp) haengt sie an eine bestehende FastMCP-Instanz - so laesst sich
das Modul in den vorhandenen NAS-Server einhaengen, ohne dessen Datei
anzufassen. Feldnamen der Rueckgaben folgen der dortigen Konvention:
deutsch, preis_gesamt, naechte, hinweis, fehler.
"""

from __future__ import annotations

import asyncio

from . import __version__
from .abruf import hole_kategorien
from .bewertung import hole_bewertung
from .bilder import hole_fotos
from .browser import Browser
from .config import einstellungen, lade_config
from .dates import DatumsFehler, zeitraum
from .engines import alle_engines, baue_urls, erkenne_engine
from .extract import angebote_aus_json, angebote_aus_jsonld, angebote_aus_state
from .folge import finde_mews_distributoren
from . import selbstpflege


def _fehler(nachricht: str, **rest) -> dict:
    return {"fehler": nachricht, **rest}


def register(mcp) -> None:
    """Registriert alle Tools an einer FastMCP-Instanz."""

    @mcp.tool()
    async def hotel_room_categories(
        buchungsseite: str,
        check_in: str,
        naechte: int | None = None,
        check_out: str | None = None,
        adults: int = 2,
        children: int = 0,
        zimmer: int = 1,
        hotel_id: str | None = None,
        debug: bool = False,
    ) -> dict:
        """Liest alle buchbaren Zimmerkategorien eines Hauses mit Preis aus.

        Fuellt die Luecke zwischen den beiden vorhandenen Hotel-Tools:
        hotel_price_search nennt ueber Google Hotels je Plattform nur den
        guenstigsten verfuegbaren Preis, nie die Kategorieliste - fuer die
        Frage "was kostet die Kategorie MIT Whirlpool" also unbrauchbar.
        hotel_availability wiederum kann nur WebHotelier.

        Dieses Tool oeffnet die Buchungsstrecke des Hauses in einem echten
        Browser. Zeigt die Hotelseite selbst keine Preise, weil die Buchung in
        einem Widget steckt (Mews, UpperBooking), wird das Widget gefunden und
        direkt geoeffnet.

        Wichtig fuer die Antwort an den Nutzer: Jede Kategorie traegt das Feld
        'quelle'. 'netzwerk' und 'state' stammen aus den Daten der
        Buchungsmaschine selbst und sind belastbar; 'dom' ist aus der
        dargestellten Seite geraten und kann einen Vergleichs- statt
        Buchungspreis erwischt haben. Ein leeres Ergebnis heisst NICHT
        automatisch "ausgebucht" - dann steht der Grund in 'hinweise', und
        buchungsstrecke_pruefen sagt, woran es lag.

        buchungsseite: URL der Buchungsmaschine oder der Hotel-Website,
            z.B. "https://theranch.fi/check-availability/".
        check_in: Anreise als JJJJ-MM-TT.
        naechte: Anzahl Naechte (alternativ check_out angeben).
        check_out: Abreise als JJJJ-MM-TT (alternativ zu naechte).
        adults: Anzahl Erwachsene, Standard 2.
        children: Anzahl Kinder, Standard 0.
        zimmer: Anzahl Zimmer bzw. Huetten, Standard 1.
        hotel_id: Kennung des Hauses, falls die Kette sie im Deeplink braucht
            (Scandic, Strawberry, Thon) - steht in der URL der Hotelseite.
            Bei Mews die Distributor-GUID.
        debug: Legt Screenshots und HTML der geladenen Seiten ab und gibt die
            Pfade zurueck. Fuer die Fehlersuche, wenn nichts gefunden wird.
        """
        try:
            zeit = zeitraum(check_in, check_out, naechte)
        except DatumsFehler as exc:
            return _fehler(str(exc))
        if not buchungsseite or not buchungsseite.strip():
            return _fehler("buchungsseite fehlt")

        ergebnis = await hole_kategorien(
            buchungsseite.strip(),
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
        """Prueft mehrere Unterkuenfte einer Reiseroute in einem Durchgang.

        Gedacht fuer eine Reise mit mehreren Stationen: statt pro Haus einen
        Einzelabruf zu starten, laeuft alles in einem Browser, was auf der NAS
        deutlich schneller ist und die Hotelseiten weniger belastet.

        etappen: Liste von Objekten mit den Feldern
            buchungsseite (Pflicht), check_in (Pflicht), naechte oder
            check_out, optional ort, hotel_id, adults, children, zimmer.
            Beispiel: [{"ort": "Levi", "buchungsseite": "https://...",
                        "check_in": "2027-02-20", "naechte": 2}]
        adults/children/zimmer: Vorgabe fuer Etappen ohne eigene Angabe.
        """
        if not etappen:
            return _fehler("etappen ist leer")
        if len(etappen) > 15:
            return _fehler(
                f"{len(etappen)} Etappen sind zu viele - bitte auf 15 aufteilen"
            )

        vorbereitet, fehlerhaft = [], []
        for nummer, etappe in enumerate(etappen, 1):
            if not isinstance(etappe, dict):
                fehlerhaft.append({"etappe": nummer, "fehler": "kein Objekt"})
                continue
            seite = (etappe.get("buchungsseite") or "").strip()
            if not seite:
                fehlerhaft.append({"etappe": nummer, "fehler": "buchungsseite fehlt"})
                continue
            try:
                zeit = zeitraum(
                    etappe.get("check_in"),
                    etappe.get("check_out"),
                    etappe.get("naechte"),
                )
            except DatumsFehler as exc:
                fehlerhaft.append(
                    {"etappe": nummer, "buchungsseite": seite, "fehler": str(exc)}
                )
                continue
            vorbereitet.append((nummer, etappe, seite, zeit))

        ergebnisse = []
        if vorbereitet:
            browser = Browser()
            # Mehr Fenster gleichzeitig bringen auf einer NAS nichts und kosten
            # nur Arbeitsspeicher; auf 2-GB-Geraeten notfalls auf 1 stellen.
            begrenzer = asyncio.Semaphore(einstellungen().max_parallel)

            async def eine(nummer, etappe, seite, zeit):
                async with begrenzer:
                    treffer = await hole_kategorien(
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
            if eintrag.get("preis_ab") is not None:
                summe += eintrag["preis_ab"]
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
            zusammenfassung["summe_ab_preise"] = round(summe, 2)
            zusammenfassung["waehrung"] = waehrungen.pop()
            zusammenfassung["hinweis"] = (
                "Summe der jeweils guenstigsten Kategorie je Haus, nicht der "
                "gewuenschten Kategorie."
            )
        elif len(waehrungen) > 1:
            zusammenfassung["hinweis"] = (
                "Etappen in verschiedenen Waehrungen "
                f"({', '.join(sorted(waehrungen))}) - nicht summiert."
            )

        antwort = {"zusammenfassung": zusammenfassung, "ergebnisse": ergebnisse}
        if fehlerhaft:
            antwort["ungueltige_etappen"] = fehlerhaft
        return antwort

    @mcp.tool()
    async def hotel_fotos(
        seite: str,
        anzahl: int = 6,
        als_base64: bool = False,
        zielbreite: int = 640,
    ) -> dict:
        """Sammelt Fotos einer Unterkunft von deren eigener Website.

        Fuer den Vergleich mehrerer Haeuser: Preise und Quadratmeter sagen
        wenig darueber, wie eine Glashuette tatsaechlich aussieht.

        Geliefert werden die Bildadressen der Seite - Vorschaubild der
        sozialen Netze zuerst, dann die Galerie. Die Zuordnung zu einer
        bestimmten Zimmerkategorie leistet das Tool NICHT; 'alt' enthaelt den
        Bildtext der Seite, mehr Anhaltspunkt gibt es nicht.

        seite: URL der Unterkunft, z.B. "https://theranch.fi/".
        anzahl: Wie viele Fotos hoechstens, Standard 6.
        als_base64: Laedt die Bilder zusaetzlich herunter und gibt sie als
            data:-URL zurueck. Nur einschalten, wenn die Bilder in eine Seite
            eingebettet werden sollen, die fremde Adressen nicht laden darf -
            die Antwort wird dadurch um ein Vielfaches groesser.
        zielbreite: Gewuenschte Bildbreite in Pixeln. Bietet die Seite
            mehrere Groessen an, wird die kleinste ausreichende genommen.
        """
        if not seite or not seite.strip():
            return _fehler("seite fehlt")
        return await hole_fotos(
            seite.strip(),
            anzahl=max(1, min(anzahl, 20)),
            zielbreite=max(120, min(zielbreite, 2000)),
            als_base64=als_base64,
        )

    @mcp.tool()
    async def hotel_bewertung(name: str, ort: str | None = None) -> dict:
        """Liest Bewertung und Zahl der Rezensionen aus Google Maps.

        Ergaenzt die Preisauskunft um das, was kein Buchungssystem liefert:
        wie zufrieden fruehere Gaeste waren und auf wie vielen Stimmen das
        beruht - eine 4,9 aus 12 Stimmen ist etwas anderes als eine 4,6 aus
        1.400.

        Wichtig fuer die Antwort an den Nutzer: 'namensaehnlichkeit' sagt, wie
        sicher der gefundene Kartenpunkt das gesuchte Haus ist. Unter 0,55
        steht zusaetzlich ein Hinweis; solche Werte nicht ungeprueft
        weiterreichen, gerade bei Haeusern mit aehnlichen Namen.

        name: Name der Unterkunft, z.B. "Northern Lights Ranch".
        ort: Ort zur Eingrenzung, z.B. "Levi Finnland". Empfohlen, weil
            Kettennamen sonst am falschen Ort landen.
        """
        if not name or not name.strip():
            return _fehler("name fehlt")
        return await hole_bewertung(name.strip(), (ort or "").strip() or None)

    @mcp.tool()
    async def buchungsstrecke_pruefen(
        buchungsseite: str,
        check_in: str,
        naechte: int = 2,
        adults: int = 2,
    ) -> dict:
        """Diagnose fuer ein Haus, bei dem keine Kategorien herauskommen.

        Laedt die Seite, sagt welches Buchungssystem erkannt wurde, welche
        Deeplinks probiert wurden, wie viele JSON-Antworten mitgeschnitten
        wurden, ob eine eingebettete Buchungsmaschine gefunden wurde und was
        die einzelnen Extraktionsebenen gefunden haetten. Legt zusaetzlich
        Screenshot und HTML ab.

        Damit laesst sich entscheiden, ob das Haus wirklich ausgebucht ist,
        der Deeplink nicht passt oder die Selektoren in engines.yaml
        nachgezogen werden muessen.

        buchungsseite: URL der Buchungsmaschine oder der Hotel-Website.
        check_in: Anreise als JJJJ-MM-TT.
        naechte: Anzahl Naechte, Standard 2.
        adults: Anzahl Erwachsene, Standard 2.
        """
        try:
            zeit = zeitraum(check_in, naechte=naechte)
        except DatumsFehler as exc:
            return _fehler(str(exc))

        engine = erkenne_engine(buchungsseite)
        kandidaten = baue_urls(engine, buchungsseite, zeit, adults=adults)
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

        html = seite.html or ""
        ebenen = {
            "netzwerk": sum(
                len(angebote_aus_json(a["daten"], naechte=zeit.naechte))
                for a in seite.json_antworten
            ),
            "state": len(angebote_aus_state(html, naechte=zeit.naechte)),
            "jsonld": len(angebote_aus_jsonld(html, naechte=zeit.naechte)),
            "dom_karten": len(seite.dom_kandidaten),
        }
        mews_guids = finde_mews_distributoren(html)
        naechster_schritt = (
            "Zugriff wurde abgewiesen - Preis manuell pruefen."
            if seite.blockiert
            else f"{len(mews_guids)} Mews-Distributor(en) im Markup gefunden. "
            "hotel_room_categories folgt diesen automatisch; kommt trotzdem "
            "nichts, die GUID direkt als buchungsseite uebergeben: "
            f"https://app.mews.com/distributor/{mews_guids[0]}"
            if mews_guids and not ebenen["netzwerk"]
            else "JSON kam an, aber nichts extrahiert: Preisschluessel in "
            "extract.py ergaenzen."
            if seite.json_antworten and not ebenen["netzwerk"]
            else "Keine JSON-Antwort: Deeplink in engines.yaml stimmt "
            "vermutlich nicht - Screenshot ansehen, ob die Ergebnisliste "
            "ueberhaupt geladen wurde."
            if not seite.json_antworten
            else "Sieht brauchbar aus - hotel_room_categories sollte liefern."
        )
        return {
            "system": engine.id,
            "system_name": engine.name,
            "deeplink_geprueft": engine.geprueft,
            "hinweis_system": engine.hinweis,
            "probierte_urls": kandidaten[:3],
            "geladen": seite.end_url,
            "status": seite.status,
            "titel": seite.titel,
            "blockiert": seite.blockiert,
            "eingebettete_mews_distributoren": mews_guids,
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
    async def dienst_aktualisieren(neustart: bool = True) -> dict:
        """Holt den aktuellen Code und startet den Dienst neu.

        Damit laesst sich eine Korrektur ausliefern, ohne auf der NAS eine
        Aufgabe auszuloesen. Der Quellcode liegt als Volume neben dem
        Container; nach dem Neustart laeuft der neue Stand.

        Geholt wird ausschliesslich der konfigurierte Zweig des
        konfigurierten Repositorys - beides ist von aussen nicht setzbar.

        Wichtig: Bei neustart=True bricht die Verbindung kurz ab, weil der
        Prozess endet und Docker ihn wieder hochfaehrt. Das ist kein Fehler.
        Nach wenigen Sekunden antwortet der Dienst wieder; dienst_status
        zeigt dann, welcher Stand laeuft.

        neustart: Ob nach dem Abgleich neu gestartet wird. Ohne Neustart
            bleibt der bisherige Code aktiv, der neue liegt nur bereit.
        """
        ergebnis = selbstpflege.aktualisiere()
        if not ergebnis.get("erfolg"):
            return ergebnis
        if neustart and ergebnis.get("veraendert"):
            selbstpflege.neustart_ausloesen()
            ergebnis["hinweis"] = (
                "Neustart in wenigen Sekunden - die Verbindung bricht dabei "
                "kurz ab. Danach mit dienst_status den Stand pruefen."
            )
        elif neustart:
            ergebnis["hinweis"] = "Kein neuer Stand vorhanden, kein Neustart."
        return ergebnis

    @mcp.tool()
    async def dienst_status() -> dict:
        """Zeigt, welcher Codestand gerade laeuft.

        Die Kontrolle nach einem dienst_aktualisieren: Steht hier der
        erwartete Commit, ist die Korrektur aktiv.
        """
        return {
            "version": __version__,
            "code": selbstpflege.stand(),
            "einstellungen": {
                "cache_ttl_s": einstellungen().cache_ttl_s,
                "min_abstand_s": einstellungen().min_abstand_s,
                "max_parallel": einstellungen().max_parallel,
            },
        }

    @mcp.tool()
    async def buchungssysteme_liste() -> dict:
        """Zeigt die konfigurierten Buchungssysteme und ihren Pruefstand.

        'geprueft: false' heisst, dass der Deeplink aus der URL-Struktur
        abgeleitet, aber nie gegen die Live-Seite bestaetigt wurde. Solche
        Eintraege liefern im Zweifel leere Ergebnisse und sollten einmal mit
        buchungsstrecke_pruefen verifiziert werden.
        """
        return {
            "config_version": lade_config().get("version", "?"),
            "einstellungen": {
                "cache_ttl_s": einstellungen().cache_ttl_s,
                "min_abstand_s": einstellungen().min_abstand_s,
                "timeout_ms": einstellungen().timeout_ms,
                "debug_verzeichnis": str(einstellungen().debug_verzeichnis),
            },
            "systeme": [
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
