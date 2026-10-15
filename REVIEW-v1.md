# Review v1 – Systembuch-Bot (feindseliger Gutachter, Tagesschicht 31, 15.10.2026 18:25 MESZ)

Gegenstand: `systembuch_bot.py` v1, `bot.yml`, `README.md` (maßgeblich), `SPEC-v2.md`. Referenz für Regeltreue: `code/forschung/K3/bt.py` (1:1-Nachbau, Replay +12,0 % p.a.). Geprüft wurde: Alpaca-Doku zu `cls`-Annahmeschluss und Fehlerursachen (WebFetch docs.alpaca.markets, alpaca.markets/learn), `git add`-Verhalten (lokal getestet), Osterformel 2027, Monatswechsel-Termine aus `handelstage()` (nachgerechnet). Keine Code-, Regel- oder Workflow-Änderung vorgenommen.

*Nachtrag Sitzung 22:30: Befunde 5.1 (Commit-Schritt), 3.3/3.4/6.3 (Lauffenster, MOC-Annahmeschluss, Nachläufer) und 1.11 (Halbtage als Cron) sind in v1 bereits behoben (bot.yml, Fensterkonstanten). Alle übrigen Befunde gelten für v2.*

Legende: ✔ erfüllt · ✘ Fehler · ? Vermutung mit 5-Minuten-Prüfung · Schwere: **hoch** = kostet Geld oder stoppt den Bot im Normalbetrieb, mittel = tritt in Sonderfällen ein, niedrig = kosmetisch/später.

**Bilanz: 14 Befunde hoch (17 Tabellenzeilen, davon 3 Querverweise) · 10 mittel · 13 niedrig.** Die vier gefährlichsten: (H1) der Commit-Schritt scheitert, solange `journal.csv` nicht existiert → `state.json` geht nach dem ersten Live-Lauf verloren, Positionen werden täglich neu gekauft und nie verkauft; (H2) Netto-Order je Symbol wird dem ersten Leg als `order_id` zugewiesen → beim ersten Tag mit IBS+BB oder IBS+MW auf SPY steht im State die doppelte Stückzahl; (H3) Orderfenster 10–30 Min vor Schluss kollidiert mit Alpacas MOC-Annahmeschluss 15:50 ET und Cron-Verzug von GitHub; (H4) abgelehnte Orders werden trotzdem als ausgeführt verbucht.

---

## 1 Regeltreue gegen README (Referenz K3/bt.py)

