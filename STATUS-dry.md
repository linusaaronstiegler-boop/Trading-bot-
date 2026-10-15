# Systembuch-Bot – Stand 2026-10-15 (DRY RUN – nichts gesendet, nichts gebucht)

## Konto

Equity **100,000 $** · Start 100,000 $ (2026-10-15) · Höchststand 100,000 $ · Drawdown 0,0 %
Entscheidung 17:34:14 ET (1345.7 Min vor Schluss)
VIX3M/VIX 1.123 (Quelle: Yahoo query1) · Kalender: Alpaca /v2/calendar
Netto-MOC-Orders heute: {'XLP': 126, 'EWZ': 168, 'SVXY': 154}

## Abschaltkriterium K5

Tage seit Start: 0

| Kennzahl | Wert | Schwelle | Status |
|---|---|---|---|
| 12-Monats-Rendite | ab Tag 252 | ≤ −24 % | ok |
| Drawdown vom Höchststand | ab Tag 1 | ≥ 34 % | ok |
| 250-Tage-Sharpe | ab Tag 250 | ≤ −1,30 | ok |

## Offene Legs

| Leg | Strategie | Symbol | Richtung | Stück | Einstieg | Kurs | unreal. $ | unreal. bp | seit | Stop | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| neu | IBS_SEKTOR | XLP | long | 126 | MOC heute | – | – | – | 2026-10-15 | | geplant |
| neu | IBS_LAND | EWZ | long | 168 | MOC heute | – | – | – | 2026-10-15 | | geplant |
| neu | VIX | SVXY | long | 154 | MOC heute | – | – | – | 2026-10-15 | | geplant |

Unrealisiert gesamt: 0 $

## Stand je Strategie seit Start (journal.csv)

| Strategie | Trades | Treffer | Ø R (bp je Trade) | t | Summe $ | Ø MOC-Abweichung bp |
|---|---|---|---|---|---|---|
| IBS | 0 | – | – | – | 0 | – |
| MW | 0 | – | – | – | 0 | – |
| BB | 0 | – | – | – | 0 | – |
| IBS_SEKTOR | 0 | – | – | – | 0 | – |
| IBS_LAND | 0 | – | – | – | 0 | – |
| TSMOM | 0 | – | – | – | 0 | – |
| MW_LAND | 0 | – | – | – | 0 | – |
| VIX | 0 | – | – | – | 0 | – |

R = Rendite je Trade nach Fill (Gebühren 0). MOC-Abweichung = Kosten der Fills gegenüber dem offiziellen Schluss (Kostenabschlag gegenüber dem Replay).

## Vorteil auf Trade-Ebene (IBS-Familie)

| Gruppe | Trades | Ø bp je Haltetag | t | Referenz K3 | Referenz K6 (15:45) | Signal gekippt | Signal verpasst |
|---|---|---|---|---|---|---|---|
| IBS | 0 | – | – | +16 bp | +12,7 bp | – | 0 |
| IBS_SEKTOR | 0 | – | – | – | – | – | 0 |
| IBS_LAND | 0 | – | – | +13 bp | +6,9 bp | – | 0 |

Gekippt = Signal um 15:45, aber nicht mehr in der fertigen Tageskerze (K6-Referenz: 26 %). Verpasst = erst nach 15:45 entstanden.

## Nächste Termine

- 2026-10-29 Thu: Monatswechsel-Kauf (vorletzter Handelstag)
- 2026-10-30 Fri: TSMOM-Umschichtung (letzter Handelstag)
- 2026-11-04 Wed: Monatswechsel-Verkauf (3. Handelstag)

## Signale heute

| ETF | Kurs | IBS | SMA200 | BB unten | Signal |
|---|---|---|---|---|---|
| SPY | 771.22 | 0.80 | 721.46 | 759.78 |  |
| QQQ | 726.20 | 0.77 | 673.19 | 722.98 |  |
| DIA | 520.96 | 0.84 | 501.3 | 507.59 |  |
| IWM | 274.94 | 0.94 | 276.42 | 272.59 |  |
| XLB | 50.73 | 1.00 | 50.45 | 48.42 |  |
| XLE | 66.56 | 0.23 | 56.87 | 59.85 |  |
| XLF | 55.28 | 0.88 | 53.33 | 53.04 |  |
| XLI | 167.55 | 0.88 | 172.12 | 166.73 |  |
| XLK | 188.46 | 0.78 | 166.98 | 188.71 | BB  |
| XLP | 86.84 | 0.13 | 82.99 | 79.12 | IBS  |
| XLU | 41.69 | 0.35 | 43.77 | 38.69 |  |
| XLV | 177.44 | 0.46 | 156.3 | 164.36 |  |
| XLY | 113.40 | 0.91 | 115.5 | 108.25 |  |
| EWG | 41.54 | 1.00 | 41.86 | 40.33 |  |
| EWJ | 95.60 | 1.00 | 90.88 | 95.31 |  |
| EWU | 47.76 | 0.71 | 46.44 | 45.66 |  |
| EWA | 28.81 | 1.00 | 28.51 | 27.96 |  |
| EWH | 22.08 | 0.81 | 22.55 | 21.40 |  |
| EWC | 60.33 | 0.99 | 57.81 | 57.73 |  |
| EWY | 155.44 | 0.85 | 159.91 | 159.99 |  |
| EWT | 108.90 | 0.86 | 91.09 | 109.61 | BB  |
| EWZ | 41.61 | 0.15 | 36.69 | 34.01 | IBS  |
| EWL | 62.00 | 1.00 | 61.02 | 58.39 |  |
| EWQ | 42.26 | 0.96 | 44.62 | 40.37 |  |
| EWP | 58.36 | 0.98 | 57.3 | 56.54 |  |
| EFA | 103.74 | 1.00 | 102.04 | 101.96 |  |
| EEM | 63.85 | 0.88 | 63.38 | 64.36 | BB  |

Ausstiege heute: keine

## Letzte Logzeilen

```
2026-10-15T21:34:15Z Lauf 2026-10-15 17:34:14 ET – Equity 100,000 $, Höchststand 100,000, Drawdown 0.0%, Größenfaktor 1.0
2026-10-15T21:34:15Z Signale: MW-Kauf False, MW-Verkauf False, TSMOM False, VIX3M/VIX 1.123 (Yahoo query1)
2026-10-15T21:34:15Z Ausstiege: []
2026-10-15T21:34:15Z Einstiege: [('IBS_SEKTOR', 'XLP', 126), ('IBS_LAND', 'EWZ', 168), ('VIX', 'SVXY', 154)]
2026-10-15T21:34:15Z Netto-MOC-Orders: {'XLP': 126, 'EWZ': 168, 'SVXY': 154}
```

*Regeln und Belege: README.md. Journal: journal.csv. Kurve: equity.csv. Log: log.txt.*
