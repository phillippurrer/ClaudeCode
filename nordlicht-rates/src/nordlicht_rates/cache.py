"""Kleiner TTL-Cache im Speicher.

Zweck ist nicht Geschwindigkeit, sondern Ruhe auf der Gegenseite: Wenn im
Gespraech dreimal nach demselben Hotel gefragt wird, soll die Buchungsstrecke
nicht dreimal aufgerufen werden.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    def __init__(self, ttl_s: int = 900, max_eintraege: int = 200):
        self.ttl_s = ttl_s
        self.max_eintraege = max_eintraege
        self._daten: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def hole(self, schluessel: str):
        eintrag = self._daten.get(schluessel)
        if eintrag is None:
            return None
        gesetzt, wert = eintrag
        if time.monotonic() - gesetzt > self.ttl_s:
            del self._daten[schluessel]
            return None
        self._daten.move_to_end(schluessel)
        return wert

    def setze(self, schluessel: str, wert: Any) -> None:
        if self.ttl_s <= 0:
            return
        self._daten[schluessel] = (time.monotonic(), wert)
        self._daten.move_to_end(schluessel)
        while len(self._daten) > self.max_eintraege:
            self._daten.popitem(last=False)

    def leeren(self) -> int:
        anzahl = len(self._daten)
        self._daten.clear()
        return anzahl
