"""Laedt engines.yaml und die Laufzeit-Einstellungen aus der Umgebung."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


def _pfad_config() -> Path:
    """Sucht engines.yaml.

    Vorrang hat die Arbeitskopie, aus der auch der Code stammt: Aktualisiert
    sich der Dienst selbst, wandert nur der Code nach - eine Konfiguration aus
    einem eingehaengten Verzeichnis gehoert dann zu einem aelteren Stand. Das
    faellt nicht als Fehler auf, sondern als ausbleibende Wirkung: Der neue
    Code liest eine Einstellung, die es dort noch gar nicht gibt.
    """
    eigenes = os.getenv("NORDLICHT_EIGENES_REPO")
    if eigenes:
        kandidat = Path(eigenes) / "nordlicht-rates" / "config" / "engines.yaml"
        if kandidat.exists():
            return kandidat

    aus_env = os.getenv("NORDLICHT_CONFIG")
    if aus_env and Path(aus_env).exists():
        return Path(aus_env)
    hier = Path(__file__).resolve()
    for kandidat in (
        hier.parent / "engines.yaml",
        hier.parents[2] / "config" / "engines.yaml",
        Path("/config/engines.yaml"),
    ):
        if kandidat.exists():
            return kandidat
    raise FileNotFoundError(
        "engines.yaml nicht gefunden - NORDLICHT_CONFIG setzen"
    )


@dataclass
class Einstellungen:
    """Laufzeit-Schalter, alle ueber Umgebungsvariablen setzbar."""

    headless: bool = True
    timeout_ms: int = 45_000
    min_abstand_s: float = 4.0
    # 6 Stunden: Buchungsmaschinen sind langsam und moegen keine
    # Lastspitzen; Zimmerpreise aendern sich nicht im Minutentakt.
    cache_ttl_s: int = 21_600
    max_angebote: int = 40
    # Gleichzeitige Browserfenster bei reise_preise. Auf einer NAS mit
    # 2 GB RAM notfalls auf 1 setzen.
    max_parallel: int = 3
    debug_verzeichnis: Path = field(default_factory=lambda: Path("/tmp/nordlicht"))
    sprache: str = "en-GB"
    zeitzone: str = "Europe/Oslo"
    # Buchungsstrecken lehnen offensichtliche Automaten ab; ein realistischer
    # UA ist keine Tarnung, sondern verhindert kaputtes Rendering.
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    @classmethod
    def aus_umgebung(cls) -> "Einstellungen":
        def zahl(name: str, standard):
            wert = os.getenv(name)
            if wert is None:
                return standard
            try:
                return type(standard)(wert)
            except (TypeError, ValueError):
                return standard

        return cls(
            headless=os.getenv("NORDLICHT_HEADLESS", "1") not in ("0", "false"),
            timeout_ms=zahl("NORDLICHT_TIMEOUT_MS", 45_000),
            min_abstand_s=zahl("NORDLICHT_MIN_ABSTAND_S", 4.0),
            cache_ttl_s=zahl("NORDLICHT_CACHE_TTL_S", 21_600),
            max_angebote=zahl("NORDLICHT_MAX_ANGEBOTE", 40),
            max_parallel=max(1, zahl("NORDLICHT_MAX_PARALLEL", 3)),
            debug_verzeichnis=Path(
                os.getenv("NORDLICHT_DEBUG_DIR", "/tmp/nordlicht")
            ),
            sprache=os.getenv("NORDLICHT_SPRACHE", "en-GB"),
            zeitzone=os.getenv("NORDLICHT_ZEITZONE", "Europe/Oslo"),
        )


@lru_cache(maxsize=1)
def lade_config() -> dict:
    pfad = _pfad_config()
    with open(pfad, "r", encoding="utf-8") as fh:
        daten = yaml.safe_load(fh)
    if not isinstance(daten, dict) or "engines" not in daten:
        raise ValueError(f"{pfad} hat kein 'engines'-Feld")
    return daten


@lru_cache(maxsize=1)
def einstellungen() -> Einstellungen:
    return Einstellungen.aus_umgebung()


def schreibbares_debug_verzeichnis() -> Path:
    """Liefert ein Verzeichnis, in das Screenshots wirklich geschrieben werden.

    Im Container gehoert der eingehaengte debug-Ordner haeufig dem Host-Root,
    waehrend der Prozess als pwuser laeuft. Dann ist die Fehlersuche genau in
    dem Moment kaputt, in dem man sie braucht - deshalb hier lieber ein
    Ausweichort als eine Ausnahme.
    """
    gewuenscht = einstellungen().debug_verzeichnis
    try:
        gewuenscht.mkdir(parents=True, exist_ok=True)
        probe = gewuenscht / ".schreibprobe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return gewuenscht
    except OSError:
        ausweich = Path(tempfile.gettempdir()) / "nordlicht-debug"
        ausweich.mkdir(parents=True, exist_ok=True)
        return ausweich
