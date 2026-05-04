from fastapi import FastAPI, Request
from datetime import datetime, timezone

app = FastAPI()

trade_store = {}

@app.get("/")
def read_root():
    return {"message": "Trading Engine activo - TradingView webhook mode"}

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    data = await request.json()

    ticker = str(data.get("ticker", "")).upper().strip()

    if not ticker:
        return {"status": "error", "message": "ticker is required"}

    data["ticker"] = ticker
    data["received_at"] = datetime.now(timezone.utc).isoformat()
    data["source"] = "tradingview"

    trade_store[ticker] = data

    return {
        "status": "ok",
        "message": f"Data received for {ticker}",
        "data": data
    }

@app.get("/get_trade_context")
def get_trade_context(ticker: str):
    ticker = ticker.upper().strip()

    if ticker not in trade_store:
        return {
            "ticker": ticker,
            "status": "missing_data",
            "message": "No TradingView data received yet for this ticker"
        }

    return trade_store[ticker]
