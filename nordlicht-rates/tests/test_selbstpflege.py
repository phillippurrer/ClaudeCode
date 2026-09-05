"""Selbstaktualisierung des Dienstes.

Der Dienst laeuft hinter einem Tunnel auf fremder Hardware. Ohne diesen Weg
haengt jede Korrektur daran, dass jemand vor Ort eine Aufgabe ausloest -
was die Fehlersuche auf einen Umlauf pro Runde streckt.

Getestet wird gegen echte Repositories in tmp_path, nicht gegen Attrappen:
Die interessanten Fehler stecken in den git-Aufrufen und in den Rechten.
"""

import os
import subprocess

import pytest

from nordlicht_rates import selbstpflege


def _git(pfad, *argumente):
    return subprocess.run(
        ["git", "-C", str(pfad), *argumente],
        capture_output=True, text=True, check=True,
    )


def _fernkopie(pfad):
    pfad.mkdir(parents=True, exist_ok=True)
    _git(pfad, "init", "-q", "-b", "haupt")
    _git(pfad, "config", "user.email", "test@example.invalid")
    _git(pfad, "config", "user.name", "Test")
    (pfad / "datei.txt").write_text("erste Fassung", encoding="utf-8")
    _git(pfad, "add", "-A")
    _git(pfad, "commit", "-q", "-m", "erster Stand")
    return pfad


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch, tmp_path):
    """Kein Durchschlagen der echten Umgebung in die Tests."""
    for name in ("NORDLICHT_REPO", "NORDLICHT_REPO_URL", "NORDLICHT_ZWEIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NORDLICHT_EIGENES_REPO", str(tmp_path / "eigen"))


@pytest.fixture
def volume(tmp_path, monkeypatch):
    """Ein eingehaengtes Repository, wie es der Container normalerweise sieht."""
    fern = _fernkopie(tmp_path / "fern")
    nah = tmp_path / "nah"
    subprocess.run(["git", "clone", "-q", str(fern), str(nah)],
                   check=True, capture_output=True)
    monkeypatch.setenv("NORDLICHT_REPO", str(nah))
    monkeypatch.setenv("NORDLICHT_ZWEIG", "haupt")
    return fern, nah


def test_volume_wird_bevorzugt(volume):
    pfad, art = selbstpflege.arbeitskopie()
    assert art == "volume"
    assert selbstpflege.stand()["commit"].endswith("erster Stand")


def test_aktualisieren_holt_neuen_stand(volume):
    fern, nah = volume
    (fern / "datei.txt").write_text("zweite Fassung", encoding="utf-8")
    _git(fern, "add", "-A")
    _git(fern, "commit", "-q", "-m", "zweiter Stand")

    ergebnis = selbstpflege.aktualisiere()
    assert ergebnis["erfolg"] is True
    assert ergebnis["veraendert"] is True
    assert "zweiter Stand" in ergebnis["nachher"]
    assert (nah / "datei.txt").read_text(encoding="utf-8") == "zweite Fassung"


def test_ohne_aenderung_kein_neustart_noetig(volume):
    """Ein Neustart ohne neuen Code kostet nur eine Unterbrechung."""
    assert selbstpflege.aktualisiere()["veraendert"] is False


def test_lokale_aenderungen_weichen(volume):
    """Der Arbeitsstand im Container ist keine Werkstatt."""
    fern, nah = volume
    (nah / "datei.txt").write_text("lokal verbogen", encoding="utf-8")
    selbstpflege.aktualisiere()
    assert (nah / "datei.txt").read_text(encoding="utf-8") == "erste Fassung"


def test_unerreichbare_fernkopie_meldet_sich(volume):
    fern, nah = volume
    _git(nah, "remote", "set-url", "origin", str(fern) + "-gibtesnicht")
    ergebnis = selbstpflege.aktualisiere()
    assert ergebnis["erfolg"] is False
    assert ergebnis["schritt"] == "fetch"


