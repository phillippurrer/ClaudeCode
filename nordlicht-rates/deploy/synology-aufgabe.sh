#!/bin/sh
# ---------------------------------------------------------------------------
# Zum Einfuegen in den Synology-Aufgabenplaner - kein SSH, kein PC noetig.
#
#   DSM im Browser oeffnen (VPN oder Tunnel)
#   Systemsteuerung -> Aufgabenplaner -> Erstellen -> Geplante Aufgabe
#     -> Benutzerdefiniertes Script
#   Benutzer: root
#   Zeitplan: egal (die Aufgabe wird von Hand ueber "Ausfuehren" gestartet)
#   Aufgabeneinstellungen -> dieses Skript einfuegen
#   Haken bei "Ausfuehrungsdetails per E-Mail senden" setzen - so kommt die
#   Preistabelle direkt in dein Postfach, ohne dass du irgendwo nachsehen musst
#
# Danach: Aufgabe markieren -> Ausfuehren. Der erste Lauf dauert ein paar
# Minuten, weil das Playwright-Image (~1 GB) geladen wird. Spaetere Laeufe
# sind in Sekunden durch.
#
# Kurzfassung: Statt dieses ganze Skript einzufuegen, reichen im
# Aufgabenplaner auch diese vier Zeilen - sie holen den Rest selbst:
#
#   PATH=/usr/local/bin:/usr/bin:/bin:/root/.local/bin:/root/.cargo/bin:/usr/local/go/bin:/opt/node22/bin:/opt/maven/bin:/opt/gradle/bin:/opt/rbenv/bin:/root/.bun/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
#   Z=claude/nordlichter-hotel-prices-mcp-rvh5ts
#   git clone -b  --depth 1 https://github.com/phillippurrer/ClaudeCode.git #     /volume1/docker/nordlicht-rates 2>/dev/null || #     (cd /volume1/docker/nordlicht-rates && git fetch origin  && #      git reset --hard origin/)
#   CHECK_IN=2027-02-22 NAECHTE=2 sh #     /volume1/docker/nordlicht-rates/nordlicht-rates/deploy/synology-aufgabe.sh
# ---------------------------------------------------------------------------

set -u

# --- Was abgefragt wird ----------------------------------------------------
# Alle Werte lassen sich beim Aufruf ueberschreiben, ohne diese Datei zu
# aendern - am Handy der angenehmere Weg:
#     HOTEL="https://..." CHECK_IN="2027-03-06" sh synology-aufgabe.sh
HOTEL="https://theranch.fi/check-availability/"
CHECK_IN="2027-02-22"
NAECHTE="2"
ADULTS="2"

# --- Wo gearbeitet wird ----------------------------------------------------
ARBEITSORDNER="/volume1/docker/nordlicht-rates"
ZWEIG="claude/nordlichter-hotel-prices-mcp-rvh5ts"
REPO="https://github.com/phillippurrer/ClaudeCode.git"

# Der Aufgabenplaner startet mit sehr magerem PATH; docker liegt auf DSM
# ausserhalb davon.
PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PATH

echo "=========================================================="
echo " nordlicht-rates  -  $(date)"
echo "=========================================================="

echo "Benutzer: $(id -un 2>/dev/null || echo unbekannt)"

DOCKER="$(command -v docker || true)"
if [ -z "$DOCKER" ]; then
    echo "FEHLER: docker nicht gefunden."
    echo "Ist das Paket 'Container Manager' im Paket-Zentrum installiert?"
    exit 1
fi
echo "docker: $DOCKER"

# Der Socket gehoert auf DSM root. Laeuft die Aufgabe unter einem anderen
# Benutzer, scheitert erst der Build - mit einer Meldung, die das eigentliche
# Problem hinter einer Wand aus URL-kodierten Build-Parametern versteckt.
if ! docker info >/dev/null 2>&1; then
    echo
    echo "FEHLER: Kein Zugriff auf den Docker-Dienst."
    echo
    echo "Die Aufgabe laeuft als '$(id -un 2>/dev/null || echo unbekannt)',"
    echo "der Docker-Socket gehoert aber root."
    echo
    echo "So behoben:"
    echo "  Aufgabenplaner -> die Aufgabe doppelt antippen"
    echo "  -> Reiter 'Allgemein' -> Feld 'Benutzer:' auf  root  stellen"
    echo "  -> OK -> Aufgabe markieren -> Ausfuehren"
    exit 1
fi

# --- Quellcode holen -------------------------------------------------------
mkdir -p "$(dirname "$ARBEITSORDNER")" || exit 1

