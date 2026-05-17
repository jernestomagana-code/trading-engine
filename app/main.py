from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import re
import os
import math
import requests

app = FastAPI(title="Super Engine Bolsa", version="5.0.0")

SIGNALS_FILE = "signals_history.json"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
REQUIRE_WEBHOOK_SECRET = os.getenv("REQUIRE_WEBHOOK_SECRET", "false").lower() == "true"

EXPIRATION_MINUTES = {
    "5m": 25,
    "15m": 90,
    "1h": 360,
    "1d": 1440,
}

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0
INITIAL_WINDOW_MINUTES = 150
MIN_PRICE_FOR_THETA = 100

trade_store: Dict[str, Dict[str, Dict[str, Any]]] = {}


class TradingSignal(BaseModel):
    ticker: Optional[str] = Field(default="UNKNOWN")
    timeframe: Optional[str] = Field(default="unknown")
    setup: Optional[str] = Field(default="WAIT")
    trend: Optional[str] = Field(default="")
    score: Optional[float] = Field(default=0)
    price: Optional[float] = Field(default=None)
    entry: Optional[float] = Field(default=None)
    stop: Optional[float] = Field(default=None)
    target: Optional[float] = Field(default=None)
    iv_rank: Optional[float] = Field(default=None)
    iv_percentile: Optional[float] = Field(default=None)
    historical_volatility: Optional[float] = Field(default=None)
    implied_volatility: Optional[float] = Field(default=None)
    gamma_bias: Optional[str] = Field(default=None)
    options_flow_bias: Optional[str] = Field(default=None)
    support_near: Optional[bool] = Field(default=None)
    resistance_near: Optional[bool] = Field(default=None)
    earnings_soon: Optional[bool] = Field(default=None)
    event_risk: Optional[bool] = Field(default=None)
    asset_class: Optional[str] = Field(default="EQUITY")
    volume_relative: Optional[float] = Field(default=None)
    rsi: Optional[float] = Field(default=None)
    macd_state: Optional[str] = Field(default=None)
    adx: Optional[float] = Field(default=None)
    vwap_position: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)
    grade: Optional[str] = Field(default=None)
    conviction: Optional[str] = Field(default=None)
    priority_score: Optional[float] = Field(default=None)
    strategy_hint: Optional[str] = Field(default=None)
    final_decision: Optional[str] = Field(default=None)
    extra: Optional[Dict[str, Any]] = Field(default=None)


class PositionSizingRequest(BaseModel):
    account_size: float = Field(..., description="Account size in USD")
    risk_percent: float = Field(default=1.0, description="Risk percent per trade")
    entry: float
    stop: float


class OptionEvalRequest(BaseModel):
    ticker: str
    strategy: str = Field(default="NAKED_PUT")
    strike: Optional[float] = None
    premium: Optional[float] = None
    dte: Optional[int] = None
    account_size: Optional[float] = None
    margin_required: Optional[float] = None
    iv_rank: Optional[float] = None
    price: Optional[float] = None
    support_near: Optional[bool] = None
    resistance_near: Optional[bool] = None
    earnings_soon: Optional[bool] = None


def now_utc():
    return datetime.now(timezone.utc)


def now_market():
    return datetime.now(MARKET_TZ)


def market_open_today():
    now = now_market()
    return now.replace(
        hour=MARKET_OPEN_HOUR,
        minute=MARKET_OPEN_MINUTE,
        second=0,
        microsecond=0,
    )


def market_close_today():
    now = now_market()
    return now.replace(
        hour=MARKET_CLOSE_HOUR,
        minute=MARKET_CLOSE_MINUTE,
        second=0,
        microsecond=0,
    )


def is_market_weekday():
    return now_market().weekday() < 5


def minutes_since_open():
    return round((now_market() - market_open_today()).total_seconds() / 60, 2)


def inside_execution_window():
    mins = minutes_since_open()
    return is_market_weekday() and 0 <= mins <= INITIAL_WINDOW_MINUTES


def market_session_state():
    if not is_market_weekday():
        return "CLOSED_WEEKEND"

    now = now_market()

    if now < market_open_today():
        return "PREMARKET"

    if market_open_today() <= now <= market_close_today():
        if inside_execution_window():
            return "OPEN_WINDOW"
        return "AFTER_INITIAL_WINDOW"

    return "CLOSED"


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ["true", "1", "yes", "y", "si", "sí"]
    return bool(value)


def supabase_enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY)


def supabase_headers(prefer="return=minimal"):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_insert_signal(signal):
    if not supabase_enabled():
        return {"enabled": False, "saved": False, "error": "Supabase env vars missing"}

    url = f"{SUPABASE_URL}/rest/v1/trading_signals"

    payload = {
        "ticker": signal.get("ticker", "UNKNOWN"),
        "timeframe": signal.get("timeframe", "unknown"),
        "setup": signal.get("setup"),
        "trend": signal.get("trend"),
        "score": safe_float(signal.get("score", signal.get("technical_score", 0)), None),
        "price": safe_float(signal.get("price", signal.get("close", 0)), None),
        "state": signal.get("state"),
        "grade": signal.get("grade"),
        "conviction": signal.get("conviction"),
        "priority_score": safe_float(signal.get("priority_score", 0), None),
        "received_at": signal.get("received_at"),
        "payload": signal,
    }

    try:
        response = requests.post(url, headers=supabase_headers(), json=payload, timeout=10)
        if response.status_code in [200, 201, 204]:
            return {"enabled": True, "saved": True, "status_code": response.status_code}

        return {
            "enabled": True,
            "saved": False,
            "status_code": response.status_code,
            "error": response.text[:800],
        }

    except Exception as e:
        return {"enabled": True, "saved": False, "error": str(e)}


def supabase_fetch_signals(limit=3000):
    if not supabase_enabled():
        return []

    url = (
        f"{SUPABASE_URL}/rest/v1/trading_signals"
        f"?select=payload&order=received_at.desc&limit={limit}"
    )

    try:
        response = requests.get(url, headers=supabase_headers(None), timeout=10)
        if response.status_code != 200:
            return []

        rows = response.json()
        signals = []

        for row in rows:
            payload = row.get("payload")
            if isinstance(payload, dict):
                signals.append(payload)

        return list(reversed(signals))

    except Exception:
        return []


