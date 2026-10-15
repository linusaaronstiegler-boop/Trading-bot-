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
