"""
kite_client.py
--------------
Thin wrapper around KiteConnect for live mode.
Only imported when KITE_ACCESS_TOKEN is set in .env
"""

import os
import threading
from dotenv import load_dotenv
from kiteconnect import KiteConnect, KiteTicker

load_dotenv()

kite = KiteConnect(api_key=os.getenv("KITE_API_KEY", ""))


def get_login_url() -> str:
    return kite.login_url()


def get_profile() -> dict:
    return kite.profile()


def complete_login(request_token: str) -> str:
    data = kite.generate_session(request_token, api_secret=os.getenv("KITE_API_SECRET", ""))
    token = data["access_token"]
    kite.set_access_token(token)
    return token


def set_access_token(token: str):
    kite.set_access_token(token)


def get_quote(instruments: list[str]) -> dict:
    return kite.quote(instruments)


def get_option_chain(underlying: str, expiry: str) -> list[dict]:
    instruments = kite.instruments("NFO")
    chain = [
        i for i in instruments
        if i["name"] == underlying
        and str(i["expiry"]) == expiry
        and i["instrument_type"] in ("CE", "PE")
    ]
    if not chain:
        return []

    tokens = [i["instrument_token"] for i in chain[:80]]
    quotes = kite.quote(tokens)
    result = []
    for inst in chain[:80]:
        token = str(inst["instrument_token"])
        q = quotes.get(token, {})
        result.append({
            "strike":   inst["strike"],
            "type":     inst["instrument_type"],
            "symbol":   inst["tradingsymbol"],
            "token":    inst["instrument_token"],
            "ltp":      q.get("last_price", 0),
            "oi":       q.get("oi", 0),
            "volume":   q.get("volume", 0),
            "bid":      q.get("depth", {}).get("buy",  [{}])[0].get("price", 0),
            "ask":      q.get("depth", {}).get("sell", [{}])[0].get("price", 0),
        })
    return sorted(result, key=lambda x: x["strike"])


def get_historical_candles(instrument_token: int,
                            interval: str = "minute",
                            days: int = 1) -> list[dict]:
    from datetime import datetime, timedelta
    to_date   = datetime.now()
    from_date = to_date - timedelta(days=days)
    return kite.historical_data(instrument_token, from_date, to_date, interval)


def get_nearest_expiry(underlying: str) -> str:
    from datetime import date
    instruments = kite.instruments("NFO")
    expiries = sorted(set(
        str(i["expiry"]) for i in instruments
        if i["name"] == underlying and i["instrument_type"] == "CE"
    ))
    today  = str(date.today())
    future = [e for e in expiries if e >= today]
    return future[0] if future else (expiries[-1] if expiries else "")


# ── WebSocket live tick stream ─────────────────────────────────────────────

_tick_store: dict[int, dict] = {}
_ws_thread = None


def start_websocket(tokens: list[int]):
    global _ws_thread
    token  = os.getenv("KITE_ACCESS_TOKEN", "")
    ticker = KiteTicker(os.getenv("KITE_API_KEY", ""), token)

    def on_ticks(ws, ticks):
        for tick in ticks:
            _tick_store[tick["instrument_token"]] = tick

    def on_connect(ws, response):
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_FULL, tokens)

    ticker.on_ticks   = on_ticks
    ticker.on_connect = on_connect
    _ws_thread = threading.Thread(target=ticker.run_forever, daemon=True)
    _ws_thread.start()


def get_latest_tick(token: int) -> dict:
    return _tick_store.get(token, {})