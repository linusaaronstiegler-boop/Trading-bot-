# Abschluss Systembuch-Bot v2 – Claude-Code-Sitzung 15./16.10.2026

Repo `linusaaronstiegler-boop/Trading-bot-` (= `systembuch-bot`), Branch **`claude/systembuch-v2`**, ein Commit je Aufgabe. **`pytest`: 121 Tests grün**, lokal und auf GitHub (Workflow `tests`).

## Kurz

- **v2 ist gebaut.** SPEC-v2 Aufgaben 1–7 sind erledigt, alle Befunde aus `REVIEW-v1.md` eingearbeitet, dazu ein zweiter feindseliger Review der v2. Die Regeln sind unverändert, es gibt kein LLM, der Live-Pfad braucht nur die Standardbibliothek.
- **Live-Trockenlauf gegen dein Paper-Konto bestanden** (15.10., 17:34 ET, mit dem Endstand noch einmal 18:39 ET): Alpaca-Daten, Kalender, Leihbarkeit und VIX sind lesbar, es wurde nichts gesendet und nur `STATUS-dry.md` geschrieben.
- **Replay trifft K3 genau**, wenn er wie K3 rechnet: +12,0 % p.a., Sharpe 0,75, Maximalverlust 24,1 %. **So, wie der Bot bei Alpaca handeln kann: +10,2 % p.a., Sharpe 0,68, Maximalverlust 26,7 %.** Das ist kein Fehler, sondern der Preis der Vorzeichenwechsel-Sperre (siehe Abschnitt Replay).
- **Paper-Prüfungen 2, 4, 6 erledigt** (Fr 16.10., 15:33 ET): Short per MOC geht, ein Vorzeichenwechsel in einer Order geht nicht, short → long mit zwei Kauforders auch nicht. Die Sperre in beide Richtungen bleibt also nötig, live gilt +10,2 % p.a. Das Konto ist wieder flach.
- **Offen:** Prüfung 5 (braucht Actions), dein erster `dry`-Lauf in GitHub Actions und die Umstellung auf scharf.

## Was gebaut wurde

| Aufgabe | Ergebnis | Commit |
|---|---|---|
| Start | `bot.yml` → `.github/workflows/bot.yml` | 4a8fff1 |
| 1 Refactoring | `kern.py`: `entscheide()` als reine Funktion (ohne Netz und Datei), Einstiege als Schleife über `VORRANG`. **v1 = v2 auf 6 eingefrorenen Tagen** (5 aus Yahoo mit allen Regelpfaden, 1 echter Alpaca-Tag): Netto-Orders, Aus- und Einstiege identisch | 0b575d0 |
| 1 Review-Zusätze | Kalender aus `/v2/calendar` (Notlösung NYSE-Regelwerk, gegen 2010–2026 geprüft); Nachholen von MW-Verkauf und TSMOM; Vorzeichenwechsel-Sperre; SIP-Historie, Hoch/Tief zusätzlich aus `delayed_sip` | 6de0b65 |
| 2 Abrechnung | Aufträge je Symbol mit Komponenten, Fills über `/v2/orders` + `/activities/FILL`, **FIFO-Verteilung** des Netto-Fills auf die Legs, Teilfüllung, Ablehnung, Positionsabgleich, atomarer Zustand, `journal.csv` mit Fill/Schluss/`abweichung_bp`, `equity.csv` | b6061e6 |
| 3 Replay | `--replay 2010-01-01 2026-10-14`, derselbe Code wie live, Ausgabe unter `replay/`, K4-Schalter | 794d284 |
| 4 Plausibilität | Abgleich mit K3, `replay/BERICHT.md`, `replay/BEOBACHTUNGEN.md`, Zahlen im README | de29c28 |
| 5 Betrieb | ausführliches `STATUS.md`, Abschaltkriterium K5, VIX-Ersatzquellen mit Alarm, Wochenbericht, Halbtage jedes Jahr, Issue-Alarm, Artifact | e439ab2 |
| 6 Tests | je README-Regel ein Test, Lauffenster, Kalender, Netting, Ablehnung, Wiederanlauf; **Dauertest**: der echte Live-Lauf Tag für Tag gegen eine Alpaca-Attrappe (1. Hj. 2025 und ganz 2022 mit vielen Vorzeichenwechseln) – Ergebnis auf den Cent gleich dem Replay ohne Dividenden, identische Trades | 32150fc, 96c5ffa |
| 7 Echtgeld | `ucits.md`: Gegenstücke mit ISIN/Xetra/TER/Spread, Brokerkosten inkl. Traders Place, Break-even-Rechnung, C40-Ergebnis | 4516f79 |
| Review v2 | 1 Befund hoch, 5 mittel, 6 niedrig behoben (siehe unten) | c800706, ecc4c99 |
| Paper | Live-Trockenlauf, Alpaca-Fixture, `assets.json`, Prüfungen 1 und 3 | 1647d41 |
| v1-Stand 23:15 | Neue `SPEC-v2.md`, `REVIEW-v1.md`, v1-Referenz im Test ersetzt. Die drei v1-Fixes (Karfreitag 2027, Abgleich nur `us_equity` mit Exit 1 bzw. nur Meldung im dry, abgelehnte Order = Symbol unverändert + Exit 1) in v2 übernommen und **gegen v1 auf denselben Fixtures getestet** (`tests/test_v1_fixes.py`); v1 = v2 weiter auf allen 6 Tagen | 0a2a167 |
| Abschluss-Review | 6 Prüfer + Gegenprüfung je Befund (38 Agenten): 32 Befunde, 4 bestätigt und behoben, dazu 2 plausible mitbehoben (siehe Review-Abschnitt) | 9874c89, fe45d75 |

