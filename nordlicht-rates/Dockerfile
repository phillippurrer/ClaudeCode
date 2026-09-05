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

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ /config/

ENV PYTHONPATH=/app/src

# Der Container fuehrt einen Browser aus - er braucht keinen Rootzugriff.
# Das Playwright-Image bringt den User pwuser bereits mit.
RUN mkdir -p /debug && chown -R pwuser:pwuser /debug /config
USER pwuser

# Frueher Fehlschlag, falls Config oder Chromium fehlen, statt erst beim
# ersten Tool-Aufruf.
HEALTHCHECK --interval=5m --timeout=30s --start-period=20s --retries=2 \
  CMD python -c "from nordlicht_rates.config import lade_config; \
from playwright.sync_api import sync_playwright; lade_config(); \
p=sync_playwright().start(); b=p.chromium.launch(args=['--no-sandbox']); \
b.close(); p.stop()" || exit 1

CMD ["python", "-m", "nordlicht_rates.server"]