def supabase_count_signals():
    if not supabase_enabled():
        return {"enabled": False, "count": 0}

    url = f"{SUPABASE_URL}/rest/v1/trading_signals?select=id"

    try:
        headers = supabase_headers(None)
        headers["Prefer"] = "count=exact"
        response = requests.get(url, headers=headers, timeout=10)
        count_header = response.headers.get("content-range", "")

        return {
            "enabled": True,
            "status_code": response.status_code,
            "content_range": count_header,
            "ok": response.status_code in [200, 206],
        }

    except Exception as e:
        return {"enabled": True, "ok": False, "error": str(e)}


def load_signals_from_file():
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

    return []


def load_signals(limit=3000):
    supabase_signals = supabase_fetch_signals(limit=limit)

    if supabase_signals:
        return supabase_signals

    return load_signals_from_file()[-limit:]


def save_signal_file(signal):
    signals = load_signals_from_file()
    signals.append(signal)
    signals = signals[-10000:]

    with open(SIGNALS_FILE, "w") as f:
        json.dump(signals, f, indent=2)


def save_signal(signal):
    save_signal_file(signal)
    return supabase_insert_signal(signal)


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
        r'\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|NFLX|USTEC\.F|MNQ|NQ|ES|SPX|IWM|VIX|DXY)\b',
        raw_text,
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

        if received_dt.tzinfo is None:
            received_dt = received_dt.replace(tzinfo=timezone.utc)

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


def get_latest_field(timeframes, field, default=None):
    for tf in ["5m", "15m", "1h", "1d"]:
        if tf in timeframes and timeframes[tf].get(field) is not None:
            return timeframes[tf].get(field)
    return default


def rebuild_store_from_history():
    signals = load_signals(limit=3000)
    store = {}

    for signal in signals:
        ticker = str(signal.get("ticker", "UNKNOWN")).upper().strip()
        tf = normalize_timeframe(signal.get("timeframe", "unknown"))

        if ticker not in store:
            store[ticker] = {}

        store[ticker][tf] = signal

    return store


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
    elif state in ["WAIT", "MIXED", "NO_DATA", "EXPIRED_SETUP"]:
        score -= 15

    if alignment in ["bullish", "bearish"]:
        score += 5
    elif "partial" in alignment:
        score -= 3

    if freshness_weighted < 50:
        score -= 10

    return round(max(0, min(score, 100)), 2)


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

    technical_score = (
        (score_5 * 0.30)
        + (score_15 * 0.30)
        + (score_1h * 0.30)
        + (score_1d * 0.10)
    )

    freshness_weighted = (
        (fresh_5 * 0.30)
        + (fresh_15 * 0.30)
        + (fresh_1h * 0.30)
        + (fresh_1d * 0.10)
    )

    weighted_score = round((technical_score * 0.80) + (freshness_weighted * 0.20), 2)

    bullish_5 = "LONG" in setup_5 or "SELL PUT" in setup_5
    bearish_5 = "SHORT" in setup_5 or "SELL CALL" in setup_5

    bullish_15 = trend_15 == "bullish" or "LONG" in setup_15 or "SELL PUT" in setup_15
    bearish_15 = trend_15 == "bearish" or "SHORT" in setup_15 or "SELL CALL" in setup_15

    bullish_1h = trend_1h == "bullish"
    bearish_1h = trend_1h == "bearish"
    bullish_1d = trend_1d == "bullish"
    bearish_1d = trend_1d == "bearish"

    has_5 = bool(tf_5)
    has_15 = bool(tf_15)
    has_1h = bool(tf_1h)
    has_1d = bool(tf_1d)

    execution_window = inside_execution_window()
    session_state = market_session_state()

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

    if not execution_window and state in [
        "LONG_READY",
        "LONG_ACTIVE",
        "SHORT_READY",
        "SHORT_ACTIVE",
        "PRE_LONG",
        "PRE_SHORT",
    ]:
        state = "EXPIRED_SETUP"
        recommendation = "Ventana operativa cerrada para estrategias intradía."
        reason = "La oportunidad intradía quedó fuera de las primeras 2.5 horas posteriores a la apertura del mercado. Estrategias swing/theta se evalúan por separado en V5."
        grade = "C"
        conviction = "LOW"
        action = "WAIT"

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
    price = tf_5.get("price") or tf_15.get("price") or tf_1h.get("price") or tf_1d.get("price")

    missing = []
    if not has_1h:
        missing.append("1h")
    if not has_15:
        missing.append("15m")
    if not has_5:
        missing.append("5m")

    priority_score = calculate_priority_score(
        state,
        grade,
        conviction,
        weighted_score,
        freshness_weighted,
        alignment,
    )

    latest_data = {
        "price": price,
        "iv_rank": get_latest_field(active, "iv_rank"),
        "iv_percentile": get_latest_field(active, "iv_percentile"),
        "implied_volatility": get_latest_field(active, "implied_volatility"),
        "historical_volatility": get_latest_field(active, "historical_volatility"),
        "gamma_bias": get_latest_field(active, "gamma_bias"),
        "options_flow_bias": get_latest_field(active, "options_flow_bias"),
        "support_near": get_latest_field(active, "support_near"),
        "resistance_near": get_latest_field(active, "resistance_near"),
        "earnings_soon": get_latest_field(active, "earnings_soon"),
        "event_risk": get_latest_field(active, "event_risk"),
        "asset_class": get_latest_field(active, "asset_class", "EQUITY"),
        "strategy_hint": get_latest_field(active, "strategy_hint"),
    }

    return {
        "execution_window": execution_window,
        "session_state": session_state,
        "minutes_since_open": round(minutes_since_open(), 2),
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
        "price": price,
        "missing_timeframes": missing,
        "active_timeframes": active,
        "all_timeframes": timeframes,
        "tf_flags": {
            "has_5m": has_5,
            "has_15m": has_15,
            "has_1h": has_1h,
            "has_1d": has_1d,
            "bullish_5m": bullish_5,
            "bearish_5m": bearish_5,
            "bullish_15m": bullish_15,
            "bearish_15m": bearish_15,
            "bullish_1h": bullish_1h,
            "bearish_1h": bearish_1h,
            "bullish_1d": bullish_1d,
            "bearish_1d": bearish_1d,
        },
        "latest_data": latest_data,
    }


def strategy_selection(classification):
    state = classification["state"]
    grade = classification["grade"]

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

    if state == "EXPIRED_SETUP":
        return {
            "primary_strategy": "Wait / Expired Intraday",
            "secondary_strategy": "Evaluar swing/theta por matriz V5 si el contexto aplica",
            "avoid": "Operar intradía fuera de ventana",
        }

    return {
        "primary_strategy": "Wait / No Trade",
        "secondary_strategy": "Capital preservation",
        "avoid": "Forzar operación sin edge",
    }


