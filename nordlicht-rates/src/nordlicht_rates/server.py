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

mcp = ServerKlasse("nordlicht-rates")
register(mcp)


def main() -> None:
    transport = os.getenv("NORDLICHT_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
    else:
        # sse/streamable-http fuer den Betrieb als Netzdienst auf der NAS.
        mcp.run(transport=transport)


if __name__ == "__main__":
    main()
