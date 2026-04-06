# 📈 AI Options Trading Assistant (Streamlit + Claude)

A beginner-friendly, AI-powered stock market trading assistant built with **Python + Streamlit**, designed for **NSE F&O trading**.

This project combines **technical indicators, news sentiment (Claude AI), and guided UX** to help users **find, monitor, and exit trades** with confidence.

---

## 🚀 Features

### 🧭 Guided User Experience
- Beginner-friendly **step-by-step wizard**
- Plain English explanations (no jargon)
- Traffic-light style signals (Buy / Wait / Exit)

---

### 🔍 Phase 1 — Find Trades
- Market scan across **indices + F&O stocks**
- AI-powered **news sentiment analysis (Claude Haiku)**
- Smart **strike selection guidance**
- Signal scoring using:
  - Trend
  - RSI
  - MACD
  - VWAP
  - OI buildup
  - PCR ratio
  - IV percentile

---

### 📊 Phase 2 — Monitor & Exit
- Live P&L tracking
- Pattern-based exit signals (CE vs PE aware)
- Auto **Stop-Loss trailing logic**
- Exit countdown + capital protection rules

---

### 🧠 AI Integration (Claude)
- **Claude Haiku** → Fast, low-cost news sentiment
- **Claude Sonnet** → Deep trade reasoning (capped tokens)
- Optimized token usage:
  - Compact prompts (no JSON dumps)
  - Last 6 messages only
  - Cached responses (10–15 min)

---

### 🧪 Demo Mode (No Broker Required)
- Uses **yfinance**
- Black-Scholes IV simulation
- Works across all instruments
- Safe environment for testing strategies

---

### ⚡ Live Mode (Zerodha Kite)
- WebSocket live ticks
- Real OI / IV data
- Full NFO option chain support

---

### 📰 News Sentiment Engine
- Source: Pulse RSS (Zerodha)
- AI sentiment classification (Bullish / Bearish / Neutral)
- Cached to reduce API costs

---

### 📓 Trade Journal
- SQLite-backed logging
- Tracks:
  - Win rate
  - P&L history
  - Trade performance
- Helps improve strategy over time

---

### 🌍 Market Context
- Expiry calendar
- PCR trends
- VIX insights
- Global cues

---

## 🗂️ Project Structure


├── app.py # Main Streamlit app
├── fo_universe.py # Instruments (indices + 30 stocks, lot sizes, tickers)
├── demo_engine.py # Simulated trading engine (yfinance + Black-Scholes)
├── data_engine.py # Live trading engine (Kite API)
├── signal_engine.py # Signal scoring + exit logic + summaries
├── news_engine.py # RSS + Claude sentiment analysis
├── state.py # Trade state + journal tracking
├── kite_client.py # Zerodha Kite integration
├── requirements.txt # Dependencies



---

## ⚙️ Installation

```bash
pip install -r requirements.txt
```
## ⚙️ RUN Project

```bash
streamlit run app.py