`bot.yaml` aus dem letzten Upload ist gleich dem ursprünglichen; `.github/workflows/bot.yml` bleibt die weiterentwickelte Fassung (Halbtage, dry/live-Auswahl, Artifact, Issue-Alarm).

Neue Dateien: `kern.py`, `replay.py`, `requirements-replay.txt`, `assets.json`, `ucits.md`, `werkzeuge/paper_pruefungen.py`, `pruefungen-ergebnis.md`, `replay/`, `tests/`, `.github/workflows/tests.yml`.

## Replay-Kennzahlen (04.01.2010 – 14.10.2026, 100.000 $, 3 bp je Seite, Leihbarkeit aus Alpaca)

| | K3 | **K3-Modell** (ohne Sperre) | **live** (mit Sperre) |
|---|---|---|---|
| Rendite p.a. | +12,0 % | +12,0 % | **+10,2 %** |
| Schwankung | 17,0 % | 17,0 % | 16,2 % |
| Sharpe / Sortino | 0,75 / 1,07 | 0,75 / 1,08 | 0,68 / 0,97 |
| Maximalverlust | 24,1 % (Tief 28.02.2020, 702 Tage) | 24,1 % (28.02.2020, 703 Tage) | 26,7 % (Nov. 2021 → Apr. 2025, neues Hoch 06/2026) |
| Endwert | ≈ 669.000 $ | 672.000 $ | 511.000 $ |
| Kosten / Trades p.a. / Ø Legs | 208.600 $ / 745 / 14,5 | 211.000 $ / 746 / 14,5 | 172.000 $ / 794 / 16,0 |
| Beta zu SPY / Alpha | 0,74 / +1,9 % | 0,74 / +1,8 % (t 0,66) | 0,69 / +0,9 % (t 0,33) |
| Tresor ab 02.10.2023 | +17,1 %, Sharpe 1,06, DD 18,1 % | +16,8 %, 1,05, 18,1 % | +11,5 %, 0,87, 18,8 % |
| Beitrag IBS / IBS-Land / VIX | +3,8 / +1,7 / +2,8 | +3,8 / +1,7 / +2,8 | +2,5 / +1,6 / +2,8 |
| ohne TSMOM / ohne VIX / ohne MW-Land | +11,4 / +10,0 / +10,1 | +11,5 / +10,1 / +10,6 | **+11,4** / +8,1 / +10,0 |
| VIX-Entscheidung mit Vortageswerten (pessimistische Schranke) | – | +11,1 | +9,3 |
| Korrelation IBS/IBS-Land, MW/MW-Land | 0,63 / 0,72 | 0,63 / 0,72 | 0,63 / 0,73 |

