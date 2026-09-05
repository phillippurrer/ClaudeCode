"""Bewertung und Zahl der Rezensionen aus Google Maps.

Warum ueberhaupt: Preise allein entscheiden nichts. Zwischen zwei Glashuetten
zum gleichen Preis liegt oft der Unterschied zwischen 4,8 bei 900 Stimmen und
4,1 bei 40 - und genau das steht in keiner Buchungsmaschine.

Die Auswertung ist zweigeteilt. Der Browser sammelt nur ein: Beschriftungen,
Kartentexte, Seitentext. Interpretiert wird in Python, weil das der Teil ist,
der bei jeder Aenderung an Googles Markup nachgezogen werden muss - und der
sich nur hier gegen feste Beispiele testen laesst.

Die Zuordnung wird immer mitgeliefert: 'namensaehnlichkeit' sagt, wie sicher
der gefundene Eintrag der gesuchte ist. Eine Bewertung ohne diese Angabe
waere eine Behauptung, keine Auskunft.
"""

from __future__ import annotations

import difflib
import re
from urllib.parse import quote_plus

# "4.7 stars 1,234 reviews", "4,7 Sterne 1.234 Rezensionen" und die
# Kurzfassung ohne Stimmenzahl.
_STERNE = re.compile(
    r"(\d[.,]\d)\s*(?:stars?|Sterne?|estrellas?|étoiles?|tähteä)"
    r"(?:\s*(?:aus|of|von)\s*5)?"
    r"(?:[^\d]{0,20}([\d.,  ]{1,12})\s*"
    r"(?:reviews?|Rezensionen|Bewertungen|avis|reseñas|arvostelua))?",
    re.I,
)
# Im Seitentext steht die Bewertung als "4,7" mit der Stimmenzahl in Klammern.
_TEXTFORM = re.compile(r"(?<![\d.,])(\d[.,]\d)\s*\n?\s*\(\s*([\d.,  ]{1,12})\s*\)")


def _zahl(text: str | None) -> int | None:
    """Stimmenzahl aus '1,234' wie aus '1.234' - Trennzeichen sind Deko."""
    if not text:
        return None
    sauber = re.sub(r"[., \s]", "", text)
    return int(sauber) if sauber.isdigit() else None


def _note(text: str) -> float | None:
    try:
        wert = float(text.replace(",", "."))
    except (TypeError, ValueError):
        return None
    return wert if 0.0 < wert <= 5.0 else None


def lies_beschriftung(label: str) -> tuple[float | None, int | None]:
    """Note und Stimmenzahl aus einer aria-Beschriftung."""
    treffer = _STERNE.search(label or "")
    if not treffer:
        return None, None
    return _note(treffer.group(1)), _zahl(treffer.group(2))


def _normiert(text: str) -> str:
    text = (text or "").lower()
    for alt, neu in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("å", "a"), ("é", "e")):
        text = text.replace(alt, neu)
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def aehnlichkeit(gesucht: str, gefunden: str) -> float:
    """Wie gut passt der gefundene Eintrag zum gesuchten Haus?

    Reiner Zeichenvergleich taugt hier nicht: "Northern Lights Ranch" und
    "Northern Lights Village Levi" sind zeichenweise fast gleich und trotzdem
    zwei Haeuser, 200 km auseinander. Entscheidend ist, ob JEDES Wort des
    gesuchten Namens im gefundenen vorkommt - ein fehlendes Wort wiegt
    deshalb doppelt. Zusaetzliche Woerter im Fund sind dagegen harmlos, das
    ist meist nur der Ort ("Apukka Resort Rovaniemi").
    """
    a, b = _normiert(gesucht), _normiert(gefunden)
    if not a or not b:
        return 0.0
    zeichen = difflib.SequenceMatcher(None, a, b).ratio()
    woerter = set(a.split())
    im_fund = set(b.split())
    abdeckung = len(woerter & im_fund) / len(woerter)
    punkte = 0.35 * zeichen + 0.65 * abdeckung
    if abdeckung < 1.0:
        punkte *= abdeckung
    return round(punkte, 3)


def _name_der_karte(eintrag: dict) -> str:
    name = (eintrag.get("name") or "").strip()
    if name:
        return name[:120]
    text = (eintrag.get("karten_text") or "").strip()
    return text.splitlines()[0][:120] if text else ""


def werte_aus(roh: dict, gesucht: str) -> dict:
    """Baut aus den Rohfunden der Seite eine Auskunft mit Guetemass."""
    treffer = []
    for eintrag in roh.get("treffer") or []:
        note, stimmen = lies_beschriftung(eintrag.get("label", ""))
        if note is None:
            continue
        if stimmen is None:
            stimmen = _zahl(
                (re.search(r"\(([\d.,  ]{1,12})\)",
                           eintrag.get("karten_text") or "") or [None, None])[1]
            )
        name = _name_der_karte(eintrag)
        treffer.append(
            {
                "name": name,
                "bewertung": note,
                "stimmen": stimmen,
                "namensaehnlichkeit": aehnlichkeit(gesucht, name),
                "href": eintrag.get("href"),
            }
        )

    if not treffer:
        # Rueckfall auf den Seitentext: Auf der Ortsseite steht die Note gross
        # neben der Stimmenzahl in Klammern, ganz ohne eigene Beschriftung.
        text = roh.get("text") or ""
        aus_text = _TEXTFORM.search(text)
        if aus_text:
            note = _note(aus_text.group(1))
            if note is not None:
                name = (roh.get("titel") or "").split(" - ")[0].strip()
                treffer.append(
                    {
                        "name": name,
                        "bewertung": note,
                        "stimmen": _zahl(aus_text.group(2)),
                        "namensaehnlichkeit": aehnlichkeit(gesucht, name),
                        "quelle": "seitentext",
                    }
                )

    if not treffer:
        return {
            "gesucht": gesucht,
            "gefunden": False,
            "hinweis": "Kein Eintrag mit Bewertung auf der Kartenseite gefunden.",
        }

    treffer.sort(key=lambda t: (-t["namensaehnlichkeit"], -(t["stimmen"] or 0)))
    bester = treffer[0]
    antwort = {
        "gesucht": gesucht,
        "gefunden": True,
        "name": bester["name"],
        "bewertung": bester["bewertung"],
        "stimmen": bester["stimmen"],
        "namensaehnlichkeit": bester["namensaehnlichkeit"],
        "maps_url": bester.get("href") or roh.get("url"),
    }
    if bester["namensaehnlichkeit"] < 0.55:
        antwort["hinweis"] = (
            f"Zuordnung unsicher: gesucht '{gesucht}', gefunden "
            f"'{bester['name']}'. Nicht ungeprueft uebernehmen."
        )
    for t in treffer:
        t.pop("href", None)
    weitere = [t for t in treffer[1:4] if t["namensaehnlichkeit"] > 0.3]
    if weitere:
        antwort["weitere_treffer"] = weitere
    return antwort


