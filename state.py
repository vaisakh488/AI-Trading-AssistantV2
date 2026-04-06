"""
state.py
--------
ActiveTrade dataclass + lightweight JSON trade journal.
No external DB needed — flat file works fine for retail usage.
"""

from dataclasses import dataclass, field
from datetime import datetime
import json
import os

JOURNAL_FILE = "trade_journal.json"


@dataclass
class ActiveTrade:
    symbol:           str   = ""
    instrument_token: int   = 0
    underlying:       str   = "NIFTY"
    option_type:      str   = ""      # CE or PE
    strike:           float = 0.0
    entry_price:      float = 0.0
    lot_size:         int   = 75
    lots:             int   = 1
    entry_time:       str   = ""
    target_pct:       float = 30.0
    sl_pct:           float = 20.0
    is_active:        bool  = False
    news_bias:        str   = "NEUTRAL"   # from news_engine at entry time


# ── Trade Journal ─────────────────────────────────────────────────────────

def load_journal() -> list[dict]:
    if not os.path.exists(JOURNAL_FILE):
        return []
    try:
        with open(JOURNAL_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_trade(trade: ActiveTrade, exit_price: float,
               exit_reason: str, pnl_pct: float, pnl_rs: float):
    """Append a completed trade to the journal."""
    journal = load_journal()
    journal.append({
        "date":        datetime.now().strftime("%Y-%m-%d"),
        "time_entry":  trade.entry_time,
        "time_exit":   datetime.now().strftime("%H:%M"),
        "underlying":  trade.underlying,
        "type":        trade.option_type,
        "strike":      trade.strike,
        "lots":        trade.lots,
        "lot_size":    trade.lot_size,
        "entry":       round(trade.entry_price, 2),
        "exit":        round(exit_price, 2),
        "pnl_pct":     round(pnl_pct, 2),
        "pnl_rs":      round(pnl_rs, 2),
        "exit_reason": exit_reason,
        "news_bias":   trade.news_bias,
        "result":      "WIN" if pnl_rs > 0 else "LOSS",
    })
    try:
        with open(JOURNAL_FILE, "w") as f:
            json.dump(journal, f, indent=2)
    except Exception as e:
        print(f"Journal save error: {e}")


def get_journal_stats() -> dict:
    journal = load_journal()
    if not journal:
        return {
            "total": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "total_pnl": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
        }
    wins   = [t for t in journal if t["result"] == "WIN"]
    losses = [t for t in journal if t["result"] == "LOSS"]
    pnls   = [t["pnl_rs"] for t in journal]
    return {
        "total":       len(journal),
        "wins":        len(wins),
        "losses":      len(losses),
        "win_rate":    round(len(wins) / len(journal) * 100, 1),
        "total_pnl":   round(sum(pnls), 2),
        "avg_win":     round(sum(t["pnl_rs"] for t in wins)   / max(len(wins),   1), 2),
        "avg_loss":    round(sum(t["pnl_rs"] for t in losses) / max(len(losses), 1), 2),
        "best_trade":  round(max(pnls), 2) if pnls else 0.0,
        "worst_trade": round(min(pnls), 2) if pnls else 0.0,
    }