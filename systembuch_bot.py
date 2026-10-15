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
from kern import (INDEX, SEKTOREN, LAENDER, MW_LAND, TSMOM, GROESSE, MAX_OFFEN, TSMOM_BRUTTO_MAX, MAX_BRUTTO, BREMSE_DD, NOTAUS,
                  VORRANG, ALLE_SYMBOLE, kennzahlen, tsmom_gewichte, entscheide, netto_plan, netto_orders, Kalender)
# Lauffenster (Studie K6, 15.10.2026): Das IBS-Signal 15 Min vor Schluss behält 91 % des Schluss-Ertrags, 30 Min vor Schluss nur 46 %.
# Der Lauf darf früh starten (Cron-Verzug bei GitHub), WARTET aber bis ENTSCHEIDUNG_MIN vor Schluss, lädt dann erst die Kurse
# und sendet die MOC-Orders sofort; Alpaca lehnt `cls` nach 15:50 ET ab, deshalb harter Abbruch unter ORDER_SPAETESTENS_MIN.
ENTSCHEIDUNG_MIN = 15.0      # Minuten vor Schluss, zu denen Kurse geladen und entschieden wird (15:45 ET)
START_FRUEHESTENS_MIN = 40.0 # Lauf darf ab hier starten und wartet (Cron 15:28 ET + Verzug)
START_SPAETESTENS_MIN = 11.5 # später gestartete Läufe handeln nicht mehr (Nachläufer-Cron 15:40 ET fängt Verzug ab)
ORDER_SPAETESTENS_MIN = 10.5 # vor der Orderschleife Uhr erneut lesen; darunter keine Orders (MOC-Annahmeschluss 15:50 ET)

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

def bars(symbols, heute, tage=420):
    """Tageskerzen (adjustment=all, konsolidierter SIP-Feed – Review 1.3: IEX hat Lücken und zu enge Hoch/Tief) als {sym: [(date, o, h, l, c)]}.
    Der Basic-Plan erlaubt SIP-Historie, die älter als 15 Minuten ist; abgeschlossene Tage sind das immer."""
    start = (heute - dt.timedelta(days=int(tage * 1.5))).isoformat()
    out = {s: [] for s in symbols}; token = None
    while True:
        q = f'/v2/stocks/bars?symbols={",".join(symbols)}&timeframe=1Day&start={start}&limit=10000&adjustment=all&feed=sip' + (f'&page_token={token}' if token else '')
        d = alp(q, base=DATA)
        for s, rows in (d.get('bars') or {}).items():
            for b in rows: out[s].append((b['t'][:10], b['o'], b['h'], b['l'], b['c']))
        token = d.get('next_page_token')
        if not token: break
    for s in out: out[s] = sorted([r for r in out[s] if r[0] < heute.isoformat()])  # nur abgeschlossene Tage
    return out

def snapshots(symbols):
    """Heutiger Stand. Letzter Kurs aus IEX (Echtzeit); Tageshoch/-tief zusätzlich aus `delayed_sip` (konsolidiert, 15 Min alt),
    damit dünn gehandelte ETFs kein zu enges IEX-Band bekommen (Review 1.3). Ist `delayed_sip` nicht erlaubt, bleibt es bei IEX.
    Kein IEX-Trade heute → Mitte aus letztem Quote bzw. jüngerer SIP-Kurs (Review 4.4)."""
    iex = alp(f'/v2/stocks/snapshots?symbols={",".join(symbols)}&feed=iex', base=DATA)
    try: sip = alp(f'/v2/stocks/snapshots?symbols={",".join(symbols)}&feed=delayed_sip', base=DATA)
    except Exception as e: sip = {}; log(f'delayed_sip nicht verfügbar – Hoch/Tief nur aus IEX ({str(e)[:80]})')
    return snapshot_zusammenfuehren(iex, sip)


def snapshot_zusammenfuehren(iex, sip):
    out = {}
    for s in set(iex) | set(sip):
        vi, vs = iex.get(s) or {}, sip.get(s) or {}
        kandidaten = [(t.get('t') or '', float(t['p'])) for t in ((vi.get('latestTrade') or {}), (vs.get('latestTrade') or {})) if t.get('p')]
        px = max(kandidaten)[1] if kandidaten else None                                   # jüngster Trade gewinnt
        q = vi.get('latestQuote') or {}
        if px is None and q.get('ap') and q.get('bp'): px = (float(q['ap']) + float(q['bp'])) / 2
        if px is None: continue
        his = [float(b['h']) for b in ((vi.get('dailyBar') or {}), (vs.get('dailyBar') or {})) if b.get('h')]
        los = [float(b['l']) for b in ((vi.get('dailyBar') or {}), (vs.get('dailyBar') or {})) if b.get('l')]
        out[s] = dict(px=px, hi=max(his + [px]), lo=min(los + [px]))
    return out

