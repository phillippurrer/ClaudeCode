#!/bin/sh
# ---------------------------------------------------------------------------
# Startet nordlicht-rates als Dauerdienst statt als Einmalabfrage.
#
# Danach ist Schluss mit VPN und Aufgabenplaner: Der Dienst haengt hinter dem
# bestehenden Cloudflare-Tunnel, und die Tools stehen im Chat zur Verfuegung -
# eine Frage genuegt, kein Klick auf der NAS.
#
# Einmal im Aufgabenplaner ausfuehren (Benutzer root), danach laeuft der
# Container von selbst wieder an, auch nach einem Neustart der NAS.
# ---------------------------------------------------------------------------
set -u

ARBEITSORDNER="${ARBEITSORDNER:-/volume1/docker/nordlicht-rates}"
ZWEIG="${ZWEIG:-claude/nordlichter-hotel-prices-mcp-rvh5ts}"
REPO="${REPO:-https://github.com/phillippurrer/ClaudeCode.git}"
PORT="${NORDLICHT_PORT:-8931}"
NAME="${NAME:-nordlicht-rates}"

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export PATH

echo "=========================================================="
echo " nordlicht-rates als Dienst  -  $(date)"
echo "=========================================================="
echo "Benutzer: $(id -un 2>/dev/null || echo unbekannt)"

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "FEHLER: Kein Zugriff auf den Docker-Dienst."
    echo "Im Aufgabenplaner unter 'Allgemein' den Benutzer auf root stellen."
    exit 1
fi

# --- Quellcode und Image ---------------------------------------------------
GIT="git -c safe.directory=$ARBEITSORDNER"
if [ -d "$ARBEITSORDNER/.git" ]; then
    cd "$ARBEITSORDNER" || exit 1
    $GIT fetch origin "$ZWEIG" >/dev/null 2>&1 && \
    $GIT checkout -f "$ZWEIG" >/dev/null 2>&1 && \
    $GIT reset --hard "origin/$ZWEIG" >/dev/null 2>&1 || {
        echo "FEHLER: Quellcode konnte nicht aktualisiert werden."; exit 1; }
else
    git clone -b "$ZWEIG" --depth 1 "$REPO" "$ARBEITSORDNER" || exit 1
fi
cd "$ARBEITSORDNER/nordlicht-rates" || exit 1
echo "Stand: $($GIT log --oneline -1 2>/dev/null)"

echo "Baue Image ..."
docker build -q -t nordlicht-rates:aktuell . || { echo "FEHLER: Build."; exit 1; }
docker run --rm nordlicht-rates:aktuell python -c "import nordlicht_rates.cli" \
    || { echo "FEHLER: Image unvollstaendig."; exit 1; }

chmod -R a+rX "$ARBEITSORDNER/nordlicht-rates/config" 2>/dev/null || true
mkdir -p "$ARBEITSORDNER/nordlicht-rates/debug"
chmod 777 "$ARBEITSORDNER/nordlicht-rates/debug"

# --- Dienst neu starten ----------------------------------------------------
# Kein --cpus: Synologys Kernel bringt den CFS-Scheduler nicht mit, das Flag
# laesst den Start scheitern. Der Speicherdeckel greift dagegen und ist auch
# der wichtigere - er haelt Chromium davon ab, die NAS leerzuraeumen.
# cloudflared erreicht den bestehenden MCP-Server ueber dessen Containernamen
# (Service "http://mcp:8080"), nicht ueber eine IP. Damit das hier genauso
# funktioniert, muss der Container im selben Docker-Netz haengen - sonst
# scheitert die Namensaufloesung und die Route liefert "connection refused".
netze_von() {
    # bridge/host/none herausfiltern: Im Standardnetz "bridge" gibt es keine
    # Namensaufloesung zwischen Containern. Wer dort landet, ist unter seinem
    # Namen nicht erreichbar - und die Tunnel-Route antwortet mit 502.
    docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}
{{end}}' "$1" 2>/dev/null | grep -vE '^(bridge|host|none|)$'
}

# cloudflared muss den Dienst erreichen, also zaehlt dessen Netz - nicht das
# irgendeines anderen Containers.
CLOUDFLARED=$(docker ps --format '{{.Names}}' 2>/dev/null \
    | grep -iE 'cloudflare|tunnel' | head -1)
NACHBAR="${NACHBAR:-mcp}"

echo "Gefundene Container: $(docker ps --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
if [ -n "$CLOUDFLARED" ]; then
    echo "cloudflared laeuft als: $CLOUDFLARED"
    NETZ=$(netze_von "$CLOUDFLARED" | head -1)
    QUELLE="$CLOUDFLARED"
fi
if [ -z "${NETZ:-}" ]; then
    NETZ=$(netze_von "$NACHBAR" | head -1)
    QUELLE="$NACHBAR"
