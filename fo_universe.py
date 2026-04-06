"""
fo_universe.py
--------------
Single source of truth for ALL F&O instruments:
- Index options (NIFTY, BANKNIFTY, etc.)
- Stock options (RELIANCE, HDFCBANK, etc.)

Lot sizes are as per NSE circular (verify at nseindia.com before live trading).
"""

# ── Index F&O ──────────────────────────────────────────────────────────────

INDEX_CONFIG = {
    "NIFTY": {
        "yf_symbol":      "^NSEI",
        "lot_size":       75,
        "step":           50,
        "expiry_day":     3,          # Thursday (0=Mon)
        "fallback_price": 24500,
        "category":       "Index",
        "description":    "Nifty 50 — most liquid index",
    },
    "BANKNIFTY": {
        "yf_symbol":      "^NSEBANK",
        "lot_size":       30,
        "step":           100,
        "expiry_day":     2,          # Wednesday
        "fallback_price": 52000,
        "category":       "Index",
        "description":    "Bank Nifty — banking sector index",
    },
    "FINNIFTY": {
        "yf_symbol":      "NIFTY_FIN_SERVICE.NS",
        "yf_fallback":    "^NSEBANK",
        "lot_size":       65,
        "step":           50,
        "expiry_day":     1,          # Tuesday
        "fallback_price": 23000,
        "category":       "Index",
        "description":    "Fin Nifty — financial services index",
    },
    "MIDCPNIFTY": {
        "yf_symbol":      "^NSEMDCP50",
        "lot_size":       120,
        "step":           25,
        "expiry_day":     0,          # Monday
        "fallback_price": 12500,
        "category":       "Index",
        "description":    "Midcap Nifty — less liquid, wider spreads",
    },
    "SENSEX": {
        "yf_symbol":      "^BSESN",
        "lot_size":       10,
        "step":           100,
        "expiry_day":     4,          # Friday
        "fallback_price": 72000,
        "category":       "Index",
        "description":    "Sensex — BSE top 30 companies",
    },
}

# ── Stock F&O ──────────────────────────────────────────────────────────────
# Lot sizes as per NSE F&O contract specs (revised periodically by NSE).
# IMPORTANT: NSE revises these every 6 months. Always verify before live trading.

