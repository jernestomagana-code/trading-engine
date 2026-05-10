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

    return age > EXPIRATION_MINUTES.get(timeframe, 60)


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

    for signal in signals[-3000:]:
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

    technical_score = (score_5 * 0.30) + (score_15 * 0.30) + (score_1h * 0.30) + (score_1d * 0.10)
    freshness_weighted = (fresh_5 * 0.30) + (fresh_15 * 0.30) + (fresh_1h * 0.30) + (fresh_1d * 0.10)
    weighted_score = round((technical_score * 0.80) + (freshness_weighted * 0.20), 2)

    bullish_5 = "LONG" in setup_5 or "SELL PUT" in setup_5
    bearish_5 = "SHORT" in setup_5 or "SELL CALL" in setup_5
    bullish_15 = trend_15 == "bullish" or "LONG" in setup_15 or "SELL PUT" in setup_15
    bearish_15 = trend_15 == "bearish" or "SHORT" in setup_15 or "SELL CALL" in setup_15
    bullish_1h = trend_1h == "bullish"
    bearish_1h = trend_1h == "bearish"

    has_5 = bool(tf_5)
    has_15 = bool(tf_15)
    has_1h = bool(tf_1h)

    state = "NO_DATA"
    action = "WAIT"
    grade = "C"
    conviction = "LOW"
    strategy_type = "none"
    alignment = "mixed"
    recommendation = "Esperar."
    reason = "No hay señales frescas suficientes."

    if has_1h and not has_15 and not has_5:
        if bullish_1h:
            state = "PRE_LONG"
            strategy_type = "swing_theta_radar"
            alignment = "bullish_context"
            reason = "1h bullish fresco, falta confirmación 15m y gatillo 5m."
            recommendation = "Radar alcista temprano. No ejecutar todavía."
        elif bearish_1h:
            state = "PRE_SHORT"
            strategy_type = "short_or_covered_call_radar"
            alignment = "bearish_context"
            reason = "1h bearish fresco, falta confirmación 15m y gatillo 5m."
            recommendation = "Radar bajista temprano. No ejecutar todavía."
        else:
            state = "MIXED"
            reason = "1h fresco pero sin dirección clara."

    elif has_1h and has_15 and not has_5:
        if bullish_1h and bullish_15:
            state = "PRE_LONG"
            strategy_type = "swing_theta_radar"
            alignment = "bullish"
            reason = "1h y 15m bullish. Falta gatillo fresco de 5m."
            recommendation = "Preparar swing long o naked put; esperar gatillo 5m."
        elif bearish_1h and bearish_15:
            state = "PRE_SHORT"
            strategy_type = "short_or_covered_call_radar"
            alignment = "bearish"
            reason = "1h y 15m bearish. Falta gatillo fresco de 5m."
            recommendation = "Preparar short táctico o covered call; esperar gatillo 5m."
        else:
            state = "MIXED"
            reason = "1h y 15m no están alineados."

    elif has_1h and has_15 and has_5:
        if bullish_1h and bullish_15 and bullish_5:
            action = setup_5
            alignment = "bullish"
            strategy_type = "swing_long_theta_or_intraday_a"
            if score_5 >= 90 and fresh_5 >= 75:
                state = "LONG_ACTIVE"
                reason = "Momentum alcista activo con 1h, 15m y 5m alineados."
            elif score_5 >= 80:
                state = "LONG_READY"
                reason = "Confluencia alcista multi-timeframe con gatillo 5m."
            else:
                state = "PARTIAL_LONG"
                reason = "Alineación alcista, pero el gatillo 5m no tiene suficiente fuerza."
            recommendation = "Evaluar swing long, intradía A/A+ o timing para naked put; validar riesgo e invalidación."

        elif bearish_1h and bearish_15 and bearish_5:
            action = setup_5
            alignment = "bearish"
            strategy_type = "short_tactical_or_sell_call"
            if score_5 >= 90 and fresh_5 >= 75:
                state = "SHORT_ACTIVE"
                reason = "Momentum bajista activo con 1h, 15m y 5m alineados."
            elif score_5 >= 80:
                state = "SHORT_READY"
                reason = "Confluencia bajista multi-timeframe con gatillo 5m."
            else:
                state = "PARTIAL_SHORT"
                reason = "Alineación bajista, pero el gatillo 5m no tiene suficiente fuerza."
            recommendation = "Evaluar short táctico o covered call/sell call; validar riesgo e invalidación."

        elif bullish_1h and bullish_5 and not bullish_15:
            state = "PARTIAL_LONG"
            action = setup_5
            alignment = "partial_bullish"
            strategy_type = "partial_radar"
            reason = "1h y 5m alcistas, pero falta confirmación 15m."
            recommendation = "No ejecutar agresivo; esperar confirmación 15m."

        elif bearish_1h and bearish_5 and not bearish_15:
            state = "PARTIAL_SHORT"
            action = setup_5
            alignment = "partial_bearish"
            strategy_type = "partial_radar"
            reason = "1h y 5m bajistas, pero falta confirmación 15m."
            recommendation = "No ejecutar agresivo; esperar confirmación 15m."
        else:
            state = "WAIT"
            reason = "Hay señales frescas, pero no existe confluencia operable."

    if state in ["LONG_ACTIVE", "SHORT_ACTIVE"]:
        conviction = "VERY_HIGH" if weighted_score >= 88 else "HIGH"
    elif state in ["LONG_READY", "SHORT_READY"]:
        conviction = "HIGH" if weighted_score >= 80 else "MEDIUM"
    elif state in ["PRE_LONG", "PRE_SHORT", "PARTIAL_LONG", "PARTIAL_SHORT"]:
        conviction = "MEDIUM" if weighted_score >= 70 else "LOW"
    else:
        conviction = "LOW"

    if action != "WAIT":
        if weighted_score >= 88 and conviction in ["VERY_HIGH", "HIGH"]:
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
        else:
            grade = "C"

    if state == "LONG_ACTIVE" and score_5 >= 95:
        state = "EXTENDED_LONG"
        recommendation = "No perseguir. Esperar pullback o nueva base."
        reason = "Momentum alcista fuerte pero potencialmente extendido."

    if state == "SHORT_ACTIVE" and score_5 >= 95:
        state = "EXTENDED_SHORT"
        recommendation = "No perseguir. Esperar rebote o nueva base."
        reason = "Momentum bajista fuerte pero potencialmente extendido."

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

    priority_score = calculate_priority_score(state, grade, conviction, weighted_score, freshness_weighted, alignment)

    return {
        "state": state,
        "grade": grade,
        "conviction": conviction,
        "action": action,
        "strategy_type": strategy_type,
        "alignment": alignment,
        "weighted_score": weighted_score,
        "technical_score": round(technical_score, 2),
        "freshness_weighted": round(freshness_weighted, 2),
        "priority_score": priority_score,
        "recommendation": recommendation,
        "reason": reason,
        "entry": entry,
        "stop": stop,
        "target": target,
        "missing_timeframes": missing,
        "active_timeframes": active,
        "all_timeframes": timeframes,
    }