fi

if [ -n "${NETZ:-}" ]; then
    echo "Netz von '$QUELLE' uebernommen: $NETZ"
    NETZ_ARG="--network $NETZ"
else
    echo "Kein gemeinsames Netz gefunden (weder cloudflared noch '$NACHBAR')."
    echo "Der Dienst ist dann nur ueber die NAS-IP erreichbar."
    NETZ_ARG=""
fi

echo "Starte Dienst neu ..."
docker rm -f "$NAME" >/dev/null 2>&1 || true
# shellcheck disable=SC2086
docker run -d --name "$NAME" \
    --restart unless-stopped \
    --shm-size=512m \
    --memory=1g \
    $NETZ_ARG \
    -p "$PORT:$PORT" \
    -e NORDLICHT_TRANSPORT=streamable-http \
    -e NORDLICHT_HOST=0.0.0.0 \
    -e NORDLICHT_PORT="$PORT" \
    -v "$ARBEITSORDNER/nordlicht-rates/config:/config:ro" \
    -v "$ARBEITSORDNER/nordlicht-rates/debug:/debug" \
    nordlicht-rates:aktuell >/dev/null || { echo "FEHLER: Start."; exit 1; }

# Kurz Zeit zum Hochfahren geben, dann nachsehen, ob er noch laeuft - ein
# Container, der sofort wieder ausgeht, meldet sich sonst gar nicht.
i=0
while [ $i -lt 10 ]; do
    sleep 1
    i=$((i + 1))
done

if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != "true" ]; then
    echo
    echo "FEHLER: Der Dienst ist nicht oben geblieben. Letzte Ausgaben:"
    docker logs --tail 30 "$NAME" 2>&1 | sed "s/^/    /"
    exit 1
fi

echo
echo "Laeuft. Protokoll:"
docker logs --tail 8 "$NAME" 2>&1 | sed "s/^/    /"

# Der entscheidende Test: Erreicht ein Container im selben Netz den Dienst
# unter seinem Namen? Genau das tut cloudflared, und genau daran scheiterte
# die Route zuvor mit 502.
if [ -n "$NETZ_ARG" ]; then
    echo
    echo "Pruefe Erreichbarkeit als '$NAME:$PORT' im Netz $NETZ ..."
    # shellcheck disable=SC2086
    ERGEBNIS=$(docker run --rm $NETZ_ARG nordlicht-rates:aktuell python -c \
"import urllib.request as u, urllib.error as e
try:
    r = u.urlopen('http://$NAME:$PORT/mcp', timeout=10)
    print('erreichbar, HTTP', r.status)
except e.HTTPError as f:
    print('erreichbar, HTTP', f.code, '- der Dienst antwortet')
except Exception as f:
    print('NICHT erreichbar:', type(f).__name__, f)
" 2>&1)
    echo "    $ERGEBNIS"
    case "$ERGEBNIS" in
        *"NICHT erreichbar"*)
            echo
            echo "  Damit wuerde auch cloudflared scheitern (502)."
            echo "  Netze dieses Containers:"
            docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}    {{$k}}
{{end}}' "$NAME" 2>/dev/null
            ;;
    esac
fi
echo
# DSMs hostname kennt kein -I; mehrere Wege probieren, damit hier nicht
# "http://:8931" steht - ausgerechnet die eine Angabe, die gebraucht wird.
IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
[ -z "$IP" ] && IP=$(hostname -i 2>/dev/null | awk '{print $1}')
[ -z "$IP" ] && IP=$(ifconfig 2>/dev/null | awk '/inet addr:/{sub("addr:","",$2); print $2; exit}')
[ -z "$IP" ] && IP=$(ip -4 addr show 2>/dev/null | awk '/inet /{split($2,a,"/"); if (a[1] != "127.0.0.1") {print a[1]; exit}}')
[ -z "$IP" ] && IP="<NAS-IP>"

echo "----------------------------------------------------------"
echo "Naechster Schritt, einmalig im Cloudflare-Tunnel:"
echo "  'Add a published application route' anlegen, Service HTTP, URL:"
if [ -n "$NETZ" ]; then
    echo
    echo "      $NAME:$PORT"
    echo
    echo "  Also der Containername - genau wie beim bestehenden Server, der"
    echo "  dort als 'mcp:8080' eingetragen ist."
else
    echo
    echo "      $IP:$PORT"
    echo
fi
echo "  Die Tool-Adresse lautet dann  https://<hostname>/mcp"
echo
echo "Die entstehende Adresse dann in den MCP-Einstellungen eintragen."
echo "Danach genuegt die Frage im Chat; die NAS musst du dafuer nicht"
echo "mehr anfassen."
echo "----------------------------------------------------------"