def yahoo_live(sym):
    r = urllib.request.Request(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=5m', headers={'User-Agent': 'Mozilla/5.0'})
    return json.load(urllib.request.urlopen(r, timeout=25))['chart']['result'][0]['meta']['regularMarketPrice']

# ---------- Zustand ----------
def laden():
    if os.path.exists('state.json'): return json.load(open('state.json'))
    return dict(start=None, startkapital=None, hwm=None, legs=[], naechste_id=1, gestoppt=False, letzter_lauf=None, letzte_tsmom=None, aufgeschoben=[])

def speichern(st): json.dump(st, open('state.json', 'w'), indent=1, ensure_ascii=False)

def journal(leg, ausstieg, grund, heute):
    neu = not os.path.exists('journal.csv')
    with open('journal.csv', 'a', newline='') as f:
        w = csv.writer(f)
        if neu: w.writerow(['id', 'strategie', 'symbol', 'richtung', 'stueck', 'einstieg', 'einstieg_datum', 'ausstieg', 'ausstieg_datum', 'pnl', 'grund'])
        pnl = (ausstieg - leg['einstieg']) * leg['stueck'] * leg['richtung'] if leg.get('einstieg') and ausstieg else ''
        w.writerow([leg['id'], leg['strategie'], leg['symbol'], leg['richtung'], leg['stueck'], leg.get('einstieg'), leg['datum'], ausstieg, heute, round(pnl, 2) if pnl != '' else '', grund])

# ---------- Hauptlauf ----------
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dry', action='store_true'); ap.add_argument('--force', action='store_true'); a = ap.parse_args()
    if a.force and not a.dry: raise SystemExit('--force nur zusammen mit --dry (Orders nur im Fenster 10–30 Min vor Schluss)')
    st = laden()
    for k, v in dict(letzte_tsmom=None, aufgeschoben=[]).items(): st.setdefault(k, v)
    for k in ('offene_orders', 'tag_zaehler'): st.pop(k, None)
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
    if st['startkapital'] is None: st.update(start=heute.isoformat(), startkapital=eq, hwm=eq, letzte_tsmom=heute.isoformat())
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
    alle = list(ALLE_SYMBOLE)
    hist = bars(alle, heute); live = snapshots(alle); kz = kennzahlen(hist, live)
    kurse = dict(live)
    try: kurse['^VIX'] = {'px': yahoo_live('^VIX')}; kurse['^VIX3M'] = {'px': yahoo_live('^VIX3M')}
    except Exception as e: kurse.pop('^VIX', None); kurse.pop('^VIX3M', None); log(f'VIX nicht lesbar: {str(e)[:80]}')
    # Aufgabe 1: Entscheidung in der reinen Funktion kern.entscheide() (derselbe Codepfad wie im Replay)
    leihbar = {}
    for s in TSMOM:
        try: leihbar[s] = alp(f'/v2/assets/{s}').get('shortable', False)
        except Exception: leihbar[s] = False
    zustand = dict(heute=heute.isoformat(), equity=eq, hwm=st['hwm'], legs=st['legs'], leihbar=leihbar,
                   letzte_tsmom=st.get('letzte_tsmom'), aufgeschoben=st.get('aufgeschoben', []))
    kal = lade_kalender(heute)
    schliessen, neu, info = entscheide(zustand, kurse, hist, kal, kz=kz)
    ratio = info['ratio']
    for l in st['legs']:
        if l.get('id') in info['datum_neu']: l['datum'] = info['datum_neu'][l['id']]       # Folgesignal: halten, Tag neu zählen
    for z in info['log']: log(z)
    log(f'Signale: MW-Kauf {info["mw_kauf"]}, MW-Verkauf {info["mw_verkauf"]}, TSMOM {info["tsmom_tag"]}, VIX3M/VIX {ratio and round(ratio, 3)}')
    roh = netto_plan(schliessen, neu)
    no = netto_orders(st['legs'], schliessen, neu)                                     # Review 3.2: nie durch null in einem Tag
    plan = no['orders']; schliessen = [(l, g) if m == l['stueck'] else (l, g, m) for l, g, m in no['ausstiege']]; neu = no['einstiege']
    for s in no['gekreuzt']: log(f'{s}: Vorzeichenwechsel – heute nur bis null ({roh.get(s)} → {plan.get(s)}), Rest nachholen/verfallen')
    for x in no['verfallen']: log(f"verfällt (Vorzeichenwechsel): {x['strategie']} {x['symbol']} {x['richtung'] * x['stueck']}")
    log(f'Ausstiege: {[(l["strategie"], l["symbol"], g) for l, g, *_ in schliessen]}')
    log(f'Einstiege: {[(l["strategie"], l["symbol"], l["richtung"] * l["stueck"]) for l in neu]}')
    log(f'Netto-MOC-Orders: {plan}')
    ergebnis = dict(roh=roh, plan=plan, gekreuzt=no['gekreuzt'], aufgeschoben=no['aufgeschoben'], verfallen=no['verfallen'])
    if a.dry:
        status_md(st, eq, dd, kz, ratio, plan, schliessen, neu, heute, dry=True); return ergebnis

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
    gesendet = {}
    for s, d in plan.items():
        for t in [d]:                                                                   # nach netto_orders nie mehr zwei Orders je Symbol
            if t == 0: continue
            body = dict(symbol=s, qty=str(abs(t)), side='buy' if t > 0 else 'sell', type='market', time_in_force='cls',
                        client_order_id=f'sb-{heute.isoformat()}-{s}-{abs(t)}-{int(time.time()) % 100000}')
            try:
                o = alp('/v2/orders', body, 'POST'); gesendet.setdefault(s, []).append(o['id']); log(f'MOC {body["side"]} {abs(t)} {s} → {o["id"]}')
            except Exception as e: log(f'Order {s} {t} FEHLER: {str(e)[:160]}')
    # 7) Legs buchen (Ausstiegspreis = heutiger Schluss ≈ letzter Kurs; Fill wird nicht nachträglich korrigiert – Journal ist Näherung auf Cent-Ebene)
    for leg, grund, *_ in schliessen:
        journal(leg, kz[leg['symbol']]['px'], grund, heute.isoformat()); st['legs'].remove(leg)
    st['aufgeschoben'] = no['aufgeschoben']
    if info['tsmom_tag']: st['letzte_tsmom'] = heute.isoformat()
    for leg in neu:
        leg['id'] = st['naechste_id']; st['naechste_id'] += 1
        leg['order_id'] = (gesendet.get(leg['symbol']) or [None])[0]
        if leg['order_id'] is None: leg['einstieg'] = kz[leg['symbol']]['px']                 # Netto 0 (Wechsel innerhalb des Symbols): Buchwert = Kurs
        st['legs'].append(leg)
    st['letzter_lauf'] = heute.isoformat(); speichern(st)
    status_md(st, eq, dd, kz, ratio, plan, schliessen, neu, heute)

def lade_kalender(heute):
    """Handelstage mit Schlusszeit aus GET /v2/calendar (Review 1.11/1.12: keine Feiertagstabelle mehr, Halbtage erkannt).
    Fallback: NYSE-Regelwerk aus kern (ohne Sonderschließungen) mit Warnung im Log."""
    von = (heute - dt.timedelta(days=100)).isoformat(); bis = (heute + dt.timedelta(days=60)).isoformat()
    try:
        tage = alp(f'/v2/calendar?start={von}&end={bis}')
        if not tage: raise RuntimeError('leere Antwort')
        return Kalender([t['date'] for t in tage], {t['date']: t['close'] for t in tage}, quelle='Alpaca /v2/calendar')
    except Exception as e:
        log(f'WARNUNG: /v2/calendar nicht lesbar ({str(e)[:80]}) – Kalender nach NYSE-Regelwerk, Sonderschließungen unbekannt')
        return Kalender.nach_regeln(von, bis)

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
    z += ['', f"Ausstiege: {[(l['strategie'], l['symbol'], g) for l, g, *_ in schliessen] or 'keine'}", '', '*Regeln und Belege: README.md. Journal: journal.csv. Log: log.txt.*']
    open('STATUS.md', 'w').write('\n'.join(z))

if __name__ == '__main__':
    main()