def calculate_priority_score(state, grade, conviction, weighted_score, freshness_weighted, alignment):
    score = weighted_score

    if grade == "A+":
        score += 10
    elif grade == "A":
        score += 6
    elif grade == "B":
        score += 2

    if conviction == "VERY_HIGH":
        score += 10
    elif conviction == "HIGH":
        score += 6
    elif conviction == "MEDIUM":
        score += 2

    if state in ["LONG_READY", "SHORT_READY"]:
        score += 8
    elif state in ["LONG_ACTIVE", "SHORT_ACTIVE"]:
        score += 6
    elif state in ["PRE_LONG", "PRE_SHORT"]:
        score += 3
    elif state in ["EXTENDED_LONG", "EXTENDED_SHORT"]:
        score -= 12
    elif state in ["WAIT", "MIXED", "NO_DATA"]:
        score -= 15

    if alignment in ["bullish", "bearish"]:
        score += 5
    elif "partial" in alignment:
        score -= 3

    if freshness_weighted < 50:
        score -= 10

    return round(max(0, min(score, 100)), 2)


def strategy_selection(classification):
    state = classification["state"]
    alignment = classification["alignment"]
    grade = classification["grade"]
    conviction = classification["conviction"]

    if state in ["LONG_READY", "LONG_ACTIVE"] and grade in ["A+", "A"]:
        return {
            "primary_strategy": "Swing Long / Tactical Long",
            "secondary_strategy": "Naked Put if IV is attractive",
            "avoid": "No perseguir si está extendido",
        }

    if state in ["PRE_LONG", "PARTIAL_LONG"]:
        return {
            "primary_strategy": "Radar Swing Long",
            "secondary_strategy": "Preparar Naked Put si confirma 5m/15m",
            "avoid": "Entrada anticipada sin gatillo fresco",
        }

    if state in ["SHORT_READY", "SHORT_ACTIVE"] and grade in ["A+", "A"]:
        return {
            "primary_strategy": "Tactical Short",
            "secondary_strategy": "Covered Call / Sell Call if holding shares",
            "avoid": "Short si está sobreextendido",
        }

    if state in ["PRE_SHORT", "PARTIAL_SHORT"]:
        return {
            "primary_strategy": "Radar Bearish",
            "secondary_strategy": "Covered Call si existe posición",
            "avoid": "Short agresivo sin confirmación",
        }

    if state in ["EXTENDED_LONG", "EXTENDED_SHORT"]:
        return {
            "primary_strategy": "Defense / Wait",
            "secondary_strategy": "Esperar pullback o nueva base",
            "avoid": "Perseguir movimiento",
        }

    return {
        "primary_strategy": "Wait / No Trade",
        "secondary_strategy": "Capital preservation",
        "avoid": "Forzar operación sin edge",
    }


