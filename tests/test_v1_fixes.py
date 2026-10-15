"""Die drei Review-Fixes, die Linus am 15.10. 22:30–23:15 in v1 gebaut hat (SPEC-v2 „Review-Risiken“), in v2 abgesichert.

1.12 Karfreitag 2027 = 26.03. · 5.5 Positionsabgleich zu Laufbeginn (nur us_equity, live Exit 1, dry nur Meldung) ·
3.5 abgelehnte Orders (schließende Legs bleiben mit `ausstieg_offen`, neue Legs entfallen, Exit 1).
Jeweils v1 (`tests/v1_referenz.py`, Stand 23:15) und v2 auf derselben Fixture – „übernehmen, nicht neu erfinden“.
"""
import copy, datetime as dt, json, sys
import kern
import systembuch_bot as v2
from tests import v1_referenz as v1
from tests.alpaca_attrappe import AlpacaAttrappe
from tests.conftest import FIXTURES, lade_fixture

F1 = [p for p in FIXTURES if 'f1_' in p][0]
F3 = [p for p in FIXTURES if 'f3_' in p][0]
KRYPTO = dict(symbol='BTCUSD', qty='0.5', side='long', asset_class='crypto', lastday_price='60000', market_value='30000')


def bestand(legs):
    out = {}
    for l in legs: out[l['symbol']] = out.get(l['symbol'], 0) + l['richtung'] * l['stueck']
    return {s: n for s, n in out.items() if n}


def lauf_v1(fx, monkeypatch, tmp_path, dry=False, ablehnen=(), extra=(), zusatz_positionen=None):
    """v1 mit `--force` (live) bzw. `--dry --force` gegen eine kleine Broker-Attrappe. → (Exit-Code, state, Logzeilen, Order-POSTs)."""
    monkeypatch.chdir(tmp_path)
    json.dump(fx['state'], open(tmp_path / 'state.json', 'w'))
    pos = bestand(fx['state']['legs'])
    for s, n in (zusatz_positionen or {}).items(): pos[s] = pos.get(s, 0) + n
    logzeilen, posts = [], []
    def alp(path, body=None, method=None, base=None, tries=3):
        if path == '/v2/clock': return fx['clock']
        if path == '/v2/account': return {'equity': str(fx['equity'])}
        if path == '/v2/positions':
            return [dict(symbol=s, qty=str(n), side='long' if n > 0 else 'short', asset_class='us_equity') for s, n in pos.items()] + list(extra)
        if path.startswith('/v2/assets/'): return {'shortable': fx['leihbar'].get(path.rsplit('/', 1)[1], False)}
        if path == '/v2/orders' and method == 'POST':
            posts.append(body)
            if body['type'] == 'market' and body['symbol'] in ablehnen: raise RuntimeError('HTTP 403: insufficient qty available')
            return {'id': f'o{len(posts)}'}
        if path.startswith('/v2/orders/') and method == 'DELETE': return {}
        if path.startswith('/v2/orders/'): return {'status': 'new'}
        raise AssertionError(f'unerwarteter Aufruf {method} {path}')
    monkeypatch.setattr(v1, 'alp', alp)
    monkeypatch.setattr(v1, 'log', logzeilen.append)
    monkeypatch.setattr(v1, 'bars', lambda symbols, tage=420: {s: [tuple(r) for r in fx['hist'].get(s, [])] for s in symbols})
    monkeypatch.setattr(v1, 'snapshots', lambda symbols: {s: fx['live'][s] for s in symbols if s in fx['live']})
    monkeypatch.setattr(v1, 'yahoo_live', lambda sym: fx['vix'] if sym == '^VIX' else fx['vix3m'])
    monkeypatch.setattr(v1, 'status_md', lambda *a, **k: None)
    monkeypatch.setattr(sys, 'argv', ['systembuch_bot.py', *(['--dry'] if dry else []), '--force'])
    try: v1.main(); code = 0
    except SystemExit as e: code = e.code
    return code, json.load(open(tmp_path / 'state.json')), logzeilen, posts


