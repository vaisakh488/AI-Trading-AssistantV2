"""
signal_engine.py
----------------
Trend detection and exit signal logic.
Works with both live Kite data and demo yfinance data.
Incorporates news sentiment bias into the trend score.
"""

import pandas as pd
from datetime import datetime


# ── Trend signal ───────────────────────────────────────────────────────────

def get_trend_signal(df: pd.DataFrame, news_bias: str = "NEUTRAL") -> dict:
    """
    Analyse last 5–10 candles and return a comprehensive trend summary.
    news_bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL' — from news_engine.
    """
    if df.empty or len(df) < 5:
        return {
            "trend": "UNKNOWN", "score": 0, "confidence": 0,
            "above_vwap": False, "ema_bullish": False,
            "rsi": 50.0, "macd_bullish": False,
            "bullish_candles": 0, "bearish_candles": 0,
            "news_bias": news_bias,
            "last_close": 0.0, "vwap": 0.0, "ema9": 0.0, "ema21": 0.0,
            "plain_summary": "Not enough data yet",
        }

    last  = df.iloc[-1]
    prev5 = df.iloc[-5:]

    bullish_candles = int(prev5["is_bullish"].sum())
    bearish_candles = int(prev5["is_bearish"].sum())
    above_vwap      = bool(last.get("above_vwap",  False))
    ema_bullish     = bool(last.get("ema_bullish",  False))
    rsi             = float(last.get("RSI_14",       50))
    macd            = float(last.get("MACD_12_26_9",  0))
    macd_signal     = float(last.get("MACDs_12_26_9", 0))

    # ── Score each signal (max technical ±8, news ±1) ─────────────────────
    score = 0
    score += 2  if bullish_candles >= 4 else (1  if bullish_candles == 3 else 0)
    score -= 2  if bearish_candles >= 4 else (1  if bearish_candles == 3 else 0)
    score += 1  if above_vwap  else -1
    score += 1  if ema_bullish else -1
    score += 1  if rsi > 55    else (-1 if rsi < 45 else 0)
    score += 1  if macd > macd_signal else -1

    # Bonus: RSI extremes
    if rsi > 70: score -= 1   # overbought — fade CE entries
    if rsi < 30: score += 1   # oversold  — fade PE entries

    # News bias (small weight — don't override technicals)
    news_score = {"BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0}.get(news_bias, 0)
    score += news_score

    trend = (
        "STRONG_BULL" if score >= 5  else
        "BULL"        if score >= 2  else
        "STRONG_BEAR" if score <= -5 else
        "BEAR"        if score <= -2 else
        "SIDEWAYS"
    )

    plain = _plain_trend(trend, rsi, above_vwap, news_bias)

    return {
        "trend":           trend,
        "score":           score,
        "confidence":      min(abs(score) * 14, 98),
        "above_vwap":      above_vwap,
        "ema_bullish":     ema_bullish,
        "rsi":             round(rsi, 1),
        "macd_bullish":    macd > macd_signal,
        "bullish_candles": bullish_candles,
        "bearish_candles": bearish_candles,
        "news_bias":       news_bias,
        "last_close":      round(float(last["close"]), 2),
        "vwap":            round(float(last.get("vwap",   last["close"])), 2),
        "ema9":            round(float(last.get("EMA_9",  last["close"])), 2),
        "ema21":           round(float(last.get("EMA_21", last["close"])), 2),
        "plain_summary":   plain,
    }


def _plain_trend(trend: str, rsi: float, above_vwap: bool, news_bias: str) -> str:
    """Return a one-line plain-English summary for beginner mode."""
    direction = {
        "STRONG_BULL": "Market is moving up strongly",
        "BULL":        "Market is moving up",
        "SIDEWAYS":    "Market has no clear direction",
        "BEAR":        "Market is moving down",
        "STRONG_BEAR": "Market is moving down strongly",
    }.get(trend, "Unclear")

    extras = []
    if rsi > 70:
        extras.append("RSI high — may reverse soon")
    elif rsi < 30:
        extras.append("RSI low — may bounce soon")
    if not above_vwap and trend in ("BULL", "STRONG_BULL"):
        extras.append("price below average — caution")
    if news_bias == "BEARISH":
        extras.append("news is negative today")
    elif news_bias == "BULLISH":
        extras.append("news is positive today")

    if extras:
        return f"{direction} ({', '.join(extras)})"
    return direction


# ── Exit signal ────────────────────────────────────────────────────────────

def get_exit_signal(df: pd.DataFrame, entry_price: float,
                    target_pct: float = 30, sl_pct: float = 20,
                    option_type: str = "CE") -> dict:
    """
    Evaluate whether to exit the active trade.
    option_type: CE or PE — used to interpret bearish/bullish patterns correctly.

    Returns:
        action:  HOLD | EXIT_SL | EXIT_TARGET | EXIT_PATTERN | EXIT_PARTIAL | EXIT_TIME
        reason:  plain-English explanation
        ltp:     estimated current price
        pnl_pct: current P&L %
        urgency: HIGH | MEDIUM | LOW | NONE
        plain:   beginner-friendly one-liner
    """
    if df.empty:
        return {
            "action": "HOLD", "reason": "Waiting for data",
            "ltp": entry_price, "pnl_pct": 0,
            "urgency": "NONE", "plain": "Waiting for price data...",
        }

    last = df.iloc[-1]
    ltp  = float(last["close"])
    pnl  = round((ltp - entry_price) / entry_price * 100, 2)

    # ── Hard rules (highest priority) ─────────────────────────────────────

    if pnl <= -sl_pct:
        return _exit("EXIT_SL", f"Stop loss hit ({pnl:.1f}%). Exit now to protect capital.",
                     ltp, pnl, "HIGH",
                     f"Your stop loss of -{sl_pct}% was hit. Exit immediately.")

    if pnl >= target_pct:
        return _exit("EXIT_TARGET", f"Target reached ({pnl:.1f}% profit). Book now.",
                     ltp, pnl, "HIGH",
                     f"You've made your {target_pct}% target! Take the profit now.")

    # ── Time-based exit ────────────────────────────────────────────────────
    now   = datetime.now()
    h, m  = now.hour, now.minute
    if h == 15 and m >= 0:
        return _exit("EXIT_TIME", f"3:00 PM — mandatory exit. P&L: {pnl:.1f}%",
                     ltp, pnl, "HIGH",
                     "3:00 PM — you must exit before market close at 3:30 PM.")
    if h == 14 and m >= 30:
        return _exit("EXIT_TIME", f"2:30 PM — exit strongly advised. P&L: {pnl:.1f}%",
                     ltp, pnl, "HIGH",
                     "2:30 PM — options lose value fast near close. Exit now.")

    # ── Pattern-based exits (depends on CE or PE) ─────────────────────────

    if option_type == "CE":
        # Bearish patterns hurt a CE buyer
        if bool(last.get("is_engulfing_bear", False)):
            return _exit("EXIT_PATTERN",
                         f"Bearish engulfing — reversal signal. P&L: {pnl:.1f}%",
                         ltp, pnl, "MEDIUM",
                         "A bearish reversal candle just formed. Your CE may lose value. Consider exiting.")

        if bool(last.get("is_pinbar_bear", False)) and pnl > 10:
            return _exit("EXIT_PATTERN",
                         f"Bearish pinbar at profit — protect gains. P&L: {pnl:.1f}%",
                         ltp, pnl, "MEDIUM",
                         f"Bearish signal with {pnl:.1f}% profit. Good time to exit and keep gains.")

        if not bool(last.get("above_vwap", True)) and pnl > 5:
            return _exit("EXIT_PATTERN",
                         f"Price fell below VWAP — momentum fading. P&L: {pnl:.1f}%",
                         ltp, pnl, "MEDIUM",
                         "Price dropped below its average. Upward momentum may be over.")

    else:  # PE
        # Bullish patterns hurt a PE buyer
        if bool(last.get("is_engulfing_bull", False)):
            return _exit("EXIT_PATTERN",
                         f"Bullish engulfing — upward reversal. P&L: {pnl:.1f}%",
                         ltp, pnl, "MEDIUM",
                         "A bullish reversal candle just formed. Your PE may lose value. Consider exiting.")

        if bool(last.get("is_pinbar_bull", False)) and pnl > 10:
            return _exit("EXIT_PATTERN",
                         f"Bullish pinbar at profit — protect gains. P&L: {pnl:.1f}%",
                         ltp, pnl, "MEDIUM",
                         f"Bullish signal with {pnl:.1f}% profit. Good time to exit and keep gains.")

        if bool(last.get("above_vwap", False)) and pnl > 5:
            return _exit("EXIT_PATTERN",
                         f"Price back above VWAP — downward momentum fading. P&L: {pnl:.1f}%",
                         ltp, pnl, "MEDIUM",
                         "Price moved above its average. Downward momentum may be over.")

    # ── Doji at profit — partial exit suggestion ───────────────────────────
    if bool(last.get("is_doji", False)) and pnl > 15:
        return _exit("EXIT_PARTIAL",
                     f"Doji (indecision candle) at good profit. P&L: {pnl:.1f}%",
                     ltp, pnl, "LOW",
                     f"Market is undecided. You have {pnl:.1f}% profit — consider exiting half your position.")

    # ── Trailing SL suggestion (profits protected) ─────────────────────────
    trail_reason = ""
    if pnl >= 20:
        trail_reason = f"Consider moving SL to breakeven (entry ₹{entry_price}). P&L: {pnl:.1f}%"
    elif pnl >= 15:
        trail_reason = f"Good profit ({pnl:.1f}%). Trail SL to +5% to lock in gains."

    return {
        "action":  "HOLD",
        "reason":  trail_reason if trail_reason else f"Trade healthy. P&L: {pnl:.1f}%. No exit signal.",
        "ltp":     ltp,
        "pnl_pct": pnl,
        "urgency": "NONE",
        "plain":   _plain_hold(pnl, trail_reason),
    }


def _exit(action, reason, ltp, pnl, urgency, plain) -> dict:
    return {
        "action":  action,
        "reason":  reason,
        "ltp":     ltp,
        "pnl_pct": pnl,
        "urgency": urgency,
        "plain":   plain,
    }


def _plain_hold(pnl: float, trail_reason: str) -> str:
    if trail_reason:
        return trail_reason
    if pnl > 10:
        return f"Good profit ({pnl:.1f}%). Hold — no exit signal yet. Watch for reversal candles."
    if pnl > 0:
        return f"In profit ({pnl:.1f}%). Hold and monitor."
    if pnl > -10:
        return f"Small loss ({pnl:.1f}%). Hold — within normal range."
    return f"Loss at {pnl:.1f}%. Approaching stop loss — stay alert."