#!/usr/bin/env python3
"""Systembuch-Bot v2 (Linus) – handelt NUR die belegten Regeln des Trading-Projekts auf einem Alpaca-Paper-Konto.
Live-Pfad: reines Python (Standardbibliothek), kein LLM, keine Rechenkosten. Ein Lauf pro Handelstag: Start 15:28 ET,
Entscheidung 15:45 ET (K6), alle Orders als Market-on-Close (`time_in_force=cls`), nur 10–30 Min vor Schluss.

Die Regeln (Strategien, Größen, Grenzen, Vorrang) stehen im README und in `kern.py` (reine Entscheidungslogik, dieselbe
im Replay). Diese Datei macht nur Ein-/Ausgabe: Alpaca lesen, entscheiden lassen, Orders senden, abrechnen, berichten.

Ablauf eines Laufs
  1. Uhr, Fenster, Sperren (heute schon gelaufen, gestoppt)
  2. Vorbereitung (vor dem Warten): Kalender, Konto, Positionen, Historie (SIP), Abrechnung des Vortags (Fills → Legs, FIFO),
     Journal, equity.csv, Positionsabgleich (Abweichung → kein Handel), Leihbarkeit
  3. Warten bis 15:45 ET, dann Snapshot + VIX → kern.entscheide() → kern.netto_orders()
  4. Senden: je Symbol eine MOC-Order; vor jeder Order Zustand atomar speichern (Wiederanlauf ohne Doppelorder)

Aufruf:  python3 systembuch_bot.py                    echter Lauf (nur im Fenster; wartet bis 15 Min vor Schluss)
         python3 systembuch_bot.py --dry              nichts senden, nichts buchen, Plan in STATUS-dry.md
         python3 systembuch_bot.py --dry --force      auch außerhalb des Fensters rechnen
         python3 systembuch_bot.py --dry --force --aufzeichnen tests/fixtures/alpaca_JJJJ-MM-TT.json   Eingaben einfrieren
         python3 systembuch_bot.py --replay 2010-01-01 2026-10-14   Rückrechnung (replay.py, braucht requirements-replay.txt)
Schlüssel: nur aus APCA_API_KEY_ID / APCA_API_SECRET_KEY (GitHub Secrets). Nie ausgeben, nie speichern.
Dateien: state.json (Legs, Aufträge), journal.csv (geschlossene Legs), equity.csv (Tageskurve), STATUS.md, log.txt.
"""
import argparse, csv, datetime as dt, json, os, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

import kern
from kern import (INDEX, SEKTOREN, LAENDER, TSMOM, BREMSE_DD, ALLE_SYMBOLE, IBS_FAMILIE, IBS_SCHWELLE,
                  kennzahlen, entscheide, netto_plan, netto_orders, verteile_fill, Kalender)

NY = ZoneInfo('America/New_York')
PAPER = 'https://paper-api.alpaca.markets'; DATA = 'https://data.alpaca.markets'
# Lauffenster (Studie K6, 15.10.2026): Das IBS-Signal 15 Min vor Schluss behält 91 % des Schluss-Ertrags, 30 Min vor Schluss nur 46 %.
# Der Lauf darf früh starten (Cron-Verzug bei GitHub), WARTET aber bis ENTSCHEIDUNG_MIN vor Schluss, lädt dann erst die Kurse
# und sendet die MOC-Orders sofort; Alpaca lehnt `cls` nach 15:50 ET ab, deshalb harter Abbruch unter ORDER_SPAETESTENS_MIN.
ENTSCHEIDUNG_MIN = 15.0      # Minuten vor Schluss, zu denen Kurse geladen und entschieden wird (15:45 ET)
START_FRUEHESTENS_MIN = 40.0 # Lauf darf ab hier starten und wartet (Cron 15:28 ET + Verzug)
START_SPAETESTENS_MIN = 11.5 # später gestartete Läufe handeln nicht mehr (Nachläufer-Cron 15:40 ET fängt Verzug ab)
ORDER_SPAETESTENS_MIN = 10.5 # vor jeder Order Uhr prüfen; darunter keine Orders (MOC-Annahmeschluss 15:50 ET)
ORDER_FRUEHESTENS_MIN = 30.0 # Linus' feste Regel 4: Orders nur 10–30 Min vor Schluss
STORNO_WARTEN_S = 10         # Review 1.9: Storno ist asynchron – so lange auf `canceled` warten
ENDSTATUS = ('filled', 'canceled', 'expired', 'rejected', 'done_for_day', 'replaced')
JOURNAL_SPALTEN = ['id', 'strategie', 'symbol', 'richtung', 'stueck', 'einstieg', 'einstieg_datum', 'ausstieg', 'ausstieg_datum', 'pnl', 'grund',
                   'fill_einstieg', 'fill_ausstieg', 'schluss_einstieg', 'schluss_ausstieg', 'abweichung_bp', 'rendite_bp', 'haltetage',
                   'kurs_entscheidung_ein', 'kurs_entscheidung_aus']
EQUITY_SPALTEN = ['datum', 'equity', 'bargeld', 'brutto', 'legs', 'drawdown']
ZUSTAND_NEU = dict(version=2, start=None, startkapital=None, hwm=None, legs=[], naechste_id=1, gestoppt=False, stopp_grund=None,
                   letzter_lauf=None, letzte_tsmom=None, aufgeschoben=[], auftraege=[], signale={}, signal_stat={})


class Abbruch(Exception):
    """Kontrollierter Abbruch: Titel oben in STATUS.md, Exit-Code 1 (GitHub zeigt den Lauf rot)."""

    def __init__(self, titel, text):
        super().__init__(f'{titel}: {text}'); self.titel = titel; self.text = text


AUSGABE = dict(schreiben=True, status='STATUS.md')   # Dry-Lauf: nichts außer STATUS-dry.md schreiben (Review 5.7/6.8)
LOGZEILEN = []