| # | Regel | Urteil | Fundstelle | Fehlerszenario | Schwere | Vorschlag |
|---|---|---|---|---|---|---|
| 1.1 | IBS = (Kurs−Tief)/(Hoch−Tief), Klemmung 0–1, 0,5 bei Hoch=Tief | ✔ | `kennzahlen()`, `hi=max(h,px)`, `lo=min(l,px)` | – | – | identisch mit K3 |
| 1.2 | IBS-Signal zum **Schluss** | ✘ strukturell | `main()` Schritt 3/5: Signal auf IEX-Kurs vor Schluss, Fill 16:00 | SPY dreht in den letzten 15 Min von IBS 0,15 auf 0,25 → Kauf ohne Signal (oder umgekehrt). K3 (+3,8 % p.a. aus IBS) kennt diesen Fehler nicht. | mittel | v2 misst „Signalabweichung“: IBS zur Entscheidung vs. IBS aus der Tagesbar des Folgelaufs, Anteil gekippter Signale im STATUS; Fenster so spät wie Alpaca erlaubt (K6: 15:45). |
| 1.3 | Hoch/Tief/Kurs vom **IEX-Feed** | ✘ | `snapshots()` `feed=iex`, `bars()` `feed=iex` | IEX trägt ≈ 2–3 % des Volumens; bei EWL/EWP/EWH/DBA/UNG liegen IEX-Tageshoch/-tief enger als konsolidiert → IBS systematisch verzerrt, `latestTrade` kann Stunden alt sein. Tage ohne IEX-Trade fehlen in der Historie → SMA200/`ret12` über falsche Lookbacks. | **hoch** | Historie mit `feed=sip` laden (Basic-Plan erlaubt SIP außer den letzten 15 Min); Snapshot-Hoch/Tief mit `feed=delayed_sip` (? – in 5 Min prüfen: `GET /v2/stocks/snapshots?symbols=EWL&feed=delayed_sip` muss 200 liefern) und letzten Kurs aus IEX. |
| 1.4 | Folgesignal halten | ✔ | Schritt 4: `ibs<0,2 → leg['datum']=heute` | – | – | wie K3 |
| 1.5 | Sektor nur ohne Index-Signal, max 4, niedrigster IBS zuerst | ✔ | `if not index_signal and not offen('IBS')`, `sorted(key=ibs)` | `not offen('IBS')` ist redundant, aber harmlos | – | – |
| 1.6 | Land max 4, niedrigster IBS zuerst, gehaltene zählen mit | ✔ | `offen('IBS_LAND') < 4` | – | – | – |
| 1.7 | BB: Schluss > SMA200 und < SMA20−2σ, σ mit ddof=1, adj-Reihen | ✔ | `kennzahlen()`: `adjustment=all` + heutiger Rohkurs | Am Ex-Dividenden-Tag hängt es davon ab, ob Alpaca die heutige Dividende schon in `adjustment=all` einrechnet (? – an einem SPY-Ex-Tag `bars` ohne/mit `adjustment` vergleichen). | niedrig | – |
| 1.8 | BB-Stop 3×ATR20 als GTC am Folgetag | ✔ mit Haken | Schritt 1 | Stop wird erst im Folgetagslauf gesetzt – K3 rechnet Stop ab t0+2 intraday, also konsistent. Aber: der GTC-Stop **reserviert** die Stücke bei Alpaca; eine MOC-Verkaufsorder einer anderen Strategie im selben Symbol wird mit 403 „insufficient qty available“ abgelehnt, wenn sie mehr als Position−reserviert verlangt. | **hoch** | Vor dem Senden alle offenen Orders des Symbols stornieren, auf Status `canceled` warten (Storno ist asynchron), Stop danach neu setzen; oder BB-Stop als Teil der Tageslogik statt GTC. |
| 1.9 | Stop-Storno vor MOC-Ausstieg | ? | `alp(DELETE)` dann sofort `POST /v2/orders` | Storno noch `pending_cancel` → Verkauf abgelehnt (1.8) oder, wenn Storno scheitert (`except: pass`), Stop und MOC verkaufen beide → ungewollter Short. | mittel | nach DELETE Status pollen (max. 10 s), bei Fehlschlag Ausstieg verschieben und loggen. |
| 1.10 | Ausstieg Tag 15 | ✔ | `handelstage_zwischen()` ≥ 15 = K3 `t−t0 ≥ 15` | hängt am Feiertagskalender (1.12) | niedrig | – |
| 1.11 | Monatswechsel: vorletzter / 3. Handelstag | ✔ Formel, ✘ Kalender | `handelstage()` | **27.11.2026 ist vorletzter Handelstag UND Halbtag (Schluss 13:00 ET)**: ohne Halbtags-Cron kein Lauf → MW-Kauf für November fällt aus. `HALBE_TAGE` ist definiert, wird aber nirgends benutzt. | **hoch** | Halbtags-Crons (seit 22:30 in bot.yml). Besser: Kalender aus `GET /v2/calendar` (liefert `close` je Tag) statt Tabelle. |
| 1.12 | Feiertagstabelle | ✘ | `FEIERTAGE` | **Karfreitag 2027 ist der 26.03., nicht 02.04.** (Ostern 28.03.2027). Tabelle endet 12/2027: ab 01/2028 sind alle Feiertage Handelstage. | **hoch** | `GET /v2/calendar?start=&end=` (kostenlos) als einzige Quelle; Tabelle nur als Offline-Fallback mit Verfallswarnung im Log. |
| 1.13 | TSMOM nur am letzten Handelstag | ✔ | `tsmom_tag` | kein Nachholen bei verpasstem Lauf (siehe 5.4) | – | – |
| 1.14 | TSMOM-Gewichte: Vorzeichen 12M, 10 %/Vol60 (Deckel 2,0, Vol-Boden 2 %), Roh-Brutto ≤ 4,0, ×0,36, Brutto ≤ 60 % | ✔ | `tsmom_gewichte()` = K3 | – | – | – |
| 1.15 | Shorts nur `shortable` | ✔ | `alp('/v2/assets/{s}')` | `easy_to_borrow` nicht geprüft – auf Paper egal; `except → False` ist konservativ richtig | niedrig | – |
| 1.16 | Short-Verkauf per MOC | ? | Schritt 6 `side=sell`, `cls` | Alpaca-Doku nennt Short+CLS nicht; falls abgelehnt → 2.7/3.5 | niedrig | Paper-Test: 1 Stück IWM short mit `cls` um 15:40 senden, Status prüfen. |
| 1.17 | VIX3M/VIX > 1,01 → SVXY 10 %, flach < 1,00 | ✔ | Schritt 4/5 | – | – | – |
| 1.18 | Gewichte 25/11/7/25/25/4/10 %, Vorrang IBS→MW→BB→Sektor→Land→TSMOM→MW-Land→VIX | ✔ | Reihenfolge der `plane()`-Aufrufe | `VORRANG` ist definiert, wird aber nicht benutzt – Reihenfolge steckt im Code | niedrig | Einstiege als Schleife über `VORRANG` (v2 Aufgabe 1). |

