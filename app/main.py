from fastapi import FastAPI, Request
from datetime import datetime, timezone
import json
import re
import os

app = FastAPI()

trade_store = {}

SIGNALS_FILE = "signals_history.json"

EXPIRATION_MINUTES = {
    "5m": 25,
    "15m": 90,
    "1h": 360,
    "1d": 1440,
}


# =========================================================
# PERSISTENCE
# =========================================================

def load_signals():
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_signal(signal):
    signals = load_signals()

    signals.append(signal)

    signals = signals[-5000:]

    with open(SIGNALS_FILE, "w") as f:
        json.dump(signals, f, indent=2)


# =========================================================
# HELPERS
# =========================================================

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

    match = re.search(
        r'\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|USTEC\.F|MNQ|NQ|ES|SPX)\b',
        raw_text
    )

    if match:
        return match.group(1).upper().strip()

    return "UNKNOWN"


# =========================================================
# TIME / EXPIRATION
# =========================================================

def signal_age_minutes(signal):

    received_at = signal.get("received_at")

    if not received_at:
        return None

    try:
        received_dt = datetime.fromisoformat(received_at)

        return round(
            (now_utc() - received_dt).total_seconds() / 60,
            2
        )

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


# =========================================================
# CLASSIFICATION ENGINE
# =========================================================

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

    weighted_score = round(
        (
            (score_5 * 0.45) +
            (score_15 * 0.30) +
            (score_1h * 0.25)
        ) * 0.75
        +
        (
            (fresh_5 * 0.45) +
            (fresh_15 * 0.30) +
            (fresh_1h * 0.25)
        ) * 0.25,
        2
    )

    bullish_5 = (
        "LONG" in setup_5 or
        "SELL PUT" in setup_5
    )

    bearish_5 = (
        "SHORT" in setup_5 or
        "SELL CALL" in setup_5
    )

    alignment = "mixed"

    action = "WAIT"

    grade = "C"

    status = "NO_SETUP"

    reason = "No hay suficiente confluencia."

    if trend_1h == "bullish":

        status = "BULLISH_CONTEXT"

    elif trend_1h == "bearish":

        status = "BEARISH_CONTEXT"

    if trend_1h == "bullish" and trend_15 == "bullish":

        status = "PRE_LONG"

        reason = "1h y 15m bullish. Esperando gatillo 5m."

    if trend_1h == "bearish" and trend_15 == "bearish":

        status = "PRE_SHORT"

        reason = "1h y 15m bearish. Esperando gatillo 5m."

    if trend_1h == "bullish" and trend_15 == "bullish" and bullish_5:

        alignment = "bullish"

        action = setup_5

        status = "LONG_READY"

        reason = "Confluencia alcista multi-timeframe."

    elif trend_1h == "bearish" and trend_15 == "bearish" and bearish_5:

        alignment = "bearish"

        action = setup_5

        status = "SHORT_READY"

        reason = "Confluencia bajista multi-timeframe."

    if weighted_score >= 88 and action != "WAIT":

        grade = "A+"

    elif weighted_score >= 80 and action != "WAIT":

        grade = "A"

    elif weighted_score >= 70:

        grade = "B"

    return {
        "grade": grade,
        "status": status,
        "action": action,
        "alignment": alignment,
        "weighted_score": weighted_score,
        "reason": reason,
        "active_timeframes": active,
    }


# =========================================================
# DASHBOARD
# =========================================================

def build_dashboard():

    dashboard = []

    for ticker, timeframes in trade_store.items():

        classification = classify_asset(timeframes)

        dashboard.append({
            "ticker": ticker,
            **classification
        })

    grade_order = {
        "A+": 4,
        "A": 3,
        "B": 2,
        "C": 1
    }

    return sorted(
        dashboard,
        key=lambda x: (
            grade_order.get(x["grade"], 0),
            x["weighted_score"]
        ),
        reverse=True
    )


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():

    return {
        "status": "alive",
        "engine": "Super Engine Bolsa"
    }


