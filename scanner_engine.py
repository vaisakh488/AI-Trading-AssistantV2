"""
scanner_engine.py
-----------------
Scans a basket of instruments, scores each one on technicals + news,
and returns a ranked list ready for Claude to pick the best trade.

Design goals:
- Fast: fetches snapshots only (no full candle load per instrument)
- Token-efficient: builds a compact table for Claude, not full JSON
- Graceful: skips any instrument that fails to fetch, never crashes
"""

import time
import anthropic
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from fo_universe import ALL_CONFIGS, LOT_SIZES, ATM_STEPS

_CLAUDE = anthropic.Anthropic()

# ── Default scan baskets ───────────────────────────────────────────────────

BASKETS = {
    "🏆 Top picks (indices)": ["NIFTY", "BANKNIFTY", "FINNIFTY"],
    "🔥 High momentum stocks": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "TATAMOTORS", "SBIN"],
    "💻 IT sector": ["INFY", "TCS", "WIPRO", "HCLTECH", "TECHM"],
    "🏦 Banking sector": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"],
    "🚗 Auto sector": ["TATAMOTORS", "MARUTI", "M&M", "BAJAJ-AUTO"],
    "💊 Pharma sector": ["SUNPHARMA", "DRREDDY"],
    "⚡ All indices": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"],
    "🎯 Custom": [],   # user picks
}

# ── Per-instrument scoring ─────────────────────────────────────────────────

def score_instrument(underlying: str, budget: int, news_bias: str = "NEUTRAL") -> dict:
    """
    Fetch snapshot + 1-min candles for one instrument and return a score dict.
    Returns None on any fetch error so the scanner can skip it gracefully.
    """
    try:
        # Import here so scanner_engine works in both demo and live mode
        try:
            from demo_engine import get_index_snapshot, get_candles_with_indicators
        except Exception:
            return None

        snap = get_index_snapshot(underlying)
        if not snap or snap.get("ltp", 0) == 0:
            return None

        df = get_candles_with_indicators(0, underlying=underlying)

        cfg      = ALL_CONFIGS.get(underlying, {})
        lot_size = cfg.get("lot_size", 75)
        step     = cfg.get("step", 50)
        spot     = snap["ltp"]
        atm      = round(spot / step) * step

        # ── Technical score ────────────────────────────────────────────────
        score = 0
        details = {}

        if df is not None and not df.empty and len(df) >= 5:
            last  = df.iloc[-1]
            prev5 = df.iloc[-5:]

            bull_c = int(prev5["is_bullish"].sum())
            bear_c = int(prev5["is_bearish"].sum())
            rsi    = float(last.get("RSI_14", 50))
            above_vwap  = bool(last.get("above_vwap",  False))
            ema_bullish = bool(last.get("ema_bullish",  False))
            macd        = float(last.get("MACD_12_26_9",  0))
            macd_sig    = float(last.get("MACDs_12_26_9", 0))
            chg_pct     = snap.get("change_pct", 0)

            # Score signals
            score += 2  if bull_c >= 4 else (1 if bull_c == 3 else 0)
            score -= 2  if bear_c >= 4 else (1 if bear_c == 3 else 0)
            score += 1  if above_vwap  else -1
            score += 1  if ema_bullish else -1
            score += 1  if rsi > 55    else (-1 if rsi < 45 else 0)
            score += 1  if macd > macd_sig else -1
            if rsi > 72: score -= 1  # overbought
            if rsi < 30: score += 1  # oversold bounce potential

            # News bias
            score += {"BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0}.get(news_bias, 0)

            # Momentum: strong move today
            if abs(chg_pct) > 1.0:
                score += 1 if chg_pct > 0 else -1

            direction = (
                "STRONG_BULL" if score >= 5  else
                "BULL"        if score >= 2  else
                "STRONG_BEAR" if score <= -5 else
                "BEAR"        if score <= -2 else
                "SIDEWAYS"
            )

            # Suggested option type
            if score >= 2:
                opt_type = "CE"
            elif score <= -2:
                opt_type = "PE"
            else:
                opt_type = "—"

            # ATM premium estimate (rough Black-Scholes)
            atm_premium = _estimate_atm_premium(spot, step, df, cfg)
            lot_cost     = round(atm_premium * lot_size, 0)
            affordable   = lot_cost <= budget

            details = {
                "rsi":          round(rsi, 1),
                "above_vwap":   above_vwap,
                "ema_bullish":  ema_bullish,
                "bull_candles": bull_c,
                "bear_candles": bear_c,
                "macd_bull":    macd > macd_sig,
                "direction":    direction,
                "opt_type":     opt_type,
                "atm_strike":   atm,
                "atm_premium":  round(atm_premium, 1),
                "lot_cost":     lot_cost,
                "affordable":   affordable,
            }
        else:
            direction = "BULLISH" if snap.get("direction") == "BULLISH" else "BEARISH"
            opt_type  = "CE" if direction == "BULLISH" else "PE"
            details = {
                "rsi": 50, "above_vwap": False, "ema_bullish": False,
                "bull_candles": 0, "bear_candles": 0, "macd_bull": False,
                "direction": direction, "opt_type": opt_type,
                "atm_strike": atm, "atm_premium": 0,
                "lot_cost": 0, "affordable": False,
            }

        return {
            "underlying":  underlying,
            "ltp":         round(spot, 2),
            "change_pct":  snap.get("change_pct", 0),
            "direction":   snap.get("direction", "—"),
            "score":       score,
            "confidence":  min(abs(score) * 14, 98),
            "category":    cfg.get("category", ""),
            "lot_size":    lot_size,
            **details,
        }

    except Exception as e:
        return None


def scan_basket(instruments: list[str], budget: int,
                news_bias: str = "NEUTRAL",
                max_workers: int = 4) -> list[dict]:
    """
    Scan a list of instruments in parallel (ThreadPoolExecutor).
    Returns results sorted by abs(score) desc — strongest signals first.
    """
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(score_instrument, sym, budget, news_bias): sym
                   for sym in instruments}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    # Sort: affordable first, then by |score| desc
    results.sort(key=lambda x: (not x.get("affordable", False), -abs(x["score"])))
    return results


