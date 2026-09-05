# nordlicht-rates

Zimmerkategorien mit Preisen direkt aus der Buchungsmaschine eines Hauses — per
Headless-Browser, als MCP-Tools für den NAS-Server.

## Das konkrete Problem

Aus der Übergabe: Der Preis der Kategorie **„Sky View Cabin Deluxe" (mit privatem
Whirlpool)** der Northern Lights Ranch für den 22.–24.2.2027 war nicht zu ermitteln.
Daran ist die Recherche gescheitert — und zwar systematisch:

| Tool | Warum es hier nicht reicht |
|---|---|
| `hotel_price_search` | Google Hotels nennt je Plattform nur den *günstigsten verfügbaren* Preis, nie die Kategorieliste. Für die Ranch kam 1.430 € zurück — die **Superior ohne** Whirlpool. Die Deluxe taucht in den Daten gar nicht auf. |
| `hotel_availability` | Kann nur WebHotelier. Keines der drei relevanten Häuser nutzt das. |

Die Frage „was kostet die Kategorie **mit** Whirlpool" ist mit einem Ab-Preis
prinzipiell nicht zu beantworten. Dafür braucht es die Kategorieliste des Hauses
selbst — und die gibt es nur mit ausgeführtem JavaScript.

## Warum Headless-Browser und nicht weiteres Endpoint-Raten

Die Übergabe dokumentiert vier Sackgassen bei der Mews-API (leere Antworten,
404 auf `configurations/get`, Loader ohne API-Pfade). Die Schlussfolgerung dort
war richtig: Der Distributor gibt ohne ausgeführtes JavaScript nichts heraus.

Dieses Modul dreht den Spieß um — statt die API zu erraten, wird der Browser sie
für uns aufrufen lassen und **die Antwort mitgeschnitten**. Vier Ebenen, absteigend
nach Verlässlichkeit; jede Kategorie trägt im Feld `quelle`, woher sie kam:

1. **`netzwerk`** — die JSON-Antwort, aus der die Buchungsstrecke ihre Preise selbst
   rendert (bei Mews: `booking-engine.services.mews.com`). Stabilste Quelle: liefert
   Kategoriename, Währung, Verpflegung und Stornoregel bereits sauber getrennt.
2. **`state`** — eingebetteter Anwendungs-State (`__NEXT_DATA__`, `__NUXT__`).
3. **`jsonld`** — schema.org, meist nur ein Ab-Preis.
4. **`dom`** — Textheuristik. Letzte Wahl; kann einen Vergleichspreis erwischen.

Zwei weitere Kniffe:

**Deeplink statt Kalender-Klicken.** Die Datumsauswahl durchzuklicken ist der
bruchanfälligste Teil jeder Buchungsautomatisierung. Stattdessen wird eine URL
gebaut, die direkt auf die Ergebnisliste springt. Vorlagen in `config/engines.yaml`.

**Widget-Verfolgung.** `theranch.fi/check-availability/` zeigt selbst keinen Preis —
die Zimmer kommen aus einem Mews-Distributor auf fremder Domain. Findet der erste
Abruf nichts, sucht das Modul im Markup nach eingebetteten Buchungsmaschinen
(Mews-GUIDs, UpperBooking, Buchungs-iframes) und öffnet diese direkt.

## Die Tools

### `hotel_room_categories`
Der Hauptfall, Signatur wie in der Übergabe spezifiziert:

```
hotel_room_categories(
  buchungsseite = "https://theranch.fi/check-availability/",
  check_in      = "2027-02-22",
  naechte       = 2,
  adults        = 2)
```

Rückgabe (Feldnamen nach Konvention des NAS-Servers):

```json
{
  "hotel": "Northern Lights Ranch",
  "system": "mews",
  "check_in": "2027-02-22", "check_out": "2027-02-24", "naechte": 2,
  "waehrung": "EUR",
  "guenstigste_kategorie": "Sky View Cabin Superior",
  "preis_ab": 1430.0,
  "gefunden": 3,
  "kategorien": [
    {"name": "Sky View Cabin Deluxe", "preis_gesamt": 1980.0,
     "preis_pro_nacht": 990.0, "groesse_m2": 25,
     "ausstattung": ["privater Whirlpool", "Glasdach", "Terrasse"],
     "verpflegung": "Breakfast included", "stornierbar": true,
     "verfuegbar": true, "quelle": "netzwerk"}
  ]
}
```