## 2 Größen und Grenzen

| # | Punkt | Urteil | Fundstelle | Fehlerszenario | Schwere | Vorschlag |
|---|---|---|---|---|---|---|
| 2.1 | Brutto ≤ 1,9× mit Vorrang (Überspringen, nicht Skalieren) | ✔ | `plane()`: `brutto(bleibende+neu)+nominal > 1,9·eq → skip` | = K3 | – | – |
| 2.2 | Brutto-Basis = State-Legs zum IEX-Kurs | ✘ | `brutto()` | Weicht State von Alpaca ab (H1/H2/H4), rechnet der Deckel mit Phantom-Legs oder übersieht echte → Margin-Ablehnung oder Übergewicht | mittel | Brutto aus `GET /v2/positions` (`market_value`) statt aus Legs. |
| 2.3 | 1,9× gegen Alpaca-Marge | ? | – | Reg-T-Overnight-Buying-Power = 2× Equity; SVXY/UNG/USO können erhöhte Margin oder `marginable=false` haben → „insufficient buying power“, Order weg (und per H4 trotzdem verbucht) | mittel | `GET /v2/assets/SVXY` (`marginable`, `maintenance_margin_requirement`) und `GET /v2/account` (`regt_buying_power`) einmal ansehen; Order-Nominal gegen `buying_power` prüfen. |
| 2.4 | Bremse 15 % → ×0,5 | ✔ | `faktor` | Höchststand = Alpaca-`equity` zur Entscheidung aus `state.json`; nur neue Legs halbiert (wie K3) | – | – |
| 2.5 | Höchststand-Quelle | ✘ | `st['hwm']` | Geht `state.json` verloren, startet `hwm` = heutige Equity → Bremse und **Not-Aus-Schwelle** (`startkapital`) setzen sich auf das aktuelle Niveau zurück. | **hoch** | `startkapital`/`hwm` zusätzlich aus Alpaca ableiten (`GET /v2/account/portfolio/history?period=all`) und im Lauf gegenprüfen; `startkapital` als Konstante. |
| 2.6 | Not-Aus 70 % | ✔ | Schritt 2 | `DELETE /v2/positions?cancel_orders=true` = Market sofort, nicht MOC – akzeptabel; `gestoppt` wird gespeichert | – | – |
| 2.7 | Ganze Stücke, Abrunden | ✔ | `int(nominal/px)` | Legs < 1 Stück entfallen stumm (MW-Land 4 % × 0,5 bei teurem ETF) | niedrig | loggen |
| 2.8 | Equity-Quelle | ✔ | `konto['equity']` (inkl. unrealisiert) | Wert zur Entscheidung statt Schluss – vernachlässigbar | – | – |

## 3 Netting und Orders

