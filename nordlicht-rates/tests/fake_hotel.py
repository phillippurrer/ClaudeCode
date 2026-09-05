"""Nachbau einer Buchungsstrecke fuer die Tests.

Bildet nach, was echte Buchungsmaschinen tun: Die HTML-Seite kommt leer, die
Zimmer werden per fetch() aus einer JSON-Antwort nachgeladen und dann ins DOM
geschrieben. Nur so testet der End-to-End-Test wirklich den Netzwerk-
Mitschnitt und nicht bloss statisches HTML.

Drei Varianten:
  /booking      JSON-API + DOM  (Normalfall)
  /nurdom       ausschliesslich serverseitiges HTML, keine JSON-Antwort
  /gesperrt     antwortet mit 403 und Sperrseite
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ZIMMER = [
    {
        "roomName": "Standard Double",
        "price": {"amount": 4590, "currency": "NOK"},
        "boardType": "Breakfast included",
        "refundable": True,
    },
    {
        "roomName": "Arctic Superior Seaview",
        "price": {"amount": 6250, "currency": "NOK"},
        "boardType": "Breakfast included",
        "refundable": True,
    },
    {
        "roomName": "Northern Lights Suite",
        "price": {"amount": 11900, "currency": "NOK"},
        "boardType": "Half board",
        "refundable": False,
    },
]

_SEITE = """<!doctype html><html><head><title>Fjordly Hotel Tromsø</title></head>
<body><h1>Booking</h1><div id="rooms">Laden ...</div>
<script>
const p = new URLSearchParams(location.search);
if (p.get('checkin') && p.get('checkout')) {
  fetch('/api/availability?' + p.toString())
    .then(r => r.json())
    .then(d => {
      document.getElementById('rooms').innerHTML = d.rooms.map(r =>
        `<article class="room-card">
           <h3 class="room-name">${r.roomName}</h3>
           <span class="price">${r.price.amount.toLocaleString('nb-NO')} kr</span>
         </article>`).join('');
    });
} else {
  document.getElementById('rooms').innerHTML = '<p>Bitte Datum wählen</p>';
}
</script></body></html>"""

_NUR_DOM = """<!doctype html><html><head><title>Gjestehus Kirkenes</title></head>
<body><h1>Ledige rom</h1>
<article class="room-card"><h3 class="room-name">Dobbeltrom</h3>
  <span class="price">1 890 kr</span></article>
<article class="room-card"><h3 class="room-name">Familierom</h3>
  <span class="price">2 450 kr</span><span class="price">3 100 kr</span></article>
<article class="room-card"><h3 class="room-name">Bytax</h3>
  <span class="price">25 kr</span></article>
</body></html>"""

_GESPERRT = """<!doctype html><html><head><title>Blocked</title></head>
<body><h1>Access denied</h1><p>Please verify you are human.</p></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # Testausgabe sauber halten
        pass

    def _sende(self, koerper: str, typ="text/html; charset=utf-8", status=200):
        roh = koerper.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self):
        zerlegt = urlparse(self.path)
        pfad = zerlegt.path
        if pfad in ("/booking", "/"):
            self._sende(_SEITE)
        elif pfad == "/nurdom":
            self._sende(_NUR_DOM)
        elif pfad == "/gesperrt":
            self._sende(_GESPERRT, status=403)
        elif pfad == "/api/availability":
            frage = parse_qs(zerlegt.query)
            if not frage.get("checkin") or not frage.get("checkout"):
                self._sende(
                    json.dumps({"rooms": []}), "application/json", status=400
                )
                return
            self._sende(
                json.dumps({"currency": "NOK", "rooms": ZIMMER}),
                "application/json",
            )
        else:
            self._sende("<h1>404</h1>", status=404)


class FakeHotel:
    """Startet den Server auf einem freien Port und liefert seine Basis-URL."""

    def __init__(self):
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )

    def __enter__(self) -> str:
        self._thread.start()
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __exit__(self, *_):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        return False
