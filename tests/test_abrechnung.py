"""Aufgabe 2 (exakte Abrechnung) mit den Review-Befunden 3.1, 3.5, 3.7, 5.2, 5.5 – Live-Läufe gegen die Alpaca-Attrappe."""
import copy, csv, json, os
import pytest
import systembuch_bot as v2
from tests.alpaca_attrappe import AlpacaAttrappe
from tests.conftest import FIXTURES, lade_fixture

F1 = [p for p in FIXTURES if 'f1_' in p][0]


def broker(monkeypatch, tmp_path, legs=None, fixture=F1):
    fx = lade_fixture(fixture); fx['state']['legs'] = legs or []
    fx['state']['start'] = None; fx['state']['startkapital'] = None; fx['state']['hwm'] = None
    b = AlpacaAttrappe(fx); b.installieren(v2, monkeypatch, tmp_path)
    return b, fx


def lauf(argv=()):
    try: return v2.main(list(argv)), 0
    except SystemExit as e: return None, e.code


def zustand(tmp_path):
    return json.load(open(tmp_path / 'state.json'))


def journal(tmp_path):
    p = tmp_path / 'journal.csv'
    return list(csv.DictReader(open(p))) if p.exists() else []


def tag2(b, fx, datum='2025-02-28', preise=None):
    """Schlussauktion des Vortags, dann neuer Tag mit (optional) neuen Kursen."""
    b.schluss(fx['heute'])
    b.neuer_tag(datum)
    if preise:
        for s, px in preise.items(): fx['live'][s] = dict(px=px, hi=max(px, fx['live'][s]['hi']), lo=min(px, fx['live'][s]['lo']))


def test_ibs_und_mw_im_selben_symbol_eine_order_zwei_legs(monkeypatch, tmp_path):
    """Review 3.1 / Abnahmetest aus REVIEW §8: eine Order über 84 SPY, am Folgetag zwei Legs mit je eigener Stückzahl (nicht 2 × 84)."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    r, code = lauf()
    assert code == 0 and r['plan']['SPY'] == 84
    spy_orders = [o for o in b.orders.values() if o['symbol'] == 'SPY']
    assert len(spy_orders) == 1 and spy_orders[0]['qty'] == '84' and spy_orders[0]['time_in_force'] == 'cls'
    tag2(b, fx)
    r, code = lauf()
    legs = [l for l in zustand(tmp_path)['legs'] if l['symbol'] == 'SPY']
    assert sorted((l['strategie'], l['stueck']) for l in legs) == [('IBS', 42), ('MW', 42)]
    assert all(l['status'] == 'offen' and l['fill_einstieg'] == fx['live']['SPY']['px'] for l in legs)


def test_teilfuellung_geht_nach_vorrang(monkeypatch, tmp_path):
    """Review 3.7: filled_qty zählt, auch wenn die Order danach storniert ist; IBS (Vorrang 1) vor MW."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf()
    b.schluss(fx['heute'], anteil={'SPY': 0.5}); b.neuer_tag('2025-02-28')
    lauf()
    legs = [l for l in zustand(tmp_path)['legs'] if l['symbol'] == 'SPY' and l['einstieg_datum'] == '2025-02-27']
    assert [(l['strategie'], l['stueck']) for l in legs] == [('IBS', 42)]                    # MW-Leg nicht eröffnet


def test_abgelehnte_order_ausstieg_bleibt_einstieg_entfaellt(monkeypatch, tmp_path):
    """Review 3.5: Ablehnung → schließende Legs bleiben (ausstieg_offen), neue Legs entfallen, Exit 1."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf()
    tag2(b, fx, preise={'IWM': fx['live']['IWM']['hi']})                                      # IWM schließt am Hoch → IBS-Ausstieg
    b.ablehnen['IWM'] = 'insufficient qty available'
    r, code = lauf()
    assert code == 1
    assert 'ORDER ABGELEHNT' in open(tmp_path / 'STATUS.md').read()
    b.schluss('2025-02-28'); b.neuer_tag('2025-03-03'); del b.ablehnen['IWM']
    fx['heute'] = '2025-02-28'
    r, code = lauf()
    st = zustand(tmp_path)
    iwm = [l for l in st['legs'] if l['symbol'] == 'IWM']
    # Ausstieg vom 28.02. wurde abgelehnt → Leg blieb mit Vermerk und wird am 03.03. nachgeholt (MOC gesendet)
    assert iwm and iwm[0].get('ausstieg', {}).get('grund', '').endswith('(nachgeholt)')
    assert b.positionen.get('IWM') == iwm[0]['stueck']


def test_positionsabgleich_stoppt_handel(monkeypatch, tmp_path):
    """Review 5.5: Alpaca-Position ohne Leg → kein Handel, STATUS „ABGLEICH NÖTIG“, Exit 1."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    b.positionen['XLE'] = 10
    r, code = lauf()
    assert code == 1
    assert not [o for o in b.orders.values() if o['time_in_force'] == 'cls']
    assert 'ABGLEICH NÖTIG' in open(tmp_path / 'STATUS.md').read()


