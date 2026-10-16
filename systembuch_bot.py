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
import argparse, csv, datetime as dt, http.client, json, os, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
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
# Vorzeichenwechsel (Review 3.2): 'beide' = an einem Tag nie durch null. Paper-Prüfungen 16.10.2026: long → short in einer Order und
# short → long mit zwei Kauf-MOC-Orders lehnt Alpaca ab („insufficient qty available“) → 'beide' ist nötig. 'verkauf' (nur long → short
# sperren) bleibt als Schalter für den Fall, dass Alpaca das Verhalten ändert (Replay: ≈ +1,9 Punkte p.a.).
VORZEICHENWECHSEL_SPERRE = 'beide'
ENDSTATUS = ('filled', 'canceled', 'expired', 'rejected', 'done_for_day', 'replaced')
JOURNAL_SPALTEN = ['id', 'strategie', 'symbol', 'richtung', 'stueck', 'einstieg', 'einstieg_datum', 'ausstieg', 'ausstieg_datum', 'pnl', 'grund',
                   'fill_einstieg', 'fill_ausstieg', 'schluss_einstieg', 'schluss_ausstieg', 'abweichung_bp', 'rendite_bp', 'haltetage',
                   'kurs_entscheidung_ein', 'kurs_entscheidung_aus']
EQUITY_SPALTEN = ['datum', 'equity', 'bargeld', 'brutto', 'legs', 'drawdown']
ZUSTAND_NEU = dict(version=2, start=None, startkapital=None, hwm=None, legs=[], naechste_id=1, gestoppt=False, stopp_grund=None,
                   letzter_lauf=None, letzte_tsmom=None, aufgeschoben=[], auftraege=[], signale={}, signal_stat={})


class Abbruch(Exception):
    """Kontrollierter Abbruch: Titel oben in STATUS.md, Exit-Code 1 (GitHub zeigt den Lauf rot)."""

    def __init__(self, titel, text, status_steht=False):
        super().__init__(f'{titel}: {text}'); self.titel = titel; self.text = text; self.status_steht = status_steht


AUSGABE = dict(schreiben=True, status='STATUS.md')   # Dry-Lauf: nichts außer STATUS-dry.md schreiben (Review 5.7/6.8)
LOGZEILEN = []; WARNUNGEN = []
VIX_ALARM_LAEUFE = 3         # Review §8: Alarm, wenn drei Läufe in Folge ohne VIX


# ---------- Infrastruktur ----------
def geheimnisse():
    out = set()
    for n in ('APCA_API_KEY_ID', 'APCA_API_SECRET_KEY'):
        v = os.environ.get(n) or ''
        out |= {v, v.strip()}
    return [g for g in out if len(g) >= 6]


def schwaerzen(text):
    """Schlüsselwerte nie ausgeben – auch nicht in Fehlermeldungen fremder Bibliotheken (Review v2: Header-ValueError)."""
    text = str(text)
    for g in geheimnisse(): text = text.replace(g, '***')
    return text


def log(msg):
    msg = schwaerzen(msg)
    line = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line); LOGZEILEN.append(line)
    if msg.startswith('WARNUNG'): WARNUNGEN.append(msg[9:])
    if AUSGABE['schreiben']:
        with open('log.txt', 'a') as f: f.write(line + '\n')


def hdr():
    k, s = (os.environ.get('APCA_API_KEY_ID') or '').strip(), (os.environ.get('APCA_API_SECRET_KEY') or '').strip()
    if not (k and s): raise Abbruch('FEHLER', 'Alpaca-Schlüssel fehlen (APCA_API_KEY_ID / APCA_API_SECRET_KEY)')
    if not all(33 <= ord(c) <= 126 for c in k + s): raise Abbruch('FEHLER', 'Alpaca-Schlüssel enthält Leer- oder Sonderzeichen – Secret neu eintragen')
    return {'APCA-API-KEY-ID': k, 'APCA-API-SECRET-KEY': s, 'Content-Type': 'application/json'}


class Abgelehnt(RuntimeError):
    """Alpaca hat fachlich abgelehnt (4xx außer 404/429) – die Order existiert sicher nicht."""


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
            fehler = Abgelehnt if 400 <= e.code < 500 and e.code not in (404, 408, 429) else RuntimeError
            raise fehler(f'Alpaca {e.code} {path.split("?")[0]}: {txt}')
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, OSError) as e:      # auch Verbindungsabbruch nach dem Senden
            if i < tries - 1: time.sleep(2 + 2 * i); continue
            raise RuntimeError(f'Alpaca nicht erreichbar ({path.split("?")[0]}): {type(e).__name__} {schwaerzen(e)[:120]}')


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
    return snapshot_zusammenfuehren(iex, sip, dt.datetime.now(NY).date().isoformat())


def _ny_datum(t):
    try: return zeit(t).astimezone(NY).date().isoformat()
    except Exception: return None


def snapshot_zusammenfuehren(iex, sip, heute=None):
    """Jüngster Trade als Kurs, Hoch/Tief aus beiden Tageskerzen. Werte, deren Zeitstempel nicht von heute (New York) ist,
    werden verworfen (Review v2: sonst mischt ein ETF ohne heutigen Trade Vortageswerte ins IBS)."""
    out = {}
    heute_ok = lambda x: heute is None or not x.get('t') or _ny_datum(x['t']) == heute
    for s in set(iex) | set(sip):
        vi, vs = iex.get(s) or {}, sip.get(s) or {}
        trades = [t for t in ((vi.get('latestTrade') or {}), (vs.get('latestTrade') or {})) if t.get('p') and heute_ok(t)]
        kandidaten = [(t.get('t') or '', float(t['p'])) for t in trades]
        px = max(kandidaten)[1] if kandidaten else None                                   # jüngster Trade gewinnt
        q = vi.get('latestQuote') or {}
        if px is None and q.get('ap') and q.get('bp') and heute_ok(q): px = (float(q['ap']) + float(q['bp'])) / 2
        if px is None:
            if heute is not None and (vi or vs): log(f'WARNUNG: {s} ohne Kurs von heute – heute kein Signal/Ausstieg in {s}')
            continue
        bars_ = [b for b in ((vi.get('dailyBar') or {}), (vs.get('dailyBar') or {})) if heute_ok(b)]
        his = [float(b['h']) for b in bars_ if b.get('h')]; los = [float(b['l']) for b in bars_ if b.get('l')]
        out[s] = dict(px=px, hi=max(his + [px]), lo=min(los + [px]))
    return out


def yahoo_live(sym, host='query1'):
    r = urllib.request.Request(f'https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=1d&interval=5m', headers={'User-Agent': 'Mozilla/5.0'})
    return float(json.load(urllib.request.urlopen(r, timeout=20))['chart']['result'][0]['meta']['regularMarketPrice'])


def cboe_live(sym):
    """CBOE-Kursseite (15 Min verzögert): cdn.cboe.com/api/global/delayed_quotes/quotes/_VIX.json."""
    r = urllib.request.Request(f'https://cdn.cboe.com/api/global/delayed_quotes/quotes/_{sym.lstrip("^")}.json', headers={'User-Agent': 'Mozilla/5.0'})
    return float(json.load(urllib.request.urlopen(r, timeout=20))['data']['current_price'])