**Plausibilität:** Alle fett gedruckten Referenzwerte der SPEC treffen im K3-Modell auf ±2 %, auch die Einzelläufe (IBS allein +5,0 %, Sharpe 0,63; TSMOM Sharpe 0,54; VIX allein +3,1 %; nur IBS-Familie +7,9 %, Sharpe 0,73, DD 18,3 %) und die Jahresrenditen bis auf wenige Zehntel. Die Abweichung des Live-Modells von −15 % habe ich bis auf den Trade zurückverfolgt. Sie kommt fast ganz aus der Sperre auf der **Kaufseite** (short → long): TSMOM ist in Abwärtsphasen short SPY/QQQ/IWM, und genau dann will IBS kaufen. Mit Sperre nur auf der Verkaufsseite sind es +12,1 %. Das Live-Modell enthält auch die Wash-Trade-Lücke des BB-Stops (227 BB-Leg-Tage ohne Stop, Wirkung ≈ 0). **Unter Live-Bedingungen ist das Buch ohne TSMOM besser.** Das ist nur eine Beobachtung, entscheiden musst du (`replay/BEOBACHTUNGEN.md`). K6 ist nicht enthalten, live eher ≈ +9 % p.a. Der VIX entscheidet im Replay wie in K3 mit dem 16:15-Schluss statt um 15:45; im ungünstigsten Fall kostet das knapp 1 Punkt (Tabellenzeile oben). Abschaltkriterium K5 hätte auf keinem der beiden Pfade ausgelöst.

## Entscheidungen, die ich ohne Rückfrage getroffen habe