# ---------- Infrastruktur ----------
def log(msg):
    line = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line); LOGZEILEN.append(line)
    if AUSGABE['schreiben']:
        with open('log.txt', 'a') as f: f.write(line + '\n')


def hdr():
    k, s = os.environ.get('APCA_API_KEY_ID'), os.environ.get('APCA_API_SECRET_KEY')
    if not (k and s): raise Abbruch('FEHLER', 'Alpaca-Schlüssel fehlen (APCA_API_KEY_ID / APCA_API_SECRET_KEY)')
    return {'APCA-API-KEY-ID': k, 'APCA-API-SECRET-KEY': s, 'Content-Type': 'application/json'}


def alp(path, body=None, method=None, base=PAPER, tries=5):
    """Alpaca-Aufruf mit Wiederholung bei 429/5xx/Netzfehler (Review 5.3). Fehlertexte enthalten nie die Schlüssel."""
    for i in range(tries):
        try:
            r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=hdr(), method=method)
            raw = urllib.request.urlopen(r, timeout=30).read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            txt = e.read()[:300].decode(errors='ignore')
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1: time.sleep(2 + 2 * i); continue
            raise RuntimeError(f'Alpaca {e.code} {path.split("?")[0]}: {txt}')
        except (urllib.error.URLError, TimeoutError) as e:
            if i < tries - 1: time.sleep(2 + 2 * i); continue
            raise RuntimeError(f'Alpaca nicht erreichbar ({path.split("?")[0]}): {e}')


def bars(symbols, heute, tage=420, adjustment='all'):
    """Tageskerzen (konsolidierter SIP-Feed – Review 1.3: IEX hat Lücken und zu enge Hoch/Tief) als {sym: [(date, o, h, l, c)]}.
    Der Basic-Plan erlaubt SIP-Historie, die älter als 15 Minuten ist; abgeschlossene Tage sind das immer."""
    start = (heute - dt.timedelta(days=int(tage * 1.5))).isoformat()
    out = {s: [] for s in symbols}; token = None
    while True:
        q = f'/v2/stocks/bars?symbols={",".join(symbols)}&timeframe=1Day&start={start}&limit=10000&adjustment={adjustment}&feed=sip' + (f'&page_token={token}' if token else '')
        d = alp(q, base=DATA)
        for s, rows in (d.get('bars') or {}).items():
            for b in rows: out[s].append((b['t'][:10], b['o'], b['h'], b['l'], b['c']))
        token = d.get('next_page_token')
        if not token: break
    for s in out: out[s] = sorted([r for r in out[s] if r[0] < heute.isoformat()])  # nur abgeschlossene Tage
    return out


def schlusskurse(symbole, heute, tage=40):
    """Offizielle Schlusskurse (roh, SIP) der letzten Wochen: {sym: {datum: close}} – Vergleichsmaßstab für die MOC-Fills."""
    if not symbole: return {}
    roh = bars(sorted(symbole), heute, tage=tage, adjustment='raw')
    return {s: {r[0]: r[4] for r in rows} for s, rows in roh.items()}


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
    r = urllib.request.Request(f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1d&interval=5m', headers={'User-Agent': 'Mozilla/5.0'})
    return json.load(urllib.request.urlopen(r, timeout=25))['chart']['result'][0]['meta']['regularMarketPrice']


def lade_vix():
    """→ (vix, vix3m, quelle) oder (None, None, Fehlertext)."""
    try: return yahoo_live('^VIX'), yahoo_live('^VIX3M'), 'Yahoo query1'
    except Exception as e: return None, None, f'fehlt ({str(e)[:60]})'


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


def zeit(s):
    return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))


# ---------- Dateien ----------
def laden():
    if not os.path.exists('state.json'): return json.loads(json.dumps(ZUSTAND_NEU))
    st = json.load(open('state.json'))
    if st.get('version') != 2:                                                           # v1-Zustand übernehmen
        if any(l.get('order_id') and l.get('einstieg') is None for l in st.get('legs', [])):
            raise Abbruch('ABGLEICH NÖTIG', 'state.json aus v1 mit offenen Orders – bitte von Hand gegen Alpaca prüfen')
        for k in ('offene_orders', 'tag_zaehler'): st.pop(k, None)
        for l in st.get('legs', []): l.setdefault('status', 'offen'); l.setdefault('einstieg_datum', l['datum']); l.pop('order_id', None)
    for k, v in ZUSTAND_NEU.items(): st.setdefault(k, json.loads(json.dumps(v)))
    st['version'] = 2
    return st


def speichern(st):
    """Atomar (Review 5.2): erst in eine Temp-Datei, dann os.replace – ein Abbruch hinterlässt nie eine halbe state.json."""
    if not AUSGABE['schreiben']: return
    fd, tmp = tempfile.mkstemp(prefix='.state-', suffix='.json', dir='.')
    with os.fdopen(fd, 'w') as f: json.dump(st, f, indent=1, ensure_ascii=False)
    os.replace(tmp, 'state.json')


def csv_lesen(pfad):
    if not os.path.exists(pfad): return []
    with open(pfad, newline='') as f: return list(csv.DictReader(f))


def csv_anhaengen(pfad, spalten, zeilen):
    if not AUSGABE['schreiben'] or not zeilen: return
    neu = not os.path.exists(pfad) or os.path.getsize(pfad) == 0
    if not neu:                                                                          # alte Kopfzeile (v1-Journal) → um neue Spalten erweitern
        with open(pfad, newline='') as f: alt = next(csv.reader(f), [])
        if alt != spalten:
            vorhanden = csv_lesen(pfad)
            with open(pfad, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=spalten, extrasaction='ignore'); w.writeheader(); w.writerows(vorhanden)
    with open(pfad, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=spalten, extrasaction='ignore')
        if neu: w.writeheader()
        w.writerows(zeilen)


def r2(x, n=4):
    return '' if x is None or x == '' else round(x, n)