VIX_QUELLEN = (('Yahoo query1', lambda s: yahoo_live(s, 'query1')), ('Yahoo query2', lambda s: yahoo_live(s, 'query2')),
               ('CBOE (15 Min verzögert)', cboe_live))


def lade_vix():
    """VIX und VIX3M aus derselben Quelle (Review 4.5: GitHub-IPs bekommen von Yahoo oft 429). → (vix, vix3m, quelle) oder (None, None, Fehlertext)."""
    fehler = []
    for name, f in VIX_QUELLEN:
        try:
            v, v3 = f('^VIX'), f('^VIX3M')
            if v > 0 and v3 > 0: return v, v3, name
        except Exception as e: fehler.append(f'{name}: {str(e)[:40]}')
    return None, None, 'fehlt (' + '; '.join(fehler) + ')'


def lade_kalender(heute, aeltestes=None):
    """Handelstage mit Schlusszeit aus GET /v2/calendar (Review 1.11/1.12: keine Feiertagstabelle mehr, Halbtage erkannt).
    Reicht bis zum ältesten offenen Leg zurück (Haltetage, BB-Alter). Fallback: NYSE-Regelwerk (ohne Sonderschließungen)."""
    von = min((heute - dt.timedelta(days=100)).isoformat(), aeltestes or '9999'); bis = (heute + dt.timedelta(days=60)).isoformat()
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
    for l in st.get('legs', []):                                                         # v1 (23:15) vermerkt ausstieg_offen als Datum
        if isinstance(l.get('ausstieg_offen'), str): l['ausstieg_offen'] = dict(grund='Ausstieg', datum=l['ausstieg_offen'])
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


def journal_anhaengen(zeilen):
    """Idempotent: eine Zeile (Leg, Ausstiegstag, Stück, Grund) steht höchstens einmal im Journal – auch wenn ein Lauf nach dem
    Schreiben, aber vor dem Speichern von state.json abbricht und der nächste Lauf dieselben Aufträge noch einmal abrechnet."""
    schluessel = lambda z: (str(z['id']), str(z['ausstieg_datum']), str(z['stueck']), str(z['grund']))
    da = {schluessel(z) for z in csv_lesen('journal.csv')}
    neu = [z for z in zeilen if schluessel(z) not in da]
    if len(neu) < len(zeilen): log(f'{len(zeilen) - len(neu)} Journalzeile(n) standen schon im Journal – nicht doppelt geschrieben')
    csv_anhaengen('journal.csv', JOURNAL_SPALTEN, neu)


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
    zeilen += stops_abrechnen(st, kal, legs)                                              # zuerst: ein Stop kann vor der MOC gefüllt haben
    fills = fill_aktivitaeten(st, heute)
    for a in st['auftraege']:
        if a['datum'] >= heute: rest.append(a); continue
        F, p_fill, status = 0, None, a['status']
        wert = 0.0
        for teil in [x for x in (a, a.get('zweite')) if x and x.get('client_order_id')]:   # auch 'abgelehnt': nachsehen, ob doch angekommen
            o = order_lesen(teil)
            if o is None: status = 'nicht angekommen' if teil is a else status; continue
            if o['status'] not in ENDSTATUS: raise Abbruch('ABGLEICH NÖTIG', f"MOC {a['symbol']} vom {a['datum']} noch nicht abgeschlossen ({o['status']})")
            f = int(round(float(o.get('filled_qty') or 0))) * (1 if o['side'] == 'buy' else -1)
            F += f; wert += abs(f) * float(o['filled_avg_price'] or 0) if f else 0.0
            status = o['status'] if teil is a else f"{status}/{o['status']}"
            g = fills.get(o['id'])
            if g is not None and abs(g - abs(f)) > 1e-9: log(f"WARNUNG: Fills laut /activities ({g}) ≠ filled_qty ({abs(f)}) für {a['symbol']} {a['datum']}")
        p_fill = wert / abs(F) if F else None
        s_px = schluss.get(a['symbol'], {}).get(a['datum'])
        preis = p_fill or s_px
        if preis is None: raise Abbruch('FEHLER', f"kein Schlusskurs für {a['symbol']} am {a['datum']} – Abrechnung unmöglich")
        komps = []
        for k in a['komponenten']:                                                       # Ausstieg nie größer als der Restbestand (Stop gefüllt)
            leg = legs.get(k['leg_id'])
            komps.append(dict(k, menge=min(k['menge'], leg['stueck']) if leg else 0) if k['art'] == 'aus' else k)
        if a['menge'] and not F:                                                         # Order nicht ausgeführt (abgelehnt, nie angekommen, ohne Fill
            erledigt = intern = [0] * len(komps)                                         # storniert): Symbol bleibt unverändert, auch der intern
        else:                                                                            # verrechenbare Teil (wie v1 seit 15.10. 23:15, Review 3.5)
            erledigt = verteile_fill(komps, F)
            intern = verteile_fill(komps, 0)                                            # ohne Börse erledigt (Kauf gegen Verkauf im Symbol)
        for k, d, d0 in zip(komps, erledigt, intern):
            d0 = min(d0, d); boerse = d - d0
            # Preis je Komponente: intern Verrechnetes zum offiziellen Schluss, über die Börse Gehandeltes zum Fill
            preis = ((boerse * p_fill if p_fill else boerse * (s_px or 0)) + d0 * (s_px or p_fill or 0)) / d if d else (p_fill or s_px)
            fill_k = preis if boerse > 0 and p_fill else None
            leg = legs.get(k['leg_id'])
            if leg is None: log(f"WARNUNG: Leg {k['leg_id']} aus Auftrag {a['symbol']} {a['datum']} fehlt im Zustand"); continue
            if k['art'] == 'ein':
                if d < k['menge'] and leg['strategie'] in kern.MEHRTAGIG and not st.get('gestoppt'):   # Rest mehrtägiger Strategien nachholen
                    st['aufgeschoben'].append(dict(strategie=leg['strategie'], symbol=leg['symbol'], richtung=leg['richtung'], stueck=k['menge'] - d,
                                                   datum=leg['datum'], atr20=leg.get('atr20'), grund=f'Order {status}'))
                    log(f"{leg['strategie']} {leg['symbol']}: {k['menge'] - d} Stück nicht ausgeführt – im nächsten Lauf nachholen")
                if d == 0:
                    st['legs'].remove(leg); legs.pop(leg['id']); log(f"Leg {leg['id']} {leg['strategie']} {leg['symbol']} nicht eröffnet (Order {status})")
                    continue
                if d < k['menge']: log(f"Teilfüllung Leg {leg['id']} {leg['strategie']} {leg['symbol']}: {d} von {k['menge']}")
                leg.update(stueck=d, status='offen', einstieg=preis, fill_einstieg=fill_k, schluss_einstieg=s_px)
            else:
                info = leg.pop('ausstieg', None) or {}
                if d > 0:
                    zeilen.append(journal_zeile(leg, d, preis, fill_k, s_px, a['datum'], info, kal)); leg['stueck'] -= d
                if d < k['menge']:
                    leg['ausstieg_offen'] = dict(grund=info.get('grund', 'Ausstieg'), datum=a['datum'])
                    log(f"Ausstieg offen: Leg {leg['id']} {leg['strategie']} {leg['symbol']} {k['menge'] - d} Stück (Order {status}) – wird nachgeholt")
                else: leg.pop('ausstieg_offen', None)
                if leg['stueck'] <= 0: st['legs'].remove(leg); legs.pop(leg['id'])
        log(f"Abrechnung {a['symbol']} {a['datum']}: Order {a['menge']:+d} → gefüllt {F:+d} @ {p_fill} (Schluss {s_px}), {status}")
    st['auftraege'] = rest
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
    tage = [a['datum'] for a in st['auftraege'] if a['datum'] < heute and (a.get('order_id') or (a.get('zweite') or {}).get('order_id'))]
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
            zeilen.append(journal_zeile(leg, neu, px, None, None, datum, dict(grund=f"BB Stop (Stop {leg.get('stop')}, Fill {px})"), kal)); leg['stueck'] -= neu
            log(f"BB-Stop gefüllt {leg['symbol']} {neu} @ {px}")
        if o['status'] in ENDSTATUS:
            if o['status'] != 'filled': log(f"BB-Stop {leg['symbol']} {o['status']} – wird neu gesetzt")
            leg.pop('stop_order', None); leg.pop('stop_gefuellt', None)
        if leg['stueck'] <= 0: st['legs'].remove(leg); legs.pop(leg['id'], None)
    return zeilen


