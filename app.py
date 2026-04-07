"""
app.py — NSE Options Assistant (Production)
--------------------------------------------
Token-efficient, beginner-friendly intraday options trading assistant.

Features:
- Phase 1: Find the best CE/PE to buy with news sentiment + technicals
- Phase 2: Monitor live trade, auto-trail SL, plain-English exit signals
- Phase 3: Trade journal with win-rate stats
- Beginner mode: plain English, no jargon, step-by-step wizard
- All 30+ F&O instruments (indices + stocks)
- News from Zerodha Pulse with Claude sentiment (token-efficient)
- Uses claude-haiku for quick tasks, claude-sonnet only for deep analysis

Cost optimisation:
- Haiku for news sentiment (~30 tokens in, ~50 out)
- Sonnet only for trade recommendation chat
- Snapshots and sentiment cached (10-15 min TTL)
- Chat history trimmed to last 6 messages before each LLM call
"""

import streamlit as st
import anthropic
import json
import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
import plotly.graph_objects as go

from fo_universe import (
    ALL_CONFIGS, ALL_INDICES, ALL_STOCKS_FO, ALL_INSTRUMENTS,
    LOT_SIZES, ATM_STEPS, instruments_by_category,
)
from signal_engine import get_trend_signal, get_exit_signal
from state import ActiveTrade, save_trade, load_journal, get_journal_stats
from news_engine import fetch_pulse_headlines, get_news_sentiment
from scanner_engine import BASKETS, scan_basket, claude_pick_best

load_dotenv()

# ── Mode detection ─────────────────────────────────────────────────────────

def is_live_mode() -> bool:
    return len(os.getenv("KITE_ACCESS_TOKEN", "").strip()) > 10

LIVE_MODE = is_live_mode()

if LIVE_MODE:
    from data_engine import get_index_snapshot, get_atm_options, get_candles_with_indicators
else:
    from demo_engine import (get_index_snapshot, get_atm_options,
                              get_candles_with_indicators, get_option_live_price)

# ── Skills loader ──────────────────────────────────────────────────────────

def load_skills() -> str:
    skills_dir = Path("skills")
    if not skills_dir.exists():
        return ""
    parts = []
    for f in sorted(skills_dir.glob("*/SKILL.md")):
        parts.append(f"## Skill: {f.parent.name}\n{f.read_text()}")
    return "\n\n---\n".join(parts)

SKILLS = load_skills()
CLAUDE = anthropic.Anthropic()

# ── LLM helpers (token-efficient) ─────────────────────────────────────────

def ask_claude_sonnet(system: str, messages: list) -> str:
    """Full model for detailed trade analysis. Trim history to last 6 turns."""
    trimmed = messages[-6:] if len(messages) > 6 else messages
    resp = CLAUDE.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=900,           # reduced from 1500 — enough for trade guidance
        system=system,
        messages=trimmed,
    )
    return resp.content[0].text


def ask_claude_haiku(prompt: str) -> str:
    """Cheap model for short structured tasks."""
    resp = CLAUDE.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text

# ── Page config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="NSE Options Assistant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state defaults ─────────────────────────────────────────────────

