# nordlicht-rates

Zimmerpreise direkt von der Buchungsstrecke eines Hotels holen — per Headless-Browser,
als MCP-Tools für den NAS-Server.

## Wozu

Der NAS-Server hat für Hotels schon zwei Werkzeuge, und beide haben eine Lücke:

| Tool | Quelle | Lücke |
|---|---|---|
| `hotel_price_search` | Google Hotels über SerpAPI | Kleine Häuser in Nordnorwegen, Lappland und Island stehen dort oft gar nicht oder ohne Preis |
| `hotel_availability` | WebHotelier | Greift nur bei `book.*`-Buchungsmaschinen |

Dazwischen fällt genau das durch, was auf einer Nordlichter-Route zählt: das
Gjestehus in Kirkenes, die Lodge in Lappland, das Kettenhotel in Tromsø. Dieses
Modul öffnet deren Buchungsseite in einem echten Browser und liest die
Zimmerkategorien mit.

## Wie es Preise findet

Vier Ebenen, absteigend nach Verlässlichkeit. Jedes Angebot trägt im Feld
`quelle`, woher es kam:

1. **`netzwerk`** — die JSON-Antwort, aus der die Buchungsstrecke ihre Preise
   selbst rendert. Wird per Response-Mitschnitt abgefangen. Stabilste Quelle:
   ändert sich seltener als das Markup und liefert Zimmername, Währung,
   Verpflegung und Stornoregel bereits sauber getrennt.
2. **`state`** — in die Seite eingebetteter Anwendungs-State
   (`__NEXT_DATA__`, `__NUXT__`, `__INITIAL_STATE__`).
3. **`jsonld`** — schema.org-Angebote, meist nur ein Ab-Preis.
4. **`dom`** — Textheuristik über die gerenderte Seite. Letzte Wahl; kann einen
   durchgestrichenen Vergleichspreis erwischen.

Der eigentliche Kniff steckt davor: statt den Datumskalender durchzuklicken —
der bruchanfälligste Teil jeder Buchungsautomatisierung — wird ein **Deeplink**
gebaut, der direkt auf die Ergebnisliste springt. Die Vorlagen dafür stehen in
`config/engines.yaml`.

## Die Tools

### `hotel_direktpreise`
Der Normalfall: eine Hotel-URL, ein Zeitraum, zurück kommen die Zimmerkategorien.

```
hotel_direktpreise(
  hotelseite = "https://www.sorrisniva.no",
  check_in   = "2027-02-14",
  naechte    = 3,
  adults     = 2)
```

### `reise_preise`
Die ganze Route in einem Browserlauf — deutlich schneller als Einzelabrufe und
schonender für die Hotelseiten:

```
reise_preise(etappen = [
  {"ort": "Tromsø",   "hotelseite": "https://...", "check_in": "2027-02-14", "naechte": 3},
  {"ort": "Kirkenes", "hotelseite": "https://...", "check_in": "2027-02-17", "naechte": 2},
])
```
Summiert die Bestpreise nur, wenn alle Etappen dieselbe Währung haben — eine
Mischsumme aus NOK und EUR wäre schlicht falsch.

### `buchungsstrecke_pruefen`
Diagnose, wenn nichts herauskommt. Sagt, welche Buchungsmaschine erkannt wurde,
welche Deeplinks probiert wurden, wie viele JSON-Antworten ankamen und was jede
Extraktionsebene gefunden hätte — plus Screenshot und HTML-Dump.

### `buchungsmaschinen_liste`
Zeigt die konfigurierten Maschinen und welche davon schon verifiziert sind.

## Installation auf der NAS

```bash
git clone <repo> && cd nordlicht-rates
cp .env.example .env          # anpassen
docker compose build
docker compose up -d
```

Das Basisimage `mcr.microsoft.com/playwright/python` bringt Chromium samt aller
Systembibliotheken mit — das ist der Grund für Docker: Chromium nativ unter
DSM/QTS lauffähig zu bekommen ist ein Nachmittag Arbeit, hier sind es null Zeilen.

Zwei Docker-Einstellungen sind nicht kosmetisch: `shm_size: 512mb` (der Standard
von 64 MB lässt Chromium willkürlich abstürzen) und `mem_limit`, damit der
Browser im Zweifel nicht den Arbeitsspeicher der NAS aufbraucht.

### In den bestehenden Server einhängen

Statt eines eigenen Containers geht auch der direkte Einbau — zwei Zeilen im
vorhandenen Server:

```python
from nordlicht_rates import register
register(mcp)
```

Dann muss allerdings Chromium auf der NAS selbst laufen. Der eigene Container
ist der ruhigere Weg.

