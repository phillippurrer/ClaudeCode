"""Aktualisiert den eigenen Code und startet den Dienst neu.

Ohne das haengt jede Korrektur daran, dass jemand auf der NAS eine Aufgabe
ausloest. Mit gemountetem Quellcode genuegt ein git-Abgleich und ein
Neustart des Prozesses: Docker faehrt den Container wegen
"--restart unless-stopped" von selbst wieder hoch, und PYTHONPATH zeigt auf
die Arbeitskopie, nicht auf die Kopie im Image.

Zwei moegliche Arbeitskopien, in dieser Reihenfolge:

  1. das eingehaengte Repository des Hosts (NORDLICHT_REPO)
  2. eine eigene Kopie im Container (NORDLICHT_EIGENES_REPO)

Der Umweg ueber die eigene Kopie ist kein Schoenheitsfehler, sondern
notwendig: Auf Synology-Volumes koennen ACLs die POSIX-Rechte ueberstimmen,
sodass ein chown zwar Erfolg meldet, der Containerbenutzer aber trotzdem
nicht an das Verzeichnis kommt. Eine Kopie an einem Ort, den der Container
selbst besitzt, umgeht das vollstaendig.

Bewusst eng gehalten: Es wird ausschliesslich der konfigurierte Zweig des
konfigurierten Repositorys geholt. Adresse und Zweig stehen in der Umgebung
und sind ueber die Schnittstelle nicht setzbar - ein Tool, das beliebigen
Code nachladen kann, waere etwas ganz anderes als eines, das sich
aktualisiert.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

STANDARD_EIGENES_REPO = "/srv/code"


def _brauchbar(pfad: Path) -> bool:
    """Existiert dort ein Repository, an das der Prozess auch herankommt?

    Lesen allein genuegt nicht: git schreibt beim Abgleich in .git, und ein
    nur lesbares Verzeichnis faellt sonst erst beim Aktualisieren auf.
    """
    try:
        return (pfad / ".git").exists() and os.access(pfad, os.R_OK | os.W_OK | os.X_OK)
    except OSError:
        return False


def _beschreibbar(pfad: Path) -> bool:
    try:
        pfad.mkdir(parents=True, exist_ok=True)
        return os.access(pfad, os.R_OK | os.W_OK | os.X_OK)
    except OSError:
        return False


def eigener_pfad() -> Path:
    return Path(os.getenv("NORDLICHT_EIGENES_REPO", STANDARD_EIGENES_REPO))


def arbeitskopie() -> tuple[Path | None, str]:
    """Liefert die zu verwendende Arbeitskopie und woher sie stammt."""
    aus_env = os.getenv("NORDLICHT_REPO")
    if aus_env and _brauchbar(Path(aus_env)):
        return Path(aus_env), "volume"

    eigen = eigener_pfad()
    if _brauchbar(eigen):
        return eigen, "eigen"
    if os.getenv("NORDLICHT_REPO_URL") and _beschreibbar(eigen):
        # Noch nichts geklont, aber es koennte geklont werden.
        return eigen, "eigen-leer"
    return None, "keine"


def _git(*argumente: str, pfad: Path | None = None) -> tuple[int, str]:
    befehl = ["git"]
    if pfad is not None:
        befehl += ["-c", f"safe.directory={pfad}", "-C", str(pfad)]
    try:
        lauf = subprocess.run(
            befehl + list(argumente), capture_output=True, text=True, timeout=180
        )
        return lauf.returncode, (lauf.stdout + lauf.stderr).strip()
    except FileNotFoundError:
        return 127, "git ist im Container nicht installiert"
    except subprocess.TimeoutExpired:
        return 124, "git-Aufruf hat zu lange gedauert"


def stand() -> dict:
    """Welcher Commit laeuft gerade."""
    pfad, art = arbeitskopie()
    if pfad is None:
        return {
            "aktualisierbar": False,
            "herkunft": art,
            "grund": (
                "Keine beschreibbare Arbeitskopie. Der Dienst laeuft mit der "
                "Kopie aus dem Image und kann sich nicht selbst "
                "aktualisieren. Erwartet wird ein Repository unter "
                "NORDLICHT_REPO oder eine klonbare Adresse in "
                "NORDLICHT_REPO_URL."
            ),
        }
    if art == "eigen-leer":
        return {
            "aktualisierbar": True,
            "herkunft": art,
            "commit": None,
            "pfad": str(pfad),
            "hinweis": (
                "Eigene Arbeitskopie noch nicht angelegt - der naechste "
                "dienst_aktualisieren klont sie."
            ),
        }
    code, ausgabe = _git("log", "-1", "--format=%h %cs %s", pfad=pfad)
    zweig_code, zweig = _git("rev-parse", "--abbrev-ref", "HEAD", pfad=pfad)
    return {
        "aktualisierbar": code == 0,
        "herkunft": art,
        "commit": ausgabe if code == 0 else None,
        "zweig": zweig if zweig_code == 0 else None,
        "pfad": str(pfad),
        "fehler": None if code == 0 else ausgabe[:400],
    }


def aktualisiere() -> dict:
    """Holt den konfigurierten Zweig und setzt den Arbeitsstand darauf."""
    pfad, art = arbeitskopie()
    if pfad is None:
        return {"erfolg": False, **stand()}

    zweig = os.getenv("NORDLICHT_ZWEIG") or "HEAD"
    adresse = os.getenv("NORDLICHT_REPO_URL")

    if art == "eigen-leer":
        if not adresse:
            return {"erfolg": False, "schritt": "clone",
                    "meldung": "NORDLICHT_REPO_URL ist nicht gesetzt."}
        code, ausgabe = _git(
            "clone", "--depth", "1", "-b", zweig, adresse, str(pfad)
        )
        if code != 0:
            return {"erfolg": False, "schritt": "clone", "meldung": ausgabe[:600]}
        return {"erfolg": True, "vorher": None, "nachher": stand().get("commit"),
                "veraendert": True, "zweig": zweig, "herkunft": "eigen"}

    vorher = stand().get("commit")
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
        "herkunft": art,
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