Das Feld `ausstattung` ist hier das Entscheidende: Es trennt Superior von Deluxe
von Ultimate, was über den Preis allein nicht geht. Stichworte in Englisch,
Finnisch und Deutsch, weil dieselbe Buchungsmaschine je nach Spracheinstellung
anders ausliefert.

### `reise_preise`
Beide Unterkünfte der Route in einem Browserlauf — Break Sokos (Nächte 1–2) und
die Glashütte (Nächte 3–4):

```
reise_preise(etappen = [
  {"ort": "Levi",   "buchungsseite": "...", "check_in": "2027-02-20", "naechte": 2},
  {"ort": "Köngäs", "buchungsseite": "...", "check_in": "2027-02-22", "naechte": 2},
])
```

### `buchungsstrecke_pruefen`
Diagnose, wenn nichts herauskommt: erkanntes System, probierte Deeplinks, Zahl der
mitgeschnittenen JSON-Antworten, gefundene Mews-Distributoren, Treffer je
Extraktionsebene — plus Screenshot und HTML-Dump.

### `buchungssysteme_liste`
Die 14 konfigurierten Systeme und welche davon verifiziert sind.

## Installation auf der NAS

```bash
git clone <repo> && cd nordlicht-rates
cp .env.example .env
docker compose build
docker compose up -d
```

Das Basisimage `mcr.microsoft.com/playwright/python:v1.56.0-noble` bringt Chromium
samt Systembibliotheken mit. **`playwright install chromium --with-deps` ist damit
nicht nötig** — der Schritt aus der Übergabe entfällt.

Zwei Einstellungen sind nicht kosmetisch:

- `shm_size: 512mb` — der Docker-Standard von 64 MB lässt Chromium willkürlich abstürzen.
- `mem_limit: 1024m` — zur RAM-Frage aus der Übergabe: Die ~1 GB Browser-Binaries sind
  **Plattenplatz im Image**, nicht Arbeitsspeicher. Zur Laufzeit braucht ein Chromium
  mit ein bis drei Tabs rund 300–600 MB. Auf einer 2-GB-Synology geht das, aber ohne
  Reserve — deshalb der Deckel, und deshalb läuft der Browser hier als *ein* Prozess
  über alle Abrufe hinweg statt pro Anfrage neu zu starten. Wenn es eng wird:
  `NORDLICHT_MAX_PARALLEL` niedrig halten und `reise_preise` statt vieler Einzelabrufe
  nutzen.

### In den bestehenden Server einhängen

```python
from nordlicht_rates import register
register(mcp)
```

Dann muss Chromium allerdings auf der NAS selbst laufen — der eigene Container ist
der ruhigere Weg. Beide Varianten funktionieren mit MCP-SDK 1.x (`FastMCP`) und
2.x (`MCPServer`); `server.py` sucht sich die passende Klasse. Der Container ist auf
1.x gepinnt, passend zum bestehenden NAS-Server.

## Erster Lauf: der offene Testfall

```
buchungsseite: https://theranch.fi/check-availability/
check_in: 2027-02-22
naechte: 2
adults: 2
```

Erwartung laut Übergabe: mindestens Standard, Superior, Deluxe, Ultimate — Deluxe
und Ultimate mit Whirlpool, Ultimate zusätzlich mit Sauna.

Kommt nichts zurück, `buchungsstrecke_pruefen` mit derselben URL aufrufen. Die drei
Distributor-GUIDs des Hauses sind bekannt und lassen sich zur Not direkt als
`buchungsseite` übergeben:

```
https://app.mews.com/distributor/fab92ee0-3fcd-401b-8539-b0900078ac94
https://app.mews.com/distributor/0ac5c0a8-0c14-44d3-8f41-81e40ad00acd
https://app.mews.com/distributor/5557d5eb-e560-4721-b145-9f500b4e6d18
```

## Kalibrierung

