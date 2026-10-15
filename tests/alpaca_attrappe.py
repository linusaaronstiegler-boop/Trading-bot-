"""Alpaca-Attrappe für Tests ohne Netz: beantwortet die Aufrufe des Live-Laufs aus einer Tages-Fixture."""
import json, sys


class AlpacaAttrappe:
    def __init__(self, fx):
        self.fx = fx; self.aufrufe = []

    def alp(self, path, body=None, method=None, base=None, tries=3):
        fx = self.fx; self.aufrufe.append((method or 'GET', path, body))
        if path == '/v2/clock': return fx['clock']
        if path == '/v2/account': return {'equity': str(fx['equity'])}
        if path.startswith('/v2/assets/'): return {'shortable': fx['leihbar'].get(path.rsplit('/', 1)[1].split('?')[0], False)}
        raise AssertionError(f'unerwarteter Alpaca-Aufruf {method} {path}')

    def dry_lauf(self, v2, monkeypatch, tmp_path):
        fx = self.fx
        monkeypatch.chdir(tmp_path)
        if fx.get('state'): json.dump(fx['state'], open(tmp_path / 'state.json', 'w'))
        gefangen = {}
        def status_md(st, eq, dd, kz, ratio, plan, schliessen, neu, heute, dry=False): gefangen.update(plan=plan)
        monkeypatch.setattr(v2, 'alp', self.alp)
        monkeypatch.setattr(v2, 'bars', lambda symbols, tage=420: {s: [tuple(r) for r in fx['hist'].get(s, [])] for s in symbols})
        monkeypatch.setattr(v2, 'snapshots', lambda symbols: {s: fx['live'][s] for s in symbols if s in fx['live']})
        monkeypatch.setattr(v2, 'yahoo_live', lambda sym: fx['vix'] if sym == '^VIX' else fx['vix3m'])
        monkeypatch.setattr(v2, 'status_md', status_md)
        monkeypatch.setattr(sys, 'argv', ['systembuch_bot.py', '--dry', '--force'])
        v2.main()
        return gefangen
