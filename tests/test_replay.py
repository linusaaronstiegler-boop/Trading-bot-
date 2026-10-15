"""Replay (SPEC Aufgabe 3): läuft über denselben Code wie live und hält die Buchhaltung geschlossen. Braucht pandas und den Yahoo-Cache."""
import os
import pytest

pd = pytest.importorskip('pandas')
WURZEL = os.path.join(os.path.dirname(__file__), '..')
if not os.path.exists(os.path.join(WURZEL, 'daten', 'SPY_1d.csv')): pytest.skip('kein Yahoo-Cache unter daten/', allow_module_level=True)

import kern, replay


@pytest.fixture(scope='module')
def jahr():
    D = replay.Daten('2024-12-31')
    i0, i1 = D.index_ab('2024-01-02'), D.index_bis('2024-12-31')
    KZ = replay.kennzahlen_alle(D, i0, i1)
    kal = kern.Kalender(D.tage + kern.regel_handelstage('2025-01-01', '2025-02-28')[0])
    return D, KZ, i0, i1, kal


def test_replay_ruft_kern_entscheide(jahr, monkeypatch):
    D, KZ, i0, i1, kal = jahr
    aufrufe = []
    original = kern.entscheide
    monkeypatch.setattr(kern, 'entscheide', lambda *a, **k: aufrufe.append(1) or original(*a, **k))
    erg = replay.simuliere(D, KZ, i0, i1, None, 'beide', 3.0, 100000.0, {s: True for s in kern.TSMOM}, kal)
    assert len(aufrufe) == i1 - i0 + 1
    assert len(erg['trades']) > 100


def test_sperre_dreht_nie_durch_null(jahr, monkeypatch):
    """Mit Sperre geht kein Symbol an einem Tag von long nach short oder umgekehrt."""
    D, KZ, i0, i1, kal = jahr
    gesehen = []
    original = kern.netto_orders
    def pruefe(legs, aus, ein, sperre='beide'):
        r = original(legs, aus, ein, sperre)
        for s, d in r['orders'].items():
            P = sum(l['richtung'] * l['stueck'] for l in legs if l['symbol'] == s)
            T = P + d
            assert P == 0 or T == 0 or (P > 0) == (T > 0), (s, P, d)
        gesehen.extend(r['gekreuzt'])
        return r
    monkeypatch.setattr(kern, 'netto_orders', pruefe)
    replay.simuliere(D, KZ, i0, i1, None, 'beide', 3.0, 100000.0, {s: True for s in kern.TSMOM}, kal)


def test_kosten_drei_bp_je_seite(jahr):
    D, KZ, i0, i1, kal = jahr
    a = replay.simuliere(D, KZ, i0, i1, None, 'aus', 3.0, 100000.0, {s: True for s in kern.TSMOM}, kal)
    b = replay.simuliere(D, KZ, i0, i1, None, 'aus', 0.0, 100000.0, {s: True for s in kern.TSMOM}, kal)
    assert a['tage']['equity'].iloc[-1] < b['tage']['equity'].iloc[-1]
    assert b['trades']['kosten'].sum() == 0


@pytest.mark.parametrize('schalter', [['--ohne-mw-land'], ['--nur', 'IBS'], ['--ohne-sektor', '--tsmom-reserve']])
def test_bericht_mit_k4_schaltern(schalter, tmp_path):
    """Review v2: Mit K4-Schaltern fehlen Spalten in der Korrelation – BERICHT.md muss trotzdem geschrieben werden (vorher KeyError)."""
    replay.main(['2024-01-02', '2024-03-28', '--ausgabe', str(tmp_path), *schalter])
    assert 'Korrelation MW/MW-Land' in (tmp_path / 'BERICHT.md').read_text()
    assert 'vix_vortag' in (tmp_path / 'varianten.csv').read_text()


def test_vix_vortag_entscheidet_mit_dem_vortagesschluss(jahr):
    """Messvariante (keine Regel): vix_versatz=1 nimmt VIX/VIX3M vom Vortag – Einstiege in SVXY verschieben sich, nie früher."""
    D, KZ, i0, i1, kal = jahr
    ein = lambda erg: sorted(t for t in erg['trades'].query("strategie == 'VIX'")['einstieg_datum'])
    a = replay.simuliere(D, KZ, i0, i1, dict(strategien=frozenset({'VIX'})), 'beide', 3.0, 100000.0, {}, kal)
    b = replay.simuliere(D, KZ, i0, i1, dict(strategien=frozenset({'VIX'})), 'beide', 3.0, 100000.0, {}, kal, vix_versatz=1)
    assert ein(a) and ein(b) and ein(b)[0] >= ein(a)[0]


def test_zeitraum_ohne_tresor(tmp_path):
    """Review v2: Lernzeit-Lauf (endet vor 02.10.2023) stürzte im Tresor-Abschnitt ab."""
    replay.main(['2019-01-02', '2019-03-29', '--nur-hauptlauf', '--ausgabe', str(tmp_path)])
    assert 'enthält den Tresor nicht' in (tmp_path / 'BERICHT.md').read_text()


def test_svxy_ab_auflage_handelbar():
    """SPEC 3 / K3: SVXY ab Auflage 10/2011, nicht erst nach 60 Handelstagen."""
    D = replay.Daten('2011-12-30')
    i0, i1 = D.index_ab('2011-10-04'), D.index_bis('2011-10-31')
    KZ = replay.kennzahlen_alle(D, i0, i1)
    erster = next(D.tage[i] for i in range(i0, i1 + 1) if 'SVXY' in KZ[i])
    assert erster <= '2011-10-05' and KZ[D.pos[erster]]['SVXY']['atr20'] >= 0