STOCK_FO_CONFIG = {
    # ── Banking & Finance ──
    "HDFCBANK": {
        "yf_symbol": "HDFCBANK.NS", "lot_size": 550,  "step": 10,
        "expiry_day": 3, "fallback_price": 1700,
        "category": "Banking", "description": "HDFC Bank — largest private bank",
    },
    "ICICIBANK": {
        "yf_symbol": "ICICIBANK.NS", "lot_size": 700, "step": 5,
        "expiry_day": 3, "fallback_price": 1250,
        "category": "Banking", "description": "ICICI Bank",
    },
    "SBIN": {
        "yf_symbol": "SBIN.NS", "lot_size": 1500, "step": 5,
        "expiry_day": 3, "fallback_price": 780,
        "category": "Banking", "description": "State Bank of India",
    },
    "AXISBANK": {
        "yf_symbol": "AXISBANK.NS", "lot_size": 625, "step": 10,
        "expiry_day": 3, "fallback_price": 1100,
        "category": "Banking", "description": "Axis Bank",
    },
    "KOTAKBANK": {
        "yf_symbol": "KOTAKBANK.NS", "lot_size": 400, "step": 10,
        "expiry_day": 3, "fallback_price": 1800,
        "category": "Banking", "description": "Kotak Mahindra Bank",
    },
    "BAJFINANCE": {
        "yf_symbol": "BAJFINANCE.NS", "lot_size": 125, "step": 50,
        "expiry_day": 3, "fallback_price": 7000,
        "category": "NBFC", "description": "Bajaj Finance — high premium",
    },
    "BAJAJFINSV": {
        "yf_symbol": "BAJAJFINSV.NS", "lot_size": 125, "step": 50,
        "expiry_day": 3, "fallback_price": 1700,
        "category": "NBFC", "description": "Bajaj Finserv",
    },
    # ── IT ──
    "INFY": {
        "yf_symbol": "INFY.NS", "lot_size": 400, "step": 20,
        "expiry_day": 3, "fallback_price": 1600,
        "category": "IT", "description": "Infosys",
    },
    "TCS": {
        "yf_symbol": "TCS.NS", "lot_size": 150, "step": 50,
        "expiry_day": 3, "fallback_price": 3500,
        "category": "IT", "description": "Tata Consultancy Services",
    },
    "WIPRO": {
        "yf_symbol": "WIPRO.NS", "lot_size": 1500, "step": 5,
        "expiry_day": 3, "fallback_price": 460,
        "category": "IT", "description": "Wipro",
    },
    "HCLTECH": {
        "yf_symbol": "HCLTECH.NS", "lot_size": 350, "step": 10,
        "expiry_day": 3, "fallback_price": 1500,
        "category": "IT", "description": "HCL Technologies",
    },
    "TECHM": {
        "yf_symbol": "TECHM.NS", "lot_size": 600, "step": 10,
        "expiry_day": 3, "fallback_price": 1600,
        "category": "IT", "description": "Tech Mahindra",
    },
    # ── Oil & Gas ──
    "RELIANCE": {
        "yf_symbol": "RELIANCE.NS", "lot_size": 250, "step": 20,
        "expiry_day": 3, "fallback_price": 2900,
        "category": "Oil & Gas", "description": "Reliance Industries",
    },
    "ONGC": {
        "yf_symbol": "ONGC.NS", "lot_size": 1925, "step": 5,
        "expiry_day": 3, "fallback_price": 280,
        "category": "Oil & Gas", "description": "ONGC — high lot count",
    },
    # ── Auto ──
    "TATAMOTORS": {
        "yf_symbol": "TATAMOTORS.NS", "lot_size": 1425, "step": 5,
        "expiry_day": 3, "fallback_price": 820,
        "category": "Auto", "description": "Tata Motors — volatile, liquid",
    },
    "MARUTI": {
        "yf_symbol": "MARUTI.NS", "lot_size": 37, "step": 100,
        "expiry_day": 3, "fallback_price": 12000,
        "category": "Auto", "description": "Maruti Suzuki — high price",
    },
    "M&M": {
        "yf_symbol": "M&M.NS", "lot_size": 700, "step": 10,
        "expiry_day": 3, "fallback_price": 2700,
        "category": "Auto", "description": "Mahindra & Mahindra",
    },
    "BAJAJ-AUTO": {
        "yf_symbol": "BAJAJ-AUTO.NS", "lot_size": 75, "step": 50,
        "expiry_day": 3, "fallback_price": 9000,
        "category": "Auto", "description": "Bajaj Auto",
    },
    # ── FMCG ──
    "HINDUNILVR": {
        "yf_symbol": "HINDUNILVR.NS", "lot_size": 300, "step": 10,
        "expiry_day": 3, "fallback_price": 2500,
        "category": "FMCG", "description": "Hindustan Unilever",
    },
    "ITC": {
        "yf_symbol": "ITC.NS", "lot_size": 3200, "step": 5,
        "expiry_day": 3, "fallback_price": 420,
        "category": "FMCG", "description": "ITC — defensive, large lot",
    },
    # ── Pharma ──
    "SUNPHARMA": {
        "yf_symbol": "SUNPHARMA.NS", "lot_size": 350, "step": 10,
        "expiry_day": 3, "fallback_price": 1700,
        "category": "Pharma", "description": "Sun Pharmaceutical",
    },
    "DRREDDY": {
        "yf_symbol": "DRREDDY.NS", "lot_size": 125, "step": 50,
        "expiry_day": 3, "fallback_price": 6500,
        "category": "Pharma", "description": "Dr. Reddy's Laboratories",
    },
    # ── Infrastructure ──
    "LT": {
        "yf_symbol": "LT.NS", "lot_size": 175, "step": 20,
        "expiry_day": 3, "fallback_price": 3400,
        "category": "Infra", "description": "Larsen & Toubro",
    },
    "ADANIENT": {
        "yf_symbol": "ADANIENT.NS", "lot_size": 500, "step": 10,
        "expiry_day": 3, "fallback_price": 2300,
        "category": "Conglomerate", "description": "Adani Enterprises — volatile",
    },
    "ADANIPORTS": {
        "yf_symbol": "ADANIPORTS.NS", "lot_size": 625, "step": 10,
        "expiry_day": 3, "fallback_price": 1300,
        "category": "Infra", "description": "Adani Ports",
    },
    # ── Power ──
    "POWERGRID": {
        "yf_symbol": "POWERGRID.NS", "lot_size": 2700, "step": 5,
        "expiry_day": 3, "fallback_price": 320,
        "category": "Power", "description": "Power Grid — defensive",
    },
    "NTPC": {
        "yf_symbol": "NTPC.NS", "lot_size": 2700, "step": 5,
        "expiry_day": 3, "fallback_price": 360,
        "category": "Power", "description": "NTPC",
    },
    # ── Telecom ──
    "BHARTIARTL": {
        "yf_symbol": "BHARTIARTL.NS", "lot_size": 475, "step": 10,
        "expiry_day": 3, "fallback_price": 1800,
        "category": "Telecom", "description": "Bharti Airtel",
    },
    # ── Metals ──
    "TATASTEEL": {
        "yf_symbol": "TATASTEEL.NS", "lot_size": 5500, "step": 5,
        "expiry_day": 3, "fallback_price": 160,
        "category": "Metals", "description": "Tata Steel — cyclical",
    },
    "JSWSTEEL": {
        "yf_symbol": "JSWSTEEL.NS", "lot_size": 675, "step": 10,
        "expiry_day": 3, "fallback_price": 900,
        "category": "Metals", "description": "JSW Steel",
    },
    # ── Consumer ──
    "ASIANPAINT": {
        "yf_symbol": "ASIANPAINT.NS", "lot_size": 200, "step": 20,
        "expiry_day": 3, "fallback_price": 2400,
        "category": "Consumer", "description": "Asian Paints",
    },
    "TITAN": {
        "yf_symbol": "TITAN.NS", "lot_size": 350, "step": 10,
        "expiry_day": 3, "fallback_price": 3400,
        "category": "Consumer", "description": "Titan Company",
    },
}

