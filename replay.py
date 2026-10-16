"""Replay des Systembuchs (SPEC Aufgabe 3/4): dieselbe Entscheidungslogik wie live (`kern.entscheide`, `kern.netto_orders`),
Tageskurse von Yahoo, Ausführung zum Schlusskurs, 3 bp je Seite auf das Netto-Volumen je Symbol.

Aufruf (über den Bot oder direkt):
  python3 systembuch_bot.py --replay 2010-01-01 2026-10-14                 Hauptlauf + Varianten + Plausibilität → replay/
  python3 replay.py 2010-01-01 2026-10-14 --nur-hauptlauf --ausgabe /tmp/x
  K4-Schalter: --ohne-sektor --ohne-mw-land --tsmom-reserve --bremse-dd 0.20 --bremse-faktor 0.75 --max-brutto 1.5
  weitere: --ohne STRAT … · --nur STRAT … · --flip-sperre beide|verkauf|aus · --kosten-bp 3 · --startkapital 100000

Modell (Abweichungen zu K3 stehen in replay/BERICHT.md):
  - Kennzahlen wie live: Historie bereinigt relativ zum Entscheidungstag (wie Alpaca adjustment=all), heute Rohkurs.
    IBS/Stückzahl aus Rohkursen, SMA/BB/TSMOM/ATR aus der bereinigten Reihe.
  - Bewertung über die bereinigte Reihe (`adj`) → Dividenden sind enthalten (Shorts zahlen sie).
  - BB-Stop: live wird er im Lauf nach dem Einstieg (t0+1, 15:45) als GTC gesetzt → im Replay ab t0+2 intraday,
    Fill zu min(Eröffnung, Stop) wie in K3; die letzten 15 Minuten von t0+1 fehlen.
  - Vorzeichenwechsel-Sperre wie live (heute nur bis null); Variante `sperre_aus` zeigt den K3-Vergleich ohne Sperre.
  - SVXY ab Auflage 04.10.2011 geladen, handelbar ab 60 Handelstagen Historie (kern.kennzahlen, wie live) = 29.12.2011. So rechnet
    auch K3 (80 VIX-Trades, 2012 +21 %); Handel ab Auflage ergäbe 83 Trades und 2012 nur +16,8 % (BEOBACHTUNGEN 2).
  - Keine Leihkosten, keine Zinsen auf Bargeld oder Marge (wie K3).
"""
import argparse, csv, datetime as dt, hashlib, inspect, json, math, os, pickle, sys, time, urllib.request
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import kern

HIER = os.path.dirname(os.path.abspath(__file__))
DATEN = os.path.join(HIER, 'daten')
SYMBOLE = kern.ALLE_SYMBOLE + ('^VIX', '^VIX3M')
FENSTER = 270                 # Zeilen Historie je Symbol und Tag (Kennzahlen brauchen höchstens 253)
LADE_START = '2005-01-01'
K3_LEIHBAR_NICHT = ('EWG', 'USO', 'FXE')
STRATEGIEN = kern.VORRANG
NAMEN = dict(IBS='IBS', MW='Monatswechsel', BB='BB-Rückkehr', IBS_SEKTOR='IBS-Sektor', IBS_LAND='IBS-Land', TSMOM='TSMOM',
             MW_LAND='Monatswechsel-Land', VIX='VIX-Contango')


# ---------- Daten ----------
def lade(sym, ende):
    """Yahoo-Tageskurse ('c' = split-bereinigt, 'adj' = split- und dividendenbereinigt), Cache daten/{sym}_1d.csv.
    Vorlage: yahoo_vorbild.py. Ist der Cache älter als `ende`, wird neu geladen."""
    os.makedirs(DATEN, exist_ok=True)
    fn = os.path.join(DATEN, f"{sym.replace('^', '_')}_1d.csv")
    if os.path.exists(fn):
        df = pd.read_csv(fn, index_col=0)
        if df.index[-1] >= ende: return df
    p1 = int(dt.datetime.fromisoformat(LADE_START).replace(tzinfo=dt.timezone.utc).timestamp())
    p2 = int((dt.datetime.fromisoformat(ende) + dt.timedelta(days=2)).replace(tzinfo=dt.timezone.utc).timestamp())
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?period1={p1}&period2={p2}&interval=1d&events=div,split'
    for i in range(4):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=90).read()); break
        except Exception as e:
            if i == 3: raise RuntimeError(f'Yahoo nicht erreichbar für {sym}: {e}')
            time.sleep(5 * (i + 1))
    r = j['chart']['result'][0]; q = r['indicators']['quote'][0]
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or q['close']
    idx = [dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat() for t in r['timestamp']]
    df = pd.DataFrame(dict(o=q['open'], h=q['high'], l=q['low'], c=q['close'], v=q['volume'], adj=adj), index=pd.Index(idx, name='datum'))
    df = df[~df.index.duplicated(keep='last')].dropna(subset=['o', 'h', 'l', 'c'])
    df = df[(df.h >= df.l) & (df.c > 0)]
    jetzt = dt.datetime.now(ZoneInfo('America/New_York'))                              # laufende Tageskerze nie speichern (Review v2):
    fertig = jetzt.date().isoformat() if jetzt.time() >= dt.time(16, 15) else (jetzt.date() - dt.timedelta(days=1)).isoformat()
    df = df[df.index <= min(ende, fertig)]                                               # nur abgeschlossene Tage bis `ende`
    df.to_csv(fn)
    return df


class Daten:
    """Alle Symbole auf die SPY-Handelstage ausgerichtet (NaN, wo ein Symbol an dem Tag keine Kerze hat)."""

    def __init__(self, ende):
        roh = {s: lade(s, ende) for s in SYMBOLE}
        self.tage = [d for d in roh['SPY'].index if d <= ende]
        self.pos = {d: i for i, d in enumerate(self.tage)}
        self.a = {}
        for s, df in roh.items():
            df = df.reindex(self.tage)
            self.a[s] = {k: df[k].to_numpy(dtype=float) for k in ('o', 'h', 'l', 'c', 'adj')}
        # Fingerabdruck für den Kennzahlen-Cache: vollständige Kursdateien + Quelltext der Kennzahl-Berechnung (Review v2)
        h = hashlib.sha1()
        for s in sorted(roh): h.update(s.encode()); h.update(pd.util.hash_pandas_object(roh[s], index=True).values.tobytes())
        for f in (kern.kennzahlen, kennzahlen_alle): h.update(inspect.getsource(f).encode())
        self.fingerabdruck = h.hexdigest()[:12]

    def index_ab(self, d):
        return next(i for i, t in enumerate(self.tage) if t >= d)

    def index_bis(self, d):
        return max(i for i, t in enumerate(self.tage) if t <= d)


