"""Systembuch-Bot – reine Entscheidungslogik (v2, Aufgabe 1 der SPEC).

Kein Netz-, Datei- oder Uhrzugriff. Live-Lauf (`systembuch_bot.py`) und Replay (`replay.py`) rufen dieselben Funktionen:
  kennzahlen()   Tageskennzahlen je Symbol (IBS, SMA, Bollinger, ATR, 12M-Rendite, Vol60) – unverändert aus v1
  entscheide()   Ausstiege und Einstiege nach den README-Regeln, Vorrang, Brutto-Deckel, Bremse
  netto_orders() Netto-Order je Symbol mit Vorzeichenwechsel-Sperre (Review 3.2)
  verteile_fill() Netto-Fill eines Symbols zurück auf die Legs (FIFO je Strategie, SPEC Aufgabe 2 / Review 3.1)
  Kalender       Handelstage, Monatswechsel- und TSMOM-Termine (Quelle: Alpaca /v2/calendar oder Regelwerk als Notlösung)
  abschaltkriterium() K5 aus der eigenen Kontokurve

Die Handelsregeln stehen im README und werden hier nur umgesetzt, nicht verändert.
"""
import bisect
import datetime as dt
import math

# ---------- Regeln (README, Stand 15.10.2026 – nicht ändern ohne neuen Test) ----------
INDEX = ('SPY', 'QQQ', 'DIA', 'IWM')
SEKTOREN = ('XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY')
LAENDER = ('EWG', 'EWJ', 'EWU', 'EWA', 'EWH', 'EWC', 'EWY', 'EWT', 'EWZ', 'EWL', 'EWQ', 'EWP', 'EFA', 'EEM')
MW_LAND = LAENDER[:12]
TSMOM = ('SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'EWJ', 'EWG', 'TLT', 'IEF', 'LQD', 'HYG', 'GLD', 'SLV', 'USO', 'DBC', 'DBA', 'UNG', 'UUP', 'FXE', 'VNQ')
VIX_ETF = 'SVXY'
ALLE_SYMBOLE = tuple(sorted(set(INDEX + SEKTOREN + LAENDER + TSMOM + (VIX_ETF,))))
GROESSE = dict(IBS=0.25, IBS_SEKTOR=0.11, IBS_LAND=0.07, BB=0.25, MW=0.25, MW_LAND=0.04, VIX=0.10)
MAX_OFFEN = dict(IBS_SEKTOR=4, IBS_LAND=4, BB=4)
TSMOM_BRUTTO_MAX = 0.60; MAX_BRUTTO = 1.9; BREMSE_DD = 0.15; BREMSE_FAKTOR = 0.5; NOTAUS = 0.70
IBS_SCHWELLE = 0.2; VIX_EIN = 1.01; VIX_AUS = 1.00; BB_STOP_ATR = 3.0; BB_MAX_TAGE = 15
VORRANG = ('IBS', 'MW', 'BB', 'IBS_SEKTOR', 'IBS_LAND', 'TSMOM', 'MW_LAND', 'VIX')
IBS_FAMILIE = ('IBS', 'IBS_SEKTOR', 'IBS_LAND')
# Strategien, deren Position über mehrere Tage gehalten wird: Ein durch die Vorzeichenwechsel-Sperre aufgeschobener Teil
# wird im nächsten Lauf nachgeholt. IBS-Signale gelten nur für den Schluss des Signaltags und verfallen.
MEHRTAGIG = ('MW', 'MW_LAND', 'BB', 'TSMOM', 'VIX')
# Abschaltkriterium K5 (README, 15.10.2026)
K5_RENDITE_12M = -0.24; K5_DRAWDOWN = 0.34; K5_SHARPE_250 = -1.30

# Parameter, die nur der Replay verändern darf (K4-Schalter, SPEC Punkt 4). Der Live-Lauf benutzt immer diese Standardwerte.
PARAM = dict(max_brutto=MAX_BRUTTO, bremse_dd=BREMSE_DD, bremse_faktor=BREMSE_FAKTOR, strategien=frozenset(VORRANG),
             tsmom_reserve=False, flip_sperre='beide')


# ---------- Kennzahlen (unverändert aus v1; ATR rechnet nur noch die letzten 20 True Ranges – gleiches Ergebnis, schneller) ----------
def kennzahlen(hist, live):
    """Pro Symbol: IBS heute, SMA200/SMA20/BB-unten (mit heutigem Kurs als letztem Schluss), ATR20, 12M-Rendite, Vol60.
    hist = {sym: [(datum, o, h, l, c), ...]} abgeschlossene Tage (bereinigt), live = {sym: {px, hi, lo}} heute (roh)."""
    out = {}
    for s, rows in hist.items():
        if s not in live or len(rows) < 60: continue
        px = live[s]['px']; hi = max(live[s]['hi'], px); lo = min(live[s]['lo'], px)      # Tagesbar hinkt dem letzten Kurs nach
        closes = [r[4] for r in rows] + [px]
        n = len(rows)
        tr = [max(rows[i][2] - rows[i][3], abs(rows[i][2] - rows[i - 1][4]), abs(rows[i][3] - rows[i - 1][4])) for i in range(max(1, n - 20), n)]
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
    """Vorzeichen der 12M-Rendite × 10 %/Vol60 (Deckel 2,0, Vol-Boden 2 %), Roh-Brutto ≤ 4,0, × 0,36, Brutto ≤ 60 %."""
    roh = {s: (1 if kz[s]['ret12'] > 0 else -1) * min(0.10 / max(kz[s]['vol60'], 0.02), 2.0) for s in TSMOM if s in kz and 'ret12' in kz[s]}
    summe = sum(abs(w) for w in roh.values()); f1 = min(1.0, 4.0 / summe) if summe else 1.0
    ziel = {s: w * f1 * 0.36 for s, w in roh.items()}
    brutto = sum(abs(w) for w in ziel.values()); f3 = min(1.0, TSMOM_BRUTTO_MAX / brutto) if brutto else 1.0
    return {s: w * f3 for s, w in ziel.items()}


def ist_bb_signal(k):
    return bool(k and k['sma200'] and k['px'] > k['sma200'] and k['px'] < k['bb_unten'])


def vix_verhaeltnis(kurse_heute):
    """VIX3M/VIX aus kurse_heute['^VIX'] / ['^VIX3M'] (je {px}); None, wenn eine Quelle fehlt."""
    v, v3 = (kurse_heute.get('^VIX') or {}).get('px'), (kurse_heute.get('^VIX3M') or {}).get('px')
    return v3 / v if v and v3 else None


# ---------- Kalender ----------
def _ostersonntag(j):
    a = j % 19; b, c = divmod(j, 100); d, e = divmod(b, 4); f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i, k = divmod(c, 4); l = (32 + 2 * e + 2 * i - h - k) % 7; m = (a + 11 * h + 22 * l) // 451
    monat, tag = divmod(h + l - 7 * m + 114, 31)
    return dt.date(j, monat, tag + 1)


def _nter_wochentag(j, monat, wochentag, n):
    d = dt.date(j, monat, 1); d += dt.timedelta(days=(wochentag - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _letzter_wochentag(j, monat, wochentag):
    d = dt.date(j + (monat == 12), monat % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - wochentag) % 7)


def _beobachtet(d):
    return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d


def nyse_feiertage(j):
    """NYSE-Regelwerk (ohne Sonderschließungen wie Staatstrauer oder Unwetter) → {datum: name}, {halbtag: name}."""
    f = {}
    neujahr = dt.date(j, 1, 1)
    if neujahr.weekday() != 5: f[_beobachtet(neujahr)] = 'Neujahr'                # fällt Neujahr auf Samstag, kein Ersatztag (NYSE-Regel)
    f[_nter_wochentag(j, 1, 0, 3)] = 'Martin Luther King Day'
    f[_nter_wochentag(j, 2, 0, 3)] = 'Presidents Day'
    f[_ostersonntag(j) - dt.timedelta(days=2)] = 'Karfreitag'
    f[_letzter_wochentag(j, 5, 0)] = 'Memorial Day'
    if j >= 2022: f[_beobachtet(dt.date(j, 6, 19))] = 'Juneteenth'
    f[_beobachtet(dt.date(j, 7, 4))] = 'Independence Day'
    f[_nter_wochentag(j, 9, 0, 1)] = 'Labor Day'
    thanks = _nter_wochentag(j, 11, 3, 4); f[thanks] = 'Thanksgiving'
    f[_beobachtet(dt.date(j, 12, 25))] = 'Weihnachten'
    if dt.date(j + 1, 1, 1).weekday() == 5: pass                                  # 31.12. bleibt Handelstag
    halb = {thanks + dt.timedelta(days=1): 'Tag nach Thanksgiving'}
    for d, name in ((dt.date(j, 7, 3), 'vor Independence Day'), (dt.date(j, 12, 24), 'Heiligabend')):
        if d.weekday() < 4 and d not in f: halb[d] = name                          # nur Mo–Do: fällt der 4.7./25.12. auf Sa, ist der Vortag Feiertag
    return f, halb


def regel_handelstage(von, bis):
    """Handelstage nach Regelwerk von..bis (ISO), mit Schlusszeiten. Notlösung, wenn /v2/calendar nicht erreichbar ist."""
    d0, d1 = dt.date.fromisoformat(von), dt.date.fromisoformat(bis)
    frei, halb = {}, {}
    for j in range(d0.year, d1.year + 1):
        f, h = nyse_feiertage(j); frei.update(f); halb.update(h)
    tage, schluss = [], {}
    d = d0
    while d <= d1:
        if d.weekday() < 5 and d not in frei:
            tage.append(d.isoformat()); schluss[d.isoformat()] = '13:00' if d in halb else '16:00'
        d += dt.timedelta(days=1)
    return tage, schluss


class Kalender:
    """Handelstage als sortierte ISO-Liste, optional Schlusszeit je Tag ('16:00' / '13:00')."""

    def __init__(self, tage, schluss=None, quelle='alpaca'):
        self.tage = sorted(set(tage)); self.schluss = dict(schluss or {}); self.quelle = quelle
        self._pos = {d: i for i, d in enumerate(self.tage)}

    @classmethod
    def nach_regeln(cls, von, bis):
        tage, schluss = regel_handelstage(von, bis)
        return cls(tage, schluss, quelle='Regelwerk (Notlösung, Sonderschließungen unbekannt)')

    def ist_handelstag(self, d): return d in self._pos

    def monat(self, jahr, monat):
        k = f'{jahr:04d}-{monat:02d}'
        i = bisect.bisect_left(self.tage, k); out = []
        while i < len(self.tage) and self.tage[i][:7] == k: out.append(self.tage[i]); i += 1
        return out

    def anzahl_zwischen(self, d0, d1):
        """Handelstage t mit d0 < t <= d1 (wie v1 `handelstage_zwischen`)."""
        return max(0, bisect.bisect_right(self.tage, d1) - bisect.bisect_right(self.tage, d0))

    def vorheriger(self, d):
        i = bisect.bisect_left(self.tage, d)
        return self.tage[i - 1] if i > 0 else None

    def naechster(self, d):
        i = bisect.bisect_right(self.tage, d)
        return self.tage[i] if i < len(self.tage) else None

    def termine(self, heute):
        """Monatswechsel-Kauf (vorletzter Handelstag), -Verkauf (3. Handelstag), TSMOM-Tag (letzter Handelstag), Nummer im Monat."""
        j, m = int(heute[:4]), int(heute[5:7])
        tage = self.monat(j, m)
        vj, vm = (j - 1, 12) if m == 1 else (j, m - 1)
        vor = self.monat(vj, vm)
        return dict(tage=tage, nr=tage.index(heute) if heute in tage else None,
                    mw_kauf=len(tage) >= 2 and heute == tage[-2], mw_verkauf=len(tage) >= 3 and heute == tage[2],
                    tsmom_tag=bool(tage) and heute == tage[-1], letzter_vormonat=vor[-1] if vor else None)

    def kommende_termine(self, heute, tage_voraus=35):
        """Liste (datum, text) für STATUS.md: MW-Kauf/-Verkauf, TSMOM, Halbtage, Feiertage (Werktage ohne Handel)."""
        ende = (dt.date.fromisoformat(heute) + dt.timedelta(days=tage_voraus)).isoformat()
        out = []
        for d in self.tage:
            if d <= heute or d > ende: continue
            t = self.termine(d)
            if t['mw_kauf']: out.append((d, 'Monatswechsel-Kauf (vorletzter Handelstag)'))
            if t['tsmom_tag']: out.append((d, 'TSMOM-Umschichtung (letzter Handelstag)'))
            if t['mw_verkauf']: out.append((d, 'Monatswechsel-Verkauf (3. Handelstag)'))
            if self.schluss.get(d, '16:00') < '16:00': out.append((d, f'Halbtag, Schluss {self.schluss[d]} ET'))
        d = dt.date.fromisoformat(heute) + dt.timedelta(days=1)
        letzter = self.tage[-1] if self.tage else heute
        while d.isoformat() <= min(ende, letzter):
            if d.weekday() < 5 and d.isoformat() not in self._pos: out.append((d.isoformat(), 'Feiertag – kein Handel'))
            d += dt.timedelta(days=1)
        return sorted(out)


# ---------- Entscheidung ----------
def _q(leg):
    return leg['richtung'] * leg['stueck']


def tsmom_nachholen(zustand, termine):
    """Review 5.4: TSMOM-Umschichtung nachholen, wenn die letzte Umschichtung vor dem letzten Handelstag des Vormonats liegt."""
    letzte = zustand.get('letzte_tsmom')
    return bool(letzte and termine['letzter_vormonat'] and letzte < termine['letzter_vormonat'] and not termine['tsmom_tag'])


def entscheide(zustand, kurse_heute, historie, kalender, param=None, kz=None):
    """Reine Entscheidungsfunktion (SPEC Grundsatz „ein Codepfad“).

    zustand: dict(heute ISO, equity, hwm, legs [...], leihbar {sym: bool}, letzte_tsmom ISO|None, aufgeschoben [...])
    kurse_heute: {sym: {px, hi, lo}} inkl. '^VIX'/'^VIX3M' ({px}); historie: {sym: [(datum, o, h, l, c)]}; kalender: Kalender
    param: Replay-Schalter (PARAM); kz: vorab berechnete kennzahlen(historie, kurse_heute) (nur Replay, spart Zeit)
    → (ausstiege [(leg, grund)], einstiege [leg], info dict)
    Die Eingaben werden nicht verändert; Halte-Verlängerungen der IBS-Legs stehen in info['datum_neu'].
    """
    p = dict(PARAM, **(param or {}))
    heute = zustand['heute']; eq = zustand['equity']
    hwm = max(zustand.get('hwm') or eq, eq); dd = 1 - eq / hwm
    faktor = p['bremse_faktor'] if dd >= p['bremse_dd'] else 1.0
    if kz is None: kz = kennzahlen(historie, kurse_heute)
    ratio = vix_verhaeltnis(kurse_heute)
    t = kalender.termine(heute)
    tsmom_nach = tsmom_nachholen(zustand, t)
    tsmom_tag = t['tsmom_tag'] or tsmom_nach
    leihbar = zustand.get('leihbar') or {}
    log = []; datum_neu = {}
    legs = zustand['legs']

    # 1) Ausstiege – Reihenfolge der Legs wie im Zustand (wie v1)
    ausstiege = []
    for leg in legs:
        s, k = leg['symbol'], kz.get(leg['symbol'])
        if k is None:
            log.append(f"WARNUNG: kein Kurs für offenes Leg {leg.get('id')} {leg['strategie']} {s} – heute kein Ausstieg möglich"); continue
        st_ = leg['strategie']
        if leg.get('ausstieg_offen'):                                                     # Review 3.5: gestern abgelehnt/nicht gefüllt → heute nachholen
            ausstiege.append((leg, f"{leg['ausstieg_offen'].get('grund', 'Ausstieg')} (nachgeholt)")); continue
        if st_ in IBS_FAMILIE and leg['datum'] < heute:
            if k['ibs'] >= IBS_SCHWELLE: ausstiege.append((leg, 'IBS Ausstieg Folgetag'))
            else: datum_neu[leg.get('id')] = heute                                       # Folgesignal: halten, Tag neu zählen
        elif st_ == 'BB':
            alter = kalender.anzahl_zwischen(leg['datum'], heute)
            if k['px'] > k['sma20']: ausstiege.append((leg, 'BB über SMA20'))
            elif alter >= BB_MAX_TAGE: ausstiege.append((leg, 'BB Tag 15'))
        elif st_ in ('MW', 'MW_LAND'):
            if t['mw_verkauf']: ausstiege.append((leg, 'Monatswechsel Verkauf'))
            elif t['nr'] is not None and t['nr'] > 2 and leg['datum'][:7] < heute[:7]:    # Review 5.4: Verkauf verpasst → nachholen
                ausstiege.append((leg, 'Monatswechsel Verkauf (nachgeholt)'))
        elif st_ == 'TSMOM' and tsmom_tag: ausstiege.append((leg, 'TSMOM Umschichtung' + (' (nachgeholt)' if tsmom_nach else '')))
        elif st_ == 'VIX' and ratio is not None and ratio < VIX_AUS: ausstiege.append((leg, 'VIX Backwardation'))

    # 2) Einstiege nach Vorrang mit Brutto-Deckel (überspringen, nicht skalieren)
    aus_ids = {id(l) for l, _ in ausstiege}
    bleibende = [l for l in legs if id(l) not in aus_ids]
    neu = []
    offen = lambda strat: [l for l in bleibende + neu if l['strategie'] == strat]
    hat = lambda strat, s: any(l['symbol'] == s for l in offen(strat))

    def brutto(ls):
        return sum(abs(l['stueck'] * kz.get(l['symbol'], {}).get('px', l.get('einstieg') or 0)) for l in ls)

    deckel = {'wert': p['max_brutto'] * eq}

    def plane(strat, sym, richtung, anteil=None, stueck=None, extra=None):
        if sym not in kz or strat not in p['strategien']: return
        nominal = anteil * eq * faktor if stueck is None else stueck * kz[sym]['px']
        if brutto(bleibende + neu) + nominal > deckel['wert']: log.append(f'{strat} {sym}: Brutto-Deckel, übersprungen'); return
        st_ = int(nominal / kz[sym]['px']) if stueck is None else stueck
        if st_ < 1: log.append(f'{strat} {sym}: unter 1 Stück, entfällt'); return
        leg = dict(id=None, strategie=strat, symbol=sym, richtung=richtung, stueck=st_, einstieg=None, datum=heute, atr20=round(kz[sym]['atr20'], 4))
        if extra: leg.update(extra)
        neu.append(leg)

    index_signal = any(kz[s]['ibs'] < IBS_SCHWELLE for s in INDEX if s in kz)
    gew = tsmom_gewichte(kz) if tsmom_tag else {}
    if tsmom_tag and p['tsmom_reserve']:                                                   # K4-Variante (nur Replay): Brutto für TSMOM vorab reservieren
        reserve = sum(abs(w) for s, w in gew.items() if w > 0 or leihbar.get(s)) * eq * faktor
        deckel['wert'] = p['max_brutto'] * eq - reserve
    aufgeschoben = list(zustand.get('aufgeschoben') or [])

    def nachholen(strat):
        """Durch die Vorzeichenwechsel-Sperre aufgeschobene Teile mehrtägiger Strategien (Review 3.2) – vor neuen Signalen."""
        for a in [a for a in aufgeschoben if a['strategie'] == strat]:
            k = kz.get(a['symbol'])
            if k is None: continue
            gilt = {'TSMOM': not tsmom_tag,
                    'MW': not (t['nr'] is not None and t['nr'] >= 2 and a['datum'][:7] < heute[:7]),
                    'MW_LAND': not (t['nr'] is not None and t['nr'] >= 2 and a['datum'][:7] < heute[:7]),
                    'BB': not (k['px'] > k['sma20'] or kalender.anzahl_zwischen(a['datum'], heute) >= BB_MAX_TAGE),
                    'VIX': ratio is not None and ratio >= VIX_AUS and not offen('VIX')}.get(strat, False)
            if gilt: plane(strat, a['symbol'], a['richtung'], stueck=a['stueck'], extra=dict(datum=a['datum'], nachgeholt=True))
            else: log.append(f"aufgeschobenes {strat} {a['symbol']} {a['stueck']} verfällt (Regel greift heute nicht mehr)")

    for strat in VORRANG:
        if strat == 'TSMOM': deckel['wert'] = p['max_brutto'] * eq                      # Reserve gilt nur für die vorrangigen Strategien
        nachholen(strat)
        if strat == 'IBS':
            for s in INDEX:
                if s in kz and kz[s]['ibs'] < IBS_SCHWELLE and not hat('IBS', s): plane('IBS', s, 1, GROESSE['IBS'])
        elif strat == 'MW' and t['mw_kauf']:
            for s in INDEX:
                if s in kz and not hat('MW', s): plane('MW', s, 1, GROESSE['MW'])
        elif strat == 'BB':
            for s in INDEX:
                if ist_bb_signal(kz.get(s)) and len(offen('BB')) < MAX_OFFEN['BB'] and not hat('BB', s): plane('BB', s, 1, GROESSE['BB'])
        elif strat == 'IBS_SEKTOR' and not index_signal and not offen('IBS'):
            for s in sorted([s for s in SEKTOREN if s in kz and kz[s]['ibs'] < IBS_SCHWELLE], key=lambda s: kz[s]['ibs']):
                if len(offen('IBS_SEKTOR')) < MAX_OFFEN['IBS_SEKTOR'] and not hat('IBS_SEKTOR', s): plane('IBS_SEKTOR', s, 1, GROESSE['IBS_SEKTOR'])
        elif strat == 'IBS_LAND':
            for s in sorted([s for s in LAENDER if s in kz and kz[s]['ibs'] < IBS_SCHWELLE], key=lambda s: kz[s]['ibs']):
                if len(offen('IBS_LAND')) < MAX_OFFEN['IBS_LAND'] and not hat('IBS_LAND', s): plane('IBS_LAND', s, 1, GROESSE['IBS_LAND'])
        elif strat == 'TSMOM' and tsmom_tag:
            for s, w in sorted(gew.items(), key=lambda x: -abs(x[1])):
                if w < 0 and not leihbar.get(s): log.append(f'TSMOM {s}: Short nicht leihbar – übersprungen'); continue
                plane('TSMOM', s, 1 if w > 0 else -1, abs(w))
        elif strat == 'MW_LAND' and t['mw_kauf']:
            for s in MW_LAND:
                if s in kz and not hat('MW_LAND', s): plane('MW_LAND', s, 1, GROESSE['MW_LAND'])
        elif strat == 'VIX':
            if ratio is not None and ratio > VIX_EIN and VIX_ETF in kz and not offen('VIX'): plane('VIX', VIX_ETF, 1, GROESSE['VIX'])

    info = dict(heute=heute, faktor=faktor, dd=dd, hwm=hwm, ratio=ratio, index_signal=index_signal, tsmom_tag=tsmom_tag,
                tsmom_nachgeholt=tsmom_nach, mw_kauf=t['mw_kauf'], mw_verkauf=t['mw_verkauf'], datum_neu=datum_neu,
                kz=kz, gewichte=gew, log=log)
    return ausstiege, neu, info


def netto_plan(ausstiege, einstiege):
    """Netto-Delta je Symbol wie v1 (vor der Vorzeichenwechsel-Sperre): {sym: Stück, + kaufen / − verkaufen}."""
    delta = {}
    for a in ausstiege:
        leg = a[0]; menge = a[2] if len(a) > 2 else leg['stueck']
        delta[leg['symbol']] = delta.get(leg['symbol'], 0) - leg['richtung'] * menge
    for leg in einstiege: delta[leg['symbol']] = delta.get(leg['symbol'], 0) + leg['richtung'] * leg['stueck']
    return {s: d for s, d in delta.items() if d != 0}


def _vorrang_index(strat):
    return VORRANG.index(strat) if strat in VORRANG else len(VORRANG)


def netto_orders(legs, ausstiege, einstiege, sperre='beide'):
    """Netto-Orders je Symbol mit Vorzeichenwechsel-Sperre (Review 3.2).

    Alpaca kann eine Position nicht in einem Zug (und nicht mit zwei MOC-Orders am selben Tag) von long auf short drehen.
    Würde die Netto-Position eines Symbols heute durch null gehen, wird nur bis null gehandelt. Der überschießende Teil wird
    von den nachrangigsten Einstiegen (danach von bleibenden Legs derselben Richtung) abgezogen:
    mehrtägige Strategien (MEHRTAGIG) → `aufgeschoben` (Nachholen im nächsten Lauf), IBS-Familie → `verfallen`.
    sperre: 'beide' (Standard), 'verkauf' (nur long→short gesperrt), 'aus' (wie v1, nur Replay-Vergleich).

    → dict(orders {sym: delta}, ausstiege [(leg, grund, menge)], einstiege [leg (Kopie, ggf. reduziert)],
           aufgeschoben [dict], verfallen [dict], gekreuzt [sym])
    """
    aus = [(a[0], a[1], a[2] if len(a) > 2 else a[0]['stueck']) for a in ausstiege]
    ein = [dict(l) for l in einstiege]
    aufgeschoben, verfallen, gekreuzt = [], [], []
    symbole = []
    for l in [a[0] for a in aus] + ein:
        if l['symbol'] not in symbole: symbole.append(l['symbol'])
    orders = {}
    for s in symbole:
        P = sum(_q(l) for l in legs if l['symbol'] == s)
        X = sum(l['richtung'] * m for l, _, m in aus if l['symbol'] == s)
        E = sum(_q(l) for l in ein if l['symbol'] == s)
        T = P - X + E
        gesperrt = P != 0 and T != 0 and (P > 0) != (T > 0) and (sperre == 'beide' or (sperre == 'verkauf' and P > 0))
        if gesperrt:
            gekreuzt.append(s)
            rest = abs(T); vz = 1 if T > 0 else -1
            # a) Einstiege in Richtung des Überschusses, nachrangigste zuerst
            kandidaten = sorted([(i, l) for i, l in enumerate(ein) if l['symbol'] == s and l['richtung'] == vz],
                                key=lambda il: (-_vorrang_index(il[1]['strategie']), -il[0]))
            for _, l in kandidaten:
                if rest <= 0: break
                r = min(l['stueck'], rest); rest -= r; l['stueck'] -= r
                teil = dict(strategie=l['strategie'], symbol=s, richtung=vz, stueck=r, datum=l['datum'], atr20=l.get('atr20'),
                            grund='Vorzeichenwechsel-Sperre (Einstieg)')
                (aufgeschoben if l['strategie'] in MEHRTAGIG else verfallen).append(teil)
            # b) bleibende Legs in Richtung des Überschusses: heute mit glattstellen
            if rest > 0:
                aus_ids = {id(l) for l, _, _ in aus}
                bleib = sorted([l for l in legs if l['symbol'] == s and l['richtung'] == vz and id(l) not in aus_ids],
                               key=lambda l: (-_vorrang_index(l['strategie']), -(l.get('id') or 0)))
                for l in bleib:
                    if rest <= 0: break
                    r = min(l['stueck'], rest); rest -= r
                    aus.append((l, 'Vorzeichenwechsel-Sperre (glattgestellt)', r))
                    teil = dict(strategie=l['strategie'], symbol=s, richtung=vz, stueck=r, datum=l['datum'], atr20=l.get('atr20'),
                                grund='Vorzeichenwechsel-Sperre (Bestand)')
                    (aufgeschoben if l['strategie'] in MEHRTAGIG else verfallen).append(teil)
            ein = [l for l in ein if l['stueck'] > 0]
            T = 0
        if T - P != 0: orders[s] = T - P
    return dict(orders=orders, ausstiege=aus, einstiege=ein, aufgeschoben=aufgeschoben, verfallen=verfallen, gekreuzt=gekreuzt)


def verteile_fill(komponenten, gefuellt):
    """Netto-Fill eines Symbols auf die Legs verteilen (SPEC Aufgabe 2, Review 3.1).

    komponenten: Liste dict(art 'aus'|'ein', menge > 0, seite +1 Kauf / −1 Verkauf, strategie, leg_id, nr)
    gefuellt: tatsächlich gefüllte Stück der Netto-Order (+ Kauf, − Verkauf), 0 bei Ablehnung/Storno.
    Was sich innerhalb des Symbols aufhebt (Kauf gegen Verkauf), ist ohne Börse erledigt. Auf der Netto-Seite bekommen zuerst
    die Ausstiege (FIFO: ältestes Leg zuerst), dann die Einstiege in Vorrang-Reihenfolge den Fill.
    → Liste erledigter Mengen je Komponente (gleiche Reihenfolge).
    """
    B = sum(k['menge'] for k in komponenten if k['seite'] > 0)
    S = sum(k['menge'] for k in komponenten if k['seite'] < 0)
    if B >= S: voll, teil, verfuegbar = -1, 1, S + max(0, gefuellt)
    else: voll, teil, verfuegbar = 1, -1, B + max(0, -gefuellt)
    erledigt = [0] * len(komponenten)
    reihe = sorted([i for i, k in enumerate(komponenten) if k['seite'] == teil],
                   key=lambda i: (komponenten[i]['art'] != 'aus',
                                  komponenten[i].get('leg_id') or 0 if komponenten[i]['art'] == 'aus' else _vorrang_index(komponenten[i]['strategie']),
                                  komponenten[i].get('nr', i)))
    for i, k in enumerate(komponenten):
        if k['seite'] == voll: erledigt[i] = k['menge']
    for i in reihe:
        r = min(komponenten[i]['menge'], max(0, verfuegbar)); erledigt[i] = r; verfuegbar -= r
    return erledigt


# ---------- Not-Aus und Abschaltkriterium ----------
def notaus(equity, startkapital):
    return bool(startkapital) and equity < NOTAUS * startkapital


def abschaltkriterium(equity_reihe):
    """K5 aus der eigenen Tageskurve (Liste Equity-Werte ab Bot-Start, ältester zuerst).
    → dict(rendite_12m, drawdown, sharpe_250, verletzt [Texte])"""
    n = len(equity_reihe); out = dict(rendite_12m=None, drawdown=None, sharpe_250=None, verletzt=[], tage=n)
    if not n: return out
    hoch = max(equity_reihe); out['drawdown'] = 1 - equity_reihe[-1] / hoch
    if n > 252: out['rendite_12m'] = equity_reihe[-1] / equity_reihe[-253] - 1
    if n > 250:
        r = [equity_reihe[i] / equity_reihe[i - 1] - 1 for i in range(n - 250, n)]
        mu = sum(r) / len(r); sd = (sum((x - mu) ** 2 for x in r) / (len(r) - 1)) ** 0.5
        out['sharpe_250'] = mu / sd * 252 ** 0.5 if sd > 0 else 0.0
    eps = 1e-12                                                                          # 1 − 66/100 = 0,33999… soll als 34 % zählen
    if out['rendite_12m'] is not None and out['rendite_12m'] <= K5_RENDITE_12M + eps: out['verletzt'].append(f"12-Monats-Rendite {out['rendite_12m']:.1%} ≤ {K5_RENDITE_12M:.0%}")
    if out['drawdown'] >= K5_DRAWDOWN - eps: out['verletzt'].append(f"Drawdown {out['drawdown']:.1%} ≥ {K5_DRAWDOWN:.0%}")
    if out['sharpe_250'] is not None and out['sharpe_250'] <= K5_SHARPE_250 + eps: out['verletzt'].append(f"250-Tage-Sharpe {out['sharpe_250']:.2f} ≤ {K5_SHARPE_250:.2f}")
    return out
