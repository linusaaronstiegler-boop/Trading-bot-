#!/usr/bin/env python3
"""Systembuch-Bot (Linus, 15.10.2026) – handelt NUR die belegten Regeln des Trading-Projekts auf einem Alpaca-Paper-Konto.
Reines Python (Standardbibliothek), kein LLM, keine Rechenkosten. Ein Lauf pro Handelstag: Start 15:28 ET, Entscheidung 15:45 ET (K6),
alle Orders als Market-on-Close (Alpaca `time_in_force=cls`), so wie die Backtests zum Schlusskurs gerechnet wurden.

Strategien (Belege: wissen/11-Testplan-2026-10.md, Katalog, Playbook v9 Abschnitt A):
  IBS            SPY QQQ DIA IWM      IBS<0,2 → Kauf, Verkauf am nächsten Tag (Halten bei Folgesignal)   25 % je ETF    C1a t 3,1
  IBS-Sektor     9 Sektor-ETFs        nur wenn heute kein Index-IBS-Signal, max 4, niedrigster IBS zuerst 11 % je ETF    C4  t 2,8
  IBS-Land       14 Länder-ETFs       max 4, niedrigster IBS zuerst                                        7 % je ETF     C18 t 5,6
  BB             SPY QQQ DIA IWM      Schluss>SMA200 und <unteres Band → Kauf, Stop 3×ATR20, Ausstieg Schluss>SMA20, spätestens Tag 15   25 %   A1a
  Monatswechsel  SPY QQQ DIA IWM      Kauf vorletzter Handelstag, Verkauf 3. Handelstag                   25 % je ETF    A1a
  MW-Land        12 Länder-ETFs       dito, experimentell                                                  4 % je ETF     C11 formal
  TSMOM          20 ETFs              letzter Handelstag: Vorzeichen 12M, 10 %/Vol60, Deckel, ×0,36, Brutto ≤ 60 %        C17 t 2,4
  VIX-Contango   SVXY long            VIX3M/VIX > 1,01 → 10 %, flach < 1,00 (Alpaca kann VXX nicht leihen; SVXY = −0,5× VIX-Futures)  C16 Experiment
Grenzen: Brutto-Nominal ≤ 1,9 × Equity (Vorrang in obiger Reihenfolge), Bremse ab 15 % unter Höchststand (alle Größen ×0,5),
Not-Aus unter 70 % des Startkapitals (alles glatt, Bot stoppt bis `state.json` von Hand zurückgesetzt wird).

Aufruf:  python3 systembuch_bot.py            (echter Lauf, nur im Fenster 11,5–40 Min vor Schluss; wartet bis 15 Min vor Schluss)
         python3 systembuch_bot.py --dry      (nichts senden, Plan zeigen)
         python3 systembuch_bot.py --dry --force   (auch außerhalb des Fensters rechnen)
Schlüssel: Umgebungsvariablen APCA_API_KEY_ID / APCA_API_SECRET_KEY (GitHub Secrets). Nie ins Repo schreiben.
Dateien im Arbeitsordner: state.json (Legs, Höchststand, offene Orders), journal.csv (geschlossene Legs), STATUS.md, log.txt.
"""
import json, os, sys, csv, math, time, argparse, urllib.request, urllib.error, datetime as dt
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
PAPER = 'https://paper-api.alpaca.markets'; DATA = 'https://data.alpaca.markets'
INDEX = ('SPY', 'QQQ', 'DIA', 'IWM')
SEKTOREN = ('XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY')
LAENDER = ('EWG', 'EWJ', 'EWU', 'EWA', 'EWH', 'EWC', 'EWY', 'EWT', 'EWZ', 'EWL', 'EWQ', 'EWP', 'EFA', 'EEM')
MW_LAND = LAENDER[:12]
TSMOM = ('SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'EWJ', 'EWG', 'TLT', 'IEF', 'LQD', 'HYG', 'GLD', 'SLV', 'USO', 'DBC', 'DBA', 'UNG', 'UUP', 'FXE', 'VNQ')
GROESSE = dict(IBS=0.25, IBS_SEKTOR=0.11, IBS_LAND=0.07, BB=0.25, MW=0.25, MW_LAND=0.04, VIX=0.10)
MAX_OFFEN = dict(IBS_SEKTOR=4, IBS_LAND=4, BB=4)
TSMOM_BRUTTO_MAX = 0.60; MAX_BRUTTO = 1.9; BREMSE_DD = 0.15; NOTAUS = 0.70
# Lauffenster (Studie K6, 15.10.2026): Das IBS-Signal 15 Min vor Schluss behält 91 % des Schluss-Ertrags, 30 Min vor Schluss nur 46 %.
# Der Lauf darf früh starten (Cron-Verzug bei GitHub), WARTET aber bis ENTSCHEIDUNG_MIN vor Schluss, lädt dann erst die Kurse
# und sendet die MOC-Orders sofort; Alpaca lehnt `cls` nach 15:50 ET ab, deshalb harter Abbruch unter ORDER_SPAETESTENS_MIN.
ENTSCHEIDUNG_MIN = 15.0      # Minuten vor Schluss, zu denen Kurse geladen und entschieden wird (15:45 ET)
START_FRUEHESTENS_MIN = 40.0 # Lauf darf ab hier starten und wartet (Cron 15:28 ET + Verzug)
START_SPAETESTENS_MIN = 11.5 # später gestartete Läufe handeln nicht mehr (Nachläufer-Cron 15:40 ET fängt Verzug ab)
ORDER_SPAETESTENS_MIN = 10.5 # vor der Orderschleife Uhr erneut lesen; darunter keine Orders (MOC-Annahmeschluss 15:50 ET)
FEIERTAGE = {'2026-11-26', '2026-12-25', '2027-01-01', '2027-01-18', '2027-02-15', '2027-04-02', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24'}
HALBE_TAGE = {'2026-11-27', '2026-12-24', '2027-11-26'}
VORRANG = ('IBS', 'MW', 'BB', 'IBS_SEKTOR', 'IBS_LAND', 'TSMOM', 'MW_LAND', 'VIX')

# ---------- Infrastruktur ----------
def log(msg):
    line = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line)
    with open('log.txt', 'a') as f: f.write(line + '\n')

def hdr():
    k, s = os.environ.get('APCA_API_KEY_ID'), os.environ.get('APCA_API_SECRET_KEY')
    if not (k and s): raise SystemExit('Alpaca-Schlüssel fehlen (APCA_API_KEY_ID / APCA_API_SECRET_KEY)')
    return {'APCA-API-KEY-ID': k, 'APCA-API-SECRET-KEY': s, 'Content-Type': 'application/json'}

def alp(path, body=None, method=None, base=PAPER, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=hdr(), method=method)
            raw = urllib.request.urlopen(r, timeout=30).read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            txt = e.read()[:300].decode(errors='ignore')
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1: time.sleep(2 + 2 * i); continue
            raise RuntimeError(f'Alpaca {e.code} {path}: {txt}')
        except (urllib.error.URLError, TimeoutError) as e:
            if i < tries - 1: time.sleep(2 + 2 * i); continue
            raise

def bars(symbols, tage=420):
    """Tageskerzen (adjustment=all, IEX-Feed) für viele Symbole in einem Aufruf, als {sym: [(date, o, h, l, c)]}."""
    start = (dt.date.today() - dt.timedelta(days=int(tage * 1.5))).isoformat()
    out = {s: [] for s in symbols}; token = None
    while True:
        q = f'/v2/stocks/bars?symbols={",".join(symbols)}&timeframe=1Day&start={start}&limit=10000&adjustment=all&feed=iex' + (f'&page_token={token}' if token else '')
        d = alp(q, base=DATA)
        for s, rows in (d.get('bars') or {}).items():
            for b in rows: out[s].append((b['t'][:10], b['o'], b['h'], b['l'], b['c']))
        token = d.get('next_page_token')
        if not token: break
    heute = dt.datetime.now(NY).date().isoformat()
    for s in out: out[s] = sorted([r for r in out[s] if r[0] < heute])            # nur abgeschlossene Tage
    return out

def snapshots(symbols):
    """Heutiger Stand (IEX): Tageshoch/-tief bisher und letzter Kurs."""
    d = alp(f'/v2/stocks/snapshots?symbols={",".join(symbols)}&feed=iex', base=DATA)
    out = {}
    for s, v in d.items():
        db = v.get('dailyBar') or {}; lt = v.get('latestTrade') or {}
        px = lt.get('p') or db.get('c')
        if px: out[s] = dict(px=float(px), hi=float(db.get('h') or px), lo=float(db.get('l') or px))
    return out

def yahoo_live(sym):
    r = urllib.request.Request(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m', headers={'User-Agent': 'Mozilla/5.0'})
    return json.load(urllib.request.urlopen(r, timeout=25))['chart']['result'][0]['meta']['regularMarketPrice']

def handelstage(jahr, monat):
    d = dt.date(jahr, monat, 1); out = []
    while d.month == monat:
        if d.weekday() < 5 and d.isoformat() not in FEIERTAGE: out.append(d)
        d += dt.timedelta(days=1)
    return out

# ---------- Zustand ----------
def laden():
    if os.path.exists('state.json'): return json.load(open('state.json'))
    return dict(start=None, startkapital=None, hwm=None, legs=[], naechste_id=1, offene_orders={}, gestoppt=False, letzter_lauf=None, tag_zaehler={})

def speichern(st): json.dump(st, open('state.json', 'w'), indent=1, ensure_ascii=False)

def journal(leg, ausstieg, grund, heute):
    neu = not os.path.exists('journal.csv')
    with open('journal.csv', 'a', newline='') as f:
        w = csv.writer(f)
        if neu: w.writerow(['id', 'strategie', 'symbol', 'richtung', 'stueck', 'einstieg', 'einstieg_datum', 'ausstieg', 'ausstieg_datum', 'pnl', 'grund'])
        pnl = (ausstieg - leg['einstieg']) * leg['stueck'] * leg['richtung'] if leg.get('einstieg') and ausstieg else ''
        w.writerow([leg['id'], leg['strategie'], leg['symbol'], leg['richtung'], leg['stueck'], leg.get('einstieg'), leg['datum'], ausstieg, heute, round(pnl, 2) if pnl != '' else '', grund])

# ---------- Signale ----------
def kennzahlen(hist, live):
    """Pro Symbol: IBS heute, SMA200/SMA20/BB-unten (mit heutigem Kurs als letztem Schluss), ATR20, 12M-Rendite, Vol60."""
    out = {}
    for s, rows in hist.items():
        if s not in live or len(rows) < 60: continue
        px = live[s]['px']; hi = max(live[s]['hi'], px); lo = min(live[s]['lo'], px)      # IEX-Tagesbar hinkt dem letzten Kurs nach
        closes = [r[4] for r in rows] + [px]
        hs = [r[2] for r in rows]; ls = [r[3] for r in rows]; cs = [r[4] for r in rows]
        tr = [max(hs[i] - ls[i], abs(hs[i] - cs[i - 1]), abs(ls[i] - cs[i - 1])) for i in range(1, len(rows))]
        k = dict(px=px, hi=hi, lo=lo, ibs=min(1.0, max(0.0, (px - lo) / (hi - lo))) if hi > lo else 0.5, atr20=sum(tr[-20:]) / 20,
                 sma20=sum(closes[-20:]) / 20, sma200=sum(closes[-200:]) / 200 if len(closes) >= 200 else None)
        sd20 = (sum((c - k['sma20']) ** 2 for c in closes[-20:]) / 19) ** 0.5
        k['bb_unten'] = k['sma20'] - 2 * sd20
        if len(closes) >= 253:
            k['ret12'] = closes[-1] / closes[-253] - 1
            rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - 60, len(closes))]
            mu = sum(rets) / 60; k['vol60'] = (sum((x - mu) ** 2 for x in rets) / 59) ** 0.5 * 252 ** 0.5
        out[s] = k
    return out