def kennzahlen_alle(D, i0, i1):
    """kern.kennzahlen() für jeden Tag – mit Historie wie live: abgeschlossene Tage, bereinigt relativ zum Tag i.
    Ergebnis wird unter daten/ zwischengespeichert (hängt nur von den Kursen ab, nicht von den Schaltern)."""
    fn = os.path.join(DATEN, f'kz_{D.fingerabdruck}_{D.tage[i0]}_{D.tage[i1]}_{FENSTER}.pkl')
    if os.path.exists(fn):
        with open(fn, 'rb') as f: return pickle.load(f)
    t0 = time.time(); out = {}
    gueltig = {s: np.where(np.isfinite(D.a[s]['c']) & np.isfinite(D.a[s]['adj']))[0] for s in kern.ALLE_SYMBOLE}
    for i in range(i0, i1 + 1):
        hist, live = {}, {}
        for s in kern.ALLE_SYMBOLE:
            A = D.a[s]
            if not np.isfinite(A['c'][i]): continue
            g = gueltig[s]; k = np.searchsorted(g, i)                                   # g[k] == i
            idx = g[max(0, k - FENSTER):k]
            if len(idx) == 0: continue
            f = (A['adj'][idx] / A['c'][idx]) / (A['adj'][i] / A['c'][i])               # Bereinigung relativ zu heute
            hist[s] = list(zip([D.tage[j] for j in idx], (A['o'][idx] * f).tolist(), (A['h'][idx] * f).tolist(),
                               (A['l'][idx] * f).tolist(), (A['c'][idx] * f).tolist()))
            live[s] = dict(px=float(A['c'][i]), hi=float(A['h'][i]), lo=float(A['l'][i]))
        out[i] = kern.kennzahlen(hist, live)
    with open(fn, 'wb') as f: pickle.dump(out, f)
    print(f'Kennzahlen {D.tage[i0]}–{D.tage[i1]} berechnet ({time.time() - t0:.0f} s), Cache {os.path.basename(fn)}')
    return out


def leihbarkeit():
    """assets.json (eingefroren aus Alpaca /v2/assets, `shortable`). Fehlt die Datei: Annahme aus K3 (EWG, USO, FXE nicht leihbar)."""
    fn = os.path.join(HIER, 'assets.json')
    if os.path.exists(fn):
        a = json.load(open(fn))
        return {s: bool(a.get('shortable', {}).get(s, False)) for s in kern.TSMOM}, a.get('quelle', 'assets.json')
    return {s: s not in K3_LEIHBAR_NICHT for s in kern.TSMOM}, 'K3-Annahme'


