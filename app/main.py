from fastapi import FastAPI
import yfinance as yf
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
    try:
        ticker = ticker.upper().strip()

        data = yf.download(
            ticker,
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        vix_data = yf.download(
            "^VIX",
            period="5d",
            interval="1d",
            progress=False,
            auto_adjust=True
        )

        if data.empty:
            return {
                "ticker": ticker,
                "error": f"No data returned for {ticker}"
            }

        close = data["Close"]
        volume = data["Volume"]

        price = float(close.iloc[-1])
        ema20 = float(close.ewm(span=20).mean().iloc[-1])
        ema50 = float(close.ewm(span=50).mean().iloc[-1])
        ema200 = float(close.ewm(span=200).mean().iloc[-1])

        rsi_series = rsi(close)
        rsi14 = float(rsi_series.dropna().iloc[-1]) if not rsi_series.dropna().empty else None

        vol_rel = None
        if len(volume) > 20:
            avg_volume_20 = volume.rolling(20).mean().iloc[-1]
            if avg_volume_20 and float(avg_volume_20) != 0:
                vol_rel = float(volume.iloc[-1] / avg_volume_20)

        vix = None
        if not vix_data.empty:
            vix = float(vix_data["Close"].iloc[-1])

        returns = close.pct_change()
        hv_series = returns.rolling(30).std()
        hv_30 = None
        if not hv_series.dropna().empty:
            hv_30 = float(hv_series.dropna().iloc[-1] * np.sqrt(252) * 100)

        if price > ema20 > ema50:
            trend = "bullish"
        elif price < ema20 < ema50:
            trend = "bearish"
        else:
            trend = "neutral"

        return {
            "ticker": ticker,
            "price": round(price, 2),
            "rsi14": round(rsi14, 2) if rsi14 is not None else None,
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
            "trend": trend,
            "volume_relative": round(vol_rel, 2) if vol_rel is not None else None,
            "vix": round(vix, 2) if vix is not None else None,
            "historical_volatility_30d": round(hv_30, 2) if hv_30 is not None else None,
            "flow": "pending_unusual_whales",
            "gamma": "pending_unusual_whales",
            "put_wall": None,
            "call_wall": None,
            "iv_rank": None
        }

    except Exception as e:
        return {
            "ticker": ticker if "ticker" in locals() else None,
            "error": str(e)
        }
