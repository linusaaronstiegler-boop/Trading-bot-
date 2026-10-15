# Abschluss Systembuch-Bot v2 – Claude-Code-Sitzung 15.10.2026

Branch `claude/systembuch-v2` im Repo `linusaaronstiegler-boop/Trading-bot-` (= `systembuch-bot`). Ein Commit je Aufgabe. `pytest`: ENTWURF Tests grün.

## Kurz

- v2 ist gebaut: SPEC-v2 Aufgaben 1–7, alle Review-Befunde eingearbeitet. Regeln unverändert, kein LLM, Live-Pfad nur Standardbibliothek.
- Der Replay trifft K3 genau (+12,0 % p.a., Sharpe 0,75, Maximalverlust 24,1 %), wenn er wie K3 rechnet. So, wie der Bot bei Alpaca handeln kann, sind es **+10,2 % p.a., Sharpe 0,68, Maximalverlust 26,7 %**. Ursache ist die Vorzeichenwechsel-Sperre, kein Fehler (`replay/BEOBACHTUNGEN.md`).
- In dieser Umgebung waren **keine Alpaca-Schlüssel gesetzt**. Deshalb sind offen: der Live-Trockenlauf, die fünf Paper-Prüfungen und der grüne Actions-`dry`-Lauf. Yahoo war erreichbar, Alpaca antwortete mit 401.

ENTWURF – wird am Ende vervollständigt.