def tsmom_gewichte(kz):
    roh = {s: (1 if kz[s]['ret12'] > 0 else -1) * min(0.10 / max(kz[s]['vol60'], 0.02), 2.0) for s in TSMOM if s in kz and 'ret12' in kz[s]}
    summe = sum(abs(w) for w in roh.values()); f1 = min(1.0, 4.0 / summe) if summe else 1.0
    ziel = {s: w * f1 * 0.36 for s, w in roh.items()}
    brutto = sum(abs(w) for w in ziel.values()); f3 = min(1.0, TSMOM_BRUTTO_MAX / brutto) if brutto else 1.0
    return {s: w * f3 for s, w in ziel.items()}

# ---------- Hauptlauf ----------
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dry', action='store_true'); ap.add_argument('--force', action='store_true'); a = ap.parse_args()
    st = laden()
    clock = alp('/v2/clock'); jetzt = dt.datetime.fromisoformat(clock['timestamp'].replace('Z', '+00:00')); heute = jetzt.astimezone(NY).date()
    naechster_schluss = dt.datetime.fromisoformat(clock['next_close'].replace('Z', '+00:00'))
    min_bis_schluss = (naechster_schluss - jetzt).total_seconds() / 60
    if not clock['is_open'] or not (START_SPAETESTENS_MIN <= min_bis_schluss <= START_FRUEHESTENS_MIN):
        if not a.force:
            log(f'kein Fenster (offen={clock["is_open"]}, {min_bis_schluss:.1f} Min bis Schluss) – Ende'); return
        log(f'--force: außerhalb des Fensters ({min_bis_schluss:.1f} Min bis Schluss)')
    if st.get('letzter_lauf') == heute.isoformat() and not a.force:
        log('heute schon gelaufen – Ende'); return
    if st.get('gestoppt'):
        log('NOT-AUS aktiv – kein Handel, bis state.json von Hand zurückgesetzt wird'); return
    # K6: bis ENTSCHEIDUNG_MIN vor Schluss warten, erst dann Kurse laden (Signal so nah am Schluss wie Alpaca erlaubt)
    if clock['is_open'] and min_bis_schluss > ENTSCHEIDUNG_MIN and not a.force:
        warte = (min_bis_schluss - ENTSCHEIDUNG_MIN) * 60
        log(f'warte {warte/60:.1f} Min bis {ENTSCHEIDUNG_MIN:.0f} Min vor Schluss (K6-Fenster)'); time.sleep(warte)
        clock = alp('/v2/clock'); jetzt = dt.datetime.fromisoformat(clock['timestamp'].replace('Z', '+00:00'))
        min_bis_schluss = (naechster_schluss - jetzt).total_seconds() / 60

    konto = alp('/v2/account'); eq = float(konto['equity'])
    if st['startkapital'] is None: st.update(start=heute.isoformat(), startkapital=eq, hwm=eq)
    st['hwm'] = max(st['hwm'] or eq, eq); dd = 1 - eq / st['hwm']
    faktor = 0.5 if dd >= BREMSE_DD else 1.0
    log(f'Lauf {heute} – Equity {eq:,.0f} $, Höchststand {st["hwm"]:,.0f}, Drawdown {dd:.1%}, Größenfaktor {faktor}')

    # 1) Fills der letzten MOC-Orders nachtragen, BB-Stops setzen
    for leg in st['legs']:
        oid = leg.get('order_id')
        if oid and leg.get('einstieg') is None:
            try:
                o = alp(f'/v2/orders/{oid}')
                if o.get('status') == 'filled':
                    leg['einstieg'] = float(o['filled_avg_price']); leg['stueck'] = int(float(o['filled_qty']))
                elif o.get('status') in ('canceled', 'expired', 'rejected'):
                    leg['stueck'] = 0; log(f'Leg {leg["id"]} {leg["symbol"]} nicht gefüllt ({o.get("status")}) – gestrichen')
            except Exception as e: log(f'Order {oid} nicht lesbar: {str(e)[:100]}')
    st['legs'] = [l for l in st['legs'] if l['stueck'] > 0]
    for leg in st['legs']:
        if leg['strategie'] == 'BB' and leg.get('einstieg') and not leg.get('stop_order') and not a.dry:
            stop = round(leg['einstieg'] - 3 * leg['atr20'], 2)
            try:
                o = alp('/v2/orders', dict(symbol=leg['symbol'], qty=str(leg['stueck']), side='sell', type='stop', stop_price=f'{stop:.2f}', time_in_force='gtc'), 'POST')
                leg['stop_order'] = o['id']; leg['stop'] = stop; log(f'BB-Stop {leg["symbol"]} {leg["stueck"]} @ {stop}')
            except Exception as e: log(f'BB-Stop {leg["symbol"]} fehlgeschlagen: {str(e)[:120]}')
    # Stops, die gefüllt wurden → Leg schließen
    for leg in list(st['legs']):
        if leg.get('stop_order'):
            try:
                o = alp(f'/v2/orders/{leg["stop_order"]}')
                if o.get('status') == 'filled':
                    journal(leg, float(o['filled_avg_price']), 'Stop', heute.isoformat()); st['legs'].remove(leg); log(f'BB-Stop gefüllt {leg["symbol"]} @ {o["filled_avg_price"]}')
            except Exception as e: log(f'Stop-Order {leg["stop_order"]} nicht lesbar: {str(e)[:100]}')

    # 2) Not-Aus
    if eq < NOTAUS * st['startkapital']:
        log(f'NOT-AUS: Equity {eq:,.0f} < 70 % von {st["startkapital"]:,.0f} – alles glatt')
        if not a.dry:
            alp('/v2/positions?cancel_orders=true', method='DELETE')
            for leg in st['legs']: journal(leg, None, 'NOT-AUS', heute.isoformat())
            st['legs'] = []; st['gestoppt'] = True; speichern(st)
        return

    # 3) Daten
    alle = sorted(set(INDEX + SEKTOREN + LAENDER + TSMOM + ('SVXY',)))
    hist = bars(alle); live = snapshots(alle); kz = kennzahlen(hist, live)
    try: vix, vix3m = yahoo_live('^VIX'), yahoo_live('^VIX3M'); ratio = vix3m / vix
    except Exception as e: vix = vix3m = ratio = None; log(f'VIX nicht lesbar: {str(e)[:80]}')
    tage = handelstage(heute.year, heute.month)
    mw_kauf = len(tage) >= 2 and heute == tage[-2]; mw_verkauf = len(tage) >= 3 and heute == tage[2]; tsmom_tag = bool(tage) and heute == tage[-1]
    handelstag_nr = {d: i for i, d in enumerate(tage)}
    log(f'Signale: MW-Kauf {mw_kauf}, MW-Verkauf {mw_verkauf}, TSMOM {tsmom_tag}, VIX3M/VIX {ratio and round(ratio, 3)}')

    # 4) Ausstiege (bestehende Legs)
    schliessen = []
    for leg in st['legs']:
        s, k = leg['symbol'], kz.get(leg['symbol'])
        if k is None: continue
        if leg['strategie'] in ('IBS', 'IBS_SEKTOR', 'IBS_LAND') and leg['datum'] < heute.isoformat():
            if k['ibs'] >= 0.2: schliessen.append((leg, 'IBS Ausstieg Folgetag'))
            else: leg['datum'] = heute.isoformat()                                       # Folgesignal: halten, Tag neu zählen
        elif leg['strategie'] == 'BB':
            alter = sum(1 for d in handelstage_zwischen(dt.date.fromisoformat(leg['datum']), heute))
            if k['px'] > k['sma20']: schliessen.append((leg, 'BB über SMA20'))
            elif alter >= 15: schliessen.append((leg, 'BB Tag 15'))
        elif leg['strategie'] in ('MW', 'MW_LAND') and mw_verkauf: schliessen.append((leg, 'Monatswechsel Verkauf'))
        elif leg['strategie'] == 'TSMOM' and tsmom_tag: schliessen.append((leg, 'TSMOM Umschichtung'))
        elif leg['strategie'] == 'VIX' and ratio is not None and ratio < 1.0: schliessen.append((leg, 'VIX Backwardation'))

    # 5) Einstiege (nach Vorrang, mit Brutto-Deckel)
    neu = []
    def brutto(legs_liste):
        return sum(abs(l['stueck'] * kz.get(l['symbol'], {}).get('px', l.get('einstieg') or 0)) for l in legs_liste)
    bleibende = [l for l in st['legs'] if l not in [x[0] for x in schliessen]]
    offen = lambda strat: [l for l in bleibende + neu if l['strategie'] == strat]
    def plane(strat, sym, richtung, anteil, extra=None):
        if sym not in kz: return
        nominal = anteil * eq * faktor
        if brutto(bleibende + neu) + nominal > MAX_BRUTTO * eq: log(f'{strat} {sym}: Brutto-Deckel, übersprungen'); return
        st_ = int(nominal / kz[sym]['px'])
        if st_ < 1: return
        leg = dict(id=None, strategie=strat, symbol=sym, richtung=richtung, stueck=st_, einstieg=None, datum=heute.isoformat(), atr20=round(kz[sym]['atr20'], 4))
        if extra: leg.update(extra)
        neu.append(leg)
    index_signal = any(kz[s]['ibs'] < 0.2 for s in INDEX if s in kz)
    for s in INDEX:
        if s in kz and kz[s]['ibs'] < 0.2 and not any(l['symbol'] == s for l in offen('IBS')): plane('IBS', s, 1, GROESSE['IBS'])
    if mw_kauf:
        for s in INDEX:
            if s in kz and not any(l['symbol'] == s for l in offen('MW')): plane('MW', s, 1, GROESSE['MW'])
    for s in INDEX:
        k = kz.get(s)
        if k and k['sma200'] and k['px'] > k['sma200'] and k['px'] < k['bb_unten'] and len(offen('BB')) < MAX_OFFEN['BB'] and not any(l['symbol'] == s for l in offen('BB')):
            plane('BB', s, 1, GROESSE['BB'])
    if not index_signal and not offen('IBS'):
        for s in sorted([s for s in SEKTOREN if s in kz and kz[s]['ibs'] < 0.2], key=lambda s: kz[s]['ibs']):
            if len(offen('IBS_SEKTOR')) < MAX_OFFEN['IBS_SEKTOR'] and not any(l['symbol'] == s for l in offen('IBS_SEKTOR')): plane('IBS_SEKTOR', s, 1, GROESSE['IBS_SEKTOR'])
    for s in sorted([s for s in LAENDER if s in kz and kz[s]['ibs'] < 0.2], key=lambda s: kz[s]['ibs']):
        if len(offen('IBS_LAND')) < MAX_OFFEN['IBS_LAND'] and not any(l['symbol'] == s for l in offen('IBS_LAND')): plane('IBS_LAND', s, 1, GROESSE['IBS_LAND'])
    if tsmom_tag:
        gew = tsmom_gewichte(kz)
        shortable = {}
        for s, w in gew.items():
            if w < 0:
                try: shortable[s] = alp(f'/v2/assets/{s}').get('shortable', False)
                except Exception: shortable[s] = False
        for s, w in sorted(gew.items(), key=lambda x: -abs(x[1])):
            if w < 0 and not shortable.get(s): log(f'TSMOM {s}: Short nicht leihbar – übersprungen'); continue
            plane('TSMOM', s, 1 if w > 0 else -1, abs(w))
    if mw_kauf:
        for s in MW_LAND:
            if s in kz and not any(l['symbol'] == s for l in offen('MW_LAND')): plane('MW_LAND', s, 1, GROESSE['MW_LAND'])
    if ratio is not None and ratio > 1.01 and 'SVXY' in kz and not offen('VIX'): plane('VIX', 'SVXY', 1, GROESSE['VIX'])

    # 6) Netto-Orders je Symbol (MOC)
    delta = {}
    for leg, _ in schliessen: delta[leg['symbol']] = delta.get(leg['symbol'], 0) - leg['richtung'] * leg['stueck']
    for leg in neu: delta[leg['symbol']] = delta.get(leg['symbol'], 0) + leg['richtung'] * leg['stueck']
    plan = {s: d for s, d in delta.items() if d != 0}
    log(f'Ausstiege: {[(l["strategie"], l["symbol"], g) for l, g in schliessen]}')
    log(f'Einstiege: {[(l["strategie"], l["symbol"], l["richtung"] * l["stueck"]) for l in neu]}')
    log(f'Netto-MOC-Orders: {plan}')
    if a.dry:
        status_md(st, eq, dd, kz, ratio, plan, schliessen, neu, heute, dry=True); return

    # Uhr erneut lesen: Alpaca lehnt MOC (`cls`) nach 15:50 ET ab – lieber kein Handel als abgelehnte Orders, die als ausgeführt gebucht würden
    clock2 = alp('/v2/clock'); jetzt2 = dt.datetime.fromisoformat(clock2['timestamp'].replace('Z', '+00:00'))
    rest = (naechster_schluss - jetzt2).total_seconds() / 60
    if rest < ORDER_SPAETESTENS_MIN and not a.force:
        log(f'ZU SPÄT für MOC ({rest:.1f} Min bis Schluss, Grenze {ORDER_SPAETESTENS_MIN}) – keine Orders gesendet, Zustand unverändert')
        status_md(st, eq, dd, kz, ratio, plan, schliessen, neu, heute, dry=True); sys.exit(1)

    # BB-Stops der schließenden Legs löschen, dann Orders
    for leg, _ in schliessen:
        if leg.get('stop_order'):
            try: alp(f'/v2/orders/{leg["stop_order"]}', method='DELETE')
            except Exception: pass
    bestand = {p['symbol']: float(p['qty']) for p in alp('/v2/positions')}
    gesendet = {}
    for s, d in plan.items():
        seite = 'buy' if d > 0 else 'sell'
        # Alpaca: Short-Verkauf und Long-Verkauf nicht in einer Order mischen → bei Vorzeichenwechsel in zwei Orders teilen
        hab = bestand.get(s, 0.0); teile = []
        if hab > 0 and d < 0 and abs(d) > hab: teile = [-int(hab), d + int(hab)]
        elif hab < 0 and d > 0 and d > -hab: teile = [int(-hab), d + int(hab)]
        else: teile = [d]
        for t in teile:
            if t == 0: continue
            body = dict(symbol=s, qty=str(abs(t)), side='buy' if t > 0 else 'sell', type='market', time_in_force='cls',
                        client_order_id=f'sb-{heute.isoformat()}-{s}-{abs(t)}-{int(time.time()) % 100000}')
            try:
                o = alp('/v2/orders', body, 'POST'); gesendet.setdefault(s, []).append(o['id']); log(f'MOC {body["side"]} {abs(t)} {s} → {o["id"]}')
            except Exception as e: log(f'Order {s} {t} FEHLER: {str(e)[:160]}')
    # 7) Legs buchen (Ausstiegspreis = heutiger Schluss ≈ letzter Kurs; Fill wird nicht nachträglich korrigiert – Journal ist Näherung auf Cent-Ebene)
    for leg, grund in schliessen:
        journal(leg, kz[leg['symbol']]['px'], grund, heute.isoformat()); st['legs'].remove(leg)
    for leg in neu:
        leg['id'] = st['naechste_id']; st['naechste_id'] += 1
        leg['order_id'] = (gesendet.get(leg['symbol']) or [None])[0]
        if leg['order_id'] is None: leg['einstieg'] = kz[leg['symbol']]['px']                 # Netto 0 (Wechsel innerhalb des Symbols): Buchwert = Kurs
        st['legs'].append(leg)
    st['letzter_lauf'] = heute.isoformat(); speichern(st)
    status_md(st, eq, dd, kz, ratio, plan, schliessen, neu, heute)

