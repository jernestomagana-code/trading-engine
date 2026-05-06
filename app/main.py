from fastapi import FastAPI, Request
from datetime import datetime, timezone
import json
import re

app = FastAPI()

trade_store = {}

def extract_json_from_text(text: str):
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass

    return None

def find_ticker(data, raw_text):
    if isinstance(data, dict):
        ticker = data.get("ticker") or data.get("symbol") or data.get("tickerid")
        if ticker:
            return str(ticker).upper().strip()

        message = data.get("message")
        if isinstance(message, str):
            nested = extract_json_from_text(message)
            if isinstance(nested, dict):
                nested_ticker = nested.get("ticker") or nested.get("symbol") or nested.get("tickerid")
                if nested_ticker:
                    return str(nested_ticker).upper().strip()

    match = re.search(r'"ticker"\s*:\s*"([^"]+)"', raw_text)
    if match:
        return match.group(1).upper().strip()

    match = re.search(r'\b(USTEC\.F|SPY|QQQ|TLT|MNQ|NQ|ES|SPX|NFLX|MSFT|NVDA|META|AAPL)\b', raw_text)
    if match:
        return match.group(1).upper().strip()

    return "UNKNOWN"

@app.get("/")
def read_root():
    return {"message": "Trading Engine activo - webhook tolerant mode"}

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="ignore").strip()

    parsed = extract_json_from_text(raw_text)

    if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
        nested = extract_json_from_text(parsed["message"])
        if isinstance(nested, dict):
            parsed = nested

    if not isinstance(parsed, dict):
        parsed = {
            "raw_message": raw_text,
            "parse_warning": "TradingView payload was not valid JSON"
        }

    ticker = find_ticker(parsed, raw_text)

    parsed["ticker"] = ticker
    parsed["received_at"] = datetime.now(timezone.utc).isoformat()
    parsed["source"] = "tradingview"
    parsed["raw_payload_preview"] = raw_text[:500]

    trade_store[ticker] = parsed

    return {
        "status": "ok",
        "message": f"Webhook received for {ticker}",
        "data": parsed
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

@app.get("/latest")
def latest():
    return trade_store
