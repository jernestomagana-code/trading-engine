from fastapi import FastAPI
import yfinance as yf
import pandas as pd
import numpy as np

app = FastAPI()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

@app.get("/")
def read_root():
    return {"message": "Trading Engine activo con datos reales"}

@app.get("/get_trade_context")
def get_trade_context(ticker: str):
    ticker = ticker.upper()

    data = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
    vix_data = yf.download("^VIX", period="5d", interval="1d", progress=False, auto_adjust=True)

    close = data["Close"]
    volume = data["Volume"]

    price = float(close.iloc[-1])
    ema20 = float(close.ewm(span=20).mean().iloc[-1])
    ema50 = float(close.ewm(span=50).mean().iloc[-1])
    ema200 = float(close.ewm(span=200).mean().iloc[-1])
    rsi14 = float(rsi(close).iloc[-1])

    vol_rel = float(volume.iloc[-1] / volume.rolling(20).mean().iloc[-1])
    vix = float(vix_data["Close"].iloc[-1])

    returns = close.pct_change()
    hv_30 = float(returns.rolling(30).std().iloc[-1] * np.sqrt(252) * 100)

    if price > ema20 > ema50:
        trend = "bullish"
    elif price < ema20 < ema50:
        trend = "bearish"
    else:
        trend = "neutral"

    return {
        "ticker": ticker,
        "price": round(price, 2),
        "rsi14": round(rsi14, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "trend": trend,
        "volume_relative": round(vol_rel, 2),
        "vix": round(vix, 2),
        "historical_volatility_30d": round(hv_30, 2),
        "flow": "pending_unusual_whales",
        "gamma": "pending_unusual_whales",
        "put_wall": None,
        "call_wall": None,
        "iv_rank": None
    }
