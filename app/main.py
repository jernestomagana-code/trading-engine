from fastapi import FastAPI, Request
from datetime import datetime, timezone
import json
import re

app = FastAPI()

trade_store = {}

EXPIRATION_MINUTES = {
    "5m": 25,
    "15m": 90,
    "1h": 360,
    "1d": 1440,
}


def now_utc():
    return datetime.now(timezone.utc)


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
    tf = str(tf).lower().replace("min", "").replace("m", "").strip()

    if tf == "5":
        return "5m"
    if tf == "15":
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

    match = re.search(r'"ticker"\s*:\s*"([^"]+)"', raw_text)
    if match:
        return match.group(1).upper().strip()

    match = re.search(r'\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|USTEC\.F|MNQ|NQ|ES|SPX)\b', raw_text)
    if match:
        return match.group(1).upper().strip()

    return "UNKNOWN"


def signal_age_minutes(signal):
    received_at = signal.get("received_at")
    if not received_at:
        return None

    try:
        received_dt = datetime.fromisoformat(received_at)
        return round((now_utc() - received_dt).total_seconds() / 60, 2)
    except Exception:
        return None


def is_expired(signal, timeframe):
    age = signal_age_minutes(signal)
    if age is None:
        return True

    limit = EXPIRATION_MINUTES.get(timeframe, 60)
    return age > limit


def freshness_score(signal, timeframe):
    age = signal_age_minutes(signal)
    if age is None:
        return 0

    limit = EXPIRATION_MINUTES.get(timeframe, 60)

    if age <= limit * 0.25:
        return 100
    if age <= limit * 0.50:
        return 75
    if age <= limit:
        return 50

    return 0


def active_timeframes(timeframes):
    clean = {}

    for tf, signal in timeframes.items():
        signal["age_minutes"] = signal_age_minutes(signal)
        signal["expires_after_minutes"] = EXPIRATION_MINUTES.get(tf, 60)
        signal["expired"] = is_expired(signal, tf)
        signal["freshness_score"] = freshness_score(signal, tf)

        if not signal["expired"]:
            clean[tf] = signal

    return clean


def classify_asset(timeframes):
    active = active_timeframes(timeframes)

    tf_5 = active.get("5m", {})
    tf_15 = active.get("15m", {})
    tf_1h = active.get("1h", {})

    setup_5 = str(tf_5.get("setup", "WAIT")).upper()
    trend_15 = str(tf_15.get("trend", "")).lower()
    trend_1h = str(tf_1h.get("trend", "")).lower()

    score_5 = float(tf_5.get("score", 0) or 0)
    score_15 = float(tf_15.get("score", 0) or 0)
    score_1h = float(tf_1h.get("score", 0) or 0)

    fresh_5 = float(tf_5.get("freshness_score", 0) or 0)
    fresh_15 = float(tf_15.get("freshness_score", 0) or 0)
    fresh_1h = float(tf_1h.get("freshness_score", 0) or 0)

    technical_weighted = (score_5 * 0.45) + (score_15 * 0.30) + (score_1h * 0.25)
    freshness_weighted = (fresh_5 * 0.45) + (fresh_15 * 0.30) + (fresh_1h * 0.25)

    weighted_score = round((technical_weighted * 0.75) + (freshness_weighted * 0.25), 2)

    bullish_5 = "LONG" in setup_5 or "SELL PUT" in setup_5
    bearish_5 = "SHORT" in setup_5 or "SELL CALL" in setup_5

    alignment = "mixed"
    action = "WAIT"
    grade = "C"
    reason = "No hay suficiente confluencia activa entre 1h, 15m y 5m."

    if not tf_5:
        reason = "No hay gatillo fresco de 5m."
    elif not tf_15:
        reason = "Falta confirmación fresca de 15m."
    elif not tf_1h:
        reason = "Falta contexto fresco de 1h."
    elif trend_1h == "bullish" and trend_15 == "bullish" and bullish_5:
        alignment = "bullish"
        action = setup_5
        reason = "Confluencia alcista fresca: 1h bullish, 15m bullish y gatillo 5m alineado."
    elif trend_1h == "bearish" and trend_15 == "bearish" and bearish_5:
        alignment = "bearish"
        action = setup_5
        reason = "Confluencia bajista fresca: 1h bearish, 15m bearish y gatillo 5m alineado."
    elif (trend_1h == "bullish" and bullish_5) or (trend_1h == "bearish" and bearish_5):
        alignment = "partial"
        action = setup_5
        reason = "Alineación parcial fresca con 1h, pero falta confirmación completa de 15m."

    if action != "WAIT":
        if weighted_score >= 88 and alignment in ["bullish", "bearish"]:
            grade = "A+"
        elif weighted_score >= 80:
            grade = "A"
        elif weighted_score >= 70:
            grade = "B"
        else:
            grade = "C"

    return {
        "grade": grade,
        "action": action,
        "alignment": alignment,
        "weighted_score": weighted_score,
        "freshness_weighted": round(freshness_weighted, 2),
        "reason": reason,
        "active_timeframes": active,
        "all_timeframes": timeframes,
    }


@app.get("/")
def read_root():
    return {
        "message": "Trading Engine activo - central scoring with signal expiration",
        "expiration_minutes": EXPIRATION_MINUTES,
    }


@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="ignore").strip()

    parsed = extract_json_from_text(raw_text)

    if not isinstance(parsed, dict):
        parsed = {
            "raw_message": raw_text,
            "parse_warning": "TradingView payload was not valid JSON"
        }

    ticker = find_ticker(parsed, raw_text)
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))

    parsed["ticker"] = ticker
    parsed["timeframe"] = timeframe
    parsed["received_at"] = now_utc().isoformat()
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
            "freshness_weighted": classification["freshness_weighted"],
            "reason": classification["reason"],
        })

    grade_order = {"A+": 4, "A": 3, "B": 2, "C": 1}

    dashboard = sorted(
        dashboard,
        key=lambda x: (grade_order.get(x["grade"], 0), x["weighted_score"]),
        reverse=True
    )

    return {
        "generated_at": now_utc().isoformat(),
        "expiration_minutes": EXPIRATION_MINUTES,
        "dashboard": dashboard
    }


@app.get("/latest")
def latest():
    return trade_store
