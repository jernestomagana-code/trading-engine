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


def normalize_timeframe(tf):
    tf = str(tf).lower().replace("m", "").replace("min", "").strip()

    if tf in ["5", "5m"]:
        return "5m"
    if tf in ["15", "15m"]:
        return "15m"
    if tf in ["60", "1h", "h"]:
        return "1h"
    if tf in ["d", "1d", "day"]:
        return "1d"

    return tf


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

    match = re.search(r'\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|USTEC\.F|MNQ|NQ|ES|SPX)\b', raw_text)
    if match:
        return match.group(1).upper().strip()

    return "UNKNOWN"


def classify_asset(timeframes):
    tf_5 = timeframes.get("5m", {})
    tf_15 = timeframes.get("15m", {})
    tf_1h = timeframes.get("1h", {})

    setup_5 = str(tf_5.get("setup", "WAIT")).upper()
    trend_15 = str(tf_15.get("trend", "")).lower()
    trend_1h = str(tf_1h.get("trend", "")).lower()

    score_5 = float(tf_5.get("score", 0) or 0)
    score_15 = float(tf_15.get("score", 0) or 0)
    score_1h = float(tf_1h.get("score", 0) or 0)

    weighted_score = round((score_5 * 0.45) + (score_15 * 0.30) + (score_1h * 0.25), 2)

    alignment = "mixed"
    action = "WAIT"
    grade = "C"
    reason = "No hay suficiente confluencia entre 1h, 15m y 5m."

    bullish_5 = "LONG" in setup_5 or "SELL PUT" in setup_5
    bearish_5 = "SHORT" in setup_5 or "SELL CALL" in setup_5

    bullish_confirmed = trend_1h == "bullish" and trend_15 == "bullish" and bullish_5
    bearish_confirmed = trend_1h == "bearish" and trend_15 == "bearish" and bearish_5

    if bullish_confirmed:
        alignment = "bullish"
        action = setup_5
        reason = "Confluencia alcista: 1h bullish, 15m bullish y gatillo 5m alineado."
    elif bearish_confirmed:
        alignment = "bearish"
        action = setup_5
        reason = "Confluencia bajista: 1h bearish, 15m bearish y gatillo 5m alineado."
    elif (trend_1h == "bullish" and bullish_5) or (trend_1h == "bearish" and bearish_5):
        alignment = "partial"
        action = setup_5
        reason = "Existe alineación parcial con 1h, pero falta confirmación completa de 15m."

    if weighted_score >= 88 and alignment in ["bullish", "bearish"]:
        grade = "A+"
    elif weighted_score >= 80 and alignment in ["bullish", "bearish", "partial"]:
        grade = "A"
    elif weighted_score >= 70:
        grade = "B"
    else:
        grade = "C"

    if action == "WAIT":
        grade = "C"

    return {
        "grade": grade,
        "action": action,
        "alignment": alignment,
        "weighted_score": weighted_score,
        "reason": reason,
        "timeframes": {
            "5m": tf_5,
            "15m": tf_15,
            "1h": tf_1h
        }
    }


@app.get("/")
def read_root():
    return {"message": "Trading Engine activo - central scoring mode"}


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
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))

    parsed["ticker"] = ticker
    parsed["timeframe"] = timeframe
    parsed["received_at"] = datetime.now(timezone.utc).isoformat()
    parsed["source"] = "tradingview"
    parsed["raw_payload_preview"] = raw_text[:500]

    if ticker not in trade_store:
        trade_store[ticker] = {}

    trade_store[ticker][timeframe] = parsed

    return {
        "status": "ok",
        "message": f"Webhook received for {ticker} {timeframe}",
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

    return {
        "ticker": ticker,
        "data": trade_store[ticker],
        "classification": classify_asset(trade_store[ticker])
    }


@app.get("/get_dashboard")
def get_dashboard():
    dashboard = []

    for ticker, timeframes in trade_store.items():
        classification = classify_asset(timeframes)
        dashboard.append({
            "ticker": ticker,
            "grade": classification["grade"],
            "action": classification["action"],
            "alignment": classification["alignment"],
            "weighted_score": classification["weighted_score"],
            "reason": classification["reason"]
        })

    grade_order = {"A+": 4, "A": 3, "B": 2, "C": 1}

    dashboard = sorted(
        dashboard,
        key=lambda x: (grade_order.get(x["grade"], 0), x["weighted_score"]),
        reverse=True
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dashboard": dashboard
    }


@app.get("/latest")
def latest():
    return trade_store