Beide Varianten funktionieren mit MCP-SDK 1.x (`FastMCP`) und 2.x (`MCPServer`);
`server.py` sucht sich die passende Klasse. Der Container ist auf 1.x gepinnt,
passend zum bestehenden NAS-Server.

## Kalibrierung — bitte einmal durchgehen

`config/engines.yaml` kennt zwölf Buchungsmaschinen. Bei den meisten steht
`geprueft: false`: Die Deeplink-Parameter sind aus der URL-Struktur der
jeweiligen Software abgeleitet, aber **nicht gegen die Live-Seite verifiziert** —
die Egress-Policy der Entwicklungsumgebung ließ keine Abrufe zu. Verifiziert
sind `webhotelier` und der generische Fallback.

Praktisch heißt das: Beim ersten echten Hotel kann ein leeres Ergebnis kommen,
obwohl Zimmer frei sind. Der Weg dahin:

1. `buchungsstrecke_pruefen` mit der Hotel-URL aufrufen.
2. Ins Feld `naechster_schritt` schauen. Kamen **keine JSON-Antworten**, stimmt
   der Deeplink nicht — Screenshot ansehen: Wurde die Ergebnisliste überhaupt
   geladen, oder steht da noch die Startseite?
3. Die echten Parameter aus der Adresszeile des Browsers abschreiben und die
   `deeplink`-Zeile der Engine in `config/engines.yaml` korrigieren.
4. `geprueft: true` setzen. `config/` ist als Volume gemountet — kein Rebuild nötig.

Kamen JSON-Antworten an, wurde daraus aber nichts extrahiert, fehlt der
Preisschlüssel der Maschine in `_PREIS_SCHLUESSEL` in `src/nordlicht_rates/extract.py`.

## Was das Modul nicht tut

- **Keine Umgehung von Bot-Schutz**, keine CAPTCHA-Lösung, keine Tarnung. Weist
  eine Seite den Zugriff ab, steht das als Warnung im Ergebnis und der Preis ist
  von Hand zu prüfen.
- **Nicht buchen.** Es wird gelesen, nie ein Formular abgeschickt und nie eine
  Anmeldung versucht.
- **Ein Zugriff pro Host gleichzeitig**, mit Mindestabstand (`NORDLICHT_MIN_ABSTAND_S`,
  Standard 4 s) und Ergebnis-Cache (Standard 15 min). Kleine Hotelseiten laufen auf
  schwacher Hardware.

## Ehrliche Grenzen

- Ein leeres Ergebnis heißt **nicht** automatisch „ausgebucht". Genau dafür gibt es
  das Feld `warnungen` und `buchungsstrecke_pruefen`.
- `quelle: "dom"` ist geraten. Für eine Zusage wie „Superior mit Meerblick inklusive
  Frühstück" reicht das nicht — dafür braucht es `netzwerk` oder `state`.
- Schreibt eine Seite nur „kr", ohne Land: Die Währung kommt dann als `"kr"` zurück,
  nicht als geratenes NOK, und eine Warnung weist darauf hin.
- Kettenpreise sind Tagespreise ohne Mitgliedsrabatt. Wer bei Scandic Friends
  oder Strawberry-Mitglied ist, zahlt weniger, als hier steht.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

70 Tests, davon 10 End-to-End durch echtes Chromium gegen einen lokalen
Fake-Buchungsserver (`tests/fake_hotel.py`), der das Verhalten echter Strecken
nachbildet: leeres HTML, Zimmer per `fetch()` nachgeladen. Nur so wird der
Netzwerk-Mitschnitt tatsächlich geprüft und nicht bloß statisches HTML.

Kein Test greift auf eine echte Hotelseite zu — die Suite läuft offline und
belästigt niemanden.

## Was noch ungetestet ist

Zwei Dinge konnten in der Entwicklungsumgebung nicht überprüft werden und
brauchen einen ersten Lauf auf der NAS:

- **Der Docker-Build.** In der Entwicklungsumgebung gab es keinen Docker-Daemon.
  Dockerfile und Compose-Datei sind ungetestet; der Playwright-Tag
  (`v1.56.0-noble`) passt zur gepinnten `playwright==1.56.0`, was der übliche
  Stolperstein ist („Executable doesn't exist"). Sollte `docker compose build`
  klemmen, ist es mit hoher Wahrscheinlichkeit hier.
- **Die Deeplinks der Ketten und Fremdmaschinen** — siehe „Kalibrierung" oben.

Getestet ist dagegen die gesamte Kette darunter: Deeplink-Bau, Browserstart,
Response-Mitschnitt, alle vier Extraktionsebenen, Währungslogik und die
Registrierung der Tools am MCP-Server.