def build_dashboard():
    dashboard = []

    for ticker, timeframes in trade_store.items():
        c = classify_asset(timeframes)
        strategy = strategy_selection(c)

        dashboard.append({
            "ticker": ticker,
            "state": c["state"],
            "grade": c["grade"],
            "conviction": c["conviction"],
            "action": c["action"],
            "strategy_type": c["strategy_type"],
            "primary_strategy": strategy["primary_strategy"],
            "secondary_strategy": strategy["secondary_strategy"],
            "avoid": strategy["avoid"],
            "alignment": c["alignment"],
            "weighted_score": c["weighted_score"],
            "priority_score": c["priority_score"],
            "freshness_weighted": c["freshness_weighted"],
            "recommendation": c["recommendation"],
            "reason": c["reason"],
            "missing_timeframes": c["missing_timeframes"],
        })

    return sorted(
        dashboard,
        key=lambda x: (x["priority_score"], x["weighted_score"]),
        reverse=True
    )


def market_regime():
    spy = classify_asset(trade_store.get("SPY", {})) if "SPY" in trade_store else None
    qqq = classify_asset(trade_store.get("QQQ", {})) if "QQQ" in trade_store else None
    tlt = classify_asset(trade_store.get("TLT", {})) if "TLT" in trade_store else None

    bullish = 0
    bearish = 0

    for item in [spy, qqq]:
        if item:
            if item["alignment"] in ["bullish", "bullish_context", "partial_bullish"]:
                bullish += 1
            if item["alignment"] in ["bearish", "bearish_context", "partial_bearish"]:
                bearish += 1

    if bullish >= 2:
        regime = "RISK_ON"
        summary = "SPY y QQQ muestran sesgo alcista."
    elif bearish >= 2:
        regime = "RISK_OFF"
        summary = "SPY y QQQ muestran sesgo bajista."
    else:
        regime = "MIXED_OR_CHOP"
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
        "engine": "Super Engine Bolsa v2.0",
        "mode": "Full Institutional Engine",
    }