1. **Arbeitsbranch** `claude/systembuch-v2` statt direkt `main` (Regel meiner Umgebung). Für den Betrieb musst du nach `main` mergen (Klick unten).
2. **Fixtures:** Ohne Schlüssel kamen fünf Tage aus Yahoo-Kursen im Alpaca-Format (je ein Regelpfad). Sobald die Schlüssel da waren, kam ein echter Alpaca-`--dry`-Tag dazu (`tests/fixtures/alpaca_2026-10-15.json`). Weitere Tage lassen sich mit `--aufzeichnen` einfrieren.
3. **Vorzeichenwechsel (Review 3.2):** Heute wird nur bis null gehandelt, in beiden Richtungen. Für short → long gibt es einen Forenbericht über die Ablehnung, aber keine Doku. Den Rest holen TSMOM/MW/MW-Land/BB/VIX am Folgetag nach, bei der IBS-Familie verfällt er, weil das Signal nur für den Schluss des Signaltags gilt.
4. **Abgelehnter Ausstieg:** Er wird im nächsten Lauf ohne neue Signalprüfung nachgeholt, weil die Regel ihn am Vortag ausgelöst hat. Steht das Einstiegssignal dann weiter, gibt es einen frischen Einstieg (netto geht nur die Differenz an die Börse), so als wäre der Ausstieg am Vortag ausgeführt worden. Nicht ausgeführte Einstiege mehrtägiger Strategien werden ebenfalls nachgeholt. Ein v1-Zustand mit `ausstieg_offen` als Datum wird beim Laden übernommen.
5. **Abgelehnte Netto-Order = Symbol unverändert** (wie deine v1 von 23:15): Auch der Teil, der sich intern hätte verrechnen lassen (z. B. MW verkauft 44 SPY, IBS kauft 23), wird nicht gebucht. Alle Ausstiege bleiben offen, alle Einstiege entfallen, ein BB-Leg bekommt seinen Stop über die volle Menge zurück. Das hatte ich vorher anders gebaut (interner Teil gebucht); der Paritätstest gegen deine v1 hat den Unterschied gezeigt. **Intern verrechnete Teile** ohne Börsenorder (netto 0) werden weiter zum offiziellen Schluss gebucht. Bei einer Teilfüllung bekommen auf der Netto-Seite zuerst die Ausstiege den Fill (ältestes Leg zuerst), dann die Einstiege in Vorrang-Reihenfolge.
6. **Brutto-Deckel aus Legs statt aus Positionen** (Review 2.2): Der Positionsabgleich zu Beginn jedes Laufs stellt sicher, dass beides gleich ist.
7. **Not-Aus und K5 per MOC** statt `DELETE /v2/positions` (deine Regel 4). Gestoppt heißt jetzt: per MOC weiter abwickeln, bis alles glatt ist (rot), danach grün „gestoppt“. Ist der Not-Aus fällig und weichen Legs und Positionen ab, werden die Alpaca-Positionen glattgestellt.
8. **`--force` nur mit `--dry`.** Zusätzlich gibt es eine harte Grenze von 30 Min vor Schluss für jede Order (deine Regel 4), die Konstanten aus K6 sind unverändert.
9. **Dry-Lauf** schreibt nur `STATUS-dry.md`, auch kein `log.txt` (die Logzeilen stehen in `STATUS-dry.md`). „Kein Fenster“ schreibt gar nichts, dadurch gibt es keine Leer-Commits.
10. **Halbtage:** Statt fester Daten (27.11./24.12.) gibt es Crons für jeden Werktag im Nov./Dez. und am 3. Juli um 12:28/12:40 ET. An normalen Tagen enden sie sofort.
11. **Replay:** Die ATR kommt wie live aus der bereinigten Reihe (K3: roh). SVXY ist ab 60 Tagen Historie handelbar, wie live. Die TSMOM-Reservierung (K4-Schalter) habe ich als „Brutto für TSMOM am TSMOM-Tag vor den vorrangigen Strategien freihalten“ ausgelegt, weil die K4-Definition nicht im Repo liegt.
12. **`equity.csv`:** Die Zeile des Vortags kommt aus Alpaca `last_equity` (Schlusskurs). Lücken füllt `portfolio/history`, der Höchststand wird gegen beide geprüft.
13. **`abweichung_bp`** = Kosten der MOC-Fills gegenüber dem offiziellen Schluss, Ein- und Ausstieg zusammen und in Leg-Richtung. Positiv heißt teurer als im Replay.
14. **SVXY im Replay ab 29.12.2011** (60 Handelstage Historie, wie live in `kern.kennzahlen`), nicht ab Auflage 04.10.2011, obwohl die SPEC „ab 10/2011“ schreibt: Nur so trifft der Replay K3 (80 VIX-Trades, 2012 +21 %). Ab Auflage wären es 83 Trades und 2012 +16,8 %, weil der erste Einstieg in die Bremse fällt (BEOBACHTUNGEN 2).
15. **Neustart-Schutz (Review 2.5):** Eine vorhandene `state.json` ohne `start`/`startkapital` bei einem Konto, das schon gehandelt hat (equity.csv/journal.csv), ergibt rot „ZUSTAND FEHLT“, statt still mit Startkapital = heutige Equity neu anzufangen. Die *gelöschte* `state.json` bleibt dein README-Weg für den Neustart nach dem Not-Aus und läuft weiter, jetzt mit Warnung im STATUS. Ausdrücklicher Neustart mit vorhandener Datei: `"neustart": true`.
16. **`ucits.md`:** Traders Place ist dazugekommen (dein Broker). C40 macht die Break-even-Rechnung zur reinen Obergrenze. Es gibt eine Beobachtung zur Ausführung auf gettex um 21:45 (Test C41, nicht entschieden).

## Review-Befunde → Status

