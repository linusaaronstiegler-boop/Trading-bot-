"""Aufgabe 5 (Betrieb): STATUS.md, Fehlerfälle, Abschaltkriterium K5, VIX-Alarm, Wochenbericht."""
import csv, json, os
import pytest
import systembuch_bot as v2
from tests.alpaca_attrappe import AlpacaAttrappe
from tests.conftest import FIXTURES, lade_fixture
from tests.test_abrechnung import broker, lauf, zustand, tag2

F1 = [p for p in FIXTURES if 'f1_' in p][0]


def test_status_enthaelt_alle_abschnitte(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf(); tag2(b, fx); lauf()
    s = open(tmp_path / 'STATUS.md').read()
    for teil in ('## Konto', 'Entscheidung', 'Min vor Schluss', '## Kurve (letzte 60 Handelstage)', '## Abschaltkriterium K5', '## Offene Legs',
                 'unreal. $', '## Stand je Strategie seit Start', '## Vorteil auf Trade-Ebene (IBS-Familie)', '## Nächste Termine',
                 'Monatswechsel-Verkauf', '## Letzte Logzeilen', 'Quelle: Fixture'):
        assert teil in s, teil


def test_alpaca_nicht_erreichbar_fehler_exit1(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    def weg(*a, **k): raise RuntimeError('Alpaca nicht erreichbar (/v2/clock): timeout')
    monkeypatch.setattr(v2, 'alp', weg)
    r, code = lauf()
    assert code == 1
    assert open(tmp_path / 'STATUS.md').read().startswith('# FEHLER')


def test_schluessel_fehlen_fehler_ohne_schluessel_im_text(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('APCA_API_KEY_ID', raising=False); monkeypatch.delenv('APCA_API_SECRET_KEY', raising=False)
    with pytest.raises(SystemExit) as e: v2.main([])
    assert e.value.code == 1
    assert 'Alpaca-Schlüssel fehlen' in open(tmp_path / 'STATUS.md').read()


def test_schluessel_nie_in_dateien(monkeypatch, tmp_path):
    monkeypatch.setenv('APCA_API_KEY_ID', 'PKGEHEIM123'); monkeypatch.setenv('APCA_API_SECRET_KEY', 'SKGEHEIM456')
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf(); tag2(b, fx); lauf()
    for f in os.listdir(tmp_path):
        if os.path.isfile(tmp_path / f):
            inhalt = open(tmp_path / f, errors='ignore').read()
            assert 'GEHEIM' not in inhalt, f


def test_abschaltkriterium_stellt_glatt_und_stoppt(monkeypatch, tmp_path):
    """K5: Drawdown ≥ 34 % → alle Legs per MOC glatt, gestoppt, STATUS oben, Exit 1, kein automatischer Neustart."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf(); b.schluss('2025-02-27'); b.neuer_tag('2025-02-28')
    with open(tmp_path / 'equity.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(v2.EQUITY_SPALTEN); w.writerow(['2025-02-26', 100000, '', '', '', 0])
    b.last_equity = 60000.0
    st = zustand(tmp_path); st['start'] = '2025-02-26'; json.dump(st, open(tmp_path / 'state.json', 'w'))
    r, code = lauf()
    assert code == 1
    st = zustand(tmp_path)
    assert st['gestoppt'] and 'ABSCHALTKRITERIUM' in st['stopp_grund']
    assert all(l.get('ausstieg') for l in st['legs'])
    assert open(tmp_path / 'STATUS.md').read().split('\n')[2].startswith('## ABSCHALTKRITERIUM AUSGELÖST')
    verkauf = {o['symbol']: int(o['qty']) for o in b.orders.values() if o['status'] == 'accepted' and o['side'] == 'sell'}
    assert verkauf == {s: n for s, n in b.positionen.items()}
    b.schluss('2025-02-28'); b.neuer_tag('2025-03-03')
    r, code = lauf()
    assert r == {'ende': 'gestoppt'} and not [o for o in b.orders.values() if o['status'] == 'accepted']


def test_vix_alarm_nach_drei_laeufen(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path)
    monkeypatch.setattr(v2, 'lade_vix', lambda: (None, None, 'fehlt (Test)'))
    codes = []
    for tag in ('2025-02-25', '2025-02-26', '2025-02-27'):
        b.neuer_tag(tag); r, code = lauf(); codes.append(code); b.schluss(tag)
    assert codes == [0, 0, 1]
    assert 'VIX seit 3 Läufen nicht lesbar' in open(tmp_path / 'STATUS.md').read()


def test_wochenbericht_am_letzten_handelstag_der_woche(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf()
    assert not (tmp_path / 'berichte').exists()                                        # Donnerstag
    tag2(b, fx)                                                                         # Freitag 28.02.2025
    lauf()
    assert (tmp_path / 'berichte' / '2025-09.md').exists()


def test_kein_fenster_schreibt_nichts(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27', uhr='16:00:00')    # 4 Stunden vor Schluss
    vorher = sorted(os.listdir(tmp_path))
    r, code = lauf()
    assert r == {'ende': 'kein Fenster'} and sorted(os.listdir(tmp_path)) == vorher
