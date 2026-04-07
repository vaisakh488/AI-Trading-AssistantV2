"""
demo_engine.py
--------------
Simulates live Kite data using yfinance + Black-Scholes options pricing.
Works for ALL instruments in fo_universe.py (indices + stocks).

Data is real market data via yfinance — ~15 min delayed, not live tick.
Used when KITE_ACCESS_TOKEN is not set.
"""

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import math
from datetime import datetime, date, timedelta
from functools import lru_cache

from fo_universe import ALL_CONFIGS, LOT_SIZES, ATM_STEPS


# ── Index snapshot ─────────────────────────────────────────────────────────

def get_index_snapshot(underlying: str = "NIFTY") -> dict:
    cfg = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])
    sym = cfg["yf_symbol"]

    ticker = yf.Ticker(sym)
    hist   = ticker.history(period="2d", interval="1m")

    # Fallback ticker
    if hist.empty and "yf_fallback" in cfg:
        ticker = yf.Ticker(cfg["yf_fallback"])
        hist   = ticker.history(period="2d", interval="1m")

    if hist.empty:
        return _fallback_snapshot(underlying)

    latest    = hist.iloc[-1]
    yesterday = hist[hist.index.date == (date.today() - timedelta(days=1))]["Close"]
    prev_close = float(yesterday.iloc[-1]) if not yesterday.empty else float(hist["Close"].iloc[0])

    ltp      = float(latest["Close"])
    today_df = hist[hist.index.date == date.today()]
    day_open = float(today_df["Open"].iloc[0])  if not today_df.empty else ltp
    day_high = float(today_df["High"].max())    if not today_df.empty else ltp
    day_low  = float(today_df["Low"].min())     if not today_df.empty else ltp
    chg_pct  = round((ltp - prev_close) / prev_close * 100, 2)

    return {
        "underlying":  underlying,
        "ltp":         round(ltp, 2),
        "open":        round(day_open, 2),
        "high":        round(day_high, 2),
        "low":         round(day_low, 2),
        "prev_close":  round(prev_close, 2),
        "change_pct":  chg_pct,
        "direction":   "BULLISH" if ltp > day_open else "BEARISH",
        "lot_size":    cfg["lot_size"],
        "step":        cfg["step"],
        "category":    cfg.get("category", ""),
        "description": cfg.get("description", ""),
        "data_source": "yfinance (~15 min delay)",
    }


def _fallback_snapshot(underlying: str) -> dict:
    cfg = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])
    ltp = cfg["fallback_price"]
    return {
        "underlying":  underlying,
        "ltp":         ltp,
        "open":        ltp - cfg["step"],
        "high":        ltp + cfg["step"] * 2,
        "low":         ltp - cfg["step"] * 3,
        "prev_close":  ltp - cfg["step"],
        "change_pct":  0.12,
        "direction":   "BULLISH",
        "lot_size":    cfg["lot_size"],
        "step":        cfg["step"],
        "category":    cfg.get("category", ""),
        "description": cfg.get("description", ""),
        "data_source": "fallback (yfinance unavailable)",
    }


# ── Options chain simulation ───────────────────────────────────────────────

def get_atm_options(underlying: str, budget: int = 5000) -> list[dict]:
    """
    Generates ATM ± 4 strikes using Black-Scholes with real historical vol.
    Filters by budget (lot_cost <= budget * 1.3 to show slightly OTM too).
    """
    cfg      = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])
    snap     = get_index_snapshot(underlying)
    spot     = snap["ltp"]
    lot_size = cfg["lot_size"]
    step     = cfg["step"]
    atm      = round(spot / step) * step

    iv  = _get_iv(underlying, cfg)
    dte = _days_to_expiry(underlying)
    T   = max(dte / 365, 1 / 365)
    r   = 0.065

    chain: list[dict] = []
    for i in range(-4, 5):
        strike = atm + i * step
        for opt_type in ["CE", "PE"]:
            ltp      = _black_scholes(spot, strike, T, r, iv, opt_type)
            ltp      = round(max(ltp, 0.5), 1)
            lot_cost = round(ltp * lot_size, 0)

            if lot_cost > budget * 1.4:
                continue

            moneyness = abs(strike - spot) / spot
            oi_base   = int(500_000 * math.exp(-moneyness * 20))
            volume    = max(int(oi_base * 0.1 * (1 + np.random.uniform(-0.3, 0.3))), 0)
            oi        = max(oi_base + int(np.random.uniform(-50_000, 50_000)), 0)

            chain.append({
                "strike":   strike,
                "type":     opt_type,
                "symbol":   f"{underlying}{_expiry_str(underlying)}{int(strike)}{opt_type}",
                "token":    abs(hash(f"{underlying}{strike}{opt_type}")) % 1_000_000,
                "ltp":      ltp,
                "oi":       oi,
                "volume":   volume,
                "bid":      round(ltp - 0.5, 1),
                "ask":      round(ltp + 0.5, 1),
                "lot_cost": lot_cost,
                "lot_size": lot_size,
                "iv_pct":   round(iv * 100, 1),
                "dte":      dte,
            })

    return sorted(chain, key=lambda x: (x["strike"], x["type"]))


# ── Candle data with indicators ────────────────────────────────────────────