def test_unlesbares_volume_faellt_auf_eigene_kopie(tmp_path, monkeypatch):
    """Genau der Fall aus dem Betrieb: Das eingehaengte Verzeichnis meldet
    'Permission denied', obwohl chown auf dem Host Erfolg gemeldet hatte -
    auf Synology-Volumes koennen ACLs die POSIX-Rechte ueberstimmen."""
    fern = _fernkopie(tmp_path / "fern")
    gesperrt = tmp_path / "gesperrt"
    subprocess.run(["git", "clone", "-q", str(fern), str(gesperrt)],
                   check=True, capture_output=True)

    monkeypatch.setenv("NORDLICHT_REPO", str(gesperrt))
    monkeypatch.setenv("NORDLICHT_REPO_URL", str(fern))
    monkeypatch.setenv("NORDLICHT_ZWEIG", "haupt")
    # Unbenutzbarkeit ueber einen Pfad erzeugen, dessen Elternteil eine Datei
    # ist: Rechte-Bits taugen nicht, weil die Suite als root laufen kann.
    monkeypatch.setattr(selbstpflege, "_brauchbar",
                        lambda p: False if str(p) == str(gesperrt) else
                        (p / ".git").exists())

    pfad, art = selbstpflege.arbeitskopie()
    assert art == "eigen-leer"
    assert str(gesperrt) not in str(pfad)


def test_eigene_kopie_wird_geklont(tmp_path, monkeypatch):
    fern = _fernkopie(tmp_path / "fern")
    monkeypatch.setenv("NORDLICHT_REPO_URL", str(fern))
    monkeypatch.setenv("NORDLICHT_ZWEIG", "haupt")

    assert selbstpflege.stand()["herkunft"] == "eigen-leer"
    ergebnis = selbstpflege.aktualisiere()
    assert ergebnis["erfolg"] is True, ergebnis
    assert ergebnis["herkunft"] == "eigen"

    danach = selbstpflege.stand()
    assert danach["herkunft"] == "eigen"
    assert "erster Stand" in danach["commit"]


def test_geklonte_kopie_wird_danach_aktualisiert(tmp_path, monkeypatch):
    fern = _fernkopie(tmp_path / "fern")
    monkeypatch.setenv("NORDLICHT_REPO_URL", str(fern))
    monkeypatch.setenv("NORDLICHT_ZWEIG", "haupt")
    selbstpflege.aktualisiere()

    (fern / "datei.txt").write_text("zweite Fassung", encoding="utf-8")
    _git(fern, "add", "-A")
    _git(fern, "commit", "-q", "-m", "zweiter Stand")

    ergebnis = selbstpflege.aktualisiere()
    assert ergebnis["erfolg"] is True
    assert "zweiter Stand" in ergebnis["nachher"]


def test_ohne_alles_kein_selbstupdate(monkeypatch, tmp_path):
    """Weder Volume noch klonbare Adresse: Der Dienst muss das sagen, statt
    eine Aktualisierung vorzutaeuschen, die nie ankommt."""
    monkeypatch.setenv("NORDLICHT_EIGENES_REPO", str(tmp_path / "nichts"))
    stand = selbstpflege.stand()
    assert stand["aktualisierbar"] is False
    assert "Keine beschreibbare Arbeitskopie" in stand["grund"]
    assert selbstpflege.aktualisiere()["erfolg"] is False


def test_klonen_ohne_adresse_meldet_sich(tmp_path, monkeypatch):
    monkeypatch.setenv("NORDLICHT_EIGENES_REPO", str(tmp_path / "leer"))
    monkeypatch.setattr(selbstpflege, "_beschreibbar", lambda p: True)
    monkeypatch.setenv("NORDLICHT_REPO_URL", "")
    ergebnis = selbstpflege.aktualisiere()
    assert ergebnis["erfolg"] is False


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
