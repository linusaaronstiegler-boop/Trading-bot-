"""Befunde des feindseligen Reviews von v2 (15.10.2026) – je Befund ein Test."""
import copy, http.client, json, os, shutil
import pytest
import kern
import systembuch_bot as v2
from tests.alpaca_attrappe import AlpacaAttrappe
from tests.conftest import FIXTURES, lade_fixture
from tests.test_abrechnung import broker, lauf, zustand, tag2

F2 = [p for p in FIXTURES if 'f2_' in p][0]


def test_nachlaeufer_mit_veraltetem_stand_storniert_und_sendet_nichts(monkeypatch, tmp_path):
    """Hoch: Nachläufer startet mit altem Checkout (state.json ohne die heutigen Orders) → nichts stornieren, nichts senden, nichts schreiben."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    alt = open(tmp_path / 'state.json').read()
    r, code = lauf(); n = len(b.orders)
    assert code == 0 and n > 0
    for f in os.listdir(tmp_path): os.remove(tmp_path / f)
    open(tmp_path / 'state.json', 'w').write(alt)                                     # Stand von vor Lauf 1
    b.neuer_tag('2025-02-27', uhr='19:47:30'); aufrufe = len(b.aufrufe)
    r, code = lauf()
    assert r == {'ende': 'schon gehandelt'} and code == 0
    assert len(b.orders) == n and all(o['status'] == 'accepted' for o in b.orders.values())
    assert not [x for x in b.aufrufe[aufrufe:] if x[0] in ('POST', 'DELETE')]
    assert sorted(os.listdir(tmp_path)) == ['state.json'] and open(tmp_path / 'state.json').read() == alt


def test_not_aus_mit_abgelehnter_order_wird_weiter_abgewickelt(monkeypatch, tmp_path):
    """Mittel: Not-Aus, eine Glattstell-Order abgelehnt → Folgelauf stellt den Rest glatt (Exit 1), danach grün „gestoppt“."""
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf(); b.schluss('2025-02-27'); b.neuer_tag('2025-02-28')
    b.equity = 60000.0; b.ablehnen['DIA'] = 'insufficient buying power'
    r, code = lauf()
    assert code == 1 and zustand(tmp_path)['gestoppt']
    b.schluss('2025-02-28'); b.neuer_tag('2025-03-03'); del b.ablehnen['DIA']; fx['heute'] = '2025-02-28'
    assert b.positionen.get('DIA') == 114
    r, code = lauf()
    assert code == 1 and [o for o in b.orders.values() if o['symbol'] == 'DIA' and o['status'] == 'accepted' and o['side'] == 'sell']
    b.schluss('2025-03-03'); b.neuer_tag('2025-03-04'); fx['heute'] = '2025-03-03'
    r, code = lauf()
    assert r == {'ende': 'gestoppt'} and code == 0 and b.positionen == {}
    assert zustand(tmp_path)['legs'] == []


def test_not_aus_trotz_abweichung_stellt_alpaca_positionen_glatt(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path); b.neuer_tag('2025-02-27')
    lauf(); b.schluss('2025-02-27'); b.neuer_tag('2025-02-28')
    b.positionen['XLE'] = 7; b.equity = 60000.0                                      # Position ohne Leg + Not-Aus
    r, code = lauf()
    assert code == 1
    verkauf = {o['symbol']: int(o['qty']) for o in b.orders.values() if o['status'] == 'accepted' and o['side'] == 'sell'}
    assert verkauf == b.positionen


def test_schluessel_mit_zeilenumbruch_wird_nie_ausgegeben(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('APCA_API_KEY_ID', 'PKGEHEIMXYZ'); monkeypatch.setenv('APCA_API_SECRET_KEY', 'SKGEHEIMäXYZ\n')
    with pytest.raises(SystemExit): v2.main([])
    for f in os.listdir(tmp_path): assert 'GEHEIM' not in open(tmp_path / f).read(), f
    assert 'Sonderzeichen' in open(tmp_path / 'STATUS.md').read()
    monkeypatch.setenv('APCA_API_SECRET_KEY', 'SKGEHEIM12345')
    v2.AUSGABE['schreiben'] = True
    v2.log('Fehler mit SKGEHEIM12345 im Text')
    assert 'GEHEIM' not in open(tmp_path / 'log.txt').read()


def test_verbindungsabbruch_wird_zu_runtimeerror(monkeypatch):
    """Mittel: http.client.RemoteDisconnected nach dem Senden darf nicht roh durchrutschen (sonst keine Nachschau per client_order_id)."""
    monkeypatch.setenv('APCA_API_KEY_ID', 'PKX123456'); monkeypatch.setenv('APCA_API_SECRET_KEY', 'SKX123456')
    def weg(*a, **k): raise http.client.RemoteDisconnected('Remote end closed connection')
    monkeypatch.setattr(v2.urllib.request, 'urlopen', weg); monkeypatch.setattr(v2.time, 'sleep', lambda s: None)
    with pytest.raises(RuntimeError, match='nicht erreichbar'): v2.alp('/v2/orders', {}, 'POST', tries=1)
    nachgesehen = []
    def alp(path, body=None, method=None, base=None, tries=5):
        if method == 'POST': raise RuntimeError('Alpaca nicht erreichbar (/v2/orders): RemoteDisconnected')
        nachgesehen.append(path); return {'id': 'o9', 'status': 'accepted'}
    monkeypatch.setattr(v2, 'alp', alp)
    assert v2.moc_senden('SPY', 10, 'sb-2026-10-16-SPY')['id'] == 'o9' and 'by_client_order_id' in nachgesehen[0]


def test_vorhandener_stop_wird_uebernommen_statt_verdoppelt(monkeypatch, tmp_path):
    b, fx = broker(monkeypatch, tmp_path)
    leg = dict(id=7, strategie='BB', symbol='SPY', richtung=1, stueck=40, einstieg=590.0, atr20=5.0, datum='2025-02-20')
    offene = [dict(id='alt1', symbol='SPY', client_order_id='sb-stop-7-2025-02-26-1', time_in_force='gtc')]
    assert v2.stop_setzen(leg, '2025-02-27', offene) and leg['stop_order'] == 'alt1'
    assert not [x for x in b.aufrufe if x[0] == 'POST']
    leg2 = dict(leg, id=8); leg2.pop('stop_order', None)
    assert v2.stop_setzen(leg2, '2025-02-27', offene)
    post = [x for x in b.aufrufe if x[0] == 'POST'][0][2]
    assert post['client_order_id'] == 'sb-stop-8-2025-02-27-1' and post['qty'] == '40' and post['stop_price'] == '575.00'


def test_abgelehnter_tsmom_einstieg_wird_nachgeholt(monkeypatch, tmp_path):
    """Mittel: TSMOM-Einstieg am Monatsletzten abgelehnt → nicht einen Monat verloren, sondern im nächsten Lauf nachgeholt."""
    b, fx = broker(monkeypatch, tmp_path, fixture=F2); b.neuer_tag('2025-02-28')
    b.ablehnen['HYG'] = 'insufficient buying power'
    r, code = lauf()
    assert code == 1 and ('TSMOM', 'HYG', 87) in [(l['strategie'], l['symbol'], l['stueck']) for l in r['einstiege']] if r else code == 1
    b.schluss('2025-02-28'); b.neuer_tag('2025-03-03'); del b.ablehnen['HYG']; fx['heute'] = '2025-02-28'
    r, code = lauf()
    st = zustand(tmp_path)
    hyg = [l for l in st['legs'] if l['symbol'] == 'HYG' and l['strategie'] == 'TSMOM']
    assert hyg and hyg[0].get('nachgeholt') and hyg[0]['datum'] == '2025-02-28'


def test_bb_hoechstzahl_zaehlt_symbole():
    kz = {s: dict(px=100, hi=101, lo=99, ibs=0.5, atr20=1, sma20=105, sma200=90, bb_unten=101, ret12=0.1, vol60=0.15) for s in kern.ALLE_SYMBOLE}
    legs = [dict(id=1, strategie='BB', symbol='SPY', richtung=1, stueck=30, datum='2026-10-13', atr20=1, einstieg=100)]
    auf = [dict(strategie='BB', symbol='SPY', richtung=1, stueck=220, datum='2026-10-13', atr20=1)]
    z = dict(heute='2026-10-14', equity=1e6, hwm=1e6, legs=legs, leihbar={}, aufgeschoben=auf)
    aus, ein, info = kern.entscheide(z, {}, {}, kern.Kalender.nach_regeln('2026-09-01', '2026-12-31'), kz=kz)
    assert sorted(l['symbol'] for l in ein if l['strategie'] == 'BB') == ['DIA', 'IWM', 'QQQ', 'SPY']


def test_aufgeschobenes_ohne_kurs_bleibt_vorgemerkt():
    auf = [dict(strategie='TSMOM', symbol='IWM', richtung=-1, stueck=20, datum='2026-09-30', atr20=1)]
    z = dict(heute='2026-10-01', equity=1e5, hwm=1e5, legs=[], leihbar={}, aufgeschoben=auf)
    aus, ein, info = kern.entscheide(z, {}, {}, kern.Kalender.nach_regeln('2026-09-01', '2026-12-31'), kz={})
    assert info['aufgeschoben_behalten'] == auf and any('kein Kurs' in x for x in info['log'])


F5 = [p for p in FIXTURES if 'f5_' in p][0]


@pytest.mark.parametrize('alpaca_nimmt_an', [True, False])
def test_wechsel_short_long_mit_zwei_kauforders(monkeypatch, tmp_path, alpaca_nimmt_an):
    """VORZEICHENWECHSEL_SPERRE='verkauf': short → long als Eindecken + Neukauf. Lehnt Alpaca die zweite Order ab
    (Prüfung 6 negativ), bleibt der Zustand trotzdem richtig: Folgelauf gleicht ab, IBS-Rest verfällt, nichts doppelt."""
    monkeypatch.setattr(v2, 'VORZEICHENWECHSEL_SPERRE', 'verkauf')
    fx = lade_fixture(F5); b = AlpacaAttrappe(fx)
    for l in fx['state']['legs']: b.positionen[l['symbol']] = b.positionen.get(l['symbol'], 0) + l['richtung'] * l['stueck']
    b.kauf_flip_ablehnen = not alpaca_nimmt_an; b.installieren(v2, monkeypatch, tmp_path); b.neuer_tag('2025-11-20')
    vorher = b.positionen['IWM']
    assert vorher < 0
    r, code = lauf()
    iwm = sorted((o['client_order_id'], int(o['qty'])) for o in b.orders.values() if o['symbol'] == 'IWM' and o['time_in_force'] == 'cls')
    assert iwm[0] == ('sb-2025-11-20-IWM', -vorher)
    assert (len(iwm) == 2) == alpaca_nimmt_an and code == (0 if alpaca_nimmt_an else 1)
    b.schluss('2025-11-20'); b.neuer_tag('2025-11-21'); fx['heute'] = '2025-11-20'
    r, code = lauf()
    st = zustand(tmp_path)
    assert 'ABGLEICH' not in open(tmp_path / 'STATUS.md').read()                       # Folgelauf: Legs = Positionen nach Abrechnung
    if alpaca_nimmt_an: assert any(l['symbol'] == 'IWM' and l['strategie'] == 'IBS' and l['einstieg_datum'] == '2025-11-20' for l in st['legs'])