_SAMMEL_SKRIPT = """
() => {
  const sterne = /([0-9][.,][0-9])\\s*(star|Stern|estrella|étoile|tähte)/i;
  const treffer = [];
  const gesehen = new Set();

  // Der verlaessliche Anker in der Trefferliste ist der Link zum Ort: Seine
  // Beschriftung IST der Name des Hauses. Von dort aus nach oben zu laufen,
  // bis der Kasten auch die Sterne enthaelt, kommt ohne Googles verwuerfelte
  // Klassennamen aus - die aendern sich staendig.
  for (const link of document.querySelectorAll('a[href*="/maps/place/"]')) {
    const name = (link.getAttribute('aria-label') || '').trim();
    if (!name || gesehen.has(name)) continue;
    let kasten = link;
    let label = '';
    for (let i = 0; i < 6 && kasten; i++) {
      for (const el of kasten.querySelectorAll('[aria-label]')) {
        const l = el.getAttribute('aria-label') || '';
        if (sterne.test(l)) { label = l; break; }
      }
      if (label) break;
      kasten = kasten.parentElement;
    }
    if (!label) continue;
    gesehen.add(name);
    treffer.push({
      label: label.slice(0, 200),
      name: name.slice(0, 160),
      href: link.href,
      karten_text: kasten ? (kasten.innerText || '').slice(0, 300) : '',
    });
    if (treffer.length >= 30) break;
  }

  // Einzelner Ort statt Trefferliste: Dann gibt es keinen Link, sondern eine
  // Ueberschrift und die Sterne daneben.
  const h1 = document.querySelector('h1');
  if (!treffer.length && h1) {
    for (const el of document.querySelectorAll('[aria-label]')) {
      const l = el.getAttribute('aria-label') || '';
      if (!sterne.test(l)) continue;
      treffer.push({
        label: l.slice(0, 200),
        name: (h1.innerText || '').trim().slice(0, 160),
        karten_text: (document.body.innerText || '').slice(0, 400),
      });
      break;
    }
  }

  return {
    treffer,
    titel: document.title,
    ueberschrift: h1 ? (h1.innerText || '').trim().slice(0, 160) : '',
    url: location.href,
    text: (document.body.innerText || '').slice(0, 6000),
  };
}
"""

# Ein Zustimmungsdialog steht in der EU vor jeder Kartenseite. Abgelehnt wird
# alles, was ablehnbar ist - fuer eine oeffentliche Bewertung braucht es
# keine Zustimmung zu Werbecookies.
_ZUSTIMMUNG = (
    "Alle ablehnen", "Reject all", "Ablehnen", "Reject",
    "Alle akzeptieren", "Accept all",
)


async def hole_bewertung(name: str, ort: str | None = None, *, browser=None) -> dict:
    """Sucht ein Haus auf Google Maps und liest Note und Stimmenzahl."""
    from .browser import Browser  # spaet, damit Tests ohne Playwright laufen

    name = (name or "").strip()
    if not name:
        return {"fehler": "name fehlt"}
    # Der Ort gehoert in die Suche, aber nicht in den Namensvergleich: "Levi
    # Finnland" steht in keinem Hotelnamen und wuerde jede Aehnlichkeit
    # verwaessern - ausgerechnet das Mass, an dem die Zuordnung haengt.
    suche = f"{name} {ort}".strip() if ort else name

    eigener = browser is None
    browser = browser or Browser()
    try:
        url = f"https://www.google.com/maps/search/{quote_plus(suche)}?hl=en"
        async with browser.sitzung(url, zusatz_wartezeit_ms=2500) as (seite, info):
            if "consent." in seite.url or "/sorry/" in seite.url:
                for beschriftung in _ZUSTIMMUNG:
                    try:
                        knopf = seite.get_by_role("button", name=beschriftung)
                        if await knopf.count():
                            await knopf.first.click(timeout=5_000)
                            await seite.wait_for_timeout(3_000)
                            break
                    except Exception:
                        continue
            if "/sorry/" in seite.url:
                return {
                    "gesucht": suche,
                    "gefunden": False,
                    "blockiert": True,
                    "hinweis": "Google hat den Zugriff abgewiesen - nicht umgangen.",
                }
            roh = await seite.evaluate(_SAMMEL_SKRIPT)
    except Exception as exc:
        return {"gesucht": suche, "fehler": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        if eigener:
            await browser.stop()

    ergebnis = werte_aus(roh, name)
    ergebnis["gesucht"] = suche
    return ergebnis
