#!/usr/bin/env python3
"""Fünf-Minuten-Prüfungen aus REVIEW-v1.md §8 (plus Prüfung 6) auf dem Alpaca-PAPER-Konto. Ergebnis → pruefungen-ergebnis.md.

  python3 werkzeuge/paper_pruefungen.py --lesen     Prüfung 1 und 3 (nur lesen, jederzeit) und assets.json einfrieren
  python3 werkzeuge/paper_pruefungen.py --orders    Prüfung 2, 4 und 6 (Test-Orders mit je 1–2 Stück; nur 10–30 Min vor Schluss,
                                                     nur auf einem Konto ohne Positionen in SPY/IWM, räumt danach auf)
Prüfung 5 (VIX im ersten Actions-dry-Lauf) steht in STATUS-dry.md („Quelle: …“), nicht hier.

Läuft ausschließlich gegen paper-api.alpaca.markets. Schlüssel nur aus APCA_API_KEY_ID / APCA_API_SECRET_KEY, werden nie ausgegeben.
Wichtig: vor dem ersten Live-Lauf des Bots ausführen – Test-Positionen würden sonst den Positionsabgleich stören.
"""
import argparse, datetime as dt, json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import kern
import systembuch_bot as bot

assert bot.PAPER == 'https://paper-api.alpaca.markets'
ERG = []


def notiz(nr, titel, ergebnis, roh=None):
    ERG.append((nr, titel, ergebnis, roh)); print(f'[{nr}] {titel}: {ergebnis}')


def versuch(f):
    try: return True, f()
    except Exception as e: return False, str(e)[:300]


def warte_status(oid, s=10):
    ende = time.time() + s
    while time.time() < ende:
        o = bot.alp(f'/v2/orders/{oid}')
        if o['status'] not in ('pending_new', 'new'): return o
        time.sleep(0.5)
    return bot.alp(f'/v2/orders/{oid}')


def storno(oid):
    try: bot.alp(f'/v2/orders/{oid}', method='DELETE')
    except Exception: pass
    return warte_status(oid)


def lesen():
    ok, r = versuch(lambda: bot.alp('/v2/stocks/snapshots?symbols=EWL,SPY&feed=delayed_sip', base=bot.DATA))
    notiz(1, 'Snapshot feed=delayed_sip', 'HTTP 200 – Hoch/Tief aus SIP nutzbar' if ok else f'abgelehnt → Snapshot bleibt IEX ({r})',
          {s: (v.get('dailyBar') or {}) for s, v in r.items()} if ok else None)
    ok, a = versuch(lambda: bot.alp('/v2/assets/SVXY')); ok2, k = versuch(lambda: bot.alp('/v2/account'))
    notiz(3, 'SVXY-Marge und Buying Power',
          f"SVXY marginable={a.get('marginable')}, maintenance_margin_requirement={a.get('maintenance_margin_requirement')}, shortable={a.get('shortable')}; "
          f"Konto equity={k.get('equity')}, regt_buying_power={k.get('regt_buying_power')}, buying_power={k.get('buying_power')}, multiplier={k.get('multiplier')}"
          if ok and ok2 else f'Fehler: {a if not ok else k}')
    aus = {}
    for s in kern.TSMOM + (kern.VIX_ETF,):
        ok, x = versuch(lambda: bot.alp(f'/v2/assets/{s}'))
        if ok: aus[s] = {f: x.get(f) for f in ('shortable', 'easy_to_borrow', 'marginable', 'maintenance_margin_requirement', 'tradable')}
    fehlt = [s for s in kern.TSMOM + (kern.VIX_ETF,) if s not in aus]
    if fehlt:
        notiz('A', 'assets.json NICHT geschrieben', f'keine Antwort für {fehlt}'); return
    json.dump(dict(stand=dt.date.today().isoformat(), quelle='Alpaca /v2/assets (Paper)', shortable={s: bool(v['shortable']) for s, v in aus.items()},
                   details=aus), open('assets.json', 'w'), indent=1)
    nicht = [s for s, v in aus.items() if not v['shortable'] and s in kern.TSMOM]
    notiz('A', 'assets.json eingefroren', f'nicht leihbar: {nicht or "keins"} (K3-Annahme: EWG, USO, FXE)')