# ── Merged master config ───────────────────────────────────────────────────

ALL_CONFIGS = {**INDEX_CONFIG, **STOCK_FO_CONFIG}

# ── Convenient lists ───────────────────────────────────────────────────────

ALL_INDICES   = list(INDEX_CONFIG.keys())
ALL_STOCKS_FO = sorted(STOCK_FO_CONFIG.keys())
ALL_INSTRUMENTS = ALL_INDICES + ALL_STOCKS_FO

# ── Lot sizes dict (for quick lookup) ─────────────────────────────────────

LOT_SIZES = {sym: cfg["lot_size"] for sym, cfg in ALL_CONFIGS.items()}
ATM_STEPS  = {sym: cfg["step"]     for sym, cfg in ALL_CONFIGS.items()}

# ── Category grouping for UI display ──────────────────────────────────────

CATEGORY_ORDER = ["Index", "Banking", "NBFC", "IT", "Oil & Gas", "Auto",
                  "FMCG", "Pharma", "Infra", "Conglomerate", "Power",
                  "Telecom", "Metals", "Consumer"]

def instruments_by_category() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {cat: [] for cat in CATEGORY_ORDER}
    for sym, cfg in ALL_CONFIGS.items():
        cat = cfg.get("category", "Other")
        if cat not in out:
            out[cat] = []
        out[cat].append(sym)
    return {k: v for k, v in out.items() if v}