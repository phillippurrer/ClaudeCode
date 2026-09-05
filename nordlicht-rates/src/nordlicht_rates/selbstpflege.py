"""Aktualisiert den eigenen Code und startet den Dienst neu.

Ohne das haengt jede Korrektur daran, dass jemand auf der NAS eine Aufgabe
ausloest. Mit gemountetem Quellcode genuegt ein git-Abgleich und ein
Neustart des Prozesses: Docker faehrt den Container wegen
"--restart unless-stopped" von selbst wieder hoch, und PYTHONPATH zeigt auf
das Volume, nicht auf die Kopie im Image.

Bewusst eng gehalten: Es wird ausschliesslich der beim Start konfigurierte
Zweig des konfigurierten Repositorys geholt. Adresse und Zweig sind nicht
ueber die Schnittstelle setzbar - ein Tool, das beliebigen Code nachladen
kann, waere etwas ganz anderes als eines, das sich aktualisiert.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path


def repo_pfad() -> Path | None:
    """Verzeichnis des gemounteten Repositorys, falls vorhanden."""
    roh = os.getenv("NORDLICHT_REPO")
    if not roh:
        return None
    pfad = Path(roh)
    return pfad if (pfad / ".git").exists() else None


def _git(*argumente: str, pfad: Path) -> tuple[int, str]:
    try:
        lauf = subprocess.run(
            ["git", "-c", f"safe.directory={pfad}", "-C", str(pfad), *argumente],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return lauf.returncode, (lauf.stdout + lauf.stderr).strip()
    except FileNotFoundError:
        return 127, "git ist im Container nicht installiert"
    except subprocess.TimeoutExpired:
        return 124, "git-Aufruf hat zu lange gedauert"


def stand() -> dict:
    """Welcher Commit laeuft gerade."""
    pfad = repo_pfad()
    if pfad is None:
        return {
            "aktualisierbar": False,
            "grund": (
                "Kein Repository eingehaengt (NORDLICHT_REPO). Der Dienst "
                "laeuft mit der Kopie aus dem Image und kann sich nicht "
                "selbst aktualisieren."
            ),
        }
    code, ausgabe = _git("log", "-1", "--format=%h %cs %s", pfad=pfad)
    zweig_code, zweig = _git("rev-parse", "--abbrev-ref", "HEAD", pfad=pfad)
    return {
        "aktualisierbar": code == 0,
        "commit": ausgabe if code == 0 else None,
        "zweig": zweig if zweig_code == 0 else None,
        "pfad": str(pfad),
        "fehler": None if code == 0 else ausgabe,
    }


def aktualisiere() -> dict:
    """Holt den konfigurierten Zweig und setzt den Arbeitsstand darauf."""
    pfad = repo_pfad()
    if pfad is None:
        return {"erfolg": False, **stand()}

    vorher = stand().get("commit")
    zweig = os.getenv("NORDLICHT_ZWEIG") or stand().get("zweig") or "HEAD"

    code, ausgabe = _git("fetch", "origin", zweig, pfad=pfad)
    if code != 0:
        return {"erfolg": False, "schritt": "fetch", "meldung": ausgabe[:600]}

    code, ausgabe = _git("reset", "--hard", f"origin/{zweig}", pfad=pfad)
    if code != 0:
        return {"erfolg": False, "schritt": "reset", "meldung": ausgabe[:600]}

    nachher = stand().get("commit")
    return {
        "erfolg": True,
        "vorher": vorher,
        "nachher": nachher,
        "veraendert": vorher != nachher,
        "zweig": zweig,
    }


def neustart_ausloesen(verzoegerung_s: float = 2.0) -> None:
    """Beendet den Prozess kurz verzoegert.

    Die Verzoegerung ist noetig, damit die Antwort auf den ausloesenden
    Aufruf noch hinausgeht - sonst sieht der Aufrufer nur einen Abbruch und
    weiss nicht, ob die Aktualisierung geklappt hat.
    """

    def ende() -> None:
        import time

        time.sleep(verzoegerung_s)
        # os._exit statt sys.exit: Der Server laeuft in einer Ereignisschleife,
        # eine Ausnahme wuerde dort abgefangen und der Prozess liefe weiter.
        os._exit(0)

    threading.Thread(target=ende, daemon=True).start()
