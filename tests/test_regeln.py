"""SPEC Aufgabe 6: Rechenregeln und mindestens ein Test je Regel aus der README-Tabelle (ohne Netz)."""
import math
import pytest
import kern

KAL = kern.Kalender.nach_regeln('2026-08-01', '2027-03-31')


# ---------- Rechenregeln ----------
def reihe(closes, spanne=1.0, start='2025-01-01'):
    """Historie mit Schluss c, Hoch c+spanne, Tief c−spanne."""
    return [(f'd{i:04d}', c, c + spanne, c - spanne, c) for i, c in enumerate(closes)]


def test_ibs_berechnung_und_klemmung():
    h = {'X': reihe([100.0] * 60)}
    assert kern.kennzahlen(h, {'X': dict(px=101.0, hi=104.0, lo=99.0)})['X']['ibs'] == pytest.approx(0.4)
    # Tagesbar hinkt nach: letzter Kurs unter dem Tief → Tief = Kurs → IBS 0
    assert kern.kennzahlen(h, {'X': dict(px=98.0, hi=104.0, lo=99.0)})['X']['ibs'] == 0.0
    assert kern.kennzahlen(h, {'X': dict(px=105.0, hi=104.0, lo=99.0)})['X']['ibs'] == 1.0
    assert kern.kennzahlen(h, {'X': dict(px=100.0, hi=100.0, lo=100.0)})['X']['ibs'] == 0.5
    assert 'X' not in kern.kennzahlen({'X': reihe([100.0] * 59)}, {'X': dict(px=1, hi=1, lo=1)})   # < 60 Tage Historie


def test_bollinger_mit_heutigem_kurs_ddof1():
    c = [100.0 + (i % 5) for i in range(240)]
    k = kern.kennzahlen({'X': reihe(c)}, {'X': dict(px=95.0, hi=96, lo=94)})['X']
    letzte = c[-19:] + [95.0]
    mu = sum(letzte) / 20; sd = math.sqrt(sum((x - mu) ** 2 for x in letzte) / 19)
    assert k['sma20'] == pytest.approx(mu) and k['bb_unten'] == pytest.approx(mu - 2 * sd)
    assert k['sma200'] == pytest.approx((sum(c[-199:]) + 95.0) / 200)


def test_atr20_true_range():
    rows = [(f'd{i}', 100, 101, 99, 100) for i in range(59)] + [('d59', 100, 110, 100, 105)]
    k = kern.kennzahlen({'X': rows}, {'X': dict(px=105, hi=106, lo=104)})['X']
    assert k['atr20'] == pytest.approx((19 * 2 + 10) / 20)                      # 19 Tage TR 2, letzter Tag TR 10 (Lücke zum Vortag)


def test_12m_rendite_und_vol60():
    c = [100.0 * 1.001 ** i for i in range(300)]
    k = kern.kennzahlen({'X': reihe(c)}, {'X': dict(px=c[-1] * 1.001, hi=c[-1] * 1.002, lo=c[-1])})['X']
    assert k['ret12'] == pytest.approx(1.001 ** 252 - 1)
    assert k['vol60'] == pytest.approx(0.0, abs=1e-9)


def test_tsmom_gewichte_deckel():
    kz = {s: dict(ret12=0.1 if i % 2 else -0.1, vol60=0.01) for i, s in enumerate(kern.TSMOM)}   # Vol unter 2 % → Boden
    g = kern.tsmom_gewichte(kz)
    # je Symbol: 10 %/max(1 %, 2 %) = 5 → Deckel 2,0; Summe 40 → ×0,1 (Roh-Brutto 4,0); ×0,36 → 0,072; Brutto 1,44 → ×0,6/1,44 → 0,03
    assert all(abs(w) == pytest.approx(0.03) for w in g.values())
    assert sum(abs(w) for w in g.values()) == pytest.approx(0.60)
    assert g['SPY'] < 0 and g['QQQ'] > 0                                                        # Vorzeichen der 12M-Rendite
    kz2 = {'GLD': dict(ret12=0.2, vol60=0.20)}
    assert kern.tsmom_gewichte(kz2)['GLD'] == pytest.approx(0.5 * 0.36)                         # 10 %/20 % = 0,5, Summe < 4, Brutto < 60 %


# ---------- Hilfen für Regeltests ----------
def kz(px=100.0, ibs=0.5, sma20=None, sma200=90.0, bb_unten=None, **x):
    d = dict(px=px, hi=px + 1, lo=px - 1, ibs=ibs, atr20=1.0, sma20=px if sma20 is None else sma20, sma200=sma200,
             bb_unten=px * 0.9 if bb_unten is None else bb_unten, ret12=0.1, vol60=0.15); d.update(x); return d


def alle(**ueber):
    k = {s: kz() for s in kern.ALLE_SYMBOLE}; k.update(ueber); return k


