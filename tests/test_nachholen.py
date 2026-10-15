"""Nachholen verpasster Termine (Review 5.4) und Datenquellen (Review 1.3/4.4)."""
import kern


def kz_flach(px=100.0, ibs=0.5):
    return dict(px=px, hi=px + 1, lo=px - 1, ibs=ibs, atr20=1.0, sma20=px, sma200=px * 0.9, bb_unten=px * 0.9, ret12=0.1, vol60=0.15)


def zustand(legs, heute, **x):
    z = dict(heute=heute, equity=100000.0, hwm=100000.0, legs=legs, leihbar={}, letzte_tsmom=None, aufgeschoben=[]); z.update(x)
    return z


KAL = kern.Kalender.nach_regeln('2026-08-01', '2027-02-28')
KZ = {s: kz_flach() for s in kern.ALLE_SYMBOLE}


def test_mw_verkauf_nach_verpasstem_dritten_handelstag():
    mw = dict(id=1, strategie='MW', symbol='SPY', richtung=1, stueck=10, datum='2026-09-29', atr20=1.0)
    # 3. Handelstag Oktober = 05.10.2026; Lauf fiel aus → 06.10. wird nachgeholt
    aus, ein, info = kern.entscheide(zustand([mw], '2026-10-06'), {}, {}, KAL, kz=KZ)
    assert [(l['id'], g) for l, g in aus] == [(1, 'Monatswechsel Verkauf (nachgeholt)')]
    # am 2. Handelstag noch nicht
    aus, *_ = kern.entscheide(zustand([mw], '2026-10-02'), {}, {}, KAL, kz=KZ)
    assert aus == []


def test_mw_kauf_wird_nicht_nachgeholt():
    aus, ein, info = kern.entscheide(zustand([], '2026-10-01'), {}, {}, KAL, kz=KZ)    # Kauftag 29.09. verpasst
    assert not [l for l in ein if l['strategie'] in ('MW', 'MW_LAND')]


def test_tsmom_nach_verpasstem_monatsletzten():
    alt = dict(id=5, strategie='TSMOM', symbol='GLD', richtung=1, stueck=10, datum='2026-08-31', atr20=1.0)
    z = zustand([alt], '2026-10-01', letzte_tsmom='2026-08-31')                       # 30.09. ausgefallen
    aus, ein, info = kern.entscheide(z, {}, {}, KAL, kz=KZ)
    assert info['tsmom_tag'] and info['tsmom_nachgeholt']
    assert (alt, 'TSMOM Umschichtung (nachgeholt)') in aus
    assert {l['symbol'] for l in ein if l['strategie'] == 'TSMOM'}
    # regulär umgeschichtet → kein Nachholen
    z = zustand([alt], '2026-10-01', letzte_tsmom='2026-09-30')
    assert not kern.entscheide(z, {}, {}, KAL, kz=KZ)[2]['tsmom_tag']


def test_abgelehnter_ausstieg_wird_nachgeholt():
    leg = dict(id=3, strategie='BB', symbol='QQQ', richtung=1, stueck=5, datum='2026-10-01', atr20=1.0,
               ausstieg_offen=dict(grund='BB über SMA20', datum='2026-10-05'))
    aus, *_ = kern.entscheide(zustand([leg], '2026-10-06'), {}, {}, KAL, kz=KZ)
    assert aus == [(leg, 'BB über SMA20 (nachgeholt)')]


def test_aufgeschobenes_tsmom_short_wird_eroeffnet():
    a = dict(strategie='TSMOM', symbol='IWM', richtung=-1, stueck=20, datum='2026-09-30', atr20=1.0)
    aus, ein, info = kern.entscheide(zustand([], '2026-10-01', aufgeschoben=[a]), {}, {}, KAL, kz=KZ)
    assert [(l['strategie'], l['symbol'], l['richtung'], l['stueck'], l['datum']) for l in ein if l['strategie'] == 'TSMOM'] == [('TSMOM', 'IWM', -1, 20, '2026-09-30')]


def test_snapshot_hoch_tief_aus_sip_letzter_kurs_juengster_trade():
    import systembuch_bot as b
    iex = {'EWL': {'latestTrade': {'p': 50.10, 't': '2026-10-15T19:44:59Z'}, 'dailyBar': {'h': 50.4, 'l': 49.9}}}
    sip = {'EWL': {'latestTrade': {'p': 50.00, 't': '2026-10-15T19:30:00Z'}, 'dailyBar': {'h': 50.9, 'l': 49.2}}}
    r = b.snapshot_zusammenfuehren(iex, sip)['EWL']
    assert r == dict(px=50.10, hi=50.9, lo=49.2)
    # kein Trade heute: Mitte aus Quote
    r = b.snapshot_zusammenfuehren({'EWP': {'latestQuote': {'ap': 30.2, 'bp': 30.0}}}, {})['EWP']
    assert abs(r['px'] - 30.1) < 1e-9
