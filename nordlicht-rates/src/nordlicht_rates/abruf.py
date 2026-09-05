"""Orchestrierung: von der Hotel-URL zum Preisergebnis.

Ablauf je Abruf:
  1. Engine anhand des Hosts erkennen
  2. Deeplink-Kandidaten bauen (bester zuerst)
  3. Kandidaten der Reihe nach laden, bis Angebote gefunden sind
  4. Angebote aus Netzwerk-JSON, State, JSON-LD und DOM zusammenfuehren
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

from .browser import Browser, SeitenErgebnis
from .cache import TTLCache
from .config import einstellungen, lade_config
from .dates import Zeitraum
from .engines import Engine, baue_urls, erkenne_engine
from .extract import (
    angebote_aus_json,
    angebote_aus_jsonld,
    angebote_aus_state,
    entdoppel,
)
from .models import PreisErgebnis, Zimmerangebot
from .money import (
    KRONEN,
    PreisFehler,
    ist_plausibler_zimmerpreis,
    parse_alle_preise,
    pro_nacht,
)

_CACHE = TTLCache(ttl_s=einstellungen().cache_ttl_s)


def _land_fuer(engine: Engine, url: str) -> str | None:
    """Loest ein blankes 'kr' auf - erst ueber die Engine, dann ueber die TLD."""
    if engine.land:
        return engine.land
    host = (urlparse(url).hostname or "").lower()
    for tld, land in (
        (".no", "no"), (".se", "se"), (".dk", "dk"), (".is", "is"), (".fi", "fi")
    ):
        if host.endswith(tld):
            return land
    return None


def angebote_aus_dom(
    kandidaten: list[dict], *, naechte: int, land: str | None
) -> list[Zimmerangebot]:
    """Macht aus den DOM-Rohtexten Angebote.

    Je Karte wird der kleinste plausible Betrag genommen: Buchungsstrecken
    zeigen daneben gern durchgestrichene Vergleichspreise, und der niedrigere
    ist der tatsaechlich buchbare.
    """
    ergebnis: list[Zimmerangebot] = []
    for kandidat in kandidaten:
        name = (kandidat.get("name") or "").strip()
        if not name:
            continue
        betraege = []
        for text in kandidat.get("preis_texte") or []:
            try:
                betraege.extend(parse_alle_preise(text, land))
            except PreisFehler:
                continue
        plausibel = [b for b in betraege if ist_plausibler_zimmerpreis(b, naechte)]
        if not plausibel:
            continue
        guenstigster = min(plausibel, key=lambda b: b.wert)
        ergebnis.append(
            Zimmerangebot(
                name=name[:120],
                gesamtpreis=guenstigster,
                preis_pro_nacht=pro_nacht(guenstigster, naechte)
                if naechte > 1
                else None,
                quelle="dom",
            )
        )
    return ergebnis


def _sammle(
    seite: SeitenErgebnis, *, naechte: int, land: str | None
) -> list[Zimmerangebot]:
    angebote: list[Zimmerangebot] = []
    for antwort in seite.json_antworten:
        angebote.extend(
            angebote_aus_json(
                antwort["daten"], naechte=naechte, quelle="netzwerk"
            )
        )
    if seite.html:
        angebote.extend(angebote_aus_state(seite.html, naechte=naechte))
        angebote.extend(angebote_aus_jsonld(seite.html, naechte=naechte))
    angebote.extend(
        angebote_aus_dom(seite.dom_kandidaten, naechte=naechte, land=land)
    )
    return entdoppel(angebote)


def _cache_schluessel(url, zeit, adults, children, zimmer) -> str:
    return "|".join(
        [url, zeit.check_in.isoformat(), str(zeit.naechte),
         str(adults), str(children), str(zimmer)]
    )


async def hole_preise(
    url: str,
    zeit: Zeitraum,
    *,
    adults: int = 2,
    children: int = 0,
    zimmer: int = 1,
    hotel_id: str | None = None,
    engine_id: str | None = None,
    debug: bool = False,
    browser: Browser | None = None,
    cache_nutzen: bool = True,
) -> PreisErgebnis:
    """Holt Zimmerpreise fuer eine Hotel-URL und einen Zeitraum."""
    from .engines import engine_nach_id

    begonnen = time.monotonic()
    schluessel = _cache_schluessel(url, zeit, adults, children, zimmer)
    if cache_nutzen and not debug:
        zwischengespeichert = _CACHE.hole(schluessel)
        if zwischengespeichert is not None:
            zwischengespeichert.aus_cache = True
            return zwischengespeichert

    engine = (engine_nach_id(engine_id) if engine_id else None) or erkenne_engine(url)
    land = _land_fuer(engine, url)
    standard = lade_config().get("defaults", {})
    kandidaten = baue_urls(
        engine, url, zeit,
        adults=adults, children=children, zimmer=zimmer, hotel_id=hotel_id,
    )

    ergebnis = PreisErgebnis(
        hotel=(urlparse(url).hostname or url),
        url=url,
        engine=engine.id,
        zeitraum=zeit.als_dict(),
        belegung={"adults": adults, "children": children, "zimmer": zimmer},
    )
    if not engine.geprueft:
        ergebnis.warnungen.append(
            f"Deeplink fuer '{engine.id}' ist nicht gegen die Live-Seite "
            "verifiziert (geprueft: false in engines.yaml). Bei leerem "
            "Ergebnis buchungsstrecke_pruefen aufrufen."
        )

    eigener_browser = browser is None
    browser = browser or Browser()
    versuche: list[dict] = []
    try:
        # Hoechstens drei Kandidaten - danach ist die Vorlage falsch, nicht die
        # Seite langsam, und weitere Versuche belasten nur die Gegenseite.
        for kandidat in kandidaten[:3]:
            seite = await browser.hole(
                kandidat,
                selektoren=engine.selektoren,
                json_pfade=engine.json_pfade,
                warte_auf=standard.get("warte_auf", "networkidle"),
                zusatz_wartezeit_ms=standard.get("zusatz_wartezeit_ms", 1200),
                debug=debug,
                debug_name=f"{engine.id}-{zeit.check_in.isoformat()}",
            )
            angebote = _sammle(seite, naechte=zeit.naechte, land=land)
            versuche.append(
                {
                    "url": kandidat,
                    "status": seite.status,
                    "json_antworten": len(seite.json_antworten),
                    "dom_karten": len(seite.dom_kandidaten),
                    "angebote": len(angebote),
                    "fehler": seite.fehler,
                }
            )
            # Vor dem moeglichen Abbruch sichern - gerade bei einer Sperre ist
            # der Screenshot das Interessanteste.
            if debug and seite.screenshot:
                ergebnis.debug["screenshot"] = seite.screenshot
                ergebnis.debug["html"] = seite.html_dump
            if seite.blockiert:
                ergebnis.warnungen.append(
                    f"Die Seite hat den Zugriff abgewiesen (Status {seite.status}). "
                    "Das wird hier nicht umgangen - Preis bitte manuell pruefen."
                )
                break
            if angebote:
                ergebnis.angebote = angebote[: einstellungen().max_angebote]
                ergebnis.url = seite.end_url
                ergebnis.hotel = seite.titel or ergebnis.hotel
                waehrungen = {
                    a.gesamtpreis.waehrung
                    for a in angebote
                    if a.gesamtpreis and a.gesamtpreis.waehrung
                }
                if len(waehrungen) == 1:
                    ergebnis.waehrung = waehrungen.pop()
                    if ergebnis.waehrung == KRONEN:
                        ergebnis.warnungen.append(
                            "Die Seite schreibt nur 'kr' - ob NOK, SEK, DKK "
                            "oder ISK gemeint ist, geht daraus nicht hervor."
                        )
                elif len(waehrungen) > 1:
                    ergebnis.warnungen.append(
                        "Mehrere Waehrungen auf der Seite gefunden "
                        f"({', '.join(sorted(waehrungen))}) - Betraege pruefen."
                    )
                break
    finally:
        if eigener_browser:
            await browser.stop()

    ergebnis.dauer_s = time.monotonic() - begonnen
    # Das Versuchsprotokoll ist Diagnosematerial. Bei einem Treffer blaeht es
    # die Antwort nur auf; bei einem leeren Ergebnis ist es die halbe Miete.
    if versuche and (debug or not ergebnis.angebote):
        ergebnis.debug["versuche"] = versuche
    if not ergebnis.angebote:
        quellen = sum(v["json_antworten"] for v in versuche)
        if quellen == 0 and not ergebnis.warnungen:
            ergebnis.warnungen.append(
                "Keine JSON-Antwort der Buchungsmaschine mitgeschnitten - "
                "vermutlich wurde die Ergebnisliste nie geladen, der Deeplink "
                "passt also nicht."
            )
    elif cache_nutzen and not debug:
        _CACHE.setze(schluessel, ergebnis)
    return ergebnis
