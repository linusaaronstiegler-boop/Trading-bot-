"""Lauffenster K6 und feste Regel 4 (Orders nur 10–30 Min vor Schluss, nur MOC), Not-Aus im Live-Lauf."""
import json
import pytest
import systembuch_bot as v2
from tests.test_abrechnung import broker, lauf, zustand

MOC = lambda b: [o for o in b.orders.values() if o['time_in_force'] == 'cls']


def test_start_1528_wartet_bis_1545_und_handelt(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27', uhr='19:28:00', schluss='20:00:00')
    r, code = lauf()
    assert code == 0 and b.geschlafen and abs(b.geschlafen[0] - 17 * 60) < 1
    assert MOC(b) and all(o['type'] == 'market' and o['time_in_force'] == 'cls' for o in MOC(b))
    assert zustand(tmp_path)['letzter_lauf_info']['entscheidung'].endswith(':45:00')


def test_start_1549_kein_handel(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27', uhr='19:49:00', schluss='20:00:00')
    r, code = lauf()
    assert r == {'ende': 'kein Fenster'} and not MOC(b)


@pytest.mark.parametrize('uhr,erlaubt', [('19:20:00', True), ('19:19:00', False), ('19:48:30', True), ('19:48:31', False)])
def test_startgrenzen_40_und_11_5_minuten(monkeypatch, tmp_path, uhr, erlaubt):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27', uhr=uhr, schluss='20:00:00')
    r, code = lauf()
    assert (r != {'ende': 'kein Fenster'}) == erlaubt


def test_uhr_vor_orders_unter_10_5_minuten_abbruch_ohne_buchung(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    b.uhr_folge = ['2025-02-27T19:45:00Z', '2025-02-27T19:45:00Z', '2025-02-27T19:49:40Z']
    r, code = lauf()
    assert code == 1 and not MOC(b)
    st = zustand(tmp_path)
    assert st['auftraege'] == [] and st['letzter_lauf'] is None and not any(l.get('status') == 'pending' for l in st['legs'])
    assert open(tmp_path / 'STATUS.md').read().startswith('# ZU SPÄT')


def test_halbtag_schluss_13_uhr(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27', uhr='17:28:00', schluss='18:00:00')
    r, code = lauf()
    assert code == 0 and MOC(b) and abs(b.geschlafen[0] - 17 * 60) < 1


def test_force_nur_mit_dry():
    with pytest.raises(SystemExit) as e: v2.main(['--force'])
    assert '--force nur zusammen mit --dry' in str(e.value)


def test_not_aus_stellt_per_moc_glatt(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf(); b.schluss('2025-02-27'); b.neuer_tag('2025-02-28')
    b.equity = 69000.0                                                                    # Start 100.000 → unter 70 %
    r, code = lauf()
    assert code == 1
    st = zustand(tmp_path)
    assert st['gestoppt'] and st['stopp_grund'].startswith('NOT-AUS')
    neu = [o for o in MOC(b) if o['status'] == 'accepted']
    assert neu and all(o['side'] == 'sell' for o in neu)
    assert {o['symbol']: int(o['qty']) for o in neu} == b.positionen
    assert not [a for a in b.aufrufe if a[0] == 'DELETE' and a[1].startswith('/v2/positions')]