**REVIEW-v1 (14 hoch):** 3.1 Netto-Order 1:1 ans Leg ✔ (FIFO, Abnahmetest IBS+MW SPY: eine Order 84, Legs 42/42) · 3.2 Vorzeichenwechsel ✔ (Sperre in beide Richtungen; Prüfungen 4 und 6 haben das Alpaca-Verhalten am 16.10. bestätigt) · 3.5 Ablehnung als ausgeführt gebucht ✔ · 5.2 Zustand nicht atomar ✔ · 5.4 kein Nachholen ✔ · 5.5 kein Abgleich ✔ · 1.8/1.9 GTC-Stop reserviert Stücke ✔ (Storno mit Warten, neu setzen) · 1.11/1.12/4.8 Kalender ✔ · 1.3/4.2 IEX ✔ (SIP; Prüfung 1 bestanden) · 2.5 Höchststand ✔ · 3.3/3.4/5.1/6.3 schon in v1 behoben · 1.12/5.5/3.5 zusätzlich in v1 (23:15) behoben, in v2 genauso umgesetzt und gegen v1 getestet. **Mittel:** 1.2 Signalabweichung gemessen ✔ · 2.2 ✔ (Entscheidung 6) · 2.3 Marge ✔ (Prüfung 3: Reg-T 200.000 $ bei 1,9 × 100.000 $) · 3.7 Teilfüllung ✔ · 4.4 fehlendes Symbol ✔ · 4.5 VIX ✔ (Ersatzquellen, Alarm nach 3 Läufen) · 5.3 Wiederholungen 5× ✔ · 5.6 Artifact ✔ · 6.7 Exit 1 + Issue ✔. **Niedrig:** 1.18 VORRANG ✔ · 2.7 Log < 1 Stück ✔ · 3.8 Stop storniert ✔ · 4.7 Leer-Commits ✔ · 5.7 Dry schreibt Journal ✔ · 5.9 tote Felder ✔ · 6.8 STATUS-dry ✔ · 1.7 BB am Ex-Tag: offen (nur an einem SPY-Ex-Tag prüfbar) · 1.16 Short per MOC: Prüfung 2.

**Review v2 (feindselig, 15.10. 23:00, mit Gegenprüfung):**
- **Hoch:** Ein Nachläufer mit veraltetem Checkout hätte die MOC-Orders des ersten Laufs storniert und neu gesendet. ✔ Jetzt gilt: Gibt es heutige Bot-Orders bei Alpaca, die `state.json` nicht kennt, endet der Lauf ohne Änderung. Eigene MOC-Orders werden nie storniert, der Checkout holt den aktuellen Stand.
- **Mittel:** Not-Aus mit abgelehnter Order (✔ Abwicklung bis glatt) · TSMOM nach Abbruch (✔ alle Aufträge vorab gespeichert, Nachholen) · Schlüssel mit Zeilenumbruch landete im Log (✔ geprüft und geschwärzt) · Verbindungsabbruch nach dem Senden (✔ Nachschau per client_order_id) · BB-Stop ohne client_order_id (✔ übernehmen statt verdoppeln).
- **Niedrig:** BB-Höchstzahl ✔ · Aufschub ohne Kurs ✔ · Not-Aus vor dem Abgleich ✔ · Storno-Ausnahme ✔ · Uhr direkt vor dem POST ✔ · Wartezeit abzüglich Vorbereitung ✔ · Höchststand-Historie nur 1 Monat ✔ · veraltete Snapshot-Kerze ✔.
- **Mittel/niedrig (Prüfer Regeltreue/Abrechnung/API):** doppelte Journalzeilen nach Abbruch ✔ (idempotent, Zustand direkt nach der Abrechnung gespeichert) · Stop-Fill während des Wartens auf 15:45 ✔ (Stops werden zuerst abgerechnet, Ausstiege auf den Restbestand gekappt) · verwaister Stop nach abgelehnter MOC ✔ (jetzt: Leg bleibt ganz, Stop über die volle Menge zurück) · aufgeschobene Teile ohne Kurs gingen live verloren ✔ · Neustart nach Not-Aus übernahm alte equity.csv ✔ (Kurve nur ab Start) · intern verrechnete Teile zum Fill statt zum Schluss gebucht ✔ (Mischpreis je Leg) · Stop-Ausstieg verfälschte die MOC-Abweichung ✔ · Haltetage über 100 Tage falsch ✔ (Kalender reicht bis zum ältesten Leg).
- **Abschluss-Review (16.10. 00:30, Workflow mit Gegenprüfung):** bestätigt und behoben: BERICHT.md stürzte mit K4-Schaltern ab · Tresor-Abschnitt stürzte bei Zeiträumen ohne 10/2023 ab (Lernzeit-Läufe) · laufende Yahoo-Kerze wurde gecacht · ein dreimal gescheiterter Push blieb grün (jetzt Exit 1 → Issue, `rebase --abort`, Artifact vor dem Commit). Mitbehoben: Kennzahlen-Cache hängt am Inhalt der Kursdateien und am Quelltext · Review 2.5 (Entscheidung 15). Als Beobachtung statt Fehler: VIX-Schluss 16:15 gegen Entscheidung 15:45 (Variante `vix_vortag`), Stückzahl aus split-bereinigtem Yahoo-Close bei UNG/USO (wie K3, ≤ 0,16 Punkte), SVXY-Start (Entscheidung 14).
- **Hoch (Prüfer Abrechnung):** BB-Stop nach MOC-Kauf im Symbol wird von Alpaca abgelehnt (Wash-Trade-Schutz). ✔ teilweise: Der Bot setzt den Stop jetzt bewusst erst im nächsten Lauf neu, statt eine Ablehnung zu provozieren, und der Replay bildet die Lücke ab (Wirkung ≈ 0). Lückenlos nur mit Nachlauf außerhalb des Fensters (offen, siehe oben).

