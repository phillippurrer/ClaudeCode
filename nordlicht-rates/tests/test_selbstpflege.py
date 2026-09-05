"""Selbstaktualisierung des Dienstes.

Der Dienst laeuft hinter einem Tunnel auf fremder Hardware. Ohne diesen Weg
haengt jede Korrektur daran, dass jemand vor Ort eine Aufgabe ausloest -
was die Fehlersuche auf einen Umlauf pro Runde streckt.

Getestet wird gegen echte Repositories in tmp_path, nicht gegen Attrappen:
Die interessanten Fehler stecken in den git-Aufrufen selbst.
"""

import subprocess

import pytest

from nordlicht_rates import selbstpflege


def _git(pfad, *argumente):
    return subprocess.run(
        ["git", "-C", str(pfad), *argumente],
        capture_output=True, text=True, check=True,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Ein Repository mit Fernkopie, wie es der Container vorfindet."""
    fern = tmp_path / "fern"
    fern.mkdir()
    _git(fern, "init", "-q", "-b", "haupt")
    _git(fern, "config", "user.email", "test@example.invalid")
    _git(fern, "config", "user.name", "Test")
    (fern / "datei.txt").write_text("erste Fassung", encoding="utf-8")
    _git(fern, "add", "-A")
    _git(fern, "commit", "-q", "-m", "erster Stand")

    nah = tmp_path / "nah"
    subprocess.run(
        ["git", "clone", "-q", str(fern), str(nah)], check=True,
        capture_output=True,
    )
    monkeypatch.setenv("NORDLICHT_REPO", str(nah))
    monkeypatch.setenv("NORDLICHT_ZWEIG", "haupt")
    return fern, nah


def test_stand_nennt_commit_und_zweig(repo):
    stand = selbstpflege.stand()
    assert stand["aktualisierbar"] is True
    assert "erster Stand" in stand["commit"]
    assert stand["zweig"] == "haupt"


def test_ohne_repo_kein_selbstupdate(monkeypatch):
    """Laeuft der Dienst nur mit der Kopie aus dem Image, muss er das sagen -
    statt eine Aktualisierung vorzutaeuschen, die nie ankommt."""
    monkeypatch.delenv("NORDLICHT_REPO", raising=False)
    stand = selbstpflege.stand()
    assert stand["aktualisierbar"] is False
    assert "Kein Repository" in stand["grund"]
    assert selbstpflege.aktualisiere()["erfolg"] is False


def test_pfad_ohne_git_wird_abgelehnt(tmp_path, monkeypatch):
    monkeypatch.setenv("NORDLICHT_REPO", str(tmp_path))
    assert selbstpflege.repo_pfad() is None


def test_aktualisieren_holt_neuen_stand(repo):
    fern, nah = repo
    (fern / "datei.txt").write_text("zweite Fassung", encoding="utf-8")
    _git(fern, "add", "-A")
    _git(fern, "commit", "-q", "-m", "zweiter Stand")

    ergebnis = selbstpflege.aktualisiere()
    assert ergebnis["erfolg"] is True
    assert ergebnis["veraendert"] is True
    assert "erster Stand" in ergebnis["vorher"]
    assert "zweiter Stand" in ergebnis["nachher"]
    assert (nah / "datei.txt").read_text(encoding="utf-8") == "zweite Fassung"


def test_ohne_aenderung_kein_neustart_noetig(repo):
    """Ein Neustart ohne neuen Code kostet nur eine Unterbrechung."""
    ergebnis = selbstpflege.aktualisiere()
    assert ergebnis["erfolg"] is True
    assert ergebnis["veraendert"] is False


def test_lokale_aenderungen_werden_ueberschrieben(repo):
    """Der Arbeitsstand im Container ist keine Werkstatt - was dort liegt,
    weicht dem Stand aus dem Repository."""
    fern, nah = repo
    (nah / "datei.txt").write_text("lokal verbogen", encoding="utf-8")
    selbstpflege.aktualisiere()
    assert (nah / "datei.txt").read_text(encoding="utf-8") == "erste Fassung"


def test_unerreichbare_fernkopie_meldet_sich(repo, monkeypatch):
    fern, nah = repo
    _git(nah, "remote", "set-url", "origin", str(fern) + "-gibtesnicht")
    ergebnis = selbstpflege.aktualisiere()
    assert ergebnis["erfolg"] is False
    assert ergebnis["schritt"] == "fetch"
    assert ergebnis["meldung"]


def test_neustart_beendet_den_prozess(monkeypatch):
    """Der Neustart muss den Prozess wirklich beenden - eine Ausnahme wuerde
    die Ereignisschleife des Servers abfangen und nichts bewirken."""
    beendet = []
    monkeypatch.setattr(selbstpflege.os, "_exit", lambda code: beendet.append(code))
    selbstpflege.neustart_ausloesen(verzoegerung_s=0.01)
    import time

    time.sleep(0.3)
    assert beendet == [0]


def test_neustart_wartet_auf_die_antwort(monkeypatch):
    """Ohne Verzoegerung bricht die Verbindung ab, bevor der Aufrufer
    erfaehrt, ob die Aktualisierung geklappt hat."""
    beendet = []
    monkeypatch.setattr(selbstpflege.os, "_exit", lambda code: beendet.append(code))
    selbstpflege.neustart_ausloesen(verzoegerung_s=0.5)
    assert beendet == []
