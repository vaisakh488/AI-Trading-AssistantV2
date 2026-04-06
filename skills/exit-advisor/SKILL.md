---
name: exit-advisor
description: Use when monitoring an active trade for exit signals. 
Triggers on: "should I exit", "hold or sell", "when to sell", "trail stop loss", "target hit".
---
# Exit Advisor — Intraday Options

## Hard exit rules (non-negotiable)
- Stop loss hit (default -20% on premium) → EXIT IMMEDIATELY, no waiting
- Target hit (default +30% on premium) → EXIT, do not be greedy
- Time: 2:45 PM IST → EXIT whatever the P&L, do not hold options overnight

## Soft exit signals (evaluate and decide)
- Bearish engulfing after profit > 15% → book profit, high reversal risk
- Price crosses below VWAP while in CE trade → momentum fading, exit or trail SL
- RSI drops below 45 while holding CE → consider partial exit
- Doji at resistance/round number while in profit → trail SL to entry price

## Trail stop loss strategy
- After +15% profit: move SL to breakeven (entry price)
- After +25% profit: move SL to +10% (lock in partial profit)
- After +40% profit: move SL to +25% (ride the trend safely)

## Never do
- Never average down on a losing options trade
- Never hold past 3:00 PM hoping for recovery
- Never remove SL "just this once"