# ---------- Abrechnung (SPEC Aufgabe 2) ----------
def journal_zeile(leg, menge, preis, p_fill, schluss, datum_aus, info, kal):
    """Eine geschlossene (Teil-)Position. abweichung_bp = Kosten der MOC-Fills gegenüber dem offiziellen Schlusskurs
    (Ein- und Ausstieg, in Richtung des Legs; positiv = teurer als der Schluss, den die Rückrechnung annimmt)."""
    ein = leg.get('einstieg'); r = leg['richtung']
    pnl = (preis - ein) * menge * r if ein and preis else None
    rend = r * (preis / ein - 1) * 1e4 if ein and preis else None
    abw = None
    if leg.get('schluss_einstieg') and schluss:
        a_ein = (leg['fill_einstieg'] / leg['schluss_einstieg'] - 1) if leg.get('fill_einstieg') else 0.0
        a_aus = (p_fill / schluss - 1) if p_fill else 0.0
        abw = r * (a_ein - a_aus) * 1e4
    return dict(id=leg['id'], strategie=leg['strategie'], symbol=leg['symbol'], richtung=r, stueck=menge, einstieg=r2(ein),
                einstieg_datum=leg.get('einstieg_datum') or leg['datum'], ausstieg=r2(preis), ausstieg_datum=datum_aus, pnl=r2(pnl, 2),
                grund=info.get('grund', ''), fill_einstieg=r2(leg.get('fill_einstieg')), fill_ausstieg=r2(p_fill),
                schluss_einstieg=r2(leg.get('schluss_einstieg')), schluss_ausstieg=r2(schluss), abweichung_bp=r2(abw, 2), rendite_bp=r2(rend, 2),
                haltetage=kal.anzahl_zwischen(leg.get('einstieg_datum') or leg['datum'], datum_aus) if kal else '',
                kurs_entscheidung_ein=r2(leg.get('kurs_entscheidung')), kurs_entscheidung_aus=r2(info.get('kurs_entscheidung')))


def abrechnen(st, heute, kal, schluss):
    """Aufträge der Vortage gegen Alpaca abrechnen: Netto-Fill je Symbol per kern.verteile_fill() auf die Legs (FIFO je Strategie).
    Einstieg/Ausstieg je Leg zum tatsächlichen Fill (intern verrechnete Teile zum offiziellen Schluss), Teilfüllungen über filled_qty
    (Review 3.7), abgelehnt/storniert = 0 Stück (Review 3.5: Ausstieg bleibt offen, Einstieg entfällt). → Journalzeilen."""
    zeilen = []; legs = {l['id']: l for l in st['legs']}; rest = []
    fills = fill_aktivitaeten(st, heute)
    for a in st['auftraege']:
        if a['datum'] >= heute: rest.append(a); continue
        F, p_fill, status = 0, None, a['status']
        if status in ('vorbereitet', 'gesendet'):
            o = order_lesen(a)
            if o is not None:
                if o['status'] not in ENDSTATUS: raise Abbruch('ABGLEICH NÖTIG', f"MOC {a['symbol']} vom {a['datum']} noch nicht abgeschlossen ({o['status']})")
                F = int(round(float(o.get('filled_qty') or 0))) * (1 if o['side'] == 'buy' else -1)
                p_fill = float(o['filled_avg_price']) if F else None
                status = o['status']
                g = fills.get(o['id'])
                if g is not None and abs(g - abs(F)) > 1e-9: log(f"WARNUNG: Fills laut /activities ({g}) ≠ filled_qty ({abs(F)}) für {a['symbol']} {a['datum']}")
            else: status = 'nicht angekommen'
        s_px = schluss.get(a['symbol'], {}).get(a['datum'])
        preis = p_fill or s_px
        if preis is None: raise Abbruch('FEHLER', f"kein Schlusskurs für {a['symbol']} am {a['datum']} – Abrechnung unmöglich")
        erledigt = verteile_fill(a['komponenten'], F)
        for k, d in zip(a['komponenten'], erledigt):
            leg = legs.get(k['leg_id'])
            if leg is None: log(f"WARNUNG: Leg {k['leg_id']} aus Auftrag {a['symbol']} {a['datum']} fehlt im Zustand"); continue
            if k['art'] == 'ein':
                if d == 0:
                    st['legs'].remove(leg); legs.pop(leg['id']); log(f"Leg {leg['id']} {leg['strategie']} {leg['symbol']} nicht eröffnet (Order {status})")
                    continue
                if d < k['menge']: log(f"Teilfüllung Leg {leg['id']} {leg['strategie']} {leg['symbol']}: {d} von {k['menge']}")
                leg.update(stueck=d, status='offen', einstieg=preis, fill_einstieg=p_fill, schluss_einstieg=s_px)
            else:
                info = leg.pop('ausstieg', None) or {}
                if d > 0:
                    zeilen.append(journal_zeile(leg, d, preis, p_fill, s_px, a['datum'], info, kal)); leg['stueck'] -= d
                if d < k['menge']:
                    leg['ausstieg_offen'] = dict(grund=info.get('grund', 'Ausstieg'), datum=a['datum'])
                    log(f"Ausstieg offen: Leg {leg['id']} {leg['strategie']} {leg['symbol']} {k['menge'] - d} Stück (Order {status}) – wird nachgeholt")
                else: leg.pop('ausstieg_offen', None)
                if leg['stueck'] <= 0: st['legs'].remove(leg); legs.pop(leg['id'])
        log(f"Abrechnung {a['symbol']} {a['datum']}: Order {a['menge']:+d} → gefüllt {F:+d} @ {p_fill} (Schluss {s_px}), {status}")
    st['auftraege'] = rest
    zeilen += stops_abrechnen(st, kal, legs)
    return zeilen


def order_lesen(a):
    """Order per id oder – wenn der Lauf vor der Antwort abbrach – per client_order_id (Review 5.2). None = nie angekommen."""
    try:
        if a.get('order_id'): return alp(f"/v2/orders/{a['order_id']}")
        return alp(f"/v2/orders:by_client_order_id?client_order_id={urllib.parse.quote(a['client_order_id'])}")
    except RuntimeError as e:
        if 'Alpaca 404' in str(e) and not a.get('order_id'): return None
        raise