def positionen_lesen():
    """Wie v1 (15.10. 23:15): nur Aktien/ETFs (`asset_class` us_equity) zählen – Krypto o. Ä. im selben Konto ist nicht Sache des Bots."""
    out = {}
    for p in alp('/v2/positions'):
        if p.get('asset_class', 'us_equity') != 'us_equity': continue
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
    reihe = [float(r['equity']) for r in rows if r.get('equity') and st.get('start') and r['datum'] >= st['start']]   # nur ab Bot-Start (Neustart!)
    for z in neu:
        reihe.append(float(z['equity'])); z['drawdown'] = round(1 - reihe[-1] / max(reihe), 4)
    csv_anhaengen('equity.csv', EQUITY_SPALTEN, neu)
    return reihe


def hwm_pruefen(st, reihe, eq):
    """Review 2.5: Höchststand nie nur aus state.json – auch aus equity.csv und Alpaca-Historie, beides ab Bot-Start.
    Fehlt der Start (gelöschte state.json = Neustart), beginnt der Höchststand neu; dagegen schützt die Prüfung in lauf()."""
    kand = [st.get('hwm') or 0, eq] + reihe
    try:
        if st.get('start'):
            ph = alp(f"/v2/account/portfolio/history?timeframe=1D&start={st['start']}&end={dt.datetime.now(NY).date().isoformat()}")  # ohne end nur 1 Monat
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
        if datum < min((r[-1][0] for r in hist.values() if r), default=datum) and not any(r[0] == datum for rows in hist.values() for r in rows[-15:]):
            del st['signale'][datum]; continue                                          # Tag ohne Kerze (z. B. Sonderschließung) nicht ewig mitschleppen
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


def stornieren(sym, offene, nur=None):
    """Offene Orders im Symbol stornieren und auf `canceled` warten (Review 1.8/1.9). Eigene MOC-Orders (sb-…) nie.
    nur: Menge von Order-IDs, auf die sich der Storno beschränkt. → (ok, stornierte Orders)."""
    weg = []
    for o in [o for o in offene if o['symbol'] == sym and (nur is None or o['id'] in nur)]:
        if o.get('time_in_force') == 'cls' or str(o.get('client_order_id', '')).startswith('sb-2'): continue
        try:
            alp(f"/v2/orders/{o['id']}", method='DELETE')
            ende = time.monotonic() + STORNO_WARTEN_S
            while True:
                z = alp(f"/v2/orders/{o['id']}", tries=2)
                if z['status'] in ENDSTATUS: break
                if time.monotonic() > ende: log(f'Storno {sym} nicht bestätigt ({z["status"]}) – Symbol heute ausgelassen'); return False, weg
                time.sleep(0.5)
        except Exception as e:
            log(f"Storno {sym} {o['id']} fehlgeschlagen: {schwaerzen(e)[:100]}"); return False, weg
        if z['status'] == 'filled' or float(z.get('filled_qty') or 0) > 0:
            log(f'{sym}: Order {o["id"]} wurde gerade gefüllt – Bestand geändert, Symbol heute ausgelassen'); return False, weg
        weg.append(o); offene.remove(o)
    return True, weg


def moc_senden(sym, menge, cid):
    """Eine MOC-Order. Kein blindes Wiederholen (Doppelorder!). Fachliche Ablehnung → Abgelehnt. Jeder andere Fehler
    (Zeitüberschreitung, Verbindungsabbruch, 5xx) heißt „Ausgang unklar“ → per client_order_id nachsehen."""
    body = dict(symbol=sym, qty=str(abs(menge)), side='buy' if menge > 0 else 'sell', type='market', time_in_force='cls', client_order_id=cid)
    try: return alp('/v2/orders', body, 'POST', tries=1)
    except Abgelehnt: raise
    except Exception as e:
        try: return alp(f'/v2/orders:by_client_order_id?client_order_id={urllib.parse.quote(cid)}', tries=3)
        except RuntimeError as e2:
            if 'Alpaca 404' in str(e2): raise Abgelehnt(f'nicht angekommen ({schwaerzen(e)[:80]})')
            raise RuntimeError(f'Ausgang unklar: {schwaerzen(e)[:80]}')


def stop_setzen(leg, heute, offene=(), menge=None):
    """GTC-Stop 3×ATR für ein BB-Leg (README). Eindeutige client_order_id je Leg; liegt schon ein Stop des Legs bei Alpaca
    (Antwort verloren), wird er übernommen statt verdoppelt (Review v2)."""
    praefix = f"sb-stop-{leg['id']}-"
    qty = menge if menge is not None else leg['stueck'] - ((leg.get('ausstieg') or {}).get('menge', 0) if (leg.get('ausstieg') or {}).get('gesendet') else 0)
    if qty <= 0: return False
    for o in offene:
        if str(o.get('client_order_id', '')).startswith(praefix) and o.get('symbol') == leg['symbol']:
            leg['stop_order'] = o['id']; log(f"BB-Stop {leg['symbol']} bereits vorhanden – übernommen"); return True
    stop = round(leg['einstieg'] - kern.BB_STOP_ATR * leg['atr20'], 2)
    leg['stop_n'] = leg.get('stop_n', 0) + 1; cid = f"{praefix}{heute}-{leg['stop_n']}"
    body = dict(symbol=leg['symbol'], qty=str(qty), side='sell', type='stop', stop_price=f'{stop:.2f}', time_in_force='gtc', client_order_id=cid)
    try:
        try: o = alp('/v2/orders', body, 'POST', tries=1)
        except Abgelehnt: raise
        except Exception: o = alp(f'/v2/orders:by_client_order_id?client_order_id={urllib.parse.quote(cid)}', tries=3)
        leg['stop_order'] = o['id']; leg['stop'] = stop; leg.pop('stop_gefuellt', None); leg.pop('stop_fehlt_seit', None); log(f"BB-Stop {leg['symbol']} {qty} @ {stop}")
        return True
    except Exception as e:
        log(f"WARNUNG: BB-Stop {leg['symbol']} nicht gesetzt ({schwaerzen(e)[:120]}) – nächster Lauf versucht es erneut"); return False