## Paper-Prüfungen (REVIEW-v1 §8)

| Nr. | Prüfung | Ergebnis |
|---|---|---|
| 1 | Snapshot `feed=delayed_sip` | **bestanden**: HTTP 200, Hoch/Tief aus SIP |
| 2 | Short-MOC 1 IWM ohne Position | **bestanden** (16.10., 15:33 ET): angenommen (Status `new`). Leerverkauf per MOC funktioniert (Review 1.16) |
| 3 | SVXY-Marge, Kaufkraft | **bestanden**: SVXY marginable, Wartungsmarge 30 %, nicht leihbar; Reg-T-Kaufkraft 200.000 $ (2×), Deckel des Bots 190.000 $ |
| 4 | Long 1 SPY, Verkauf 2 SPY MOC | **bestätigt Review 3.2**: Verkauf 2 abgelehnt, „insufficient qty available for order (requested: 2, available: 1)“. Long → short geht nicht in einer Order |
| 5 | VIX im ersten Actions-`dry`-Lauf | **offen**: lokal kam der VIX von Yahoo query1. Auf GitHub-IPs zeigt es dein erster `dry`-Lauf in `STATUS-dry.md` („Quelle: …“) |
| 6 | Short 1 IWM, dann 2 Kauf-MOC (neu) | **negativ**: Eindecken angenommen, zweiter Kauf abgelehnt („insufficient qty available“, `held_for_orders` 1). Short → long geht auch mit zwei Orders nicht, **die Sperre auf der Kaufseite bleibt** (`VORZEICHENWECHSEL_SPERRE = 'beide'`). Die ≈ 1,9 Punkte p.a. sind nur über ein zweites Konto für TSMOM erreichbar (BEOBACHTUNGEN 1, Weg 2) |

`assets.json` ist eingefroren: nicht leihbar sind EWG, USO und FXE, genau wie in K3 angenommen. Aufgeräumt: Alle Test-Orders sind storniert oder glattgestellt, das Konto ist flach (Equity 100.000,05 $, keine offenen Orders). Rohausgabe: `pruefungen-ergebnis.md`.

## Offen

