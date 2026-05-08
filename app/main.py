from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from datetime import datetime, timezone
import json
import re
import os

app = FastAPI()

SIGNALS_FILE = "signals_history.json"

EXPIRATION_MINUTES = {
    "5m": 25,
    "15m": 90,
    "1h": 360,
    "1d": 1440,
}

WATCHLIST = ["SPY", "QQQ", "MSFT", "TLT", "GOOG", "AMZN"]


trade_store = {}


def now_utc():
    return datetime.now(timezone.utc)


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


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
    signals = signals[-10000:]

    with open(SIGNALS_FILE, "w") as f:
        json.dump(signals, f, indent=2)


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

    return tf or "unknown"


def find_ticker(data, raw_text):
    if isinstance(data, dict):
        ticker = data.get("ticker") or data.get("symbol") or data.get("tickerid")
        if ticker:
            return str(ticker).upper().strip()

    match = re.search(r'"ticker"\s*:\s*"([^"]+)"', raw_text)
    if match:
        return match.group(1).upper().strip()

    match = re.search(
        r'\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|NFLX|USTEC\.F|MNQ|NQ|ES|SPX)\b',
        raw_text
    )

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


def enrich_signal(signal, timeframe):
    signal = dict(signal)
    signal["age_minutes"] = signal_age_minutes(signal)
    signal["expires_after_minutes"] = EXPIRATION_MINUTES.get(timeframe, 60)
    signal["expired"] = is_expired(signal, timeframe)
    signal["freshness_score"] = freshness_score(signal, timeframe)
    return signal


def active_timeframes(timeframes):
    active = {}

    for tf, signal in timeframes.items():
        enriched = enrich_signal(signal, tf)

        if not enriched["expired"]:
            active[tf] = enriched

    return active


def get_trend(signal):
    return str(signal.get("trend", "")).lower()


def get_setup(signal):
    return str(signal.get("setup", "WAIT")).upper()


def get_score(signal):
    return safe_float(signal.get("score", signal.get("technical_score", 0)), 0)


def rebuild_store_from_history():
    signals = load_signals()
    store = {}

    for signal in signals[-2000:]:
        ticker = str(signal.get("ticker", "UNKNOWN")).upper().strip()
        tf = normalize_timeframe(signal.get("timeframe", "unknown"))

        if ticker not in store:
            store[ticker] = {}

        store[ticker][tf] = signal

    return store