def senden(st, heute, kz, ausstiege, einstiege, orders, uhr, offene):
    """1. Alle Aufträge vorbereiten und in einem Schritt speichern (bricht der Lauf ab, findet der Folgelauf jeden als
       'vorbereitet' und sieht per client_order_id nach – Review 5.2). 2. Je Symbol: offene Stops stornieren → Uhr prüfen →
       MOC senden → speichern. 3. Stornierte Stops bleibender BB-Legs neu setzen (immer, auch nach Fehlern).
    → Liste Fehlertexte."""
    fehler = []; nr = 0; symbole = []; auftraege = []
    for x in [a[0] for a in ausstiege] + einstiege:
        if x['symbol'] not in symbole: symbole.append(x['symbol'])
    for s in symbole:
        d = orders.get(s, 0); cid = f'sb-{heute}-{s}'; komps = []
        P = sum(l['richtung'] * l['stueck'] for l in st['legs'] if l['symbol'] == s)      # Bestand vor dem heutigen Auftrag
        for leg, grund, menge in [a for a in ausstiege if a[0]['symbol'] == s]:
            komps.append(dict(art='aus', leg_id=leg['id'], menge=menge, seite=-leg['richtung'], strategie=leg['strategie']))
            leg['ausstieg'] = dict(grund=grund, datum=heute, menge=menge, kurs_entscheidung=kz.get(s, {}).get('px'), auftrag=cid)
        for leg in [l for l in einstiege if l['symbol'] == s]:
            leg.update(id=st['naechste_id'], status='pending', einstieg_datum=heute, kurs_entscheidung=kz[s]['px']); st['naechste_id'] += 1
            komps.append(dict(art='ein', leg_id=leg['id'], menge=leg['stueck'], seite=leg['richtung'], strategie=leg['strategie'], nr=nr)); nr += 1
            st['legs'].append(leg)
        a = dict(datum=heute, symbol=s, menge=d, client_order_id=cid if d else None, order_id=None, status='vorbereitet' if d else 'intern', komponenten=komps)
        if P < 0 < P + d:                                                                # short → long (nur ohne Kauf-Sperre): eindecken + neu kaufen
            a['menge_order'] = -P; a['zweite'] = dict(client_order_id=f'{cid}-2', order_id=None, menge=P + d, status='vorbereitet')
        auftraege.append(a)
    st['auftraege'] += auftraege; speichern(st)
    neu_setzen = []                                                                      # (Leg, steigt heute aus) mit storniertem Stop
    try:
        for a in auftraege:
            try: fehler += auftrag_senden(st, a, uhr, offene, neu_setzen)
            except Exception as e:
                a['grund'] = f'Ausgang unklar: {schwaerzen(e)[:150]}'                      # Status bleibt 'vorbereitet' → Folgelauf sieht nach
                fehler.append(f"ORDER UNKLAR {a['symbol']} {a['menge']:+d}: {schwaerzen(e)[:120]}"); log(f"Order {a['symbol']} Ausgang unklar: {schwaerzen(e)[:160]}")
            speichern(st)
    finally:
        for leg, steigt_aus in neu_setzen:
            if steigt_aus or leg not in st['legs'] or not leg.get('einstieg') or leg.get('stop_order'): continue
            stop_setzen(leg, heute, offene)                                              # MOC nicht raus → Leg bleibt ganz (Review 3.5) → voller Stop
        speichern(st)
    return fehler


def auftrag_senden(st, a, uhr, offene, neu_setzen):
    s, d = a['symbol'], a['menge']
    legs = {l['id']: l for l in st['legs']}
    aus_legs = [legs[k['leg_id']] for k in a['komponenten'] if k['art'] == 'aus' and k['leg_id'] in legs]
    if d == 0:
        log(f'{s}: Wechsel innerhalb des Symbols, keine Order (intern zum Schluss verrechnet)')
        stops = {l['stop_order'] for l in aus_legs if l.get('stop_order')}                # Stop eines intern geschlossenen BB-Legs muss weg
        if not stops: return []
        ok, weg = stornieren(s, offene, nur=stops)
        for l in aus_legs:
            if l.get('stop_order') in {o['id'] for o in weg}: l.pop('stop_order', None)
        return [] if ok else [f'STOP NICHT STORNIERT {s}: Stop des geschlossenen BB-Legs bleibt aktiv – bitte von Hand stornieren']
    m = minuten_bis_schluss_jetzt(uhr)
    if not (ORDER_SPAETESTENS_MIN <= m <= ORDER_FRUEHESTENS_MIN):
        a.update(status='abgelehnt', grund=f'nicht gesendet, {m:.1f} Min bis Schluss')
        return [f'ORDER NICHT GESENDET {s}: {m:.1f} Min bis Schluss (erlaubt {ORDER_SPAETESTENS_MIN}–{ORDER_FRUEHESTENS_MIN})']
    ok, weg = stornieren(s, offene)
    aus_ids = {l['id'] for l in aus_legs}
    for o in weg:
        for leg in st['legs']:
            if leg.get('stop_order') == o['id']: leg.pop('stop_order', None); neu_setzen.append((leg, False))
    if not ok:
        a.update(status='abgelehnt', grund='offene Order im Symbol nicht stornierbar')
        return [f'ORDER NICHT GESENDET {s}: offene Order nicht stornierbar – heute keine MOC']
    m = minuten_bis_schluss_jetzt(uhr)                                                    # direkt vor dem POST noch einmal (Storno kann dauern)
    if not (ORDER_SPAETESTENS_MIN <= m <= ORDER_FRUEHESTENS_MIN):
        a.update(status='abgelehnt', grund=f'nicht gesendet, {m:.1f} Min bis Schluss')
        return [f'ORDER NICHT GESENDET {s}: {m:.1f} Min bis Schluss nach Storno']
    try:
        o = moc_senden(s, a.get('menge_order', d), a['client_order_id'])
    except Abgelehnt as e:
        a.update(status='abgelehnt', grund=schwaerzen(e)[:200]); log(f'Order {s} {d:+d} ABGELEHNT: {schwaerzen(e)[:160]}')
        if a.get('zweite'): a['zweite']['status'] = 'abgelehnt'
        return [f'ORDER ABGELEHNT {s} {d:+d}: {schwaerzen(e)[:160]}']
    a.update(order_id=o['id'], status='gesendet')
    if d > 0:                                                                            # offene MOC-Kauforder: Alpaca lehnt jeden Sell-Stop im Symbol ab
        for i, (leg, aus) in enumerate(neu_setzen):                                      # (Wash-Trade-Schutz) → Stop erst im nächsten Lauf neu setzen
            if leg['symbol'] == s and not aus:
                neu_setzen[i] = (leg, True); leg['stop_fehlt_seit'] = a['datum']
                log(f"BB-Stop {s}: bis zum nächsten Lauf ohne Stop (Alpaca Wash-Trade-Schutz bei offener MOC-Kauforder)")
    zusatz = []
    if a.get('zweite'):                                                                  # zweite Kauforder: neue Long-Position
        z = a['zweite']; m = minuten_bis_schluss_jetzt(uhr)
        if not (ORDER_SPAETESTENS_MIN <= m <= ORDER_FRUEHESTENS_MIN):
            z.update(status='abgelehnt', grund='Fenster'); zusatz.append(f"ORDER NICHT GESENDET {s} {z['menge']:+d} (zweiter Teil): {m:.1f} Min bis Schluss")
        else:
            try:
                o2 = moc_senden(s, z['menge'], z['client_order_id']); z.update(order_id=o2['id'], status='gesendet')
                log(f"MOC buy {z['menge']} {s} (zweiter Teil, neu long) → {o2['id']}")
            except Abgelehnt as e:
                z.update(status='abgelehnt', grund=schwaerzen(e)[:200])
                zusatz.append(f"ORDER ABGELEHNT {s} {z['menge']:+d} (zweiter Teil short → long): {schwaerzen(e)[:120]}")
    for i, (leg, _) in enumerate(neu_setzen):                                              # aussteigende Legs bekommen keinen Stop zurück
        if leg['id'] in aus_ids and leg.get('ausstieg', {}).get('menge', 0) >= leg['stueck']: neu_setzen[i] = (leg, True)
    for leg in aus_legs:
        if leg.get('ausstieg'): leg['ausstieg']['gesendet'] = True
    log(f"MOC {'buy' if d > 0 else 'sell'} {abs(a.get('menge_order', d))} {s} → {o['id']} ({minuten_bis_schluss_jetzt(uhr):.1f} Min vor Schluss)")
    return zusatz


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
    AUSGABE.update(schreiben=not a.dry, status='STATUS-dry.md' if a.dry else 'STATUS.md'); LOGZEILEN.clear(); WARNUNGEN.clear()
    try:
        return lauf(a)
    except Abbruch as e:
        log(f'{e.titel}: {e.text}')
        if not e.status_steht: status_fehler(e.titel, e.text)
        sys.exit(1)
    except Exception as e:
        import traceback
        log(f'FEHLER: {type(e).__name__}: {str(e)[:300]}'); print(traceback.format_exc()[-2000:])
        status_fehler('FEHLER', f'{type(e).__name__}: {str(e)[:300]}'); sys.exit(1)


