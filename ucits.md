# Echtgeld-Vorbereitung: UCITS-Gegenstücke und Kosten (SPEC Aufgabe 7)

*Stand 15.10.2026. Nur Datei, kein Handel, keine Anlageempfehlung. Recherche mit Gegenprüfung. Quellen: justETF, Emittenten-Factsheets, Deutsche-Börse-ETF-Statistik 09/2026 (Xetra-Liquiditätsmaß XLM), Tradegate-Orderbuch, Preis- und Leistungsverzeichnisse der Broker. Volle Quellenliste je Zeile in der Recherche-Ausgabe der Sitzung.*

## Ergebnis vorab

**Test C40 (README, 15.10.2026) hat die UCITS-Kopie von IBS verworfen.** Auf Xetra-Kerzen bringt IBS auch ohne Ordergebühr netto nichts: +1,8 % p.a. in der Lernzeit, t 0,7, seit 2018 negativ. Die Xetra-Kerze endet um 17:30 MEZ und sieht die US-Schlussauktion nicht, in der die Rückkehr entsteht. **Es gibt deshalb keinen Kontostand, ab dem diese Kopie Geld verdient.** Abschnitt 3 enthält die Rechnung, die die SPEC unter der Annahme „wie US-ETF, minus Kosten“ verlangt hat. Sie ist durch C40 überholt und als Obergrenze gekennzeichnet. Abschnitt 4 hält eine Beobachtung zum Handelsplatz fest. Dort ist nichts entschieden.

Die übrigen Regeln lassen sich schon vom Instrument her nicht sauber kopieren:
- **VIX-Contango:** In der EU gibt es kein Short-VIX-ETF oder -ETP. Das einzige ETN (SG, XS2425315400) wurde zum 28.04.2025 gekündigt. Übrig sind Faktor-Zertifikate, −1× statt −0,5×, Risikoklasse 7/7.
- **TSMOM-Shorts:** Privatkunden können ETFs nicht leerverkaufen. Short ginge nur über inverse ETPs, die es für die meisten Märkte des Universums nicht gibt.

## 1. Gegenstücke je US-ETF

Spread = Xetra-Liquiditätsmaß (XLM), also die Roundtrip-Kosten bei 100.000 € Ordergröße in Basispunkten. Für kleine Orders zur Xetra-Zeit entspricht das ungefähr der vollen Geld-Brief-Spanne. **Außerhalb der Xetra-Zeit (17:30–22:00/23:00) sind die Spannen 3- bis 10-mal so breit.** Tradegate am 15.10.2026 um 22:00: SXR8 0,07 %, ZPRR 0,11 %, Sektor-ETFs 0,24–1,64 %, Rohstoff-ETCs 0,4–2,7 %.

Handelsplätze, wenn nicht anders vermerkt, für alle gelisteten Produkte: **Xetra 9:00–17:30** (über den Xetra-Retail-Service teilnehmender Broker 8:00–22:00, seit 01.12.2025), **gettex 7:30–23:00**, **Tradegate 7:30–22:00**. Alle Produkte notieren in EUR ohne Währungssicherung. Gegenüber dem US-Original kommt also die EUR/USD-Bewegung dazu.

### Index (IBS, BB, Monatswechsel)

| US-ETF | UCITS-Gegenstück | ISIN | Xetra | TER | XLM bp | Abweichung |
|---|---|---|---|---|---|---|
| SPY | iShares Core S&P 500 UCITS ETF (Acc) | IE00B5BMR087 | SXR8 | 0,07 % | 1,6 | gleicher Index, thesaurierend, ≈ 746 € je Anteil |
| QQQ | iShares Nasdaq 100 UCITS ETF (Acc) | IE00B53SZB19 | SXRV | 0,30 % | 2,4 | gleicher Index, ≈ 1.534 € je Anteil (grob gestückelt) |
| DIA | iShares Dow Jones Industrial Average UCITS ETF (Acc) | IE00B53L4350 | SXRU | 0,33 % | 5,0 | gleicher Index |
| IWM | SPDR Russell 2000 U.S. Small Cap UCITS ETF (Acc) | IE00BJ38QD84 | ZPRR | 0,30 % | 7,1 | gleicher Index, optimiertes Sampling |
| SVXY | – kein Gegenstück – | (SG Faktor 1× Short VIXF: DE000CU0AF69) | – | 0,75 % + 2,0 % IKS | – | −1× statt −0,5×, Zertifikat, SRI 7, nicht aktiv quotiert gefunden |

### Sektoren (IBS-Sektor)