def classify_asset(timeframes):
    active = active_timeframes(timeframes)

    tf_5 = active.get("5m", {})
    tf_15 = active.get("15m", {})
    tf_1h = active.get("1h", {})
    tf_1d = active.get("1d", {})

    setup_5 = get_setup(tf_5)
    setup_15 = get_setup(tf_15)

    trend_5 = get_trend(tf_5)
    trend_15 = get_trend(tf_15)
    trend_1h = get_trend(tf_1h)
    trend_1d = get_trend(tf_1d)

    score_5 = get_score(tf_5)
    score_15 = get_score(tf_15)
    score_1h = get_score(tf_1h)
    score_1d = get_score(tf_1d)

    fresh_5 = safe_float(tf_5.get("freshness_score"), 0)
    fresh_15 = safe_float(tf_15.get("freshness_score"), 0)
    fresh_1h = safe_float(tf_1h.get("freshness_score"), 0)
    fresh_1d = safe_float(tf_1d.get("freshness_score"), 0)

    technical_score = (
        score_5 * 0.30 +
        score_15 * 0.30 +
        score_1h * 0.30 +
        score_1d * 0.10
    )

    freshness_weighted = (
        fresh_5 * 0.30 +
        fresh_15 * 0.30 +
        fresh_1h * 0.30 +
        fresh_1d * 0.10
    )

    weighted_score = round((technical_score * 0.80) + (freshness_weighted * 0.20), 2)

    bullish_5 = "LONG" in setup_5 or "SELL PUT" in setup_5
    bearish_5 = "SHORT" in setup_5 or "SELL CALL" in setup_5

    bullish_context = trend_1h == "bullish"
    bearish_context = trend_1h == "bearish"

    bullish_confirm = trend_15 == "bullish"
    bearish_confirm = trend_15 == "bearish"

    has_5 = bool(tf_5)
    has_15 = bool(tf_15)
    has_1h = bool(tf_1h)

    state = "NO_DATA"
    action = "WAIT"
    grade = "C"
    strategy_type = "none"
    alignment = "mixed"
    recommendation = "Esperar."
    reason = "No hay señales suficientes."

    if has_1h and not has_15:
        if bullish_context:
            state = "BULLISH_CONTEXT"
            strategy_type = "radar"
            reason = "1h bullish, falta confirmación 15m."
        elif bearish_context:
            state = "BEARISH_CONTEXT"
            strategy_type = "radar"
            reason = "1h bearish, falta confirmación 15m."
        else:
            state = "MIXED_CONTEXT"
            reason = "1h sin dirección clara."

    elif has_1h and has_15 and not has_5:
        if bullish_context and bullish_confirm:
            state = "PRE_LONG"
            strategy_type = "swing_theta_radar"
            alignment = "bullish"
            reason = "1h y 15m bullish. Falta gatillo fresco de 5m."
            recommendation = "Radar alcista: esperar gatillo 5m para swing long o naked put."
        elif bearish_context and bearish_confirm:
            state = "PRE_SHORT"
            strategy_type = "short_or_covered_call_radar"
            alignment = "bearish"
            reason = "1h y 15m bearish. Falta gatillo fresco de 5m."
            recommendation = "Radar bajista: esperar gatillo 5m para short o covered call/sell call."
        else:
            state = "WAIT"
            reason = "1h y 15m no están alineados."

    elif has_1h and has_15 and has_5:
        if bullish_context and bullish_confirm and bullish_5:
            state = "LONG_READY"
            action = setup_5
            strategy_type = "intraday_a_plus_or_swing_long"
            alignment = "bullish"
            reason = "Confluencia alcista: 1h bullish, 15m bullish y gatillo 5m alineado."
            recommendation = "Evaluar entrada long o timing para naked put, siempre validando precio, riesgo e invalidación."
        elif bearish_context and bearish_confirm and bearish_5:
            state = "SHORT_READY"
            action = setup_5
            strategy_type = "intraday_a_plus_or_sell_call"
            alignment = "bearish"
            reason = "Confluencia bajista: 1h bearish, 15m bearish y gatillo 5m alineado."
            recommendation = "Evaluar short táctico o covered call/sell call si existe posición base."
        elif bullish_context and bullish_5:
            state = "PARTIAL_LONG"
            action = setup_5
            strategy_type = "partial_radar"
            alignment = "partial_bullish"
            reason = "5m y 1h alcistas, pero falta confirmación fuerte de 15m."
            recommendation = "No entrar agresivo. Esperar confirmación 15m."
        elif bearish_context and bearish_5:
            state = "PARTIAL_SHORT"
            action = setup_5
            strategy_type = "partial_radar"
            alignment = "partial_bearish"
            reason = "5m y 1h bajistas, pero falta confirmación fuerte de 15m."
            recommendation = "No entrar agresivo. Esperar confirmación 15m."
        else:
            state = "WAIT"
            reason = "Hay datos frescos, pero no existe confluencia operable."

    if action != "WAIT":
        if weighted_score >= 88 and alignment in ["bullish", "bearish"]:
            grade = "A+"
        elif weighted_score >= 80:
            grade = "A"
        elif weighted_score >= 70:
            grade = "B"
        else:
            grade = "C"
    else:
        if state in ["PRE_LONG", "PRE_SHORT"] and weighted_score >= 70:
            grade = "B"
        elif state in ["BULLISH_CONTEXT", "BEARISH_CONTEXT"]:
            grade = "C"
        else:
            grade = "C"

    entry = tf_5.get("entry") or tf_5.get("price") or tf_15.get("price") or tf_1h.get("price")
    stop = tf_5.get("stop")
    target = tf_5.get("target")

    missing = []
    if not has_1h:
        missing.append("1h")
    if not has_15:
        missing.append("15m")
    if not has_5:
        missing.append("5m")

    return {
        "state": state,
        "grade": grade,
        "action": action,
        "strategy_type": strategy_type,
        "alignment": alignment,
        "weighted_score": weighted_score,
        "technical_score": round(technical_score, 2),
        "freshness_weighted": round(freshness_weighted, 2),
        "recommendation": recommendation,
        "reason": reason,
        "entry": entry,
        "stop": stop,
        "target": target,
        "missing_timeframes": missing,
        "active_timeframes": active,
        "all_timeframes": timeframes,
    }