def lauf(K, heute='2026-10-14', legs=(), equity=100000.0, hwm=None, kurse=None, **z):
    zs = dict(heute=heute, equity=equity, hwm=hwm or equity, legs=list(legs), leihbar={s: True for s in kern.TSMOM}, letzte_tsmom=None, aufgeschoben=[])
    zs.update(z)
    return kern.entscheide(zs, kurse or {}, {}, KAL, kz=K)


def ein(r, strat=None):
    return [(l['strategie'], l['symbol'], l['richtung'] * l['stueck']) for l in r[1] if strat is None or l['strategie'] == strat]


def leg(i, strat, sym, st=10, datum='2026-10-13', richtung=1, **x):
    d = dict(id=i, strategie=strat, symbol=sym, richtung=richtung, stueck=st, datum=datum, atr20=1.0, einstieg=100.0); d.update(x); return d


# ---------- README-Tabelle ----------
def test_ibs_kauf_unter_0_2_mit_25_prozent():
    r = lauf(alle(SPY=kz(ibs=0.19), QQQ=kz(ibs=0.2)))
    assert ein(r, 'IBS') == [('IBS', 'SPY', 250)]                                # 25 % von 100.000 / 100 $


def test_ibs_ausstieg_folgetag_und_halten_bei_folgesignal():
    a, b = leg(1, 'IBS', 'SPY'), leg(2, 'IBS', 'QQQ')
    aus, neu, info = lauf(alle(SPY=kz(ibs=0.5), QQQ=kz(ibs=0.1)), legs=[a, b])
    assert [(l['symbol'], g) for l, g in aus] == [('SPY', 'IBS Ausstieg Folgetag')]
    assert info['datum_neu'] == {2: '2026-10-14'}
    assert not [l for l in neu if l['symbol'] == 'QQQ' and l['strategie'] == 'IBS']    # gehaltenes Leg wird nicht verdoppelt


def test_ibs_sektor_nur_ohne_index_signal_max_4_niedrigster_zuerst():
    ibs = dict(XLB=0.15, XLE=0.05, XLF=0.10, XLI=0.01, XLK=0.12, XLP=0.3)
    K = alle(**{s: kz(ibs=v) for s, v in ibs.items()})
    assert [s for _, s, _ in ein(lauf(K), 'IBS_SEKTOR')] == ['XLI', 'XLE', 'XLF', 'XLK']
    assert [st for _, _, st in ein(lauf(K), 'IBS_SEKTOR')] == [110] * 4          # 11 %
    K['DIA'] = kz(ibs=0.1)
    assert ein(lauf(K), 'IBS_SEKTOR') == []


def test_ibs_land_max_4_bestand_zaehlt_mit():
    K = alle(**{s: kz(ibs=0.05 + i * 0.01) for i, s in enumerate(kern.LAENDER[:6])})
    assert [s for _, s, _ in ein(lauf(K), 'IBS_LAND')] == list(kern.LAENDER[:4])
    gehalten = [leg(1, 'IBS_LAND', 'EWZ', datum='2026-10-13'), leg(2, 'IBS_LAND', 'EWL')]
    K.update(EWZ=kz(ibs=0.1), EWL=kz(ibs=0.1))                                     # Folgesignal → beide gehalten
    assert len(ein(lauf(K, legs=gehalten), 'IBS_LAND')) == 2
    assert ein(lauf(K), 'IBS_LAND')[0][2] == 70                                   # 7 %


def test_bb_einstieg_stop_ausstieg():
    K = alle(SPY=kz(px=100, sma200=90, bb_unten=101, sma20=105), QQQ=kz(px=100, sma200=110, bb_unten=101))
    assert ein(lauf(K), 'BB') == [('BB', 'SPY', 250)]                             # QQQ unter SMA200 → kein Signal
    alt = leg(1, 'BB', 'DIA', datum='2026-10-01')
    aus, *_ = lauf(alle(DIA=kz(px=100, sma20=99)), legs=[alt])
    assert aus == [(alt, 'BB über SMA20')]
    alt15 = leg(2, 'BB', 'DIA', datum='2026-09-23')                                # 15 Handelstage bis 14.10.
    aus, *_ = lauf(alle(DIA=kz(px=100, sma20=101)), legs=[alt15])
    assert aus == [(alt15, 'BB Tag 15')]
    alt14 = leg(3, 'BB', 'DIA', datum='2026-09-24')
    assert lauf(alle(DIA=kz(px=100, sma20=101)), legs=[alt14])[0] == []
    assert kern.BB_STOP_ATR == 3.0


def test_bb_hoechstens_vier():
    K = alle(**{s: kz(px=100, sma200=90, bb_unten=101) for s in kern.INDEX})
    bestand = [leg(i, 'BB', s, datum='2026-10-13') for i, s in enumerate(('SPY', 'QQQ', 'DIA'))]
    K.update({s: kz(px=100, sma200=90, bb_unten=101, sma20=101) for s in ('SPY', 'QQQ', 'DIA')})
    assert [s for _, s, _ in ein(lauf(K, legs=bestand), 'BB')] == ['IWM']


