"""nordlicht_rates - Zimmerpreise direkt von Hotel-Buchungsstrecken.

Ergaenzt den bestehenden NAS-MCP-Server um die Faelle, die Google Hotels
(hotel_price_search) nicht abdeckt und die keine WebHotelier-Maschine nutzen
(hotel_availability).
"""

from .tools import register

__all__ = ["register", "__version__"]
__version__ = "0.1.0"