def fill_aktivitaeten(st, heute):
    """GET /v2/account/activities/FILL seit dem ältesten offenen Auftrag: Summe Stück je order_id (Gegenprobe zu filled_qty)."""
    tage = [a['datum'] for a in st['auftraege'] if a['datum'] < heute and a.get('order_id')]
    if not tage: return {}
    try:
        akt = alp(f'/v2/account/activities/FILL?after={min(tage)}T00:00:00Z&direction=asc&page_size=100')
    except Exception as e:
        log(f'WARNUNG: /activities/FILL nicht lesbar ({str(e)[:80]})'); return {}
    out = {}
    for x in akt or []: out[x.get('order_id')] = out.get(x.get('order_id'), 0) + float(x.get('qty') or 0)
    return out


def stops_abrechnen(st, kal, legs):
    """BB-Stops (GTC): gefüllte Stücke journalisieren; storniert/abgelaufen → Stop neu setzen lassen (Review 3.8)."""
    zeilen = []
    for leg in list(st['legs']):
        sid = leg.get('stop_order')
        if not sid: continue
        o = alp(f'/v2/orders/{sid}')
        gef = int(round(float(o.get('filled_qty') or 0)))
        if gef > 0 and gef > leg.get('stop_gefuellt', 0):
            neu = gef - leg.get('stop_gefuellt', 0); leg['stop_gefuellt'] = gef
            datum = zeit(o['filled_at']).astimezone(NY).date().isoformat() if o.get('filled_at') else st.get('letzter_lauf')
            px = float(o['filled_avg_price'])
            zeilen.append(journal_zeile(leg, neu, px, px, leg.get('stop'), datum, dict(grund='BB Stop'), kal)); leg['stueck'] -= neu
            log(f"BB-Stop gefüllt {leg['symbol']} {neu} @ {px}")
        if o['status'] in ENDSTATUS:
            if o['status'] != 'filled': log(f"BB-Stop {leg['symbol']} {o['status']} – wird neu gesetzt")
            leg.pop('stop_order', None); leg.pop('stop_gefuellt', None)
        if leg['stueck'] <= 0: st['legs'].remove(leg); legs.pop(leg['id'], None)
    return zeilen


def positionen_lesen():
    out = {}
    for p in alp('/v2/positions'):
        q = abs(float(p['qty'])) * (-1 if p.get('side') == 'short' else 1)
        out[p['symbol']] = dict(qty=int(round(q)), vortag=float(p.get('lastday_price') or 0), wert=float(p.get('market_value') or 0))
    return out


def abgleich(legs, positionen):
    """Review 5.5: Σ Legs je Symbol gegen Alpaca-Positionen. → {sym: (soll, ist)} nur für Abweichungen."""
    soll = {}
    for l in legs: soll[l['symbol']] = soll.get(l['symbol'], 0) + l['richtung'] * l['stueck']
    ist = {s: p['qty'] for s, p in positionen.items()}
    return {s: (soll.get(s, 0), ist.get(s, 0)) for s in sorted(set(soll) | set(ist)) if soll.get(s, 0) != ist.get(s, 0)}


def equity_nachtragen(st, konto, positionen, kal, heute):
    """Tageszeile(n) in equity.csv für abgeschlossene Handelstage seit dem letzten Eintrag (SPEC Aufgabe 2).
    Vortag: Equity = Alpaca `last_equity` (Schluss), Brutto = Σ |Stück × Vortagesschluss|. Lücken (ausgefallene Läufe) aus
    /v2/account/portfolio/history (nur Equity). → Liste aller Equity-Werte ab Start (für K5)."""
    rows = csv_lesen('equity.csv'); vortag = kal.vorheriger(heute)
    letzte = rows[-1]['datum'] if rows else None
    neu = []
    if st.get('start') and vortag and vortag >= st['start'] and (letzte is None or vortag > letzte):
        try:
            ph = alp(f"/v2/account/portfolio/history?timeframe=1D&start={st['start']}&end={vortag}")
            for t, e in zip(ph.get('timestamp') or [], ph.get('equity') or []):
                d = dt.datetime.fromtimestamp(t, NY).date().isoformat()
                if e and st['start'] <= d < vortag and (letzte is None or d > letzte) and kal.ist_handelstag(d): neu.append(dict(datum=d, equity=round(e, 2)))
        except Exception as ex: log(f'WARNUNG: portfolio/history nicht lesbar ({str(ex)[:80]})')
        brutto = sum(abs(p['qty'] * p['vortag']) for p in positionen.values())
        neu.append(dict(datum=vortag, equity=round(float(konto['last_equity']), 2), bargeld=round(float(konto['cash']), 2),
                        brutto=round(brutto, 2), legs=len(st['legs'])))
    reihe = [float(r['equity']) for r in rows if r.get('equity')]
    for z in neu:
        reihe.append(float(z['equity'])); z['drawdown'] = round(1 - reihe[-1] / max(reihe), 4)
    csv_anhaengen('equity.csv', EQUITY_SPALTEN, neu)
    return reihe


def hwm_pruefen(st, reihe, eq):
    """Review 2.5: Höchststand nie nur aus state.json – auch aus equity.csv und Alpaca-Historie (state.json verloren → kein Reset)."""
    kand = [st.get('hwm') or 0, eq] + reihe
    try:
        if st.get('start'):
            ph = alp(f"/v2/account/portfolio/history?timeframe=1D&start={st['start']}")
            kand += [e for e in (ph.get('equity') or []) if e]
    except Exception as ex: log(f'WARNUNG: Höchststand nicht gegen Alpaca prüfbar ({str(ex)[:60]})')
    hwm = max(kand)
    if st.get('hwm') and hwm > st['hwm'] * 1.0001: log(f"Höchststand aus Kontohistorie korrigiert: {st['hwm']:,.0f} → {hwm:,.0f}")
    return hwm