| # | Punkt | Urteil | Fundstelle | Fehlerszenario | Schwere | Vorschlag |
|---|---|---|---|---|---|---|
| 3.1 | Netto-Order je Symbol → Leg-Zuordnung | ✘ | Schritt 7: `leg['order_id'] = gesendet[sym][0]` für **jedes** neue Leg; Schritt 1: `stueck = filled_qty` | (a) IBS SPY (50) und BB SPY (50) am selben Tag ergeben eine Order über 100; beide Legs bekommen dieselbe `order_id`, am Folgetag stehen beide auf 100 Stück → State 200, Alpaca 100 → Ausstiege verkaufen doppelt → Short. (b) IBS-Ausstieg SPY −50 + TSMOM-Einstieg SPY +20 → Netto-Verkauf 30 → TSMOM-Leg bekommt die **Verkaufsorder** als Einstieg. (c) Bei Aufteilung (`teile`) nimmt das Leg nur die erste Hälfte. | **hoch** | Fill je Symbol auf Legs verteilen (SPEC Aufgabe 2 FIFO), nie `order_id` 1:1 ans Leg; Leg-Stückzahl nur aus eigener Planung + Fill-Delta. |
| 3.2 | Vorzeichenwechsel in zwei Orders | ✘ | Schritt 6 `teile` | Alpaca: „Fully close the long before opening a short“; die Stücke der ersten Order sind reserviert → die zweite MOC-Order wird mit 403 abgelehnt. Mit MOC ist ein Richtungswechsel im selben Symbol am selben Tag unmöglich. | **hoch** | Bei Vorzeichenwechsel heute nur glattstellen, Gegenposition am Folgetag eröffnen (als „nachzuholen“ im State). In Tests (SPEC 6) abbilden. |
| 3.3 | `cls`-Annahmeschluss vs. Fenster | ✘ (behoben 22:30) | Fensterkonstanten, Uhr-Prüfung vor Orders | Alpaca: „CLS orders submitted after 3:50pm … will be rejected“. GitHub-Cron verzögert sich regelmäßig 3–15 Min. | **hoch** | v1 wartet jetzt bis 15:45, bricht unter 10,5 Min hart ab; Cron 15:28 + Nachläufer 15:40. |
| 3.4 | Fenster-Untergrenze bei verpasstem Cron | ✘ (behoben 22:30) | dito | Start zu spät → „kein Fenster“ → Tag ohne Ausstiege | **hoch** | Nachläufer-Cron 15:40 ET (`letzter_lauf` verhindert Doppelhandel) |
| 3.5 | Abgelehnte Orders → Zustand | ✘ | Schritt 6 `except → log`, Schritt 7 bucht trotzdem | Order abgelehnt (Margin, reservierte Stücke, nicht leihbar): schließende Legs werden journaliert und entfernt (Alpaca hält die Position weiter → Position bleibt ewig liegen), neue Legs bekommen `order_id=None` → State hat ein Leg, Alpaca nichts → späterer „Ausstieg“ verkauft leer → Short. | **hoch** | Bei Order-Fehler: schließende Legs behalten (mit Vermerk), neue Legs nicht anlegen, Exit-Code 1. |
| 3.6 | Netto 0 (Wechsel innerhalb Symbol) | ✔ | `einstieg=px` ohne Order | – | – | – |
| 3.7 | Teilfüllung | ✘ | Schritt 1: nur `status=='filled'` | MOC teilgefüllt und dann `canceled` → `stueck=0`, Leg gestrichen, Stücke liegen bei Alpaca | mittel | `filled_qty` unabhängig vom Status übernehmen; 0 nur bei `filled_qty==0`. |
| 3.8 | Stop teilgefüllt/abgelaufen/storniert | ✘ | Stop-Prüfung nur `filled` | Stop `canceled` (Not-Aus, Hand, 90-Tage-Regel) → Leg hält `stop_order`, glaubt sich geschützt | niedrig | Status `canceled/expired` → Stop neu setzen oder loggen. |
| 3.9 | `client_order_id` | ✔ | eindeutig je Sekunde | – | – | – |
| 3.10 | Journal-Ausstiegspreis = Entscheidungskurs | ✔ bekannt | Schritt 7 Kommentar | SPEC 2 deckt ab | – | – |

## 4 Daten