def build_dashboard():
    dashboard = []

    for ticker, timeframes in trade_store.items():
        c = classify_asset(timeframes)

        dashboard.append({
            "ticker": ticker,
            "state": c["state"],
            "grade": c["grade"],
            "action": c["action"],
            "strategy_type": c["strategy_type"],
            "alignment": c["alignment"],
            "weighted_score": c["weighted_score"],
            "freshness_weighted": c["freshness_weighted"],
            "recommendation": c["recommendation"],
            "reason": c["reason"],
            "missing_timeframes": c["missing_timeframes"],
        })

    grade_order = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}

    return sorted(
        dashboard,
        key=lambda x: (grade_order.get(x["grade"], 0), x["weighted_score"]),
        reverse=True
    )


def market_regime():
    spy = classify_asset(trade_store.get("SPY", {})) if "SPY" in trade_store else None
    qqq = classify_asset(trade_store.get("QQQ", {})) if "QQQ" in trade_store else None
    tlt = classify_asset(trade_store.get("TLT", {})) if "TLT" in trade_store else None

    signals = []

    for item in [spy, qqq]:
        if item:
            if item["alignment"] == "bullish":
                signals.append("bullish")
            elif item["alignment"] == "bearish":
                signals.append("bearish")

    if signals.count("bullish") >= 2:
        regime = "risk_on"
        summary = "SPY y QQQ muestran sesgo alcista alineado."
    elif signals.count("bearish") >= 2:
        regime = "risk_off"
        summary = "SPY y QQQ muestran sesgo bajista alineado."
    else:
        regime = "mixed_or_chop"
        summary = "No hay alineación clara entre índices principales."

    return {
        "regime": regime,
        "summary": summary,
        "spy": spy,
        "qqq": qqq,
        "tlt": tlt,
    }


@app.on_event("startup")
def startup():
    global trade_store
    trade_store = rebuild_store_from_history()


@app.get("/")
def root():
    return {
        "status": "alive",
        "engine": "Super Engine Bolsa v1.0",
        "mode": "hybrid institutional: swing + theta core, intraday only A/A+",
    }


@app.get("/health")
def health():
    signals = load_signals()
    last_signal = signals[-1] if signals else None

    return {
        "status": "ok",
        "engine": "Super Engine Bolsa v1.0",
        "total_signals": len(signals),
        "tickers_in_memory": list(trade_store.keys()),
        "last_signal": last_signal,
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
            "parse_warning": "payload not valid json"
        }

    ticker = find_ticker(parsed, raw_text)
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))

    parsed["ticker"] = ticker
    parsed["timeframe"] = timeframe
    parsed["received_at"] = now_utc().isoformat()
    parsed["saved_at"] = now_utc().isoformat()
    parsed["source"] = "tradingview"
    parsed["raw_payload_preview"] = raw_text[:500]

    if ticker not in trade_store:
        trade_store[ticker] = {}

    trade_store[ticker][timeframe] = parsed

    save_signal(parsed)

    return {
        "status": "ok",
        "message": f"Webhook received for {ticker} {timeframe}",
        "ticker": ticker,
        "timeframe": timeframe,
        "data": parsed,
    }


@app.get("/get_trade_context")
def get_trade_context(ticker: str):
    ticker = ticker.upper().strip()

    if ticker not in trade_store:
        return {
            "ticker": ticker,
            "status": "missing_data",
            "message": "No hay datos todavía para este ticker."
        }

    return {
        "ticker": ticker,
        "classification": classify_asset(trade_store[ticker])
    }


@app.get("/get_dashboard")
def get_dashboard():
    return {
        "generated_at": now_utc().isoformat(),
        "market_regime": market_regime(),
        "dashboard": build_dashboard()
    }


