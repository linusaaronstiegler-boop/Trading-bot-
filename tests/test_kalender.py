"""Kalender (Review 1.11/1.12, SPEC Aufgabe 6): Monatswechsel-Termine inkl. Feiertage, Halbtage und Zeitumstellung."""
import kern


def kal(von='2026-01-01', bis='2028-12-31'):
    return kern.Kalender.nach_regeln(von, bis)


def test_karfreitag_2027_ist_26_maerz():
    k = kal()
    assert not k.ist_handelstag('2027-03-26')
    assert k.ist_handelstag('2027-04-02')                       # v1-Tabelle hatte bis 15.10. 23:15 fälschlich den 02.04.


def test_heiligabend_2027_feiertag_und_silvester_2027_handelstag():
    k = kal()
    assert not k.ist_handelstag('2027-12-24')                   # 25.12.2027 ist Samstag → Freitag frei
    assert k.ist_handelstag('2027-12-31')                       # Neujahr 2028 auf Samstag → kein Ersatztag
    assert not k.ist_handelstag('2028-01-17')                   # MLK 2028 – v1-Tabelle endete 2027


def test_27_november_2026_halbtag_und_mw_kauftag():
    k = kal()
    assert k.schluss['2026-11-27'] == '13:00'
    t = k.termine('2026-11-27')
    assert t['mw_kauf'] and not t['tsmom_tag']
    assert k.termine('2026-11-30')['tsmom_tag']
    assert not k.ist_handelstag('2026-11-26')


def test_feiertag_am_monatsende_verschiebt_termine():
    k = kal()                                                   # Memorial Day 31.05.2027 ist der letzte Werktag im Mai
    assert k.termine('2027-05-28')['tsmom_tag']
    assert k.termine('2027-05-27')['mw_kauf']


def test_feiertag_am_monatsanfang_verschiebt_dritten_handelstag():
    k = kal()                                                   # Neujahr 2027 (Fr): 4., 5., 6. Januar
    assert k.termine('2027-01-06')['mw_verkauf']
    assert not k.termine('2027-01-05')['mw_verkauf']


def test_zeitumstellung_aendert_keine_handelstage():
    k = kal()                                                   # EU 25.10.2026, USA 01.11.2026: Kalender in ET-Datum, unabhängig von der Uhrzeit
    okt = k.monat(2026, 10)
    assert okt[-1] == '2026-10-30' and okt[-2] == '2026-10-29' and len(okt) == 22
    assert k.monat(2026, 11)[2] == '2026-11-04'


def test_regelwerk_stimmt_mit_echten_handelstagen_ueberein():
    """2010–2026 gegen die SPY-Handelstage (Yahoo-Cache, falls vorhanden): nur die bekannten Sonderschließungen fehlen im Regelwerk."""
    import os, csv, pytest
    fn = os.path.join(os.path.dirname(__file__), '..', 'daten', 'SPY_1d.csv')
    if not os.path.exists(fn): pytest.skip('kein Yahoo-Cache')
    echt = {r['datum'] for r in csv.DictReader(open(fn)) if '2010-01-01' <= r['datum'] <= '2026-10-14'}
    regel = set(kern.regel_handelstage('2010-01-01', '2026-10-14')[0])
    assert echt - regel == set()
    assert regel - echt == {'2012-10-29', '2012-10-30', '2018-12-05', '2025-01-09'}


def test_bb_alter_zaehlt_handelstage():
    k = kal()                                                   # (24.11., 01.12.]: 25., 27., 30.11., 01.12. → 4 (26.11. Thanksgiving)
    assert k.anzahl_zwischen('2026-11-24', '2026-12-01') == 4


def test_kommende_termine_nennt_halbtag_und_feiertag():
    t = dict(kal().kommende_termine('2026-11-20'))
    assert '2026-11-26' in t and 'Feiertag' in t['2026-11-26']
    assert 'Halbtag' in t['2026-11-27'] or 'Monatswechsel' in t['2026-11-27']
