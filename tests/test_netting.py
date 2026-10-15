"""Netting und Vorzeichenwechsel (Review 3.1/3.2, SPEC Aufgabe 6)."""
import kern


def leg(i, strat, sym, st, richtung=1, datum='2026-10-01'):
    return dict(id=i, strategie=strat, symbol=sym, richtung=richtung, stueck=st, datum=datum, atr20=1.0)


def test_zwei_neue_legs_eine_order_zwei_stueckzahlen():
    ein = [leg(None, 'IBS', 'SPY', 50), leg(None, 'BB', 'SPY', 30)]
    r = kern.netto_orders([], [], ein)
    assert r['orders'] == {'SPY': 80}
    assert [l['stueck'] for l in r['einstiege']] == [50, 30]


def test_ausstieg_und_einstieg_im_selben_symbol_netto_verkauf():
    alt = leg(1, 'IBS', 'SPY', 50)
    r = kern.netto_orders([alt], [(alt, 'IBS Ausstieg Folgetag')], [leg(None, 'TSMOM', 'SPY', 20)])
    assert r['orders'] == {'SPY': -30}
    assert r['einstiege'][0]['stueck'] == 20                   # Einstiegsleg behält seine geplante Stückzahl (nicht −30)


def test_vorzeichenwechsel_long_nach_short_nur_glattstellen():
    alt = leg(1, 'IBS', 'IWM', 50)
    r = kern.netto_orders([alt], [(alt, 'IBS Ausstieg Folgetag')], [leg(None, 'TSMOM', 'IWM', 20, -1)])
    assert r['orders'] == {'IWM': -50} and r['gekreuzt'] == ['IWM']
    assert r['einstiege'] == []
    assert r['aufgeschoben'][0]['stueck'] == 20 and r['aufgeschoben'][0]['richtung'] == -1   # TSMOM: im nächsten Lauf eröffnen


def test_vorzeichenwechsel_short_nach_long_ibs_verfaellt_teilweise():
    short = leg(1, 'TSMOM', 'IWM', 30, -1)
    r = kern.netto_orders([short], [], [leg(None, 'IBS', 'IWM', 100)])
    assert r['orders'] == {'IWM': 30}                            # nur bis null kaufen
    assert r['einstiege'][0]['stueck'] == 30                     # IBS erhält den intern verrechneten Teil
    assert r['verfallen'][0]['stueck'] == 70 and r['aufgeschoben'] == []


def test_vorzeichenwechsel_durch_bleibendes_leg():
    """Long 100 (IBS) und Short 50 (TSMOM) im Bestand, IBS geht → Netto −50 wäre ein Wechsel: heute nur auf null,
    das TSMOM-Short wird glattgestellt und morgen nachgeholt."""
    ibs, ts = leg(1, 'IBS', 'SPY', 100), leg(2, 'TSMOM', 'SPY', 50, -1)
    r = kern.netto_orders([ibs, ts], [(ibs, 'IBS Ausstieg Folgetag')], [])
    assert r['orders'] == {'SPY': -50}
    assert (ts, 'Vorzeichenwechsel-Sperre (glattgestellt)', 50) in r['ausstiege']
    assert r['aufgeschoben'][0]['strategie'] == 'TSMOM' and r['aufgeschoben'][0]['stueck'] == 50


def test_sperre_aus_entspricht_v1():
    alt = leg(1, 'IBS', 'IWM', 50)
    r = kern.netto_orders([alt], [(alt, 'x')], [leg(None, 'TSMOM', 'IWM', 20, -1)], sperre='aus')
    assert r['orders'] == {'IWM': -70}


def test_netto_null_ohne_order():
    alt = leg(1, 'IBS', 'SPY', 40)
    r = kern.netto_orders([alt], [(alt, 'x')], [leg(None, 'MW', 'SPY', 40)])
    assert r['orders'] == {}


def test_verteile_fill_voll_und_teil():
    k = [dict(art='ein', menge=50, seite=1, strategie='IBS', nr=0), dict(art='ein', menge=30, seite=1, strategie='BB', nr=1)]
    assert kern.verteile_fill(k, 80) == [50, 30]
    assert kern.verteile_fill(k, 60) == [50, 10]                 # Teilfüllung: Vorrang IBS vor BB
    assert kern.verteile_fill(k, 0) == [0, 0]                    # abgelehnt


def test_verteile_fill_intern_verrechnet():
    # Ausstieg IBS 50 (Verkauf), Einstieg TSMOM 20 (Kauf) → Netto-Verkauf 30
    k = [dict(art='aus', menge=50, seite=-1, strategie='IBS', leg_id=1), dict(art='ein', menge=20, seite=1, strategie='TSMOM', nr=0)]
    assert kern.verteile_fill(k, -30) == [50, 20]
    assert kern.verteile_fill(k, -10) == [30, 20]                # Einstieg intern voll, Ausstieg 30 von 50
    assert kern.verteile_fill(k, 0) == [20, 20]                  # Order abgelehnt: nur der intern verrechnete Teil


def test_verteile_fill_ausstiege_fifo():
    k = [dict(art='aus', menge=10, seite=-1, strategie='BB', leg_id=7), dict(art='aus', menge=10, seite=-1, strategie='IBS', leg_id=3)]
    assert kern.verteile_fill(k, -12) == [2, 10]                 # ältestes Leg (id 3) zuerst
