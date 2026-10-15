# Systembuch-Bot

Handelt **nur die belegten Regeln** von Linus' Trading-Projekt auf einem Alpaca-Paper-Konto – reines Python, kein LLM, keine Rechenkosten. Ein Lauf pro US-Handelstag: Start 15:28 New York (Cron), **Entscheidung 15:45 New York** (21:45 MESZ / MEZ; 26.–30.10. 20:45 MEZ), alle Orders Market-on-Close vor dem Annahmeschluss 15:50.

> **Stand 15.10.2026, 22:30 – v1 ist ein Trockenlauf-Stand, kein Live-Stand.** Der feindselige Code-Review (`REVIEW-v1.md`, 14 Befunde „hoch“) hat Fehler gefunden, die im Betrieb Geld kosten: Netto-Orders werden dem ersten Leg 1:1 zugeordnet (doppelte Stückzahl im Zustand), abgelehnte Orders werden als ausgeführt gebucht, kein Positionsabgleich gegen Alpaca, Monatswechsel/TSMOM werden nach verpasstem Lauf nicht nachgeholt, Feiertagstabelle falsch (Karfreitag 2027), IEX-Feed verzerrt das IBS auf dünnen ETFs. Zwei Befunde sind hier schon behoben (Commit-Schritt in `bot.yml`, MOC-Annahmeschluss/Lauffenster). **Scharf geschaltet wird erst v2 nach SPEC-v2 inkl. Review-Befunden.** Bis dahin nur `dry`.

| Strategie | Markt | Regel | Größe | Beleg |
|---|---|---|---|---|
| IBS | SPY QQQ DIA IWM | IBS = (Kurs − Tief)/(Hoch − Tief) < 0,2 → Kauf zum Schluss, Verkauf nächster Schluss (Folgesignal: halten) | 25 % je ETF | C1a: +6,3 % p.a. bei 20 % Investitionszeit, t 3,1 |
| IBS-Sektor | 9 Sektor-ETFs | wie IBS, nur an Tagen ohne Index-Signal, max 4 | 11 % | C4: t 2,8 |
| IBS-Land | 14 Länder-ETFs | wie IBS, max 4, niedrigster IBS zuerst | 7 % | C18: t 5,6, α +5 % p.a. |
| BB-Rückkehr | SPY QQQ DIA IWM | Schluss > SMA200 und < SMA20 − 2σ → Kauf; Stop 3×ATR20; Ausstieg Schluss > SMA20, spätestens Tag 15 | 25 % | A1a (Bündel t 2,3) |
| Monatswechsel | SPY QQQ DIA IWM | Kauf vorletzter Handelstag, Verkauf 3. Handelstag | 25 % je ETF | A1a |
| Monatswechsel-Land | 12 Länder-ETFs | dito | 4 % je ETF | C11 formal (experimentell) |
| TSMOM | 20 ETFs | letzter Handelstag: long/short nach 12-Monats-Vorzeichen, 10 %/Vol60, Deckel, ×0,36, Brutto ≤ 60 % | je Gewicht | C17: t 2,4 |
| VIX-Contango | SVXY | VIX3M/VIX > 1,01 → long; flach < 1,00 | 10 % | C16 (Experiment) |

Grenzen: Brutto ≤ 1,9 × Equity (Vorrang IBS → Monatswechsel → BB → Sektor → Land → TSMOM → MW-Land → VIX), Bremse ab 15 % unter Höchststand (alle Größen halbiert), **Not-Aus unter 70 % des Startkapitals** (alles glatt, Bot stoppt – `state.json` dann von Hand löschen oder `gestoppt` auf `false`).

Erwartung (ehrlich, **Replay K3 vom 15.10.2026**, alle acht Regeln exakt wie oben, 01/2010–14.10.2026, Yahoo-Tageskurse, 3 bp je Seite, 100.000 $ Start): **+12,0 % p.a., Schwankung 17 %, Sharpe 0,75, Maximalverlust 24 %** (Jan. 2018 → Feb. 2020, 702 Handelstage bis zum neuen Hoch), vier negative Kalenderjahre von 17 (2015, 2018, 2022, 2024). Letzte drei Jahre (ab 10/2023): +17,1 % p.a., Sharpe 1,06, Maximalverlust 18 %. Beta 0,74 zu SPY, Alpha +1,9 % p.a. (t 0,7) – **ein Long-Aktien-Buch mit gedämpftem Verlust, kein marktneutrales.** Drei Regeln tragen drei Viertel: IBS (+3,8 % p.a.), VIX-Contango (+2,8 %), IBS-Land (+1,7 %). Plausibilität gegen die Einzeltests: IBS allein +5,0 % p.a. (C1a ≈ +6 %), IBS-Land t 5,2 auf Trade-Ebene (C18 ≈ 5), TSMOM allein Sharpe 0,54 (C17 ≈ 0,5). Rechne mit +10–12 % p.a. und einem Verlust von 20–25 %, der zwei bis drei Jahre dauern kann. Quelle: `vault/Studie-2026-10-15-K3-Systembuch-Replay.md` im Projekt.