# ── Claude picks the best trade ────────────────────────────────────────────

def claude_pick_best(
    scan_results: list[dict],
    budget: int,
    news_bias: str,
    news_themes: list[str],
    news_hint: str,
    beginner_mode: bool = True,
) -> str:
    """
    Send the compact scan table to Claude (Sonnet) and get a single best
    trade recommendation with entry/SL/target.

    Token-efficient: sends a CSV-like table, not full JSON.
    """
    if not scan_results:
        return "No scan results available. Please scan again."

    # Build a compact table — much cheaper than JSON
    header = "sym|score|dir|rsi|vwap|ema|chg%|opt|atm_strike|premium|lot_cost|affordable"
    rows   = []
    for r in scan_results[:12]:    # max 12 rows to Claude
        rows.append(
            f"{r['underlying']}|{r['score']}|{r['direction']}|{r['rsi']}|"
            f"{'Y' if r['above_vwap'] else 'N'}|{'Y' if r['ema_bullish'] else 'N'}|"
            f"{r['change_pct']}|{r['opt_type']}|{r['atm_strike']}|"
            f"{r['atm_premium']}|{r['lot_cost']}|{'Y' if r['affordable'] else 'N'}"
        )
    table = header + "\n" + "\n".join(rows)

    mode_note = (
        "User is a BEGINNER. Use plain English, no jargon. Explain why you picked it simply."
        if beginner_mode
        else "User is experienced. Give full technical reasoning."
    )

    prompt = f"""You are an expert NSE intraday options trader.
{mode_note}

Budget per lot: ₹{budget}
News bias: {news_bias} | Themes: {', '.join(news_themes) if news_themes else 'none'}
News hint: {news_hint}
Time: {time.strftime('%H:%M IST')}

Scan results (sorted by signal strength, affordable=within budget):
{table}

Pick the SINGLE BEST trade from affordable instruments (affordable=Y).
Respond in this exact structure:

**Best trade: [SYMBOL] [CE/PE]**
Strike: ₹[ATM strike]
Entry range: ₹[X] – ₹[Y]
Stop loss: ₹[SL] (–[X]%)
Target: ₹[TGT] (+[X]%)
Lot cost: ₹[X] × [lot_size] units = ₹[total]

Why this trade:
[2–3 sentences of reasoning]

Why NOT the others:
[1 sentence on why top alternatives were skipped]

⚠️ Educational only — not financial advice. Always use stop loss."""

    resp = _CLAUDE.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ── Helper: quick ATM premium estimate ────────────────────────────────────

def _estimate_atm_premium(spot: float, step: float,
                           df, cfg: dict) -> float:
    """Rough ATM CE premium estimate using historical vol and BS."""
    try:
        import math
        from scipy.stats import norm

        # Get IV from recent candle returns
        if df is not None and len(df) >= 10:
            ret = df["close"].pct_change().dropna()
            iv  = float(ret.std() * math.sqrt(252 * 375))  # annualised from 1-min
            iv  = max(min(iv, 1.5), 0.05)                  # clamp 5%–150%
        else:
            iv = 0.15

        expiry_day = cfg.get("expiry_day", 3)
        from datetime import date
        today = date.today()
        days_ahead = expiry_day - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        T = max(days_ahead / 365, 1 / 365)
        r = 0.065
        K = round(spot / step) * step

        d1 = (math.log(spot / K) + (r + 0.5 * iv**2) * T) / (iv * math.sqrt(T))
        d2 = d1 - iv * math.sqrt(T)
        premium = spot * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
        return max(round(premium, 1), 1.0)
    except Exception:
        return round(spot * 0.003, 1)   # fallback: 0.3% of spot