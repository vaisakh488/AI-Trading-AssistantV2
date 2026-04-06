"""
news_engine.py
--------------
Fetches headlines from Zerodha Pulse RSS and extracts market sentiment
using Claude with a minimal, token-efficient prompt.

Cache: headlines are cached for 10 minutes to avoid repeated API calls.
Sentiment: cached for 15 minutes per underlying to save LLM tokens.
"""

import time
import json
import anthropic
from datetime import datetime

try:
    import feedparser
    _FEEDPARSER_OK = True
except ImportError:
    _FEEDPARSER_OK = False

PULSE_RSS = "https://pulse.zerodha.com/feed.php"
_CLAUDE   = anthropic.Anthropic()

# ── Simple in-memory cache ─────────────────────────────────────────────────

_headline_cache: dict = {"data": [], "ts": 0.0}
_sentiment_cache: dict = {}          # key: underlying, val: {data, ts}

HEADLINE_TTL  = 600   # 10 min
SENTIMENT_TTL = 900   # 15 min — sentiment doesn't need per-minute refresh


def fetch_pulse_headlines(max_items: int = 12) -> list[dict]:
    """Return cached headlines; re-fetch only when TTL expired."""
    now = time.time()
    if now - _headline_cache["ts"] < HEADLINE_TTL and _headline_cache["data"]:
        return _headline_cache["data"][:max_items]

    items: list[dict] = []
    if _FEEDPARSER_OK:
        try:
            feed = feedparser.parse(PULSE_RSS)
            for e in feed.entries[:20]:
                title = e.get("title", "").strip()
                if title:
                    items.append({
                        "title":     title,
                        "published": e.get("published", ""),
                        "link":      e.get("link", ""),
                    })
        except Exception:
            pass

    # Fallback: return stale cache if fetch failed
    if not items and _headline_cache["data"]:
        return _headline_cache["data"][:max_items]

    _headline_cache["data"] = items
    _headline_cache["ts"]   = now
    return items[:max_items]


def get_news_sentiment(underlying: str = "NIFTY") -> dict:
    """
    Token-efficient Claude call: sends headlines once, gets structured JSON back.
    Cached per underlying for SENTIMENT_TTL seconds.
    Returns: bias, confidence (0-100), key_themes (list), trade_hint (str)
    """
    now = time.time()
    cached = _sentiment_cache.get(underlying, {})
    if cached and (now - cached.get("ts", 0)) < SENTIMENT_TTL:
        return cached["data"]

    headlines = fetch_pulse_headlines(10)
    if not headlines:
        result = _neutral()
        _cache_sentiment(underlying, result)
        return result

    # Build a compact headline string (titles only — saves tokens)
    hl_text = "\n".join(f"- {h['title']}" for h in headlines)
    today   = datetime.now().strftime("%d %b %Y")

    # ── Token-efficient prompt: short, structured, no examples ─────────────
    prompt = (
        f"Date: {today}. Underlying: {underlying}.\n"
        f"Headlines:\n{hl_text}\n\n"
        "Reply ONLY with valid JSON (no markdown, no explanation):\n"
        '{"bias":"BULLISH|BEARISH|NEUTRAL","conf":70,'
        '"themes":["theme1","theme2","theme3"],'
        '"hint":"one line trade hint for options buyer"}'
    )

    try:
        resp = _CLAUDE.messages.create(
            model="claude-haiku-4-5-20251001",   # cheapest model for simple JSON
            max_tokens=180,
            messages=[{"role": "user", "content": prompt}],
        )
        raw  = resp.content[0].text.strip()
        # Strip accidental code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        data = json.loads(raw)
        result = {
            "bias":       data.get("bias",   "NEUTRAL"),
            "confidence": int(data.get("conf", 50)),
            "key_themes": data.get("themes", [])[:3],
            "trade_hint": data.get("hint",   "No specific signal from news"),
        }
    except Exception as e:
        result = _neutral(f"Sentiment parse error: {e}")

    _cache_sentiment(underlying, result)
    return result


def _neutral(hint: str = "No news data available") -> dict:
    return {"bias": "NEUTRAL", "confidence": 40, "key_themes": [], "trade_hint": hint}


def _cache_sentiment(underlying: str, data: dict):
    _sentiment_cache[underlying] = {"data": data, "ts": time.time()}


def invalidate_cache():
    """Call this if you want to force a refresh (e.g. on app restart)."""
    _headline_cache["ts"] = 0.0
    _sentiment_cache.clear()