def signale_auswerten(st, hist):
    """Review §8 Aufgabe 2 / K6: IBS zur Entscheidung (15:45) gegen IBS der fertigen Tageskerze – Anteil gekippter Signale je Gruppe."""
    gruppen = dict(IBS=INDEX, IBS_SEKTOR=SEKTOREN, IBS_LAND=LAENDER)
    for datum in sorted(list(st['signale'])):
        ent = st['signale'][datum]; fertig = {}
        for s in ent:
            r = next((r for r in hist.get(s, []) if r[0] == datum), None)
            if r and r[2] > r[3]: fertig[s] = (r[4] - r[3]) / (r[2] - r[3])
        if not fertig: continue
        for g, syms in gruppen.items():
            n, gek, verp = st['signal_stat'].get(g, [0, 0, 0])
            for s in syms:
                if s not in ent or s not in fertig: continue
                a, b = ent[s] < IBS_SCHWELLE, fertig[s] < IBS_SCHWELLE
                n += a; gek += a and not b; verp += b and not a
            st['signal_stat'][g] = [n, gek, verp]
        del st['signale'][datum]


# ---------- Senden ----------
def minuten_bis_schluss_jetzt(uhr):
    """Uhr aus /v2/clock plus lokal vergangene Zeit (keine Extra-Aufrufe in der Orderschleife)."""
    return (uhr['schluss'] - uhr['jetzt']).total_seconds() / 60 - (time.monotonic() - uhr['mono']) / 60


def stornieren(sym, offene, nicht=()):
    """Alle offenen Orders im Symbol stornieren und auf `canceled` warten (Review 1.8/1.9). → (ok, stornierte Orders)."""
    weg = []
    for o in [o for o in offene if o['symbol'] == sym and o['id'] not in nicht]:
        try: alp(f"/v2/orders/{o['id']}", method='DELETE')
        except Exception as e: log(f"Storno {sym} {o['id']} fehlgeschlagen: {str(e)[:100]}"); return False, weg
        ende = time.monotonic() + STORNO_WARTEN_S
        while True:
            z = alp(f"/v2/orders/{o['id']}")
            if z['status'] in ENDSTATUS: break
            if time.monotonic() > ende: log(f'Storno {sym} nicht bestätigt ({z["status"]}) – Symbol heute ausgelassen'); return False, weg
            time.sleep(0.5)
        if z['status'] == 'filled' or float(z.get('filled_qty') or 0) > 0:
            log(f'{sym}: Order {o["id"]} wurde gerade gefüllt – Bestand geändert, Symbol heute ausgelassen'); return False, weg
        weg.append(o); offene.remove(o)
    return True, weg


def moc_senden(sym, menge, cid):
    """Eine MOC-Order. Kein blindes Wiederholen (Doppelorder!): bei Netzfehler per client_order_id nachsehen."""
    body = dict(symbol=sym, qty=str(abs(menge)), side='buy' if menge > 0 else 'sell', type='market', time_in_force='cls', client_order_id=cid)
    try: return alp('/v2/orders', body, 'POST', tries=1)
    except RuntimeError as e:
        if 'Alpaca 4' in str(e) and 'Alpaca 429' not in str(e): raise                  # fachlich abgelehnt (403/422 …)
        try: return alp(f'/v2/orders:by_client_order_id?client_order_id={urllib.parse.quote(cid)}')
        except Exception: raise e


def stop_setzen(leg):
    stop = round(leg['einstieg'] - kern.BB_STOP_ATR * leg['atr20'], 2)
    try:
        o = alp('/v2/orders', dict(symbol=leg['symbol'], qty=str(leg['stueck']), side='sell', type='stop', stop_price=f'{stop:.2f}', time_in_force='gtc'), 'POST', tries=1)
        leg['stop_order'] = o['id']; leg['stop'] = stop; leg.pop('stop_gefuellt', None); log(f"BB-Stop {leg['symbol']} {leg['stueck']} @ {stop}")
        return True
    except Exception as e:
        log(f"WARNUNG: BB-Stop {leg['symbol']} nicht gesetzt ({str(e)[:120]}) – nächster Lauf versucht es erneut"); return False


def senden(st, heute, kz, ausstiege, einstiege, orders, uhr, offene):
    """Je Symbol: Auftrag vorbereiten + Zustand speichern → offene Orders stornieren → MOC senden → Zustand speichern.
    → Liste Fehlertexte (abgelehnte/ausgelassene Symbole)."""
    fehler = []; nr = 0; symbole = []
    for x in [a[0] for a in ausstiege] + einstiege:
        if x['symbol'] not in symbole: symbole.append(x['symbol'])
    gestoppt_neu = []                                                                    # BB-Legs, deren Stop für die MOC storniert wurde
    for s in symbole:
        m = minuten_bis_schluss_jetzt(uhr)
        if not (ORDER_SPAETESTENS_MIN <= m <= ORDER_FRUEHESTENS_MIN):
            fehler.append(f'{s}: nicht gesendet, {m:.1f} Min bis Schluss (erlaubt {ORDER_SPAETESTENS_MIN}–{ORDER_FRUEHESTENS_MIN})'); continue
        aus_s = [a for a in ausstiege if a[0]['symbol'] == s]; ein_s = [l for l in einstiege if l['symbol'] == s]
        d = orders.get(s, 0); cid = f'sb-{heute}-{s}'
        komps = []
        for leg, grund, menge in aus_s:
            komps.append(dict(art='aus', leg_id=leg['id'], menge=menge, seite=-leg['richtung'], strategie=leg['strategie']))
            leg['ausstieg'] = dict(grund=grund, datum=heute, menge=menge, kurs_entscheidung=kz.get(s, {}).get('px'), auftrag=cid)
        for leg in ein_s:
            leg.update(id=st['naechste_id'], status='pending', einstieg_datum=heute, kurs_entscheidung=kz[s]['px']); st['naechste_id'] += 1
            komps.append(dict(art='ein', leg_id=leg['id'], menge=leg['stueck'], seite=leg['richtung'], strategie=leg['strategie'], nr=nr)); nr += 1
            st['legs'].append(leg)
        a = dict(datum=heute, symbol=s, menge=d, client_order_id=cid if d else None, order_id=None, status='vorbereitet' if d else 'intern', komponenten=komps)
        st['auftraege'].append(a); speichern(st)
        if d == 0: log(f'{s}: Wechsel innerhalb des Symbols, keine Order (intern zum Schluss verrechnet)'); continue
        ok, weg = stornieren(s, offene)
        aus_ids = {l['id'] for l, _, _ in aus_s}
        for o in weg:
            for leg in st['legs']:
                if leg.get('stop_order') == o['id']:
                    leg.pop('stop_order', None)
                    if leg['id'] not in aus_ids: gestoppt_neu.append(leg)
        if not ok:
            a['status'] = 'abgelehnt'; a['grund'] = 'offene Order im Symbol nicht stornierbar'; speichern(st)
            fehler.append(f'{s}: offene Order nicht stornierbar – heute keine MOC'); continue
        try:
            o = moc_senden(s, d, cid); a.update(order_id=o['id'], status='gesendet')
            log(f"MOC {'buy' if d > 0 else 'sell'} {abs(d)} {s} → {o['id']} ({minuten_bis_schluss_jetzt(uhr):.1f} Min vor Schluss)")
        except Exception as e:
            a.update(status='abgelehnt', grund=str(e)[:200]); fehler.append(f'{s} {d:+d}: {str(e)[:160]}'); log(f'Order {s} {d:+d} ABGELEHNT: {str(e)[:160]}')
        speichern(st)
    for leg in gestoppt_neu:                                                             # Stops der bleibenden BB-Legs wieder setzen
        if leg in st['legs'] and leg.get('einstieg'): stop_setzen(leg)
    speichern(st)
    return fehler