def handelstage_zwischen(d0, d1):
    d = d0; out = []
    while d < d1:
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in FEIERTAGE: out.append(d)
    return out

def status_md(st, eq, dd, kz, ratio, plan, schliessen, neu, heute, dry=False):
    z = [f"# Systembuch-Bot – Stand {heute} {'(DRY RUN)' if dry else ''}", '',
         f"Equity **{eq:,.0f} $** · Start {st.get('startkapital') or eq:,.0f} $ · Höchststand {st.get('hwm') or eq:,.0f} $ · Drawdown {dd:.1%}{' · BREMSE' if dd >= BREMSE_DD else ''}",
         f"VIX3M/VIX {ratio and round(ratio, 3)} · Netto-Orders heute: {plan or 'keine'}", '',
         '| Leg | Strategie | Symbol | Richtung | Stück | Einstieg | seit | Stop |', '|---|---|---|---|---|---|---|---|']
    for l in st['legs']: z.append(f"| {l['id']} | {l['strategie']} | {l['symbol']} | {'long' if l['richtung'] > 0 else 'short'} | {l['stueck']} | {l.get('einstieg') or 'MOC offen'} | {l['datum']} | {l.get('stop', '')} |")
    for l in neu: z.append(f"| neu | {l['strategie']} | {l['symbol']} | {'long' if l['richtung'] > 0 else 'short'} | {l['stueck']} | MOC heute | {l['datum']} | |")
    z += ['', '## Signale heute', '| ETF | Kurs | IBS | SMA200 | BB unten | Signal |', '|---|---|---|---|---|---|']
    for s in INDEX + SEKTOREN + LAENDER:
        k = kz.get(s)
        if not k: continue
        sig = ('IBS ' if k['ibs'] < 0.2 else '') + ('BB ' if k['sma200'] and k['px'] > k['sma200'] and k['px'] < k['bb_unten'] else '')
        z.append(f"| {s} | {k['px']:.2f} | {k['ibs']:.2f} | {k['sma200'] and round(k['sma200'], 2)} | {k['bb_unten']:.2f} | {sig} |")
    z += ['', f"Ausstiege: {[(l['strategie'], l['symbol'], g) for l, g in schliessen] or 'keine'}", '', '*Regeln und Belege: README.md. Journal: journal.csv. Log: log.txt.*']
    open('STATUS.md', 'w').write('\n'.join(z))

if __name__ == '__main__':
    main()
