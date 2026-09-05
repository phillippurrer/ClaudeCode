"""Die Kommandozeile - der Weg zur ersten Zahl, ohne MCP-Server einzurichten."""

import datetime

import pytest

from fake_hotel import FakeHotel
from nordlicht_rates.cli import _groesse, main

ANREISE = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()


@pytest.fixture(scope="module")
def hotel():
    with FakeHotel() as basis:
        yield basis


def test_tabelle_zeigt_alle_kategorien(hotel, capsys):
    code = main([f"{hotel}/booking", "--check-in", ANREISE, "--naechte", "2"])
    ausgabe = capsys.readouterr().out
    assert code == 0
    for name in ("Superior", "Deluxe", "Ultimate"):
        assert name in ausgabe
    assert "1.430 EUR" in ausgabe and "1.980 EUR" in ausgabe


def test_vergleich_stellt_whirlpool_gegenueber(hotel, capsys):
    """Die eigentliche Frage: was kostet der Whirlpool an Aufpreis."""
    main([f"{hotel}/booking", "--check-in", ANREISE, "--naechte", "2"])
    ausgabe = capsys.readouterr().out
    assert "ohne Whirlpool: Sky View Cabin Superior" in ausgabe
    assert "mit  Whirlpool: Sky View Cabin Deluxe" in ausgabe
    assert "Aufpreis:       550 EUR" in ausgabe


def test_widget_seite_wird_verfolgt(hotel, capsys):
    """Der Fall theranch.fi: Hotelseite ohne eigene Preise."""
    code = main([f"{hotel}/widget", "--check-in", ANREISE, "--naechte", "2"])
    ausgabe = capsys.readouterr().out
    assert code == 0
    assert "eingebettete Buchungsstrecke" in ausgabe
    assert "1.980 EUR" in ausgabe


def test_json_ausgabe_ist_maschinenlesbar(hotel, capsys):
    import json

    main([f"{hotel}/booking", "--check-in", ANREISE, "--naechte", "2", "--json"])
    daten = json.loads(capsys.readouterr().out)
    assert daten[0]["gefunden"] == 3
    assert daten[0]["kategorien"][0]["preis_gesamt"] == 1430.0


def test_leeres_ergebnis_ergibt_exitcode_1(hotel, capsys):
    """Damit ein Skript merkt, dass nichts kam."""
    code = main([f"{hotel}/gibtesnicht", "--check-in", ANREISE, "--naechte", "1"])
    ausgabe = capsys.readouterr().out
    assert code == 1
    assert "Keine Kategorien gefunden" in ausgabe
    assert "Probierte Adressen" in ausgabe


def test_falsches_datum_meldet_sich_sofort(hotel, capsys):
    code = main([f"{hotel}/booking", "--check-in", "22.02.2027", "--naechte", "2"])
    assert code == 2
    assert "JJJJ-MM-TT" in capsys.readouterr().err


def test_mehrere_haeuser_in_einem_lauf(hotel, capsys):
    code = main([f"{hotel}/booking", f"{hotel}/nurdom",
                 "--check-in", ANREISE, "--naechte", "1"])
    ausgabe = capsys.readouterr().out
    assert code == 0
    assert "Sky View Cabin Deluxe" in ausgabe and "Dobbeltrom" in ausgabe


@pytest.mark.parametrize("wert,erwartet", [(25.0, "25"), (16.5, "16.5"), (None, "-")])
def test_groessendarstellung(wert, erwartet):
    assert _groesse(wert) == erwartet


def test_debug_verzeichnis_weicht_aus_wenn_unbenutzbar(tmp_path, monkeypatch):
    """Im Container gehoert der eingehaengte debug-Ordner oft dem Host-Root.
    Die Fehlersuche darf nicht genau dann scheitern, wenn man sie braucht.

    Unbenutzbar wird hier ueber einen Pfad erzeugt, dessen Elternteil eine
    Datei ist - Rechte-Bits taugen dafuer nicht, weil die Testsuite je nach
    Umgebung als root laeuft und root sie schlicht ignoriert.
    """
    from nordlicht_rates import config

    keine_datei = tmp_path / "ich_bin_eine_datei"
    keine_datei.write_text("x", encoding="utf-8")
    unmoeglich = keine_datei / "debug"

    monkeypatch.setenv("NORDLICHT_DEBUG_DIR", str(unmoeglich))
    config.einstellungen.cache_clear()
    try:
        ziel = config.schreibbares_debug_verzeichnis()
        assert ziel != unmoeglich
        assert ziel.is_dir()
        probe = ziel / "probe.txt"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    finally:
        config.einstellungen.cache_clear()


def test_debug_verzeichnis_wird_normal_genutzt(tmp_path, monkeypatch):
    """Der Ausweichort darf nicht ueberhandnehmen: Ist der Ordner brauchbar,
    landen die Dateien dort."""
    from nordlicht_rates import config

    monkeypatch.setenv("NORDLICHT_DEBUG_DIR", str(tmp_path / "debug"))
    config.einstellungen.cache_clear()
    try:
        assert config.schreibbares_debug_verzeichnis() == tmp_path / "debug"
    finally:
        config.einstellungen.cache_clear()
