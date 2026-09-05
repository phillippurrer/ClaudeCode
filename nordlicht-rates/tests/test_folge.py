"""Eingebettete Buchungsmaschinen finden.

Der Anlass ist die Northern Lights Ranch: theranch.fi zeigt selbst keinen
einzigen Preis, die Zimmer kommen aus einem Mews-Distributor auf fremder
Domain. Ohne diesen Schritt laeuft jeder Abruf ins Leere.
"""

from nordlicht_rates.folge import (
    finde_buchungs_frames,
    finde_mews_distributoren,
    folge_ziele,
    mews_distributor_url,
)

# Die drei GUIDs, die auf theranch.fi/check-availability/ gefunden wurden.
GUIDS = [
    "fab92ee0-3fcd-401b-8539-b0900078ac94",
    "0ac5c0a8-0c14-44d3-8f41-81e40ad00acd",
    "5557d5eb-e560-4721-b145-9f500b4e6d18",
]

RANCH_MARKUP = f"""<html><head><link rel=stylesheet href="/theme/mews.css"></head>
<body><div class="mews-widget" data-mews-configuration="{GUIDS[0]}"></div>
<script>var configurationIds = ["{GUIDS[1]}", "{GUIDS[2]}"];</script></body></html>"""


def test_alle_guids_einer_liste_werden_gefunden():
    """Regression: ein Regex, der nur die erste Zuweisung greift, verliert
    die uebrigen Konfigurationen - und damit moeglicherweise ganze
    Huettenkategorien."""
    assert set(finde_mews_distributoren(RANCH_MARKUP)) == set(GUIDS)


def test_direkte_distributor_url_wird_erkannt():
    html = f'<a href="https://app.mews.com/distributor/{GUIDS[0]}">Buchen</a>'
    assert finde_mews_distributoren(html) == [GUIDS[0]]


def test_deckel_auf_drei_zielen():
    viele = " ".join(
        f'data-mews-configuration="{i:08d}-0000-0000-0000-000000000000"'
        for i in range(10)
    )
    assert len(finde_mews_distributoren(viele)) <= 3


def test_ohne_mews_keine_uuid_jagd():
    """Eine beliebige UUID auf einer Seite ohne Mews-Bezug ist kein Ziel."""
    html = '<html><body data-session="fab92ee0-3fcd-401b-8539-b0900078ac94">'
    assert finde_mews_distributoren(html) == []


def test_folge_ziele_baut_distributor_urls():
    ziele = folge_ziele(RANCH_MARKUP, "generic")
    assert ziele[0] == mews_distributor_url(GUIDS[0])
    assert all(z.startswith("https://app.mews.com/distributor/") for z in ziele)


def test_upperbooking_wird_erkannt():
    """Northern Lights Village Levi laeuft darueber."""
    html = ('<iframe src="https://upperbooking.com/de/booking/start/'
            'northernlightsvillagelevi1"></iframe>')
    assert folge_ziele(html, "generic")[0].startswith("https://upperbooking.com/")


def test_relative_iframes_werden_aufgeloest():
    html = '<iframe src="/booking?lang=de"></iframe>'
    ziele = finde_buchungs_frames(html, "https://hotel.fi/verfuegbarkeit")
    assert ziele == ["https://hotel.fi/booking?lang=de"]


def test_fremde_iframes_werden_ignoriert():
    """Ein Werbevideo ist keine Buchungsstrecke."""
    html = ('<iframe src="https://www.youtube.com/embed/abc"></iframe>'
            '<iframe src="https://maps.google.com/maps?q=levi"></iframe>')
    assert finde_buchungs_frames(html, "https://hotel.fi/") == []


def test_leeres_markup_wirft_nicht():
    assert folge_ziele("", "generic") == []
    assert finde_mews_distributoren("") == []
    assert finde_buchungs_frames("<iframe>", "") == []