# ---------- Simulation ----------
def simuliere(D, KZ, i0, i1, param=None, sperre='beide', kosten_bp=3.0, startkapital=100000.0, leihbar=None, kal=None, stop_luecke=None,
              vix_versatz=0):
    """Tag für Tag: Bewertung → BB-Stops → kern.entscheide → kern.netto_orders → Ausführung zum Schluss.
    → dict(tage DataFrame, trades DataFrame, info)"""
    kosten = kosten_bp / 1e4
    if stop_luecke is None: stop_luecke = sperre != 'aus'                                   # live: Wash-Trade-Lücke des BB-Stops, K3-Modell: keine
    cash = startkapital; legs = []; nid = 1; hwm = startkapital; letzte_tsmom = None; aufgeschoben = []; gestoppt = False
    zeilen, trades = [], []
    stat = dict(gekreuzt=0, verfallen=0, aufgeschoben=0, verfallen_stueck_wert=0.0, stopps=0)
    vix, vix3 = D.a['^VIX']['c'], D.a['^VIX3M']['c']
    # Yahoo-Tagesschluss von ^VIX/^VIX3M = CBOE-Wert von 16:15 ET, SVXY schließt 16:00, live entscheidet der Bot 15:45 (Review v2).
    # vix_versatz=1: Entscheidung mit dem Vortagesschluss – untere Schranke für den Wert um 15:45 (nur Messung, keine Regel).
    if vix_versatz: vix, vix3 = np.concatenate([[np.nan] * vix_versatz, vix[:-vix_versatz]]), np.concatenate([[np.nan] * vix_versatz, vix3[:-vix_versatz]])

    def schliessen(leg, menge, preis_wert, d, i, grund, kosten_teil):
        """Teil `menge` des Legs zum Wert `preis_wert` (Gesamtwert dieses Teils) schließen."""
        nonlocal cash
        anteil = menge / leg['stueck']
        w_ein = leg['wert_ein'] * anteil; k_ein = leg['kosten'] * anteil
        cash += leg['richtung'] * preis_wert - kosten_teil
        pnl = leg['richtung'] * (preis_wert - w_ein) - k_ein - kosten_teil
        trades.append(dict(id=leg['id'], strategie=leg['strategie'], symbol=leg['symbol'], richtung=leg['richtung'], stueck=menge,
                           einstieg_datum=leg['einstieg_datum'], ausstieg_datum=d, haltetage=i - leg['i_ein'], wert_ein=w_ein,
                           wert_aus=preis_wert, kosten=k_ein + kosten_teil, pnl=pnl, rendite=pnl / w_ein if w_ein else 0.0, grund=grund))
        leg['wert'] -= leg['wert'] * anteil; leg['wert_ein'] -= w_ein; leg['kosten'] -= k_ein; leg['stueck'] -= menge
        return pnl

    for i in range(i0, i1 + 1):
        d = D.tage[i]; kz = KZ[i]
        pnl_s = dict.fromkeys(STRATEGIEN, 0.0)
        eq_vor = cash + sum(l['richtung'] * l['wert'] for l in legs)
        # 1) Bewertung mit der bereinigten Reihe (enthält Dividenden); fehlt heute eine Kerze, bleibt der Wert stehen
        for l in legs:
            a = D.a[l['symbol']]['adj'][i]
            if np.isfinite(a):
                neu = l['wert'] * a / l['adj']; pnl_s[l['strategie']] += l['richtung'] * (neu - l['wert']); l['wert'] = neu; l['adj'] = a
        # 2) BB-Stops (GTC ab t0+2 intraday; Fill min(Eröffnung, Stop))
        for l in [l for l in legs if l['strategie'] == 'BB' and i >= l['i_ein'] + 2 and l.get('stop_pause') != i]:
            A = D.a[l['symbol']]
            if np.isfinite(A['l'][i]) and A['l'][i] <= l['stop']:
                fill = min(A['o'][i], l['stop'])
                wert = l['wert'] * fill / A['c'][i]                                       # Wert (inkl. aufgelaufener Dividende) zum Stopkurs
                pnl_s['BB'] += l['richtung'] * (wert - l['wert'])
                k = kosten * l['stueck'] * fill; pnl_s['BB'] -= k
                l['wert'] = wert
                schliessen(l, l['stueck'], wert, d, i, 'BB Stop', k); stat['stopps'] += 1
        legs = [l for l in legs if l['stueck'] > 0]
        eq = cash + sum(l['richtung'] * l['wert'] for l in legs)
        hwm = max(hwm, eq)
        # 3) Entscheidung – derselbe Code wie live
        kurse = {}
        if np.isfinite(vix[i]) and np.isfinite(vix3[i]): kurse = {'^VIX': {'px': float(vix[i])}, '^VIX3M': {'px': float(vix3[i])}}
        if gestoppt: aus, ein, info = [], [], dict(datum_neu={}, tsmom_tag=False, faktor=1.0)
        else:
            z = dict(heute=d, equity=eq, hwm=hwm, legs=legs, leihbar=leihbar or {}, letzte_tsmom=letzte_tsmom, aufgeschoben=aufgeschoben)
            aus, ein, info = kern.entscheide(z, kurse, None, kal, param, kz=kz)
            if kern.notaus(eq, startkapital):
                aus = [(l, 'NOT-AUS') for l in legs]; ein = []; gestoppt = True
        no = kern.netto_orders(legs, aus, ein, sperre)
        stat['stop_luecken'] = stat.get('stop_luecken', 0) + sum(1 for l in legs if l.get('stop_pause') == i)
        stat['gekreuzt'] += len(no['gekreuzt']); stat['verfallen'] += len(no['verfallen']); stat['aufgeschoben'] += len(no['aufgeschoben'])
        stat['verfallen_stueck_wert'] += sum(x['stueck'] * kz[x['symbol']]['px'] for x in no['verfallen'] if x['symbol'] in kz)
        # 4) Ausführung zum Schluss; Kosten auf das Netto-Volumen je Symbol, anteilig auf die beteiligten Legs
        brutto_s = {}
        for l, _, m in no['ausstiege']: brutto_s[l['symbol']] = brutto_s.get(l['symbol'], 0) + m
        for l in no['einstiege']: brutto_s[l['symbol']] = brutto_s.get(l['symbol'], 0) + l['stueck']
        def kostenanteil(sym, menge):
            px = D.a[sym]['c'][i]; netto = abs(no['orders'].get(sym, 0))
            return kosten * netto * px * menge / brutto_s[sym] if brutto_s.get(sym) else 0.0
        for l, grund, m in no['ausstiege']:
            if not np.isfinite(D.a[l['symbol']]['c'][i]): continue                     # ohne Kurs kein Ausstieg (wie live)
            k = kostenanteil(l['symbol'], m); pnl_s[l['strategie']] -= k
            schliessen(l, m, l['wert'] * m / l['stueck'], d, i, grund, k)
        for l in legs:
            if l.get('id') in info['datum_neu']: l['datum'] = info['datum_neu'][l['id']]
        legs = [l for l in legs if l['stueck'] > 0]
        for l in no['einstiege']:
            A = D.a[l['symbol']]; px = float(A['c'][i]); k = kostenanteil(l['symbol'], l['stueck']); pnl_s[l['strategie']] -= k
            wert = l['stueck'] * px
            leg = dict(l, id=nid, einstieg=px, einstieg_datum=d, i_ein=i, wert=wert, wert_ein=wert, adj=float(A['adj'][i]), kosten=k)
            if l['strategie'] == 'BB': leg['stop'] = round(px - kern.BB_STOP_ATR * l['atr20'], 2)
            nid += 1; cash -= l['richtung'] * wert + k; legs.append(leg)
        aufgeschoben = no['aufgeschoben'] + info.get('aufgeschoben_behalten', [])
        if stop_luecke:                                                                    # live: MOC-Kauf im Symbol → Sell-Stop erst im nächsten Lauf
            for l in legs:                                                                 # (Alpaca Wash-Trade-Schutz) → am Folgetag kein Stop
                if l['strategie'] == 'BB' and no['orders'].get(l['symbol'], 0) > 0 and l['i_ein'] < i: l['stop_pause'] = i + 1
        if info.get('tsmom_tag'): letzte_tsmom = d
        eq_end = cash + sum(l['richtung'] * l['wert'] for l in legs)
        brutto = sum(l['stueck'] * D.a[l['symbol']]['c'][i] for l in legs if np.isfinite(D.a[l['symbol']]['c'][i]))
        zeile = dict(datum=d, equity=eq_end, bargeld=cash, brutto=brutto, brutto_quote=brutto / eq_end, legs=len(legs),
                     faktor=info.get('faktor', 1.0))
        for s in STRATEGIEN:
            zeile[f'pnl_{s}'] = pnl_s[s]; zeile[f'brutto_{s}'] = sum(l['stueck'] * D.a[l['symbol']]['c'][i] for l in legs if l['strategie'] == s and np.isfinite(D.a[l['symbol']]['c'][i]))
        zeilen.append(zeile)
        assert abs(eq_end - eq_vor - sum(pnl_s.values())) < 1e-6 * max(1.0, abs(eq_end)), (d, eq_end, eq_vor, sum(pnl_s.values()))
    tage = pd.DataFrame(zeilen).set_index('datum')
    tr = pd.DataFrame(trades)
    return dict(tage=tage, trades=tr, stat=stat, offen=legs)


# ---------- Auswertung ----------
def drawdown_info(eq):
    dd = 1 - eq / eq.cummax(); tief = dd.idxmax(); spitze = eq.loc[:tief].idxmax()
    pos = list(eq.index); i_s, i_t = pos.index(spitze), pos.index(tief)
    nach = eq.iloc[i_t:]; erholt = nach[nach >= eq.loc[spitze]]
    i_e = pos.index(erholt.index[0]) if len(erholt) else None
    return dict(max_dd=float(dd.max()), spitze=spitze, tief=tief, erholt=erholt.index[0] if len(erholt) else None,
                tage_bis_tief=i_t - i_s, tage_bis_erholt=(i_e - i_s) if i_e is not None else None, tage_unter_wasser=(i_e if i_e is not None else len(pos) - 1) - i_s)


