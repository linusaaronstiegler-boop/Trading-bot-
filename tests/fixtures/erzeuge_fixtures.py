"""Erzeugt die eingefrorenen Tages-Fixtures für den v1/v2-Vergleich (SPEC Aufgabe 1) aus dem Yahoo-Cache `daten/`.

Format wie ein Alpaca-`--dry`-Lauf: Historie = abgeschlossene Tage vor `heute`, bereinigt relativ zu `heute`
(wie `adjustment=all`), heutiger Stand = Rohkurse (px = Schluss, hi/lo = Tageshoch/-tief).
Ein echter Alpaca-Trockenlauf lässt sich später mit `python3 systembuch_bot.py --dry --force --aufzeichnen tests/fixtures/alpaca_JJJJ-MM-TT.json`
im selben Format einfrieren. Aufruf: python3 tests/fixtures/erzeuge_fixtures.py
"""
import csv, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import kern

FENSTER = 270          # Zeilen Historie je Symbol (Kennzahlen brauchen höchstens 253)
HIER = os.path.dirname(__file__)
DATEN = os.path.join(HIER, '..', '..', 'daten')


def lade(sym):
    fn = os.path.join(DATEN, f"{sym.replace('^', '_')}_1d.csv")
    return [(r['datum'], float(r['o']), float(r['h']), float(r['l']), float(r['c']), float(r['adj'])) for r in csv.DictReader(open(fn))]


def tag_daten(heute, symbole):
    hist, live = {}, {}
    for s in symbole:
        rows = lade(s)
        idx = [i for i, r in enumerate(rows) if r[0] == heute]
        if not idx: continue
        i = idx[0]; d, o, h, l, c, a = rows[i]
        f_heute = a / c
        live[s] = dict(px=round(c, 4), hi=round(h, 4), lo=round(l, 4))
        hist[s] = [[r[0]] + [round(x * (r[5] / r[4]) / f_heute, 4) for x in r[1:5]] for r in rows[max(0, i - FENSTER):i]]
    vix = {r[0]: r[4] for r in lade('^VIX')}[heute]; vix3m = {r[0]: r[4] for r in lade('^VIX3M')}[heute]
    return hist, live, round(vix, 2), round(vix3m, 2)


# Alpaca-Leihbarkeit wie in K3 angenommen (EWG, USO, FXE nicht leihbar); echte Abfrage: assets.json
LEIHBAR = {s: s not in ('EWG', 'USO', 'FXE') for s in kern.TSMOM}


def leg(i, strat, sym, st, ein, datum, atr=1.0, richtung=1, **x):
    d = dict(id=i, strategie=strat, symbol=sym, richtung=richtung, stueck=st, einstieg=ein, datum=datum, atr20=atr, order_id=None)
    d.update(x); return d


