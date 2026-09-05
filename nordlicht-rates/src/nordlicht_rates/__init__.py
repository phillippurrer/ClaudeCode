"""nordlicht_rates - Zimmerpreise direkt von Hotel-Buchungsstrecken.

Ergaenzt den bestehenden NAS-MCP-Server um die Faelle, die Google Hotels
(hotel_price_search) nicht abdeckt und die keine WebHotelier-Maschine nutzen
(hotel_availability).
"""

__version__ = "0.2.0"

# Erst nach __version__ importieren: tools liest sie beim Laden aus.
from .tools import register  # noqa: E402

__all__ = ["register", "__version__"]