`config/engines.yaml` kennt 14 Buchungssysteme. Bei den meisten steht
`geprueft: false`: Die Deeplink-Parameter sind aus der URL-Struktur der jeweiligen
Software abgeleitet, aber **nicht gegen die Live-Seite verifiziert** — die
Egress-Policy der Entwicklungsumgebung blockte `theranch.fi`, `app.mews.com`,
`upperbooking.com` und `sokoshotels.fi` sämtlich mit 403. Verifiziert sind
`webhotelier` und der generische Fallback.

Der Weg zur Korrektur:

1. `buchungsstrecke_pruefen` aufrufen, Feld `naechster_schritt` lesen.
2. Keine JSON-Antworten → Deeplink stimmt nicht. Screenshot ansehen: Wurde die
   Ergebnisliste überhaupt geladen?
3. Die echten Parameter aus der Adresszeile abschreiben, `deeplink`-Zeile in
   `config/engines.yaml` korrigieren, `geprueft: true` setzen.
4. `config/` ist als Volume gemountet — **kein Rebuild nötig**.

Kamen JSON-Antworten an, wurde daraus aber nichts extrahiert, fehlt der
Preisschlüssel der Maschine in `_PREIS_SCHLUESSEL` in `src/nordlicht_rates/extract.py`.

### Die drei Häuser der Reise

| Haus | System | Stand |
|---|---|---|
| Northern Lights Ranch | `mews` | GUIDs bekannt, Widget-Verfolgung implementiert |
| Northern Lights Village Levi | `upperbooking` | Deeplink geraten |
| Break Sokos Hotel Levi | `sokos` | Deeplink geraten; laut Recherche war Expedia für dasselbe Zimmer ohnehin deutlich günstiger — hier vor allem zum Gegenprüfen der Kategorie |

## Was das Modul nicht tut

- **Keine Umgehung von Bot-Schutz**, keine CAPTCHA-Lösung, keine Tarnung. Weist eine
  Seite den Zugriff ab, steht das als Hinweis im Ergebnis und der Preis ist von Hand
  zu prüfen.
- **Nicht buchen.** Es wird gelesen, nie ein Formular abgeschickt, nie angemeldet.
- **Ein Zugriff pro Host gleichzeitig**, Mindestabstand 4 s, Ergebnis-Cache 6 h
  (wie in der Übergabe vorgeschlagen).

## Ehrliche Grenzen

- Ein leeres Ergebnis heißt **nicht** automatisch „ausgebucht" — genau der Fehlschluss,
  der in der bisherigen Recherche bei Levin Iglut, Arctic Fox Igloos und anderen
  drohte. Dafür gibt es `hinweise` und `buchungsstrecke_pruefen`.
- `quelle: "dom"` ist geraten. Für eine belastbare Aussage zur Ausstattung braucht es
  `netzwerk` oder `state`.
- `ausstattung` ist Stichworterkennung, kein Vertrag. Was die Buchungsseite nicht
  schreibt, findet das Modul nicht.
- Kettenpreise sind Tagespreise ohne Mitgliedsrabatt (S-Card, Scandic Friends).

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

102 Tests, davon 12 End-to-End durch echtes Chromium gegen einen lokalen
Fake-Buchungsserver (`tests/fake_hotel.py`), der das Verhalten echter Strecken
nachbildet: leeres HTML, Zimmer per `fetch()` nachgeladen, plus eine Widget-Seite
ohne eigene Preise. Nur so wird der Netzwerk-Mitschnitt tatsächlich geprüft und
nicht bloß statisches HTML.

Kein Test greift auf eine echte Hotelseite zu — die Suite läuft offline.

## Was noch ungetestet ist

- **Der Docker-Build.** Kein Docker-Daemon in der Entwicklungsumgebung. Der übliche
  Stolperstein ist abgeräumt: `playwright==1.56.0` passt zum Image-Tag `v1.56.0-noble`
  (Chromium-Build 1194). Bei Versionswechsel **beide zusammen** ändern.
- **Alle Deeplinks außer WebHotelier** — siehe „Kalibrierung".

Getestet ist die gesamte Kette darunter: Deeplink-Bau, Browserstart,
Response-Mitschnitt, alle vier Extraktionsebenen, GUID- und iframe-Erkennung,
Ausstattungs- und Währungslogik sowie die Registrierung der Tools am MCP-Server.
