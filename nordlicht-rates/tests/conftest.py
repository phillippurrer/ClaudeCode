import os
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("NORDLICHT_CONFIG", str(WURZEL / "config" / "engines.yaml"))
# Tests sollen nicht kuenstlich warten und sich nicht gegenseitig cachen.
os.environ.setdefault("NORDLICHT_MIN_ABSTAND_S", "0")
os.environ.setdefault("NORDLICHT_CACHE_TTL_S", "0")
os.environ.setdefault("NORDLICHT_TIMEOUT_MS", "20000")