| # | Punkt | Urteil | Fundstelle | Fehlerszenario | Schwere | Vorschlag |
|---|---|---|---|---|---|---|
| 4.1 | Bars-Pagination `page_token` | ✔ | `bars()` while-Schleife | 48 Symbole × ≈ 430 Tage ≈ 21 000 Bars > `limit=10000` → 3 Seiten, korrekt verkettet | – | – |
| 4.2 | IEX-Lücken/Qualität | ✘ | siehe 1.3 | – | **hoch** | siehe 1.3 |
| 4.3 | Tagesbar vor Schluss unvollständig | ✔ gelöst | `hi=max(h,px)`, `lo=min(l,px)`; Bars filtern `r[0] < heute` | – | – | – |
| 4.4 | Symbol fehlt im Snapshot | ✘ | `kennzahlen()`: `if s not in live: continue`; Schritt 4 `if k is None: continue` | Kein IEX-Trade bis zur Entscheidung (EWL, EWP möglich) → Leg wird stumm gehalten, kein Log, kein Ausstieg | mittel | fehlende Symbole mit offenen Legs laut loggen; Ausstieg zur Not mit `latestQuote`-Mitte. |
| 4.5 | Yahoo ^VIX/^VIX3M | ? | `yahoo_live()`, `except → ratio=None` | GitHub-Runner-IPs bekommen von Yahoo häufig 429 → VIX-Contango (+2,8 % p.a. in K3) wird nie eröffnet; bestehender SVXY-Long wird bei Backwardation nicht geschlossen. | mittel | Im ersten Actions-`dry`-Lauf log.txt auf „VIX nicht lesbar“ prüfen. Fallback: CBOE-CSV (`cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv`) oder `query2.finance.yahoo.com`; STATUS zeigt „VIX-Quelle: fehlt“. |
| 4.6 | Zeitzonen | ✔ | `heute` aus `/v2/clock` in NY, Log UTC | – | – | – |
| 4.7 | DST: EU 25.10., USA 01.11. | ✔ | Cron in UTC: 19:28 = 15:28 EDT, 20:28 = 15:28 EST | der jeweils falsche Lauf endet „kein Fenster“, erzeugt aber täglich einen Commit mit Logzeile | niedrig | – |
| 4.8 | Feiertage ohne `/v2/calendar` | ✘ | `FEIERTAGE`, `handelstage()` | 1.11/1.12 | **hoch** | `/v2/calendar` |
| 4.9 | `/v2/clock` Zeitstempel mit Nanosekunden | ✔ | `fromisoformat` kürzt in 3.11+ | – | – | – |

## 5 Zustand und Wiederanlauf

| # | Punkt | Urteil | Fundstelle | Fehlerszenario | Schwere | Vorschlag |
|---|---|---|---|---|---|---|
| 5.1 | Commit-Schritt scheitert ohne `journal.csv` | ✘ **bestätigt, behoben 22:30** | `bot.yml` | `git add` bricht bei einem fehlenden Pfad komplett ab (lokal getestet). Ablauf: Tag 1 kauft IBS SPY, `state.json` wird nicht committed → Tag 2 startet mit leerem State → SPY-Leg wird nie verkauft, täglich neue Orphans. | **hoch** | `git add -f` je vorhandener Datei; `journal.csv` mit Kopfzeile beim ersten Lauf anlegen; Commit-Schritt `if: always()`; `pull --rebase` vor Push (alles in bot.yml seit 22:30). |
| 5.2 | State-Speicherung nicht atomar | ✘ | Schritt 6 sendet Orders, `speichern()` erst nach Schritt 7 | Ausnahme in Schritt 7 oder Runner-Timeout → Orders sind draußen, State alt → am Folgetag werden geschlossene Legs erneut verkauft, neue Legs sind unbekannt | **hoch** | Nach jeder gesendeten Order State mit `pending`-Vermerk sofort schreiben (`os.replace` temp→state.json); Schritt 1 des Folgelaufs räumt `pending` auf. |
| 5.3 | `letzter_lauf`-Sperre | ✔ | nur nach Erfolg gesetzt | kein zweiter Versuch im Fenster außer dem Nachläufer; jeder Alpaca-Schluckauf (500/Timeout nach 3 Versuchen) = Tag verloren | mittel | `alp()` Retries auf 5 mit Backoff innerhalb des Fensters. |
| 5.4 | Kein Nachholen von Terminen | ✘ | `mw_verkauf = heute == tage[2]`, `tsmom_tag = heute == tage[-1]` | Ein verpasster Lauf am 3. Handelstag → MW-Legs (148 % Brutto!) bleiben bis zum 3. Handelstag des **nächsten** Monats; verpasster letzter Handelstag → TSMOM einen Monat veraltet. | **hoch** | „am oder nach dem 3. Handelstag, wenn Leg aus Vormonat“ bzw. „TSMOM, wenn letzte Umschichtung < aktueller Monatsletzter“ – Nachholen am nächsten Lauf, im Journal als „nachgeholt“. |
| 5.5 | Fill-Abgleich Alpaca-Positionen ≠ Legs | ✘ | fehlt vollständig | Jede Abweichung aus 3.1/3.2/3.5/5.2 bleibt unentdeckt, bis ein Ausstieg leer verkauft | **hoch** | Zu Beginn jedes Laufs Σ Legs je Symbol gegen `GET /v2/positions`; Abweichung → kein Handel, STATUS „ABGLEICH“, Exit 1. |
| 5.6 | Git-Push-Konflikt | ✘ (behoben 22:30) | `bot.yml` | Push abgelehnt → State nur im gelöschten Runner | mittel | `git pull --rebase` mit drei Versuchen (seit 22:30); zusätzlich `state.json` als Workflow-Artifact. |
| 5.7 | Dry-Lauf schreibt `journal.csv` | ✘ | Schritt 1 `journal()` bei gefülltem Stop auch mit `--dry` | Stop-Schließung wird im Dry-Lauf journaliert | niedrig | Dry: keine Dateischreibzugriffe außer STATUS. |
| 5.8 | Secrets | ✔ | nur in `hdr()`; Fehlertexte enthalten keine Header; GitHub maskiert | – | – | – |
| 5.9 | Tote Felder | niedrig | `offene_orders`, `tag_zaehler`, `HALBE_TAGE`, `VORRANG`, `handelstag_nr` | signalisiert unfertige Absicht | niedrig | in v2 benutzen oder streichen |