**K4 (15.10.2026): keine Strukturänderung bestanden.** Sieben Varianten (ohne IBS-Sektor, ohne MW-Land, TSMOM-Reservierung am Monatsende, Bremse 20 % / ×0,75, Deckel 1,5×) wurden gegen vorab festgelegte Kriterien geprüft; keine erfüllt alle (`vault/Studie-2026-10-15-K4-Systembuch-Struktur.md`). Das Buch bleibt bei acht Regeln, Deckel 1,9×, Bremse 15 % → ×0,5. Knapp gescheitert: Bremse ×0,75 (Sharpe Hälfte 1 um 0,01 verfehlt) – bewusst nicht übernommen.

**K5 (15.10.2026) – was das wirklich ist:** Der messbare Vorteil des Buchs gegenüber 0,74 × SPY beträgt +1,95 Prozentpunkte p.a. (t 0,7). Block-Bootstrap über drei Jahre: Rendite p.a. zwischen −3,4 % (5. Perzentil) und +28,7 % (95.), Median +12,3 %; jedes fünfte Dreijahresfenster hat einen Verlust über 25 %, jedes zweite ein negatives Jahr; über fünf Jahre ist ein Drawdown von 22 % der Normalfall und 37 % das 95-%-Szenario, mit Verlustphasen bis fast vier Jahre. Szenario „halber Vorteil“ (halbes Alpha): Median +11,2 %; „kein Vorteil“ (nur Beta): +10,0 % – **im Konto nicht unterscheidbar** (80 % Trennschärfe erst nach Jahrhunderten). Wer den Bot startet, kauft im Wesentlichen 0,74 × Marktprämie mit Hebelspitzen bis 1,9× und 745 Trades im Jahr; der Regelvorteil ist eine begründete Hoffnung mit t 0,7, belegt auf Trade-Ebene (IBS-Land t 5,2), nicht auf Kontoebene. Quelle: `vault/Studie-2026-10-15-K5-Bootstrap-Abschaltkriterium.md`.

**K6 (15.10.2026) – Ausführungslücke:** Der Bot entscheidet vor dem Schluss, die Rückrechnungen mit der fertigen Kerze. Mit Alpaca-15-Minuten-Bars gemessen: Das Signal 15 Minuten vor Schluss behält 91 % des IBS-Familien-Ertrags (Index 102 %, Sektor 107 %, **Land 64 %**), das Signal 30 Minuten vor Schluss nur 46 %. Folge (vorab festgeschrieben): Entscheidung um **15:45 ET** (Code wartet im Lauf bis dahin, Orders bis 15:48, harter Abbruch unter 10,5 Min vor Schluss). Erwartung für IBS deshalb um ein Zehntel, für IBS-Land um ein Drittel niedriger ansetzen als K3 (≈ −0,4 bzw. −0,6 Punkte p.a.). Quelle: `vault/Studie-2026-10-15-K6-Ausfuehrungsluecke.md`.

## Abschaltkriterium (K5, 15.10.2026)
Drei Kennzahlen aus der eigenen Kontokurve seit Bot-Start, geprüft in jedem Lauf und in `STATUS.md` ausgewiesen; **eine Verletzung genügt → Bot setzt `gestoppt`, Sitzung mit Linus entscheidet. Kein automatisches Weiterhandeln mit halber Größe.**

| Kennzahl | Schwelle | Kalibrierung |
|---|---|---|
| Rollierende 12-Monats-Rendite (ab Tag 252) | **≤ −24 %** | 5 % Fehlalarm je Jahr im Szenario „wie K3“; der historische Pfad lag schlimmstenfalls bei −19 % (Dez. 2018) |
| Drawdown vom Höchststand seit Start (ab Tag 1) | **≥ 34 %** | über dem historischen Maximum (24 %), weil die Historie nur ein Pfad ist; Not-Aus 70 % des Startkapitals bleibt daneben bestehen |
| Rollierende 250-Tage-Sharpe, rf 0 (ab Tag 250) | **≤ −1,30** | historisch tiefster Wert −1,20 (Jan. 2019) |

