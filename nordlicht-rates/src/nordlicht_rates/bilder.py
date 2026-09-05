"""Fotos einer Unterkunft einsammeln.

Ein Preisvergleich ohne Bilder ist fuer die Entscheidung wenig wert: Ob eine
Glashuette 21 oder 42 Quadratmeter hat, sagt weniger als ein Blick auf den
Raum. Dieses Modul liest deshalb die Bilder von der Seite der Unterkunft -
Vorschaubild der sozialen Netze, Galerie, Hintergrundbilder.

Zwei Dinge sind hier bewusst so und nicht anders geloest:

Erstens wird nicht verkleinert. Das Image bringt keine Bildbibliothek mit,
und eine neue Abhaengigkeit hiesse Neubau des Containers - der laesst sich
nicht aus der Ferne ausloesen. Stattdessen wird aus dem srcset die kleinste
Fassung genommen, die noch gross genug ist; die liefert der Server ohnehin
schon fertig.

Zweitens steckt die Auswahl in reinen Python-Funktionen und nicht im
Browserskript: Logos von Fotos zu unterscheiden ist Heuristik, und Heuristik
gehoert dorthin, wo man sie mit Tests festnageln kann.
"""

from __future__ import annotations

import base64
import re
from urllib.parse import urljoin, urlparse, urlunparse

# Dateinamen, hinter denen nie ein Zimmerfoto steckt. Bewusst grosszuegig:
# Ein verworfenes Logo kostet nichts, ein Logo in der Auswahl verbraucht
# einen der wenigen Plaetze.
_DEKO = (
    "logo", "icon", "favicon", "sprite", "avatar", "placeholder", "spinner",
    "loader", "badge", "flag", "arrow", "pixel", "tracking", "banner-ad",
    "tripadvisor", "booking-com", "trustpilot", "certificate", "award-",
    "footer", "header-bg", "pattern", "texture", "watermark", "qr",
)

_ENDUNGEN = (".jpg", ".jpeg", ".png", ".webp", ".avif")

# Bildformate ohne Fotoeignung. SVG ist immer Grafik, GIF fast immer
# Animation oder Zaehlpixel.
_UNGEEIGNET = (".svg", ".gif", ".ico", ".bmp")

# WordPress und die meisten Baukaesten haengen die Groesse an den Dateinamen:
# huette-1024x683.jpg. Fuer die Dublettenpruefung muss das weg, sonst
# belegt dasselbe Motiv in fuenf Groessen die ganze Auswahl.
_GROESSENSUFFIX = re.compile(r"-\d{2,4}x\d{2,4}(?=\.[a-z]{3,4}$)", re.I)

_MAX_BYTES = 900_000


def _grundform(url: str) -> str:
    """Kennung eines Motivs, unabhaengig von Groesse und Zwischenspeicher."""
    teile = urlparse(url)
    pfad = _GROESSENSUFFIX.sub("", teile.path)
    return urlunparse(("", teile.netloc.lower(), pfad.lower(), "", "", ""))


def ist_deko(url: str) -> bool:
    """Logo, Symbol, Zaehlpixel - alles ausser einem Foto der Unterkunft."""
    if not url or url.startswith("data:"):
        return True
    klein = url.lower().split("?")[0]
    if klein.endswith(_UNGEEIGNET):
        return True
    if any(wort in klein for wort in _DEKO):
        return True
    # Winzige Kacheln erkennt man am Groessensuffix, ohne sie zu laden.
    treffer = re.search(r"-(\d{2,4})x(\d{2,4})\.[a-z]{3,4}$", klein)
    if treffer and (int(treffer.group(1)) < 300 or int(treffer.group(2)) < 200):
        return True
    return False


