"""
data_engine.py
--------------
Live data engine using Kite Connect.
Only imported when KITE_ACCESS_TOKEN is set.
Supports all instruments in fo_universe.py.
"""

import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import date

import kite_client as kite
from fo_universe import ALL_CONFIGS, LOT_SIZES, ATM_STEPS


# ── NSE symbol map for indices ─────────────────────────────────────────────

NSE_SYMBOL_MAP = {
    "NIFTY":      "NSE:NIFTY 50",
    "BANKNIFTY":  "NSE:NIFTY BANK",
    "FINNIFTY":   "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
    "SENSEX":     "BSE:SENSEX",
}


def get_index_snapshot(underlying: str = "NIFTY") -> dict:
    cfg = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])

    # Indices use NSE symbol map; stocks use NSE:SYMBOL format
    sym = NSE_SYMBOL_MAP.get(underlying, f"NSE:{underlying}")

    q    = kite.get_quote([sym])
    data = list(q.values())[0]
    ltp  = data["last_price"]
    ohlc = data.get("ohlc", {})

    prev_close = ohlc.get("close", ltp)
    change_pct = round((ltp - prev_close) / prev_close * 100, 2) if prev_close else 0.0

    return {
        "underlying":  underlying,
        "ltp":         ltp,
        "open":        ohlc.get("open",  ltp),
        "high":        ohlc.get("high",  ltp),
        "low":         ohlc.get("low",   ltp),
        "prev_close":  prev_close,
        "change_pct":  change_pct,
        "direction":   "BULLISH" if ltp > ohlc.get("open", ltp) else "BEARISH",
        "lot_size":    cfg["lot_size"],
        "step":        cfg["step"],
        "category":    cfg.get("category", ""),
        "description": cfg.get("description", ""),
        "data_source": "Kite Connect (live)",
    }


def get_atm_options(underlying: str, budget: int = 5000) -> list[dict]:
    """Fetch live option chain from NFO via Kite."""
    from kite_client import get_nearest_expiry, get_option_chain
    cfg      = ALL_CONFIGS.get(underlying, ALL_CONFIGS["NIFTY"])
    snap     = get_index_snapshot(underlying)
    spot     = snap["ltp"]
    lot_size = cfg["lot_size"]
    step     = cfg["step"]
    atm      = round(spot / step) * step

    try:
        expiry = get_nearest_expiry(underlying)
        chain  = get_option_chain(underlying, expiry)
    except Exception:
        return []

    strikes_range = {atm + i * step for i in range(-4, 5)}
    result = []
    for opt in chain:
        if opt["strike"] not in strikes_range:
            continue
        lot_cost = round(opt["ltp"] * lot_size, 0)
        if lot_cost > budget * 1.4:
            continue
        result.append({**opt, "lot_cost": lot_cost, "lot_size": lot_size,
                        "iv_pct": None, "dte": _days_to_expiry_str(expiry)})

    return sorted(result, key=lambda x: (x["strike"], x["type"]))


def get_candles_with_indicators(instrument_token: int,
                                 underlying: str = "NIFTY",
                                 interval: str = "minute") -> pd.DataFrame:
    """Fetch live 1-min candles via Kite historical data API."""
    records = kite.get_historical_candles(instrument_token, interval=interval, days=1)
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df.set_index("date", inplace=True)
    df.columns = [c.lower() for c in df.columns]

    # Manual indicators — guaranteed columns regardless of row count
    df["EMA_9"]  = df["close"].ewm(span=9,  adjust=False).mean()
    df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()

    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=13, adjust=False).mean()
    avg_l = loss.ewm(com=13, adjust=False).mean()
    df["RSI_14"] = 100 - (100 / (1 + avg_g / avg_l.replace(0, np.nan)))

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD_12_26_9"]  = ema12 - ema26
    df["MACDs_12_26_9"] = df["MACD_12_26_9"].ewm(span=9, adjust=False).mean()
    df["MACDh_12_26_9"] = df["MACD_12_26_9"] - df["MACDs_12_26_9"]

    hl  = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift(1)).abs()
    lpc = (df["low"]  - df["close"].shift(1)).abs()
    df["ATRr_14"] = pd.concat([hl, hpc, lpc], axis=1).max(axis=1).ewm(com=13, adjust=False).mean()

    df["cum_vol"]   = df["volume"].cumsum()
    df["cum_volvp"] = (df["volume"] * (df["high"] + df["low"] + df["close"]) / 3).cumsum()
    df["vwap"]      = (df["cum_volvp"] / df["cum_vol"].replace(0, np.nan)).ffill()
    df.drop(columns=["cum_vol", "cum_volvp"], inplace=True)

    df["body"]         = abs(df["close"] - df["open"])
    df["upper_wick"]   = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"]   = df[["open", "close"]].min(axis=1) - df["low"]
    df["candle_range"] = df["high"] - df["low"]

    df["is_bullish"] = df["close"] > df["open"]
    df["is_bearish"] = df["close"] < df["open"]
    df["is_doji"]    = df["body"]  < df["candle_range"] * 0.1

    df["is_engulfing_bull"] = (
        df["is_bullish"] & (df["open"]  < df["close"].shift(1)) & (df["close"] > df["open"].shift(1))
    )
    df["is_engulfing_bear"] = (
        df["is_bearish"] & (df["open"]  > df["close"].shift(1)) & (df["close"] < df["open"].shift(1))
    )
    df["is_pinbar_bull"] = (df["lower_wick"] > df["body"] * 2) & (df["upper_wick"] < df["body"])
    df["is_pinbar_bear"] = (df["upper_wick"] > df["body"] * 2) & (df["lower_wick"] < df["body"])

    df["above_vwap"]  = df["close"] > df["vwap"]
    df["ema_bullish"] = df["EMA_9"] > df["EMA_21"]

    return df.iloc[9:] if len(df) > 9 else df


def _days_to_expiry_str(expiry: str) -> int:
    try:
        exp = date.fromisoformat(expiry)
        return max((exp - date.today()).days, 0)
    except Exception:
        return 0