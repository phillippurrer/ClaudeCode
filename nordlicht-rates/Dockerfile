# Das offizielle Playwright-Image bringt Chromium samt aller System-
# bibliotheken mit. Auf einer NAS ist das der entscheidende Punkt: Chromium
# nativ unter DSM/QTS lauffaehig zu bekommen, ist ein Nachmittag Arbeit -
# hier sind es null Zeilen.
#
# Der Tag muss zur playwright-Version in requirements.txt passen.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NORDLICHT_CONFIG=/config/engines.yaml \
    NORDLICHT_DEBUG_DIR=/debug

WORKDIR /app

# git wird zur Laufzeit gebraucht: Der Dienst holt sich damit selbst neuen
# Code aus dem eingehaengten Repository, ohne dass jemand auf der NAS eine
# Aufgabe ausloesen muss.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ /config/

# Reihenfolge entscheidet: Zuerst die eigene Arbeitskopie des Containers,
# dann das eingehaengte Repository des Hosts, zuletzt die Kopie im Image.
#
# Die eigene Kopie steht vorn, weil sie die einzige ist, an die der Container
# unter allen Umstaenden herankommt: Auf Synology-Volumes koennen ACLs die
# POSIX-Rechte ueberstimmen, sodass ein chown auf dem Host Erfolg meldet, der
# Containerbenutzer aber trotzdem nicht an das eingehaengte Verzeichnis kommt.
ENV PYTHONPATH=/srv/code/nordlicht-rates/src:/repo/nordlicht-rates/src:/app/src \
    NORDLICHT_EIGENES_REPO=/srv/code

# COPY uebernimmt die Rechte der Quelle. Liegt der Bauordner auf einem
# Synology-Volume mit 700 root, ist er im Image fuer pwuser unlesbar - und
# Python macht aus dem Paket dann ein Namespace-Paket: "import
# nordlicht_rates" gelingt, jedes Submodul fehlt. Der Fehler sieht damit nach
# einem Programmfehler aus, obwohl es ein Rechteproblem ist.
# a+rX setzt Leserecht fuer alle und Durchgangsrecht nur auf Verzeichnissen.
RUN chmod -R a+rX /app/src /config

# Der Container fuehrt einen Browser aus - er braucht keinen Rootzugriff.
# Das Playwright-Image bringt den User pwuser bereits mit.
RUN mkdir -p /debug /srv/code && chown -R pwuser:pwuser /debug /config /srv/code
USER pwuser

# Prueft Config und Chromium-Binary, ohne den Browser zu starten: Ein
# Probelauf alle 5 Minuten wuerde auf einer 2-GB-NAS dauerhaft 300-600 MB
# in Spitzen belegen - fuer eine Auskunft, die auch die Datei auf der Platte
# gibt.
HEALTHCHECK --interval=5m --timeout=20s --start-period=15s --retries=2 \
  CMD python -c "import pathlib, sys; \
from nordlicht_rates.config import lade_config; \
from playwright.sync_api import sync_playwright; \
lade_config(); \
p = sync_playwright().start(); \
pfad = pathlib.Path(p.chromium.executable_path); \
p.stop(); \
sys.exit(0 if pfad.exists() else 1)" || exit 1

CMD ["python", "-m", "nordlicht_rates.server"]