# ---------- Hauptlauf ----------
def argumente(argv=None):
    ap = argparse.ArgumentParser(description='Systembuch-Bot v2')
    ap.add_argument('--dry', action='store_true', help='nichts senden, nichts buchen; Plan in STATUS-dry.md')
    ap.add_argument('--force', action='store_true', help='nur mit --dry: auch außerhalb des Fensters rechnen')
    ap.add_argument('--aufzeichnen', metavar='PFAD', help='Eingaben des Laufs als Test-Fixture speichern')
    ap.add_argument('--replay', nargs=2, metavar=('START', 'ENDE'), help='Rückrechnung, siehe replay.py')
    a, rest = ap.parse_known_args(argv)
    a.rest = rest
    return a


def main(argv=None):
    a = argumente(argv)
    if a.replay:
        import replay
        return replay.main([*a.replay, *a.rest])
    if a.rest: raise SystemExit(f'unbekannte Optionen: {a.rest}')
    if a.force and not a.dry: raise SystemExit('--force nur zusammen mit --dry (Orders nur im Fenster 10–30 Min vor Schluss)')
    AUSGABE.update(schreiben=not a.dry, status='STATUS-dry.md' if a.dry else 'STATUS.md'); LOGZEILEN.clear()
    try:
        return lauf(a)
    except Abbruch as e:
        log(f'{e.titel}: {e.text}'); status_fehler(e.titel, e.text); sys.exit(1)
    except Exception as e:
        import traceback
        log(f'FEHLER: {type(e).__name__}: {str(e)[:300]}'); print(traceback.format_exc()[-2000:])
        status_fehler('FEHLER', f'{type(e).__name__}: {str(e)[:300]}'); sys.exit(1)