def broker_v2(fx, monkeypatch, tmp_path):
    b = AlpacaAttrappe(fx, positionen=bestand(fx['state']['legs']))
    b.installieren(v2, monkeypatch, tmp_path)
    return b


def lauf_v2(argv=()):
    try: return v2.main(list(argv)), 0
    except SystemExit as e: return None, e.code


def moc(b):
    return {o['symbol']: (1 if o['side'] == 'buy' else -1) * int(o['qty']) for o in b.orders.values() if o['time_in_force'] == 'cls'}


# ---------- 1.12 Kalender ----------
def test_v1_feiertage_und_halbtage_gleich_v2_regelwerk():
    """v1-Tabelle (mit Karfreitag 26.03.2027) = v2-NYSE-Regelwerk für den Zeitraum, den die Tabelle abdeckt."""
    tage, schluss = kern.regel_handelstage('2026-10-15', '2027-12-31')
    werktage = [d for d in (dt.date(2026, 10, 15) + dt.timedelta(n) for n in range(443)) if d.weekday() < 5]
    frei = {d.isoformat() for d in werktage} - set(tage)
    assert frei == v1.FEIERTAGE
    assert '2027-03-26' in frei and '2027-04-02' not in frei
    assert {d for d, z in schluss.items() if z != '16:00'} == v1.HALBE_TAGE


# ---------- 5.5 Positionsabgleich ----------
def test_krypto_im_konto_stoert_den_abgleich_nicht(monkeypatch, tmp_path):
    fx = lade_fixture(F1)
    (tmp_path / 'v1').mkdir(); (tmp_path / 'v2').mkdir()
    code1, st1, log1, posts1 = lauf_v1(copy.deepcopy(fx), monkeypatch, tmp_path / 'v1', extra=[KRYPTO])
    assert code1 == 0 and not any('ABGLEICH' in z for z in log1)
    b = broker_v2(fx, monkeypatch, tmp_path / 'v2'); b.fremde_positionen.append(KRYPTO)
    r, code = lauf_v2()
    assert code == 0
    assert moc(b) == {p['symbol']: (1 if p['side'] == 'buy' else -1) * int(p['qty']) for p in posts1 if p['type'] == 'market'}


def test_abweichung_live_exit1_ohne_order_in_v1_und_v2(monkeypatch, tmp_path):
    fx = lade_fixture(F1)
    (tmp_path / 'v1').mkdir(); (tmp_path / 'v2').mkdir()
    code1, _, log1, posts1 = lauf_v1(copy.deepcopy(fx), monkeypatch, tmp_path / 'v1', zusatz_positionen={'XLE': 10})
    assert code1 == 1 and not [p for p in posts1 if p['type'] == 'market']
    assert 'ABGLEICH NÖTIG' in open(tmp_path / 'v1' / 'STATUS.md').read()
    b = broker_v2(fx, monkeypatch, tmp_path / 'v2'); b.positionen['XLE'] = 10
    r, code = lauf_v2()
    assert code == 1 and not moc(b)
    assert 'ABGLEICH NÖTIG' in open(tmp_path / 'v2' / 'STATUS.md').read()


def test_abweichung_im_dry_lauf_nur_gemeldet_v1_und_v2(monkeypatch, tmp_path):
    fx = lade_fixture(F1)
    (tmp_path / 'v1').mkdir(); (tmp_path / 'v2').mkdir()
    code1, _, log1, _ = lauf_v1(copy.deepcopy(fx), monkeypatch, tmp_path / 'v1', dry=True, zusatz_positionen={'XLE': 10})
    assert code1 == 0 and any('ABGLEICH' in z for z in log1) and any('nur gemeldet' in z for z in log1)
    plan1 = eval(next(z for z in log1 if z.startswith('Netto-MOC-Orders: ')).split(': ', 1)[1])
    b = broker_v2(fx, monkeypatch, tmp_path / 'v2'); b.positionen['XLE'] = 10
    r, code = lauf_v2(['--dry', '--force'])
    assert code == 0 and r['roh'] == plan1
    assert any('ABGLEICH NÖTIG (dry' in z for z in v2.LOGZEILEN)
    assert not (tmp_path / 'v2' / 'STATUS.md').exists()
    assert json.load(open(tmp_path / 'v2' / 'state.json')) == fx['state']                     # dry schreibt keinen Zustand