# =========================================================
# WEBHOOK
# =========================================================

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):

    raw_body = await request.body()

    raw_text = raw_body.decode(
        "utf-8",
        errors="ignore"
    ).strip()

    parsed = extract_json_from_text(raw_text)

    if not isinstance(parsed, dict):

        parsed = {
            "raw_message": raw_text,
            "parse_warning": "payload not valid json"
        }

    ticker = find_ticker(parsed, raw_text)

    timeframe = normalize_timeframe(
        parsed.get("timeframe", "unknown")
    )

    parsed["ticker"] = ticker

    parsed["timeframe"] = timeframe

    parsed["received_at"] = now_utc().isoformat()

    parsed["saved_at"] = now_utc().isoformat()

    parsed["source"] = "tradingview"

    if ticker not in trade_store:
        trade_store[ticker] = {}

    trade_store[ticker][timeframe] = parsed

    save_signal(parsed)

    return {
        "status": "ok",
        "ticker": ticker,
        "timeframe": timeframe
    }


# =========================================================
# TRADE CONTEXT
# =========================================================

@app.get("/get_trade_context")
def get_trade_context(ticker: str):

    ticker = ticker.upper().strip()

    if ticker not in trade_store:

        return {
            "ticker": ticker,
            "message": "No hay datos todavía"
        }

    return {
        "ticker": ticker,
        "classification": classify_asset(
            trade_store[ticker]
        )
    }


# =========================================================
# DASHBOARD
# =========================================================

@app.get("/get_dashboard")
def get_dashboard():

    return {
        "generated_at": now_utc().isoformat(),
        "dashboard": build_dashboard()
    }


# =========================================================
# REPORT
# =========================================================

@app.get("/get_report")
def get_report():

    dashboard = build_dashboard()

    report = []

    report.append("SUPER ENGINE BOLSA — REPORTE INSTITUCIONAL")
    report.append("")

    if not dashboard:

        report.append("Todavía no hay señales suficientes.")

        return {
            "report": "\n".join(report)
        }

    long_ready = []
    short_ready = []
    radar = []
    weak = []

    for item in dashboard:

        if item["status"] == "LONG_READY":
            long_ready.append(item)

        elif item["status"] == "SHORT_READY":
            short_ready.append(item)

        elif item["status"] in ["PRE_LONG", "PRE_SHORT"]:
            radar.append(item)

        else:
            weak.append(item)

    report.append("RESUMEN EJECUTIVO")
    report.append("")

    report.append(f"LONG listos: {len(long_ready)}")
    report.append(f"SHORT listos: {len(short_ready)}")
    report.append(f"En radar: {len(radar)}")
    report.append(f"Débiles: {len(weak)}")
    report.append("")

    if long_ready:

        report.append("🔥 LONG READY")
        report.append("")

        for x in long_ready:

            report.append(
                f"{x['ticker']} | "
                f"{x['grade']} | "
                f"Score {x['weighted_score']} | "
                f"{x['reason']}"
            )

        report.append("")

    if short_ready:

        report.append("🔻 SHORT READY")
        report.append("")

        for x in short_ready:

            report.append(
                f"{x['ticker']} | "
                f"{x['grade']} | "
                f"Score {x['weighted_score']} | "
                f"{x['reason']}"
            )

        report.append("")

    if radar:

        report.append("👀 EN RADAR")
        report.append("")

        for x in radar:

            report.append(
                f"{x['ticker']} | "
                f"{x['status']} | "
                f"{x['reason']}"
            )

        report.append("")

    if weak:

        report.append("⚠️ SIN SETUP")
        report.append("")

        for x in weak:

            report.append(
                f"{x['ticker']} | "
                f"{x['reason']}"
            )

    return {
        "generated_at": now_utc().isoformat(),
        "report": "\n".join(report),
        "dashboard": dashboard
    }


# =========================================================
# LATEST
# =========================================================

@app.get("/latest")
def latest():

    return trade_store


# =========================================================
# HISTORY
# =========================================================

@app.get("/history")
def history(limit: int = 100):

    signals = load_signals()

    return {
        "total_signals": len(signals),
        "signals": signals[-limit:]
    }