@app.get("/health")
def health():
    signals = load_signals()
    return {
        "status": "ok",
        "engine": "Super Engine Bolsa v2.0",
        "total_signals": len(signals),
        "tickers_in_memory": list(trade_store.keys()),
        "last_signal": signals[-1] if signals else None,
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

    c = classify_asset(trade_store[ticker])
    c["strategy_selection"] = strategy_selection(c)

    return {
        "ticker": ticker,
        "classification": c
    }


@app.get("/get_dashboard")
def get_dashboard():
    dashboard = build_dashboard()

    for i, item in enumerate(dashboard, start=1):
        item["priority_rank"] = i

    return {
        "generated_at": now_utc().isoformat(),
        "market_regime": market_regime(),
        "dashboard": dashboard,
        "best_setups": dashboard[:5],
    }


@app.get("/get_report")
def get_report():
    dashboard = build_dashboard()
    regime = market_regime()

    for i, item in enumerate(dashboard, start=1):
        item["priority_rank"] = i

    lines = []
    lines.append("SUPER ENGINE BOLSA v2.0 — FULL INSTITUTIONAL ENGINE")
    lines.append(f"Generado UTC: {now_utc().isoformat()}")
    lines.append("")
    lines.append("RÉGIMEN DE MERCADO")
    lines.append(f"- Estado: {regime['regime']}")
    lines.append(f"- Lectura: {regime['summary']}")
    lines.append("")

    if not dashboard:
        lines.append("No hay señales suficientes todavía.")
        return {"generated_at": now_utc().isoformat(), "report": "\n".join(lines), "dashboard": []}

    ready = [x for x in dashboard if x["state"] in ["LONG_READY", "SHORT_READY", "LONG_ACTIVE", "SHORT_ACTIVE"]]
    extended = [x for x in dashboard if x["state"] in ["EXTENDED_LONG", "EXTENDED_SHORT"]]
    radar = [x for x in dashboard if x["state"] in ["PRE_LONG", "PRE_SHORT", "PARTIAL_LONG", "PARTIAL_SHORT"]]
    avoid = [x for x in dashboard if x["state"] in ["WAIT", "NO_DATA", "MIXED", "MIXED_OR_CHOP"]]

    lines.append("RESUMEN EJECUTIVO")
    lines.append(f"- Setups listos/activos: {len(ready)}")
    lines.append(f"- Extendidos/no perseguir: {len(extended)}")
    lines.append(f"- Radar: {len(radar)}")
    lines.append(f"- Evitar/sin edge: {len(avoid)}")
    lines.append("")

    lines.append("🏆 TOP PRIORITY SETUPS")
    for x in dashboard[:5]:
        lines.append(
            f"{x['priority_rank']}. {x['ticker']} | {x['grade']} | {x['conviction']} | "
            f"{x['state']} | Priority {x['priority_score']} | {x['primary_strategy']}"
        )
    lines.append("")

    if ready:
        lines.append("🔥 SETUPS LISTOS / ACTIVOS")
        for x in ready:
            lines.append(
                f"- {x['ticker']} | {x['grade']} | {x['conviction']} | {x['state']} | "
                f"Priority {x['priority_score']} | {x['recommendation']} | {x['reason']}"
            )
        lines.append("")

    if extended:
        lines.append("⚠️ EXTENDIDOS — NO PERSEGUIR")
        for x in extended:
            lines.append(f"- {x['ticker']} | {x['state']} | Priority {x['priority_score']} | {x['reason']}")
        lines.append("")

    if radar:
        lines.append("👀 RADAR / EN FORMACIÓN")
        for x in radar:
            missing = ", ".join(x["missing_timeframes"]) if x["missing_timeframes"] else "confirmación"
            lines.append(
                f"- {x['ticker']} | {x['grade']} | {x['conviction']} | {x['state']} | "
                f"Priority {x['priority_score']} | Falta: {missing} | {x['reason']}"
            )
        lines.append("")

    if avoid:
        lines.append("⚪ EVITAR / SIN EDGE")
        for x in avoid:
            lines.append(f"- {x['ticker']} | {x['state']} | {x['reason']}")

    return {
        "generated_at": now_utc().isoformat(),
        "report": "\n".join(lines),
        "dashboard": dashboard,
        "best_setups": dashboard[:5],
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

    for i, item in enumerate(dashboard, start=1):
        color = color_map.get(item["grade"], "#999")
        rows += f"""
        <tr>
            <td>{i}</td>
            <td>{item['ticker']}</td>
            <td style="background:{color}; color:white; font-weight:bold;">{item['grade']}</td>
            <td>{item['conviction']}</td>
            <td>{item['state']}</td>
            <td>{item['primary_strategy']}</td>
            <td>{item['priority_score']}</td>
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
        <h1>Super Engine Bolsa v2.0</h1>
        <div class="regime">
            <b>Market Regime:</b> {regime['regime']}<br>
            <b>Lectura:</b> {regime['summary']}
        </div>
        <table>
            <tr>
                <th>Rank</th>
                <th>Ticker</th>
                <th>Grade</th>
                <th>Conviction</th>
                <th>State</th>
                <th>Strategy</th>
                <th>Priority</th>
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