def heutige_bot_orders(heute_d):
    """MOC-Orders des Bots von heute bei Alpaca (client_order_id sb-JJJJ-MM-TT-…)."""
    ab = dt.datetime.combine(heute_d, dt.time(0, 0), NY).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return [o for o in alp(f'/v2/orders?status=all&after={ab}&limit=500&direction=desc') or []
            if str(o.get('client_order_id', '')).startswith(f'sb-{heute_d.isoformat()}-')]


def stopp_grund(st, eq, k5):
    """Bereits gestoppt (Abwicklung läuft), Not-Aus oder Abschaltkriterium K5 → Text, sonst None."""
    if st.get('gestoppt'): return st.get('stopp_grund') or 'GESTOPPT'
    if kern.notaus(eq, st.get('startkapital')): return f'NOT-AUS: Equity {eq:,.0f} $ < 70 % des Startkapitals {st["startkapital"]:,.0f} $'
    if k5['verletzt']: return 'ABSCHALTKRITERIUM AUSGELÖST: ' + '; '.join(k5['verletzt'])
    return None


def abwicklungs_legs(st, differenz, heute):
    """Beim Glattstellen trotz Abweichung: Differenz je Symbol als Leg 'ABWICKLUNG' buchen, damit Σ Legs = Alpaca-Position
    und die Glattstell-Order genau die Alpaca-Position schließt."""
    for s, (soll, ist) in differenz.items():
        d = ist - soll
        st['legs'].append(dict(id=st['naechste_id'], strategie='ABWICKLUNG', symbol=s, richtung=1 if d > 0 else -1, stueck=abs(d), datum=heute,
                               einstieg_datum=heute, einstieg=None, status='offen', atr20=0.0))
        st['naechste_id'] += 1