| US-ETF | UCITS-Gegenstück | ISIN | Xetra | TER | XLM bp |
|---|---|---|---|---|---|
| XLB | iShares S&P 500 Materials Sector (Acc) | IE00B4MKCJ84 | 2B7B | 0,15 % | 24,2 |
| XLE | SPDR S&P U.S. Energy Select Sector (Acc) | IE00BWBXM492 | ZPDE | 0,15 % | 14,4 |
| XLF | iShares S&P 500 Financials Sector (Acc) | IE00B4JNQZ49 | QDVH | 0,15 % | 10,3 |
| XLI | SPDR S&P U.S. Industrials Select Sector (Acc) | IE00BWBXM724 | ZPDI | 0,15 % | 12,3 |
| XLK | iShares S&P 500 Information Technology Sector (Acc) | IE00B3WJKG14 | QDVE | 0,15 % | 5,1 |
| XLP | iShares S&P 500 Consumer Staples Sector (Acc) | IE00B40B8R38 | 2B7D | 0,15 % | 14,7 |
| XLU | iShares S&P 500 Utilities Sector (Acc) | IE00B4KBBD01 | 2B7A | 0,15 % | 12,6 |
| XLV | iShares S&P 500 Health Care Sector (Acc) | IE00B43HR379 | QDVG | 0,15 % | 14,8 |
| XLY | iShares S&P 500 Consumer Discretionary Sector (Acc) | IE00B4MCHD36 | QDVK | 0,15 % | 12,5 |

Gemeinsame Abweichung: UCITS-Kappung 35/20 statt der US-Regel 23/45 %. Das zählt vor allem bei XLK (Apple/Microsoft/Nvidia) und XLE (Exxon/Chevron).

### Länder (IBS-Land, Monatswechsel-Land, TSMOM)

| US-ETF | UCITS-Gegenstück | ISIN | Xetra | TER | XLM bp | Abweichung |
|---|---|---|---|---|---|---|
| EWG | Xtrackers DAX 1C | LU0274211480 | DBXD | 0,09 % | 3,6 | DAX statt MSCI Germany (kein MSCI-Germany-UCITS mehr) |
| EWJ | Xtrackers MSCI Japan 1C | LU0274209740 | DBXJ | 0,12 % | 11,9 | gleicher Index, Tokio während Xetra geschlossen |
| EWU | iShares Core FTSE 100 (Dist) | IE0005042456 | IUSZ | 0,07 % | 5,6 | FTSE 100 statt MSCI UK |
| EWA | iShares MSCI Australia (Acc) | IE00B5377D42 | IBC6 | 0,50 % | 8,1 | gleicher Index |
| EWH | UBS MSCI Hong Kong (dis) | LU1169827224 | – (gettex/Tradegate 3CE0) | 0,45 % | – (Annahme 50–150) | ungekappt statt 25/50, kleiner Fonds, Sicherheit „wahrscheinlich“ |
| EWC | iShares MSCI Canada (Acc) | IE00B52SF786 | SXR2 | 0,48 % | 9,7 | gleicher Index |
| EWY | iShares MSCI Korea (Dist) | IE00B0M63391 | IQQK | 0,65 % | 16,6 | Kappung 20/35 statt 25/50 |
| EWT | iShares MSCI Taiwan (Dist) | IE00B0M63623 | IQQT | 0,74 % | 15,3 | Kappung 20/35 (TSMC) |
| EWZ | Xtrackers MSCI Brazil 1C | LU0292109344 | XMBR | 0,25 % | 37,6 | gleicher Index; nach 16:00 nur ≈ 22 bp |
| EWL | Amundi MSCI Switzerland (C) | LU1681044720 | 540J | 0,25 % | 8,5 | ungekappt, Swap |
| EWQ | iShares MSCI France (Acc) | IE00BP3QZJ36 | IS3U | 0,25 % | 11,4 | gleicher Index |
| EWP | Xtrackers Spanish Equity 1C | LU0592216393 | XESP | 0,30 % | 8,7 | Solactive Spain 40 statt MSCI Spain |
| EFA | Xtrackers MSCI World ex USA 1C | IE0006WW1TQ4 | EXUS | 0,15 % | 4,5 | enthält Kanada (≈ 12 %), kein EAFE-UCITS |
| EEM | Xtrackers MSCI Emerging Markets 1C | IE00BTJRMP35 | XMME | 0,18 % | 6,7 | gleicher Index, Sampling |

### TSMOM-Universum ohne Aktien