def kennzahlen(eq, spy=None):
    r = eq.pct_change().dropna(); n = len(r)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (252 / n) - 1
    vol = r.std() * math.sqrt(252); sharpe = r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else 0.0
    unten = math.sqrt((r.clip(upper=0) ** 2).mean()) * math.sqrt(252)
    out = dict(cagr=cagr, vol=vol, sharpe=sharpe, sortino=r.mean() * 252 / unten if unten > 0 else 0.0, endwert=float(eq.iloc[-1]),
               start=eq.index[0], ende=eq.index[-1], **drawdown_info(eq))
    if spy is not None:
        rs = spy.pct_change().reindex(r.index).fillna(0)
        beta = float(np.cov(r, rs)[0, 1] / np.var(rs, ddof=1)); out['beta'] = beta
        out['alpha'] = float((r.mean() - beta * rs.mean()) * 252)
        res = r - beta * rs; out['alpha_t'] = float(res.mean() / (res.std() / math.sqrt(n)))
    return out


def jahresrenditen(eq0):
    """eq0 beginnt am Vortag des ersten Replay-Tags (Startkapital) → Jahresrenditen ab dem Startjahr."""
    j = eq0.groupby(eq0.index.str[:4]).last()
    return (j / j.shift(1) - 1).iloc[1:]


def strategie_tabelle(erg, eq):
    t = erg['tage']; tr = erg['trades']; vortag = t['equity'].shift(1).fillna(eq.iloc[0])
    zeilen = []
    for s in STRATEGIEN:
        beitrag = t[f'pnl_{s}'] / vortag
        x = tr[tr.strategie == s] if len(tr) else tr
        n = len(x); mu = x.rendite.mean() if n else float('nan'); sd = x.rendite.std() if n > 1 else float('nan')
        zeilen.append(dict(strategie=s, name=NAMEN[s], beitrag_pa=beitrag.mean() * 252,
                           sharpe=beitrag.mean() / beitrag.std() * math.sqrt(252) if beitrag.std() > 0 else 0.0,
                           summe_dollar=t[f'pnl_{s}'].sum(), trades=n, trades_pa=n / (len(t) / 252), treffer=(x.pnl > 0).mean() if n else float('nan'),
                           bp_je_trade=mu * 1e4 if n else float('nan'), t_wert=mu / (sd / math.sqrt(n)) if n > 1 and sd > 0 else float('nan'),
                           haltetage=x.haltetage.mean() if n else float('nan'), brutto_avg=(t[f'brutto_{s}'] / t['equity']).mean()))
    return pd.DataFrame(zeilen).set_index('strategie')


def korrelation(erg, eq):
    t = erg['tage']; vortag = t['equity'].shift(1).fillna(eq.iloc[0])
    b = pd.DataFrame({s: t[f'pnl_{s}'] / vortag for s in STRATEGIEN})
    b = b.loc[:, b.abs().sum() > 0]
    return b.corr()


def auswerten(erg, D, spy):
    t = erg['tage']; eq = t['equity']
    # Start mit dem Startkapital am Vortag des ersten Replay-Tags, damit die erste Tagesrendite zählt
    eq0 = pd.concat([pd.Series([erg['startkapital']], index=[erg['vortag']]), eq])
    k = kennzahlen(eq0, spy.reindex(eq0.index))
    tr = erg['trades']
    k.update(kosten=float(tr.kosten.sum()) if len(tr) else 0.0, trades=len(tr), trades_pa=len(tr) / (len(t) / 252),
             legs_avg=float(t['legs'].mean()), investiert=float((t['legs'] > 0).mean()), brutto_avg=float(t['brutto_quote'].mean()),
             brutto_max=float(t['brutto_quote'].max()), bremse_tage=float((t['faktor'] < 1).mean()), **erg['stat'])
    return k, eq0


# ---------- Berichte ----------
NAVY, GOLD, CREME, GRAU = '#1F3864', '#C9A84C', '#F5F0E8', '#7A7A7A'


def bild_brutto(tage, pfad):
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    x = pd.to_datetime(tage.index)
    fig, a = plt.subplots(figsize=(11, 3.6), facecolor=CREME); a.set_facecolor(CREME)
    a.plot(x, tage['brutto_quote'].values, color=GRAU, lw=.4, alpha=.6, label='täglich')
    a.plot(x, tage['brutto_quote'].rolling(21).mean().values, color=NAVY, lw=1.2, label='Ø 21 Tage')
    a.axhline(kern.MAX_BRUTTO, color=GOLD, lw=1, ls='--', label='Deckel 1,9×')
    a.set_ylabel('Brutto / Equity'); a.legend(loc='upper left', fontsize=8, frameon=True, facecolor=CREME, edgecolor=GRAU, framealpha=.95); a.grid(alpha=.25)
    a.set_title('Brutto-Exposure im Zeitverlauf', color=NAVY, fontsize=11)
    fig.tight_layout(); fig.savefig(pfad, dpi=110, facecolor=CREME); plt.close(fig)


def p(x, n=1):
    return '–' if x is None or (isinstance(x, float) and math.isnan(x)) else f'{x * 100:+.{n}f} %'.replace('.', ',')


def tsd(x):
    """Tausenderpunkt: 100000 → 100.000"""
    return f'{x:,.0f}'.replace(',', '.')


def pz1(x):
    return '–' if x is None or (isinstance(x, float) and math.isnan(x)) else f'{x * 100:.1f} %'.replace('.', ',')


def pz(x, n=0):
    return '–' if x is None or (isinstance(x, float) and math.isnan(x)) else f'{x * 100:.{n}f} %'


def zahl(x, n=2):
    return '–' if x is None or (isinstance(x, float) and math.isnan(x)) else f'{x:.{n}f}'.replace('.', ',')


# Referenz K3 (SPEC-v2 Punkt 4); fett = Abweichung > 15 % → Fehler suchen
K3 = dict(cagr=0.120, vol=0.170, sharpe=0.75, sortino=1.07, max_dd=0.241, endwert=669000, kosten=208600, trades_pa=745, legs_avg=14.5,
          beta=0.74, tresor_cagr=0.171, tresor_sharpe=1.06, tresor_dd=0.181,
          beitrag=dict(IBS=0.038, MW=0.016, BB=0.016, IBS_SEKTOR=0.003, IBS_LAND=0.017, TSMOM=0.005, MW_LAND=0.006, VIX=0.028),
          trades=dict(IBS=2245, BB=208, IBS_LAND=4507, VIX=80), treffer=dict(BB=0.68, VIX=0.34), bp=dict(IBS=16), t=dict(IBS=5.0, IBS_LAND=5.2),
          varianten=dict(ohne_tsmom=0.114, ohne_vix=0.100, ohne_mw_land=0.101, nur_ibs_familie=0.079), allein=dict(ibs=0.050, vix=0.031),
          allein_sharpe=dict(ibs=0.63, tsmom=0.54), nur_ibs_familie_sharpe=0.73, nur_ibs_familie_dd=0.183,
          korr=dict(IBS_IBS_LAND=0.63, MW_MW_LAND=0.72),
          jahre={'2010': .158, '2011': .169, '2012': .210, '2013': .222, '2014': .002, '2015': -.062, '2016': .169, '2017': .380, '2018': -.156,
                 '2019': .007, '2020': .385, '2021': .214, '2022': -.044, '2023': .117, '2024': -.032, '2025': .202, '2026': .242})