def orders():
    clock = bot.alp('/v2/clock'); m = (bot.zeit(clock['next_close']) - bot.zeit(clock['timestamp'])).total_seconds() / 60
    if not clock['is_open'] or not (11 <= m <= 30): sys.exit(f'nur 11–30 Min vor Schluss ausführen (jetzt {m:.1f} Min, offen={clock["is_open"]})')
    pos = {p['symbol']: p for p in bot.alp('/v2/positions')}
    if 'SPY' in pos or 'IWM' in pos: sys.exit('Konto hat SPY/IWM-Positionen – Prüfungen nur auf flachem Konto (vor dem ersten Live-Lauf)')
    if any(o['symbol'] in ('SPY', 'IWM') for o in bot.alp('/v2/orders?status=open')): sys.exit('offene SPY/IWM-Orders – erst stornieren')
    # 2) Short per MOC ohne Position
    ok, o = versuch(lambda: bot.alp('/v2/orders', dict(symbol='IWM', qty='1', side='sell', type='market', time_in_force='cls'), 'POST', tries=1))
    if ok:
        o = warte_status(o['id']); notiz(2, 'Short-MOC 1 IWM ohne Position', f"Status {o['status']} → {'angenommen' if o['status'] in ('accepted', 'new', 'pending_new') else 'abgelehnt'}")
        storno(o['id'])
    else: notiz(2, 'Short-MOC 1 IWM ohne Position', f'abgelehnt: {o}')
    # 4) Long 1 SPY (market, day), dann Verkauf 2 SPY per MOC → Vorzeichenwechsel in einer Order
    ok, b = versuch(lambda: bot.alp('/v2/orders', dict(symbol='SPY', qty='1', side='buy', type='market', time_in_force='day'), 'POST', tries=1))
    if ok:
        b = warte_status(b['id'], 20)
        ok2, s2 = versuch(lambda: bot.alp('/v2/orders', dict(symbol='SPY', qty='2', side='sell', type='market', time_in_force='cls'), 'POST', tries=1))
        notiz(4, 'Long 1 SPY, dann Verkauf 2 SPY MOC', f'Kauf {b["status"]}; Verkauf 2: ' + (f"angenommen ({warte_status(s2['id'])['status']}) – Review 3.2 widerlegt?" if ok2 else f'abgelehnt: {s2}'))
        if ok2: storno(s2['id'])
        ok3, s1 = versuch(lambda: bot.alp('/v2/orders', dict(symbol='SPY', qty='1', side='sell', type='market', time_in_force='day'), 'POST', tries=1))
        notiz('4b', 'Aufräumen SPY', 'verkauft' if ok3 else f'BITTE VON HAND SCHLIESSEN: {s1}')
    else: notiz(4, 'Long 1 SPY', f'Kauf abgelehnt: {b}')
    # 6) Short 1 IWM (market, day), dann zwei Kauf-MOC: 1 zum Eindecken + 1 neu long → nimmt Alpaca die zweite an?
    ok, sh = versuch(lambda: bot.alp('/v2/orders', dict(symbol='IWM', qty='1', side='sell', type='market', time_in_force='day'), 'POST', tries=1))
    if ok:
        sh = warte_status(sh['id'], 20); time.sleep(2)
        ok1, k1 = versuch(lambda: bot.alp('/v2/orders', dict(symbol='IWM', qty='1', side='buy', type='market', time_in_force='cls'), 'POST', tries=1))
        ok2, k2 = versuch(lambda: bot.alp('/v2/orders', dict(symbol='IWM', qty='1', side='buy', type='market', time_in_force='cls'), 'POST', tries=1))
        notiz(6, 'Short 1 IWM, dann Kauf 1 + Kauf 1 MOC (short → long)',
              f"Short {sh['status']}; Eindecken: {'angenommen' if ok1 else k1}; zweiter Kauf: {'ANGENOMMEN → Sperre kaufseitig evtl. unnötig (BEOBACHTUNGEN 1)' if ok2 else 'abgelehnt: ' + str(k2)}")
        for ok_, k_ in ((ok1, k1), (ok2, k2)):
            if ok_: storno(k_['id'])
        ok3, c = versuch(lambda: bot.alp('/v2/orders', dict(symbol='IWM', qty='1', side='buy', type='market', time_in_force='day'), 'POST', tries=1))
        notiz('6b', 'Aufräumen IWM', 'eingedeckt' if ok3 else f'BITTE VON HAND SCHLIESSEN: {c}')
    else: notiz(6, 'Short 1 IWM', f'abgelehnt: {sh}')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--lesen', action='store_true'); ap.add_argument('--orders', action='store_true'); a = ap.parse_args()
    if not (a.lesen or a.orders): ap.error('--lesen und/oder --orders')
    if not (os.environ.get('APCA_API_KEY_ID') and os.environ.get('APCA_API_SECRET_KEY')): sys.exit('APCA_API_KEY_ID / APCA_API_SECRET_KEY fehlen')
    if a.lesen: lesen()
    if a.orders: orders()
    with open('pruefungen-ergebnis.md', 'a') as f:
        f.write(f'\n## Paper-Prüfungen {dt.datetime.now(bot.NY):%Y-%m-%d %H:%M} ET\n\n')
        for nr, titel, erg, roh in ERG: f.write(f'- **{nr}. {titel}:** {erg}\n')
    print('→ pruefungen-ergebnis.md')


if __name__ == '__main__':
    main()