def v5_alignment_score(classification):
    alignment = classification.get("alignment", "mixed")
    missing = classification.get("missing_timeframes", [])

    if alignment in ["bullish", "bearish"] and not missing:
        return 100
    if alignment in ["bullish", "bearish"] and "5m" in missing:
        return 80
    if alignment in ["bullish_context", "bearish_context"]:
        return 60
    if "partial" in alignment:
        return 65

    return 25


def probability_engine(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state", "NO_DATA")
    priority = safe_float(classification.get("priority_score"), 0)
    freshness = safe_float(classification.get("freshness_weighted"), 0)
    alignment_score = v5_alignment_score(classification)

    base = 45
    base += (priority - 50) * 0.28
    base += (alignment_score - 50) * 0.18
    base += (freshness - 50) * 0.10

    if state in ["LONG_READY", "SHORT_READY"]:
        base += 8
    elif state in ["LONG_ACTIVE", "SHORT_ACTIVE"]:
        base += 6
    elif state in ["PRE_LONG", "PRE_SHORT"]:
        base += 2
    elif state in ["EXTENDED_LONG", "EXTENDED_SHORT"]:
        base -= 10
    elif state in ["WAIT", "NO_DATA", "MIXED", "EXPIRED_SETUP"]:
        base -= 12

    if regime in ["STRONG_BULL", "BULL", "BEAR"]:
        base += 3
    elif regime in ["CHOP", "RANGE"]:
        base -= 5
    elif regime == "PANIC":
        base -= 4

    probability = round(max(5, min(base, 92)), 1)

    if probability >= 80:
        confidence = "HIGH"
    elif probability >= 68:
        confidence = "MEDIUM_HIGH"
    elif probability >= 56:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    risk = (
        "LOW"
        if probability >= 78 and state not in ["EXTENDED_LONG", "EXTENDED_SHORT"]
        else "MEDIUM"
        if probability >= 60
        else "HIGH"
    )

    return {
        "probability_estimate": probability,
        "confidence": confidence,
        "risk": risk,
        "alignment_score": alignment_score,
        "note": "Heurístico interno V5 basado en score, alineación, frescura, régimen y matriz por estrategia. Aún no usa APIs reales de IV/flow/gamma.",
    }


def risk_engine(classification, regime="MIXED_OR_CHOP", strategy_name="NO_TRADE", window_required=False):
    state = classification.get("state", "NO_DATA")
    missing = classification.get("missing_timeframes", [])
    priority = safe_float(classification.get("priority_score"), 0)

    warnings = []
    allowed = True

    if state in ["NO_DATA", "WAIT", "MIXED"]:
        warnings.append("No hay edge suficiente.")
        allowed = False

    if state in ["EXTENDED_LONG", "EXTENDED_SHORT"]:
        warnings.append("Movimiento extendido: no perseguir.")
        allowed = False

    if state == "EXPIRED_SETUP" and window_required:
        warnings.append("Ventana operativa intradía cerrada.")
        allowed = False

    if window_required and not classification.get("execution_window", False):
        warnings.append("Estrategia requiere ventana inicial de 2.5 horas.")
        allowed = False

    if "5m" in missing and strategy_name in ["INTRADAY_BREAKOUT", "FUTURES"]:
        warnings.append("Falta gatillo 5m para estrategia intradía/futuros.")
        allowed = False

    if regime in ["CHOP", "RANGE"] and priority < 85 and strategy_name in ["INTRADAY_BREAKOUT", "FUTURES"]:
        warnings.append("Régimen de mercado reduce edge para intradía/futuros.")
        allowed = False

    if priority < 60 and strategy_name not in ["COVERED_CALL", "EARNINGS"]:
        warnings.append("Priority score insuficiente.")
        allowed = False

    return {
        "trade_allowed": allowed,
        "risk_level": "LOW" if allowed and priority >= 85 else "MEDIUM" if priority >= 70 else "HIGH",
        "warnings": warnings,
        "capital_preservation_bias": not allowed,
    }


def expected_pl_engine(classification, account_size=None):
    priority = safe_float(classification.get("priority_score"), 0)
    entry = safe_float(classification.get("entry"), 0)
    stop = safe_float(classification.get("stop"), 0)

    risk_budget = (account_size * 0.01) if account_size else 1000

    if entry and stop and abs(entry - stop) > 0:
        unit_risk = abs(entry - stop)
        units = math.floor(risk_budget / unit_risk)
    else:
        units = None

    base = round((priority - 50) * 12, 2)

    return {
        "base_case_pl": base,
        "favorable_case_pl": round(base * 2.0, 2),
        "adverse_case_pl": round(-risk_budget, 2),
        "risk_budget_assumption": risk_budget,
        "suggested_units_if_entry_stop_available": units,
        "note": "P/L conceptual V5. Requiere contrato/opción/cartera para cálculo monetario real.",
    }


def theta_engine(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state")
    priority = classification.get("priority_score", 0)
    data = classification.get("latest_data", {})
    iv_rank = safe_float(data.get("iv_rank"), None)
    support_near = safe_bool(data.get("support_near"), False)
    resistance_near = safe_bool(data.get("resistance_near"), False)
    price = safe_float(data.get("price"), 0)

    naked_put_bias = "NEUTRAL"
    covered_call_bias = "NEUTRAL"

    if state in ["PRE_LONG", "LONG_READY", "LONG_ACTIVE", "PARTIAL_LONG", "EXPIRED_SETUP"] and regime in [
        "STRONG_BULL",
        "BULL",
        "MIXED_OR_CHOP",
        "RISK_ON",
    ]:
        if priority >= 70 and (iv_rank is None or iv_rank >= 30) and (not price or price >= MIN_PRICE_FOR_THETA):
            naked_put_bias = "FAVORABLE" if support_near or iv_rank is None or iv_rank >= 50 else "WATCH"
        else:
            naked_put_bias = "WATCH"

    if state in ["EXTENDED_LONG", "PRE_SHORT", "SHORT_READY", "SHORT_ACTIVE", "PARTIAL_SHORT"]:
        covered_call_bias = "FAVORABLE_IF_HOLDING_SHARES" if resistance_near or state == "EXTENDED_LONG" else "WATCH"

    if state in ["PRE_SHORT", "SHORT_READY", "SHORT_ACTIVE", "PARTIAL_SHORT"]:
        naked_put_bias = "AVOID"

    return {
        "naked_put_bias": naked_put_bias,
        "covered_call_bias": covered_call_bias,
        "preferred_condition": "Naked put requiere tendencia no bajista, soporte, precio >100 ideal e IV suficiente. Covered call requiere posición, extensión o resistencia.",
    }


def market_regime():
    spy = classify_asset(trade_store.get("SPY", {})) if "SPY" in trade_store else None
    qqq = classify_asset(trade_store.get("QQQ", {})) if "QQQ" in trade_store else None
    tlt = classify_asset(trade_store.get("TLT", {})) if "TLT" in trade_store else None
    iwm = classify_asset(trade_store.get("IWM", {})) if "IWM" in trade_store else None
    vix = classify_asset(trade_store.get("VIX", {})) if "VIX" in trade_store else None
    dxy = classify_asset(trade_store.get("DXY", {})) if "DXY" in trade_store else None

    bullish = 0
    bearish = 0
    partial = 0

    for item in [spy, qqq, iwm]:
        if item:
            if item["alignment"] in ["bullish", "bullish_context", "partial_bullish"]:
                bullish += 1
            if item["alignment"] in ["bearish", "bearish_context", "partial_bearish"]:
                bearish += 1
            if "partial" in item["alignment"]:
                partial += 1

    vix_risk = bool(vix and vix.get("alignment") in ["bullish", "bullish_context", "partial_bullish"])

    if bullish >= 2 and bearish == 0 and not vix_risk:
        regime = "STRONG_BULL" if qqq and qqq.get("priority_score", 0) >= 75 else "BULL"
        summary = "Índices principales muestran sesgo alcista."
    elif bearish >= 2 and bullish == 0 and vix_risk:
        regime = "PANIC"
        summary = "Índices bajistas con VIX presionando."
    elif bearish >= 2 and bullish == 0:
        regime = "BEAR"
        summary = "Índices principales muestran sesgo bajista."
    elif bullish >= 1 and bearish >= 1:
        regime = "CHOP"
        summary = "Lectura mixta entre índices; riesgo de falsas rupturas."
    elif partial >= 2:
        regime = "RANGE"
        summary = "Señales parciales; mercado en posible rango."
    else:
        regime = "MIXED_OR_CHOP"
        summary = "No hay alineación clara entre índices principales."

    return {
        "regime": regime,
        "summary": summary,
        "spy": spy,
        "qqq": qqq,
        "tlt": tlt,
        "iwm": iwm,
        "vix": vix,
        "dxy": dxy,
    }


def strategy_matrix_v5(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state", "NO_DATA")
    score = safe_float(classification.get("weighted_score"), 0)
    priority = safe_float(classification.get("priority_score"), 0)
    flags = classification.get("tf_flags", {})
    data = classification.get("latest_data", {})

    has_5 = flags.get("has_5m", False)
    has_15 = flags.get("has_15m", False)
    has_1h = flags.get("has_1h", False)
    has_1d = flags.get("has_1d", False)

    bullish_5 = flags.get("bullish_5m", False)
    bullish_15 = flags.get("bullish_15m", False)
    bullish_1h = flags.get("bullish_1h", False)
    bullish_1d = flags.get("bullish_1d", False)
    bearish_5 = flags.get("bearish_5m", False)
    bearish_15 = flags.get("bearish_15m", False)
    bearish_1h = flags.get("bearish_1h", False)
    bearish_1d = flags.get("bearish_1d", False)

    price = safe_float(data.get("price"), 0)
    iv_rank = safe_float(data.get("iv_rank"), None)
    support_near = safe_bool(data.get("support_near"), False)
    resistance_near = safe_bool(data.get("resistance_near"), False)
    earnings_soon = safe_bool(data.get("earnings_soon"), False)
    event_risk = safe_bool(data.get("event_risk"), False)
    asset_class = str(data.get("asset_class", "EQUITY")).upper()
    strategy_hint = str(data.get("strategy_hint") or "").upper()

    candidates = []

    def add_candidate(name, decision, reason, score_boost=0, window_required=False):
        probability = probability_engine(classification, regime)
        risk = risk_engine(classification, regime, name, window_required)
        candidates.append({
            "strategy": name,
            "decision": decision,
            "reason": reason,
            "score": round(priority + score_boost, 2),
            "requires_window": window_required,
            "probability": probability,
            "risk": risk,
        })

    if has_1h and has_15 and has_5 and ((bullish_1h and bullish_15 and bullish_5) or (bearish_1h and bearish_15 and bearish_5)):
        if classification.get("execution_window") and score >= 80:
            add_candidate("INTRADAY_BREAKOUT", "OPERAR", "1h + 15m + 5m alineados dentro de la ventana inicial.", 12, True)
        elif score >= 75:
            add_candidate("INTRADAY_BREAKOUT", "EXPIRADO", "Setup intradía válido, pero fuera de la ventana inicial de 2.5 horas.", -10, True)
        else:
            add_candidate("INTRADAY_BREAKOUT", "RADAR", "Alineación intradía incompleta o score insuficiente.", 0, True)

    if bullish_1h and (bullish_1d or not has_1d) and score >= 70:
        decision = "OPERAR" if score >= 78 and state not in ["EXTENDED_LONG"] else "RADAR"
        add_candidate("SWING_LONG", decision, "Contexto 1h alcista y 1d alcista/neutro. No requiere ventana de apertura.", 8, False)

    if bearish_1h and bearish_1d and score >= 70:
        decision = "OPERAR" if score >= 78 and regime in ["BEAR", "PANIC", "MIXED_OR_CHOP"] else "RADAR"
        add_candidate("SWING_SHORT", decision, "Contexto 1h y 1d bajista. No requiere ventana de apertura.", 8, False)

    theta = theta_engine(classification, regime)
    if theta["naked_put_bias"] in ["FAVORABLE", "WATCH"]:
        naked_put_ok = (
            not bearish_1h
            and not bearish_1d
            and priority >= 60
            and (not price or price >= MIN_PRICE_FOR_THETA)
            and (iv_rank is None or iv_rank >= 30)
            and not event_risk
        )
        if naked_put_ok and (support_near or iv_rank is None or iv_rank >= 50):
            add_candidate("NAKED_PUT", "OPERAR", "Tendencia no bajista, score aceptable, precio/IV adecuados y soporte favorable.", 9, False)
        elif naked_put_ok:
            add_candidate("NAKED_PUT", "ESPERAR", "Contexto posible para naked put, pero falta soporte claro o IV más atractiva.", 2, False)
        else:
            add_candidate("NAKED_PUT", "EVITAR", "No cumple condiciones mínimas de tendencia, precio, IV o riesgo de evento.", -15, False)

    if theta["covered_call_bias"] in ["FAVORABLE_IF_HOLDING_SHARES", "WATCH"]:
        if state in ["EXTENDED_LONG"] or resistance_near:
            add_candidate("COVERED_CALL", "OPERAR", "Activo extendido o resistencia cercana; candidato para covered call si ya tienes acciones.", 6, False)
        else:
            add_candidate("COVERED_CALL", "RADAR", "Posible covered call, pero falta resistencia/extensión clara.", 0, False)

    if earnings_soon:
        if iv_rank is not None and iv_rank >= 50 and not event_risk:
            add_candidate("EARNINGS", "OPERAR", "Earnings próximo con IV alta; evaluar estrategia definida de earnings.", 5, False)
        else:
            add_candidate("EARNINGS", "ESPERAR", "Earnings próximo, pero falta IV suficientemente alta o hay riesgo de evento.", -2, False)

    if asset_class in ["FUTURE", "FUTURES"] or strategy_hint in ["FUTURES", "FUTURE", "MNQ", "NQ", "ES"]:
        if has_1h and has_15 and has_5 and score >= 75:
            add_candidate("FUTURES", "OPERAR" if classification.get("session_state") in ["OPEN_WINDOW", "AFTER_INITIAL_WINDOW"] else "RADAR", "Futuros con alineación multi-timeframe; requiere gestión por sesión.", 6, False)
        else:
            add_candidate("FUTURES", "RADAR", "Futuros en observación; falta alineación completa.", 0, False)

    if not candidates:
        add_candidate("NO_TRADE", "ESPERAR", "No hay estrategia V5 con edge suficiente.", -20, False)

    preferred_order = {"OPERAR": 5, "RADAR": 4, "ESPERAR": 3, "EXPIRADO": 2, "EVITAR": 1}
    candidates = sorted(candidates, key=lambda x: (preferred_order.get(x["decision"], 0), x["score"]), reverse=True)
    best = candidates[0]

    return {
        "primary": best,
        "candidates": candidates,
        "final_decision": best["decision"],
        "strategy": best["strategy"],
        "reason": best["reason"],
        "requires_window": best["requires_window"],
    }


def strategy_selection_v5(classification, regime="MIXED_OR_CHOP"):
    base = strategy_selection(classification)
    probability = probability_engine(classification, regime)
    theta = theta_engine(classification, regime)
    expected_pl = expected_pl_engine(classification)
    matrix = strategy_matrix_v5(classification, regime)
    primary = matrix["primary"]
    risk = primary["risk"]

    return {
        **base,
        "strategy_score": primary["score"],
        "probability": probability,
        "theta": theta,
        "risk": risk,
        "expected_pl": expected_pl,
        "strategy_matrix": matrix,
        "final_decision": matrix["final_decision"],
        "v5_strategy": matrix["strategy"],
        "v5_reason": matrix["reason"],
    }


def build_dashboard():
    dashboard = []
    regime_info = market_regime()
    regime = regime_info.get("regime", "MIXED_OR_CHOP")

    for ticker, timeframes in trade_store.items():
        c = classify_asset(timeframes)
        strategy = strategy_selection_v5(c, regime)

        dashboard.append(
            {
                "ticker": ticker,
                "execution_window": c["execution_window"],
                "session_state": c["session_state"],
                "minutes_since_open": c["minutes_since_open"],
                "state": c["state"],
                "grade": c["grade"],
                "conviction": c["conviction"],
                "action": c["action"],
                "strategy_type": c["strategy_type"],
                "primary_strategy": strategy["primary_strategy"],
                "secondary_strategy": strategy["secondary_strategy"],
                "avoid": strategy["avoid"],
                "strategy_score": strategy["strategy_score"],
                "v5_strategy": strategy["v5_strategy"],
                "final_decision": strategy["final_decision"],
                "v5_reason": strategy["v5_reason"],
                "theta": strategy["theta"],
                "probability": strategy["probability"],
                "risk": strategy["risk"],
                "expected_pl": strategy["expected_pl"],
                "strategy_matrix": strategy["strategy_matrix"],
                "alignment": c["alignment"],
                "alignment_score": strategy["probability"]["alignment_score"],
                "weighted_score": c["weighted_score"],
                "priority_score": c["priority_score"],
                "freshness_weighted": c["freshness_weighted"],
                "recommendation": c["recommendation"],
                "reason": c["reason"],
                "missing_timeframes": c["missing_timeframes"],
                "latest_data": c.get("latest_data", {}),
            }
        )

    decision_order = {"OPERAR": 5, "RADAR": 4, "ESPERAR": 3, "EXPIRADO": 2, "EVITAR": 1}
    return sorted(
        dashboard,
        key=lambda x: (decision_order.get(x["final_decision"], 0), x["strategy_score"], x["priority_score"]),
        reverse=True,
    )


def stats_from_signals(signals):
    by_ticker = {}
    by_timeframe = {}
    by_setup = {}
    by_state = {}
    by_decision = {}

    for s in signals:
        ticker = str(s.get("ticker", "UNKNOWN")).upper()
        timeframe = str(s.get("timeframe", "unknown"))
        setup = str(s.get("setup", "WAIT"))
        state = str(s.get("state", "NO_DATA"))
        decision = str(s.get("final_decision", "UNKNOWN"))

        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
        by_timeframe[timeframe] = by_timeframe.get(timeframe, 0) + 1
        by_setup[setup] = by_setup.get(setup, 0) + 1
        by_state[state] = by_state.get(state, 0) + 1
        by_decision[decision] = by_decision.get(decision, 0) + 1

    return {
        "total_signals": len(signals),
        "by_ticker": by_ticker,
        "by_timeframe": by_timeframe,
        "by_setup": by_setup,
        "by_state": by_state,
        "by_decision": by_decision,
    }


def verify_webhook_secret(x_webhook_secret: Optional[str]):
    if REQUIRE_WEBHOOK_SECRET:
        if not WEBHOOK_SECRET:
            raise HTTPException(status_code=500, detail="WEBHOOK_SECRET required but not configured")
        if x_webhook_secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")


@app.on_event("startup")
def startup():
    global trade_store
    trade_store = rebuild_store_from_history()


@app.get("/")
def root():
    return {
        "status": "alive",
        "engine": "Super Engine Bolsa v5.0",
        "mode": "Strategy Matrix Decision Core",
    }


@app.get("/health")
def health():
    signals = load_signals(limit=100)

    return {
        "status": "ok",
        "engine": "Super Engine Bolsa v5.0",
        "mode": "Strategy Matrix Decision Core",
        "supabase_enabled": supabase_enabled(),
        "webhook_secret_required": REQUIRE_WEBHOOK_SECRET,
        "total_recent_signals_loaded": len(signals),
        "tickers_in_memory": list(trade_store.keys()),
        "last_signal": signals[-1] if signals else None,
        "expiration_minutes": EXPIRATION_MINUTES,
        "market_clock": {
            "market_timezone": "America/New_York",
            "session_state": market_session_state(),
            "execution_window": inside_execution_window(),
            "minutes_since_open": minutes_since_open(),
            "initial_window_minutes": INITIAL_WINDOW_MINUTES,
        },
    }


@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request, x_webhook_secret: Optional[str] = Header(default=None)):
    verify_webhook_secret(x_webhook_secret)

    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="ignore").strip()

    parsed = extract_json_from_text(raw_text)

    if not isinstance(parsed, dict):
        parsed = {
            "raw_message": raw_text,
            "parse_warning": "payload not valid json",
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

    classification = classify_asset(trade_store[ticker])
    regime = market_regime().get("regime", "MIXED_OR_CHOP")
    strategy = strategy_selection_v5(classification, regime)

    parsed["state"] = classification["state"]
    parsed["grade"] = classification["grade"]
    parsed["conviction"] = classification["conviction"]
    parsed["priority_score"] = classification["priority_score"]
    parsed["execution_window"] = classification["execution_window"]
    parsed["session_state"] = classification["session_state"]
    parsed["final_decision"] = strategy["final_decision"]
    parsed["v5_strategy"] = strategy["v5_strategy"]

    trade_store[ticker][timeframe] = parsed

    storage_result = save_signal(parsed)

    return {
        "status": "ok",
        "engine": "v5.0",
        "message": f"Webhook received for {ticker} {timeframe}",
        "ticker": ticker,
        "timeframe": timeframe,
        "storage": storage_result,
        "classification": classification,
        "strategy": strategy,
        "data": parsed,
    }


@app.post("/test_signal")
def test_signal(signal: TradingSignal):
    parsed = signal.dict(exclude_none=True)

    if parsed.get("extra"):
        parsed.update(parsed.pop("extra"))

    ticker = find_ticker(parsed, json.dumps(parsed))
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))

    parsed["ticker"] = ticker
    parsed["timeframe"] = timeframe
    parsed["received_at"] = now_utc().isoformat()
    parsed["saved_at"] = now_utc().isoformat()
    parsed["source"] = "manual_test"

    if ticker not in trade_store:
        trade_store[ticker] = {}

    trade_store[ticker][timeframe] = parsed

    classification = classify_asset(trade_store[ticker])
    regime = market_regime().get("regime", "MIXED_OR_CHOP")
    strategy = strategy_selection_v5(classification, regime)

    parsed["state"] = classification["state"]
    parsed["grade"] = classification["grade"]
    parsed["conviction"] = classification["conviction"]
    parsed["priority_score"] = classification["priority_score"]
    parsed["execution_window"] = classification["execution_window"]
    parsed["session_state"] = classification["session_state"]
    parsed["final_decision"] = strategy["final_decision"]
    parsed["v5_strategy"] = strategy["v5_strategy"]

    trade_store[ticker][timeframe] = parsed

    storage_result = save_signal(parsed)

    return {
        "status": "ok",
        "engine": "v5.0",
        "message": f"Test signal saved for {ticker} {timeframe}",
        "storage": storage_result,
        "classification": classification,
        "strategy": strategy,
        "data": parsed,
    }


