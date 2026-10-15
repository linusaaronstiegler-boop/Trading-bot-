import json, os, sys, glob
import pytest

WURZEL = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, WURZEL)
FIXTURES = sorted(glob.glob(os.path.join(WURZEL, 'tests', 'fixtures', '*.json')))


def lade_fixture(pfad):
    with open(pfad) as f: return json.load(f)


@pytest.fixture(params=FIXTURES, ids=[os.path.basename(p)[:-5] for p in FIXTURES])
def tagesfixture(request):
    return lade_fixture(request.param)


@pytest.fixture(autouse=True)
def nichts_ins_repo_schreiben(monkeypatch):
    """Direkt aufgerufene Bot-Funktionen (ohne main) schreiben sonst log.txt/state.json ins Arbeitsverzeichnis des Repos."""
    import systembuch_bot
    monkeypatch.setitem(systembuch_bot.AUSGABE, 'schreiben', False)