# Der Ordner wurde moeglicherweise von einem anderen Benutzer angelegt, die
# Aufgabe laeuft aber als root. git verweigert dann mit "dubious ownership".
# -c wirkt nur fuer diesen Aufruf und aendert keine globale Konfiguration.
GIT="git -c safe.directory=$ARBEITSORDNER"
AUSGABE=""

if [ -d "$ARBEITSORDNER/.git" ]; then
    echo "Aktualisiere vorhandene Kopie ..."
    cd "$ARBEITSORDNER" || exit 1
    AUSGABE=$($GIT fetch origin "$ZWEIG" 2>&1 && \
              $GIT checkout -f "$ZWEIG" 2>&1 && \
              $GIT reset --hard "origin/$ZWEIG" 2>&1)
    HOLEN=$?
else
    echo "Hole Quellcode ..."
    AUSGABE=$(git clone -b "$ZWEIG" --depth 1 "$REPO" "$ARBEITSORDNER" 2>&1)
    HOLEN=$?
    cd "$ARBEITSORDNER" 2>/dev/null || true
fi
echo "$AUSGABE"

if [ "$HOLEN" -ne 0 ]; then
    echo
    echo "FEHLER: Der Quellcode konnte nicht geholt werden."
    echo
    # Die Ursache steht in der git-Ausgabe - raten muss hier niemand.
    case "$AUSGABE" in
        *"dubious ownership"*|*"safe.directory"*)
            echo "Ursache: Der Ordner gehoert einem anderen Benutzer als dem,"
            echo "der die Aufgabe ausfuehrt. Einmalig behoben mit:"
            echo "  rm -rf $ARBEITSORDNER"
            echo "und einem erneuten Lauf - dann legt root ihn selbst an."
            ;;
        *"Authentication failed"*|*"could not read Username"*|*"Permission denied"*|*"403"*)
            echo "Ursache: Kein Zugriff auf das Repository."
            echo "Ein Token hinterlegen und REPO oben ersetzen:"
            echo "  REPO=\"https://<TOKEN>@github.com/phillippurrer/ClaudeCode.git\""
            echo "(Token unter github.com/settings/tokens, Rechte: nur 'repo')"
            ;;
        *"not found"*|*"does not exist"*|*"Repository not found"*)
            echo "Ursache: Repository oder Zweig nicht gefunden."
            echo "  Repo:  $REPO"
            echo "  Zweig: $ZWEIG"
            ;;
        *)
            echo "Die Meldung von git steht oben."
            ;;
    esac
    exit 1
fi

cd "$ARBEITSORDNER/nordlicht-rates" || {
    echo "FEHLER: Unterordner nordlicht-rates fehlt."
    exit 1
}

# --- Bauen -----------------------------------------------------------------
echo
echo "Baue Image (beim ersten Mal einige Minuten) ..."
if ! docker build -q -t nordlicht-rates:aktuell . ; then
    echo "FEHLER: Der Build ist fehlgeschlagen. Ausgabe siehe oben."
    exit 1
fi

# --- Abfragen --------------------------------------------------------------
echo
echo "Frage ab: $HOTEL"
echo "Zeitraum: ab $CHECK_IN, $NAECHTE Naechte, $ADULTS Erwachsene"
echo
mkdir -p "$ARBEITSORDNER/nordlicht-rates/debug"
# Der Container laeuft als pwuser (UID 1000); ohne das darf er in den
# eingehaengten debug-Ordner nicht schreiben.
chmod 777 "$ARBEITSORDNER/nordlicht-rates/debug"

docker run --rm \
    --shm-size=512m \
    --memory=1g \
    -v "$ARBEITSORDNER/nordlicht-rates/config:/config:ro" \
    -v "$ARBEITSORDNER/nordlicht-rates/debug:/debug" \
    nordlicht-rates:aktuell \
    python -m nordlicht_rates.cli "$HOTEL" \
        --check-in "$CHECK_IN" --naechte "$NAECHTE" --adults "$ADULTS" --debug
ERGEBNIS=$?

echo
if [ "$ERGEBNIS" -eq 0 ]; then
    echo "Fertig - die Kategorien stehen oben."
else
    echo "Es kamen keine Kategorien zurueck (Code $ERGEBNIS)."
    echo "Screenshot und HTML liegen in:"
    echo "  $ARBEITSORDNER/nordlicht-rates/debug"
    echo "Die Dateien lassen sich in der File Station ansehen; die Ausgabe"
    echo "oben nennt jede probierte Adresse mit Status."
fi
exit "$ERGEBNIS"
