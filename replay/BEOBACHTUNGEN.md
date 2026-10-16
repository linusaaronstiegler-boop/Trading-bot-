# Beobachtungen aus dem Replay v2 (15.10.2026)

Nur Beobachtungen. Keine Regel wurde geändert, über alles hier wird in einer Sitzung mit Linus und mit vorab festgeschriebenem Test entschieden.
Zahlen: `replay/BERICHT.md`, 04.01.2010 bis 14.10.2026, 100.000 $, 3 bp je Seite.

## 1. Die Vorzeichenwechsel-Sperre kostet 1,9 Punkte p.a.

| | p.a. | Sharpe | Maximalverlust | Tresor ab 10/2023 |
|---|---|---|---|---|
| K3-Modell (ohne Sperre, = K3) | +12,0 % | 0,75 | 24,1 % | +16,8 % |
| Sperre nur long → short | +12,1 % | 0,75 | 24,0 % | – |
| Sperre beide Richtungen (live) | +10,2 % | 0,68 | 26,7 % | +11,5 % |

- Alpaca kann eine Position nicht an einem Tag durch null drehen (Review 3.2). Für long → short ist das belegt (zweite Verkaufsorder: „insufficient qty“). Für short → long gibt es einen Forenbericht vom 23.12.2022 mit derselben Ablehnung auf der zweiten Kauforder ([forum.alpaca.markets/t/11413](https://forum.alpaca.markets/t/changing-short-to-long-get-insufficient-quantity-available-even-after-check-for-no-open-orders/11413)). Eine verbindliche Doku gibt es nicht. **Paper-Prüfung 16.10.2026 bestätigt es für beide Richtungen:** Verkauf 2 SPY bei Long 1 → „insufficient qty available“; Short 1 IWM, dann Kauf 1 + Kauf 1 per MOC → die zweite Kauforder wird abgelehnt. Der Bot sperrt deshalb beide Richtungen, und das bleibt so.
- Die Sperre auf der Verkaufsseite kostet nichts. Der Verlust entsteht auf der Kaufseite: TSMOM ist in Abwärtsphasen short SPY/QQQ/IWM/EEM, und genau dann kauft IBS dieselben ETFs. IBS verdient in Abwärtsphasen am meisten. Die Sperre schneidet deshalb gezielt die besten IBS-Trades ab. Beispiel: QQQ am 09.11.2022 mit 13 statt ≈ 300 Stück, am 10.11. stieg QQQ um 7 %. 2022 bringt IBS mit Sperre −32.100 $, ohne +8.500 $, bei fast gleich vielen Trades (189 gegen 186).
- Folgeeffekt: Das Konto fällt 2022 tiefer, die Bremse (×0,5) greift 2023–2025 an 79–92 % der Tage, und das Buch braucht bis Juni 2026 für ein neues Hoch (1.146 Handelstage).
- Unter Live-Bedingungen ist **„ohne TSMOM“ besser als das Gesamtbuch**: +11,4 % gegen +10,2 % p.a., Sharpe 0,72 gegen 0,68. Im K3-Modell bringt TSMOM dagegen +0,5 Punkte.

Mögliche Wege, alle mit vorab festgeschriebenem Test zu entscheiden:
1. ~~Zwei Kauf-MOC-Orders für short → long~~ – **geprüft am 16.10.2026, Alpaca lehnt die zweite ab.** Der Schalter `VORZEICHENWECHSEL_SPERRE = 'verkauf'` bleibt gebaut (falls Alpaca das ändert), hilft heute aber nicht.
2. TSMOM in ein zweites Alpaca-Paper-Konto legen. Dann gibt es kein Netting zwischen TSMOM-Shorts und den Long-Strategien, und der Replay entspricht dem K3-Modell. Brutto-Deckel und Bremse müssten über beide Konten gerechnet werden.
3. TSMOM streichen. Das wäre eine Regeländerung mit eigenem Test, und K4 hat Strukturvarianten bisher alle verworfen.

## 1b. BB-Stop: Lücke durch Alpacas Wash-Trade-Schutz

Kauft der Bot per MOC in einem Symbol, in dem ein BB-Leg liegt (IBS, Monatswechsel oder TSMOM in SPY/QQQ/DIA/IWM), muss der GTC-Sell-Stop vorher weg. Neu setzen lässt er sich erst, wenn die Kauforder ausgeführt ist: Alpaca lehnt gegenläufige Orders ab, wenn eine davon Market oder einfacher Stop ist. Der Bot setzt ihn deshalb im nächsten Lauf (15:28 ET) neu. Im Replay sind das 227 BB-Leg-Tage ohne Stop, die Wirkung ist ≈ 0 (+0,1 Punkte, Zufall).
Lückenlos ginge es nur mit einem Stop-Nachlauf nach Börsenschluss (≈ 16:05 ET, eigener Cron). Das wäre eine Order außerhalb des Fensters nach Linus' Regel 4. Nicht gebaut, Entscheidung offen.

## 2. VIX-Contango trägt viel auf wenig Trades

+2,8 Punkte p.a. (zweitgrößter Beitrag) aus 80 Trades mit 34 % Treffern und Ø +637 bp je Trade. Live ohne VIX: +8,1 % p.a. (K3-Modell +10,1 %). In der README steht die Regel als „Experiment“ (C16). Der Beitrag hängt an wenigen langen Haltephasen (Ø 41 Tage). Außerdem hat sich das Produkt geändert: SVXY war bis 27.02.2018 −1× und ist seitdem −0,5×.

- **Zeitpunkt der Entscheidung:** Der Replay nimmt (wie K3) den Yahoo-Schluss von ^VIX/^VIX3M. Das ist der CBOE-Wert von 16:15 ET, SVXY schließt aber um 16:00, und der Bot entscheidet um 15:45. Die tragenden Ausstiege liegen knapp an der Schwelle: 02.02.2018 (Verhältnis 0,984, SVXY danach −32 % und −83 %) und 02.08.2024 (0,998, danach −21 %) bringen zusammen rund 36.000 $ der VIX-Summe. Variante `vix_vortag` (Entscheidung mit dem Vortagesschluss, pessimistische Schranke): live +9,3 % statt +10,2 % p.a., K3-Modell +11,1 % statt +12,0 %. Der wahre 15:45-Wert liegt dazwischen, näher am Schluss. Messen ließe er sich nur mit CBOE-Intraday-Historie (nicht frei verfügbar). Live kann man es ab dem ersten Monat vergleichen: STATUS zeigt das Verhältnis um 15:45, der Schluss steht am Folgetag bei Yahoo.
- **Ein Einstiegstag entscheidet ein Jahr:** Handelt man SVXY schon ab Auflage (04.10.2011) statt ab 60 Handelstagen Historie (29.12.2011, so rechnen der Bot und K3), fällt der erste Dauer-Einstieg auf den 10.11.2011, mitten in die Bremse (×0,5). Diese eine Haltephase läuft mit halber Größe bis 28.12.2012: 2012 bringt dann +16,8 % statt +21,1 %, der VIX-Beitrag sinkt von 2,8 auf 2,4 Punkte p.a., das Buch von 12,05 auf 11,84 % (K3-Modell). Ein VIX-Leg wird nach dem Einstieg nie neu gewichtet. Der Beitrag hängt also stark davon ab, in welcher Bremsphase ein langer Contango-Abschnitt beginnt.

## 3. IBS-Sektor ist auf Trade-Ebene schwach

Ø +5,5 bp (K3-Modell) bzw. +6,0 bp (live) je Trade, t 1,4–1,6. Der Einzeltest C4 nennt t 2,8. Beitrag im Buch +0,3–0,4 Punkte. K4 hat „ohne IBS-Sektor“ geprüft und verworfen, das bleibt so.

## 4. Monatswechsel-Land

Live +0,3 Punkte p.a. (Summe −4.400 $), im K3-Modell +0,6. Die Korrelation zu Monatswechsel liegt bei 0,72. Variante „ohne MW-Land“: live +10,0 % gegen +10,2 %, also für das Buch noch leicht positiv.

## 5. Was der Replay nicht zeigt

- K6: Die Rückrechnung entscheidet am Schluss, der Bot schon um 15:45. Laut README sind deshalb für IBS rund −0,4 und für IBS-Land rund −0,6 Punkte p.a. abzuziehen. Live liegt die Erwartung also eher bei +9 % als bei +10 %.
- MOC-Fill gegen Schlusskurs: Das misst der Live-Bot im Journal (`abweichung_bp`).
- Die Leihbarkeit kommt aus `assets.json` (Alpaca, 15.10.2026): EWG, USO, FXE nicht leihbar, genau die K3-Annahme.
- Stückzahl aus Yahoos `close` (nur split-bereinigt), wie K3. Bei UNG und USO war der echte Kurs 2010–2012 viel niedriger (UNG ≈ 10 $ statt 1.362 $ bereinigt), deshalb rundet der Replay dort gröber als live (TSMOM-UNG ≈ 2,6 statt 3,1 Stück). Wirkung höchstens ≈ 0,16 Punkte p.a., live ohne Bedeutung (Alpaca liefert echte Kurse).
- Aktiensplits während einer Haltephase gleicht der Live-Bot nicht aus: Nach einem Reverse-Split (UNG, USO hatten mehrere) stimmen Legs und Alpaca-Position nicht mehr überein, der Positionsabgleich hält den Bot an („ABGLEICH NÖTIG“), dann ist ein Eingriff von Hand nötig (Stückzahl des Legs in `state.json` anpassen). Selten, aber vorhersehbar: Split-Termine stehen vorab in den Alpaca-Corporate-Actions.
- Abschaltkriterium K5 auf beiden Replay-Pfaden: schlechteste 12-Monats-Rendite −18,6 % (24.12.2018), tiefste 250-Tage-Sharpe −1,20 (03.01.2019), Maximalverlust 26,7 % bzw. 24,1 %. Es hätte also nicht ausgelöst.
