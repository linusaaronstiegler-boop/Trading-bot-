
## Paper-Prüfungen 2026-10-15 17:34 ET

- **1. Snapshot feed=delayed_sip:** HTTP 200 – Hoch/Tief aus SIP nutzbar
- **3. SVXY-Marge und Buying Power:** SVXY marginable=True, maintenance_margin_requirement=30, shortable=False; Konto equity=100000, regt_buying_power=200000, buying_power=400000, multiplier=4
- **A. assets.json eingefroren:** nicht leihbar: ['EWG', 'USO', 'FXE'] (K3-Annahme: EWG, USO, FXE)

## Paper-Prüfungen 2026-10-16 15:33 ET

- **2. Short-MOC 1 IWM ohne Position:** Status new → angenommen
- **4. Long 1 SPY, dann Verkauf 2 SPY MOC:** Kauf filled; Verkauf 2: abgelehnt: Alpaca 403 /v2/orders: {"available":"1","code":40310000,"existing_qty":"1","held_for_orders":"0","message":"insufficient qty available for order (requested: 2, available: 1)","symbol":"SPY"}
- **4b. Aufräumen SPY:** verkauft
- **6. Short 1 IWM, dann Kauf 1 + Kauf 1 MOC (short → long):** Short filled; Eindecken: angenommen; zweiter Kauf: abgelehnt: Alpaca 403 /v2/orders: {"available":"0","code":40310000,"existing_qty":"1","held_for_orders":"1","message":"insufficient qty available for order (requested: 1, available: 0)","symbol":"IWM"}
- **6b. Aufräumen IWM:** eingedeckt