FETT = ('cagr', 'sharpe', 'max_dd', 'beitrag_IBS', 'beitrag_IBS_LAND', 'beitrag_VIX')


def abweichung(ist, soll):
    return (ist - soll) / abs(soll) if soll else float('nan')


VARIANTEN = {
    'ohne_tsmom': dict(ohne=('TSMOM',)), 'ohne_vix': dict(ohne=('VIX',)), 'ohne_mw_land': dict(ohne=('MW_LAND',)),
    'nur_ibs_familie': dict(nur=kern.IBS_FAMILIE), 'ibs_allein': dict(nur=('IBS',)), 'tsmom_allein': dict(nur=('TSMOM',)),
    'vix_allein': dict(nur=('VIX',)), 'vix_vortag': dict(vix_versatz=1),
}


def param_aus(a, ohne=(), nur=None):
    strat = set(nur) if nur else set(kern.VORRANG)
    strat -= set(ohne) | set(a.ohne or ())
    if a.nur: strat &= set(a.nur)
    if a.ohne_sektor: strat.discard('IBS_SEKTOR')
    if a.ohne_mw_land: strat.discard('MW_LAND')
    return dict(strategien=frozenset(strat), tsmom_reserve=a.tsmom_reserve, max_brutto=a.max_brutto, bremse_dd=a.bremse_dd, bremse_faktor=a.bremse_faktor)


def argumente(argv):
    ap = argparse.ArgumentParser(prog='replay', description='Replay des Systembuchs')
    ap.add_argument('start'); ap.add_argument('ende')
    ap.add_argument('--ausgabe', default=os.path.join(HIER, 'replay'))
    ap.add_argument('--nur-hauptlauf', action='store_true', help='ohne Varianten, ohne K3-Modell')
    ap.add_argument('--ohne-sektor', action='store_true'); ap.add_argument('--ohne-mw-land', action='store_true')
    ap.add_argument('--tsmom-reserve', action='store_true', help='K4: am TSMOM-Tag Brutto für TSMOM vorab reservieren')
    ap.add_argument('--bremse-dd', type=float, default=kern.BREMSE_DD); ap.add_argument('--bremse-faktor', type=float, default=kern.BREMSE_FAKTOR)
    ap.add_argument('--max-brutto', type=float, default=kern.MAX_BRUTTO)
    ap.add_argument('--ohne', nargs='+', choices=kern.VORRANG); ap.add_argument('--nur', nargs='+', choices=kern.VORRANG)
    ap.add_argument('--flip-sperre', default='beide', choices=('beide', 'verkauf', 'aus'),
                    help='Vorzeichenwechsel-Sperre des Hauptlaufs (live: beide)')
    ap.add_argument('--kosten-bp', type=float, default=3.0); ap.add_argument('--startkapital', type=float, default=100000.0)
    return ap.parse_args(argv)


def lauf(D, KZ, i0, i1, a, leihbar, kal, spy, sperre, **v):
    param = param_aus(a, v.get('ohne', ()), v.get('nur'))
    t0 = time.time()
    erg = simuliere(D, KZ, i0, i1, param, sperre, a.kosten_bp, a.startkapital, leihbar, kal, vix_versatz=v.get('vix_versatz', 0))
    erg.update(startkapital=a.startkapital, vortag=D.tage[i0 - 1], dauer=time.time() - t0)
    k, eq0 = auswerten(erg, D, spy)
    return dict(erg=erg, k=k, eq0=eq0)


def main(argv=None):
    a = argumente(argv if argv is not None else sys.argv[1:])
    os.makedirs(a.ausgabe, exist_ok=True)
    D = Daten(a.ende)
    i0, i1 = D.index_ab(a.start), D.index_bis(a.ende)
    leihbar, leih_quelle = leihbarkeit()
    letzter = D.tage[-1]; zukunft = (dt.date.fromisoformat(letzter) + dt.timedelta(days=60)).isoformat()
    kal = kern.Kalender(D.tage + kern.regel_handelstage((dt.date.fromisoformat(letzter) + dt.timedelta(days=1)).isoformat(), zukunft)[0],
                        quelle='Yahoo-Handelstage (SPY), danach NYSE-Regelwerk')
    KZ = kennzahlen_alle(D, i0, i1)
    spy = pd.Series(D.a['SPY']['adj'], index=D.tage)
    # Modell „live“: so, wie der Bot handeln kann (Vorzeichenwechsel-Sperre). Modell „k3“: ohne Sperre, methodisch gleich K3.
    modelle = {'live': a.flip_sperre} if a.nur_hauptlauf or a.flip_sperre == 'aus' else {'live': a.flip_sperre, 'k3': 'aus'}
    R = {}
    for m, sperre in modelle.items():
        R[m] = {'haupt': lauf(D, KZ, i0, i1, a, leihbar, kal, spy, sperre)}
        k = R[m]['haupt']['k']
        print(f"[{m}] Hauptlauf {D.tage[i0]}–{D.tage[i1]}: {k['cagr']:+.2%} p.a., Sharpe {k['sharpe']:.2f}, maxDD {k['max_dd']:.1%}, Endwert {k['endwert']:,.0f} $")
        if a.nur_hauptlauf: continue
        for name, v in VARIANTEN.items():
            R[m][name] = lauf(D, KZ, i0, i1, a, leihbar, kal, spy, sperre, **v); kv = R[m][name]['k']
            print(f"[{m}] {name}: {kv['cagr']:+.2%} p.a., Sharpe {kv['sharpe']:.2f}, maxDD {kv['max_dd']:.1%}")
        if m == 'live' and sperre == 'beide':
            R[m]['nur_verkauf_gesperrt'] = lauf(D, KZ, i0, i1, a, leihbar, kal, spy, 'verkauf')
    schreibe_berichte(a, R, spy, leih_quelle, kal)
    return {m: R[m]['haupt']['k'] for m in R}


def tresor_kz(eq0, spy):
    """Tresor ab 02.10.2023 (README). None, wenn der Zeitraum den Tresor nicht enthält (z. B. Lernzeit-Lauf bis 2019)."""
    vor = eq0[eq0.index < '2023-10-02'].index
    vor = vor[-1] if len(vor) else eq0.index[0]                                          # Zeitraum beginnt nach dem Tresor-Start
    teil = eq0[eq0.index >= vor]
    if len(teil) < 3 or teil.index[-1] < '2023-10-02': return None
    return kennzahlen(teil, spy.reindex(teil.index))


