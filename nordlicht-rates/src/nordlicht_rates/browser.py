"""Playwright-Steuerung: Seite laden, XHR mitschneiden, DOM auslesen.

Der Mitschnitt ist der wichtigere Teil. Eine Buchungsstrecke rendert ihre
Preise aus einer JSON-Antwort; diese Antwort abzufangen ist deutlich stabiler,
als das fertige HTML zu interpretieren - sie aendert sich seltener als das
Markup und enthaelt Zimmername, Waehrung und Stornoregel bereits sauber
getrennt.

Bewusst nicht enthalten: Umgehung von Bot-Schutz, CAPTCHA-Loesung oder
Tarnung. Blockt eine Seite den Zugriff, wird das gemeldet, nicht umgangen.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from .config import Einstellungen, einstellungen, schreibbares_debug_verzeichnis

# Ressourcen, die nur Zeit und Bandbreite kosten. Stylesheets bleiben erlaubt,
# weil manche Strecken Elemente per CSS ein-/ausblenden und die DOM-Heuristik
# sonst ausgeblendete Preise mitliest.
_BLOCKIERTE_TYPEN = {"image", "media", "font"}

_MAX_JSON_BYTES = 4_000_000


@dataclass
class SeitenErgebnis:
    url: str
    end_url: str
    status: int | None
    html: str
    json_antworten: list[dict] = field(default_factory=list)
    dom_kandidaten: list[dict] = field(default_factory=list)
    titel: str = ""
    screenshot: str | None = None
    html_dump: str | None = None
    blockiert: bool = False
    fehler: str | None = None


class _Drossel:
    """Ein Zugriff pro Host zur Zeit, mit Mindestabstand.

    Kein Schutzmechanismus fuer uns, sondern Anstand gegenueber kleinen
    Hotelseiten: Parallelabrufe auf dieselbe Buchungsmaschine bringen nichts
    und fallen auf.
    """

    def __init__(self, min_abstand_s: float):
        self.min_abstand_s = min_abstand_s
        self._sperren: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._zuletzt: dict[str, float] = {}

    async def __call__(self, host: str):
        return self._Kontext(self, host)

    class _Kontext:
        def __init__(self, drossel: "_Drossel", host: str):
            self.drossel = drossel
            self.host = host

        async def __aenter__(self):
            await self.drossel._sperren[self.host].acquire()
            vergangen = time.monotonic() - self.drossel._zuletzt.get(self.host, 0.0)
            if vergangen < self.drossel.min_abstand_s:
                await asyncio.sleep(self.drossel.min_abstand_s - vergangen)
            return self

        async def __aexit__(self, *_):
            self.drossel._zuletzt[self.host] = time.monotonic()
            self.drossel._sperren[self.host].release()
            return False


# DOM-Heuristik: liefert nur Rohtext-Paare; Preise werden in Python geparst,
# damit die Logik testbar bleibt und nicht in einem JS-String verschwindet.
_DOM_SKRIPT = """
(selektoren) => {
  const sichtbar = (el) => {
    const s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0')
      return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const text = (el) => (el ? (el.innerText || el.textContent || '').trim() : '');
  const karten = Array.from(document.querySelectorAll(selektoren.karte || 'article'))
    .filter(sichtbar)
    .slice(0, 200);
  const raus = [];
  for (const karte of karten) {
    const kartenText = text(karte);
    if (!kartenText || kartenText.length > 1500) continue;
    const nameEl = karte.querySelector(selektoren.name || 'h2, h3');
    const preisEls = Array.from(
      karte.querySelectorAll(selektoren.preis || '[class*="price"]')
    ).filter(sichtbar);
    const name = text(nameEl);
    const preisTexte = preisEls.map(text).filter(Boolean);
    if (!name && !preisTexte.length) continue;
    raus.push({
      name: name.slice(0, 200),
      preis_texte: preisTexte.slice(0, 6),
      karten_text: kartenText.slice(0, 400),
    });
  }
  return raus;
}
"""

# Formulierungen, an denen sich eine Blockade erkennen laesst. Wichtig fuer
# ehrliche Ergebnisse: "keine Zimmer gefunden" darf nicht als "ausgebucht"
# durchgehen, wenn in Wahrheit eine Bot-Sperre griff.
_BLOCK_MARKER = (
    "access denied", "attention required", "verify you are human",
    "unusual traffic", "captcha", "request blocked", "are you a robot",
    "zugriff verweigert", "bot detection",
)


class Browser:
    """Haelt einen Chromium-Prozess ueber mehrere Abrufe hinweg offen."""

    def __init__(self, konfig: Einstellungen | None = None):
        self.konfig = konfig or einstellungen()
        self._playwright = None
        self._browser = None
        self._drossel = _Drossel(self.konfig.min_abstand_s)
        self._start_sperre = asyncio.Lock()

    async def start(self):
        async with self._start_sperre:
            if self._browser is not None:
                return
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.konfig.headless,
                args=[
                    "--disable-dev-shm-usage",  # sonst OOM im Container
                    "--no-sandbox",
                    "--disable-gpu",
                ],
            )

    async def stop(self):
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_):
        await self.stop()

    @asynccontextmanager
    async def sitzung(
        self,
        url: str,
        *,
        blockiere_bilder: bool = True,
        warte_auf: str = "networkidle",
        zusatz_wartezeit_ms: int = 1200,
    ):
        """Oeffnet eine Seite und gibt sie heraus, statt sie selbst auszulesen.

        hole() ist auf Buchungsstrecken zugeschnitten: Es schneidet JSON mit
        und wertet feste Selektoren aus. Fotos und Bewertungen brauchen etwas
        anderes - eigenes Skript, eigene Nachbehandlung, teils ein Klick auf
        einen Zustimmungsdialog. Gemeinsam bleiben Drossel, Kontextaufbau und
        das zuverlaessige Aufraeumen; genau das steckt hier drin.
        """
        await self.start()
        host = urlparse(url).hostname or "unbekannt"
        async with await self._drossel(host):
            kontext = await self._browser.new_context(
                user_agent=self.konfig.user_agent,
                locale=self.konfig.sprache,
                timezone_id=self.konfig.zeitzone,
                viewport={"width": 1440, "height": 1000},
            )
            seite = await kontext.new_page()
            seite.set_default_timeout(self.konfig.timeout_ms)

            if blockiere_bilder:
                async def route(anfrage):
                    if anfrage.request.resource_type in _BLOCKIERTE_TYPEN:
                        await anfrage.abort()
                    else:
                        await anfrage.continue_()

                await seite.route("**/*", route)

            hinweis = None
            try:
                antwort = await seite.goto(url, wait_until="domcontentloaded")
                status = antwort.status if antwort else None
                try:
                    await seite.wait_for_load_state(
                        warte_auf, timeout=min(self.konfig.timeout_ms, 20_000)
                    )
                except PlaywrightTimeout:
                    hinweis = "networkidle nicht erreicht (weiter mit Inhalt)"
                await seite.wait_for_timeout(zusatz_wartezeit_ms)
                yield seite, {"status": status, "hinweis": hinweis}
            finally:
                await kontext.close()

    async def hole(
        self,
        url: str,
        *,
        selektoren: dict,
        json_pfade: list[str],
        warte_auf: str = "networkidle",
        zusatz_wartezeit_ms: int = 1200,
        warte_auf_json: str | None = None,
        warte_auf_json_ms: int = 15_000,
        debug: bool = False,
        debug_name: str = "abruf",
    ) -> SeitenErgebnis:
        """Laedt eine URL und sammelt JSON-Antworten, DOM-Kandidaten und HTML."""
        await self.start()
        host = urlparse(url).hostname or "unbekannt"
        json_antworten: list[dict] = []

        async with await self._drossel(host):
            kontext = await self._browser.new_context(
                user_agent=self.konfig.user_agent,
                locale=self.konfig.sprache,
                timezone_id=self.konfig.zeitzone,
                viewport={"width": 1440, "height": 1000},
            )
            seite = await kontext.new_page()
            seite.set_default_timeout(self.konfig.timeout_ms)

            async def route(anfrage):
                if anfrage.request.resource_type in _BLOCKIERTE_TYPEN:
                    await anfrage.abort()
                else:
                    await anfrage.continue_()

            await seite.route("**/*", route)

            async def bei_antwort(antwort):
                try:
                    typ = (antwort.headers or {}).get("content-type", "")
                    if "json" not in typ.lower():
                        return
                    treffer = not json_pfade or any(
                        p in antwort.url for p in json_pfade
                    )
                    if not treffer:
                        return
                    roh = await antwort.body()
                    if len(roh) > _MAX_JSON_BYTES:
                        return
                    # Die Anfrage mitzuschneiden ist bei Buchungsmaschinen
                    # wichtiger als die Antwort: Eine leere Preisliste sagt
                    # nicht, ob das Haus ausgebucht ist oder ob nach dem
                    # falschen Zeitraum gefragt wurde. Erst der Rumpf der
                    # Anfrage nennt die Daten, mit denen die Maschine
                    # tatsaechlich gerechnet hat.
                    anfrage = None
                    try:
                        if antwort.request.method == "POST":
                            anfrage = antwort.request.post_data
                    except PlaywrightError:
                        pass
                    json_antworten.append(
                        {
                            "url": antwort.url,
                            "status": antwort.status,
                            "daten": json.loads(roh),
                            "anfrage": anfrage,
                        }
                    )
                except (PlaywrightError, ValueError, UnicodeDecodeError):
                    # Abgebrochene oder nicht lesbare Antworten sind normal.
                    return

            seite.on("response", bei_antwort)

            ergebnis = SeitenErgebnis(url=url, end_url=url, status=None, html="")
            try:
                antwort = await seite.goto(url, wait_until="domcontentloaded")
                ergebnis.status = antwort.status if antwort else None
                try:
                    await seite.wait_for_load_state(
                        warte_auf, timeout=min(self.konfig.timeout_ms, 20_000)
                    )
                except PlaywrightTimeout:
                    # networkidle wird von Seiten mit Dauer-Polling nie erreicht;
                    # das ist kein Fehler, der Inhalt steht meist trotzdem.
                    ergebnis.fehler = "networkidle nicht erreicht (weiter mit Inhalt)"
                await seite.wait_for_timeout(zusatz_wartezeit_ms)

                # Netzstille heisst nicht, dass die Preise da sind: Der
                # Mews-Distributor startet seine Preisabfrage erst, nachdem
                # er Verfuegbarkeit und Einschraenkungen geladen hat. Wer
                # nach der Stille aufhoert, erwischt sie mal und mal nicht -
                # derselbe Abruf lieferte so einmal Preise und einmal nicht.
                if warte_auf_json:
                    frist = time.monotonic() + warte_auf_json_ms / 1000
                    while time.monotonic() < frist:
                        if any(
                            warte_auf_json.lower() in a["url"].lower()
                            for a in json_antworten
                        ):
                            # Die Antwort ist da; kurz nachfassen, damit auch
                            # unmittelbar folgende Aufrufe noch mitkommen.
                            await seite.wait_for_timeout(800)
                            break
                        await seite.wait_for_timeout(500)
                    else:
                        ergebnis.fehler = (
                            f"'{warte_auf_json}' kam innerhalb von "
                            f"{warte_auf_json_ms} ms nicht"
                        )

                ergebnis.end_url = seite.url
                ergebnis.titel = await seite.title()
                ergebnis.html = await seite.content()
                try:
                    ergebnis.dom_kandidaten = await seite.evaluate(
                        _DOM_SKRIPT, selektoren
                    )
                except PlaywrightError as exc:
                    ergebnis.fehler = f"DOM-Auswertung fehlgeschlagen: {exc}"

                klein = (ergebnis.html or "").lower()[:200_000]
                # Ein Stichwort allein beweist nichts: "captcha" steht auf
                # vielen Buchungsseiten im eingebundenen Skript, ohne dass
                # eine Sperre greift. Erst wenn zusaetzlich keine einzige
                # JSON-Antwort ankam, ist es plausibel eine Abweisung.
                ergebnis.blockiert = ergebnis.status in (403, 429) or (
                    any(m in klein for m in _BLOCK_MARKER)
                    and not json_antworten
                )

                if debug:
                    pfad = schreibbares_debug_verzeichnis()
                    stempel = time.strftime("%Y%m%d-%H%M%S")
                    bild = pfad / f"{debug_name}-{stempel}.png"
                    dump = pfad / f"{debug_name}-{stempel}.html"
                    await seite.screenshot(path=str(bild), full_page=True)
                    dump.write_text(ergebnis.html, encoding="utf-8")
                    ergebnis.screenshot = str(bild)
                    ergebnis.html_dump = str(dump)
            except PlaywrightTimeout:
                ergebnis.fehler = (
                    f"Zeitueberschreitung nach {self.konfig.timeout_ms} ms"
                )
            except PlaywrightError as exc:
                ergebnis.fehler = f"Browserfehler: {exc}"
            finally:
                ergebnis.json_antworten = json_antworten
                await kontext.close()

        return ergebnis