def lauf(a):
    st = laden()
    clock = alp('/v2/clock'); jetzt = zeit(clock['timestamp']); heute_d = jetzt.astimezone(NY).date(); heute = heute_d.isoformat()
    naechster_schluss = zeit(clock['next_close']); min_bis_schluss = (naechster_schluss - jetzt).total_seconds() / 60
    if not clock['is_open'] or not (START_SPAETESTENS_MIN <= min_bis_schluss <= START_FRUEHESTENS_MIN):
        if not a.force:
            print(f'kein Fenster (offen={clock["is_open"]}, {min_bis_schluss:.1f} Min bis Schluss) – Ende'); return dict(ende='kein Fenster')
        log(f'--force: außerhalb des Fensters ({min_bis_schluss:.1f} Min bis Schluss)')
    if st.get('letzter_lauf') == heute and not a.force:
        log('heute schon gelaufen – Ende'); return dict(ende='schon gelaufen')
    if st.get('gestoppt'):
        log(f"GESTOPPT ({st.get('stopp_grund')}) – kein Handel, bis eine Sitzung mit Linus entscheidet (state.json: gestoppt=false)")
        status_gestoppt(st); return dict(ende='gestoppt')

    # 2) Vorbereitung vor dem Warten (alles, was sich bis zum Schluss nicht mehr ändert)
    kal = lade_kalender(heute_d)
    hist = bars(list(ALLE_SYMBOLE), heute_d)
    offen_symbole = {x['symbol'] for x in st['auftraege']} | {l['symbol'] for l in st['legs'] if l.get('stop_order')}
    aelteste = min([x['datum'] for x in st['auftraege']] + [heute])
    tage_zurueck = (heute_d - dt.date.fromisoformat(aelteste)).days + 10
    zeilen = abrechnen(st, heute, kal, schlusskurse(offen_symbole, heute_d, tage=tage_zurueck) if offen_symbole else {})
    signale_auswerten(st, hist)
    konto = alp('/v2/account'); positionen = positionen_lesen()
    csv_anhaengen('journal.csv', JOURNAL_SPALTEN, zeilen)
    reihe = equity_nachtragen(st, konto, positionen, kal, heute)
    differenz = abgleich(st['legs'], positionen)
    if differenz:
        text = 'Legs ≠ Alpaca-Positionen: ' + ', '.join(f'{s} Legs {a_} / Alpaca {b_}' for s, (a_, b_) in differenz.items())
        if not a.dry: speichern(st); raise Abbruch('ABGLEICH NÖTIG', text + ' – kein Handel, bitte prüfen')
        log(f'ABGLEICH NÖTIG (dry: rechne trotzdem weiter): {text}')
    leihbar = {}
    for s in TSMOM:
        try: leihbar[s] = bool(alp(f'/v2/assets/{s}').get('shortable', False))
        except Exception: leihbar[s] = False
    offene = [o for o in alp('/v2/orders?status=open&limit=500') or []] if not a.dry else []
    for leg in st['legs']:                                                               # Stops für BB-Legs mit bekanntem Einstieg
        if leg['strategie'] == 'BB' and leg.get('einstieg') and leg.get('status') == 'offen' and not leg.get('stop_order') and not a.dry:
            if stop_setzen(leg): offene.append(dict(id=leg['stop_order'], symbol=leg['symbol']))
    speichern(st)

    # 3) K6: bis ENTSCHEIDUNG_MIN vor Schluss warten, erst dann Kurse laden (Signal so nah am Schluss wie Alpaca erlaubt)
    if clock['is_open'] and min_bis_schluss > ENTSCHEIDUNG_MIN and not a.force:
        warte = (min_bis_schluss - ENTSCHEIDUNG_MIN) * 60
        log(f'warte {warte / 60:.1f} Min bis {ENTSCHEIDUNG_MIN:.0f} Min vor Schluss (K6-Fenster)'); time.sleep(warte)
    clock = alp('/v2/clock'); uhr = dict(jetzt=zeit(clock['timestamp']), schluss=naechster_schluss, mono=time.monotonic())
    entscheidung_zeit = uhr['jetzt'].astimezone(NY).strftime('%H:%M:%S')

    konto = alp('/v2/account'); eq = float(konto['equity'])
    if st['startkapital'] is None: st.update(start=heute, startkapital=eq, hwm=eq, letzte_tsmom=heute)
    st['hwm'] = hwm_pruefen(st, reihe, eq); dd = 1 - eq / st['hwm']
    live = snapshots(list(ALLE_SYMBOLE))
    vix, vix3m, vix_quelle = lade_vix()
    kurse = dict(live)
    if vix and vix3m: kurse['^VIX'] = {'px': vix}; kurse['^VIX3M'] = {'px': vix3m}
    else: log(f'VIX nicht lesbar: {vix_quelle}')
    if a.aufzeichnen: aufzeichnen(a.aufzeichnen, heute, clock, eq, st, hist, live, vix, vix3m, leihbar)
    kz = kennzahlen(hist, live)
    for leg in st['legs']:
        if leg['symbol'] not in kz: log(f"WARNUNG: kein Kurs für offenes Leg {leg['id']} {leg['strategie']} {leg['symbol']}")
    zustand = dict(heute=heute, equity=eq, hwm=st['hwm'], legs=st['legs'], leihbar=leihbar, letzte_tsmom=st.get('letzte_tsmom'),
                   aufgeschoben=st.get('aufgeschoben', []))
    schliessen, neu, info = entscheide(zustand, kurse, hist, kal, kz=kz)
    ratio = info['ratio']
    for z in info['log']: log(z)
    log(f'Lauf {heute} {entscheidung_zeit} ET – Equity {eq:,.0f} $, Höchststand {st["hwm"]:,.0f}, Drawdown {dd:.1%}, Größenfaktor {info["faktor"]}')
    log(f'Signale: MW-Kauf {info["mw_kauf"]}, MW-Verkauf {info["mw_verkauf"]}, TSMOM {info["tsmom_tag"]}, VIX3M/VIX {ratio and round(ratio, 3)} ({vix_quelle})')

    # Not-Aus: alles per MOC glatt (Regel 4: nur MOC im Fenster, kein DELETE /v2/positions mehr)
    if kern.notaus(eq, st['startkapital']):
        log(f'NOT-AUS: Equity {eq:,.0f} < 70 % von {st["startkapital"]:,.0f} – alle Legs per MOC glatt, Bot stoppt')
        schliessen = [(l, 'NOT-AUS') for l in st['legs']]; neu = []; st.update(gestoppt=True, stopp_grund='Not-Aus')
    roh = netto_plan(schliessen, neu)
    no = netto_orders(st['legs'], schliessen, neu)                                     # Review 3.2: nie durch null in einem Tag
    plan = no['orders']
    for s in no['gekreuzt']: log(f'{s}: Vorzeichenwechsel – heute nur bis null ({roh.get(s, 0):+d} → {plan.get(s, 0):+d}), Rest nachholen/verfallen')
    for x in no['verfallen']: log(f"verfällt (Vorzeichenwechsel): {x['strategie']} {x['symbol']} {x['richtung'] * x['stueck']:+d}")
    for x in no['aufgeschoben']: log(f"aufgeschoben auf den nächsten Lauf: {x['strategie']} {x['symbol']} {x['richtung'] * x['stueck']:+d}")
    log(f'Ausstiege: {[(l["strategie"], l["symbol"], g, m) for l, g, m in no["ausstiege"]]}')
    log(f'Einstiege: {[(l["strategie"], l["symbol"], l["richtung"] * l["stueck"]) for l in no["einstiege"]]}')
    log(f'Netto-MOC-Orders: {plan}')
    ergebnis = dict(roh=roh, plan=plan, gekreuzt=no['gekreuzt'], aufgeschoben=no['aufgeschoben'], verfallen=no['verfallen'],
                    ausstiege=no['ausstiege'], einstiege=no['einstiege'], info=info, fehler=[])
    lauf_info = dict(entscheidung=entscheidung_zeit, min_entscheidung=minuten_bis_schluss_jetzt(uhr), vix_quelle=vix_quelle, kalender=kal.quelle)
    if a.dry:
        status_md(st, eq, dd, kz, ratio, plan, no['ausstiege'], no['einstiege'], heute, kal, lauf_info, dry=True); return ergebnis

    # 4) Senden (Uhr erneut lesen: Alpaca lehnt MOC nach 15:50 ET ab – lieber kein Handel als abgelehnte Orders)
    clock2 = alp('/v2/clock'); uhr = dict(jetzt=zeit(clock2['timestamp']), schluss=naechster_schluss, mono=time.monotonic())
    rest = minuten_bis_schluss_jetzt(uhr)
    if not clock2['is_open'] or not (ORDER_SPAETESTENS_MIN <= rest <= ORDER_FRUEHESTENS_MIN):
        raise Abbruch('ZU SPÄT', f'{rest:.1f} Min bis Schluss (erlaubt {ORDER_SPAETESTENS_MIN}–{ORDER_FRUEHESTENS_MIN}) – keine Orders gesendet, nichts gebucht')
    for l in st['legs']:
        if l.get('id') in info['datum_neu']: l['datum'] = info['datum_neu'][l['id']]       # Folgesignal: halten, Tag neu zählen
    st['letzter_lauf'] = heute                                                           # vor der ersten Order: Nachläufer handelt nicht doppelt
    st['aufgeschoben'] = no['aufgeschoben']
    if info['tsmom_tag']: st['letzte_tsmom'] = heute
    st['signale'][heute] = {s: round(kz[s]['ibs'], 4) for s in INDEX + SEKTOREN + LAENDER if s in kz}
    lauf_info['min_senden'] = rest
    fehler = senden(st, heute, kz, no['ausstiege'], no['einstiege'], plan, uhr, offene)
    st['letzter_lauf_info'] = lauf_info; speichern(st)
    ergebnis['fehler'] = fehler
    status_md(st, eq, dd, kz, ratio, plan, no['ausstiege'], [], heute, kal, lauf_info, fehler=fehler)
    if fehler: raise Abbruch('ORDER ABGELEHNT', '; '.join(fehler))
    return ergebnis