| US-ETF | Gegenstück | ISIN | Xetra | Kosten p.a. | XLM bp | Abweichung |
|---|---|---|---|---|---|---|
| TLT | iShares $ Treasury Bond 20+yr (Dist) | IE00BSKRJZ44 | IS04 | 0,07 % | 9,2 | gleicher Index |
| IEF | iShares $ Treasury Bond 7-10yr (Dist) | IE00B1FZS798 | IUSM | 0,07 % | 5,3 | gleicher Index |
| LQD | iShares $ Corp Bond (Dist) | IE0032895942 | IBCD | 0,20 % | 23,2 | gleicher Index |
| HYG | iShares $ High Yield Corp Bond (Dist) | IE00B4PY7Y77 | IS0R | 0,50 % | 18,5 | gekappte Indexvariante |
| GLD | iShares Physical Gold ETC | IE00B4ND3602 | PPFB | 0,12 % | 3,3 | ETC, physisch |
| SLV | Invesco Physical Silver ETC | IE00B43VDT70 | 8PSB | 0,19 % | 10,0 | ETC, physisch |
| USO | WisdomTree WTI Crude Oil (ETC) | GB00B15KXV33 | OD7F | 0,49 % + 0,45 % Swap | 9,7 | Multi-Tenor-Index, andere Rollrendite |
| DBC | iShares Diversified Commodity Swap UCITS | IE00BDFL4P12 | SXRS | 0,19 % | 12,4 | BCOM statt DBIQ (weniger Energie) |
| DBA | WisdomTree Agriculture (ETC) | GB00B15KYH63 | OD7U | 0,49 % + 0,45 % Swap | 24,3 | ohne Vieh |
| UNG | WisdomTree Natural Gas (ETC) | JE00BN7KB334 | OD7L | 0,49 % + 0,45 % Swap | 23,6 | anderer Rollkalender |
| UUP | Xtrackers II USD Overnight Rate Swap 1C (Proxy) | LU0321465469 | XFFE | 0,10 % | 5,2 | nur EUR-Anteil des Dollar-Index (≈ 58 %) |
| FXE | WisdomTree Short USD Long EUR (ETP) | JE00B3SBYQ91 | XBJQ | 0,39 % | 31,8 (Jul./Aug. 73–76) | kaum Umsatz (0,2 Mio. €/Monat) |
| VNQ | iShares US Property Yield (Dist) | IE00B1FZSF77 | IQQ7 | 0,40 % | 16,7 | Dividenden-Filter-Index |

## 2. Brokerkosten (Einzelorder ETF, Stand 15.10.2026)

| Broker | Order | Günstige Plätze | Zeiten | Für einen Bot wichtig |
|---|---|---|---|---|
| **Traders Place** (Baader Bank) | **0 € ab 500 €** auf gettex und Baader Trading, sonst 0,95 €. Xetra 2 € + 0,01 % (mind. 3 €) + Börsenentgelte, Tradegate 5 € | gettex, Baader Trading | gettex 7:30–23:00, Baader Mo–Fr 7:30–23:00, Sa 14–19 | Teilausführungen kosten je Abrechnung. 0-€-Modell über Baader-Bonifikation, BaFin sieht das laut Presse kritisch. Kein API belegt |
| Trade Republic | 1 € Bestpreis, 2 € Direktpreis (Platz frei wählbar) | eigenes Orderbuch (TR als Gegenpartei seit 02.07.2026) | 7:30–23:00 | Bruchstücke ab 1 €, Limit kostenlos, kein API belegt |
| Scalable FREE | EIX 0,99 € (Kauf PRIME-Partner-ETF ab 250 € = 0 €), Xetra/gettex 1,99 € | EIX (Scalable = Market Maker) | EIX 6:00–23:00 | „Agentic Investing“ (MCP/CLI) seit 25.08.2026, aber Freigabe und KID-Bestätigung je Order, 2FA |
| Scalable PRIME+ | 4,99 €/Monat; EIX 0 € ab 250 € (Kauf und Verkauf), sonst 0,99 € | EIX | EIX 6:00–23:00 | wie FREE |
| justTRADE | 1 € auf LS Exchange/Tradegate (2,90 € − 1,90 € Ausgleich), sonst 2,90 € | LS, Tradegate | 7:30–23:00 / 22:00 | keine Market-Kauforder, nur Quote Request/Limit, 1.368 ETFs |

Payment for Order Flow ist in der EU seit 01.07.2026 verboten. Die 0-€-Modelle (Traders Place, Scalable EIX) verdienen über den Spread des eigenen Market Makers. **Der Spread ist bei diesen Brokern also die eigentliche Ordergebühr.**

## 3. Rechnung: ab welchem Konto bleibt IBS netto positiv? *(Annahme „wie US-ETF, minus Kosten“ – durch C40 überholt)*