@app.get("/get_report")
def get_report():
    dashboard = build_dashboard()
    regime = market_regime()

    lines = []
    lines.append("SUPER ENGINE BOLSA v1.0 — REPORTE INSTITUCIONAL")
    lines.append(f"Generado UTC: {now_utc().isoformat()}")
    lines.append("")
    lines.append("RÉGIMEN DE MERCADO")
    lines.append(f"- Estado: {regime['regime']}")
    lines.append(f"- Lectura: {regime['summary']}")
    lines.append("")

    if not dashboard:
        lines.append("No hay señales suficientes todavía.")
        return {
            "generated_at": now_utc().isoformat(),
            "report": "\n".join(lines),
            "dashboard": [],
        }

    ready = [x for x in dashboard if x["state"] in ["LONG_READY", "SHORT_READY"]]
    radar = [x for x in dashboard if x["state"] in ["PRE_LONG", "PRE_SHORT", "PARTIAL_LONG", "PARTIAL_SHORT"]]
    context = [x for x in dashboard if x["state"] in ["BULLISH_CONTEXT", "BEARISH_CONTEXT"]]
    avoid = [x for x in dashboard if x["state"] in ["WAIT", "NO_DATA", "MIXED_CONTEXT"]]

    lines.append("RESUMEN EJECUTIVO")
    lines.append(f"- Listos para evaluación: {len(ready)}")
    lines.append(f"- Radar / casi listos: {len(radar)}")
    lines.append(f"- Contexto sin gatillo: {len(context)}")
    lines.append(f"- Evitar / sin setup: {len(avoid)}")
    lines.append("")

    if ready:
        lines.append("🔥 SETUPS LISTOS")
        for x in ready:
            lines.append(
                f"- {x['ticker']} | {x['grade']} | {x['state']} | "
                f"Score {x['weighted_score']} | {x['recommendation']} | {x['reason']}"
            )
        lines.append("")

    if radar:
        lines.append("👀 RADAR")
        for x in radar:
            lines.append(
                f"- {x['ticker']} | {x['grade']} | {x['state']} | "
                f"Score {x['weighted_score']} | Falta: {', '.join(x['missing_timeframes']) if x['missing_timeframes'] else 'confirmación'} | "
                f"{x['reason']}"
            )
        lines.append("")

    if context:
        lines.append("📌 CONTEXTO")
        for x in context:
            lines.append(
                f"- {x['ticker']} | {x['state']} | {x['reason']}"
            )
        lines.append("")

    if avoid:
        lines.append("⚠️ EVITAR POR AHORA")
        for x in avoid:
            lines.append(
                f"- {x['ticker']} | {x['state']} | {x['reason']}"
            )

    return {
        "generated_at": now_utc().isoformat(),
        "report": "\n".join(lines),
        "dashboard": dashboard,
    }


@app.get("/latest")
def latest():
    return trade_store


@app.get("/history")
def history(limit: int = 100):
    signals = load_signals()

    return {
        "total_signals": len(signals),
        "showing": min(limit, len(signals)),
        "signals": signals[-limit:]
    }


@app.get("/dashboard_html", response_class=HTMLResponse)
def dashboard_html():
    dashboard = build_dashboard()
    regime = market_regime()

    rows = ""

    color_map = {
        "A+": "#0B6E4F",
        "A": "#1A936F",
        "B": "#F4A261",
        "C": "#E76F51",
    }

    for item in dashboard:
        color = color_map.get(item["grade"], "#999")

        rows += f"""
        <tr>
            <td>{item['ticker']}</td>
            <td style="background:{color}; color:white; font-weight:bold;">{item['grade']}</td>
            <td>{item['state']}</td>
            <td>{item['action']}</td>
            <td>{item['weighted_score']}</td>
            <td>{item['alignment']}</td>
            <td>{item['reason']}</td>
        </tr>
        """

    html = f"""
    <html>
    <head>
        <title>Super Engine Bolsa Dashboard</title>
        <style>
            body {{ font-family: Arial; margin: 30px; background: #f7f7f7; }}
            h1 {{ color: #111; }}
            table {{ border-collapse: collapse; width: 100%; background: white; }}
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
            th {{ background: #111; color: white; }}
            .regime {{ padding: 15px; background: white; margin-bottom: 20px; border-left: 5px solid #111; }}
        </style>
    </head>
    <body>
        <h1>Super Engine Bolsa v1.0</h1>
        <div class="regime">
            <b>Market Regime:</b> {regime['regime']}<br>
            <b>Lectura:</b> {regime['summary']}
        </div>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Grade</th>
                <th>State</th>
                <th>Action</th>
                <th>Score</th>
                <th>Alignment</th>
                <th>Reason</th>
            </tr>
            {rows}
        </table>
    </body>
    </html>
    """

    return html