# ---------- 3.5 abgelehnte Orders ----------
def test_abgelehnte_order_v1_und_v2_gleicher_zustand(monkeypatch, tmp_path):
    """F3 (03.04.2025): SPY = MW-Verkauf 44 + IBS-Kauf 23 → Netto −21, Alpaca lehnt ab.
    v1 und v2: MW-Leg SPY bleibt mit `ausstieg_offen`, IBS-Leg SPY wird nicht angelegt, alle anderen Symbole normal, Exit 1."""
    fx = lade_fixture(F3)
    (tmp_path / 'v1').mkdir(); (tmp_path / 'v2').mkdir()
    code1, st1, log1, _ = lauf_v1(copy.deepcopy(fx), monkeypatch, tmp_path / 'v1', ablehnen={'SPY'})
    assert code1 == 1
    b = broker_v2(fx, monkeypatch, tmp_path / 'v2'); b.ablehnen['SPY'] = 'insufficient qty available'
    r, code = lauf_v2()
    assert code == 1 and 'ORDER ABGELEHNT' in open(tmp_path / 'v2' / 'STATUS.md').read()
    b.schluss(fx['heute'])                                                                     # Schlussauktion, dann Abrechnung wie im Folgelauf
    st2 = json.load(open(tmp_path / 'v2' / 'state.json'))
    v2.abrechnen(st2, '2025-04-04', v2.lade_kalender(dt.date(2025, 4, 4), '2025-01-01'), v2.schlusskurse(set(moc(b)) | {'SPY'}))
    form = lambda legs: sorted((l['strategie'], l['symbol'], l['richtung'] * l['stueck'], bool(l.get('ausstieg_offen'))) for l in legs)
    assert form(st2['legs']) == form(st1['legs'])
    assert [(l['strategie'], l['stueck'], l['ausstieg_offen']) for l in st1['legs'] if l.get('ausstieg_offen')] == [('MW', 44, fx['heute'])]
    assert [(l['strategie'], l['stueck'], l['ausstieg_offen']['datum']) for l in st2['legs'] if l.get('ausstieg_offen')] == [('MW', 44, fx['heute'])]
    assert bestand(st2['legs']) == b.positionen                                                # v2: Zustand = Alpaca nach der Auktion


def test_v1_zustand_mit_ausstieg_offen_als_datum(monkeypatch, tmp_path):
    """v1 vermerkt `ausstieg_offen` als Datumstext. v2 übernimmt den Zustand und holt den Ausstieg im nächsten Lauf nach."""
    fx = lade_fixture(F1)
    iwm = next(l for l in fx['state']['legs'] if l['symbol'] == 'IWM'); iwm['ausstieg_offen'] = '2025-02-26'
    b = broker_v2(fx, monkeypatch, tmp_path)
    v2.AUSGABE.update(schreiben=False)
    st = v2.laden()
    assert next(l for l in st['legs'] if l['symbol'] == 'IWM')['ausstieg_offen'] == dict(grund='Ausstieg', datum='2025-02-26')
    r, code = lauf_v2()
    assert code == 0
    legs = [l for l in json.load(open(tmp_path / 'state.json'))['legs'] if l['symbol'] == 'IWM']
    alt = next(l for l in legs if l['id'] == iwm['id'])
    assert alt['ausstieg'] == dict(alt['ausstieg'], grund='Ausstieg (nachgeholt)', menge=iwm['stueck'])
    neu = [l for l in legs if l['id'] != iwm['id']]                                           # IBS-Signal steht weiter → frischer Einstieg,
    assert moc(b)['IWM'] == -iwm['stueck'] + sum(l['stueck'] for l in neu)                    # als wäre der Ausstieg gestern ausgeführt worden