## 6 GitHub Actions

| # | Punkt | Urteil | Fundstelle | Fehlerszenario | Schwere | Vorschlag |
|---|---|---|---|---|---|---|
| 6.1 | Cron-Minute (nicht :00) | ✔ | `bot.yml` | Schedule-Events verzögern sich bei Last | – | – |
| 6.2 | Doppelter Trigger EDT/EST | ✔ | Fenster + `is_open` | beide Läufe committen | niedrig | – |
| 6.3 | Nachläufer | ✔ (seit 22:30) | `40 19`/`40 20` | – | – | – |
| 6.4 | Workflow-Zeitlimit | ✔ | 25 Min (Warten bis 15:45 eingerechnet) | bei Timeout mitten in Schritt 6 → 5.2 | – | – |
| 6.5 | Python 3.12, zoneinfo, nur Stdlib | ✔ | `setup-python@v5` | – | – | – |
| 6.6 | `permissions: contents: write`, Push mit `GITHUB_TOKEN` | ✔ | – | nur auf dem Default-Branch laufen Schedules; Branch-Protection würde den Push blocken | niedrig | README: Repo ohne Branch-Schutz, Workflow auf `main`. |
| 6.7 | Roter Lauf | ✘ teilweise | `main()` liefert bei Order-Fehlern Exit 0 | Order-Ablehnungen → Lauf grün, niemand merkt es. | mittel | Exit 1 bei jeder abgelehnten Order; STATUS „FEHLER“ fett oben; optional `gh issue create` als Alarm. |
| 6.8 | `workflow_dispatch` `dry` | ✔ | `inputs.modus` | Dry überschreibt `STATUS.md` des Live-Laufs | niedrig | `STATUS-dry.md` |
| 6.9 | Schedule-Abschaltung nach 60 Tagen Inaktivität | ✔ | tägliche Commits halten das Repo aktiv | – | – | – |

---

## 7 Top 10 nach Schweregrad (Stand vor den Korrekturen 22:30)