def test_wiederanlauf_nach_abbruch_ohne_doppelorder(monkeypatch, tmp_path):
    """Review 5.2: Abbruch nach Order 2 → Zustand ist nach jeder Order gespeichert; der Nachläufer handelt nicht doppelt,
    der Folgelauf rechnet die zwei gesendeten Orders ab und verwirft die nicht gesendeten."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    b.abbruch_nach_orders = 2
    with pytest.raises(KeyboardInterrupt): v2.main([])
    st = zustand(tmp_path)
    assert [a['status'] for a in st['auftraege']] == ['gesendet', 'gesendet', 'vorbereitet']
    b.abbruch_nach_orders = None
    b.neuer_tag('2025-02-27', uhr='19:46:00')                                                   # Nachläufer am selben Tag
    r, code = lauf()
    assert r == {'ende': 'schon gelaufen'}
    assert sum(1 for o in b.orders.values() if o['time_in_force'] == 'cls') == 2
    tag2(b, fx)
    r, code = lauf()
    assert code == 0
    st = zustand(tmp_path)
    alt = [l for l in st['legs'] if l['einstieg_datum'] == '2025-02-27']
    assert {l['symbol'] for l in alt} == {'SPY', 'QQQ'}                                          # nur die gesendeten Symbole


def test_netzfehler_nach_post_findet_order_ueber_client_order_id(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    b.netzfehler_nach_post = {'QQQ'}
    r, code = lauf()
    assert code == 0
    st = zustand(tmp_path)
    assert [a['status'] for a in st['auftraege'] if a['symbol'] == 'QQQ'] == ['gesendet']
    assert sum(1 for o in b.orders.values() if o['symbol'] == 'QQQ') == 1


def test_journal_mit_fill_und_schluss_spalten(monkeypatch, tmp_path):
    """SPEC 2: Einstieg/Ausstieg je Leg zum tatsächlichen Fill, Schluss daneben, abweichung_bp = Kosten gegenüber dem Schluss."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf()
    tag2(b, fx, preise={'IWM': fx['live']['IWM']['hi']})
    lauf()
    schluss = fx['live']['IWM']['px']
    b.schluss('2025-02-28', fill={'IWM': schluss * 0.999})                                    # Fill 10 bp unter Schluss
    b.neuer_tag('2025-03-03'); fx['heute'] = '2025-02-28'
    lauf()
    z = [r for r in journal(tmp_path) if r['symbol'] == 'IWM']
    assert len(z) == 1
    r = z[0]
    assert set(v2.JOURNAL_SPALTEN) <= set(r)
    assert float(r['fill_ausstieg']) == pytest.approx(schluss * 0.999, abs=1e-3)
    assert float(r['schluss_ausstieg']) == pytest.approx(schluss, abs=1e-3)
    assert float(r['abweichung_bp']) == pytest.approx(10.0, abs=0.1)                          # Verkauf 10 bp unter Schluss = 10 bp Kosten
    assert r['grund'] == 'IBS Ausstieg Folgetag' and r['haltetage'] == '1'


def test_equity_csv_und_signalabweichung(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf()
    st = zustand(tmp_path)
    assert st['signale']['2025-02-27']['SPY'] < 0.2
    tag2(b, fx)
    fx['hist'] = {s: rows + [[fx['heute'], v['px'], v['hi'], v['lo'], v['px']]] for s, (rows, v) in
                  ((s, (fx['hist'][s], fx['live'][s])) for s in fx['hist'])}                  # fertige Tageskerze des 27.02.
    lauf()
    st = zustand(tmp_path)
    assert st['signal_stat']['IBS'][0] == 4 and st['signal_stat']['IBS'][1] == 0              # 4 Index-Signale, keins gekippt
    e = list(csv.DictReader(open(tmp_path / 'equity.csv')))
    assert e[-1]['datum'] == '2025-02-27' and float(e[-1]['brutto']) > 0 and e[-1]['legs'] == '9'


def test_dry_schreibt_nur_status_dry(monkeypatch, tmp_path):
    """Review 5.7/6.8: Dry-Lauf schreibt weder state.json noch journal.csv noch log.txt, nur STATUS-dry.md."""
    fx = lade_fixture(F1)
    b = AlpacaAttrappe(fx)
    vorher = None
    r = b.dry_lauf(v2, monkeypatch, tmp_path)
    assert r['plan']
    dateien = sorted(os.listdir(tmp_path))
    assert dateien == ['STATUS-dry.md', 'state.json']
    assert json.load(open(tmp_path / 'state.json')) == fx['state']                             # unverändert
    assert not [a for a in b.aufrufe if a[0] in ('POST', 'DELETE')]