def variante_waehlen(srcset: str, zielbreite: int) -> tuple[str, int] | None:
    """Kleinste Fassung aus dem srcset, die noch breit genug ist.

    Das spart Bandbreite und - wenn die Bilder spaeter als Base64 durch die
    Leitung sollen - ein Vielfaches an Datenmenge, ohne dass hier irgendetwas
    umgerechnet werden muesste.
    """
    eintraege: list[tuple[str, int]] = []
    for teil in srcset.split(","):
        teil = teil.strip()
        if not teil:
            continue
        stuecke = teil.split()
        url = stuecke[0]
        breite = 0
        if len(stuecke) > 1 and stuecke[1].endswith("w"):
            try:
                breite = int(stuecke[1][:-1])
            except ValueError:
                breite = 0
        eintraege.append((url, breite))
    if not eintraege:
        return None
    passend = [e for e in eintraege if e[1] >= zielbreite]
    if passend:
        return min(passend, key=lambda e: e[1])
    return max(eintraege, key=lambda e: e[1])


def waehle_fotos(kandidaten: list[dict], anzahl: int, zielbreite: int) -> list[dict]:
    """Sortiert, entdoppelt und begrenzt die Rohfunde aus der Seite.

    Reihenfolge: Vorschaubild der sozialen Netze zuerst - das ist das Bild,
    mit dem das Haus selbst wirbt -, danach Galeriebilder nach Groesse.
    """
    rang = {"og": 0, "jsonld": 1, "img": 2, "bg": 3}
    bewertet = []
    for nummer, k in enumerate(kandidaten):
        url = (k.get("url") or "").strip()
        if not url or ist_deko(url):
            continue
        breite = int(k.get("breite") or 0)
        hoehe = int(k.get("hoehe") or 0)
        # Sehr flache oder sehr schmale Bilder sind Kopfleisten, keine Motive.
        if breite and hoehe and (breite < 260 or hoehe < 180):
            continue
        if k.get("srcset"):
            gewaehlt = variante_waehlen(k["srcset"], zielbreite)
            if gewaehlt:
                url, gemeldet = gewaehlt
                if ist_deko(url):
                    continue
                breite = gemeldet or breite
        bewertet.append(
            {
                "url": url,
                "quelle": k.get("quelle") or "img",
                "alt": (k.get("alt") or "").strip()[:160],
                "breite": breite,
                "_rang": (rang.get(k.get("quelle"), 4), -breite, nummer),
            }
        )

    bewertet.sort(key=lambda d: d["_rang"])
    gesehen: set[str] = set()
    auswahl = []
    for eintrag in bewertet:
        schluessel = _grundform(eintrag["url"])
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        eintrag.pop("_rang")
        auswahl.append(eintrag)
        if len(auswahl) >= anzahl:
            break
    return auswahl


# Die Sammlung im Browser bleibt bewusst dumm: Sie traegt zusammen, was da
# ist, und entscheidet nichts. Gefiltert wird oben in Python.
_SAMMEL_SKRIPT = """
() => {
  const raus = [];
  const nimm = (url, quelle, extra) => {
    if (!url) return;
    try { url = new URL(url, location.href).href; } catch (e) { return; }
    raus.push(Object.assign({url, quelle}, extra || {}));
  };
  for (const sel of ['meta[property="og:image"]', 'meta[property="og:image:url"]',
                     'meta[name="twitter:image"]', 'link[rel="image_src"]']) {
    for (const el of document.querySelectorAll(sel))
      nimm(el.getAttribute('content') || el.getAttribute('href'), 'og', {});
  }
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const sammle = (wert) => {
        if (!wert) return;
        if (typeof wert === 'string') nimm(wert, 'jsonld', {});
        else if (Array.isArray(wert)) wert.forEach(sammle);
        else if (typeof wert === 'object') {
          if (wert.url) nimm(wert.url, 'jsonld', {});
          if (wert.image) sammle(wert.image);
          if (wert.photo) sammle(wert.photo);
        }
      };
      const daten = JSON.parse(s.textContent);
      (Array.isArray(daten) ? daten : [daten]).forEach((d) => sammle(d.image || d.photo));
    } catch (e) { /* kaputtes JSON-LD ist haeufig und kein Grund aufzuhoeren */ }
  }
  for (const img of Array.from(document.querySelectorAll('img')).slice(0, 400)) {
    nimm(img.getAttribute('src') || img.getAttribute('data-src') ||
         img.getAttribute('data-lazy-src'), 'img', {
      srcset: img.getAttribute('srcset') || img.getAttribute('data-srcset') || '',
      alt: img.getAttribute('alt') || '',
      breite: img.naturalWidth || parseInt(img.getAttribute('width') || '0', 10) || 0,
      hoehe: img.naturalHeight || parseInt(img.getAttribute('height') || '0', 10) || 0,
    });
  }
  for (const el of Array.from(document.querySelectorAll('*')).slice(0, 3000)) {
    const bild = window.getComputedStyle(el).backgroundImage;
    if (!bild || bild === 'none') continue;
    const treffer = /url\\(["']?([^"')]+)["']?\\)/.exec(bild);
    if (treffer) {
      const r = el.getBoundingClientRect();
      nimm(treffer[1], 'bg', {breite: Math.round(r.width), hoehe: Math.round(r.height)});
    }
  }
  return {bilder: raus.slice(0, 600), titel: document.title, url: location.href};
}
"""