@app.get("/get_trade_context")
def get_trade_context(ticker: str):
    ticker = ticker.upper().strip()

    if ticker not in trade_store:
        return {
            "ticker": ticker,
            "status": "missing_data",
            "message": "No hay datos todavía para este ticker.",
        }

    c = classify_asset(trade_store[ticker])
    regime = market_regime().get("regime", "MIXED_OR_CHOP")
    c["strategy_selection"] = strategy_selection_v5(c, regime)

    return {
        "ticker": ticker,
        "engine": "v5.0",
        "classification": c,
    }


@app.get("/get_dashboard")
def get_dashboard():
    dashboard = build_dashboard()

    for i, item in enumerate(dashboard, start=1):
        item["priority_rank"] = i

    return {
        "generated_at": now_utc().isoformat(),
        "engine": "v5.0",
        "supabase_enabled": supabase_enabled(),
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
    lines.append("SUPER ENGINE BOLSA v5.0 — STRATEGY MATRIX DECISION CORE")
    lines.append(f"Generado UTC: {now_utc().isoformat()}")
    lines.append("")
    lines.append("RÉGIMEN DE MERCADO")
    lines.append(f"- Estado: {regime['regime']}")
    lines.append(f"- Lectura: {regime['summary']}")
    lines.append(f"- Sesión: {market_session_state()}")
    lines.append(f"- Minutos desde apertura: {round(minutes_since_open(), 1)}")
    lines.append(f"- Ventana intradía activa: {inside_execution_window()}")
    lines.append("")

    if not dashboard:
        lines.append("No hay señales suficientes todavía.")

        return {
            "generated_at": now_utc().isoformat(),
            "engine": "v5.0",
            "report": "\n".join(lines),
            "dashboard": [],
        }

    operar = [x for x in dashboard if x["final_decision"] == "OPERAR"]
    radar = [x for x in dashboard if x["final_decision"] == "RADAR"]
    esperar = [x for x in dashboard if x["final_decision"] == "ESPERAR"]
    evitar = [x for x in dashboard if x["final_decision"] == "EVITAR"]
    expirado = [x for x in dashboard if x["final_decision"] == "EXPIRADO"]

    lines.append("RESUMEN EJECUTIVO")
    lines.append(f"- OPERAR: {len(operar)}")
    lines.append(f"- RADAR: {len(radar)}")
    lines.append(f"- ESPERAR: {len(esperar)}")
    lines.append(f"- EVITAR: {len(evitar)}")
    lines.append(f"- EXPIRADO: {len(expirado)}")
    lines.append("")

    lines.append("TOP PRIORITY SETUPS")
    for x in dashboard[:5]:
        lines.append(
            f"{x['priority_rank']}. {x['ticker']} | {x['final_decision']} | {x['v5_strategy']} | "
            f"{x['grade']} | {x['conviction']} | {x['state']} | Priority {x['priority_score']} | "
            f"Prob {x['probability']['probability_estimate']}% | Risk {x['risk']['risk_level']} | {x['v5_reason']}"
        )

    lines.append("")

    if operar:
        lines.append("OPERAR")
        for x in operar:
            lines.append(
                f"- {x['ticker']} | {x['v5_strategy']} | {x['grade']} | {x['conviction']} | "
                f"Priority {x['priority_score']} | {x['v5_reason']}"
            )
        lines.append("")

    if radar:
        lines.append("RADAR")
        for x in radar:
            lines.append(f"- {x['ticker']} | {x['v5_strategy']} | {x['v5_reason']}")
        lines.append("")

    if expirado:
        lines.append("EXPIRADO")
        for x in expirado:
            lines.append(f"- {x['ticker']} | {x['v5_strategy']} | {x['v5_reason']}")
        lines.append("")

    if evitar:
        lines.append("EVITAR")
        for x in evitar:
            lines.append(f"- {x['ticker']} | {x['v5_strategy']} | {x['v5_reason']}")

    return {
        "generated_at": now_utc().isoformat(),
        "engine": "v5.0",
        "supabase_enabled": supabase_enabled(),
        "report": "\n".join(lines),
        "dashboard": dashboard,
        "best_setups": dashboard[:5],
    }


@app.get("/gpt_report")
def gpt_report():
    dashboard = build_dashboard()
    regime = market_regime()
    best = dashboard[0] if dashboard else None

    if not best:
        return {
            "engine": "v5.0",
            "market": regime["regime"],
            "status": "NO_DATA",
            "best_setup": None,
            "plan": "Esperar nuevas señales frescas.",
        }

    return {
        "engine": "v5.0",
        "market_regime": regime["regime"],
        "market_summary": regime["summary"],
        "session_state": market_session_state(),
        "execution_window": inside_execution_window(),
        "minutes_since_open": minutes_since_open(),
        "top_focus": [
            {
                "ticker": x["ticker"],
                "decision": x["final_decision"],
                "strategy": x["v5_strategy"],
                "grade": x["grade"],
                "conviction": x["conviction"],
                "priority_score": x["priority_score"],
                "probability": x["probability"]["probability_estimate"],
                "risk": x["risk"]["risk_level"],
                "trade_allowed": x["risk"]["trade_allowed"],
                "reason": x["v5_reason"],
                "warnings": x["risk"].get("warnings", []),
            }
            for x in dashboard[:5]
        ],
        "operate_now": [x for x in dashboard if x["final_decision"] == "OPERAR"][:5],
        "radar": [x for x in dashboard if x["final_decision"] == "RADAR"][:5],
        "avoid": [x for x in dashboard if x["final_decision"] in ["EVITAR", "EXPIRADO"]][:5],
        "best_setup": f"{best['ticker']} {best['final_decision']} {best['v5_strategy']}",
        "plan": best["v5_reason"],
    }


@app.post("/position_sizing")
def position_sizing(req: PositionSizingRequest):
    risk_budget = req.account_size * (req.risk_percent / 100)
    unit_risk = abs(req.entry - req.stop)

    if unit_risk <= 0:
        return {"error": "Entry and stop cannot be equal."}

    return {
        "engine": "v5.0",
        "account_size": req.account_size,
        "risk_percent": req.risk_percent,
        "risk_budget": round(risk_budget, 2),
        "entry": req.entry,
        "stop": req.stop,
        "unit_risk": round(unit_risk, 4),
        "suggested_units": math.floor(risk_budget / unit_risk),
    }


@app.post("/evaluate_option")
def evaluate_option(req: OptionEvalRequest):
    ticker = req.ticker.upper().strip()
    context = classify_asset(trade_store.get(ticker, {})) if ticker in trade_store else None
    regime = market_regime().get("regime", "MIXED_OR_CHOP")

    margin_yield = None

    if req.premium and req.margin_required and req.margin_required > 0:
        margin_yield = round((req.premium / req.margin_required) * 100, 2)

    iv_comment = "IV no proporcionada."

    if req.iv_rank is not None:
        if req.iv_rank >= 50:
            iv_comment = "IV rank favorable para venta de prima."
        elif req.iv_rank >= 30:
            iv_comment = "IV rank moderada; venta de prima condicional."
        else:
            iv_comment = "IV rank baja; prima puede no compensar riesgo."

    dictamen = "No recomendable: falta contexto técnico reciente."
    strategy_context = None

    if context:
        latest = context.get("latest_data", {})
        if req.iv_rank is not None:
            latest["iv_rank"] = req.iv_rank
        if req.price is not None:
            latest["price"] = req.price
        if req.support_near is not None:
            latest["support_near"] = req.support_near
        if req.resistance_near is not None:
            latest["resistance_near"] = req.resistance_near
        if req.earnings_soon is not None:
            latest["earnings_soon"] = req.earnings_soon
        context["latest_data"] = latest

        matrix = strategy_matrix_v5(context, regime)
        strategy_context = matrix

        if req.strategy.upper() in ["NAKED_PUT", "SELL_PUT"]:
            naked = [c for c in matrix["candidates"] if c["strategy"] == "NAKED_PUT"]
            if naked and naked[0]["decision"] == "OPERAR":
                dictamen = "Favorable/condicional para naked put: revisar strike, soporte, IV, DTE y assignment risk."
            elif naked:
                dictamen = f"{naked[0]['decision']}: {naked[0]['reason']}"
            else:
                dictamen = "No hay edge claro para naked put."

        elif req.strategy.upper() in ["COVERED_CALL", "SELL_CALL"]:
            cc = [c for c in matrix["candidates"] if c["strategy"] == "COVERED_CALL"]
            if cc and cc[0]["decision"] == "OPERAR":
                dictamen = "Favorable/condicional para covered call si ya existe posición y resistencia clara."
            elif cc:
                dictamen = f"{cc[0]['decision']}: {cc[0]['reason']}"
            else:
                dictamen = "No hay edge claro para covered call."

        else:
            dictamen = f"Dictamen matriz V5: {matrix['final_decision']} / {matrix['strategy']} — {matrix['reason']}"

    return {
        "engine": "v5.0",
        "ticker": ticker,
        "strategy": req.strategy,
        "strike": req.strike,
        "premium": req.premium,
        "dte": req.dte,
        "margin_required": req.margin_required,
        "premium_on_margin_percent": margin_yield,
        "iv_rank": req.iv_rank,
        "iv_comment": iv_comment,
        "context_available": context is not None,
        "technical_context": context,
        "strategy_context": strategy_context,
        "dictamen": dictamen,
    }


@app.get("/latest")
def latest():
    return trade_store


@app.get("/history")
def history(limit: int = 100):
    signals = load_signals(limit=limit)

    return {
        "engine": "v5.0",
        "supabase_enabled": supabase_enabled(),
        "showing": min(limit, len(signals)),
        "signals": signals[-limit:],
    }


@app.get("/stats")
def stats(limit: int = 1000):
    signals = load_signals(limit=limit)

    return {
        "engine": "v5.0",
        "generated_at": now_utc().isoformat(),
        "stats": stats_from_signals(signals),
    }


@app.get("/stats/ticker/{ticker}")
def stats_ticker(ticker: str, limit: int = 1000):
    ticker = ticker.upper().strip()
    signals = [
        s
        for s in load_signals(limit=limit)
        if str(s.get("ticker", "")).upper() == ticker
    ]

    return {
        "engine": "v5.0",
        "ticker": ticker,
        "generated_at": now_utc().isoformat(),
        "stats": stats_from_signals(signals),
        "signals": signals[-50:],
    }


@app.get("/debug/supabase")
def debug_supabase():
    return {
        "engine": "v5.0",
        "supabase_enabled": supabase_enabled(),
        "supabase_url_present": bool(SUPABASE_URL),
        "supabase_key_present": bool(SUPABASE_KEY),
        "count_test": supabase_count_signals(),
    }


@app.get("/debug/regime")
def debug_regime():
    return {
        "engine": "v5.0",
        "market_regime": market_regime(),
        "market_clock": {
            "market_timezone": "America/New_York",
            "session_state": market_session_state(),
            "execution_window": inside_execution_window(),
            "minutes_since_open": minutes_since_open(),
            "initial_window_minutes": INITIAL_WINDOW_MINUTES,
        },
    }


@app.get("/debug/scoring")
def debug_scoring(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()

    if ticker not in trade_store:
        return {
            "engine": "v5.0",
            "ticker": ticker,
            "error": "Ticker not in memory",
        }

    regime = market_regime().get("regime", "MIXED_OR_CHOP")
    c = classify_asset(trade_store[ticker])

    return {
        "engine": "v5.0",
        "ticker": ticker,
        "classification": c,
        "strategy": strategy_selection_v5(c, regime),
        "probability": probability_engine(c, regime),
        "risk": risk_engine(c, regime),
        "theta": theta_engine(c, regime),
        "expected_pl": expected_pl_engine(c),
        "strategy_matrix": strategy_matrix_v5(c, regime),
    }


@app.get("/debug/routes")
def debug_routes():
    return {
        "engine": "v5.0",
        "routes": [
            "/",
            "/health",
            "/webhook/tradingview",
            "/test_signal",
            "/get_trade_context",
            "/get_dashboard",
            "/get_report",
            "/gpt_report",
            "/position_sizing",
            "/evaluate_option",
            "/latest",
            "/history",
            "/stats",
            "/stats/ticker/{ticker}",
            "/debug/supabase",
            "/debug/regime",
            "/debug/scoring",
            "/debug/routes",
            "/dashboard_html",
        ],
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

    decision_color = {
        "OPERAR": "#0B6E4F",
        "RADAR": "#2A9D8F",
        "ESPERAR": "#F4A261",
        "EVITAR": "#E76F51",
        "EXPIRADO": "#6C757D",
    }

    for i, item in enumerate(dashboard, start=1):
        grade_color = color_map.get(item["grade"], "#999")
        d_color = decision_color.get(item["final_decision"], "#999")
        prob = item.get("probability", {}).get("probability_estimate", "")
        risk = item.get("risk", {}).get("risk_level", "")
        allowed = item.get("risk", {}).get("trade_allowed", False)
        theta = item.get("theta", {}).get("naked_put_bias", "")

        rows += f"""
        <tr>
            <td>{i}</td>
            <td>{item['ticker']}</td>
            <td style="background:{d_color}; color:white; font-weight:bold;">{item['final_decision']}</td>
            <td>{item['v5_strategy']}</td>
            <td style="background:{grade_color}; color:white; font-weight:bold;">{item['grade']}</td>
            <td>{item['conviction']}</td>
            <td>{item['state']}</td>
            <td>{theta}</td>
            <td>{prob}%</td>
            <td>{risk}</td>
            <td>{allowed}</td>
            <td>{item['priority_score']}</td>
            <td>{item['weighted_score']}</td>
            <td>{item['alignment']}</td>
            <td>{item['execution_window']}</td>
            <td>{item['minutes_since_open']}</td>
            <td>{item['v5_reason']}</td>
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
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; font-size: 13px; }}
            th {{ background: #111; color: white; }}
            .regime {{ padding: 15px; background: white; margin-bottom: 20px; border-left: 5px solid #111; }}
            .meta {{ font-size: 13px; color: #555; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <h1>Super Engine Bolsa v5.0</h1>
        <div class="meta">Supabase enabled: {supabase_enabled()} | Webhook secret required: {REQUIRE_WEBHOOK_SECRET}</div>
        <div class="regime">
            <b>Market Regime:</b> {regime['regime']}<br>
            <b>Lectura:</b> {regime['summary']}<br>
            <b>Sesión:</b> {market_session_state()}<br>
            <b>Ventana intradía activa:</b> {inside_execution_window()}<br>
            <b>Minutos desde apertura:</b> {minutes_since_open()}
        </div>
        <table>
            <tr>
                <th>Rank</th>
                <th>Ticker</th>
                <th>Decision</th>
                <th>V5 Strategy</th>
                <th>Grade</th>
                <th>Conviction</th>
                <th>State</th>
                <th>Theta</th>
                <th>Prob</th>
                <th>Risk</th>
                <th>Allowed</th>
                <th>Priority</th>
                <th>Score</th>
                <th>Alignment</th>
                <th>Window</th>
                <th>Min Open</th>
                <th>Reason</th>
            </tr>
            {rows}
        </table>
    </body>
    </html>
    """

    return html