def test_monatswechsel_kauf_vorletzter_verkauf_dritter_tag():
    assert {s for _, s, _ in ein(lauf(alle(), heute='2026-10-29'), 'MW')} == set(kern.INDEX)      # 29.10. vorletzter Handelstag
    assert ein(lauf(alle(), heute='2026-10-28'), 'MW') == []
    mw = leg(1, 'MW', 'SPY', datum='2026-10-29')
    assert lauf(alle(), heute='2026-11-04', legs=[mw])[0] == [(mw, 'Monatswechsel Verkauf')]    # 3. Handelstag November
    assert lauf(alle(), heute='2026-11-03', legs=[mw])[0] == []


def test_monatswechsel_land_12_etfs_4_prozent():
    r = ein(lauf(alle(), heute='2026-10-29'), 'MW_LAND')
    assert [s for _, s, _ in r] == list(kern.MW_LAND) and all(n == 40 for _, _, n in r)


def test_tsmom_letzter_handelstag_long_short_leihbar():
    K = alle(**{s: kz(ret12=-0.1 if s in ('TLT', 'EWG') else 0.1, vol60=0.15) for s in kern.TSMOM})
    assert ein(lauf(K, heute='2026-10-29'), 'TSMOM') == []
    r = lauf(K, heute='2026-10-30', leihbar={s: s != 'EWG' for s in kern.TSMOM})
    t = {s: n for _, s, n in ein(r, 'TSMOM')}
    assert t['TLT'] < 0 and 'EWG' not in t and t['GLD'] > 0
    assert 'TSMOM EWG: Short nicht leihbar – übersprungen' in r[2]['log']
    assert sum(abs(n) * 100.0 for n in t.values()) <= 0.60 * 100000 + 100


def test_vix_kontango_ein_aus_halten():
    k = lambda r: {'^VIX': {'px': 20.0}, '^VIX3M': {'px': 20.0 * r}}
    assert ein(lauf(alle(), kurse=k(1.02)), 'VIX') == [('VIX', 'SVXY', 100)]       # 10 %
    assert ein(lauf(alle(), kurse=k(1.005)), 'VIX') == []
    v = leg(1, 'VIX', 'SVXY')
    assert lauf(alle(), kurse=k(1.005), legs=[v])[0] == []                        # zwischen 1,00 und 1,01: halten
    assert lauf(alle(), kurse=k(0.99), legs=[v])[0] == [(v, 'VIX Backwardation')]
    assert lauf(alle(), kurse={}, legs=[v])[0] == []                              # VIX fehlt: kein Ausstieg, kein Einstieg


def test_brutto_deckel_ueberspringt_nach_vorrang():
    """IBS (4 × 25 %) + MW (4 × 25 %) = 200 % > 190 % → das letzte MW-Leg wird übersprungen, nicht verkleinert."""
    K = alle(**{s: kz(ibs=0.1) for s in kern.INDEX})
    r = lauf(K, heute='2026-10-29')
    assert [s for _, s, _ in ein(r, 'IBS')] == list(kern.INDEX)
    assert [s for _, s, _ in ein(r, 'MW')] == ['SPY', 'QQQ', 'DIA']
    assert 'MW IWM: Brutto-Deckel, übersprungen' in r[2]['log']
    assert all(n == 250 for _, _, n in ein(r, 'MW'))


def test_bremse_halbiert_ab_15_prozent():
    K = alle(SPY=kz(ibs=0.1))
    assert ein(lauf(K, equity=85000, hwm=100000), 'IBS') == [('IBS', 'SPY', 106)]     # 25 % × 85.000 × 0,5 / 100
    assert ein(lauf(K, equity=85100, hwm=100000), 'IBS') == [('IBS', 'SPY', 212)]


def test_not_aus_unter_70_prozent():
    assert kern.notaus(69999, 100000) and not kern.notaus(70000, 100000)


def test_abschaltkriterium_schwellen():
    assert kern.abschaltkriterium([100, 66])['verletzt'] == ['Drawdown 34.0% ≥ 34%']
    assert kern.abschaltkriterium([100, 67])['verletzt'] == []
    jahr = [100 * (1 - 0.25 * i / 252) for i in range(253)]
    assert any('12-Monats' in v for v in kern.abschaltkriterium(jahr)['verletzt'])
    assert kern.abschaltkriterium(jahr[:252])['rendite_12m'] is None               # erst ab Tag 252
    fallend = [100 * 0.999 ** i * (1 + 0.001 * (-1) ** i) for i in range(260)]
    assert kern.abschaltkriterium(fallend)['sharpe_250'] < -1.3