Ehrlich: Das Kriterium ist ein Katastrophenschutz, kein Vorteilsmesser. Es erkennt ein Buch, das strukturell verliert (48 % binnen drei Jahren), aber nicht ein Buch, das nur sein Alpha verloren hat (16 % binnen drei Jahren) – das ist mit 17 % Schwankung auf der Kontokurve nicht messbar. Ob der Vorteil lebt, prüft man auf Trade-Ebene (IBS-Familie: Ø bp je Haltetag und t im Journal, Vergleich mit K3: Index +16 bp, Land +13 bp), nicht am Kontostand.

## Einrichtung (einmalig, ≈ 10 Minuten)
1. **Alpaca:** Im Dashboard unter *Paper Trading* ein **zweites Paper-Konto** anlegen (Konto-Menü → „+ New Paper Account“, 100.000 $), dort unter *API Keys* ein Schlüsselpaar erzeugen. Nicht das Konto des Agenten 200k verwenden.
2. **GitHub:** Privates Repo `systembuch-bot` anlegen (ohne Branch-Schutz, Workflow auf `main`), diese Dateien hochladen (`systembuch_bot.py`, `README.md`, `SPEC-v2.md`, `REVIEW-v1.md`, `yahoo_vorbild.py`, `bot.yml` → wird nach `.github/workflows/bot.yml` verschoben).
3. **Secrets:** Repo → Settings → Secrets and variables → Actions → `APCA_API_KEY_ID` und `APCA_API_SECRET_KEY` eintragen. Die Schlüssel stehen sonst nirgends.
4. **Actions erlauben:** Settings → Actions → General → „Read and write permissions“ (damit der Bot `state.json`, `journal.csv`, `STATUS.md` zurückschreiben kann).
5. **Probelauf:** Actions → systembuch-bot → *Run workflow* → modus `dry`. Danach `STATUS.md` im Repo lesen: Signale und geplante Orders, nichts gesendet.
6. Ab dann läuft er von selbst Mo–Fr. Stand jederzeit in `STATUS.md`, jede geschlossene Position in `journal.csv`, Fehler in `log.txt`. Im Alpaca-Dashboard siehst du Orders und Positionen.

Hinweis zur Ausführung: Einstiege und Ausstiege sind Market-on-Close (Füllung zum offiziellen Schlusskurs, wie im Backtest). Der BB-Stop (3×ATR) wird am Folgetag nach bekanntem Fill als GTC-Stop gesetzt; am Einstiegstag selbst gibt es keinen Stop (Lücke von einem Tag, im Backtest ebenfalls so).

Lokal statt GitHub: `APCA_API_KEY_ID=… APCA_API_SECRET_KEY=… python3 systembuch_bot.py --dry --force` (Aufgabenplanung 21:28 Berlin ohne `--dry --force`; der Lauf wartet selbst bis 15:45 ET).

## Was der Bot NICHT tut
Kein Daytrading, keine Optionen, kein Polymarket, kein Hebel über die Alpaca-Marge hinaus, kein Nachkaufen, keine Regel, die nicht vorab getestet wurde. Änderungen an den Regeln nur mit neuem Test (Lernzeit, Tresor, t ≥ 2/3) – siehe `wissen/11-Testplan-2026-10.md` im Projekt.

## Echtgeld-Hinweis
US-ETFs (SPY, QQQ …) sind für Privatkunden in der EU nicht kaufbar (PRIIPs/KID). **Test C40 (15.10.2026, `vault/Befund-2026-10-15-C40-IBS-UCITS.md`) hat die UCITS-Kopie geprüft und verworfen:** IBS auf neun Xetra-UCITS-ETFs (SXR8, SXRV, EUNL, SXRT, EXS1, IS3N, SXR5, EXSA, IUSN) ist auch ohne Ordergebühr netto nicht positiv (Lernzeit +1,8 % p.a., t 0,7; seit 2018 und seit 10/2023 negativ), mit 1 € je Order bei 1.000 € Konto −45 % p.a. (600–760 Orders im Jahr). Grund ist zuerst das Instrument: Die Xetra-Kerze endet 17:30 MEZ und sieht die US-Schlussauktion nicht, in der die Rückkehr entsteht (SPY/QQQ im selben Zeitraum +6,3 % p.a., t 2,3). **Es gibt keinen Kontostand, bei dem diese Kopie Geld verdient.** Der Bot bleibt deshalb ein US-Paper-Bot; die 1.000 € gehen nicht in IBS auf UCITS-ETFs. Ein Weg zum US-Schluss für deutsche Privatkunden (Index-CFD/Knock-out ab 22:00 MEZ) wäre ein eigener Test mit größerem Konto, frühestens nach dem Echtgeld-Kriterium in `wissen/08-Echtgeld-Regeln.md`.
