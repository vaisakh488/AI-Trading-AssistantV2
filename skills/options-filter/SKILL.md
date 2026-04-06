---
name: options-filter
description: Use when filtering NSE options chain for intraday CE/PE selection.
Triggers on: "which option to buy", "best strike", "CE or PE", "options chain".
---
# Options Filter

## Strike selection rules
- Trade ATM or 1 strike OTM only — deeper OTM decays too fast intraday
- Prefer strikes with OI > 5 lakh (liquid, tight spread)
- Volume > 1000 contracts by 10 AM = active strike
- Avoid strikes where ask-bid spread > 5% of LTP

## CE vs PE decision
- BULLISH trend (price above VWAP + EMA9 > EMA21) → buy CE
- BEARISH trend (price below VWAP + EMA9 < EMA21) → buy PE
- Sideways/unclear → NO TRADE, wait for confirmation

## Budget fit (Rs. 2000–5000 per lot)
- NIFTY lot = 50 units. LTP must be ≤ budget/50
- BANKNIFTY lot = 15 units. LTP must be ≤ budget/15
- Never trade if premium > budget — do not suggest partial lots