def lauf(a):
    ohne_datei = not os.path.exists('state.json')
    st = laden()
    clock = alp('/v2/clock'); jetzt = zeit(clock['timestamp']); heute_d = jetzt.astimezone(NY).date(); heute = heute_d.isoformat()
    naechster_schluss = zeit(clock['next_close']); min_bis_schluss = (naechster_schluss - jetzt).total_seconds() / 60
    if not clock['is_open'] or not (START_SPAETESTENS_MIN <= min_bis_schluss <= START_FRUEHESTENS_MIN):
        if not a.force:
            print(f'kein Fenster (offen={clock["is_open"]}, {min_bis_schluss:.1f} Min bis Schluss) – Ende'); return dict(ende='kein Fenster')
        log(f'--force: außerhalb des Fensters ({min_bis_schluss:.1f} Min bis Schluss)')
    if st.get('letzter_lauf') == heute and not a.force:
        log('heute schon gelaufen – Ende'); return dict(ende='schon gelaufen')
    t_start = time.monotonic()
    if not st.get('start') and (csv_lesen('equity.csv') or csv_lesen('journal.csv')) and not st.get('neustart'):
        # Review 2.5: Der Bot hat schon gehandelt, aber Start/Startkapital/Höchststand fehlen. Gelöschte state.json = Neustart
        # nach README („state.json dann von Hand löschen“) → laut melden. Vorhandene state.json ohne Start (von Hand gebaut,
        # beschädigt) → nicht still mit Startkapital = heutige Equity weiter (Not-Aus-Schwelle, Bremse und K5 wären zurückgesetzt).
        if ohne_datei:
            log('WARNUNG: NEUSTART – state.json fehlt, equity.csv/journal.csv zeigen frühere Läufe – Startkapital und Höchststand '
                'beginnen heute neu (README: Neustart nach Not-Aus). War das nicht gewollt: state.json aus der Git-Historie zurückholen.')
        else:
            text = ('state.json ohne start/startkapital, aber equity.csv/journal.csv zeigen frühere Läufe – start, startkapital und hwm '
                    'aus der Git-Historie wiederherstellen oder für einen gewollten Neustart "neustart": true setzen')
            if not a.dry: raise Abbruch('ZUSTAND FEHLT', text)
            log(f'WARNUNG: ZUSTAND FEHLT (dry: rechne mit heutiger Equity weiter): {text}')
    if not a.dry and heutige_bot_orders(heute_d):
        # Bot-Orders von heute bei Alpaca, aber state.json kennt sie nicht → veralteter Stand (z. B. Nachläufer mit altem Checkout).
        # Nichts stornieren, nichts senden, keine Datei schreiben (Review v2, Befund „Nachläufer“).
        print('heute schon gehandelt (Bot-Orders bei Alpaca), state.json veraltet – Ende ohne Änderung'); return dict(ende='schon gehandelt')
    if st.get('gestoppt') and not st['legs'] and not st['auftraege'] and not positionen_lesen():
        log(f"GESTOPPT ({st.get('stopp_grund')}) – kein Handel, bis eine Sitzung mit Linus entscheidet (state.json: gestoppt=false)")
        status_gestoppt(st); return dict(ende='gestoppt')

    # 2) Vorbereitung vor dem Warten (alles, was sich bis zum Schluss nicht mehr ändert)
    kal = lade_kalender(heute_d, min([l.get('einstieg_datum') or l['datum'] for l in st['legs']], default=None))
    hist = bars(list(ALLE_SYMBOLE), heute_d)
    offen_symbole = {x['symbol'] for x in st['auftraege']} | {l['symbol'] for l in st['legs'] if l.get('stop_order')}
    aelteste = min([x['datum'] for x in st['auftraege']] + [heute])
    tage_zurueck = (heute_d - dt.date.fromisoformat(aelteste)).days + 10
    zeilen = abrechnen(st, heute, kal, schlusskurse(offen_symbole, heute_d, tage=tage_zurueck) if offen_symbole else {})
    signale_auswerten(st, hist)
    konto = alp('/v2/account'); positionen = positionen_lesen()
    journal_anhaengen(zeilen); speichern(st)                                             # Abrechnung sofort sichern (Review v2: doppelte Journalzeilen)
    reihe = equity_nachtragen(st, konto, positionen, kal, heute)
    k5 = kern.abschaltkriterium(reihe)                                               # K5 aus der eigenen Kontokurve seit Start
    if k5['verletzt']: log('ABSCHALTKRITERIUM verletzt: ' + '; '.join(k5['verletzt']))
    # Not-Aus/K5/Stopp vor dem Abgleich bewerten: ein Abgleichfehler darf das Glattstellen nicht verhindern (Review v2)
    stopp = stopp_grund(st, float(konto['equity']), k5)
    differenz = abgleich(st['legs'], positionen)
    if differenz:
        text = 'Legs ≠ Alpaca-Positionen: ' + ', '.join(f'{s} Legs {a_} / Alpaca {b_}' for s, (a_, b_) in differenz.items())
        if stopp and not a.dry:
            abwicklungs_legs(st, differenz, heute); log(f'WARNUNG: {text} – {stopp.split(":")[0]}: es werden die Alpaca-Positionen glattgestellt')
        elif not a.dry: speichern(st); raise Abbruch('ABGLEICH NÖTIG', text + ' – kein Handel, bitte prüfen')
        else: log(f'ABGLEICH NÖTIG (dry: rechne trotzdem weiter): {text}')
    if st.get('gestoppt') and not st['legs']:                                          # Abwicklung abgeschlossen: alles glatt
        speichern(st); csv_anhaengen('journal.csv', JOURNAL_SPALTEN, [])
        log(f"GESTOPPT ({st.get('stopp_grund')}) – alle Positionen glatt, kein Handel bis zur Sitzung mit Linus")
        status_gestoppt(st); return dict(ende='gestoppt')
    leihbar = {}
    for s in TSMOM:
        try: leihbar[s] = bool(alp(f'/v2/assets/{s}').get('shortable', False))
        except Exception: leihbar[s] = False
    offene = [o for o in alp('/v2/orders?status=open&limit=500') or []] if not a.dry else []
    for leg in st['legs']:                                                               # Stops für BB-Legs mit bekanntem Einstieg
        if leg['strategie'] == 'BB' and leg.get('einstieg') and leg.get('status') == 'offen' and not leg.get('stop_order') and not a.dry and not stopp:
            if stop_setzen(leg, heute, offene) and leg['stop_order'] not in {o['id'] for o in offene}:
                offene.append(dict(id=leg['stop_order'], symbol=leg['symbol'], client_order_id=f"sb-stop-{leg['id']}-", time_in_force='gtc'))
    speichern(st)

    # 3) K6: bis ENTSCHEIDUNG_MIN vor Schluss warten, erst dann Kurse laden (Signal so nah am Schluss wie Alpaca erlaubt)
    warte = (min_bis_schluss - ENTSCHEIDUNG_MIN) * 60 - (time.monotonic() - t_start)         # Vorbereitung abziehen (Review v2)
    if clock['is_open'] and warte > 0 and not a.force:
        log(f'warte {warte / 60:.1f} Min bis {ENTSCHEIDUNG_MIN:.0f} Min vor Schluss (K6-Fenster)'); time.sleep(warte)
    clock = alp('/v2/clock'); uhr = dict(jetzt=zeit(clock['timestamp']), schluss=naechster_schluss, mono=time.monotonic())
    entscheidung_zeit = uhr['jetzt'].astimezone(NY).strftime('%H:%M:%S')

    konto = alp('/v2/account'); eq = float(konto['equity'])
    if st['startkapital'] is None: st.update(start=heute, startkapital=eq, hwm=eq, letzte_tsmom=heute); st.pop('neustart', None)
    st['hwm'] = hwm_pruefen(st, reihe, eq); dd = 1 - eq / st['hwm']
    live = snapshots(list(ALLE_SYMBOLE))
    vix, vix3m, vix_quelle = lade_vix()
    kurse = dict(live)
    if vix and vix3m: kurse['^VIX'] = {'px': vix}; kurse['^VIX3M'] = {'px': vix3m}; st['vix_fehlt'] = 0
    else: st['vix_fehlt'] = st.get('vix_fehlt', 0) + 1; log(f'WARNUNG: VIX nicht lesbar ({st["vix_fehlt"]}. Lauf in Folge): {vix_quelle}')
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

    # Not-Aus und Abschaltkriterium K5: alles per MOC glatt (Regel 4: nur MOC im Fenster, kein DELETE /v2/positions), Bot stoppt
    stopp = stopp or stopp_grund(st, eq, k5)
    if stopp:
        log(f'{stopp} – alle Legs per MOC glatt, Bot stoppt, kein automatischer Neustart')
        schliessen = [(l, stopp.split(':')[0]) for l in st['legs']]; neu = []
        st.update(gestoppt=True, stopp_grund=st.get('stopp_grund') or stopp, aufgeschoben=[])
    roh = netto_plan(schliessen, neu)
    no = netto_orders(st['legs'], schliessen, neu, VORZEICHENWECHSEL_SPERRE)           # Review 3.2: nie durch null in einem Tag
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
        status_md(st, eq, dd, kz, ratio, plan, no['ausstiege'], no['einstiege'], heute, kal, lauf_info, k5, dry=True, titel=stopp); return ergebnis

    # 4) Senden (Uhr erneut lesen: Alpaca lehnt MOC nach 15:50 ET ab – lieber kein Handel als abgelehnte Orders)
    clock2 = alp('/v2/clock'); uhr = dict(jetzt=zeit(clock2['timestamp']), schluss=naechster_schluss, mono=time.monotonic())
    rest = minuten_bis_schluss_jetzt(uhr)
    if not clock2['is_open'] or not (ORDER_SPAETESTENS_MIN <= rest <= ORDER_FRUEHESTENS_MIN):
        raise Abbruch('ZU SPÄT', f'{rest:.1f} Min bis Schluss (erlaubt {ORDER_SPAETESTENS_MIN}–{ORDER_FRUEHESTENS_MIN}) – keine Orders gesendet, nichts gebucht')
    for l in st['legs']:
        if l.get('id') in info['datum_neu']: l['datum'] = info['datum_neu'][l['id']]       # Folgesignal: halten, Tag neu zählen
    st['letzter_lauf'] = heute                                                           # vor der ersten Order: Nachläufer handelt nicht doppelt
    if not stopp: st['aufgeschoben'] = no['aufgeschoben'] + info.get('aufgeschoben_behalten', [])
    if info['tsmom_tag']: st['letzte_tsmom'] = heute
    st['signale'][heute] = {s: round(kz[s]['ibs'], 4) for s in INDEX + SEKTOREN + LAENDER if s in kz}
    lauf_info['min_senden'] = rest
    fehler = senden(st, heute, kz, no['ausstiege'], no['einstiege'], plan, uhr, offene)
    st['letzter_lauf_info'] = lauf_info
    if st.get('vix_fehlt', 0) >= VIX_ALARM_LAEUFE: fehler.append(f"VIX seit {st['vix_fehlt']} Läufen nicht lesbar – VIX-Contango kann weder ein- noch aussteigen")
    if kal.ist_handelstag(heute) and (kal.naechster(heute) or '9') > heute and woche(kal.naechster(heute) or '2999-12-31') != woche(heute):
        wochenbericht(st, heute, eq, kal)                                                # letzter Handelstag der Woche (meist Freitag)
    speichern(st)
    ergebnis['fehler'] = fehler
    status_md(st, eq, dd, kz, ratio, plan, no['ausstiege'], [], heute, kal, lauf_info, k5, fehler=fehler, titel=stopp)
    if stopp: raise Abbruch(stopp.split(':')[0] if stopp.split(':')[0] != 'GESTOPPT' else 'GESTOPPT – ABWICKLUNG', stopp, status_steht=True)
    if fehler: raise Abbruch('ORDER ABGELEHNT' if any('VIX' not in f for f in fehler) else 'VIX FEHLT', '; '.join(fehler), status_steht=True)
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