async def hole_fotos(
    seite_url: str,
    *,
    anzahl: int = 8,
    zielbreite: int = 640,
    als_base64: bool = False,
    browser=None,
) -> dict:
    """Liest die Fotos einer Unterkunftsseite.

    als_base64 laedt die ausgewaehlten Bilder zusaetzlich herunter und gibt
    sie als data:-URL zurueck. Das ist teuer und nur dort sinnvoll, wo die
    Bilder in eine Seite eingebettet werden sollen, die die Originaladressen
    nicht laden darf.
    """
    from .browser import Browser  # spaet, damit Tests ohne Playwright laufen

    eigener = browser is None
    browser = browser or Browser()
    ergebnis: dict = {"seite": seite_url, "fotos": []}
    try:
        # Bilder werden hier geladen: naturalWidth ist die einzige verlaessliche
        # Groessenangabe, und ohne sie landen Kopfgrafiken in der Auswahl.
        async with browser.sitzung(
            seite_url, blockiere_bilder=False, zusatz_wartezeit_ms=2000
        ) as (seite, info):
            roh = await seite.evaluate(_SAMMEL_SKRIPT)
            ergebnis["titel"] = roh.get("titel", "")
            ergebnis["geladen"] = roh.get("url", seite_url)
            ergebnis["status"] = info.get("status")
            if info.get("hinweis"):
                ergebnis["hinweis"] = info["hinweis"]
            ergebnis["gefunden"] = len(roh.get("bilder", []))
            auswahl = waehle_fotos(roh.get("bilder", []), anzahl, zielbreite)

            if als_base64:
                for foto in auswahl:
                    try:
                        antwort = await seite.request.get(foto["url"], timeout=20_000)
                        if not antwort.ok:
                            foto["daten_fehler"] = f"HTTP {antwort.status}"
                            continue
                        rohbytes = await antwort.body()
                        if len(rohbytes) > _MAX_BYTES:
                            foto["daten_fehler"] = f"{len(rohbytes)} Bytes zu gross"
                            continue
                        typ = (antwort.headers or {}).get("content-type", "image/jpeg")
                        foto["bytes"] = len(rohbytes)
                        foto["daten"] = (
                            f"data:{typ.split(';')[0]};base64,"
                            + base64.b64encode(rohbytes).decode("ascii")
                        )
                    except Exception as exc:  # Netzfehler pro Bild sind normal
                        foto["daten_fehler"] = str(exc)[:120]

            ergebnis["fotos"] = auswahl
    except Exception as exc:
        ergebnis["fehler"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        if eigener:
            await browser.stop()
    if not ergebnis["fotos"] and "fehler" not in ergebnis:
        ergebnis["hinweis"] = (
            "Keine Fotos gefunden - laedt die Galerie erst beim Scrollen "
            "oder steckt sie in einem Widget?"
        )
    return ergebnis
