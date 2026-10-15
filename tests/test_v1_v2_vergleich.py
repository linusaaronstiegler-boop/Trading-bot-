"""Abnahme Aufgabe 1: v1 und v2 liefern auf denselben eingefrorenen Tagesdaten dieselben Netto-Orders.

v1 (`tests/v1_referenz.py`, unveränderte Kopie des Stands vom 15.10.2026) läuft mit `--dry --force`; Netz, Uhr und Konto
werden durch die Fixture ersetzt. v2 rechnet mit `kern.entscheide()` auf denselben Daten und demselben Kalender wie v1
(v1-Feiertagstabelle), damit nur die Entscheidungslogik verglichen wird.
"""
import copy, datetime as dt, sys
import pytest
import kern
from tests import v1_referenz as v1


def lauf_v1(fx, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    if fx.get('state'):
        import json; json.dump(fx['state'], open(tmp_path / 'state.json', 'w'))
    def alp(path, body=None, method=None, base=None, tries=3):
        if path == '/v2/clock': return fx['clock']
        if path == '/v2/account': return {'equity': str(fx['equity'])}
        if path.startswith('/v2/assets/'): return {'shortable': fx['leihbar'].get(path.rsplit('/', 1)[1], False)}
        raise AssertionError(f'unerwarteter Aufruf {path}')
    gefangen = {}
    def status_md(st, eq, dd, kz, ratio, plan, schliessen, neu, heute, dry=False):
        gefangen.update(plan=plan, aus=[(l['strategie'], l['symbol'], l['richtung'] * l['stueck'], g) for l, g in schliessen],
                        ein=[(l['strategie'], l['symbol'], l['richtung'] * l['stueck']) for l in neu])
    monkeypatch.setattr(v1, 'alp', alp)
    monkeypatch.setattr(v1, 'bars', lambda symbols, tage=420: {s: [tuple(r) for r in fx['hist'].get(s, [])] for s in symbols})
    monkeypatch.setattr(v1, 'snapshots', lambda symbols: {s: fx['live'][s] for s in symbols if s in fx['live']})
    monkeypatch.setattr(v1, 'yahoo_live', lambda sym: fx['vix'] if sym == '^VIX' else fx['vix3m'])
    monkeypatch.setattr(v1, 'status_md', status_md)
    monkeypatch.setattr(sys, 'argv', ['systembuch_bot.py', '--dry', '--force'])
    v1.main()
    return gefangen


def v1_kalender(heute):
    """Kalender wie v1 ihn sieht: Werktage ohne v1-FEIERTAGE (± 3 Monate um heute)."""
    d = dt.date.fromisoformat(heute) - dt.timedelta(days=100); ende = dt.date.fromisoformat(heute) + dt.timedelta(days=60)
    tage = []
    while d <= ende:
        if d.weekday() < 5 and d.isoformat() not in v1.FEIERTAGE: tage.append(d.isoformat())
        d += dt.timedelta(days=1)
    return kern.Kalender(tage, quelle='v1-Tabelle')


def lauf_v2(fx):
    st = copy.deepcopy(fx['state'])
    hist = {s: [tuple(r) for r in rows] for s, rows in fx['hist'].items()}
    kurse = dict(fx['live']); kurse['^VIX'] = {'px': fx['vix']}; kurse['^VIX3M'] = {'px': fx['vix3m']}
    eq = fx['equity']; hwm = max(st['hwm'] or eq, eq)
    zustand = dict(heute=fx['heute'], equity=eq, hwm=hwm, legs=st['legs'], leihbar=fx['leihbar'])
    aus, ein, info = kern.entscheide(zustand, kurse, hist, v1_kalender(fx['heute']))
    return dict(plan=kern.netto_plan(aus, ein),
                aus=[(l['strategie'], l['symbol'], l['richtung'] * l['stueck'], g) for l, g in aus],
                ein=[(l['strategie'], l['symbol'], l['richtung'] * l['stueck']) for l in ein]), info, aus, ein, st


def test_v1_gleich_v2(tagesfixture, monkeypatch, tmp_path):
    r1 = lauf_v1(tagesfixture, monkeypatch, tmp_path)
    r2, info, *_ = lauf_v2(tagesfixture)
    assert r1['plan'], 'Fixture ohne Orders taugt nicht als Vergleich'
    assert r2['plan'] == r1['plan']
    assert r2['aus'] == r1['aus']
    assert r2['ein'] == r1['ein']


def test_fixtures_decken_die_pfade_ab():
    """Die fünf Fixtures zusammen berühren jede Regel aus der README-Tabelle mindestens einmal (Ein- oder Ausstieg)."""
    from tests.conftest import FIXTURES, lade_fixture
    ein, aus = set(), set()
    for p in FIXTURES:
        r, *_ = lauf_v2(lade_fixture(p))
        ein |= {e[0] for e in r['ein']}; aus |= {a[3].split(' (')[0] for a in r['aus']}
    assert ein >= {'IBS', 'IBS_SEKTOR', 'IBS_LAND', 'BB', 'MW', 'MW_LAND', 'TSMOM'}, ein
    assert aus >= {'IBS Ausstieg Folgetag', 'Monatswechsel Verkauf', 'TSMOM Umschichtung', 'VIX Backwardation'}, aus


def test_live_dry_lauf_v2_gleich_v1(tagesfixture, monkeypatch, tmp_path):
    """Abnahme SPEC: `--dry --force` von v2 liefert auf der Fixture dieselben Netto-Orders wie v1."""
    import systembuch_bot as v2
    r1 = lauf_v1(tagesfixture, monkeypatch, tmp_path)
    r2 = live_dry_v2(v2, tagesfixture, monkeypatch, tmp_path)
    assert r2['plan'] == r1['plan']


def live_dry_v2(v2, fx, monkeypatch, tmp_path):
    from tests.alpaca_attrappe import AlpacaAttrappe
    return AlpacaAttrappe(fx).dry_lauf(v2, monkeypatch, tmp_path)