Annahme laut SPEC: IBS bringt brutto ≈ +30 bp je Trade. Zum Vergleich der Replay v2: +16 bp je Haltephase nach 6 bp Kosten, also ≈ 22 bp brutto. Nettoergebnis je Trade in bp = Brutto − Spread (Roundtrip) − 2 × Ordergebühr / Positionsgröße × 10⁴. IBS-Größe laut README: 25 % des Kontos je Index-ETF, 11 % Sektor, 7 % Land.

Break-even-Position P* = 2 × Gebühr / (Brutto − Spread):

| IBS-Index auf SXR8, Spread 3 bp | Gebühr je Order | P* (Brutto 30 bp) | Konto (25 %) | P* (Brutto 22 bp) | Konto |
|---|---|---|---|---|---|
| Traders Place gettex | 0 € ab 500 € | 500 € (Gebührengrenze) | **2.000 €** | 500 € | 2.000 € |
| Scalable PRIME+ EIX | 0 € ab 250 € + 4,99 €/Monat | 250 € (Gebührengrenze) | **1.000 €*** | 250 € | 1.000 €* |
| Scalable FREE EIX | Kauf 0 €, Verkauf 0,99 € | 367 € | 1.470 € | 521 € | 2.080 € |
| Trade Republic | 1 € | 741 € | 2.960 € | 1.053 € | 4.210 € |
| justTRADE Tradegate | 1 € | 741 € | 2.960 € | 1.053 € | 4.210 € |

\* Das Abo kostet 59,88 €/Jahr. Dem stehen ≈ 134 IBS-Index-Trades/Jahr × 25 % des Kontos × (Brutto − Spread) gegenüber. Gedeckt ist es ab ≈ 660 € (30 bp) bzw. ≈ 940 € (22 bp) Konto, darunter greift ohnehin die 250-€-Grenze. Für das Konto zählen nur die IBS-Trades, nicht der übrige Bot.

Für **IBS-Land** (7 % je ETF) reicht das nicht. Die Spreads liegen über oder nahe am Ertrag: XMBR 38 bp, IQQK 17 bp, IQQT 15 bp, DBXJ 12 bp. Bei 30 bp brutto bleiben je nach Land 0 bis 22 bp übrig, bei 22 bp brutto für Brasilien nichts. **IBS-Sektor** (11 %) hat Spreads von 5–24 bp und auf Trade-Ebene ohnehin nur ≈ +6 bp (Replay), ist also auch ohne Gebühr nicht positiv.

**Bei 1.000 € Konto** ist eine IBS-Index-Position 250 € groß. Mit 1 € je Order kostet ein Trade 80 bp plus Spread, das sind −50 bis −60 bp je Trade. Bei ≈ 134 Trades/Jahr allein im Index sind das ≈ −17 bis −20 % p.a. Das deckt sich größenordnungsmäßig mit C40 (−45 % p.a. für die ganze IBS-Familie mit 1 € je Order).

**C40 ersetzt diese Annahme:** Auf UCITS-Xetra-Kerzen ist der Bruttoertrag nicht +30 bp, sondern nahe null bis negativ. Damit gibt es keinen Kontostand, ab dem es aufgeht.

## 4. Beobachtung (nicht entschieden, Test nötig)

C40 begründet das Scheitern mit der Kerze, nicht mit dem Produkt: Xetra schließt um 17:30 MEZ, also vor der US-Schlussauktion. Die Ersatzprodukte werden aber auch **während der US-Schlussphase** gehandelt: gettex bis 23:00, Tradegate bis 22:00, Scalable EIX bis 23:00, Trade Republic bis 23:00. Die Market Maker stellen ihre Kurse dann nach den laufenden US-Kursen. Ein Signal aus SPY um 15:45 ET, ausgeführt in SXR8 auf gettex um 21:45 MEZ (bis 26.10. und ab 02.11.; dazwischen 20:45 MEZ wegen der Zeitumstellung), hält dieselbe Zeitspanne wie der Bot. Dazu kommen EUR/USD-Rauschen und Abendspreads (SXR8/SXRV 5–7 bp, ZPRR ≈ 11 bp; Sektor- und Länder-ETFs 25–160 bp, also unbrauchbar).

Das wäre ein eigener Test „C41: IBS-Index auf SXR8/SXRV/ZPRR, Ausführung gettex 21:45 MEZ“ mit vorab festgeschriebenen Kriterien (Lernzeit, Tresor, t ≥ 2). Er braucht historische gettex- oder Tradegate-Quotes um 21:45, die es nicht frei gibt. Ersatz wäre die SPY-Rendite 15:45→15:45 ET, umgerechnet in EUR, minus gemessener Abendspread. Laut README kommt das frühestens nach dem Echtgeld-Kriterium in `wissen/08-Echtgeld-Regeln.md`.