| Rang | # | Befund | Folge im Betrieb | Schwere |
|---|---|---|---|---|
| 1 | 5.1 | `git add` mit fehlendem `journal.csv` staged nichts → `state.json` nach Lauf 1 weg | Täglich neue Käufe, nie Verkäufe | hoch (behoben) |
| 2 | 3.1 | Netto-Order 1:1 ans erste Leg; `stueck` aus `filled_qty` | Doppelte Stückzahl im State am ersten IBS+BB-Tag → späterer Leerverkauf | hoch |
| 3 | 3.3 | Fenster vs. Alpaca-Annahmeschluss 15:50 ET, Cron-Verzug | Ganze Ordertage abgelehnt | hoch (behoben) |
| 4 | 3.5 | Abgelehnte Orders werden als ausgeführt gebucht | State ≠ Alpaca, Leerverkäufe/Orphans | hoch |
| 5 | 5.4 | Kein Nachholen von MW-Verkauf/TSMOM nach verpasstem Lauf | 148 % Brutto einen Monat zu lang gehalten | hoch |
| 6 | 1.11 | Halbtage 27.11./24.12. ohne Lauf | November-Monatswechsel fällt aus | hoch (Cron behoben, Kalender offen) |
| 7 | 1.12 | Karfreitag 2027 falsch, Tabelle endet 2027 | Termine ab März 2027 verschoben | hoch |
| 8 | 1.8/3.2 | GTC-Stop reserviert Stücke; Short erst nach Glattstellung | 403 bei MOC-Verkäufen, Vorzeichenwechsel unmöglich | hoch |
| 9 | 5.2/5.5 | State erst nach Orders gespeichert; kein Positionsabgleich | Jeder Abbruch erzeugt dauerhaft falschen State, unbemerkt | hoch |
| 10 | 1.3/4.2 | IEX-Feed für Hoch/Tief und Historie | IBS auf dünnen Länder-ETFs verzerrt | hoch |

Weitere hohe Befunde: 2.5 (Höchststand/Startkapital-Reset).

---

## 8 Textbausteine für die Claude-Code-Sitzung (zweite Nachricht)

### Review-Befunde v1 – bitte in Aufgabe 1/2/5/6 einarbeiten

**Was v2 laut SPEC schon abdeckt (nicht doppelt bauen, aber die Befunde als Testfälle nehmen):**
- Aufgabe 2 (exakte Abrechnung, FIFO-Verteilung der Netto-Fills auf Legs) löst Befund 3.1 – vorausgesetzt, `order_id` wird nicht mehr 1:1 an ein Leg gehängt und `stueck` nie aus `filled_qty` einer Sammelorder übernommen. Abnahmetest: IBS SPY + BB SPY am selben Tag, eine Order, zwei Legs mit je eigener Stückzahl.
- Aufgabe 5 (Alpaca nicht erreichbar → FEHLER, Exit 1) deckt den Verbindungsfall; sie deckt **nicht** abgelehnte Einzelorders (3.5).
- Aufgabe 6 (Tests Netting mit Vorzeichenwechsel, Kalender mit Feiertagen) – Vorzeichenwechsel muss als „heute nur glattstellen“ getestet werden (3.2); Kalendertest muss Halbtage und Karfreitag 2027 = 26.03. enthalten.
- Aufgabe 3/4 (Replay) – unverändert; keiner der Befunde ändert eine Regel.

**Was v2 zusätzlich einplanen muss (alle vor dem ersten Live-Lauf):**

Aufgabe 1 (Refactoring) zusätzlich:
- Kalender aus `GET /v2/calendar` (mit `close`-Zeit je Tag) statt `FEIERTAGE`/`HALBE_TAGE`; Tabelle nur als Fallback mit Verfallswarnung. Monatswechsel- und TSMOM-Termine daraus; Halbtage erkennen.
- Nachhol-Logik: MW-Verkauf „am oder nach dem 3. Handelstag für Legs aus dem Vormonat“, TSMOM „wenn letzte Umschichtung vor dem aktuellen Monatsletzten liegt“, MW-Kauf nicht nachholen (Signal verfallen). Im Journal als `nachgeholt` kennzeichnen.
- Vorzeichenwechsel je Symbol: heute nur glattstellen, Gegenposition als `nachzuholen` im State, Eröffnung im nächsten Lauf.
- Historie mit `feed=sip`, Snapshot-Hoch/Tief mit `feed=delayed_sip` prüfen, letzter Kurs IEX; Symbole ohne Snapshot bei offenem Leg laut loggen.
- Einstiege als Schleife über `VORRANG`; tote Felder streichen oder nutzen.

