"""Dauertest: der echte Live-Lauf (systembuch_bot.main) Tag für Tag über ein Halbjahr gegen die Alpaca-Attrappe mit Yahoo-Kursen.

Prüft das Zusammenspiel von Aufgabe 1/2/5: jeder Lauf grün, nie „ABGLEICH NÖTIG“, Legs = Positionen, Stops ausgelöst und abgerechnet,
Journal vollständig – und das Ergebnis liegt nahe am Replay desselben Zeitraums (gleicher Code in kern, andere Buchhaltung).
Braucht den Yahoo-Cache unter daten/ und pandas (für den Replay-Vergleich)."""
import csv, json, os
import pytest

WURZEL = os.path.join(os.path.dirname(__file__), '..')
if not os.path.exists(os.path.join(WURZEL, 'daten', 'SPY_1d.csv')): pytest.skip('kein Yahoo-Cache unter daten/', allow_module_level=True)
pd = pytest.importorskip('pandas')

import kern, replay
import systembuch_bot as v2
from tests.alpaca_attrappe import AlpacaAttrappe

VON, BIS = '2025-01-02', '2025-06-30'
LEIHBAR = {s: s not in ('EWG', 'USO', 'FXE') for s in kern.TSMOM}


def lade_alle():
    out = {}
    for s in kern.ALLE_SYMBOLE + ('^VIX', '^VIX3M'):
        rows = list(csv.DictReader(open(os.path.join(WURZEL, 'daten', f"{s.replace('^', '_')}_1d.csv"))))
        out[s] = [(r['datum'], float(r['o']), float(r['h']), float(r['l']), float(r['c']), float(r['adj'])) for r in rows]
    return out


def tag_fixture(alle, d):
    hist, live, ohlc = {}, {}, {}
    for s in kern.ALLE_SYMBOLE:
        rows = alle[s]; idx = next((i for i, r in enumerate(rows) if r[0] == d), None)
        if idx is None: continue
        _, o, h, l, c, a = rows[idx]; f0 = a / c
        live[s] = dict(px=c, hi=h, lo=l); ohlc[s] = (o, h, l, c)
        hist[s] = [(r[0], *[x * (r[5] / r[4]) / f0 for x in r[1:5]]) for r in rows[max(0, idx - 270):idx]]
    vix = {r[0]: r[4] for r in alle['^VIX']}[d]; vix3m = {r[0]: r[4] for r in alle['^VIX3M']}[d]
    return dict(heute=d, clock=dict(timestamp=f'{d}T19:45:00Z', next_close=f'{d}T20:00:00Z', is_open=True), equity=100000.0,
                hist=hist, live=live, vix=vix, vix3m=vix3m, leihbar=LEIHBAR, state={'legs': []}), ohlc


def test_halbjahr_live_gegen_attrappe(monkeypatch, tmp_path):
    alle = lade_alle()
    tage = [r[0] for r in alle['SPY'] if VON <= r[0] <= BIS]
    fx, _ = tag_fixture(alle, tage[0])
    b = AlpacaAttrappe(fx); b.mit_bargeld = True; b.installieren(v2, monkeypatch, tmp_path, state=False)
    for d in tage:
        fx_neu, ohlc = tag_fixture(alle, d)
        b.fx.clear(); b.fx.update(fx_neu)
        for sym, (o, h, l, c) in ohlc.items():                                   # BB-Stops intraday: Fill zu min(Eröffnung, Stop)
            for x in list(b.orders.values()):
                if x['symbol'] == sym and x['type'] == 'stop' and x['status'] == 'accepted' and l <= float(x['stop_price']):
                    b.stop_ausloesen(sym, min(o, float(x['stop_price'])), d)
        b.neuer_tag(d); b.bewerten()
        try: r = v2.main([])
        except SystemExit as e: pytest.fail(f'{d}: Lauf rot (Exit {e.code}): ' + open(tmp_path / 'STATUS.md').read()[:600])
        st = json.load(open(tmp_path / 'state.json'))
        b.schluss(d)
        soll = {}
        for l in st['legs']:
            n = l['stueck'] - (l['ausstieg']['menge'] if l.get('ausstieg') else 0)
            soll[l['symbol']] = soll.get(l['symbol'], 0) + l['richtung'] * n
        assert {s: n for s, n in soll.items() if n} == b.positionen, d                   # nach dem Schluss: Legs = Positionen
    journal = list(csv.DictReader(open(tmp_path / 'journal.csv')))
    assert len(journal) > 300 and all(z['ausstieg'] and z['einstieg'] for z in journal)
    assert all(z['schluss_ausstieg'] for z in journal)                                   # intern Verrechnetes: Preis = offizieller Schluss
    # Vergleich mit dem Replay desselben Halbjahrs (Bewertung dort mit Dividenden, hier ohne → kleine Differenz erlaubt)
    D = replay.Daten(BIS); i0, i1 = D.index_ab(VON), D.index_bis(BIS)
    kal = kern.Kalender(D.tage + kern.regel_handelstage('2025-07-01', '2025-08-31')[0])
    sim = replay.simuliere(D, replay.kennzahlen_alle(D, i0, i1), i0, i1, None, 'beide', 0.0, 100000.0, LEIHBAR, kal)
    r_live, r_sim = b.equity / 100000 - 1, sim['tage']['equity'].iloc[-1] / 100000 - 1
    print(f'Live-Code {r_live:+.2%}, Replay {r_sim:+.2%}, Journal {len(journal)}, Replay-Trades {len(sim["trades"])}')
    assert abs(r_live - r_sim) < 0.015, (r_live, r_sim)
    assert abs(len(journal) - len(sim['trades'])) / len(sim['trades']) < 0.05, (len(journal), len(sim['trades']))
