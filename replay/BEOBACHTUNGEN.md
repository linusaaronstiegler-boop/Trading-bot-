# Beobachtungen aus dem Replay v2 (15.10.2026)

Nur Beobachtungen. Keine Regel wurde geändert, über alles hier wird in einer Sitzung mit Linus und mit vorab festgeschriebenem Test entschieden.
Zahlen: `replay/BERICHT.md`, 04.01.2010 bis 14.10.2026, 100.000 $, 3 bp je Seite.

## 1. Die Vorzeichenwechsel-Sperre kostet 1,9 Punkte p.a.

| | p.a. | Sharpe | Maximalverlust | Tresor ab 10/2023 |
|---|---|---|---|---|
| K3-Modell (ohne Sperre, = K3) | +12,0 % | 0,75 | 24,1 % | +16,8 % |
| Sperre nur long → short | +12,1 % | 0,76 | 24,1 % | – |
| Sperre beide Richtungen (live) | +10,2 % | 0,68 | 26,7 % | +11,7 % |

- Alpaca kann eine Position nicht an einem Tag durch null drehen (Review 3.2). Für long → short ist das belegt (zweite Verkaufsorder: „insufficient qty“). Für short → long gibt es einen Forenbericht vom 23.12.2022 mit derselben Ablehnung auf der zweiten Kauforder ([forum.alpaca.markets/t/11413](https://forum.alpaca.markets/t/changing-short-to-long-get-insufficient-quantity-available-even-after-check-for-no-open-orders/11413)). Eine verbindliche Doku gibt es nicht. Der Bot sperrt deshalb beide Richtungen.
- Die Sperre auf der Verkaufsseite kostet nichts. Der Verlust entsteht auf der Kaufseite: TSMOM ist in Abwärtsphasen short SPY/QQQ/IWM/EEM, und genau dann kauft IBS dieselben ETFs. IBS verdient in Abwärtsphasen am meisten. Die Sperre schneidet deshalb gezielt die besten IBS-Trades ab. Beispiel: QQQ am 09.11.2022 mit 13 statt ≈ 300 Stück, am 10.11. stieg QQQ um 7 %. 2022 bringt IBS mit Sperre −31.500 $, ohne +8.500 $, bei fast gleich vielen Trades (189 gegen 186).
- Folgeeffekt: Das Konto fällt 2022 tiefer, die Bremse (×0,5) greift 2023–2025 an 79–91 % der Tage, und das Buch braucht bis Juni 2026 für ein neues Hoch (1.146 Handelstage).
- Unter Live-Bedingungen ist **„ohne TSMOM“ besser als das Gesamtbuch**: +11,5 % gegen +10,2 % p.a., Sharpe 0,72 gegen 0,68. Im K3-Modell bringt TSMOM dagegen +0,5 Punkte.

Mögliche Wege, alle mit vorab festgeschriebenem Test zu entscheiden:
1. Auf dem Paper-Konto prüfen, ob short → long mit zwei Kauf-MOC-Orders angenommen wird (zusätzliche Fünf-Minuten-Prüfung 6 in ABSCHLUSS.md). Wenn ja, `flip_sperre='verkauf'` im Live-Lauf. Das ist eine Ausführungsfrage, keine Regeländerung. Ergebnis dann ≈ +12,1 % p.a.
2. TSMOM in ein zweites Alpaca-Paper-Konto legen. Dann gibt es kein Netting zwischen TSMOM-Shorts und den Long-Strategien, und der Replay entspricht dem K3-Modell. Brutto-Deckel und Bremse müssten über beide Konten gerechnet werden.
3. TSMOM streichen. Das wäre eine Regeländerung mit eigenem Test, und K4 hat Strukturvarianten bisher alle verworfen.

## 2. VIX-Contango trägt viel auf wenig Trades

+2,8 Punkte p.a. (zweitgrößter Beitrag) aus 80 Trades mit 34 % Treffern und Ø +637 bp je Trade. Live ohne VIX: +7,9 % p.a. (K3-Modell +10,1 %). In der README steht die Regel als „Experiment“ (C16). Der Beitrag hängt an wenigen langen Haltephasen (Ø 41 Tage). Außerdem hat sich das Produkt geändert: SVXY war bis 27.02.2018 −1× und ist seitdem −0,5×.

## 3. IBS-Sektor ist auf Trade-Ebene schwach

Ø +5,5 bp (K3-Modell) bzw. +6,0 bp (live) je Trade, t 1,4–1,6. Der Einzeltest C4 nennt t 2,8. Beitrag im Buch +0,3–0,4 Punkte. K4 hat „ohne IBS-Sektor“ geprüft und verworfen, das bleibt so.

## 4. Monatswechsel-Land

Live +0,3 Punkte p.a. (Summe −1.600 $), im K3-Modell +0,6. Die Korrelation zu Monatswechsel liegt bei 0,72. Variante „ohne MW-Land“: live +9,8 % gegen +10,2 %, also für das Buch noch leicht positiv.

## 5. Was der Replay nicht zeigt

- K6: Die Rückrechnung entscheidet am Schluss, der Bot schon um 15:45. Laut README sind deshalb für IBS rund −0,4 und für IBS-Land rund −0,6 Punkte p.a. abzuziehen. Live liegt die Erwartung also eher bei +9 % als bei +10 %.
- MOC-Fill gegen Schlusskurs: Das misst der Live-Bot im Journal (`abweichung_bp`).
- Die Leihbarkeit ist die K3-Annahme (EWG, USO, FXE nicht leihbar), bis `assets.json` von Alpaca eingefroren ist.
- Abschaltkriterium K5 auf beiden Replay-Pfaden: schlechteste 12-Monats-Rendite −18,6 % (24.12.2018), tiefste 250-Tage-Sharpe −1,20 (03.01.2019), Maximalverlust 26,7 % bzw. 24,1 %. Es hätte also nicht ausgelöst.