Aufgabe 2 (Abrechnung) zusätzlich:
- Positionsabgleich zu Beginn jedes Laufs: Σ Legs je Symbol gegen `GET /v2/positions`; Abweichung → kein Handel, STATUS „ABGLEICH NÖTIG“, Exit 1. Orphans auflisten.
- Abgelehnte Orders: schließende Legs bleiben (Vermerk `ausstieg_offen`), neue Legs werden nicht angelegt, Exit 1. Teilfüllungen: `filled_qty` übernehmen, egal welcher Status.
- Signalabweichung messen: IBS zum Orderzeitpunkt vs. IBS aus der Tagesbar des Folgelaufs; Anteil gekippter Signale je Strategie in STATUS (K6-Referenz: 15:45-Signal kippt in 26 % der Fälle weg).
- `startkapital`/`hwm` gegen `GET /v2/account/portfolio/history?period=all` prüfen.

Aufgabe 5 (Betrieb) zusätzlich:
- Lauffenster wie in v1 seit 22:30 (warten bis 15:45 ET, Orders bis 15:48, Abbruch unter 10,5 Min) beibehalten; `STATUS.md` zeigt Entscheidungszeit und Minuten bis Schluss beim Senden.
- State nach jeder gesendeten Order sofort atomar schreiben (`tempfile` + `os.replace`), Legs mit `pending` bis der Fill bekannt ist.
- `bot.yml`: `state.json` zusätzlich als Workflow-Artifact. Dry-Lauf schreibt nur `STATUS-dry.md`, nie `journal.csv`.
- BB-Stop: vor jedem MOC-Verkauf im selben Symbol alle offenen Orders stornieren und auf `canceled` warten; Stop nach dem Lauf neu setzen, wenn das Leg bleibt. `canceled/expired`-Stops erkennen.
- VIX-Quelle: Fallback (CBOE-CSV oder `query2`), STATUS zeigt die Quelle; Alarm, wenn drei Läufe in Folge ohne VIX.
- Exit 1 bei jeder abgelehnten Order; Alarmweg (GitHub-Issue per `gh issue create` oder Mail) im ABSCHLUSS.md beschreiben.
- Abschaltkriterium (K5): rollierende 12-Monats-Rendite ≤ −24 %, Drawdown ≥ 34 % vom Höchststand seit Start, 250-Tage-Sharpe ≤ −1,30 → `gestoppt`, alles glatt, Exit 1 (siehe SPEC-v2).

Aufgabe 6 (Tests) zusätzlich:
- Kalender: 27.11.2026 ist Halbtag und MW-Kauftag; 26.03.2027 Karfreitag; 24.12.2027 Feiertag; Monat mit Feiertag am Monatsende.
- Netting: zwei neue Legs in einem Symbol → eine Order, zwei Stückzahlen; Ausstieg + Einstieg im selben Symbol → Netto-Verkauf, Einstiegsleg behält geplante Stückzahl; Vorzeichenwechsel → nur Glattstellung.
- Ablehnung: Order-Fehler → State unverändert, Exit 1. Teilfüllung → `filled_qty`.
- Wiederanlauf: Abbruch nach Order 2 von 5 → `pending`-Legs, Folgelauf räumt auf ohne Doppelorder.
- Abgleich: Alpaca-Position ohne Leg → kein Handel.
- Lauffenster: Start 15:28 → wartet; Start 15:49 → kein Handel; Uhr vor Orders < 10,5 Min → Exit 1 ohne Buchung.

**Fünf-Minuten-Prüfungen auf dem Paper-Konto (vor Aufgabe 5, Ergebnis ins ABSCHLUSS.md):**
1. `GET /v2/stocks/snapshots?symbols=EWL,SPY&feed=delayed_sip` → 200? (sonst `sip` nur für Historie, Snapshot bleibt IEX).
2. 1 Stück IWM `sell`, `type=market`, `time_in_force=cls` um 15:40 ET ohne Position → wird die Short-MOC angenommen (Status `accepted`)? Danach stornieren.
3. `GET /v2/assets/SVXY` → `marginable`, `maintenance_margin_requirement`; `GET /v2/account` → `regt_buying_power` bei 100 000 $.
4. Buy 1 SPY `day`, dann sofort sell 2 SPY `cls` → Antwort 403 „insufficient qty“ bestätigt 3.2.
5. Erster Actions-`dry`-Lauf: `log.txt` auf „VIX nicht lesbar“ prüfen (Yahoo von GitHub-IPs).