def aufzeichnen(pfad, heute, clock, eq, st, hist, live, vix, vix3m, leihbar):
    """Eingaben eines (Dry-)Laufs als Fixture im Format von tests/fixtures/ (SPEC Aufgabe 1)."""
    fx = dict(name=os.path.basename(pfad)[:-5], beschreibung='aufgezeichneter Alpaca-Lauf', quelle='Alpaca SIP/IEX', heute=heute,
              clock=clock, equity=eq, state=st, hist={s: [list(r) for r in rows[-270:]] for s, rows in hist.items()}, live=live,
              vix=vix, vix3m=vix3m, leihbar=leihbar)
    with open(pfad, 'w') as f: json.dump(fx, f, separators=(',', ':'))
    print(f'Fixture gespeichert: {pfad}')


# ---------- Berichte ----------
def status_schreiben(zeilen):
    with open(AUSGABE['status'], 'w') as f: f.write('\n'.join(zeilen) + '\n')


def status_fehler(titel, text):
    status_schreiben([f'# {titel}', '', f'**{text}**', '', f"Stand {dt.datetime.now(NY):%Y-%m-%d %H:%M} ET. Kein weiterer Handel in diesem Lauf.",
                      '', '## Letzte Logzeilen', '```', *LOGZEILEN[-15:], '```'])


def status_gestoppt(st):
    status_schreiben([f"# GESTOPPT – {st.get('stopp_grund')}", '', 'Kein Handel. Wieder einschalten nur nach Sitzung mit Linus: in state.json `gestoppt` auf false.'])


def status_md(st, eq, dd, kz, ratio, plan, ausstiege, neu, heute, kal, lauf_info, dry=False, fehler=()):
    z = [f"# Systembuch-Bot – Stand {heute} {'(DRY RUN)' if dry else ''}", '']
    if fehler: z += ['**ORDER ABGELEHNT:** ' + '; '.join(fehler), '']
    z += [f"Equity **{eq:,.0f} $** · Start {st.get('startkapital') or eq:,.0f} $ · Höchststand {st.get('hwm') or eq:,.0f} $ · Drawdown {dd:.1%}{' · BREMSE' if dd >= BREMSE_DD else ''}",
          f"Entscheidung {lauf_info.get('entscheidung')} ET · Senden {lauf_info.get('min_senden', 0):.1f} Min vor Schluss · VIX3M/VIX {ratio and round(ratio, 3)} ({lauf_info.get('vix_quelle')}) · Kalender {lauf_info.get('kalender')}",
          f"Netto-Orders heute: {plan or 'keine'}", '',
          '| Leg | Strategie | Symbol | Richtung | Stück | Einstieg | seit | Stop | Status |', '|---|---|---|---|---|---|---|---|---|']
    for l in st['legs']:
        z.append(f"| {l['id']} | {l['strategie']} | {l['symbol']} | {'long' if l['richtung'] > 0 else 'short'} | {l['stueck']} | {l.get('einstieg') or 'MOC offen'} | {l['datum']} | {l.get('stop', '')} | {'Ausstieg MOC heute' if l.get('ausstieg') else l.get('status', '')} |")
    for l in neu: z.append(f"| neu | {l['strategie']} | {l['symbol']} | {'long' if l['richtung'] > 0 else 'short'} | {l['stueck']} | MOC heute | {l['datum']} | | geplant |")
    z += ['', '## Signale heute', '| ETF | Kurs | IBS | SMA200 | BB unten | Signal |', '|---|---|---|---|---|---|']
    for s in INDEX + SEKTOREN + LAENDER:
        k = kz.get(s)
        if not k: continue
        sig = ('IBS ' if k['ibs'] < 0.2 else '') + ('BB ' if kern.ist_bb_signal(k) else '')
        z.append(f"| {s} | {k['px']:.2f} | {k['ibs']:.2f} | {k['sma200'] and round(k['sma200'], 2)} | {k['bb_unten']:.2f} | {sig} |")
    z += ['', f"Ausstiege: {[(l['strategie'], l['symbol'], g) for l, g, *_ in ausstiege] or 'keine'}", '', '*Regeln und Belege: README.md. Journal: journal.csv. Log: log.txt.*']
    status_schreiben(z)


if __name__ == '__main__':
    main()