def get_candles_with_indicators(instrument_token: int,
                                 underlying: str = "NIFTY",
                                 interval: str = "1m") -> pd.DataFrame:
    """
    Fetch 1-min candles for the underlying from yfinance and compute indicators.
    instrument_token is ignored in demo mode (kept for API compatibility).
    """
    cfg = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])
    sym = cfg["yf_symbol"]

    ticker = yf.Ticker(sym)
    hist   = ticker.history(period="1d", interval="1m")

    if hist.empty and "yf_fallback" in cfg:
        ticker = yf.Ticker(cfg["yf_fallback"])
        hist   = ticker.history(period="1d", interval="1m")

    if hist.empty:
        return pd.DataFrame()

    df = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index.name = "date"

    # ── Technical indicators ──────────────────────────────────────────────
    # ── Indicators — only append if enough rows exist ─────────────────────
    # pandas-ta silently skips appending when len(df) < period.
    # EMA_21 needs at least 21 rows; EMA_9 needs 9.
    # We always compute manually so the column is guaranteed to exist.

    df["EMA_9"]  = df["close"].ewm(span=9,  adjust=False).mean()
    df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()

    # RSI (manual — avoids pandas-ta missing-column issue on short data)
    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=13, adjust=False).mean()
    avg_l = loss.ewm(com=13, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    df["RSI_14"] = 100 - (100 / (1 + rs))

    # MACD (manual)
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD_12_26_9"]  = ema12 - ema26
    df["MACDs_12_26_9"] = df["MACD_12_26_9"].ewm(span=9, adjust=False).mean()
    df["MACDh_12_26_9"] = df["MACD_12_26_9"] - df["MACDs_12_26_9"]

    # ATR (manual)
    hl  = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift(1)).abs()
    lpc = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    df["ATRr_14"] = tr.ewm(com=13, adjust=False).mean()

    # VWAP (manual — reliable across all symbols)
    df["cum_vol"]   = df["volume"].cumsum()
    df["cum_volvp"] = (df["volume"] * (df["high"] + df["low"] + df["close"]) / 3).cumsum()
    df["vwap"]      = (df["cum_volvp"] / df["cum_vol"].replace(0, np.nan)).ffill()
    df.drop(columns=["cum_vol", "cum_volvp"], inplace=True)

    # ── Candle patterns ───────────────────────────────────────────────────
    df["body"]         = abs(df["close"] - df["open"])
    df["upper_wick"]   = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"]   = df[["open", "close"]].min(axis=1) - df["low"]
    df["candle_range"] = df["high"] - df["low"]

    df["is_bullish"] = df["close"] > df["open"]
    df["is_bearish"] = df["close"] < df["open"]
    df["is_doji"]    = df["body"]  < df["candle_range"] * 0.1

    df["is_engulfing_bull"] = (
        df["is_bullish"] &
        (df["open"]  < df["close"].shift(1)) &
        (df["close"] > df["open"].shift(1))
    )
    df["is_engulfing_bear"] = (
        df["is_bearish"] &
        (df["open"]  > df["close"].shift(1)) &
        (df["close"] < df["open"].shift(1))
    )
    df["is_pinbar_bull"] = (df["lower_wick"] > df["body"] * 2) & (df["upper_wick"] < df["body"])
    df["is_pinbar_bear"] = (df["upper_wick"] > df["body"] * 2) & (df["lower_wick"] < df["body"])

    df["above_vwap"]  = df["close"] > df["vwap"]
    df["ema_bullish"] = df["EMA_9"] > df["EMA_21"]

    # Drop only the first few rows where EMA_9 is warming up (< 9 rows of history)
    # Never raise KeyError — columns always exist now
    return df.iloc[9:] if len(df) > 9 else df


# ── Option live price (Phase 2 monitoring) ────────────────────────────────

def get_option_live_price(strike: float, opt_type: str,
                           underlying: str = "NIFTY") -> dict:
    """
    Approximate live option LTP using Black-Scholes from current spot.
    Used in Phase 2 when Kite is not connected.
    """
    cfg   = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])
    snap  = get_index_snapshot(underlying)
    spot  = snap["ltp"]
    T     = max(_days_to_expiry(underlying) / 365, 1 / 365)
    iv    = _get_iv(underlying, cfg)
    ltp   = round(_black_scholes(spot, strike, T, 0.065, iv, opt_type), 1)
    return {
        "ltp":    max(ltp, 0.5),
        "spot":   spot,
        "iv_pct": round(iv * 100, 1),
        "dte":    _days_to_expiry(underlying),
    }


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_iv(underlying: str, cfg: dict) -> float:
    """Historical volatility as IV proxy. Cached implicitly via yfinance."""
    sym = cfg["yf_symbol"]
    try:
        ticker = yf.Ticker(sym)
        hist   = ticker.history(period="10d")
        if hist.empty and "yf_fallback" in cfg:
            hist = yf.Ticker(cfg["yf_fallback"]).history(period="10d")
        if len(hist) >= 5:
            return float(hist["Close"].pct_change().dropna().std() * math.sqrt(252))
    except Exception:
        pass
    return 0.15


def _days_to_expiry(underlying: str = "NIFTY") -> int:
    cfg        = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])
    expiry_dow = cfg.get("expiry_day", 3)
    today      = date.today()
    days_ahead = expiry_dow - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return max(days_ahead, 1)


def _expiry_str(underlying: str = "NIFTY") -> str:
    cfg        = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])
    expiry_dow = cfg.get("expiry_day", 3)
    today      = date.today()
    days_ahead = expiry_dow - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return (today + timedelta(days=days_ahead)).strftime("%y%b%d").upper()


def _black_scholes(S: float, K: float, T: float, r: float,
                   sigma: float, opt_type: str = "CE") -> float:
    from scipy.stats import norm
    if T <= 0:
        return max(S - K, 0) if opt_type == "CE" else max(K - S, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "CE":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)