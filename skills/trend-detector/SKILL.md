---
name: trend-detector
description: Use for detecting intraday trend direction on Nifty/BankNifty.
Triggers on: "trend", "direction", "bullish", "bearish", "market mood today".
---
# Trend Detector — 1-Minute Timeframe

## Primary signals (in order of importance)
1. VWAP position: price above VWAP = bullish bias. Below = bearish.
2. EMA9 vs EMA21: EMA9 > EMA21 = bullish. Crossover = trend change.
3. Last 3 candles: 2+ bullish bodies = momentum up. 2+ bearish = down.
4. RSI: 55-70 bullish zone. 30-45 bearish zone. 45-55 = sideways.
5. MACD: line above signal = bullish. Below = bearish.

## Confidence levels
- 4-5 signals agree → HIGH confidence. Trade with full lot.
- 2-3 signals agree → MEDIUM confidence. Trade with caution.
- < 2 signals agree → LOW / SIDEWAYS. Skip trade entirely.

## Time-of-day rules
- 9:15–9:30: volatile opening. Observe only, do not trade.
- 9:30–11:30: best window for trend trades.
- 11:30–1:00: lunch range, often sideways. Reduce size.
- 1:00–2:30: trend often resumes. Valid window.
- After 2:30: do not enter new trades. Exit only.