def schreibe_berichte(a, R, spy, leih_quelle, kal):
    aus = a.ausgabe; H = R['live']['haupt']; t = H['erg']['tage']; tr = H['erg']['trades']; eq0 = H['eq0']
    t.round(4).to_csv(os.path.join(aus, 'equity.csv'))
    if len(tr): tr.round(6).to_csv(os.path.join(aus, 'trades.csv'), index=False)
    jr = pd.DataFrame({m: jahresrenditen(R[m]['haupt']['eq0']) for m in R}); jr['K3'] = [K3['jahre'].get(j) for j in jr.index]
    jr.round(4).to_csv(os.path.join(aus, 'jahresrenditen.csv'))
    st = {m: strategie_tabelle(R[m]['haupt']['erg'], R[m]['haupt']['eq0']) for m in R}
    ko = {m: korrelation(R[m]['haupt']['erg'], R[m]['haupt']['eq0']) for m in R}
    for m in R:
        st[m].round(5).to_csv(os.path.join(aus, 'strategien.csv' if m == 'live' else f'strategien_{m}modell.csv'))
        ko[m].round(3).to_csv(os.path.join(aus, 'korrelation.csv' if m == 'live' else f'korrelation_{m}modell.csv'))
    tresor = {m: tresor_kz(R[m]['haupt']['eq0'], spy) for m in R}
    zeilen = []
    for m in R:
        for n, x in R[m].items():
            v = x['k']; zeilen.append(dict(modell=m, variante=n, cagr=v['cagr'], vol=v['vol'], sharpe=v['sharpe'], sortino=v['sortino'],
                                           max_dd=v['max_dd'], endwert=v['endwert'], trades_pa=v['trades_pa'], kosten=v['kosten']))
    pd.DataFrame(zeilen).round(4).to_csv(os.path.join(aus, 'varianten.csv'), index=False)
    bild_equity({m: R[m]['haupt']['eq0'] for m in R}, os.path.join(aus, 'equity.png'),
                f'Systembuch-Replay {eq0.index[1]} – {eq0.index[-1]} (100.000 $, 3 bp je Seite)')
    bild_brutto(t, os.path.join(aus, 'brutto.png'))
    json.dump(dict(stand=dt.date.today().isoformat(), zeitraum=[eq0.index[1], eq0.index[-1]], leihbarkeit=leih_quelle, kalender=kal.quelle,
                   modelle={m: dict(haupt=_json(R[m]['haupt']['k']), tresor=_json(tresor[m]) if tresor[m] else None,
                                    varianten={n: _json(x['k']) for n, x in R[m].items() if n != 'haupt'},
                                    beitrag={s: float(st[m].loc[s, 'beitrag_pa']) for s in STRATEGIEN}) for m in R}),
              open(os.path.join(aus, 'kennzahlen.json'), 'w'), indent=1, ensure_ascii=False, default=str)
    bericht(a, R, tresor, st, ko, jr, leih_quelle)


def bild_equity(kurven, pfad, titel):
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw=dict(height_ratios=[3, 1]), facecolor=CREME)
    for a in (a1, a2): a.set_facecolor(CREME); [sp.set_color(GRAU) for sp in a.spines.values()]
    namen = dict(live='live ausführbar (mit Vorzeichenwechsel-Sperre)', k3='K3-Modell (ohne Sperre)')
    for (m, eq0), farbe in zip(kurven.items(), (NAVY, GOLD)):
        x = pd.to_datetime(eq0.index)
        a1.plot(x, eq0.values, color=farbe, lw=1.3 if m == 'live' else 1.0, label=namen.get(m, m))
        dd = 1 - eq0 / eq0.cummax()
        if m == 'live': a2.fill_between(x, -dd.values * 100, 0, color=NAVY, alpha=.55, label=namen[m])
        else: a2.plot(x, -dd.values * 100, color=GOLD, lw=.9, label=namen[m])
    a1.set_yscale('log'); a1.set_ylabel('Equity ($, log)'); a1.set_title(titel, color=NAVY, fontsize=12); a1.grid(alpha=.25)
    a1.legend(loc='upper left', fontsize=8, frameon=False)
    a2.set_ylabel('Drawdown %'); a2.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(pfad, dpi=110, facecolor=CREME); plt.close(fig)


def _json(d):
    return {k: (float(v) if isinstance(v, (np.floating, float)) else int(v) if isinstance(v, (np.integer,)) else v) for k, v in d.items()}


def _urteil(ab, fett):
    if ab != ab: return '–'
    if fett: return '**Fehler suchen**' if abs(ab) > 0.15 else 'ok'
    return 'ok' if abs(ab) <= 0.30 else '> 30 %'


