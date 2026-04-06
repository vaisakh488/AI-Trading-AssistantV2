---
name: candle-analyzer
description: Use for reading 1-minute candle patterns on NSE options/index charts.
Triggers on: "candle", "pattern", "engulfing", "doji", "pinbar", "reversal".
---
# Candle Analyzer — 1-Minute NSE

## Bullish patterns (look for CE entry)
- Bullish engulfing: current green body fully covers previous red body → strong buy
- Bullish pinbar: long lower wick (2x body), small upper wick → reversal from support
- Three consecutive green candles above VWAP → strong momentum, enter on 4th open

## Bearish patterns (look for PE entry or CE exit)
- Bearish engulfing: current red body fully covers previous green body → strong sell signal
- Bearish pinbar: long upper wick (2x body) → rejection from resistance
- Three consecutive red candles below VWAP → strong downtrend

## Neutral/caution patterns
- Doji (body < 10% of range): indecision. Wait for next candle confirmation.
- Long wicks on both sides: high volatility, spreads will be wide. Avoid entry.

## Context rules
- Never trade a pattern in isolation — confirm with VWAP and EMA direction
- A bullish engulfing below EMA21 is weak — wait for EMA confirmation
- Volume on the signal candle should be above the 5-candle average