def fixture(name, heute, legs, equity=100000.0, hwm=None, beschreibung=''):
    hist, live, vix, vix3m = tag_daten(heute, kern.ALLE_SYMBOLE)
    st = dict(start='2025-01-02', startkapital=100000.0, hwm=hwm or equity, legs=legs, naechste_id=max([l['id'] for l in legs] + [0]) + 1,
              offene_orders={}, gestoppt=False, letzter_lauf=None, tag_zaehler={})
    out = dict(name=name, beschreibung=beschreibung, quelle='Yahoo-Tageskurse (daten/), bereinigt relativ zu heute', heute=heute,
               clock=dict(timestamp=f'{heute}T19:45:00Z', next_close=f'{heute}T20:00:00Z', is_open=True),
               equity=equity, state=st, hist=hist, live=live, vix=vix, vix3m=vix3m, leihbar=LEIHBAR)
    json.dump(out, open(os.path.join(HIER, f'{name}.json'), 'w'), separators=(',', ':'))
    print(name, heute, 'Symbole', len(hist), 'VIX', vix, vix3m)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--suche', action='store_true'); a = ap.parse_args()
    if a.suche:
        # Hilfsmodus: Tage mit seltenen Konstellationen finden
        tage = [r[0] for r in lade('SPY') if '2025-01-01' <= r[0] <= '2026-10-14']
        for d in tage:
            hist, live, vix, vix3m = tag_daten(d, kern.INDEX + kern.SEKTOREN)
            kz = kern.kennzahlen(hist, live)
            bb = [s for s in kern.INDEX if kern.ist_bb_signal(kz.get(s))]
            ibs_i = [s for s in kern.INDEX if kz[s]['ibs'] < 0.2]
            sek = [s for s in kern.SEKTOREN if kz[s]['ibs'] < 0.2]
            if bb or (not ibs_i and len(sek) >= 2) or vix3m / vix < 1.0:
                print(d, 'BB', bb, 'IBS', ibs_i, 'Sektor', sek, 'VIX3M/VIX', round(vix3m / vix, 3))
        sys.exit()

    def px(sym, d):
        return {r[0]: r[4] for r in lade(sym)}[d]

    def n(anteil, sym, d, eq=100000.0):
        return int(anteil * eq / px(sym, d))

    # F1: vorletzter Handelstag Feb. 2025 – MW-Kauf, IBS auf allen vier Index-ETFs, BB auf SPY und QQQ (IBS+BB im selben Symbol,
    #     Review 3.1), Brutto-Deckel greift; Bestand: IBS-Legs vom Vortag, TSMOM vom 31.01., VIX-Leg (Kontango hält).
    d0 = '2025-02-26'
    fixture('f1_2025-02-27_mw_kauf_ibs_bb', '2025-02-27', [
        leg(1, 'IBS', 'IWM', n(.25, 'IWM', d0), px('IWM', d0), d0, 3.1),
        leg(2, 'IBS_LAND', 'EWZ', n(.07, 'EWZ', d0), px('EWZ', d0), d0, 0.6),
        leg(3, 'IBS_LAND', 'EWJ', n(.07, 'EWJ', d0), px('EWJ', d0), d0, 0.9),
        leg(4, 'TSMOM', 'GLD', n(.08, 'GLD', '2025-01-31'), px('GLD', '2025-01-31'), '2025-01-31', 3.0),
        leg(5, 'TSMOM', 'TLT', n(.05, 'TLT', '2025-01-31'), px('TLT', '2025-01-31'), '2025-01-31', 1.2, richtung=-1),
        leg(6, 'VIX', 'SVXY', n(.10, 'SVXY', '2025-02-10'), px('SVXY', '2025-02-10'), '2025-02-10', 1.0),
    ], beschreibung='MW-Kauf, IBS+BB im selben Symbol, Brutto-Deckel')
    # F2: letzter Handelstag Feb. 2025 – TSMOM-Umschichtung (Shorts teils nicht leihbar), MW-Legs vom Vortag halten.
    d1 = '2025-02-27'
    fixture('f2_2025-02-28_tsmom', '2025-02-28', [
        leg(1, 'MW', s, n(.25, s, d1), px(s, d1), d1, 2.0) for s in ('SPY', 'QQQ', 'DIA')] + [
        leg(4 + i, 'MW_LAND', s, n(.04, s, d1), px(s, d1), d1, 0.5) for i, s in enumerate(kern.MW_LAND[:6])] + [
        leg(20, 'IBS', 'SPY', n(.25, 'SPY', d1), px('SPY', d1), d1, 6.0),
        leg(21, 'IBS', 'QQQ', n(.25, 'QQQ', d1), px('QQQ', d1), d1, 7.0),
        leg(22, 'TSMOM', 'GLD', n(.08, 'GLD', '2025-01-31'), px('GLD', '2025-01-31'), '2025-01-31', 3.0),
        leg(23, 'TSMOM', 'UNG', n(.03, 'UNG', '2025-01-31'), px('UNG', '2025-01-31'), '2025-01-31', 0.8, richtung=-1),
    ], beschreibung='TSMOM-Tag mit Altbestand, MW halten, IBS-Ausstiege')
    # F3: 3. Handelstag April 2025 – MW-Verkauf, VIX-Backwardation (Ausstieg), Bremse (Höchststand 120 000), BB Tag 15.
    d2 = '2025-03-28'
    fixture('f3_2025-04-03_mw_verkauf_vix_bremse', '2025-04-03', [
        leg(1 + i, 'MW', s, n(.25, s, d2), px(s, d2), d2, 2.0) for i, s in enumerate(kern.INDEX)] + [
        leg(10 + i, 'MW_LAND', s, n(.04, s, d2), px(s, d2), d2, 0.5) for i, s in enumerate(kern.MW_LAND)] + [
        leg(30, 'VIX', 'SVXY', n(.10, 'SVXY', '2025-03-20'), px('SVXY', '2025-03-20'), '2025-03-20', 1.5),
        leg(31, 'BB', 'DIA', n(.25, 'DIA', '2025-03-10'), px('DIA', '2025-03-10'), '2025-03-10', 6.5),
        leg(32, 'IBS_LAND', 'EWT', n(.07, 'EWT', '2025-04-02'), px('EWT', '2025-04-02'), '2025-04-02', 1.0),
        leg(33, 'TSMOM', 'SPY', n(.06, 'SPY', '2025-03-31'), px('SPY', '2025-03-31'), '2025-03-31', 8.0),
    ], equity=100000.0, hwm=120000.0, beschreibung='MW-Verkauf, VIX-Ausstieg, Bremse ×0,5, BB-Altleg')
    # F4: Tag ohne Index-Signal – IBS-Sektor (5 Signale, max 4), IBS-Land mit gehaltenen Legs (max 4 inkl. Bestand).
    d3 = '2025-01-21'
    fixture('f4_2025-01-22_sektor_land', '2025-01-22', [
        leg(1, 'IBS_LAND', 'EWZ', n(.07, 'EWZ', d3), px('EWZ', d3), d3, 0.6),
        leg(2, 'IBS_LAND', 'EWP', n(.07, 'EWP', d3), px('EWP', d3), d3, 0.4),
        leg(3, 'IBS_SEKTOR', 'XLE', n(.11, 'XLE', d3), px('XLE', d3), d3, 1.8),
        leg(4, 'TSMOM', 'SPY', n(.06, 'SPY', '2024-12-31'), px('SPY', '2024-12-31'), '2024-12-31', 7.0),
    ], beschreibung='Sektor-Pfad, Land-Höchstzahl, Folgesignal halten')
    # F5: BB und IBS auf allen Index-ETFs; TSMOM-Short IWM im Bestand → IBS-Long IWM dreht das Vorzeichen (Review 3.2).
    d4 = '2025-10-31'
    fixture('f5_2025-11-20_vorzeichenwechsel', '2025-11-20', [
        leg(1, 'TSMOM', 'IWM', n(.30, 'IWM', d4), px('IWM', d4), d4, 4.0, richtung=-1),
        leg(2, 'TSMOM', 'TLT', n(.05, 'TLT', d4), px('TLT', d4), d4, 1.0),
        leg(3, 'BB', 'IWM', n(.25, 'IWM', '2025-11-17'), px('IWM', '2025-11-17'), '2025-11-17', 4.5),
        leg(4, 'IBS', 'SPY', n(.25, 'SPY', '2025-11-19'), px('SPY', '2025-11-19'), '2025-11-19', 7.0),
    ], beschreibung='Vorzeichenwechsel IWM, BB-Höchstzahl, IBS-Folgesignal')