- Prüfung 5 und der grüne Actions-`dry`-Lauf brauchen die Secrets.
- Sperre auf der Kaufseite: Prüfung 6 hat sie bestätigt, `VORZEICHENWECHSEL_SPERRE` bleibt auf `'beide'`. Offen ist nur deine Entscheidung, ob TSMOM unter Live-Bedingungen bleibt (live ohne TSMOM +11,4 statt +10,2 % p.a.) oder in ein zweites Paper-Konto wandert. Dafür eine Sitzung mit dir und einen vorab festgeschriebenen Test.
- BB-Stop nach MOC-Kauf im selben Symbol: Wegen Alpacas Wash-Trade-Schutz bleibt das Leg bis zum nächsten Lauf ohne Stop (Replay: 227 Leg-Tage, Wirkung ≈ 0). Lückenlos ginge es nur mit einem Stop-Nachlauf um ≈ 16:05 ET, also außerhalb deines Orderfensters (Regel 4). Deine Entscheidung, nicht gebaut.
- Randfall: Ein BB-Long und ein TSMOM-Short im selben ETF mit netto Short-Bestand. Dann ist der GTC-Stop des BB-Legs bei Alpaca ein Leerverkaufs-Stop. Lehnt Alpaca ihn ab, gibt es eine Warnung im STATUS, und der Stop fehlt bis zum Ausstieg.
- Review 1.7 (BB-Signal am Ex-Dividenden-Tag): beobachten, wenn SPY ex geht.
- Splits: Ein (Reverse-)Split während einer Haltephase (UNG, USO hatten mehrere) lässt Legs und Alpaca-Position auseinanderlaufen → „ABGLEICH NÖTIG“, Stückzahl des Legs in `state.json` von Hand anpassen. Automatik nicht gebaut.
- K4-Variante „TSMOM-Reservierung“: Auslegung prüfen (Entscheidung 11).
- Kalender, Monatswechsel-Termine und Wochenbericht laufen im Echtbetrieb erstmals zum Monatsende Oktober (29./30.10.).

## Deine Klicks

1. **Schlüssel erneuern:** Die jetzigen stehen im Chatverlauf. Alpaca → Paper-Konto → *API Keys* → *Regenerate*, neues Paar notieren.
2. **Secrets:** github.com/linusaaronstiegler-boop/Trading-bot- → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*: `APCA_API_KEY_ID`, dann `APCA_API_SECRET_KEY`. Ohne Leerzeichen und Zeilenumbruch einfügen (sonst bricht der Bot mit „Sonderzeichen“ ab).
3. **Schreibrechte:** *Settings* → *Actions* → *General* → *Workflow permissions* → **Read and write permissions** → *Save*.
4. **Mergen:** Repo-Startseite → gelber Balken „claude/systembuch-v2 had recent pushes“ → *Compare & pull request* → *Create pull request* → *Merge pull request* → *Confirm merge*. Erst danach laufen Schedules und *Run workflow* für `systembuch-bot`.
5. **Paper-Prüfungen:** erledigt am 16.10. (2, 4, 6; Ergebnis oben). Nur falls du sie mit neuen Schlüsseln wiederholen willst, lokal Mo–Fr 21:30–21:49 MESZ und vor dem ersten Live-Lauf:
   `APCA_API_KEY_ID=… APCA_API_SECRET_KEY=… python3 werkzeuge/paper_pruefungen.py --orders`
6. **Erster `dry`-Lauf:** *Actions* → *systembuch-bot* → *Run workflow* → Branch `main`, modus **dry** → *Run workflow*. Danach `STATUS-dry.md` im Repo öffnen: Signale, Netto-Orders, „Quelle:“ beim VIX (Prüfung 5), keine Warnungen. Der Lauf muss grün sein.
7. **Scharf schalten:** Es gibt nichts umzuschalten. Nach dem Merge laufen die Schedules Mo–Fr von selbst (15:28/15:40 ET) und handeln im Fenster. **Wenn du erst nach den Prüfungen scharf willst:** *Actions* → *systembuch-bot* → *…* → *Disable workflow*, und nach den Prüfungen *Enable workflow*.
8. **Benachrichtigung:** Oben rechts *Watch* → *Custom* → *Issues* anhaken. Jeder rote Lauf legt ein Issue an, und du bekommst eine Mail.
9. **Täglich:** `STATUS.md` im Repo lesen. Wöchentlich: `berichte/JJJJ-WW.md`.

## Umgebung dieser Sitzung

Yahoo war erreichbar (über den vorkonfigurierten Proxy der Umgebung, kein Umweg). Alpaca hat bis zu deiner Nachricht mit 401 geantwortet (keine Schlüssel), danach normal. Die Schlüssel standen nur als Umgebungsvariable in einzelnen Befehlen. Eine Suche über alle Repo-Dateien findet sie nicht. Eine Ablage „Projekt Trading“ ist aus dieser Sitzung nicht erreichbar (in Google Drive gibt es keinen passenden Ordner mit den K-Studien). `ABSCHLUSS.md` liegt deshalb im Repo, bitte von dort in das Cowork-Projekt übernehmen.