def sparkline(werte):
    zeichen = '▁▂▃▄▅▆▇█'
    if not werte: return ''
    lo, hi = min(werte), max(werte)
    return ''.join(zeichen[int((v - lo) / (hi - lo) * 7)] if hi > lo else zeichen[3] for v in werte)


def woche(datum):
    j, w, _ = dt.date.fromisoformat(datum).isocalendar()
    return f'{j}-{w:02d}'


def _f(x, fmt='{:,.0f}'):
    try: return fmt.format(float(x)).replace(',', '.') if x not in (None, '') else '–'
    except (TypeError, ValueError): return '–'


def statistik(zeilen, schluessel='rendite_bp'):
    """Ø, t-Wert und n einer Spalte (bp) aus Journalzeilen."""
    x = [float(z[schluessel]) for z in zeilen if z.get(schluessel) not in (None, '')]
    n = len(x)
    if n == 0: return dict(n=0, mittel=None, t=None)
    mu = sum(x) / n; sd = (sum((v - mu) ** 2 for v in x) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return dict(n=n, mittel=mu, t=mu / (sd / n ** 0.5) if sd > 0 else None)


def status_md(st, eq, dd, kz, ratio, plan, ausstiege, neu, heute, kal, lauf_info, k5=None, dry=False, fehler=(), titel=None):
    """STATUS.md (SPEC Aufgabe 5): Alarme oben, Konto, Lauf, Kurve, K5, offene Legs, Stand je Strategie, IBS-Vorteil, Termine, Log."""
    k5 = k5 or {}
    z = [f"# Systembuch-Bot – Stand {heute}{' (DRY RUN – nichts gesendet, nichts gebucht)' if dry else ''}", '']
    if titel: z += [f'## {titel}', '', 'Alle Positionen per MOC glatt, Bot gestoppt. Neustart nur nach Sitzung mit Linus (`gestoppt` in state.json).', '']
    if fehler: z += ['## FEHLER – Lauf rot (Exit 1)', '', *[f'- {x}' for x in fehler], '']
    if WARNUNGEN: z += ['**Warnungen:** ' + ' · '.join(dict.fromkeys(WARNUNGEN)), '']
    z += ['## Konto', '',
          f"Equity **{_f(eq)} $** · Start {_f(st.get('startkapital') or eq)} $ ({st.get('start') or heute}) · Höchststand {_f(st.get('hwm') or eq)} $ · "
          f"Drawdown {dd * 100:.1f} %".replace(".", ",") + f"{' · **BREMSE ×0,5**' if dd >= BREMSE_DD else ''}",
          f"Entscheidung {lauf_info.get('entscheidung')} ET · gesendet {lauf_info['min_senden']:.1f} Min vor Schluss" if 'min_senden' in lauf_info else
          f"Entscheidung {lauf_info.get('entscheidung')} ET ({lauf_info.get('min_entscheidung', 0):.1f} Min vor Schluss)",
          f"VIX3M/VIX {ratio and round(ratio, 3)} (Quelle: {lauf_info.get('vix_quelle')}) · Kalender: {lauf_info.get('kalender')}",
          f"Netto-MOC-Orders heute: {plan or 'keine'}", '']
    eqz = csv_lesen('equity.csv')[-60:]
    if eqz:
        w = [float(r['equity']) for r in eqz]
        z += ['## Kurve (letzte 60 Handelstage)', '', f"`{sparkline(w)}`  {eqz[0]['datum']} {_f(w[0])} $ → {eqz[-1]['datum']} {_f(w[-1])} $ (min {_f(min(w))}, max {_f(max(w))})", '']
    def k5zeile(name, wert, schwelle, ab, fmt):
        return f"| {name} | {fmt(wert) if wert is not None else f'ab Tag {ab}'} | {schwelle} | {'**VERLETZT**' if any(name.split()[0] in v for v in k5.get('verletzt', [])) else 'ok'} |"
    z += ['## Abschaltkriterium K5', '', f"Tage seit Start: {k5.get('tage', 0)}", '', '| Kennzahl | Wert | Schwelle | Status |', '|---|---|---|---|',
          k5zeile('12-Monats-Rendite', k5.get('rendite_12m'), '≤ −24 %', 252, lambda x: f'{x * 100:+.1f} %'),
          k5zeile('Drawdown vom Höchststand', k5.get('drawdown'), '≥ 34 %', 1, lambda x: f'{x * 100:.1f} %'),
          k5zeile('250-Tage-Sharpe', k5.get('sharpe_250'), '≤ −1,30', 250, lambda x: f'{x:.2f}'), '']
    z += ['## Offene Legs', '', '| Leg | Strategie | Symbol | Richtung | Stück | Einstieg | Kurs | unreal. $ | unreal. bp | seit | Stop | Status |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    summe = 0.0
    for l in st['legs']:
        px = kz.get(l['symbol'], {}).get('px'); ein = l.get('einstieg')
        u = (px - ein) * l['stueck'] * l['richtung'] if px and ein else None; summe += u or 0
        ub = l['richtung'] * (px / ein - 1) * 1e4 if px and ein else None
        status = 'Ausstieg MOC heute' if l.get('ausstieg') else ('Ausstieg offen (nachholen)' if l.get('ausstieg_offen') else l.get('status', ''))
        z.append(f"| {l['id']} | {l['strategie']} | {l['symbol']} | {'long' if l['richtung'] > 0 else 'short'} | {l['stueck']} | {ein or 'MOC offen'} | "
                 f"{px or '–'} | {_f(u)} | {_f(ub, '{:+.0f}')} | {l.get('einstieg_datum') or l['datum']} | {l.get('stop', '')} | {status} |")
    for l in neu: z.append(f"| neu | {l['strategie']} | {l['symbol']} | {'long' if l['richtung'] > 0 else 'short'} | {l['stueck']} | MOC heute | – | – | – | {l['datum']} | | geplant |")
    z += ['', f'Unrealisiert gesamt: {_f(summe)} $', '']
    j = csv_lesen('journal.csv')
    z += ['## Stand je Strategie seit Start (journal.csv)', '', '| Strategie | Trades | Treffer | Ø R (bp je Trade) | t | Summe $ | Ø MOC-Abweichung bp |', '|---|---|---|---|---|---|---|']
    for strat in kern.VORRANG:
        x = [r for r in j if r['strategie'] == strat]
        s_ = statistik(x); a_ = statistik(x, 'abweichung_bp')
        tr = sum(1 for r in x if r.get('pnl') not in ('', None) and float(r['pnl']) > 0) / len(x) if x else None
        z.append(f"| {strat} | {len(x)} | {_f(tr, '{:.0%}')} | {_f(s_['mittel'], '{:+.1f}')} | {_f(s_['t'], '{:.1f}')} | "
                 f"{_f(sum(float(r['pnl']) for r in x if r.get('pnl') not in ('', None)))} | {_f(a_['mittel'], '{:+.1f}')} |")
    z += ['', 'R = Rendite je Trade nach Fill (Gebühren 0). MOC-Abweichung = Kosten der Fills gegenüber dem offiziellen Schluss (Kostenabschlag gegenüber dem Replay).', '',
          '## Vorteil auf Trade-Ebene (IBS-Familie)', '', '| Gruppe | Trades | Ø bp je Haltetag | t | Referenz K3 | Referenz K6 (15:45) | Signal gekippt | Signal verpasst |', '|---|---|---|---|---|---|---|---|']
    ref = dict(IBS=('+16 bp', '+12,7 bp'), IBS_SEKTOR=('–', '–'), IBS_LAND=('+13 bp', '+6,9 bp'))
    for g in IBS_FAMILIE:
        x = [dict(r, bp_tag=float(r['rendite_bp']) / max(1, int(r['haltetage'] or 1))) for r in j if r['strategie'] == g and r.get('rendite_bp') not in ('', None)]
        s_ = statistik(x, 'bp_tag'); n, gek, verp = st.get('signal_stat', {}).get(g, [0, 0, 0])
        z.append(f"| {g} | {s_['n']} | {_f(s_['mittel'], '{:+.1f}')} | {_f(s_['t'], '{:.1f}')} | {ref[g][0]} | {ref[g][1]} | "
                 f"{f'{gek / n:.0%} von {n}' if n else '–'} | {verp} |")
    z += ['', 'Gekippt = Signal um 15:45, aber nicht mehr in der fertigen Tageskerze (K6-Referenz: 26 %). Verpasst = erst nach 15:45 entstanden.', '',
          '## Nächste Termine', '']
    z += [f'- {d} {dt.date.fromisoformat(d).strftime("%a")}: {t}' for d, t in kal.kommende_termine(heute, 35)] or ['- keine']
    z += ['', '## Signale heute', '', '| ETF | Kurs | IBS | SMA200 | BB unten | Signal |', '|---|---|---|---|---|---|']
    for s in INDEX + SEKTOREN + LAENDER:
        k = kz.get(s)
        if not k: continue
        sig = ('IBS ' if k['ibs'] < IBS_SCHWELLE else '') + ('BB ' if kern.ist_bb_signal(k) else '')
        z.append(f"| {s} | {k['px']:.2f} | {k['ibs']:.2f} | {k['sma200'] and round(k['sma200'], 2)} | {k['bb_unten']:.2f} | {sig} |")
    z += ['', f"Ausstiege heute: {[(l['strategie'], l['symbol'], g) for l, g, *_ in ausstiege] or 'keine'}", '',
          '## Letzte Logzeilen', '', '```', *LOGZEILEN[-5:], '```', '', '*Regeln und Belege: README.md. Journal: journal.csv. Kurve: equity.csv. Log: log.txt.*']
    status_schreiben(z)


def wochenbericht(st, heute, eq, kal):
    """berichte/JJJJ-WW.md am letzten Handelstag der Woche (SPEC Aufgabe 5): Abschlüsse seit dem letzten Bericht, Kurve, offene Legs."""
    if not AUSGABE['schreiben']: return
    os.makedirs('berichte', exist_ok=True)
    j = csv_lesen('journal.csv'); ab = st.get('bericht_journal', 0); neu = j[ab:]
    e = [r for r in csv_lesen('equity.csv') if woche(r['datum']) == woche(heute)]
    vorwoche = [r for r in csv_lesen('equity.csv') if woche(r['datum']) < woche(heute)]
    basis = float(vorwoche[-1]['equity']) if vorwoche else (st.get('startkapital') or eq)
    z = [f'# Wochenbericht {woche(heute)} (Stand {heute}, 15:45 ET)', '',
         f'Equity {_f(eq)} $ · Woche {(eq / basis - 1) * 100:+.2f} % (gegen Schluss Vorwoche {_f(basis)} $) · Höchststand {_f(st.get("hwm"))} $', '',
         '| Tag | Equity (Schluss) | Brutto | Legs |', '|---|---|---|---|']
    z += [f"| {r['datum']} | {_f(r['equity'])} | {_f(r.get('brutto'))} | {r.get('legs') or '–'} |" for r in e]
    z += ['', f'## Abschlüsse seit dem letzten Bericht ({len(neu)})', '', '| Strategie | Trades | Treffer | Ø bp | Summe $ |', '|---|---|---|---|---|']
    for strat in kern.VORRANG:
        x = [r for r in neu if r['strategie'] == strat]
        if not x: continue
        pn = [float(r['pnl']) for r in x if r.get('pnl') not in ('', None)]
        z.append(f"| {strat} | {len(x)} | {sum(1 for p in pn if p > 0) / len(pn):.0%} | {_f(statistik(x)['mittel'], '{:+.1f}')} | {_f(sum(pn))} |" if pn else f'| {strat} | {len(x)} | – | – | – |')
    z += ['', f"Offene Legs: {len(st['legs'])}. Ausstiege zum heutigen Schluss erscheinen im nächsten Bericht (Abrechnung im Folgelauf).", '']
    with open(os.path.join('berichte', f'{woche(heute)}.md'), 'w') as f: f.write('\n'.join(z))
    st['bericht_journal'] = len(j)
    log(f'Wochenbericht berichte/{woche(heute)}.md geschrieben')


if __name__ == '__main__':
    main()