def bericht(a, R, tresor, st, ko, jr, leih_quelle):
    """replay/BERICHT.md: Plausibilität gegen K3 (K3-Modell und live), Jahre, Beitrag je Strategie, Korrelation, Varianten, Tresor."""
    L = R['live']; K = R.get('k3'); kl = L['haupt']['k']; kk = K['haupt']['k'] if K else None
    z = [f'# Replay Systembuch {L["haupt"]["eq0"].index[1]} – {kl["ende"]}', '',
         f'*Erzeugt {dt.date.today():%d.%m.%Y} mit `python3 systembuch_bot.py --replay {a.start} {a.ende}`. Yahoo-Tageskurse, Start {tsd(a.startkapital)} $, '
         f'Kosten {a.kosten_bp:g} bp je Seite auf das Netto-Volumen je Symbol, Leihbarkeit: {leih_quelle}. Dieselbe Entscheidungsfunktion wie live '
         f'(`kern.entscheide`, `kern.netto_orders`).*', '',
         'Zwei Modelle, sonst identisch: **live** = so, wie der Bot bei Alpaca handeln kann (Vorzeichenwechsel-Sperre: ein Symbol dreht an einem Tag nie '
         'durch null, Review 3.2). **K3-Modell** = ohne Sperre, methodisch gleich dem unabhängigen Replay K3 – an ihm wird die Plausibilität geprüft.', '',
         '![Equity](equity.png)', '', '## Plausibilität gegen K3 (SPEC Punkt 4)', '',
         '| Kennzahl | K3 | K3-Modell | Abw. | Prüfung | live | Abw. |', '|---|---|---|---|---|---|---|']
    def zeile(name, soll, ist_k, ist_l, fmt, schl):
        fett = schl in FETT
        ab_k = abweichung(ist_k, soll) if ist_k is not None else float('nan'); ab_l = abweichung(ist_l, soll)
        z.append(f"| {'**' + name + '**' if fett else name} | {fmt(soll)} | {fmt(ist_k) if ist_k is not None else '–'} | "
                 f"{'–' if ab_k != ab_k else f'{ab_k * 100:+.0f} %'} | {_urteil(ab_k, fett)} | {fmt(ist_l)} | {'–' if ab_l != ab_l else f'{ab_l * 100:+.0f} %'} |")
    def kor(m, x, y):                                                                    # Strategie ohne Ergebnis (K4-Schalter, --nur) hat keine Spalte
        k = ko.get(m); return float(k.loc[x, y]) if k is not None and x in k.columns and y in k.columns else float('nan')
    g = lambda d, x: d[x] if d else None
    zeile('Rendite p.a.', K3['cagr'], g(kk, 'cagr'), kl['cagr'], p, 'cagr')
    zeile('Schwankung', K3['vol'], g(kk, 'vol'), kl['vol'], p, 'vol')
    zeile('Sharpe', K3['sharpe'], g(kk, 'sharpe'), kl['sharpe'], zahl, 'sharpe')
    zeile('Sortino', K3['sortino'], g(kk, 'sortino'), kl['sortino'], zahl, 'sortino')
    zeile('Maximalverlust', K3['max_dd'], g(kk, 'max_dd'), kl['max_dd'], pz1, 'max_dd')
    zeile('Endwert $', K3['endwert'], g(kk, 'endwert'), kl['endwert'], tsd, 'endwert')
    zeile('Kosten gesamt $', K3['kosten'], g(kk, 'kosten'), kl['kosten'], tsd, 'kosten')
    zeile('Trades p.a.', K3['trades_pa'], g(kk, 'trades_pa'), kl['trades_pa'], lambda x: f'{x:.0f}', 'trades_pa')
    zeile('Ø offene Legs', K3['legs_avg'], g(kk, 'legs_avg'), kl['legs_avg'], lambda x: zahl(x, 1), 'legs_avg')
    zeile('Beta zu SPY', K3['beta'], g(kk, 'beta'), kl['beta'], zahl, 'beta')
    for s in STRATEGIEN:
        zeile(f'Beitrag {NAMEN[s]} p.a.', K3['beitrag'][s], st['k3'].loc[s, 'beitrag_pa'] if K else None, st['live'].loc[s, 'beitrag_pa'], p, f'beitrag_{s}')
    if tresor['live']:
        zeile('Tresor ab 02.10.2023 p.a.', K3['tresor_cagr'], g(tresor.get('k3'), 'cagr'), tresor['live']['cagr'], p, 'tresor_cagr')
        zeile('Tresor Sharpe', K3['tresor_sharpe'], g(tresor.get('k3'), 'sharpe'), tresor['live']['sharpe'], zahl, 'tresor_sharpe')
        zeile('Tresor Maximalverlust', K3['tresor_dd'], g(tresor.get('k3'), 'max_dd'), tresor['live']['max_dd'], pz1, 'tresor_dd')
    for n, soll in K3['varianten'].items():
        if n in L: zeile(f'Variante {n}', soll, K[n]['k']['cagr'] if K else None, L[n]['k']['cagr'], p, n)
    for n, soll in K3['allein'].items():
        if f'{n}_allein' in L: zeile(f'{n.upper()} allein p.a.', soll, K[f'{n}_allein']['k']['cagr'] if K else None, L[f'{n}_allein']['k']['cagr'], p, n)
    for n, soll in K3['allein_sharpe'].items():
        if f'{n}_allein' in L: zeile(f'{n.upper()} allein Sharpe', soll, K[f'{n}_allein']['k']['sharpe'] if K else None, L[f'{n}_allein']['k']['sharpe'], zahl, n)
    if 'nur_ibs_familie' in L:
        zeile('nur IBS-Familie Sharpe', K3['nur_ibs_familie_sharpe'], K['nur_ibs_familie']['k']['sharpe'] if K else None, L['nur_ibs_familie']['k']['sharpe'], zahl, 'x')
        zeile('nur IBS-Familie Maximalverlust', K3['nur_ibs_familie_dd'], K['nur_ibs_familie']['k']['max_dd'] if K else None, L['nur_ibs_familie']['k']['max_dd'], pz1, 'x')
    if K:
        zeile('Korrelation IBS/IBS-Land', K3['korr']['IBS_IBS_LAND'], kor('k3', 'IBS', 'IBS_LAND'), kor('live', 'IBS', 'IBS_LAND'), zahl, 'x')
        zeile('Korrelation MW/MW-Land', K3['korr']['MW_MW_LAND'], kor('k3', 'MW', 'MW_LAND'), kor('live', 'MW', 'MW_LAND'), zahl, 'x')
    z += ['', 'Fett = Kennzahl, bei der laut SPEC eine Abweichung über 15 % Fehlersuche heißt (Linus\' Regel 7: über 30 %). Geprüft wird das K3-Modell; '
          'die Spalte „live“ weicht nur wegen der Vorzeichenwechsel-Sperre ab (Abschnitt „Preis der Sperre“).', '']
    for m, k in (('live', kl), ('K3-Modell', kk)):
        if k is None: continue
        z.append(f"- **{m}:** Maximalverlust {pz1(k['max_dd'])} vom Höchststand {k['spitze']} bis {k['tief']} ({k['tage_bis_tief']} Handelstage), neues Hoch "
                 f"{k['erholt'] or 'noch nicht'} ({k['tage_bis_erholt'] or '–'} Handelstage ab Höchststand; K3: Tief 28.02.2020, 702). Alpha zu SPY {p(k['alpha'])} p.a. "
                 f"(t {zahl(k['alpha_t'])}), investiert an {k['investiert'] * 100:.0f} % der Tage, Ø Brutto {zahl(k['brutto_avg'])}× (max {zahl(k['brutto_max'])}×), "
                 f"Bremse an {k['bremse_tage'] * 100:.0f} % der Tage, {k['stopps']} BB-Stopps" + (f", {k.get('stop_luecken', 0)} BB-Leg-Tage ohne Stop (Wash-Trade-Lücke)." if m == 'live' else '.'))
    z += ['', '## Jahresrenditen', '', '| Jahr | live | K3-Modell | K3 |', '|---|---|---|---|']
    for j, r in jr.iterrows(): z.append(f"| {j} | {p(r['live'])} | {p(r['k3']) if 'k3' in r else '–'} | {p(r['K3'])} |")
    z += ['', '## Beitrag je Strategie (live)', '',
          '| Strategie | Beitrag p.a. | (K3-Modell) | Sharpe | Summe $ | Trades | je Jahr | Treffer | Ø bp je Trade | t (Trade) | Ø Haltetage | Ø Brutto |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for s, r in st['live'].iterrows():
        z.append(f"| {NAMEN[s]} | {p(r.beitrag_pa)} | {p(st['k3'].loc[s, 'beitrag_pa']) if K else '–'} | {zahl(r.sharpe)} | {tsd(r.summe_dollar)} | {r.trades:.0f} | "
                 f"{r.trades_pa:.0f} | {pz(r.treffer)} | {zahl(r.bp_je_trade, 1)} | {zahl(r.t_wert, 1)} | {zahl(r.haltetage, 1)} | {zahl(r.brutto_avg)} |")
    z += ['', 'Beitrag p.a. = Ø tägliches Ergebnis der Strategie / Vortages-Equity × 252. Ø bp je Trade nach Kosten. t = Mittelwert / Standardfehler der Trade-Renditen. '
          'K3-Referenz: IBS 2 245 Trades, +16 bp, t 5,0 · IBS-Land 4 507 Trades, t 5,2 · BB 208 Trades, Treffer 68 % · VIX 80 Trades, Treffer 34 %.', '',
          '## Korrelation der Strategie-Tagesrenditen (live)', '', '| | ' + ' | '.join(NAMEN[c] for c in ko['live'].columns) + ' |', '|---' * (len(ko['live'].columns) + 1) + '|']
    for s, r in ko['live'].iterrows(): z.append(f'| {NAMEN[s]} | ' + ' | '.join(zahl(v) for v in r.values) + ' |')
    z += ['', '## Varianten (SPEC Aufgabe 3: was die Experimente kosten oder bringen)', '',
          '| Variante | live p.a. | Sharpe | Maximalverlust | K3-Modell p.a. | Sharpe | Maximalverlust | K3 p.a. |', '|---|---|---|---|---|---|---|---|']
    for n in L:
        if n == 'nur_verkauf_gesperrt': continue
        kv = L[n]['k']; kk_ = K[n]['k'] if K and n in K else None
        ref = K3['varianten'].get(n) if n != 'haupt' else K3['cagr']
        z.append(f"| {'Gesamtbuch' if n == 'haupt' else n} | {p(kv['cagr'])} | {zahl(kv['sharpe'])} | {pz1(kv['max_dd'])} | "
                 f"{p(kk_['cagr']) if kk_ else '–'} | {zahl(kk_['sharpe']) if kk_ else '–'} | {pz1(kk_['max_dd']) if kk_ else '–'} | {p(ref) if ref else '–'} |")
    z += ['', '## Tresor ab 02.10.2023', '']
    if not tresor['live']: z.append('- Der Zeitraum enthält den Tresor nicht.')
    for m in [m for m in tresor if tresor[m]]:
        tz = tresor[m]; z.append(f"- {'live' if m == 'live' else 'K3-Modell'}: {p(tz['cagr'])} p.a., Sharpe {zahl(tz['sharpe'])}, Maximalverlust {pz1(tz['max_dd'])} (Tief {tz['tief']}).")
    z.append('- K3: +17,1 % p.a., Sharpe 1,06, Maximalverlust 18,1 % (08.04.2025).')
    if K:
        kv = L.get('nur_verkauf_gesperrt', {}).get('k')
        st_ = L['haupt']['erg']['stat']
        z += ['', '## Preis der Vorzeichenwechsel-Sperre', '',
              f"Ohne Sperre {p(kk['cagr'])} p.a., mit Sperre nur long→short {p(kv['cagr']) if kv else '–'}, mit Sperre in beide Richtungen (live) {p(kl['cagr'])}. "
              f"{st_['gekreuzt']} Symbol-Tage hätten durch null gedreht; {st_['aufgeschoben']} Teile mehrtägiger Strategien wurden am Folgetag nachgeholt, "
              f"{st_['verfallen']} IBS-Teile sind verfallen. Fast die ganze Differenz kommt aus der Kaufseite (short → long): TSMOM ist in Abwärtsphasen short "
              'SPY/QQQ/IWM/EEM, genau dann kauft IBS dieselben ETFs – und IBS verdient in Abwärtsphasen am meisten. Die Sperre kappt so die besten IBS-Trades '
              '(z. B. QQQ 09.11.2022: 13 statt ≈ 300 Stück vor dem CPI-Tag), das Konto fällt 2022 tiefer, die Bremse (×0,5) greift 2023–2025 an den meisten Tagen. '
              'Siehe replay/BEOBACHTUNGEN.md.']
    z += ['', '![Brutto](brutto.png)', '', '## Modell und bewusste Abweichungen zu K3', '',
          '- Kennzahlen wie live: Historie relativ zum Entscheidungstag bereinigt (Alpaca `adjustment=all`); dadurch ATR aus der bereinigten statt der Rohreihe (K3: roh). Unterschied nur an Ex-Tagen.',
          '- Live-Modell mit Vorzeichenwechsel-Sperre (Review 3.2); K3-Modell ohne.',
          '- BB-Stop ab t0+2 intraday, Fill min(Eröffnung, Stop) – wie K3 (live wird der Stop schon am Ende von t0+1 gesetzt; nicht abgebildet).',
          '- SVXY handelbar ab 60 Handelstagen Historie (29.12.2011, Bedingung in `kern.kennzahlen`, live immer erfüllt). Das trifft K3 genau '
          '(80 VIX-Trades, 2012 +21 %); ab Auflage 04.10.2011 wären es 83 Trades, VIX-Beitrag 2,4 statt 2,8 Punkte (BEOBACHTUNGEN 2).',
          '- VIX-Contango entscheidet mit dem Yahoo-Schluss von ^VIX/^VIX3M (CBOE 16:15 ET), live um 15:45. Variante `vix_vortag` (Vortagesschluss) '
          'zeigt die pessimistische Schranke.',
          '- Fill = Schlusskurs. Die MOC-Abweichung misst der Live-Bot im Journal (`abweichung_bp`). K6 (Signal 15:45 statt Schluss) ist nicht enthalten: '
          'Erwartung IBS ≈ −0,4, IBS-Land ≈ −0,6 Punkte p.a. (README).',
          '- Stückzahl aus Yahoos `close` (nur split-bereinigt) wie K3: Bei UNG/USO war der echte Kurs 2010–2012 viel niedriger, der Replay rundet dort gröber als live (≤ 0,16 Punkte p.a., BEOBACHTUNGEN 5).',
          '- Keine Leihkosten, keine Zinsen (wie K3).']
    open(os.path.join(a.ausgabe, 'BERICHT.md'), 'w').write('\n'.join(z) + '\n')


if __name__ == '__main__':
    main()
