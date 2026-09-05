"""Standalone-MCP-Server.

Zwei Betriebsarten:

  1. Eigenstaendig (empfohlen fuer den Anfang):
         python -m nordlicht_rates.server
     Laeuft als eigener MCP-Server neben dem bestehenden NAS-Server. Vorteil:
     Der laufende Server bleibt unangetastet, und Chromium steckt in einem
     eigenen Container.

  2. Eingehaengt in den bestehenden Server - dort einfuegen:
         from nordlicht_rates import register
         register(mcp)

Beide Wege funktionieren mit dem MCP-SDK 1.x (FastMCP) und 2.x (MCPServer).
"""

from __future__ import annotations

import logging
import os

from .tools import register

# Das SDK hat FastMCP in Version 2 zu MCPServer umbenannt. register() selbst
# ist davon unberuehrt - beide bieten denselben .tool()-Dekorator -, also wird
# hier nur die Klasse gesucht. So laeuft dasselbe Modul im bestehenden
# NAS-Server (1.x) und in einem frisch gebauten Container (2.x).
try:
    from mcp.server.fastmcp import FastMCP as ServerKlasse
except ModuleNotFoundError:  # pragma: no cover - haengt an der SDK-Version
    from mcp.server.mcpserver import MCPServer as ServerKlasse

logging.basicConfig(
    level=os.getenv("NORDLICHT_LOGLEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Bind-Adresse ist im Container entscheidend: FastMCP nimmt sonst 127.0.0.1,
# und dann ist der Dienst zwar gestartet, aber von aussen nicht erreichbar -
# ein Fehler, der sich als "Server laeuft, antwortet aber nicht" zeigt.
# Bei stdio ist die Angabe wirkungslos und stoert nicht.
_HOST = os.getenv("NORDLICHT_HOST", "0.0.0.0")
_PORT = int(os.getenv("NORDLICHT_PORT", "8931"))

try:
    mcp = ServerKlasse("nordlicht-rates", host=_HOST, port=_PORT)
except TypeError:  # pragma: no cover - aeltere SDK-Fassungen
    mcp = ServerKlasse("nordlicht-rates")
register(mcp)


def main() -> None:
    transport = os.getenv("NORDLICHT_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
        return
    # streamable-http (oder sse) fuer den Dauerbetrieb als Netzdienst auf der
    # NAS, erreichbar ueber den bestehenden Cloudflare-Tunnel.
    logging.getLogger(__name__).info(
        "nordlicht-rates hoert auf %s:%s (%s)", _HOST, _PORT, transport
    )
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