_defaults = {
    "phase1_msgs":    [],
    "phase2_msgs":    [],
    "active_trade":   ActiveTrade(),
    "monitor_on":     False,
    "scan_done":      False,
    "scan_snapshot":  {},
    "scan_options":   [],
    "scan_trend":     {},
    "scan_sentiment": {},
    "underlying":     "NIFTY",
    "budget":         5000,
    "beginner_mode":  True,
    "wizard_step":    1,
    "last_refresh":   0.0,
    "scanner_results": [],
    "scanner_done":    False,
    "scanner_basket":  "🏆 Top picks (indices)",
    "scanner_budget":  5000,
    "scanner_pick":    "",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Helpers ────────────────────────────────────────────────────────────────

TREND_LABEL = {
    "STRONG_BULL": ("📈 Moving up strongly",   "green"),
    "BULL":        ("📈 Moving up",             "green"),
    "SIDEWAYS":    ("↔️ No clear direction",   "orange"),
    "BEAR":        ("📉 Moving down",           "red"),
    "STRONG_BEAR": ("📉 Moving down strongly", "red"),
    "UNKNOWN":     ("❓ Unknown",               "gray"),
}

ACTION_LABEL = {
    "HOLD":         ("🟢 HOLD",        "success"),
    "EXIT_SL":      ("🔴 EXIT — SL HIT","error"),
    "EXIT_TARGET":  ("🎯 EXIT — TARGET","success"),
    "EXIT_PATTERN": ("🟡 EXIT SIGNAL",  "warning"),
    "EXIT_PARTIAL": ("🟡 PARTIAL EXIT", "warning"),
    "EXIT_TIME":    ("🔴 EXIT — TIME",  "error"),
}

def is_market_open() -> tuple[bool, bool, bool]:
    """Returns (is_open, is_best_window, is_exit_only)"""
    now  = datetime.now()
    h, m = now.hour, now.minute
    is_open       = (h == 9 and m >= 15) or (9 < h < 15) or (h == 15 and m == 0)
    best_window   = (h == 9 and m >= 45) or (10 <= h <= 11) or (h == 11 and m <= 30)
    exit_only     = (h == 14 and m >= 30) or (h >= 15)
    return is_open, best_window, exit_only

# ══════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 📊 NSE Options Assistant")

    # Mode badge
    if LIVE_MODE:
        st.success("🟢 LIVE MODE — Kite Connect")
    else:
        st.warning("🟡 DEMO MODE — yfinance (~15 min delay)")
        st.caption("Add KITE_ACCESS_TOKEN to .env for live data")

    st.divider()

    # Beginner / Expert toggle
    st.session_state.beginner_mode = st.toggle(
        "🎓 Beginner mode (plain English)",
        value=st.session_state.beginner_mode,
        help="ON = simple language. OFF = technical terms.",
    )

    st.divider()

    # Market status
    is_open, best_window, exit_only = is_market_open()
    if is_open:
        if best_window:
            st.success("✅ Best time to trade\n9:45–11:30 AM window")
        elif exit_only:
            st.error("🛑 Exit only — no new entries\nAfter 2:30 PM")
        else:
            st.info("⏳ Market open\nBest window: 9:45–11:30 AM")
    else:
        st.warning("💤 Market closed\nOpens 9:15 AM IST Mon–Fri")

    st.caption(f"🕐 {datetime.now().strftime('%H:%M:%S IST')}")

    st.divider()

    # Kite login (demo mode only)
    if not LIVE_MODE:
        with st.expander("🔑 Connect Kite for live data"):
            api_key = os.getenv("KITE_API_KEY", "")
            if api_key:
                from kiteconnect import KiteConnect as _KC
                _k = _KC(api_key=api_key)
                st.markdown(f"[Step 1: Login to Kite →]({_k.login_url()})")
                req_token = st.text_input("Step 2: Paste request_token here")
                if st.button("Activate live mode") and req_token.strip():
                    try:
                        from kite_client import complete_login
                        token = complete_login(req_token.strip())
                        os.environ["KITE_ACCESS_TOKEN"] = token
                        env_path = Path(".env")
                        lines    = env_path.read_text().splitlines() if env_path.exists() else []
                        updated  = [f"KITE_ACCESS_TOKEN={token}" if l.startswith("KITE_ACCESS_TOKEN") else l for l in lines]
                        if not any(l.startswith("KITE_ACCESS_TOKEN") for l in lines):
                            updated.append(f"KITE_ACCESS_TOKEN={token}")
                        env_path.write_text("\n".join(updated))
                        st.success("✅ Live mode activated! Restart the app.")
                    except Exception as e:
                        st.error(f"Login failed: {e}")
            else:
                st.caption("Add KITE_API_KEY to .env first")

    st.divider()

    # Quick lot sizes reference
    with st.expander("📋 Lot sizes reference"):
        cats = instruments_by_category()
        for cat, syms in cats.items():
            st.caption(f"**{cat}**")
            for sym in syms[:6]:   # show first 6 per category
                st.caption(f"  {sym}: {LOT_SIZES[sym]}")

# ══════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════

tab1, tab2, tab_scanner, tab3 = st.tabs([
    "🔍 Phase 1 — Find Trade",
    "📡 Phase 2 — Monitor & Exit",
    "🔭 Market Scanner",
    "📒 My Journal",
])

# ══════════════════════════════════════════════════════════════════════════
# PHASE 1 — FIND TRADE
# ══════════════════════════════════════════════════════════════════════════

with tab1:

    # ── Beginner wizard header ─────────────────────────────────────────────
    if st.session_state.beginner_mode:
        st.subheader("Find your trade — 3 easy steps")
        step = st.session_state.wizard_step
        cols = st.columns(3)
        for i, lbl in enumerate(
            ["1️⃣ Pick instrument", "2️⃣ Check market", "3️⃣ Get recommendation"], 1
        ):
            done    = step > i
            current = step == i
            cols[i-1].markdown(
                f"{'✅' if done else ('▶️' if current else '⭕')} **{lbl}**"
            )
        st.divider()
    else:
        st.subheader("Find the right option to buy")

    if not LIVE_MODE:
        st.info("📊 Demo mode — real yfinance data, ~15 min delayed. Perfect for paper trading and strategy testing.")

    # ── Controls ───────────────────────────────────────────────────────────
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2, 2, 2, 1])

    # Instrument selector with category grouping
    cats  = instruments_by_category()
    cat_opts = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX",
                "──── Stock F&O ────"] + ALL_STOCKS_FO
    underlying = ctrl1.selectbox(
        "Instrument",
        cat_opts,
        index=cat_opts.index(st.session_state.underlying) if st.session_state.underlying in cat_opts else 0,
        help="Indices are most liquid. Stock options available too.",
        key="underlying_select",
    )
    if underlying == "──── Stock F&O ────":
        underlying = st.session_state.underlying

    budget   = ctrl2.number_input("Budget per lot (₹)", 2000, 20000, st.session_state.budget, step=500, key="budget_input")
    ctrl3.write("")
    ctrl3.write("")
    scan_btn = ctrl3.button("🔍 Scan live data", use_container_width=True, type="primary")

    ls   = LOT_SIZES.get(underlying, 75)
    step_val = ATM_STEPS.get(underlying, 50)
    ctrl4.metric("Lot size", f"{ls}")

    if scan_btn:
        with st.spinner(f"Fetching {underlying} data and news..."):
            try:
                snap      = get_index_snapshot(underlying)
                opts      = get_atm_options(underlying, budget)
                sentiment = get_news_sentiment(underlying)

                df_c  = get_candles_with_indicators(0, underlying=underlying)
                trend = get_trend_signal(df_c, sentiment.get("bias", "NEUTRAL")) if not df_c.empty else {}

                st.session_state.scan_snapshot  = snap
                st.session_state.scan_options   = opts
                st.session_state.scan_done      = True
                st.session_state.scan_trend     = trend
                st.session_state.scan_sentiment = sentiment
                st.session_state.underlying     = underlying
                st.session_state.budget         = budget
                st.session_state.wizard_step    = 2 if st.session_state.beginner_mode else 1
            except Exception as e:
                st.error(f"Data fetch error: {e}")

    # ── Scan results ───────────────────────────────────────────────────────
    if st.session_state.scan_done:
        snap      = st.session_state.scan_snapshot
        opts      = st.session_state.scan_options
        und       = st.session_state.underlying
        trend     = st.session_state.scan_trend
        sentiment = st.session_state.scan_sentiment

        # ── Index metrics ──────────────────────────────────────────────────
        m1, m2, m3, m4, m5 = st.columns(5)
        chg_color = "normal" if snap.get("change_pct", 0) >= 0 else "inverse"
        m1.metric(und,          f"₹{snap.get('ltp', 0):,.2f}",   f"{snap.get('change_pct', 0)}%", delta_color=chg_color)
        m2.metric("Day High",   f"₹{snap.get('high', 0):,.2f}")
        m3.metric("Day Low",    f"₹{snap.get('low', 0):,.2f}")
        m4.metric("Prev Close", f"₹{snap.get('prev_close', 0):,.2f}")
        m5.metric("Lot size",   f"{snap.get('lot_size', ls)}")
        st.caption(f"Data: {snap.get('data_source', '—')} | Strike step: ₹{snap.get('step', step_val)}")

        # ── News sentiment card ────────────────────────────────────────────
        bias        = sentiment.get("bias", "NEUTRAL")
        bias_icons  = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}
        bias_colors = {"BULLISH": "green", "BEARISH": "red", "NEUTRAL": "orange"}
        themes      = sentiment.get("key_themes", [])
        hint        = sentiment.get("trade_hint", "")
        conf        = sentiment.get("confidence", 50)

        with st.expander(f"📰 Today's market news — {bias_icons.get(bias, '🟡')} **{bias}** ({conf}% confidence)", expanded=True):
            if themes:
                st.caption("Key drivers: " + " · ".join(themes))
            if hint:
                st.info(f"💡 {hint}")
            headlines = fetch_pulse_headlines(6)
            for h in headlines:
                link = h.get("link", "")
                title = h["title"]
                if link:
                    st.caption(f"• [{title}]({link})")
                else:
                    st.caption(f"• {title}")

        # ── Trend summary ──────────────────────────────────────────────────
        if trend:
            if st.session_state.beginner_mode:
                t_label, t_color = TREND_LABEL.get(trend.get("trend", "UNKNOWN"), ("Unknown", "gray"))
                st.markdown(f"**Market direction:** :{t_color}[{t_label}]")
                st.caption(trend.get("plain_summary", ""))
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("RSI",       trend.get("rsi", "—"))
                rc2.metric("Confidence",f"{trend.get('confidence', 0)}%")
                rc3.metric("Price vs average", "Above avg" if trend.get("above_vwap") else "Below avg")
            else:
                tc1, tc2, tc3, tc4, tc5 = st.columns(5)
                tc1.metric("Trend",       trend.get("trend", "—"))
                tc2.metric("Confidence",  f"{trend.get('confidence', 0)}%")
                tc3.metric("RSI",         trend.get("rsi", "—"))
                tc4.metric("VWAP",        "Above" if trend.get("above_vwap") else "Below")
                tc5.metric("News bias",   trend.get("news_bias", "NEUTRAL"))

        # ── Warnings for illiquid instruments ─────────────────────────────
        if und == "FINNIFTY":
            st.warning("⚠️ FINNIFTY: yfinance data may be incomplete. If chart is empty, try NIFTY or BANKNIFTY.")
        elif und == "MIDCPNIFTY":
            st.warning("⚠️ MIDCPNIFTY: Less liquid — wider spreads. Use limit orders only.")
        elif und in ALL_STOCKS_FO:
            st.info(f"ℹ️ {und} ({ALL_CONFIGS[und].get('description', '')}). Stock options have wider spreads than index options.")

        # ── Options chain ──────────────────────────────────────────────────
        if opts:
            st.markdown("#### Available options within budget")
            df_opts = pd.DataFrame(opts)
            display_cols = ["strike", "type", "ltp", "oi", "volume", "lot_cost", "iv_pct", "dte"]
            display_cols = [c for c in display_cols if c in df_opts.columns]
            df_display   = df_opts[display_cols].copy()

            col_names = {
                "strike": "Strike", "type": "CE/PE", "ltp": "Premium ₹",
                "oi": "Open Interest", "volume": "Volume",
                "lot_cost": "Lot Cost ₹", "iv_pct": "IV %", "dte": "Days to Expiry",
            }
            df_display.columns = [col_names.get(c, c) for c in display_cols]

            atm_strike = round(snap.get("ltp", 0) / step_val) * step_val

            def _highlight_atm(row):
                if row.get("Strike", 0) == atm_strike:
                    return ["background-color: #1a3a1a; color: #90ee90"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_display.style.apply(_highlight_atm, axis=1),
                use_container_width=True,
                hide_index=True,
            )
            if st.session_state.beginner_mode:
                st.caption(
                    f"🟢 Highlighted row = ATM (at-the-money) strike = ₹{atm_strike:,.0f}. "
                    "Start here — it's the most responsive option to price moves. "
                    "CE = buy if you expect UP move. PE = buy if you expect DOWN move."
                )
            else:
                st.caption(f"Highlighted = ATM strike (₹{atm_strike:,.0f}). IV% = implied volatility. DTE = days to expiry.")
        else:
            st.warning("No options found within budget. Try increasing budget or selecting a different instrument.")

        # ── Candle chart ───────────────────────────────────────────────────
        st.markdown("#### 1-minute chart (last 60 candles)")
        try:
            df_c = get_candles_with_indicators(0, underlying=und)
            if not df_c.empty:
                last60 = df_c.tail(60)
                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=last60.index, open=last60["open"], high=last60["high"],
                    low=last60["low"],   close=last60["close"],
                    name="1 min", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
                ))
                if "EMA_9"  in last60.columns:
                    fig.add_trace(go.Scatter(x=last60.index, y=last60["EMA_9"],  name="EMA 9",  line=dict(color="orange",     width=1.5)))
                if "EMA_21" in last60.columns:
                    fig.add_trace(go.Scatter(x=last60.index, y=last60["EMA_21"], name="EMA 21", line=dict(color="royalblue",  width=1.5)))
                if "vwap"   in last60.columns:
                    fig.add_trace(go.Scatter(x=last60.index, y=last60["vwap"],   name="VWAP",   line=dict(color="magenta",    width=1.5, dash="dot")))
                fig.update_layout(
                    height=300, margin=dict(l=0, r=0, t=10, b=0),
                    xaxis_rangeslider_visible=False,
                    legend=dict(orientation="h", y=1.02),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig, use_container_width=True)
                if st.session_state.beginner_mode:
                    st.caption(
                        "📘 Orange line = short-term trend (EMA 9). "
                        "Blue line = medium-term trend (EMA 21). "
                        "Pink dotted = average price for today (VWAP). "
                        "Green candles = price went up. Red = price went down."
                    )
            else:
                st.warning(f"No chart data for {und}. Market may be closed or yfinance data unavailable.")
        except Exception as e:
            st.warning(f"Chart error: {e}")

    st.divider()

    # ── Phase 1 Chat ───────────────────────────────────────────────────────
    if st.session_state.beginner_mode:
        st.markdown("#### Step 3 — Ask for a trade recommendation")
    else:
        st.markdown("#### Ask Claude for trade analysis")

    # Quick-action buttons
    qc1, qc2, qc3, qc4 = st.columns(4)
    und_now = st.session_state.underlying
    ls_now  = LOT_SIZES.get(und_now, 75)

    if qc1.button("What should I buy?", use_container_width=True):
        msg = (f"I want to trade {und_now} options. Budget ₹{st.session_state.budget} per lot "
               f"(lot size = {ls_now} units). "
               f"{'Explain simply, no jargon.' if st.session_state.beginner_mode else 'Give full technical analysis.'} "
               "Which CE or PE should I buy right now?")
        st.session_state.phase1_msgs.append({"role": "user", "content": msg})
        st.session_state.wizard_step = 3
        st.rerun()

    if qc2.button("Is now a good time?", use_container_width=True):
        msg = f"Is this a good time to enter a trade on {und_now}? Consider market timing, trend, and news."
        st.session_state.phase1_msgs.append({"role": "user", "content": msg})
        st.rerun()

    if qc3.button("Best strike to pick?", use_container_width=True):
        msg = (f"Which strike price should I choose for {und_now}? "
               f"Budget ₹{st.session_state.budget}, lot size {ls_now}. "
               f"{'Explain ATM/OTM in simple terms.' if st.session_state.beginner_mode else 'Explain with Greeks and risk/reward.'}")
        st.session_state.phase1_msgs.append({"role": "user", "content": msg})
        st.rerun()

    if qc4.button("Explain the signals", use_container_width=True):
        t = st.session_state.scan_trend
        msg = (f"The current trend score is {t.get('score', 0)}, RSI is {t.get('rsi', '—')}, "
               f"price is {'above' if t.get('above_vwap') else 'below'} VWAP. "
               f"News is {st.session_state.scan_sentiment.get('bias', 'NEUTRAL')}. "
               f"{'Explain what this means in simple language for a beginner.' if st.session_state.beginner_mode else 'Give full technical interpretation.'}")
        st.session_state.phase1_msgs.append({"role": "user", "content": msg})
        st.rerun()

    # Chat history display
    for msg in st.session_state.phase1_msgs:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask anything about the trade... (e.g. 'is it safe to buy now?')"):
        st.session_state.phase1_msgs.append({"role": "user", "content": prompt})
        st.rerun()

    # ── Claude response ────────────────────────────────────────────────────
    if st.session_state.phase1_msgs and st.session_state.phase1_msgs[-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Analysing..."):
                und_now   = st.session_state.underlying
                snap_now  = st.session_state.scan_snapshot
                opts_now  = st.session_state.scan_options
                trend_now = st.session_state.scan_trend
                sent_now  = st.session_state.scan_sentiment

                # Compact context (saves tokens vs full JSON dump)
                ctx_lines = [
                    f"Mode: {'DEMO' if not LIVE_MODE else 'LIVE'}",
                    f"Instrument: {und_now} | Lot: {LOT_SIZES.get(und_now, 75)} | Step: ₹{ATM_STEPS.get(und_now, 50)}",
                    f"Budget: ₹{st.session_state.budget}",
                    f"Price: ₹{snap_now.get('ltp', 0):,.2f} | Change: {snap_now.get('change_pct', 0)}% | Dir: {snap_now.get('direction', '—')}",
                    f"High: ₹{snap_now.get('high', 0):,.2f} | Low: ₹{snap_now.get('low', 0):,.2f} | Prev: ₹{snap_now.get('prev_close', 0):,.2f}",
                    f"Trend: {trend_now.get('trend', '—')} | Score: {trend_now.get('score', 0)} | Confidence: {trend_now.get('confidence', 0)}%",
                    f"RSI: {trend_now.get('rsi', '—')} | VWAP: {'Above' if trend_now.get('above_vwap') else 'Below'} | EMA: {'Bullish' if trend_now.get('ema_bullish') else 'Bearish'}",
                    f"News: {sent_now.get('bias', 'NEUTRAL')} | Themes: {', '.join(sent_now.get('key_themes', []))}",
                    f"News hint: {sent_now.get('trade_hint', '—')}",
                    f"Time IST: {datetime.now().strftime('%H:%M')} {datetime.now().strftime('%A %d %b %Y')}",
                ]
                # Top 8 options (trim to save tokens)
                if opts_now:
                    ctx_lines.append("Top options (strike|type|premium|lot_cost|iv|dte):")
                    for o in opts_now[:8]:
                        ctx_lines.append(
                            f"  {o['strike']}|{o['type']}|₹{o['ltp']}|₹{o['lot_cost']}|{o.get('iv_pct','—')}%|{o.get('dte','—')}d"
                        )

                ctx_str = "\n".join(ctx_lines)

                mode_note = (
                    "User is BEGINNER — use simple language, avoid jargon, explain every term."
                    if st.session_state.beginner_mode
                    else "User is EXPERT — use technical language."
                )

                system = f"""You are an expert NSE intraday options trading assistant for Indian retail traders.
{mode_note}

{SKILLS}

Market context:
{ctx_str}

Rules:
- Suggest specific: instrument + CE or PE + strike + entry range + stop loss ₹ + target ₹
- Show: lot cost = premium × lot_size, total investment for N lots
- Warn if time is outside 9:45–14:30 IST
- For stock options: warn about liquidity, use limit orders
- If DEMO mode: mention data is delayed but analysis method is same
- End EVERY response with: "⚠️ Educational only — not financial advice. Always use stop loss."
- Keep response under 350 words."""

                reply = ask_claude_sonnet(system, [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.phase1_msgs
                ])
                st.markdown(reply)
                st.session_state.phase1_msgs.append({"role": "assistant", "content": reply})
                st.rerun()

    # ── Trade entry form ───────────────────────────────────────────────────
    st.divider()
    if st.session_state.beginner_mode:
        st.markdown("#### After you buy on Kite — enter your trade details here")
        st.caption("Once you've placed the order on Kite app, enter the details below to start Phase 2 live monitoring.")
    else:
        st.markdown("#### Confirm trade entry → Start Phase 2")

    with st.form("trade_entry_form", clear_on_submit=False):
        fc1, fc2, fc3 = st.columns(3)

        cat_opts2 = ALL_INDICES + ["── Stock F&O ──"] + ALL_STOCKS_FO
        und_entry = fc1.selectbox("Instrument", cat_opts2,
                                   index=cat_opts2.index(st.session_state.underlying)
                                   if st.session_state.underlying in cat_opts2 else 0,
                                   key="trade_und")
        if und_entry == "── Stock F&O ──":
            und_entry = st.session_state.underlying

        sym      = fc1.text_input("Symbol (optional)", placeholder="NIFTY25JAN2524500CE")
        otype    = fc2.selectbox("CE or PE?",
                                  ["CE", "PE"],
                                  help="CE = Call (buy when market goes UP)\nPE = Put (buy when market goes DOWN)")
        ls_entry = LOT_SIZES.get(und_entry, 75)
        strike   = fc2.number_input("Strike price", value=float(round(
                                        st.session_state.scan_snapshot.get("ltp", 24500) /
                                        ATM_STEPS.get(und_entry, 50)) *
                                        ATM_STEPS.get(und_entry, 50)),
                                     step=float(ATM_STEPS.get(und_entry, 50)))
        eprice   = fc3.number_input("Entry premium ₹ (what you paid per unit)", value=80.0, step=0.5, min_value=0.5)
        lots     = fc3.number_input("Number of lots", value=1, min_value=1, max_value=20)
        tgt      = fc3.number_input("Target %", value=30, min_value=5,  max_value=200,
                                     help="Exit when profit reaches this %")
        sl       = fc3.number_input("Stop loss %", value=20, min_value=5, max_value=80,
                                     help="Exit when loss reaches this %")

        lot_cost_display = round(eprice * ls_entry, 0)
        total_investment = round(lot_cost_display * lots, 0)
        target_price     = round(eprice * (1 + tgt / 100), 2)
        sl_price         = round(eprice * (1 - sl / 100), 2)

        st.info(
            f"**Summary:** {lots} lot(s) × ₹{eprice} × {ls_entry} units = "
            f"**₹{total_investment:,.0f} total** | "
            f"Target: ₹{target_price} | Stop loss: ₹{sl_price}"
        )

        submitted = st.form_submit_button("▶️ Start Phase 2 Monitoring", use_container_width=True, type="primary")
        if submitted and eprice > 0:
            st.session_state.active_trade = ActiveTrade(
                symbol=sym or f"{und_entry}{otype}{int(strike)}",
                instrument_token=0,
                underlying=und_entry,
                option_type=otype,
                strike=strike,
                entry_price=eprice,
                lot_size=ls_entry,
                lots=lots,
                entry_time=datetime.now().strftime("%H:%M"),
                target_pct=float(tgt),
                sl_pct=float(sl),
                is_active=True,
                news_bias=st.session_state.scan_sentiment.get("bias", "NEUTRAL"),
            )
            st.session_state.monitor_on   = True
            st.session_state.phase2_msgs  = []
            st.session_state.last_refresh = time.time()
            st.success(f"✅ Monitoring started! Switch to Phase 2 tab →")

# ══════════════════════════════════════════════════════════════════════════
# PHASE 2 — MONITOR & EXIT
# ══════════════════════════════════════════════════════════════════════════

with tab2:
    trade = st.session_state.active_trade

    if not trade.is_active:
        st.info("No active trade. Go to Phase 1 → fill in trade entry form → click 'Start Phase 2 Monitoring'.")
        st.stop()

    st.subheader(f"Monitoring: {trade.symbol}")
    st.caption(
        f"Entry: ₹{trade.entry_price} | {trade.underlying} {trade.option_type} {trade.strike} | "
        f"{trade.lots} lot(s) × {trade.lot_size} units | "
        f"Entered: {trade.entry_time} | Target: +{trade.target_pct}% | SL: -{trade.sl_pct}%"
    )

    # ── Fetch live data ────────────────────────────────────────────────────
    df     = pd.DataFrame()
    trend  = {}
    exit_s = {}
    ltp    = trade.entry_price
    pnl    = 0.0
    pnl_rs = 0.0

    try:
        if LIVE_MODE:
            df = get_candles_with_indicators(trade.instrument_token)
        else:
            df = get_candles_with_indicators(0, underlying=trade.underlying)
            if not df.empty:
                idx_chg = (df.iloc[-1]["close"] - df.iloc[0]["close"]) / df.iloc[0]["close"]
                mult    = 5 if trade.option_type == "CE" else -5
                ltp     = round(max(trade.entry_price * (1 + idx_chg * mult), 0.5), 1)

        if not df.empty:
            trend  = get_trend_signal(df, trade.news_bias)
            exit_s = get_exit_signal(df, trade.entry_price, trade.target_pct, trade.sl_pct, trade.option_type)
            if exit_s.get("ltp"):
                ltp = exit_s["ltp"]
            pnl    = round((ltp - trade.entry_price) / trade.entry_price * 100, 2)
            pnl_rs = round((ltp - trade.entry_price) * trade.lot_size * trade.lots, 2)

    except Exception as e:
        st.warning(f"Data error: {e}")

    # ── Live P&L metrics ───────────────────────────────────────────────────
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Entry",      f"₹{trade.entry_price}")
    m2.metric("Current",    f"₹{ltp}",    f"{pnl:+.1f}%", delta_color="normal")
    m3.metric("P&L",        f"₹{pnl_rs:+,.0f}", delta_color="normal")
    m4.metric("Target",     f"₹{round(trade.entry_price * (1 + trade.target_pct / 100), 1)}")
    m5.metric("Stop loss",  f"₹{round(trade.entry_price * (1 - trade.sl_pct  / 100), 1)}")
    m6.metric("Trend",      trend.get("trend", "—") if not st.session_state.beginner_mode
              else TREND_LABEL.get(trend.get("trend", "UNKNOWN"), ("—", "gray"))[0])

    # ── Exit signal banner ─────────────────────────────────────────────────
    action   = exit_s.get("action", "HOLD")
    a_label, a_style = ACTION_LABEL.get(action, ("🟢 HOLD", "success"))

    display_text = (
        f"{a_label} — {exit_s.get('plain', exit_s.get('reason', ''))}"
        if st.session_state.beginner_mode
        else f"{a_label} — {exit_s.get('reason', 'Monitoring...')}"
    )

    if a_style == "error":
        st.error(display_text)
    elif a_style == "warning":
        st.warning(display_text)
    else:
        st.success(display_text)

    # ── Chart ──────────────────────────────────────────────────────────────
    if not df.empty:
        last45 = df.tail(45)
        fig2   = go.Figure()
        fig2.add_trace(go.Candlestick(
            x=last45.index, open=last45["open"], high=last45["high"],
            low=last45["low"],   close=last45["close"],
            name="1 min",
            increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        ))
        for col, name, color, dash in [
            ("EMA_9",  "EMA 9",  "orange",    "solid"),
            ("EMA_21", "EMA 21", "royalblue", "solid"),
            ("vwap",   "VWAP",   "magenta",   "dot"),
        ]:
            if col in last45.columns:
                fig2.add_trace(go.Scatter(x=last45.index, y=last45[col], name=name,
                                          line=dict(color=color, width=1.5, dash=dash)))

        # Entry / target / SL lines
        fig2.add_hline(y=trade.entry_price,
                       line_dash="dash", line_color="yellow",
                       annotation_text=f"Entry ₹{trade.entry_price}")
        fig2.add_hline(y=trade.entry_price * (1 + trade.target_pct / 100),
                       line_dash="dot", line_color="lime",
                       annotation_text=f"Target +{trade.target_pct}%")
        fig2.add_hline(y=trade.entry_price * (1 - trade.sl_pct / 100),
                       line_dash="dot", line_color="red",
                       annotation_text=f"SL -{trade.sl_pct}%")

        fig2.update_layout(
            height=340, margin=dict(l=0, r=0, t=10, b=0),
            xaxis_rangeslider_visible=False,
            legend=dict(orientation="h", y=1.02),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig2, use_container_width=True)

        # Last 5 candles table
        pattern_cols = [c for c in [
            "open", "high", "low", "close",
            "is_bullish", "is_doji", "is_engulfing_bull", "is_engulfing_bear",
            "is_pinbar_bull", "is_pinbar_bear", "above_vwap",
        ] if c in df.columns]

        if st.session_state.beginner_mode:
            st.markdown("**Last 5 candles:**")
            last5 = df.tail(5)[["open", "high", "low", "close", "is_bullish", "above_vwap"]].copy()
            last5.columns = ["Open", "High", "Low", "Close", "Green candle?", "Above avg?"]
            last5.index = last5.index.strftime("%H:%M")
            st.dataframe(last5, use_container_width=True)
        else:
            st.markdown("**Last 5 candles (technical):**")
            last5 = df.tail(5)[pattern_cols].copy()
            last5.index = last5.index.strftime("%H:%M")
            st.dataframe(last5, use_container_width=True)

    st.divider()

    # ── Phase 2 Chat ───────────────────────────────────────────────────────
    st.markdown("#### Ask Claude for exit guidance")

    qa1, qa2, qa3, qa4 = st.columns(4)
    if qa1.button("Should I exit now?", use_container_width=True):
        st.session_state.phase2_msgs.append({
            "role": "user",
            "content": f"Should I exit this trade? I'm at {pnl:.1f}% P&L (₹{pnl_rs:+,.0f}). "
                       f"{'Explain simply.' if st.session_state.beginner_mode else 'Full technical analysis.'}",
        })
        st.rerun()
    if qa2.button("How to trail SL?", use_container_width=True):
        st.session_state.phase2_msgs.append({
            "role": "user",
            "content": f"I'm at {pnl:.1f}% profit. How should I trail my stop loss? "
                       f"Entry ₹{trade.entry_price}, current ₹{ltp}.",
        })
        st.rerun()
    if qa3.button("What pattern is forming?", use_container_width=True):
        st.session_state.phase2_msgs.append({
            "role": "user",
            "content": "What candle pattern is forming in the last 5 candles? What does it mean for my trade?",
        })
        st.rerun()
    if qa4.button("Explain current signals", use_container_width=True):
        st.session_state.phase2_msgs.append({
            "role": "user",
            "content": f"RSI is {trend.get('rsi', '—')}, trend is {trend.get('trend', '—')}, "
                       f"news was {trade.news_bias} at entry. What does this mean for my {trade.option_type}?",
        })
        st.rerun()

    for msg in st.session_state.phase2_msgs:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if p2 := st.chat_input("Ask: hold or exit? trail SL? what's forming?"):
        st.session_state.phase2_msgs.append({"role": "user", "content": p2})
        st.rerun()

    if st.session_state.phase2_msgs and st.session_state.phase2_msgs[-1]["role"] == "user":
        with st.chat_message("assistant"):
            with st.spinner("Analysing trade..."):

                last5_dict = {}
                if not df.empty and pattern_cols:
                    last5_dict = df.tail(5)[pattern_cols].to_dict()

                ctx2_lines = [
                    f"Mode: {'DEMO' if not LIVE_MODE else 'LIVE'}",
                    f"Trade: {trade.underlying} {trade.option_type} {trade.strike}",
                    f"Lot: {trade.lot_size} × {trade.lots} lots",
                    f"Entry: ₹{trade.entry_price} | LTP: ₹{ltp} | P&L: {pnl:+.1f}% (₹{pnl_rs:+,.0f})",
                    f"Target: +{trade.target_pct}% | SL: -{trade.sl_pct}%",
                    f"Entry time: {trade.entry_time} | Now: {datetime.now().strftime('%H:%M')}",
                    f"Trend: {trend.get('trend', '—')} | RSI: {trend.get('rsi', '—')} | VWAP: {'Above' if trend.get('above_vwap') else 'Below'}",
                    f"Exit signal: {exit_s.get('action', 'HOLD')} — {exit_s.get('reason', '—')}",
                    f"News bias at entry: {trade.news_bias}",
                ]
                ctx2_str = "\n".join(ctx2_lines)

                mode_note2 = (
                    "User is BEGINNER — plain English only, no jargon."
                    if st.session_state.beginner_mode
                    else "User is EXPERT — full technical analysis."
                )

                system2 = f"""You are an expert intraday options exit advisor for NSE markets.
{mode_note2}

Live trade:
{ctx2_str}

Rules:
- Give ONE clear action: HOLD / EXIT NOW / TRAIL SL TO ₹XX
- Show ₹ impact of recommendation
- Capital preservation first — user has small capital (₹2000–10000 per lot)
- If exit signal is EXIT_SL or EXIT_TIME, be firm: exit immediately
- Keep response under 250 words
- End with: ACTION: [HOLD / EXIT NOW / TRAIL SL TO ₹XX]"""

                reply2 = ask_claude_sonnet(system2, [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.phase2_msgs
                ])
                st.markdown(reply2)
                st.session_state.phase2_msgs.append({"role": "assistant", "content": reply2})
                st.rerun()

    st.divider()

    # ── Close trade / auto-refresh ─────────────────────────────────────────
    col_close, col_status = st.columns([1, 3])

    if col_close.button("✅ Close & save trade", type="primary", use_container_width=True):
        save_trade(trade, ltp, action, pnl, pnl_rs)
        st.session_state.active_trade = ActiveTrade()
        st.session_state.monitor_on   = False
        st.session_state.phase2_msgs  = []
        st.success("Trade saved to journal! View it in the 📒 My Journal tab.")
        st.rerun()

    # Non-blocking auto-refresh every 60 seconds
    if st.session_state.monitor_on:
        now_ts  = time.time()
        elapsed = int(now_ts - st.session_state.get("last_refresh", now_ts))
        remaining = max(60 - elapsed, 0)
        col_status.caption(f"🔄 Auto-refresh in {remaining}s  |  Last updated: {datetime.now().strftime('%H:%M:%S')}")
        if elapsed >= 60:
            st.session_state.last_refresh = now_ts
            st.rerun()
        else:
            time.sleep(1)
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════
# MARKET SCANNER
# ══════════════════════════════════════════════════════════════════════════

with tab_scanner:
    st.subheader("🔭 Market Scanner — Let Claude pick today's best trade")

    if st.session_state.beginner_mode:
        st.caption(
            "Select a group of stocks/indices below, click Scan, and Claude will "
            "analyse all of them and tell you which single one is best to trade today."
        )
    else:
        st.caption("Multi-instrument technical + news scan. Claude ranks and picks the strongest setup.")

    sc1, sc2, sc3 = st.columns([3, 2, 1])

    basket_name = sc1.selectbox(
        "Scan basket",
        list(BASKETS.keys()),
        index=list(BASKETS.keys()).index(st.session_state.scanner_basket)
              if st.session_state.scanner_basket in BASKETS else 0,
        key="basket_select",
    )
    st.session_state.scanner_basket = basket_name

    if basket_name == "🎯 Custom":
        basket_instruments = sc1.multiselect(
            "Pick instruments",
            ALL_INDICES + ALL_STOCKS_FO,
            default=["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK"],
            key="custom_basket",
        )
    else:
        basket_instruments = BASKETS[basket_name]
        sc1.caption("Scanning: " + ", ".join(basket_instruments))

    scan_budget = sc2.number_input(
        "Budget per lot (Rs)", 2000, 20000,
        st.session_state.scanner_budget, step=500,
        key="scanner_budget_input",
    )
    st.session_state.scanner_budget = scan_budget

    sc3.write("")
    sc3.write("")
    run_scan = sc3.button("🔭 Scan all", use_container_width=True, type="primary")

    if run_scan and basket_instruments:
        sentiment = get_news_sentiment("NIFTY")
        news_bias = sentiment.get("bias", "NEUTRAL")
        results   = []
        progress  = st.progress(0, text="Scanning instruments...")
        total     = len(basket_instruments)

        from scanner_engine import score_instrument
        for i, sym in enumerate(basket_instruments):
            progress.progress((i + 1) / total, text=f"Scanning {sym}...")
            r = score_instrument(sym, scan_budget, news_bias)
            if r:
                results.append(r)

        progress.empty()
        results.sort(key=lambda x: (not x.get("affordable", False), -abs(x["score"])))
        st.session_state.scanner_results = results
        st.session_state.scanner_done    = True
        st.session_state.scanner_pick    = ""

    # ── Results table ──────────────────────────────────────────────────────
    if st.session_state.scanner_done and st.session_state.scanner_results:
        results = st.session_state.scanner_results

        st.markdown("#### Scan results")

        rows = []
        for r in results:
            signal = "🟢" if r["score"] >= 2 else ("🔴" if r["score"] <= -2 else "🟡")
            rows.append({
                "":           signal,
                "Instrument": r["underlying"],
                "Category":   r.get("category", ""),
                "Price":      f"Rs{r['ltp']:,.2f}",
                "Change":     f"{r['change_pct']:+.2f}%",
                "Score":      r["score"],
                "Direction":  r["direction"].replace("STRONG_", "S."),
                "RSI":        r["rsi"],
                "VWAP":       "Y" if r["above_vwap"]  else "N",
                "EMA":        "Y" if r["ema_bullish"] else "N",
                "Trade":      r["opt_type"],
                "Strike":     f"{r['atm_strike']:,.0f}",
                "Premium":    r["atm_premium"],
                "Lot cost":   f"Rs{r['lot_cost']:,.0f}",
                "Budget OK":  "Y" if r["affordable"] else "N",
            })

        df_scan = pd.DataFrame(rows)

        # Find best affordable row index
        best_idx = next(
            (i for i, r in enumerate(results) if r.get("affordable")), None
        )

        def _color_scan_row(row):
            try:
                idx = df_scan.index[df_scan["Instrument"] == row["Instrument"]].tolist()
                if idx and idx[0] == best_idx:
                    return ["background-color: #0d2b0d"] * len(row)
                score_val = next(
                    (r["score"] for r in results if r["underlying"] == row["Instrument"]), 0
                )
                if score_val >= 3:
                    return ["color: #26a69a"] * len(row)
                if score_val <= -3:
                    return ["color: #ef5350"] * len(row)
            except Exception:
                pass
            return [""] * len(row)

        st.dataframe(
            df_scan.style.apply(_color_scan_row, axis=1),
            use_container_width=True,
            hide_index=True,
        )

        if st.session_state.beginner_mode:
            st.caption(
                "Highlighted row = strongest affordable signal. "
                "Score > 0 = buy CE (market going up). Score < 0 = buy PE (going down). "
                "Score near 0 = no clear direction, skip it."
            )

        st.divider()

        affordable_count = sum(1 for r in results if r.get("affordable"))
        st.caption(
            f"{len(results)} instruments scanned · "
            f"{affordable_count} within Rs{scan_budget:,} budget"
        )

        if st.button(
            "🤖 Ask Claude: which is the single best trade right now?",
            use_container_width=True,
            type="primary",
            key="claude_pick_btn",
        ):
            sentiment = get_news_sentiment("NIFTY")
            with st.spinner("Claude is comparing all signals and picking the best trade..."):
                pick = claude_pick_best(
                    scan_results=results,
                    budget=scan_budget,
                    news_bias=sentiment.get("bias", "NEUTRAL"),
                    news_themes=sentiment.get("key_themes", []),
                    news_hint=sentiment.get("trade_hint", ""),
                    beginner_mode=st.session_state.beginner_mode,
                )
            st.session_state.scanner_pick = pick

        # ── Claude's answer ────────────────────────────────────────────────
        if st.session_state.scanner_pick:
            st.markdown("#### Claude's recommendation")
            st.success(st.session_state.scanner_pick)

            st.divider()

            import re
            match = re.search(
                r"Best trade:\s*\*{0,2}([A-Z0-9&.\-]+)\s+(CE|PE)\*{0,2}",
                st.session_state.scanner_pick,
            )
            if match:
                sym_pick  = match.group(1).strip()
                type_pick = match.group(2).strip()
                if sym_pick in ALL_CONFIGS:
                    if st.button(
                        f"Go to Phase 1 with {sym_pick} {type_pick}",
                        type="primary",
                        key="load_pick_btn",
                    ):
                        st.session_state.underlying  = sym_pick
                        st.session_state.scan_done   = False
                        st.session_state.wizard_step = 1
                        st.success(
                            f"Switched to {sym_pick}. "
                            "Now go to Phase 1 tab, click Scan, then fill the trade entry form."
                        )


# ══════════════════════════════════════════════════════════════════════════
# PHASE 3 — TRADE JOURNAL
# ══════════════════════════════════════════════════════════════════════════

with tab3:
    st.subheader("📒 My Trade Journal")

    stats = get_journal_stats()
    journal = load_journal()

    if stats["total"] == 0:
        st.info("No trades recorded yet. Complete a trade in Phase 2 and click 'Close & save trade'.")
    else:
        # Summary stats
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Total trades",  stats["total"])
        sc2.metric("Win rate",      f"{stats['win_rate']}%",
                   f"{stats['wins']}W / {stats['losses']}L")
        pnl_color = "normal" if stats["total_pnl"] >= 0 else "inverse"
        sc3.metric("Total P&L",     f"₹{stats['total_pnl']:+,.0f}", delta_color=pnl_color)
        sc4.metric("Avg win",       f"₹{stats['avg_win']:,.0f}")
        sc5.metric("Avg loss",      f"₹{stats['avg_loss']:,.0f}")

        if st.session_state.beginner_mode and stats["total"] >= 3:
            # Plain-English summary from journal
            win_rate = stats["win_rate"]
            total_pnl = stats["total_pnl"]
            if win_rate >= 60 and total_pnl > 0:
                st.success(f"✅ Great performance! You're winning {win_rate}% of trades and up ₹{total_pnl:,.0f} overall.")
            elif win_rate >= 40:
                st.info(f"📊 Decent performance. Win rate {win_rate}%. Keep using stop losses consistently.")
            else:
                st.warning(f"⚠️ Win rate is {win_rate}% — below 50%. Review your entry timing and stick to the 9:45–11:30 AM window.")

        st.divider()

        # Journal table
        df_j = pd.DataFrame(journal[::-1])   # newest first
        if not df_j.empty:
            display_j = df_j[[c for c in [
                "date", "time_entry", "time_exit", "underlying", "type",
                "strike", "entry", "exit", "lots", "pnl_pct", "pnl_rs",
                "exit_reason", "result",
            ] if c in df_j.columns]].copy()

            col_rename = {
                "date": "Date", "time_entry": "Entry time", "time_exit": "Exit time",
                "underlying": "Instrument", "type": "CE/PE", "strike": "Strike",
                "entry": "Entry ₹", "exit": "Exit ₹", "lots": "Lots",
                "pnl_pct": "P&L %", "pnl_rs": "P&L ₹",
                "exit_reason": "Exit reason", "result": "Result",
            }
            display_j.columns = [col_rename.get(c, c) for c in display_j.columns]

            def _color_result(row):
                if row.get("Result") == "WIN":
                    return ["color: #26a69a"] * len(row)
                elif row.get("Result") == "LOSS":
                    return ["color: #ef5350"] * len(row)
                return [""] * len(row)

            st.dataframe(
                display_j.style.apply(_color_result, axis=1),
                use_container_width=True,
                hide_index=True,
            )

        # Export button
        if st.button("⬇️ Download journal as CSV"):
            csv = pd.DataFrame(journal).to_csv(index=False)
            st.download_button(
                label="Download trade_journal.csv",
                data=csv,
                file_name="trade_journal.csv",
                mime="text/csv",
            )