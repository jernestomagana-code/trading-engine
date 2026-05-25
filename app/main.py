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

# ============================================================
# SUPER ENGINE BOLSA — APP MAIN V8
# Unified Decision Engine:
# TradingView + IBKR + Strategy Commander + GPT Report
# ============================================================

app = FastAPI(title="Super Engine Bolsa", version="8.0.0")

SIGNALS_FILE = "signals_history.json"
OUTCOMES_FILE = "trade_outcomes.json"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
REQUIRE_WEBHOOK_SECRET = os.getenv("REQUIRE_WEBHOOK_SECRET", "false").lower() == "true"
OPERATING_MODE = os.getenv("OPERATING_MODE", "ANALYSIS_ONLY")

EXPIRATION_MINUTES = {
    "5m": 25,
    "15m": 90,
    "1h": 360,
    "1d": 1440,
}

TECHNICAL_TIMEFRAMES = ["5m", "15m", "1h", "1d"]
IBKR_LAYERS = ["live", "position", "options", "portfolio"]

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0
INITIAL_WINDOW_MINUTES = 150
MIN_PRICE_FOR_THETA = 100

# Iron Condor PRO rules
IRON_CONDOR_ALLOWED_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]
IRON_CONDOR_DTE_MIN = 35
IRON_CONDOR_DTE_MAX = 45
IRON_CONDOR_IVR_MIN = 40
IRON_CONDOR_IVR_MAX = 70
IRON_CONDOR_VIX_MIN = 16
IRON_CONDOR_VIX_MAX = 24
IRON_CONDOR_VIX_IDEAL_MIN = 18
IRON_CONDOR_VIX_IDEAL_MAX = 22
IRON_CONDOR_RSI_MIN = 45
IRON_CONDOR_RSI_MAX = 55
IRON_CONDOR_ADX_MAX = 22
IRON_CONDOR_SHORT_DELTA_MIN = 0.15
IRON_CONDOR_SHORT_DELTA_MAX = 0.20
IRON_CONDOR_CREDIT_WIDTH_MIN = 0.25

trade_store: Dict[str, Dict[str, Dict[str, Any]]] = {}


# ============================================================
# MODELS
# ============================================================

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
    has_position: Optional[bool] = Field(default=None)
    position_delta: Optional[float] = Field(default=None)
    exposure_usd: Optional[float] = Field(default=None)
    asset_class: Optional[str] = Field(default="EQUITY")
    strategy_hint: Optional[str] = Field(default=None)
    volume_relative: Optional[float] = Field(default=None)
    rsi: Optional[float] = Field(default=None)
    macd_state: Optional[str] = Field(default=None)
    adx: Optional[float] = Field(default=None)
    vwap_position: Optional[str] = Field(default=None)
    range_20d: Optional[bool] = Field(default=None)
    range_breakout: Optional[bool] = Field(default=None)
    institutional_flow_bias: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)
    grade: Optional[str] = Field(default=None)
    conviction: Optional[str] = Field(default=None)
    priority_score: Optional[float] = Field(default=None)
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


class PortfolioInput(BaseModel):
    account_size: Optional[float] = None
    cash_available: Optional[float] = None
    net_liquidation: Optional[float] = None
    buying_power: Optional[float] = None
    open_naked_puts: Optional[int] = 0
    open_covered_calls: Optional[int] = 0
    open_futures: Optional[int] = 0
    directional_bias: Optional[str] = "NEUTRAL"
    notes: Optional[str] = None


# ============================================================
# TIME / UTILS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def now_market():
    return datetime.now(MARKET_TZ)


def market_open_today():
    now = now_market()
    return now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)


def market_close_today():
    now = now_market()
    return now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)


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
        return "OPEN_WINDOW" if inside_execution_window() else "AFTER_INITIAL_WINDOW"
    return "CLOSED"


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
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


def decision_rank(decision):
    return {
        "OPERAR": 6,
        "RADAR": 5,
        "WAIT_FOR_GREEKS": 4,
        "ESPERAR": 3,
        "MISSING_DATA": 2,
        "BLOCKED": 1,
        "EVITAR": 1,
        "EXPIRADO": 1,
        "NO_OPERAR_SIN_PRECIO": 1,
    }.get(str(decision).upper(), 0)


def normalize_timeframe(tf):
    tf_raw = str(tf or "unknown").lower().strip()

    if tf_raw in ["live", "position", "options", "portfolio"]:
        return tf_raw

    tf = tf_raw.replace("min", "").replace("m", "").strip()

    if tf == "5":
        return "5m"
    if tf == "15":
        return "15m"
    if tf in ["60", "1h", "h"]:
        return "1h"
    if tf in ["d", "1d", "day"]:
        return "1d"

    return tf_raw or "unknown"


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

    match = re.search(r'"ticker"\s*:\s*"([^"]+)"', raw_text)
    if match:
        return match.group(1).upper().strip()

    match = re.search(
        r'\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|NFLX|USTEC\.F|MNQ|NQ|ES|SPX|IWM|DIA|VIX|DXY)\b',
        raw_text,
    )

    return match.group(1).upper().strip() if match else "UNKNOWN"


# ============================================================
# STORAGE
# ============================================================

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
        return {"enabled": True, "saved": False, "status_code": response.status_code, "error": response.text[:800]}
    except Exception as e:
        return {"enabled": True, "saved": False, "error": str(e)}


def supabase_fetch_signals(limit=3000):
    if not supabase_enabled():
        return []

    url = f"{SUPABASE_URL}/rest/v1/trading_signals?select=payload&order=received_at.desc&limit={limit}"

    try:
        response = requests.get(url, headers=supabase_headers(None), timeout=10)
        if response.status_code != 200:
            return []

        signals = []
        for row in response.json():
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
        return {
            "enabled": True,
            "status_code": response.status_code,
            "content_range": response.headers.get("content-range", ""),
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


def save_signal_file(signal):
    signals = load_signals_from_file()
    signals.append(signal)
    signals = signals[-10000:]

    with open(SIGNALS_FILE, "w") as f:
        json.dump(signals, f, indent=2)

    return True


def load_signals(limit=3000):
    supabase_signals = supabase_fetch_signals(limit=limit)
    if supabase_signals:
        return supabase_signals
    return load_signals_from_file()[-limit:]


def save_signal(signal):
    save_signal_file(signal)
    return supabase_insert_signal(signal)


def load_outcomes_from_file():
    if os.path.exists(OUTCOMES_FILE):
        try:
            with open(OUTCOMES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_outcome_file(outcome):
    outcomes = load_outcomes_from_file()
    outcome = dict(outcome)
    outcome["recorded_at"] = now_utc().isoformat()
    outcome["id"] = f"OUT-{len(outcomes) + 1}-{outcome.get('ticker', 'UNKNOWN')}-{int(now_utc().timestamp())}"
    outcomes.append(outcome)
    outcomes = outcomes[-10000:]

    with open(OUTCOMES_FILE, "w") as f:
        json.dump(outcomes, f, indent=2)

    return outcome


def outcome_stats(outcomes):
    closed = [
        o for o in outcomes
        if str(o.get("outcome", "")).upper() in ["WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"]
    ]

    wins = [o for o in closed if str(o.get("outcome", "")).upper() == "WIN"]
    losses = [o for o in closed if str(o.get("outcome", "")).upper() == "LOSS"]
    breakeven = [o for o in closed if str(o.get("outcome", "")).upper() == "BREAKEVEN"]

    pnl_values = [safe_float(o.get("pnl"), 0) for o in closed if o.get("pnl") is not None]
    gross_profit = sum(x for x in pnl_values if x > 0)
    gross_loss = abs(sum(x for x in pnl_values if x < 0))

    by_strategy = {}
    by_ticker = {}

    for o in outcomes:
        strategy = str(o.get("strategy", "UNKNOWN")).upper()
        ticker = str(o.get("ticker", "UNKNOWN")).upper()
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1
        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1

    return {
        "total_outcomes": len(outcomes),
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": round((len(wins) / max(len(wins) + len(losses), 1)) * 100, 2),
        "net_pnl": round(sum(pnl_values), 2),
        "avg_pnl": round(sum(pnl_values) / len(pnl_values), 2) if pnl_values else 0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "by_strategy": by_strategy,
        "by_ticker": by_ticker,
    }


# ============================================================
# MEMORY STORE
# ============================================================

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
        if tf not in TECHNICAL_TIMEFRAMES:
            continue

        enriched = enrich_signal(signal, tf)

        if not enriched["expired"]:
            active[tf] = enriched

    return active


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


# ============================================================
# TECHNICAL CORE
# ============================================================

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


def technical_core(timeframes):
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

    bullish_1d = trend_1d == "bullish"
    bearish_1d = trend_1d == "bearish"

    has_5 = bool(tf_5)
    has_15 = bool(tf_15)
    has_1h = bool(tf_1h)
    has_1d = bool(tf_1d)

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
            state, strategy_type, alignment = "PRE_LONG", "swing_theta_radar", "bullish_context"
            reason = "1h bullish fresco, falta confirmación 15m y gatillo 5m."
            recommendation = "Radar alcista temprano. No ejecutar todavía."
        elif bearish_1h:
            state, strategy_type, alignment = "PRE_SHORT", "short_or_covered_call_radar", "bearish_context"
            reason = "1h bearish fresco, falta confirmación 15m y gatillo 5m."
            recommendation = "Radar bajista temprano. No ejecutar todavía."
        else:
            state = "MIXED"
            reason = "1h fresco pero sin dirección clara."

    elif has_1h and has_15 and not has_5:
        if bullish_1h and bullish_15:
            state, strategy_type, alignment = "PRE_LONG", "swing_theta_radar", "bullish"
            reason = "1h y 15m bullish. Falta gatillo fresco de 5m."
            recommendation = "Preparar swing long o naked put; esperar gatillo 5m."
        elif bearish_1h and bearish_15:
            state, strategy_type, alignment = "PRE_SHORT", "short_or_covered_call_radar", "bearish"
            reason = "1h y 15m bearish. Falta gatillo fresco de 5m."
            recommendation = "Preparar short táctico o covered call; esperar gatillo 5m."
        else:
            state = "MIXED"
            reason = "1h y 15m no están alineados."

    elif has_1h and has_15 and has_5:
        if bullish_1h and bullish_15 and bullish_5:
            action, alignment, strategy_type = setup_5, "bullish", "swing_long_theta_or_intraday_a"

            if score_5 >= 90 and fresh_5 >= 75:
                state, reason = "LONG_ACTIVE", "Momentum alcista activo con 1h, 15m y 5m alineados."
            elif score_5 >= 80:
                state, reason = "LONG_READY", "Confluencia alcista multi-timeframe con gatillo 5m."
            else:
                state, reason = "PARTIAL_LONG", "Alineación alcista, pero el gatillo 5m no tiene suficiente fuerza."

            recommendation = "Evaluar swing long, intradía A/A+ o timing para naked put; validar riesgo e invalidación."

        elif bearish_1h and bearish_15 and bearish_5:
            action, alignment, strategy_type = setup_5, "bearish", "short_tactical_or_sell_call"

            if score_5 >= 90 and fresh_5 >= 75:
                state, reason = "SHORT_ACTIVE", "Momentum bajista activo con 1h, 15m y 5m alineados."
            elif score_5 >= 80:
                state, reason = "SHORT_READY", "Confluencia bajista multi-timeframe con gatillo 5m."
            else:
                state, reason = "PARTIAL_SHORT", "Alineación bajista, pero el gatillo 5m no tiene suficiente fuerza."

            recommendation = "Evaluar short táctico o covered call/sell call; validar riesgo e invalidación."

        elif bullish_1h and bullish_5 and not bullish_15:
            state, action, alignment, strategy_type = "PARTIAL_LONG", setup_5, "partial_bullish", "partial_radar"
            reason = "1h y 5m alcistas, pero falta confirmación 15m."
            recommendation = "No ejecutar agresivo; esperar confirmación 15m."

        elif bearish_1h and bearish_5 and not bearish_15:
            state, action, alignment, strategy_type = "PARTIAL_SHORT", setup_5, "partial_bearish", "partial_radar"
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

    if action != "WAIT":
        if weighted_score >= 88 and conviction in ["VERY_HIGH", "HIGH"]:
            grade = "A+"
        elif weighted_score >= 80:
            grade = "A"
        elif weighted_score >= 70:
            grade = "B"
    else:
        if state in ["PRE_LONG", "PRE_SHORT"] and weighted_score >= 70:
            grade = "B"

    if state == "LONG_ACTIVE" and score_5 >= 95:
        state = "EXTENDED_LONG"
        recommendation = "No perseguir. Esperar pullback o nueva base."
        reason = "Momentum alcista fuerte pero potencialmente extendido."

    if state == "SHORT_ACTIVE" and score_5 >= 95:
        state = "EXTENDED_SHORT"
        recommendation = "No perseguir. Esperar rebote o nueva base."
        reason = "Momentum bajista fuerte pero potencialmente extendido."

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
        alignment
    )

    price = tf_5.get("price") or tf_15.get("price") or tf_1h.get("price") or tf_1d.get("price")

    latest_data = {
        "price": price,
        "entry": tf_5.get("entry") or tf_5.get("price") or tf_15.get("price") or tf_1h.get("price"),
        "stop": tf_5.get("stop"),
        "target": tf_5.get("target"),
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
        "has_position": get_latest_field(active, "has_position"),
        "position_delta": get_latest_field(active, "position_delta"),
        "exposure_usd": get_latest_field(active, "exposure_usd"),
        "asset_class": get_latest_field(active, "asset_class", "EQUITY"),
        "strategy_hint": get_latest_field(active, "strategy_hint"),
        "rsi": get_latest_field(active, "rsi"),
        "adx": get_latest_field(active, "adx"),
        "range_20d": get_latest_field(active, "range_20d"),
        "range_breakout": get_latest_field(active, "range_breakout"),
        "institutional_flow_bias": get_latest_field(active, "institutional_flow_bias"),
    }

    return {
        "execution_window": inside_execution_window(),
        "session_state": market_session_state(),
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
        "entry": latest_data["entry"],
        "stop": latest_data["stop"],
        "target": latest_data["target"],
        "price": price,
        "missing_timeframes": missing,
        "active_timeframes": active,
        "all_timeframes": {k: v for k, v in timeframes.items() if k in TECHNICAL_TIMEFRAMES},
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


# ============================================================
# CONTEXT HELPERS — V8
# ============================================================

def get_technical_context(ticker: str):
    ticker = ticker.upper().strip()
    raw = trade_store.get(ticker, {})
    technical_layers = {k: v for k, v in raw.items() if k in TECHNICAL_TIMEFRAMES}

    if not technical_layers:
        return {
            "available": False,
            "ticker": ticker,
            "message": "No technical TradingView context available.",
            "classification": technical_core({}),
        }

    classification = technical_core(technical_layers)

    return {
        "available": True,
        "ticker": ticker,
        "layers": technical_layers,
        "classification": classification,
    }


def get_ibkr_context(ticker: str):
    ticker = ticker.upper().strip()
    raw = trade_store.get(ticker, {})

    live = raw.get("live")
    position = raw.get("position")
    options = raw.get("options")
    portfolio = raw.get("portfolio")

    return {
        "available": bool(live or position or options or portfolio),
        "ticker": ticker,
        "live": live,
        "position": position,
        "options": options,
        "portfolio": portfolio,
        "latest_price": safe_float((live or {}).get("price"), None) if live else None,
        "price_source": (live or {}).get("price_source") if live else None,
        "position_class": (position or {}).get("position_class") if position else None,
        "sec_type": (position or {}).get("sec_type") if position else None,
        "position_size": safe_float((position or {}).get("position_size"), None) if position else None,
        "market_value": safe_float((position or {}).get("market_value"), None) if position else None,
        "unrealized_pl": safe_float((position or {}).get("unrealized_pl"), None) if position else None,
        "option_strategy_hint": (options or {}).get("strategy_hint") if options else None,
        "option_decision": (options or {}).get("strategy_decision") if options else None,
        "option_data_quality": (options or {}).get("data_quality") if options else None,
        "option_dte": safe_float((options or {}).get("dte"), None) if options else None,
        "option_delta": safe_float((options or {}).get("delta"), None) if options else None,
        "option_iv": safe_float((options or {}).get("implied_volatility"), None) if options else None,
        "option_mid": safe_float((options or {}).get("mid"), None) if options else None,
        "option_spread_pct": safe_float((options or {}).get("spread_pct"), None) if options else None,
        "option_strike": safe_float((options or {}).get("strike"), None) if options else None,
        "option_type": (options or {}).get("option_type") if options else None,
    }


def get_market_context():
    vix_context = get_technical_context("VIX")
    vix_price = None

    if vix_context.get("available"):
        vix_price = safe_float(vix_context["classification"].get("price"), None)

    return {
        "vix": vix_price,
        "session_state": market_session_state(),
        "execution_window": inside_execution_window(),
        "minutes_since_open": minutes_since_open(),
        "market_regime": market_regime().get("regime", "MIXED_OR_CHOP"),
    }


def build_unified_context(ticker: str):
    ticker = ticker.upper().strip()
    technical = get_technical_context(ticker)
    ibkr = get_ibkr_context(ticker)
    market = get_market_context()

    commander = strategy_commander(ticker, technical, ibkr, market)

    return {
        "ticker": ticker,
        "generated_at": now_utc().isoformat(),
        "technical_context": technical,
        "ibkr_context": ibkr,
        "market_context": market,
        "strategy_commander": commander,
    }


# ============================================================
# MARKET REGIME / PROBABILITY / RISK
# ============================================================

def v6_alignment_score(classification):
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


def market_regime():
    spy = technical_core(trade_store.get("SPY", {})) if "SPY" in trade_store else None
    qqq = technical_core(trade_store.get("QQQ", {})) if "QQQ" in trade_store else None
    tlt = technical_core(trade_store.get("TLT", {})) if "TLT" in trade_store else None
    iwm = technical_core(trade_store.get("IWM", {})) if "IWM" in trade_store else None
    vix = technical_core(trade_store.get("VIX", {})) if "VIX" in trade_store else None
    dxy = technical_core(trade_store.get("DXY", {})) if "DXY" in trade_store else None

    bullish = bearish = partial = 0

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


def probability_engine(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state", "NO_DATA")
    priority = safe_float(classification.get("priority_score"), 0)
    freshness = safe_float(classification.get("freshness_weighted"), 0)
    alignment_score = v6_alignment_score(classification)

    base = 45 + (priority - 50) * 0.28 + (alignment_score - 50) * 0.18 + (freshness - 50) * 0.10

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
    confidence = "HIGH" if probability >= 80 else "MEDIUM_HIGH" if probability >= 68 else "MEDIUM" if probability >= 56 else "LOW"
    risk = "LOW" if probability >= 78 and state not in ["EXTENDED_LONG", "EXTENDED_SHORT"] else "MEDIUM" if probability >= 60 else "HIGH"

    return {
        "probability_estimate": probability,
        "confidence": confidence,
        "risk": risk,
        "alignment_score": alignment_score,
    }


def expected_pl_engine(classification, account_size=None):
    priority = safe_float(classification.get("priority_score"), 0)
    entry = safe_float(classification.get("entry"), 0)
    stop = safe_float(classification.get("stop"), 0)
    risk_budget = (account_size * 0.01) if account_size else 1000
    units = math.floor(risk_budget / abs(entry - stop)) if entry and stop and abs(entry - stop) > 0 else None
    base = round((priority - 50) * 12, 2)

    return {
        "base_case_pl": base,
        "favorable_case_pl": round(base * 2, 2),
        "adverse_case_pl": round(-risk_budget, 2),
        "risk_budget_assumption": risk_budget,
        "suggested_units_if_entry_stop_available": units,
    }


# ============================================================
# LEGACY BRAINS
# ============================================================

def build_brains(classification, regime="MIXED_OR_CHOP"):
    flags = classification.get("tf_flags", {})
    data = classification.get("latest_data", {})
    score = safe_float(classification.get("weighted_score"), 0)
    priority = safe_float(classification.get("priority_score"), 0)
    price = safe_float(data.get("price"), 0)
    iv_rank = safe_float(data.get("iv_rank"), None)
    support = safe_bool(data.get("support_near"), False)
    resistance = safe_bool(data.get("resistance_near"), False)
    event_risk = safe_bool(data.get("event_risk"), False)
    earnings_soon = safe_bool(data.get("earnings_soon"), False)
    has_position = safe_bool(data.get("has_position"), False)
    asset_class = str(data.get("asset_class", "EQUITY")).upper()
    hint = str(data.get("strategy_hint") or "").upper()

    has_5 = flags.get("has_5m", False)
    has_15 = flags.get("has_15m", False)
    has_1h = flags.get("has_1h", False)

    bull5 = flags.get("bullish_5m", False)
    bull15 = flags.get("bullish_15m", False)
    bull1h = flags.get("bullish_1h", False)
    bull1d = flags.get("bullish_1d", False)

    bear5 = flags.get("bearish_5m", False)
    bear15 = flags.get("bearish_15m", False)
    bear1h = flags.get("bearish_1h", False)
    bear1d = flags.get("bearish_1d", False)

    brains = {}

    if has_5 and has_15 and has_1h and ((bull5 and bull15 and bull1h) or (bear5 and bear15 and bear1h)):
        if classification.get("execution_window") and score >= 80:
            intraday = {
                "state": "VALID",
                "decision": "OPERAR",
                "score": priority + 12,
                "reason": "1h + 15m + 5m alineados dentro de ventana intradía.",
            }
        elif score >= 75:
            intraday = {
                "state": "EXPIRED",
                "decision": "EXPIRADO",
                "score": priority - 10,
                "reason": "Setup intradía válido, pero fuera de la ventana inicial.",
            }
        else:
            intraday = {
                "state": "FORMING",
                "decision": "RADAR",
                "score": priority,
                "reason": "Alineación intradía parcial o score insuficiente.",
            }
    else:
        intraday = {
            "state": "NO_EDGE",
            "decision": "ESPERAR",
            "score": priority - 20,
            "reason": "No hay alineación 1h + 15m + 5m para intradía.",
        }

    brains["intraday"] = {
        "strategy": "INTRADAY_BREAKOUT",
        "requires_window": True,
        **intraday,
    }

    if bull1h and (bull1d or not flags.get("has_1d", False)) and score >= 70:
        decision = "OPERAR" if score >= 78 and classification.get("state") != "EXTENDED_LONG" else "RADAR"
        swing = {
            "state": "BULLISH",
            "decision": decision,
            "score": priority + 8,
            "reason": "Contexto 1h alcista con 1d alcista/neutro.",
        }
    elif bear1h and bear1d and score >= 70:
        decision = "OPERAR" if score >= 78 else "RADAR"
        swing = {
            "state": "BEARISH",
            "decision": decision,
            "score": priority + 8,
            "reason": "Contexto 1h y 1d bajista.",
        }
    else:
        swing = {
            "state": "NO_EDGE",
            "decision": "ESPERAR",
            "score": priority - 10,
            "reason": "No hay contexto swing suficiente.",
        }

    brains["swing"] = {
        "strategy": "SWING",
        "requires_window": False,
        **swing,
    }

    if not bear1h and not bear1d and priority >= 60 and (not price or price >= MIN_PRICE_FOR_THETA) and (iv_rank is None or iv_rank >= 30) and not event_risk:
        if support or (iv_rank is not None and iv_rank >= 50):
            theta_np = {
                "state": "NAKED_PUT_FAVORABLE",
                "decision": "OPERAR",
                "score": priority + 9,
                "reason": "Naked put favorable: tendencia no bajista, soporte/IV adecuados.",
            }
        else:
            theta_np = {
                "state": "NAKED_PUT_WATCH",
                "decision": "ESPERAR",
                "score": priority + 2,
                "reason": "Naked put posible, falta soporte claro o IV más atractiva.",
            }
    else:
        theta_np = {
            "state": "NAKED_PUT_AVOID",
            "decision": "EVITAR",
            "score": priority - 15,
            "reason": "No cumple condiciones mínimas para naked put.",
        }

    if has_position and (classification.get("state") == "EXTENDED_LONG" or resistance):
        theta_cc = {
            "state": "COVERED_CALL_FAVORABLE",
            "decision": "OPERAR",
            "score": priority + 6,
            "reason": "Covered call favorable si ya tienes acciones y hay resistencia/extensión.",
        }
    elif resistance or classification.get("state") == "EXTENDED_LONG":
        theta_cc = {
            "state": "COVERED_CALL_RADAR",
            "decision": "RADAR",
            "score": priority,
            "reason": "Covered call en radar; confirmar posición o resistencia.",
        }
    else:
        theta_cc = {
            "state": "COVERED_CALL_NEUTRAL",
            "decision": "ESPERAR",
            "score": priority - 5,
            "reason": "Sin extensión/resistencia suficiente para covered call.",
        }

    selected_theta = theta_np if decision_rank(theta_np["decision"]) >= decision_rank(theta_cc["decision"]) else theta_cc

    brains["theta"] = {
        "strategy": "THETA",
        "requires_window": False,
        "naked_put": theta_np,
        "covered_call": theta_cc,
        **selected_theta,
    }

    if earnings_soon:
        if iv_rank is not None and iv_rank >= 50 and not event_risk:
            earnings = {
                "state": "EARNINGS_IV_HIGH",
                "decision": "OPERAR",
                "score": priority + 5,
                "reason": "Earnings próximo con IV alta; evaluar play definido.",
            }
        else:
            earnings = {
                "state": "EARNINGS_WAIT",
                "decision": "ESPERAR",
                "score": priority - 2,
                "reason": "Earnings próximo, pero IV insuficiente o riesgo elevado.",
            }
    else:
        earnings = {
            "state": "NO_EVENT",
            "decision": "ESPERAR",
            "score": priority - 10,
            "reason": "No hay evento de earnings próximo.",
        }

    brains["earnings"] = {
        "strategy": "EARNINGS",
        "requires_window": False,
        **earnings,
    }

    if asset_class in ["FUTURE", "FUTURES"] or hint in ["FUTURES", "FUTURE", "MNQ", "NQ", "ES"]:
        if has_5 and has_15 and has_1h and score >= 75:
            futures = {
                "state": "FUTURES_READY",
                "decision": "OPERAR",
                "score": priority + 6,
                "reason": "Futuros con alineación multi-timeframe; gestionar por sesión.",
            }
        else:
            futures = {
                "state": "FUTURES_RADAR",
                "decision": "RADAR",
                "score": priority,
                "reason": "Futuros en observación; falta alineación completa.",
            }
    else:
        futures = {
            "state": "NOT_FUTURES",
            "decision": "ESPERAR",
            "score": priority - 20,
            "reason": "Activo no marcado como futuro.",
        }

    brains["futures"] = {
        "strategy": "FUTURES",
        "requires_window": False,
        **futures,
    }

    candidates = [brains[k] for k in ["intraday", "swing", "theta", "earnings", "futures"]]
    final = sorted(candidates, key=lambda x: (decision_rank(x["decision"]), x["score"]), reverse=True)[0]

    brains["final"] = {
        "final_decision": final["decision"],
        "strategy": final["strategy"],
        "state": final["state"],
        "score": round(final["score"], 2),
        "reason": final["reason"],
    }

    return brains


def risk_engine(classification, regime="MIXED_OR_CHOP", brain=None):
    brain = brain or {
        "strategy": "NO_TRADE",
        "requires_window": False,
        "decision": "ESPERAR",
    }

    priority = safe_float(classification.get("priority_score"), 0)
    warnings = []
    allowed = True

    if brain.get("decision") not in ["OPERAR"]:
        allowed = False

    if brain.get("requires_window") and not classification.get("execution_window", False):
        warnings.append("Estrategia requiere ventana inicial de 2.5 horas.")
        allowed = False

    if classification.get("state") in ["EXTENDED_LONG", "EXTENDED_SHORT"] and brain.get("strategy") in ["INTRADAY_BREAKOUT", "SWING"]:
        warnings.append("Movimiento extendido: no perseguir direccionalmente.")
        allowed = False

    if regime in ["CHOP", "RANGE"] and priority < 85 and brain.get("strategy") in ["INTRADAY_BREAKOUT", "FUTURES"]:
        warnings.append("Régimen reduce edge para intradía/futuros.")
        allowed = False

    if safe_bool(classification.get("latest_data", {}).get("event_risk"), False) and brain.get("strategy") in ["NAKED_PUT", "THETA"]:
        warnings.append("Riesgo de evento: evitar venta de prima sin compensación suficiente.")
        allowed = False

    if priority < 60 and brain.get("strategy") not in ["COVERED_CALL", "EARNINGS", "THETA"]:
        warnings.append("Priority score insuficiente.")
        allowed = False

    return {
        "trade_allowed": allowed,
        "risk_level": "LOW" if allowed and priority >= 85 else "MEDIUM" if priority >= 70 else "HIGH",
        "warnings": warnings,
        "capital_preservation_bias": not allowed,
    }


def classify_asset(timeframes):
    core = technical_core(timeframes)
    regime = market_regime().get("regime", "MIXED_OR_CHOP")
    brains = build_brains(core, regime)
    probability = probability_engine(core, regime)
    risk = risk_engine(core, regime, brains.get("final"))

    core["brains"] = brains
    core["final_decision"] = brains["final"]["final_decision"]
    core["v6_strategy"] = brains["final"]["strategy"]
    core["v6_state"] = brains["final"]["state"]
    core["v6_reason"] = brains["final"]["reason"]
    core["master_score"] = round(
        (safe_float(core.get("priority_score"), 0) * 0.45)
        + (safe_float(brains["final"].get("score"), 0) * 0.35)
        + (probability["probability_estimate"] * 0.20),
        2,
    )
    core["probability"] = probability
    core["risk"] = risk
    core["expected_pl"] = expected_pl_engine(core)

    return core


# ============================================================
# STRATEGY COMMANDER PRO — V8
# ============================================================

def module_result(strategy, state, decision, score, reason, blockers=None, missing_data=None, details=None):
    return {
        "strategy": strategy,
        "state": state,
        "decision": decision,
        "score": round(max(0, min(score, 100)), 2),
        "reason": reason,
        "blockers": blockers or [],
        "missing_data": missing_data or [],
        "details": details or {},
    }


def evaluate_naked_put_pro(ticker, technical, ibkr, market):
    c = technical.get("classification", {})
    latest = c.get("latest_data", {})
    option_hint = str(ibkr.get("option_strategy_hint") or "").upper()
    option_type = str(ibkr.get("option_type") or "").upper()

    blockers = []
    missing = []

    score = 50

    alignment = c.get("alignment", "mixed")
    priority = safe_float(c.get("priority_score"), 0)
    support = safe_bool(latest.get("support_near"), False)
    event_risk = safe_bool(latest.get("event_risk"), False)
    earnings = safe_bool(latest.get("earnings_soon"), False)
    price = safe_float(ibkr.get("latest_price") or c.get("price"), None)

    dte = ibkr.get("option_dte")
    delta = ibkr.get("option_delta")
    iv = ibkr.get("option_iv")
    mid = ibkr.get("option_mid")
    data_quality = ibkr.get("option_data_quality")
    ibkr_decision = str(ibkr.get("option_decision") or "").upper()

    if option_hint != "NAKED_PUT" and option_type != "PUT":
        blockers.append("No hay candidato IBKR Naked Put activo.")
        score -= 25

    if not technical.get("available"):
        missing.append("technical_context")
        score -= 10

    if not ibkr.get("available"):
        missing.append("ibkr_context")
        score -= 25

    if price is None:
        missing.append("underlying_price")
        score -= 10

    if dte is None:
        missing.append("dte")
        score -= 10
    elif 25 <= dte <= 65:
        score += 10
    else:
        score -= 10
        blockers.append("DTE fuera del rango ideal para Naked Put.")

    if delta is None:
        missing.append("delta")
        score -= 15
    else:
        abs_delta = abs(delta)
        if 0.12 <= abs_delta <= 0.25:
            score += 20
        elif 0.08 <= abs_delta < 0.12:
            score += 8
        else:
            score -= 15
            blockers.append("Delta fuera del rango ideal para Naked Put.")

    if iv is None:
        missing.append("iv")
        score -= 10
    elif iv >= 0.25:
        score += 8
    else:
        score -= 5

    if mid is None:
        missing.append("premium_mid")
        score -= 15
    elif mid >= 0.20:
        score += 8
    else:
        score -= 8

    if data_quality in ["NO_VALID_OPTION_PRICE", "OPTION_MARKET_DATA_ERROR", "PRICE_ONLY_NO_GREEKS"]:
        blockers.append(f"Calidad de datos insuficiente: {data_quality}")
        score -= 15

    if ibkr_decision in ["WAIT_FOR_GREEKS", "NO_OPERAR_SIN_PRECIO"]:
        blockers.append(f"IBKR bloquea operación: {ibkr_decision}")

    if event_risk:
        blockers.append("Event risk activo.")
        score -= 15

    if earnings:
        blockers.append("Earnings próximos.")
        score -= 15

    if alignment in ["bullish", "bullish_context", "partial_bullish"]:
        score += 8
    elif alignment in ["bearish", "bearish_context", "partial_bearish"]:
        score -= 15
        blockers.append("Contexto técnico bajista.")

    if support:
        score += 8

    if priority >= 70:
        score += 5

    if blockers:
        decision = "RADAR" if score >= 65 else "ESPERAR"
    elif missing:
        decision = "MISSING_DATA"
    elif score >= 82:
        decision = "OPERAR"
    elif score >= 65:
        decision = "RADAR"
    else:
        decision = "ESPERAR"

    return module_result(
        "NAKED_PUT_PRO",
        "EVALUATED",
        decision,
        score,
        "Evalúa venta de puts con soporte, tendencia no bajista, prima, delta e IV.",
        blockers,
        missing,
        {
            "alignment": alignment,
            "priority_score": priority,
            "dte": dte,
            "delta": delta,
            "iv": iv,
            "mid": mid,
            "data_quality": data_quality,
            "ibkr_decision": ibkr_decision,
        },
    )


def evaluate_covered_call_pro(ticker, technical, ibkr, market):
    c = technical.get("classification", {})
    latest = c.get("latest_data", {})
    option_hint = str(ibkr.get("option_strategy_hint") or "").upper()
    option_type = str(ibkr.get("option_type") or "").upper()
    position_class = str(ibkr.get("position_class") or "").upper()
    position_size = ibkr.get("position_size")

    blockers = []
    missing = []
    score = 50

    resistance = safe_bool(latest.get("resistance_near"), False)
    state = c.get("state", "NO_DATA")
    alignment = c.get("alignment", "mixed")
    priority = safe_float(c.get("priority_score"), 0)

    dte = ibkr.get("option_dte")
    delta = ibkr.get("option_delta")
    iv = ibkr.get("option_iv")
    mid = ibkr.get("option_mid")
    data_quality = ibkr.get("option_data_quality")
    ibkr_decision = str(ibkr.get("option_decision") or "").upper()

    if position_size is None:
        missing.append("position_size")
        score -= 15
    elif position_size >= 100:
        score += 20
    else:
        blockers.append("No hay al menos 100 acciones para covered call.")
        score -= 25

    if position_class != "COVERED_CALL_CANDIDATE":
        blockers.append("IBKR no marca la posición como candidata natural a covered call.")
        score -= 5

    if option_hint != "COVERED_CALL" and option_type != "CALL":
        blockers.append("No hay candidato IBKR Covered Call activo.")
        score -= 15

    if dte is None:
        missing.append("dte")
        score -= 10
    elif 25 <= dte <= 65:
        score += 8
    else:
        score -= 8

    if delta is None:
        missing.append("delta")
        score -= 15
    else:
        abs_delta = abs(delta)
        if 0.15 <= abs_delta <= 0.35:
            score += 20
        elif 0.08 <= abs_delta < 0.15:
            score += 8
        else:
            score -= 10
            blockers.append("Delta de call fuera del rango ideal.")

    if iv is None:
        missing.append("iv")
        score -= 8
    elif iv >= 0.20:
        score += 5

    if mid is None:
        missing.append("premium_mid")
        score -= 15
    elif mid >= 0.20:
        score += 8

    if resistance or state == "EXTENDED_LONG":
        score += 10

    if alignment in ["bearish", "bearish_context", "partial_bearish"]:
        score += 5
    elif alignment == "bullish" and state not in ["EXTENDED_LONG"]:
        blockers.append("Activo con sesgo alcista; cuidado con vender calls demasiado pronto.")
        score -= 5

    if data_quality in ["NO_VALID_OPTION_PRICE", "OPTION_MARKET_DATA_ERROR", "PRICE_ONLY_NO_GREEKS"]:
        blockers.append(f"Calidad de datos insuficiente: {data_quality}")
        score -= 15

    if ibkr_decision in ["WAIT_FOR_GREEKS", "NO_OPERAR_SIN_PRECIO"]:
        blockers.append(f"IBKR bloquea operación: {ibkr_decision}")

    if priority >= 70:
        score += 5

    if blockers:
        decision = "RADAR" if score >= 65 else "ESPERAR"
    elif missing:
        decision = "MISSING_DATA"
    elif score >= 82:
        decision = "OPERAR"
    elif score >= 65:
        decision = "RADAR"
    else:
        decision = "ESPERAR"

    return module_result(
        "COVERED_CALL_PRO",
        "EVALUATED",
        decision,
        score,
        "Evalúa venta de calls contra acciones existentes con resistencia/extensión y prima suficiente.",
        blockers,
        missing,
        {
            "position_size": position_size,
            "position_class": position_class,
            "dte": dte,
            "delta": delta,
            "iv": iv,
            "mid": mid,
            "data_quality": data_quality,
            "ibkr_decision": ibkr_decision,
        },
    )


def evaluate_iron_condor_pro(ticker, technical, ibkr, market):
    c = technical.get("classification", {})
    latest = c.get("latest_data", {})

    blockers = []
    missing = []
    score = 50

    ticker = ticker.upper()
    if ticker in IRON_CONDOR_ALLOWED_TICKERS:
        score += 15
    else:
        blockers.append("Activo no está en la lista preferente para Iron Condor PRO.")
        score -= 25

    rsi = safe_float(latest.get("rsi"), None)
    adx = safe_float(latest.get("adx"), None)
    range_20d = latest.get("range_20d")
    range_breakout = latest.get("range_breakout")
    event_risk = safe_bool(latest.get("event_risk"), False)
    earnings_soon = safe_bool(latest.get("earnings_soon"), False)
    iv_rank = safe_float(latest.get("iv_rank"), None)
    institutional_flow_bias = str(latest.get("institutional_flow_bias") or latest.get("options_flow_bias") or "").upper()

    vix = market.get("vix")
    dte = ibkr.get("option_dte")
    delta = ibkr.get("option_delta")
    mid = ibkr.get("option_mid")
    data_quality = ibkr.get("option_data_quality")

    if dte is None:
        missing.append("dte")
        score -= 10
    elif IRON_CONDOR_DTE_MIN <= dte <= IRON_CONDOR_DTE_MAX:
        score += 15
    else:
        blockers.append("DTE fuera del rango 35–45.")
        score -= 15

    if iv_rank is None:
        missing.append("iv_rank")
        score -= 5
    elif IRON_CONDOR_IVR_MIN <= iv_rank <= IRON_CONDOR_IVR_MAX:
        score += 12
    else:
        blockers.append("IV Rank fuera del rango ideal 40–70.")
        score -= 12

    if vix is None:
        missing.append("vix")
        score -= 5
    elif IRON_CONDOR_VIX_MIN <= vix <= IRON_CONDOR_VIX_MAX:
        score += 10
        if IRON_CONDOR_VIX_IDEAL_MIN <= vix <= IRON_CONDOR_VIX_IDEAL_MAX:
            score += 5
    else:
        blockers.append("VIX fuera del rango ideal 16–24.")
        score -= 10

    if rsi is None:
        missing.append("rsi")
        score -= 5
    elif IRON_CONDOR_RSI_MIN <= rsi <= IRON_CONDOR_RSI_MAX:
        score += 10
    else:
        blockers.append("RSI no está entre 45 y 55.")
        score -= 10

    if adx is None:
        missing.append("adx")
        score -= 5
    elif adx <= IRON_CONDOR_ADX_MAX:
        score += 10
    else:
        blockers.append("ADX indica mercado demasiado direccional.")
        score -= 12

    if range_20d is None:
        missing.append("range_20d")
    elif safe_bool(range_20d):
        score += 10
    else:
        blockers.append("No hay rango claro de 20 días.")
        score -= 10

    if safe_bool(range_breakout):
        blockers.append("Ruptura de rango detectada.")
        score -= 15

    if earnings_soon:
        blockers.append("Earnings próximos.")
        score -= 15

    if event_risk:
        blockers.append("Evento macro o riesgo de evento activo.")
        score -= 15

    if institutional_flow_bias in ["BULLISH_AGGRESSIVE", "BEARISH_AGGRESSIVE", "AGGRESSIVE"]:
        blockers.append("Flujo institucional direccional agresivo.")
        score -= 12

    if delta is None:
        missing.append("short_strike_delta")
        score -= 8
    else:
        abs_delta = abs(delta)
        if IRON_CONDOR_SHORT_DELTA_MIN <= abs_delta <= IRON_CONDOR_SHORT_DELTA_MAX:
            score += 10
        else:
            blockers.append("Delta del short strike fuera del rango 0.15–0.20.")
            score -= 10

    if mid is None:
        missing.append("credit_or_mid")
        score -= 8
    elif mid > 0:
        score += 5

    if data_quality in ["NO_VALID_OPTION_PRICE", "OPTION_MARKET_DATA_ERROR", "PRICE_ONLY_NO_GREEKS"]:
        blockers.append(f"Calidad de datos insuficiente: {data_quality}")
        score -= 10

    if blockers:
        decision = "BLOCKED" if score < 60 else "RADAR"
    elif missing:
        decision = "MISSING_DATA" if score < 75 else "RADAR"
    elif score >= 85:
        decision = "OPERAR"
    elif score >= 70:
        decision = "RADAR"
    else:
        decision = "ESPERAR"

    return module_result(
        "IRON_CONDOR_PRO",
        "EVALUATED",
        decision,
        score,
        "Evalúa mercado lateral con IV adecuada, VIX controlado, RSI neutral, ADX bajo y strikes delta 0.15–0.20.",
        blockers,
        missing,
        {
            "rsi": rsi,
            "adx": adx,
            "range_20d": range_20d,
            "range_breakout": range_breakout,
            "iv_rank": iv_rank,
            "vix": vix,
            "dte": dte,
            "delta": delta,
            "mid": mid,
            "data_quality": data_quality,
            "institutional_flow_bias": institutional_flow_bias,
        },
    )


def evaluate_earnings_pro(ticker, technical, ibkr, market):
    c = technical.get("classification", {})
    latest = c.get("latest_data", {})
    earnings_soon = safe_bool(latest.get("earnings_soon"), False)
    iv_rank = safe_float(latest.get("iv_rank"), None)
    event_risk = safe_bool(latest.get("event_risk"), False)

    score = 40
    blockers = []
    missing = []

    if earnings_soon:
        score += 25
    else:
        blockers.append("No hay earnings próximos detectados.")
        score -= 10

    if iv_rank is None:
        missing.append("iv_rank")
        score -= 5
    elif iv_rank >= 50:
        score += 15
    elif iv_rank >= 30:
        score += 5
    else:
        blockers.append("IV Rank bajo para earnings play.")
        score -= 10

    if event_risk:
        blockers.append("Event risk adicional.")
        score -= 10

    decision = "RADAR" if earnings_soon and score >= 60 else "ESPERAR"
    if missing and decision == "RADAR":
        decision = "MISSING_DATA"

    return module_result(
        "EARNINGS_PRO",
        "EVALUATED",
        decision,
        score,
        "Evalúa si existe oportunidad de earnings basada en IV y riesgo definido.",
        blockers,
        missing,
        {
            "earnings_soon": earnings_soon,
            "iv_rank": iv_rank,
            "event_risk": event_risk,
        },
    )


def evaluate_futures_pro(ticker, technical, ibkr, market):
    c = technical.get("classification", {})
    latest = c.get("latest_data", {})
    asset_class = str(latest.get("asset_class") or ibkr.get("sec_type") or "").upper()
    hint = str(latest.get("strategy_hint") or "").upper()
    alignment = c.get("alignment", "mixed")
    score_base = safe_float(c.get("priority_score"), 0)

    is_future = ticker in ["MNQ", "NQ", "ES", "MES"] or asset_class in ["FUT", "FUTURE", "FUTURES"] or hint in ["FUTURES", "FUTURE"]

    blockers = []
    missing = []
    score = score_base

    if not is_future:
        blockers.append("Activo no identificado como futuro.")
        score -= 20

    if not technical.get("available"):
        missing.append("technical_context")
        score -= 20

    if c.get("execution_window"):
        score += 5

    if alignment in ["bullish", "bearish"]:
        score += 15
    elif "partial" in alignment:
        score += 5
    else:
        blockers.append("Sin alineación técnica clara para futuros.")
        score -= 10

    if score >= 80 and not blockers and not missing:
        decision = "OPERAR"
    elif score >= 65:
        decision = "RADAR"
    elif missing:
        decision = "MISSING_DATA"
    else:
        decision = "ESPERAR"

    return module_result(
        "FUTURES_PRO",
        "EVALUATED",
        decision,
        score,
        "Evalúa futuros por alineación técnica multi-timeframe y ventana de ejecución.",
        blockers,
        missing,
        {
            "asset_class": asset_class,
            "hint": hint,
            "alignment": alignment,
            "execution_window": c.get("execution_window"),
            "priority_score": score_base,
        },
    )


def evaluate_exit_manager(ticker, technical, ibkr, market):
    position_class = str(ibkr.get("position_class") or "").upper()
    unrealized_pl = ibkr.get("unrealized_pl")
    option_dte = ibkr.get("option_dte")
    option_delta = ibkr.get("option_delta")
    alignment = technical.get("classification", {}).get("alignment", "mixed")

    score = 50
    blockers = []
    missing = []
    alerts = []

    if not ibkr.get("position"):
        return module_result(
            "EXIT_MANAGER",
            "NO_POSITION_DATA",
            "ESPERAR",
            30,
            "No hay datos suficientes de posición para evaluar salida o roll.",
            [],
            ["position_context"],
            {},
        )

    if unrealized_pl is not None:
        if unrealized_pl > 0:
            score += 5
        elif unrealized_pl < 0:
            score += 5
            alerts.append("Posición con pérdida no realizada; revisar riesgo.")

    if option_dte is not None and option_dte <= 21:
        alerts.append("DTE <= 21: revisar cierre o roll.")
        score += 10

    if option_delta is not None and abs(option_delta) >= 0.30:
        alerts.append("Delta de strike vendido amenazado.")
        score += 15

    if "SHORT_PUT" in position_class and alignment in ["bearish", "bearish_context", "partial_bearish"]:
        alerts.append("Short put con contexto técnico bajista.")
        score += 15

    if "SHORT_CALL" in position_class and alignment in ["bullish", "bullish_context", "partial_bullish"]:
        alerts.append("Short call con contexto técnico alcista.")
        score += 15

    if alerts and score >= 70:
        decision = "RADAR"
    else:
        decision = "ESPERAR"

    return module_result(
        "EXIT_MANAGER",
        "EVALUATED",
        decision,
        score,
        "Evalúa si una posición abierta requiere cierre, monitoreo o roll.",
        blockers,
        missing,
        {
            "position_class": position_class,
            "unrealized_pl": unrealized_pl,
            "option_dte": option_dte,
            "option_delta": option_delta,
            "alignment": alignment,
            "alerts": alerts,
        },
    )


def strategy_commander(ticker, technical, ibkr, market):
    modules = {
        "naked_put_pro": evaluate_naked_put_pro(ticker, technical, ibkr, market),
        "covered_call_pro": evaluate_covered_call_pro(ticker, technical, ibkr, market),
        "iron_condor_pro": evaluate_iron_condor_pro(ticker, technical, ibkr, market),
        "earnings_pro": evaluate_earnings_pro(ticker, technical, ibkr, market),
        "futures_pro": evaluate_futures_pro(ticker, technical, ibkr, market),
        "exit_manager": evaluate_exit_manager(ticker, technical, ibkr, market),
    }

    candidates = list(modules.values())
    final = sorted(candidates, key=lambda x: (decision_rank(x["decision"]), x["score"]), reverse=True)[0]

    return {
        "engine": "STRATEGY_COMMANDER_V8",
        "final": final,
        "modules": modules,
        "summary": {
            "best_strategy": final["strategy"],
            "decision": final["decision"],
            "score": final["score"],
            "reason": final["reason"],
            "blockers": final.get("blockers", []),
            "missing_data": final.get("missing_data", []),
        },
    }


# ============================================================
# DASHBOARD
# ============================================================

def build_dashboard():
    dashboard = []
    regime_info = market_regime()
    regime = regime_info.get("regime", "MIXED_OR_CHOP")

    for ticker, timeframes in trade_store.items():
        c = technical_core(timeframes)
        brains = build_brains(c, regime)
        probability = probability_engine(c, regime)
        risk = risk_engine(c, regime, brains["final"])
        expected_pl = expected_pl_engine(c)
        final = brains["final"]

        commander_context = build_unified_context(ticker)
        commander_final = commander_context["strategy_commander"]["final"]

        master_score = round(
            (safe_float(c.get("priority_score"), 0) * 0.35)
            + (safe_float(final.get("score"), 0) * 0.25)
            + (probability["probability_estimate"] * 0.15)
            + (safe_float(commander_final.get("score"), 0) * 0.25),
            2,
        )

        final_decision = commander_final["decision"] if commander_final["decision"] in ["OPERAR", "RADAR", "MISSING_DATA", "BLOCKED"] else final["final_decision"]

        dashboard.append({
            "ticker": ticker,
            "final_decision": final_decision,
            "v6_strategy": final["strategy"],
            "v6_state": final["state"],
            "v6_reason": final["reason"],
            "commander_strategy": commander_final["strategy"],
            "commander_state": commander_final["state"],
            "commander_decision": commander_final["decision"],
            "commander_score": commander_final["score"],
            "commander_reason": commander_final["reason"],
            "commander_blockers": commander_final.get("blockers", []),
            "commander_missing_data": commander_final.get("missing_data", []),
            "master_score": master_score,
            "brains": brains,
            "strategy_commander": commander_context["strategy_commander"],
            "execution_window": c["execution_window"],
            "session_state": c["session_state"],
            "minutes_since_open": c["minutes_since_open"],
            "state": c["state"],
            "grade": c["grade"],
            "conviction": c["conviction"],
            "action": c["action"],
            "strategy_type": c["strategy_type"],
            "probability": probability,
            "risk": risk,
            "expected_pl": expected_pl,
            "alignment": c["alignment"],
            "weighted_score": c["weighted_score"],
            "priority_score": c["priority_score"],
            "freshness_weighted": c["freshness_weighted"],
            "recommendation": c["recommendation"],
            "reason": c["reason"],
            "missing_timeframes": c["missing_timeframes"],
            "latest_data": c.get("latest_data", {}),
            "ibkr_context": commander_context["ibkr_context"],
        })

    return sorted(
        dashboard,
        key=lambda x: (decision_rank(x["final_decision"]), x["master_score"], x["priority_score"]),
        reverse=True,
    )


def grouped_dashboard():
    dashboard = build_dashboard()
    groups = {
        "OPERAR": [],
        "RADAR": [],
        "MISSING_DATA": [],
        "BLOCKED": [],
        "ESPERAR": [],
        "EVITAR": [],
        "EXPIRADO": [],
    }

    for item in dashboard:
        groups.setdefault(item["final_decision"], []).append(item)

    return groups


def stats_from_signals(signals):
    by_ticker, by_timeframe, by_setup, by_state, by_decision, by_source = {}, {}, {}, {}, {}, {}

    for s in signals:
        ticker = str(s.get("ticker", "UNKNOWN")).upper()
        timeframe = str(s.get("timeframe", "unknown"))
        setup = str(s.get("setup", "WAIT"))
        state = str(s.get("state", "NO_DATA"))
        decision = str(s.get("final_decision", s.get("strategy_decision", "UNKNOWN")))
        source = str(s.get("source", "UNKNOWN"))

        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
        by_timeframe[timeframe] = by_timeframe.get(timeframe, 0) + 1
        by_setup[setup] = by_setup.get(setup, 0) + 1
        by_state[state] = by_state.get(state, 0) + 1
        by_decision[decision] = by_decision.get(decision, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1

    return {
        "total_signals": len(signals),
        "by_ticker": by_ticker,
        "by_timeframe": by_timeframe,
        "by_setup": by_setup,
        "by_state": by_state,
        "by_decision": by_decision,
        "by_source": by_source,
    }


# ============================================================
# SECURITY
# ============================================================

def verify_webhook_secret(x_webhook_secret: Optional[str]):
    if REQUIRE_WEBHOOK_SECRET:
        if not WEBHOOK_SECRET:
            raise HTTPException(status_code=500, detail="WEBHOOK_SECRET required but not configured")
        if x_webhook_secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")


# ============================================================
# INGESTION HELPERS
# ============================================================

async def parse_request_payload(request: Request):
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="ignore").strip()
    parsed = extract_json_from_text(raw_text)

    if not isinstance(parsed, dict):
        parsed = {
            "raw_message": raw_text,
            "parse_warning": "payload not valid json",
        }

    return parsed, raw_text


def save_ingested_payload(parsed, raw_text, source_label):
    ticker = find_ticker(parsed, raw_text)
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))

    parsed = dict(parsed)
    parsed.update({
        "ticker": ticker,
        "timeframe": timeframe,
        "received_at": now_utc().isoformat(),
        "saved_at": now_utc().isoformat(),
        "source": source_label,
        "raw_payload_preview": raw_text[:500],
    })

    trade_store.setdefault(ticker, {})[timeframe] = parsed

    classification = classify_asset(trade_store[ticker])

    parsed.update({
        "state": classification["state"],
        "grade": classification["grade"],
        "conviction": classification["conviction"],
        "priority_score": classification["priority_score"],
        "final_decision": classification["final_decision"],
        "v6_strategy": classification["v6_strategy"],
        "master_score": classification["master_score"],
    })

    trade_store[ticker][timeframe] = parsed

    unified = build_unified_context(ticker)

    parsed["strategy_commander_summary"] = unified["strategy_commander"]["summary"]

    storage_result = save_signal(parsed)

    return ticker, timeframe, parsed, classification, unified, storage_result


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup():
    global trade_store
    trade_store = rebuild_store_from_history()


# ============================================================
# CORE ROUTES
# ============================================================

@app.get("/")
def root():
    return {
        "status": "alive",
        "engine": "Super Engine Bolsa v8.0",
        "mode": "Unified Decision Engine",
        "architecture": "TradingView + IBKR + Strategy Commander",
    }


@app.get("/health")
def health():
    signals = load_signals(limit=100)

    return {
        "status": "ok",
        "engine": "Super Engine Bolsa v8.0",
        "mode": "Unified Decision Engine",
        "operating_mode": OPERATING_MODE,
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
    parsed, raw_text = await parse_request_payload(request)

    ticker, timeframe, data, classification, unified, storage_result = save_ingested_payload(
        parsed=parsed,
        raw_text=raw_text,
        source_label="TRADINGVIEW",
    )

    return {
        "status": "ok",
        "engine": "v8.0",
        "message": f"TradingView webhook received for {ticker} {timeframe}",
        "ticker": ticker,
        "timeframe": timeframe,
        "storage": storage_result,
        "classification": classification,
        "unified_context": unified,
        "data": data,
    }


@app.post("/webhook/ibkr")
async def ibkr_webhook(request: Request, x_webhook_secret: Optional[str] = Header(default=None)):
    verify_webhook_secret(x_webhook_secret)
    parsed, raw_text = await parse_request_payload(request)

    ticker, timeframe, data, classification, unified, storage_result = save_ingested_payload(
        parsed=parsed,
        raw_text=raw_text,
        source_label="IBKR",
    )

    return {
        "status": "ok",
        "engine": "v8.0",
        "message": f"IBKR webhook received for {ticker} {timeframe}",
        "ticker": ticker,
        "timeframe": timeframe,
        "storage": storage_result,
        "classification": classification,
        "unified_context": unified,
        "data": data,
    }


@app.post("/test_signal")
def test_signal(signal: TradingSignal):
    parsed = signal.dict(exclude_none=True)

    if parsed.get("extra"):
        parsed.update(parsed.pop("extra"))

    ticker = find_ticker(parsed, json.dumps(parsed))
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))

    parsed.update({
        "ticker": ticker,
        "timeframe": timeframe,
        "received_at": now_utc().isoformat(),
        "saved_at": now_utc().isoformat(),
        "source": "MANUAL_TEST",
    })

    trade_store.setdefault(ticker, {})[timeframe] = parsed

    classification = classify_asset(trade_store[ticker])

    parsed.update({
        "state": classification["state"],
        "grade": classification["grade"],
        "conviction": classification["conviction"],
        "priority_score": classification["priority_score"],
        "final_decision": classification["final_decision"],
        "v6_strategy": classification["v6_strategy"],
        "master_score": classification["master_score"],
    })

    trade_store[ticker][timeframe] = parsed
    unified = build_unified_context(ticker)
    storage_result = save_signal(parsed)

    return {
        "status": "ok",
        "engine": "v8.0",
        "message": f"Test signal saved for {ticker} {timeframe}",
        "storage": storage_result,
        "classification": classification,
        "unified_context": unified,
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

    return {
        "ticker": ticker,
        "engine": "v8.0",
        "unified_context": build_unified_context(ticker),
    }


@app.get("/strategy_commander")
def strategy_commander_route(ticker: str):
    ticker = ticker.upper().strip()

    if ticker not in trade_store:
        return {
            "ticker": ticker,
            "status": "missing_data",
            "message": "No hay datos todavía para este ticker.",
        }

    unified = build_unified_context(ticker)

    return {
        "engine": "v8.0",
        "ticker": ticker,
        "strategy_commander": unified["strategy_commander"],
        "technical_context_available": unified["technical_context"]["available"],
        "ibkr_context_available": unified["ibkr_context"]["available"],
    }


@app.get("/get_dashboard")
def get_dashboard():
    dashboard = build_dashboard()

    for i, item in enumerate(dashboard, start=1):
        item["priority_rank"] = i

    return {
        "generated_at": now_utc().isoformat(),
        "engine": "v8.0",
        "supabase_enabled": supabase_enabled(),
        "market_regime": market_regime(),
        "dashboard": dashboard,
        "groups": grouped_dashboard(),
        "best_setups": dashboard[:5],
    }


@app.get("/get_report")
def get_report():
    groups = grouped_dashboard()
    regime = market_regime()

    lines = [
        "SUPER ENGINE BOLSA v8.0 — UNIFIED DECISION ENGINE",
        f"Generado UTC: {now_utc().isoformat()}",
        "",
        "RÉGIMEN DE MERCADO",
        f"- Estado: {regime['regime']}",
        f"- Lectura: {regime['summary']}",
        f"- Sesión: {market_session_state()}",
        f"- Minutos desde apertura: {round(minutes_since_open(), 1)}",
        f"- Ventana intradía activa: {inside_execution_window()}",
        "",
    ]

    for decision in ["OPERAR", "RADAR", "MISSING_DATA", "BLOCKED", "ESPERAR", "EVITAR", "EXPIRADO"]:
        lines.append(decision)
        items = groups.get(decision, [])

        if not items:
            lines.append("- Sin candidatos")

        for x in items[:10]:
            lines.append(
                f"- {x['ticker']} | Commander: {x['commander_strategy']} | "
                f"Decision: {x['commander_decision']} | Master {x['master_score']} | "
                f"Commander Score {x['commander_score']} | {x['commander_reason']}"
            )

        lines.append("")

    return {
        "generated_at": now_utc().isoformat(),
        "engine": "v8.0",
        "supabase_enabled": supabase_enabled(),
        "report": "\n".join(lines),
        "groups": groups,
        "best_setups": build_dashboard()[:5],
    }


@app.get("/gpt_report")
def gpt_report():
    dashboard = build_dashboard()
    regime = market_regime()

    if not dashboard:
        return {
            "engine": "v8.0",
            "market": regime["regime"],
            "status": "NO_DATA",
            "plan": "Esperar nuevas señales frescas.",
        }

    return {
        "engine": "v8.0",
        "market_regime": regime["regime"],
        "market_summary": regime["summary"],
        "session_state": market_session_state(),
        "execution_window": inside_execution_window(),
        "minutes_since_open": minutes_since_open(),
        "top_focus": [
            {
                "ticker": x["ticker"],
                "decision": x["final_decision"],
                "commander_strategy": x["commander_strategy"],
                "commander_state": x["commander_state"],
                "commander_score": x["commander_score"],
                "commander_reason": x["commander_reason"],
                "blockers": x["commander_blockers"],
                "missing_data": x["commander_missing_data"],
                "master_score": x["master_score"],
                "grade": x["grade"],
                "conviction": x["conviction"],
                "priority_score": x["priority_score"],
                "probability": x["probability"]["probability_estimate"],
                "risk": x["risk"]["risk_level"],
                "trade_allowed": x["risk"]["trade_allowed"],
                "legacy_strategy": x["v6_strategy"],
                "legacy_reason": x["v6_reason"],
                "ibkr_context": x["ibkr_context"],
                "strategy_commander": x["strategy_commander"],
            }
            for x in dashboard[:5]
        ],
        "operate_now": [x for x in dashboard if x["final_decision"] == "OPERAR"][:5],
        "radar": [x for x in dashboard if x["final_decision"] == "RADAR"][:5],
        "missing_data": [x for x in dashboard if x["final_decision"] == "MISSING_DATA"][:5],
        "blocked": [x for x in dashboard if x["final_decision"] == "BLOCKED"][:5],
        "avoid": [x for x in dashboard if x["final_decision"] in ["EVITAR", "EXPIRADO"]][:5],
    }


@app.get("/premarket_plan")
def premarket_plan():
    dashboard = build_dashboard()
    regime = market_regime()

    return {
        "engine": "v8.0",
        "generated_at": now_utc().isoformat(),
        "market_regime": regime,
        "session_state": market_session_state(),
        "plan": {
            "operate": [x for x in dashboard if x["final_decision"] == "OPERAR"][:5],
            "radar": [x for x in dashboard if x["final_decision"] == "RADAR"][:10],
            "missing_data": [x for x in dashboard if x["final_decision"] == "MISSING_DATA"][:10],
            "blocked": [x for x in dashboard if x["final_decision"] == "BLOCKED"][:10],
            "avoid": [x for x in dashboard if x["final_decision"] in ["EVITAR", "EXPIRADO"]][:10],
        },
        "note": "Premarket plan usa las últimas señales disponibles; ideal actualizar 1d/1h antes de apertura.",
    }


@app.get("/after_action_review")
def after_action_review(limit: int = 500):
    signals = load_signals(limit=limit)
    stats = stats_from_signals(signals)
    recent_decisions = [s for s in signals if s.get("final_decision")]

    return {
        "engine": "v8.0",
        "generated_at": now_utc().isoformat(),
        "review_window_signals": len(signals),
        "stats": stats,
        "recent_decisions": recent_decisions[-50:],
        "note": "AAR todavía no calcula win rate real hasta conectar precios posteriores o resultados manuales.",
    }


@app.post("/position_sizing")
def position_sizing(req: PositionSizingRequest):
    risk_budget = req.account_size * (req.risk_percent / 100)
    unit_risk = abs(req.entry - req.stop)

    if unit_risk <= 0:
        return {"error": "Entry and stop cannot be equal."}

    return {
        "engine": "v8.0",
        "account_size": req.account_size,
        "risk_percent": req.risk_percent,
        "risk_budget": round(risk_budget, 2),
        "entry": req.entry,
        "stop": req.stop,
        "unit_risk": round(unit_risk, 4),
        "suggested_units": math.floor(risk_budget / unit_risk),
    }


@app.post("/portfolio_commander")
def portfolio_commander(req: PortfolioInput):
    dashboard = build_dashboard()
    operate = [x for x in dashboard if x["final_decision"] == "OPERAR"]
    theta_candidates = [x for x in operate if x["commander_strategy"] in ["NAKED_PUT_PRO", "COVERED_CALL_PRO", "IRON_CONDOR_PRO"]]
    futures_candidates = [x for x in operate if x["commander_strategy"] == "FUTURES_PRO"]

    warnings = []

    if req.open_naked_puts and req.open_naked_puts >= 4:
        warnings.append("Exposición alta en naked puts; considerar concentración y margen.")

    if req.open_futures and req.open_futures >= 2:
        warnings.append("Exposición alta en futuros; controlar drawdown intradía.")

    if len(theta_candidates) >= 3:
        warnings.append("Muchas oportunidades theta simultáneas; priorizar por IV/soporte/correlación.")

    return {
        "engine": "v8.0",
        "operating_mode": OPERATING_MODE,
        "portfolio_input": req.dict(),
        "summary": {
            "operate_candidates": len(operate),
            "theta_candidates": len(theta_candidates),
            "futures_candidates": len(futures_candidates),
            "directional_bias": req.directional_bias,
        },
        "warnings": warnings,
        "top_candidates": operate[:5],
    }


@app.post("/evaluate_option")
def evaluate_option(req: OptionEvalRequest):
    ticker = req.ticker.upper().strip()
    technical = get_technical_context(ticker)
    ibkr = get_ibkr_context(ticker)
    market = get_market_context()

    if req.iv_rank is not None and technical.get("available"):
        technical["classification"]["latest_data"]["iv_rank"] = req.iv_rank

    if req.price is not None and technical.get("available"):
        technical["classification"]["latest_data"]["price"] = req.price

    if req.support_near is not None and technical.get("available"):
        technical["classification"]["latest_data"]["support_near"] = req.support_near

    if req.resistance_near is not None and technical.get("available"):
        technical["classification"]["latest_data"]["resistance_near"] = req.resistance_near

    if req.earnings_soon is not None and technical.get("available"):
        technical["classification"]["latest_data"]["earnings_soon"] = req.earnings_soon

    commander = strategy_commander(ticker, technical, ibkr, market)

    margin_yield = round((req.premium / req.margin_required) * 100, 2) if req.premium and req.margin_required and req.margin_required > 0 else None

    return {
        "engine": "v8.0",
        "ticker": ticker,
        "strategy": req.strategy,
        "strike": req.strike,
        "premium": req.premium,
        "dte": req.dte,
        "margin_required": req.margin_required,
        "premium_on_margin_percent": margin_yield,
        "iv_rank": req.iv_rank,
        "technical_context": technical,
        "ibkr_context": ibkr,
        "strategy_commander": commander,
        "dictamen": f"Dictamen V8: {commander['summary']['decision']} / {commander['summary']['best_strategy']} — {commander['summary']['reason']}",
    }


# ============================================================
# OUTCOMES
# ============================================================

@app.post("/record_outcome")
async def record_outcome(request: Request):
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="ignore").strip()
    parsed = extract_json_from_text(raw_text)

    if not isinstance(parsed, dict):
        return {"status": "error", "message": "Invalid outcome payload."}

    saved = save_outcome_file(parsed)

    return {
        "status": "ok",
        "engine": "v8.0",
        "outcome": saved,
    }


@app.get("/outcomes")
def outcomes():
    data = load_outcomes_from_file()
    return {
        "engine": "v8.0",
        "outcomes": data[-500:],
        "stats": outcome_stats(data),
    }


# ============================================================
# DEBUG / DATA ROUTES
# ============================================================

@app.get("/latest")
def latest():
    return trade_store


@app.get("/history")
def history(limit: int = 100):
    signals = load_signals(limit=limit)

    return {
        "engine": "v8.0",
        "supabase_enabled": supabase_enabled(),
        "showing": min(limit, len(signals)),
        "signals": signals[-limit:],
    }


@app.get("/stats")
def stats(limit: int = 1000):
    signals = load_signals(limit=limit)

    return {
        "engine": "v8.0",
        "generated_at": now_utc().isoformat(),
        "stats": stats_from_signals(signals),
    }


@app.get("/stats/ticker/{ticker}")
def stats_ticker(ticker: str, limit: int = 1000):
    ticker = ticker.upper().strip()
    signals = [s for s in load_signals(limit=limit) if str(s.get("ticker", "")).upper() == ticker]

    return {
        "engine": "v8.0",
        "ticker": ticker,
        "generated_at": now_utc().isoformat(),
        "stats": stats_from_signals(signals),
        "signals": signals[-50:],
    }


@app.get("/debug/supabase")
def debug_supabase():
    return {
        "engine": "v8.0",
        "supabase_enabled": supabase_enabled(),
        "supabase_url_present": bool(SUPABASE_URL),
        "supabase_key_present": bool(SUPABASE_KEY),
        "count_test": supabase_count_signals(),
    }


@app.get("/debug/regime")
def debug_regime():
    return {
        "engine": "v8.0",
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
            "engine": "v8.0",
            "ticker": ticker,
            "error": "Ticker not in memory",
        }

    regime = market_regime().get("regime", "MIXED_OR_CHOP")
    c = technical_core(trade_store[ticker])

    return {
        "engine": "v8.0",
        "ticker": ticker,
        "classification": classify_asset(trade_store[ticker]),
        "legacy_brains": build_brains(c, regime),
        "strategy_commander": build_unified_context(ticker)["strategy_commander"],
        "probability": probability_engine(c, regime),
        "expected_pl": expected_pl_engine(c),
    }


@app.get("/debug/routes")
def debug_routes():
    return {
        "engine": "v8.0",
        "routes": [
            "/",
            "/health",
            "/webhook/tradingview",
            "/webhook/ibkr",
            "/test_signal",
            "/get_trade_context",
            "/strategy_commander",
            "/get_dashboard",
            "/get_report",
            "/gpt_report",
            "/premarket_plan",
            "/after_action_review",
            "/record_outcome",
            "/outcomes",
            "/portfolio_commander",
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


# ============================================================
# HTML DASHBOARD
# ============================================================

@app.get("/dashboard_html", response_class=HTMLResponse)
def dashboard_html():
    groups = grouped_dashboard()
    regime = market_regime()

    decision_color = {
        "OPERAR": "#0B6E4F",
        "RADAR": "#2A9D8F",
        "MISSING_DATA": "#E9C46A",
        "BLOCKED": "#E76F51",
        "ESPERAR": "#F4A261",
        "EVITAR": "#E76F51",
        "EXPIRADO": "#6C757D",
    }

    sections = ""

    for decision in ["OPERAR", "RADAR", "MISSING_DATA", "BLOCKED", "ESPERAR", "EVITAR", "EXPIRADO"]:
        rows = ""

        for i, item in enumerate(groups.get(decision, []), start=1):
            rows += f"""
            <tr>
                <td>{i}</td>
                <td>{item['ticker']}</td>
                <td>{item['commander_strategy']}</td>
                <td>{item['commander_decision']}</td>
                <td>{item['commander_score']}</td>
                <td>{item['master_score']}</td>
                <td>{item['grade']}</td>
                <td>{item['conviction']}</td>
                <td>{item['probability']['probability_estimate']}%</td>
                <td>{item['risk']['risk_level']}</td>
                <td>{item['commander_reason']}</td>
            </tr>
            """

        sections += f"""
        <h2 style='border-left:6px solid {decision_color.get(decision, "#999")}; padding-left:10px;'>{decision}</h2>
        <table>
            <tr>
                <th>#</th>
                <th>Ticker</th>
                <th>Commander Strategy</th>
                <th>Decision</th>
                <th>Commander Score</th>
                <th>Master</th>
                <th>Grade</th>
                <th>Conviction</th>
                <th>Prob</th>
                <th>Risk</th>
                <th>Reason</th>
            </tr>
            {rows}
        </table>
        """

    html = f"""
    <html>
    <head>
        <title>Super Engine Bolsa v8 Dashboard</title>
        <style>
            body {{
                font-family: Arial;
                margin: 30px;
                background: #f7f7f7;
            }}
            h1 {{
                color: #111;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                background: white;
                margin-bottom: 26px;
            }}
            th, td {{
                border: 1px solid #ddd;
                padding: 9px;
                text-align: left;
                font-size: 13px;
            }}
            th {{
                background: #111;
                color: white;
            }}
            .regime {{
                padding: 15px;
                background: white;
                margin-bottom: 20px;
                border-left: 5px solid #111;
            }}
            .meta {{
                font-size: 13px;
                color: #555;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <h1>Super Engine Bolsa v8.0 — Unified Decision Engine</h1>
        <div class='meta'>
            Supabase enabled: {supabase_enabled()} |
            Webhook secret required: {REQUIRE_WEBHOOK_SECRET} |
            Mode: {OPERATING_MODE}
        </div>
        <div class='regime'>
            <b>Market Regime:</b> {regime['regime']}<br>
            <b>Lectura:</b> {regime['summary']}<br>
            <b>Sesión:</b> {market_session_state()}<br>
            <b>Ventana intradía activa:</b> {inside_execution_window()}<br>
            <b>Minutos desde apertura:</b> {minutes_since_open()}
        </div>
        {sections}
    </body>
    </html>
    """

    return html


# ============================================================
# SUPER ENGINE BOLSA — V9 PATCH
# Multi-option candidates + safer commander + GPT summary
# ============================================================

MAX_OPTIONS_CANDIDATES_PER_TICKER = 80

def option_candidate_key(option):
    return "|".join([
        str(option.get("ticker", "")),
        str(option.get("strategy_hint", "")),
        str(option.get("option_type", "")),
        str(option.get("option_symbol", "")),
        str(option.get("strike", "")),
        str(option.get("expiration", "")),
    ])


def option_quality_score(option):
    quality = str(option.get("data_quality") or "").upper()
    if quality == "FULL_WITH_GREEKS":
        return 30
    if quality == "PRICE_WITH_GREEKS_NO_BIDASK":
        return 22
    if quality == "PARTIAL_OPTION_DATA":
        return 12
    if quality == "PRICE_ONLY_NO_GREEKS":
        return 8
    return 0


def option_candidate_rank(option):
    decision = str(option.get("strategy_decision") or "").upper()
    score = safe_float(option.get("score"), 0)
    mid = safe_float(option.get("mid"), 0)
    delta = option.get("delta")
    iv = option.get("implied_volatility")
    has_delta = 1 if delta is not None else 0
    has_iv = 1 if iv is not None else 0

    return (
        decision_rank(decision),
        option_quality_score(option),
        score,
        has_delta + has_iv,
        mid,
    )


def upsert_option_candidate(ticker, option):
    ticker = ticker.upper().strip()
    trade_store.setdefault(ticker, {})

    candidates = trade_store[ticker].get("options_candidates", [])
    key = option_candidate_key(option)

    candidates = [
        existing for existing in candidates
        if option_candidate_key(existing) != key
    ]

    candidates.append(option)
    candidates = sorted(candidates, key=option_candidate_rank, reverse=True)
    candidates = candidates[:MAX_OPTIONS_CANDIDATES_PER_TICKER]

    trade_store[ticker]["options_candidates"] = candidates
    trade_store[ticker]["options"] = candidates[0] if candidates else option

    return candidates


def select_best_option_candidate(candidates, strategy_hint=None, option_type=None):
    if not candidates:
        return None

    filtered = []

    for option in candidates:
        candidate_strategy = str(option.get("strategy_hint") or "").upper()
        candidate_type = str(option.get("option_type") or "").upper()

        if strategy_hint and candidate_strategy != strategy_hint:
            continue

        if option_type and candidate_type != option_type:
            continue

        filtered.append(option)

    if not filtered:
        return None

    return sorted(filtered, key=option_candidate_rank, reverse=True)[0]


def save_ingested_payload(parsed, raw_text, source_label):
    ticker = find_ticker(parsed, raw_text)
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))

    parsed = dict(parsed)
    parsed.update({
        "ticker": ticker,
        "timeframe": timeframe,
        "received_at": now_utc().isoformat(),
        "saved_at": now_utc().isoformat(),
        "source": source_label,
        "raw_payload_preview": raw_text[:500],
    })

    trade_store.setdefault(ticker, {})

    if source_label == "IBKR" and timeframe == "options":
        upsert_option_candidate(ticker, parsed)
    else:
        trade_store[ticker][timeframe] = parsed

    classification = classify_asset(trade_store[ticker])

    parsed.update({
        "state": classification["state"],
        "grade": classification["grade"],
        "conviction": classification["conviction"],
        "priority_score": classification["priority_score"],
        "final_decision": classification["final_decision"],
        "v6_strategy": classification["v6_strategy"],
        "master_score": classification["master_score"],
    })

    if source_label == "IBKR" and timeframe == "options":
        upsert_option_candidate(ticker, parsed)
    else:
        trade_store[ticker][timeframe] = parsed

    unified = build_unified_context(ticker)
    parsed["strategy_commander_summary"] = unified["strategy_commander"]["summary"]

    if source_label == "IBKR" and timeframe == "options":
        upsert_option_candidate(ticker, parsed)
    else:
        trade_store[ticker][timeframe] = parsed

    storage_result = save_signal(parsed)

    return ticker, timeframe, parsed, classification, unified, storage_result


def get_ibkr_context(ticker: str):
    ticker = ticker.upper().strip()
    raw = trade_store.get(ticker, {})

    live = raw.get("live")
    position = raw.get("position")
    portfolio = raw.get("portfolio")

    options_candidates = raw.get("options_candidates", [])
    best_option = select_best_option_candidate(options_candidates) or raw.get("options")
    best_naked_put = select_best_option_candidate(options_candidates, strategy_hint="NAKED_PUT") or select_best_option_candidate(options_candidates, option_type="PUT")
    best_covered_call = select_best_option_candidate(options_candidates, strategy_hint="COVERED_CALL") or select_best_option_candidate(options_candidates, option_type="CALL")

    options = best_option

    return {
        "available": bool(live or position or options or portfolio or options_candidates),
        "ticker": ticker,
        "live": live,
        "position": position,
        "options": options,
        "portfolio": portfolio,
        "options_candidates_count": len(options_candidates),
        "options_candidates": options_candidates[:20],
        "best_naked_put": best_naked_put,
        "best_covered_call": best_covered_call,
        "latest_price": safe_float((live or {}).get("price"), None) if live else None,
        "price_source": (live or {}).get("price_source") if live else None,
        "position_class": (position or {}).get("position_class") if position else None,
        "sec_type": (position or {}).get("sec_type") if position else None,
        "position_size": safe_float((position or {}).get("position_size"), None) if position else None,
        "market_value": safe_float((position or {}).get("market_value"), None) if position else None,
        "unrealized_pl": safe_float((position or {}).get("unrealized_pl"), None) if position else None,
        "option_strategy_hint": (options or {}).get("strategy_hint") if options else None,
        "option_decision": (options or {}).get("strategy_decision") if options else None,
        "option_data_quality": (options or {}).get("data_quality") if options else None,
        "option_dte": safe_float((options or {}).get("dte"), None) if options else None,
        "option_delta": safe_float((options or {}).get("delta"), None) if options else None,
        "option_iv": safe_float((options or {}).get("implied_volatility"), None) if options else None,
        "option_mid": safe_float((options or {}).get("mid"), None) if options else None,
        "option_spread_pct": safe_float((options or {}).get("spread_pct"), None) if options else None,
        "option_strike": safe_float((options or {}).get("strike"), None) if options else None,
        "option_type": (options or {}).get("option_type") if options else None,
    }


def apply_live_price_safety_cap(result, ibkr):
    price_source = str(ibkr.get("price_source") or "")

    if price_source == "IBKR_HISTORICAL_CLOSE_FALLBACK":
        result = dict(result)
        blockers = list(result.get("blockers", []))
        blockers.append("Precio del subyacente viene de fallback histórico; confirmar precio live en TWS antes de operar.")
        result["blockers"] = blockers
        result["details"] = dict(result.get("details", {}))
        result["details"]["price_source_blocker"] = price_source

        if result.get("decision") == "OPERAR":
            result["decision"] = "RADAR"
            result["reason"] = result.get("reason", "") + " Decisión limitada a RADAR por precio no live."

    return result


_evaluate_naked_put_pro_v8 = evaluate_naked_put_pro
_evaluate_covered_call_pro_v8 = evaluate_covered_call_pro
_evaluate_iron_condor_pro_v8 = evaluate_iron_condor_pro


def inject_option_candidate_into_ibkr_context(ibkr, candidate):
    if not candidate:
        return ibkr

    patched = dict(ibkr)
    patched["options"] = candidate
    patched["option_strategy_hint"] = candidate.get("strategy_hint")
    patched["option_decision"] = candidate.get("strategy_decision")
    patched["option_data_quality"] = candidate.get("data_quality")
    patched["option_dte"] = safe_float(candidate.get("dte"), None)
    patched["option_delta"] = safe_float(candidate.get("delta"), None)
    patched["option_iv"] = safe_float(candidate.get("implied_volatility"), None)
    patched["option_mid"] = safe_float(candidate.get("mid"), None)
    patched["option_spread_pct"] = safe_float(candidate.get("spread_pct"), None)
    patched["option_strike"] = safe_float(candidate.get("strike"), None)
    patched["option_type"] = candidate.get("option_type")
    return patched


def evaluate_naked_put_pro(ticker, technical, ibkr, market):
    candidate = ibkr.get("best_naked_put")
    patched_ibkr = inject_option_candidate_into_ibkr_context(ibkr, candidate)
    result = _evaluate_naked_put_pro_v8(ticker, technical, patched_ibkr, market)
    result = apply_live_price_safety_cap(result, patched_ibkr)

    result["details"] = dict(result.get("details", {}))
    result["details"]["selected_option_candidate"] = candidate

    return result


def evaluate_covered_call_pro(ticker, technical, ibkr, market):
    candidate = ibkr.get("best_covered_call")
    patched_ibkr = inject_option_candidate_into_ibkr_context(ibkr, candidate)
    result = _evaluate_covered_call_pro_v8(ticker, technical, patched_ibkr, market)
    result = apply_live_price_safety_cap(result, patched_ibkr)

    result["details"] = dict(result.get("details", {}))
    result["details"]["selected_option_candidate"] = candidate

    return result


def evaluate_iron_condor_pro(ticker, technical, ibkr, market):
    result = _evaluate_iron_condor_pro_v8(ticker, technical, ibkr, market)

    candidates = ibkr.get("options_candidates", [])
    best_put = select_best_option_candidate(candidates, option_type="PUT")
    best_call = select_best_option_candidate(candidates, option_type="CALL")

    result = dict(result)
    result["details"] = dict(result.get("details", {}))
    result["details"]["best_put_candidate"] = best_put
    result["details"]["best_call_candidate"] = best_call
    result["details"]["options_candidates_count"] = len(candidates)

    missing = list(result.get("missing_data", []))
    blockers = list(result.get("blockers", []))

    if not best_put:
        missing.append("short_put_candidate")
    if not best_call:
        missing.append("short_call_candidate")

    result["missing_data"] = sorted(list(set(missing)))
    result["blockers"] = sorted(list(set(blockers)))

    if result.get("decision") == "OPERAR" and (not best_put or not best_call):
        result["decision"] = "MISSING_DATA"
        result["reason"] = result.get("reason", "") + " Falta una de las dos alas del Iron Condor."

    return result


def compact_strategy_result(item):
    return {
        "strategy": item.get("strategy"),
        "decision": item.get("decision"),
        "score": item.get("score"),
        "reason": item.get("reason"),
        "blockers": item.get("blockers", []),
        "missing_data": item.get("missing_data", []),
        "details": item.get("details", {}),
    }


@app.get("/gpt_summary")
def gpt_summary():
    dashboard = build_dashboard()
    regime = market_regime()

    top = []
    for x in dashboard[:10]:
        top.append({
            "ticker": x["ticker"],
            "decision": x["final_decision"],
            "best_strategy": x["commander_strategy"],
            "commander_score": x["commander_score"],
            "master_score": x["master_score"],
            "reason": x["commander_reason"],
            "blockers": x["commander_blockers"],
            "missing_data": x["commander_missing_data"],
            "ibkr": {
                "available": x.get("ibkr_context", {}).get("available"),
                "price_source": x.get("ibkr_context", {}).get("price_source"),
                "latest_price": x.get("ibkr_context", {}).get("latest_price"),
                "position_class": x.get("ibkr_context", {}).get("position_class"),
                "position_size": x.get("ibkr_context", {}).get("position_size"),
                "options_candidates_count": x.get("ibkr_context", {}).get("options_candidates_count"),
                "best_naked_put": x.get("ibkr_context", {}).get("best_naked_put"),
                "best_covered_call": x.get("ibkr_context", {}).get("best_covered_call"),
            },
        })

    return {
        "engine": "v9.0_patch",
        "generated_at": now_utc().isoformat(),
        "market_regime": regime.get("regime"),
        "market_summary": regime.get("summary"),
        "session_state": market_session_state(),
        "summary": {
            "operate_count": len([x for x in dashboard if x["final_decision"] == "OPERAR"]),
            "radar_count": len([x for x in dashboard if x["final_decision"] == "RADAR"]),
            "missing_data_count": len([x for x in dashboard if x["final_decision"] == "MISSING_DATA"]),
            "blocked_count": len([x for x in dashboard if x["final_decision"] == "BLOCKED"]),
        },
        "top_opportunities": top,
        "next_best_action": "Revisar oportunidades RADAR/MISSING_DATA y confirmar datos faltantes: griegas, IV Rank, VIX, macro y precio live cuando aplique.",
    }


# END SUPER ENGINE BOLSA — V9 PATCH


# ============================================================
# SUPER ENGINE BOLSA — V9.1 PATCH
# Debug options + memory store diagnostics
# ============================================================

@app.get("/debug/options")
def debug_options(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()
    raw = trade_store.get(ticker, {})

    candidates = raw.get("options_candidates", [])
    best_any = select_best_option_candidate(candidates)
    best_put = select_best_option_candidate(candidates, option_type="PUT")
    best_call = select_best_option_candidate(candidates, option_type="CALL")
    best_naked_put = select_best_option_candidate(candidates, strategy_hint="NAKED_PUT")
    best_covered_call = select_best_option_candidate(candidates, strategy_hint="COVERED_CALL")

    return {
        "engine": "v9.1_debug",
        "ticker": ticker,
        "ticker_in_memory": ticker in trade_store,
        "available_layers": list(raw.keys()),
        "options_candidates_count": len(candidates),
        "best_any": best_any,
        "best_put": best_put,
        "best_call": best_call,
        "best_naked_put": best_naked_put,
        "best_covered_call": best_covered_call,
        "options_candidates": candidates[:30],
        "note": "Si options_candidates_count es 0 después de un ciclo completo de ibkr_bridge.py, las opciones no están quedando guardadas como candidatos múltiples."
    }


@app.get("/debug/stores")
def debug_stores(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()
    raw = trade_store.get(ticker, {})

    compact = {}
    for key, value in raw.items():
        if key == "options_candidates":
            compact[key] = {
                "type": "list",
                "count": len(value),
                "sample": value[:3],
            }
        elif isinstance(value, dict):
            compact[key] = {
                "type": "dict",
                "ticker": value.get("ticker"),
                "timeframe": value.get("timeframe"),
                "setup": value.get("setup"),
                "source": value.get("source"),
                "price": value.get("price"),
                "strategy_hint": value.get("strategy_hint"),
                "strategy_decision": value.get("strategy_decision"),
                "data_quality": value.get("data_quality"),
                "received_at": value.get("received_at"),
            }
        else:
            compact[key] = str(type(value))

    return {
        "engine": "v9.1_debug",
        "ticker": ticker,
        "ticker_in_memory": ticker in trade_store,
        "available_layers": list(raw.keys()),
        "store_compact": compact,
        "raw_store": raw,
    }


@app.get("/debug/routes_full")
def debug_routes_full():
    return {
        "engine": "v9.1_debug",
        "routes": sorted([route.path for route in app.routes]),
    }

# END SUPER ENGINE BOLSA — V9.1 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V10 PATCH
# Strategy Commander PRO separation:
# Entry Strategies vs Management Actions + GPT Decision
# ============================================================

ENTRY_STRATEGY_KEYS = [
    "naked_put_pro",
    "covered_call_pro",
    "iron_condor_pro",
    "earnings_pro",
    "futures_pro",
]

MANAGEMENT_STRATEGY_KEYS = [
    "exit_manager",
]


def pick_best_entry_strategy(modules):
    entry_candidates = [
        modules[k] for k in ENTRY_STRATEGY_KEYS
        if k in modules
    ]

    if not entry_candidates:
        return module_result(
            "NO_ENTRY_STRATEGY",
            "NO_DATA",
            "ESPERAR",
            0,
            "No hay estrategias de entrada evaluables.",
            [],
            ["entry_strategies"],
            {},
        )

    return sorted(
        entry_candidates,
        key=lambda x: (decision_rank(x.get("decision")), safe_float(x.get("score"), 0)),
        reverse=True,
    )[0]


def pick_best_management_action(modules):
    management_candidates = [
        modules[k] for k in MANAGEMENT_STRATEGY_KEYS
        if k in modules
    ]

    if not management_candidates:
        return module_result(
            "NO_MANAGEMENT_ACTION",
            "NO_DATA",
            "ESPERAR",
            0,
            "No hay acciones de gestión evaluables.",
            [],
            ["management_actions"],
            {},
        )

    return sorted(
        management_candidates,
        key=lambda x: (decision_rank(x.get("decision")), safe_float(x.get("score"), 0)),
        reverse=True,
    )[0]


def final_action_from_entry_and_management(best_entry, best_management):
    entry_decision = str(best_entry.get("decision", "ESPERAR")).upper()
    management_decision = str(best_management.get("decision", "ESPERAR")).upper()

    management_alert = management_decision in ["OPERAR", "RADAR"]
    entry_actionable = entry_decision in ["OPERAR", "RADAR"]

    if management_alert and best_management.get("score", 0) >= 70:
        return {
            "final_action": "MANAGE_POSITION",
            "decision": management_decision,
            "primary_focus": best_management.get("strategy"),
            "secondary_focus": best_entry.get("strategy"),
            "reason": "Hay una posición abierta que requiere revisión antes de abrir nuevas operaciones.",
        }

    if entry_actionable:
        return {
            "final_action": "ENTRY_OPPORTUNITY",
            "decision": entry_decision,
            "primary_focus": best_entry.get("strategy"),
            "secondary_focus": best_management.get("strategy"),
            "reason": "La mejor oportunidad actual viene de una estrategia de entrada.",
        }

    if entry_decision == "MISSING_DATA":
        return {
            "final_action": "WAIT_FOR_DATA",
            "decision": "MISSING_DATA",
            "primary_focus": best_entry.get("strategy"),
            "secondary_focus": best_management.get("strategy"),
            "reason": "Hay oportunidad potencial, pero faltan datos para confirmar.",
        }

    if entry_decision == "BLOCKED":
        return {
            "final_action": "BLOCKED",
            "decision": "BLOCKED",
            "primary_focus": best_entry.get("strategy"),
            "secondary_focus": best_management.get("strategy"),
            "reason": "La mejor oportunidad está bloqueada por una o más reglas de riesgo.",
        }

    return {
        "final_action": "NO_TRADE",
        "decision": "ESPERAR",
        "primary_focus": best_entry.get("strategy"),
        "secondary_focus": best_management.get("strategy"),
        "reason": "No hay oportunidad de entrada ni alerta de gestión suficientemente fuerte.",
    }


_strategy_commander_v9 = strategy_commander


def strategy_commander(ticker, technical, ibkr, market):
    modules = {
        "naked_put_pro": evaluate_naked_put_pro(ticker, technical, ibkr, market),
        "covered_call_pro": evaluate_covered_call_pro(ticker, technical, ibkr, market),
        "iron_condor_pro": evaluate_iron_condor_pro(ticker, technical, ibkr, market),
        "earnings_pro": evaluate_earnings_pro(ticker, technical, ibkr, market),
        "futures_pro": evaluate_futures_pro(ticker, technical, ibkr, market),
        "exit_manager": evaluate_exit_manager(ticker, technical, ibkr, market),
    }

    best_entry = pick_best_entry_strategy(modules)
    best_management = pick_best_management_action(modules)
    final = final_action_from_entry_and_management(best_entry, best_management)

    legacy_best = sorted(
        list(modules.values()),
        key=lambda x: (decision_rank(x.get("decision")), safe_float(x.get("score"), 0)),
        reverse=True,
    )[0]

    return {
        "engine": "STRATEGY_COMMANDER_V10",
        "final": {
            "strategy": final["primary_focus"],
            "state": final["final_action"],
            "decision": final["decision"],
            "score": max(
                safe_float(best_entry.get("score"), 0),
                safe_float(best_management.get("score"), 0),
            ),
            "reason": final["reason"],
            "blockers": best_entry.get("blockers", []) + best_management.get("blockers", []),
            "missing_data": best_entry.get("missing_data", []) + best_management.get("missing_data", []),
            "details": {
                "final_action": final,
                "best_entry_strategy": best_entry,
                "best_management_action": best_management,
                "legacy_best": legacy_best,
            },
        },
        "best_entry_strategy": best_entry,
        "best_management_action": best_management,
        "modules": modules,
        "summary": {
            "final_action": final["final_action"],
            "decision": final["decision"],
            "best_entry_strategy": best_entry.get("strategy"),
            "best_entry_decision": best_entry.get("decision"),
            "best_entry_score": best_entry.get("score"),
            "best_management_action": best_management.get("strategy"),
            "best_management_decision": best_management.get("decision"),
            "best_management_score": best_management.get("score"),
            "primary_focus": final["primary_focus"],
            "secondary_focus": final["secondary_focus"],
            "reason": final["reason"],
            "entry_blockers": best_entry.get("blockers", []),
            "entry_missing_data": best_entry.get("missing_data", []),
            "management_alerts": best_management.get("details", {}).get("alerts", []),
        },
    }


def compact_option(option):
    if not option:
        return None

    return {
        "ticker": option.get("ticker"),
        "strategy_hint": option.get("strategy_hint"),
        "option_type": option.get("option_type"),
        "option_symbol": option.get("option_symbol"),
        "strike": option.get("strike"),
        "expiration": option.get("expiration"),
        "dte": option.get("dte"),
        "mid": option.get("mid"),
        "bid": option.get("bid"),
        "ask": option.get("ask"),
        "delta": option.get("delta"),
        "iv": option.get("implied_volatility"),
        "score": option.get("score"),
        "decision": option.get("strategy_decision"),
        "data_quality": option.get("data_quality"),
    }


def compact_decision_row(x):
    commander = x.get("strategy_commander", {})
    summary = commander.get("summary", {})
    ibkr = x.get("ibkr_context", {})

    return {
        "ticker": x.get("ticker"),
        "decision": summary.get("decision", x.get("final_decision")),
        "final_action": summary.get("final_action"),
        "primary_focus": summary.get("primary_focus"),
        "best_entry_strategy": summary.get("best_entry_strategy"),
        "best_entry_decision": summary.get("best_entry_decision"),
        "best_entry_score": summary.get("best_entry_score"),
        "best_management_action": summary.get("best_management_action"),
        "best_management_decision": summary.get("best_management_decision"),
        "best_management_score": summary.get("best_management_score"),
        "reason": summary.get("reason"),
        "entry_blockers": summary.get("entry_blockers", []),
        "entry_missing_data": summary.get("entry_missing_data", []),
        "management_alerts": summary.get("management_alerts", []),
        "master_score": x.get("master_score"),
        "technical": {
            "alignment": x.get("alignment"),
            "priority_score": x.get("priority_score"),
            "grade": x.get("grade"),
            "conviction": x.get("conviction"),
        },
        "ibkr": {
            "available": ibkr.get("available"),
            "price_source": ibkr.get("price_source"),
            "latest_price": ibkr.get("latest_price"),
            "position_class": ibkr.get("position_class"),
            "position_size": ibkr.get("position_size"),
            "unrealized_pl": ibkr.get("unrealized_pl"),
            "options_candidates_count": ibkr.get("options_candidates_count"),
            "best_naked_put": compact_option(ibkr.get("best_naked_put")),
            "best_covered_call": compact_option(ibkr.get("best_covered_call")),
        },
    }


@app.get("/gpt_decision")
def gpt_decision():
    dashboard = build_dashboard()
    regime = market_regime()

    compact = [compact_decision_row(x) for x in dashboard]

    entry_opportunities = [
        x for x in compact
        if x.get("final_action") == "ENTRY_OPPORTUNITY"
    ]

    management_actions = [
        x for x in compact
        if x.get("final_action") == "MANAGE_POSITION"
    ]

    wait_for_data = [
        x for x in compact
        if x.get("final_action") == "WAIT_FOR_DATA"
    ]

    blocked = [
        x for x in compact
        if x.get("final_action") == "BLOCKED"
    ]

    no_trade = [
        x for x in compact
        if x.get("final_action") == "NO_TRADE"
    ]

    return {
        "engine": "v10_strategy_commander_pro",
        "generated_at": now_utc().isoformat(),
        "market": {
            "regime": regime.get("regime"),
            "summary": regime.get("summary"),
            "session_state": market_session_state(),
            "execution_window": inside_execution_window(),
            "minutes_since_open": minutes_since_open(),
        },
        "counts": {
            "entry_opportunities": len(entry_opportunities),
            "management_actions": len(management_actions),
            "wait_for_data": len(wait_for_data),
            "blocked": len(blocked),
            "no_trade": len(no_trade),
        },
        "top_entry_opportunities": entry_opportunities[:10],
        "top_management_actions": management_actions[:10],
        "wait_for_data": wait_for_data[:10],
        "blocked": blocked[:10],
        "no_trade": no_trade[:10],
        "all_ranked": compact[:20],
        "next_best_action": "Priorizar primero gestión de posiciones abiertas con alerta fuerte; después revisar oportunidades de entrada con decisión OPERAR/RADAR y confirmar datos faltantes.",
    }

# END SUPER ENGINE BOLSA — V10 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V10.1 PATCH
# Rebuild options candidates from history + actionable entry filtering
# ============================================================

def is_actionable_entry_candidate(item):
    strategy = str(item.get("strategy") or "").upper()
    decision = str(item.get("decision") or "").upper()
    state = str(item.get("state") or "").upper()
    score = safe_float(item.get("score"), 0)

    if strategy == "EARNINGS_PRO" and state in ["NO_EVENT", "EVALUATED"] and decision == "ESPERAR":
        return False

    if decision in ["OPERAR", "RADAR", "MISSING_DATA", "BLOCKED"]:
        return True

    if score >= 55 and strategy in ["NAKED_PUT_PRO", "COVERED_CALL_PRO", "IRON_CONDOR_PRO", "FUTURES_PRO"]:
        return True

    return False


def pick_best_entry_strategy(modules):
    entry_candidates = [
        modules[k] for k in ENTRY_STRATEGY_KEYS
        if k in modules and is_actionable_entry_candidate(modules[k])
    ]

    if not entry_candidates:
        return module_result(
            "NO_ENTRY_STRATEGY",
            "NO_EDGE",
            "ESPERAR",
            0,
            "No hay oportunidad real de entrada con la información actual.",
            [],
            ["actionable_entry_strategy"],
            {},
        )

    return sorted(
        entry_candidates,
        key=lambda x: (decision_rank(x.get("decision")), safe_float(x.get("score"), 0)),
        reverse=True,
    )[0]


def rebuild_store_from_history():
    signals = load_signals(limit=5000)
    store = {}

    for signal in signals:
        ticker = str(signal.get("ticker", "UNKNOWN")).upper().strip()
        tf = normalize_timeframe(signal.get("timeframe", "unknown"))
        source = str(signal.get("source", "")).upper()

        if ticker not in store:
            store[ticker] = {}

        if source == "IBKR" and tf == "options":
            existing = store[ticker].get("options_candidates", [])
            key = option_candidate_key(signal)

            existing = [
                item for item in existing
                if option_candidate_key(item) != key
            ]

            existing.append(signal)
            existing = sorted(existing, key=option_candidate_rank, reverse=True)
            existing = existing[:MAX_OPTIONS_CANDIDATES_PER_TICKER]

            store[ticker]["options_candidates"] = existing
            store[ticker]["options"] = existing[0] if existing else signal

        else:
            store[ticker][tf] = signal

    return store


@app.get("/debug/rebuild")
def debug_rebuild():
    global trade_store
    trade_store = rebuild_store_from_history()

    summary = {}
    for ticker, raw in trade_store.items():
        summary[ticker] = {
            "layers": list(raw.keys()),
            "options_candidates_count": len(raw.get("options_candidates", [])),
        }

    return {
        "engine": "v10.1_debug",
        "status": "rebuilt",
        "tickers": summary,
    }


@app.get("/gpt_decision_clean")
def gpt_decision_clean():
    dashboard = build_dashboard()
    regime = market_regime()

    compact = [compact_decision_row(x) for x in dashboard]

    actionable = [
        x for x in compact
        if x.get("final_action") in ["ENTRY_OPPORTUNITY", "MANAGE_POSITION", "WAIT_FOR_DATA", "BLOCKED"]
    ]

    return {
        "engine": "v10.1_clean",
        "generated_at": now_utc().isoformat(),
        "market": {
            "regime": regime.get("regime"),
            "summary": regime.get("summary"),
            "session_state": market_session_state(),
            "execution_window": inside_execution_window(),
            "minutes_since_open": minutes_since_open(),
        },
        "top": actionable[:10],
        "all_ranked": compact[:20],
        "note": "Versión limpia: evita que Earnings PRO gane si no hay evento y reconstruye options_candidates desde historial.",
    }

# END SUPER ENGINE BOLSA — V10.1 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V10.2 PATCH
# GPT Action Plan: executive actionable output
# ============================================================

PREFERRED_STRATEGY_ORDER = {
    "COVERED_CALL_PRO": 100,
    "NAKED_PUT_PRO": 95,
    "IRON_CONDOR_PRO": 90,
    "EXIT_MANAGER": 85,
    "FUTURES_PRO": 70,
    "EARNINGS_PRO": 60,
    "NO_ENTRY_STRATEGY": 0,
}


def preferred_strategy_weight(strategy):
    return PREFERRED_STRATEGY_ORDER.get(str(strategy or "").upper(), 10)


def has_real_entry_edge(row):
    decision = str(row.get("decision") or "").upper()
    final_action = str(row.get("final_action") or "").upper()
    strategy = str(row.get("best_entry_strategy") or row.get("primary_focus") or "").upper()
    score = safe_float(row.get("best_entry_score") or row.get("master_score"), 0)

    if strategy == "EARNINGS_PRO":
        return False

    if strategy == "FUTURES_PRO" and final_action != "ENTRY_OPPORTUNITY":
        return False

    if final_action == "ENTRY_OPPORTUNITY" and decision in ["OPERAR", "RADAR"]:
        return True

    if decision in ["OPERAR", "RADAR"] and strategy in ["COVERED_CALL_PRO", "NAKED_PUT_PRO", "IRON_CONDOR_PRO"]:
        return True

    if score >= 75 and strategy in ["COVERED_CALL_PRO", "NAKED_PUT_PRO", "IRON_CONDOR_PRO"]:
        return True

    return False


def has_management_edge(row):
    final_action = str(row.get("final_action") or "").upper()
    management_action = str(row.get("best_management_action") or "").upper()
    management_decision = str(row.get("best_management_decision") or "").upper()
    alerts = row.get("management_alerts", [])

    if final_action == "MANAGE_POSITION":
        return True

    if management_action == "EXIT_MANAGER" and management_decision in ["OPERAR", "RADAR"]:
        return True

    if alerts:
        return True

    return False


def is_wait_for_data_candidate(row):
    final_action = str(row.get("final_action") or "").upper()
    decision = str(row.get("decision") or "").upper()
    missing = row.get("entry_missing_data", [])

    if final_action == "WAIT_FOR_DATA":
        return True

    if decision == "MISSING_DATA":
        return True

    if missing and row.get("best_entry_strategy") in ["COVERED_CALL_PRO", "NAKED_PUT_PRO", "IRON_CONDOR_PRO"]:
        return True

    return False


def action_priority(row):
    strategy = row.get("best_entry_strategy") or row.get("primary_focus")
    decision = str(row.get("decision") or "").upper()
    score = safe_float(row.get("best_entry_score") or row.get("master_score"), 0)
    mgmt_score = safe_float(row.get("best_management_score"), 0)
    options_count = safe_float(row.get("ibkr", {}).get("options_candidates_count"), 0)
    position_size = safe_float(row.get("ibkr", {}).get("position_size"), 0)
    price_source = str(row.get("ibkr", {}).get("price_source") or "")

    priority = 0
    priority += preferred_strategy_weight(strategy)
    priority += decision_rank(decision) * 15
    priority += score * 0.60
    priority += mgmt_score * 0.25

    if options_count > 0:
        priority += 10

    if position_size and position_size >= 100:
        priority += 10

    if price_source == "IBKR_HISTORICAL_CLOSE_FALLBACK":
        priority -= 15

    return round(priority, 2)


def compact_action_plan_row(row):
    ibkr = row.get("ibkr", {})
    best_put = ibkr.get("best_naked_put")
    best_call = ibkr.get("best_covered_call")

    suggested_action = "ESPERAR"

    if has_management_edge(row):
        suggested_action = "REVISAR_GESTION"
    elif has_real_entry_edge(row):
        if row.get("decision") == "OPERAR":
            suggested_action = "EVALUAR_ENTRADA_AHORA"
        else:
            suggested_action = "MANTENER_EN_RADAR"
    elif is_wait_for_data_candidate(row):
        suggested_action = "COMPLETAR_DATOS"
    elif row.get("final_action") == "BLOCKED":
        suggested_action = "NO_OPERAR"

    return {
        "ticker": row.get("ticker"),
        "suggested_action": suggested_action,
        "decision": row.get("decision"),
        "final_action": row.get("final_action"),
        "primary_focus": row.get("primary_focus"),
        "best_entry_strategy": row.get("best_entry_strategy"),
        "best_entry_decision": row.get("best_entry_decision"),
        "best_entry_score": row.get("best_entry_score"),
        "best_management_action": row.get("best_management_action"),
        "best_management_decision": row.get("best_management_decision"),
        "best_management_score": row.get("best_management_score"),
        "priority": action_priority(row),
        "reason": row.get("reason"),
        "entry_blockers": row.get("entry_blockers", []),
        "entry_missing_data": row.get("entry_missing_data", []),
        "management_alerts": row.get("management_alerts", []),
        "technical": row.get("technical", {}),
        "ibkr": {
            "available": ibkr.get("available"),
            "latest_price": ibkr.get("latest_price"),
            "price_source": ibkr.get("price_source"),
            "position_class": ibkr.get("position_class"),
            "position_size": ibkr.get("position_size"),
            "unrealized_pl": ibkr.get("unrealized_pl"),
            "options_candidates_count": ibkr.get("options_candidates_count"),
            "best_naked_put": best_put,
            "best_covered_call": best_call,
        },
    }


def collect_critical_missing_data(rows):
    missing_counter = {}
    affected = {}

    for row in rows:
        ticker = row.get("ticker")
        missing_items = row.get("entry_missing_data", []) or []

        for item in missing_items:
            missing_counter[item] = missing_counter.get(item, 0) + 1
            affected.setdefault(item, []).append(ticker)

    ranked = sorted(
        [
            {
                "missing_data": key,
                "count": value,
                "affected_tickers": sorted(list(set(affected.get(key, [])))),
            }
            for key, value in missing_counter.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    return ranked


@app.get("/gpt_action_plan")
def gpt_action_plan():
    dashboard = build_dashboard()
    regime = market_regime()

    decision_rows = [compact_decision_row(x) for x in dashboard]
    plan_rows = [compact_action_plan_row(x) for x in decision_rows]

    actionable_opportunities = sorted(
        [x for x in plan_rows if has_real_entry_edge(x)],
        key=action_priority,
        reverse=True,
    )

    radar_candidates = sorted(
        [
            x for x in plan_rows
            if x.get("suggested_action") == "MANTENER_EN_RADAR"
            or str(x.get("best_entry_decision") or "").upper() == "RADAR"
        ],
        key=action_priority,
        reverse=True,
    )

    management_alerts = sorted(
        [x for x in plan_rows if has_management_edge(x)],
        key=action_priority,
        reverse=True,
    )

    wait_for_data = sorted(
        [x for x in plan_rows if is_wait_for_data_candidate(x)],
        key=action_priority,
        reverse=True,
    )

    blocked = sorted(
        [x for x in plan_rows if str(x.get("final_action") or "").upper() == "BLOCKED"],
        key=action_priority,
        reverse=True,
    )

    no_trade_low_priority = sorted(
        [
            x for x in plan_rows
            if x not in actionable_opportunities
            and x not in radar_candidates
            and x not in management_alerts
            and x not in wait_for_data
            and x not in blocked
        ],
        key=action_priority,
        reverse=True,
    )

    critical_missing_data = collect_critical_missing_data(plan_rows)

    return {
        "engine": "v10.2_gpt_action_plan",
        "generated_at": now_utc().isoformat(),
        "market": {
            "regime": regime.get("regime"),
            "summary": regime.get("summary"),
            "session_state": market_session_state(),
            "execution_window": inside_execution_window(),
            "minutes_since_open": minutes_since_open(),
        },
        "executive_summary": {
            "actionable_opportunities_count": len(actionable_opportunities),
            "radar_candidates_count": len(radar_candidates),
            "management_alerts_count": len(management_alerts),
            "wait_for_data_count": len(wait_for_data),
            "blocked_count": len(blocked),
            "main_message": "Priorizar covered calls, naked puts, iron condors y gestión de posiciones abiertas. Ignorar estrategias sin edge real.",
        },
        "actionable_opportunities": actionable_opportunities[:10],
        "radar_candidates": radar_candidates[:10],
        "management_alerts": management_alerts[:10],
        "wait_for_data": wait_for_data[:10],
        "blocked": blocked[:10],
        "critical_missing_data": critical_missing_data[:10],
        "no_trade_low_priority": no_trade_low_priority[:10],
        "next_best_action": "Revisar primero management_alerts, después actionable_opportunities y finalmente wait_for_data. Confirmar precio live si price_source es IBKR_HISTORICAL_CLOSE_FALLBACK.",
    }


@app.get("/debug/routes_v10_2")
def debug_routes_v10_2():
    return {
        "engine": "v10.2",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/gpt_action_plan",
            "/gpt_decision_clean",
            "/gpt_decision",
            "/gpt_summary",
            "/debug/options",
            "/debug/stores",
            "/debug/rebuild",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V10.2 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V11 PATCH
# Iron Condor PRO Builder using multi-option candidates
# ============================================================

def get_all_option_candidates(ibkr):
    candidates = ibkr.get("options_candidates") or []
    if not isinstance(candidates, list):
        return []
    return candidates


def option_abs_delta(option):
    return abs(safe_float(option.get("delta"), 999))


def option_mid_value(option):
    return safe_float(option.get("mid"), 0)


def option_dte_value(option):
    return safe_float(option.get("dte"), None)


def option_type_value(option):
    return str(option.get("option_type") or "").upper()


def strategy_hint_value(option):
    return str(option.get("strategy_hint") or "").upper()


def iron_condor_candidate_score(option, target_delta_min=0.15, target_delta_max=0.20):
    score = 0

    delta = option.get("delta")
    mid = option_mid_value(option)
    dte = option_dte_value(option)
    quality = str(option.get("data_quality") or "").upper()
    decision = str(option.get("strategy_decision") or "").upper()

    if delta is not None:
        abs_delta = abs(safe_float(delta, 0))
        if target_delta_min <= abs_delta <= target_delta_max:
            score += 40
        elif 0.10 <= abs_delta < target_delta_min:
            score += 25
        elif target_delta_max < abs_delta <= 0.30:
            score += 15
        else:
            score -= 10
    else:
        score -= 15

    if mid and mid > 0:
        score += min(mid * 5, 20)
    else:
        score -= 15

    if dte is not None:
        if 35 <= dte <= 45:
            score += 25
        elif 25 <= dte <= 65:
            score += 10
        else:
            score -= 10
    else:
        score -= 10

    if quality in ["FULL_WITH_GREEKS", "PRICE_WITH_GREEKS_NO_BIDASK"]:
        score += 15
    elif quality == "PRICE_ONLY_NO_GREEKS":
        score -= 10

    if decision == "RADAR":
        score += 10
    elif decision == "WAIT_FOR_GREEKS":
        score -= 5

    return round(score, 2)


def select_iron_condor_leg(candidates, option_type):
    option_type = option_type.upper()
    filtered = [
        option for option in candidates
        if option_type_value(option) == option_type
    ]

    if not filtered:
        return None

    return sorted(
        filtered,
        key=lambda option: iron_condor_candidate_score(option),
        reverse=True,
    )[0]


def build_iron_condor_structure(ibkr):
    candidates = get_all_option_candidates(ibkr)

    put_leg = select_iron_condor_leg(candidates, "PUT")
    call_leg = select_iron_condor_leg(candidates, "CALL")

    estimated_credit = None
    dte_match = None
    legs_valid = bool(put_leg and call_leg)

    if put_leg and call_leg:
        put_mid = option_mid_value(put_leg)
        call_mid = option_mid_value(call_leg)
        estimated_credit = round((put_mid or 0) + (call_mid or 0), 4)

        put_dte = option_dte_value(put_leg)
        call_dte = option_dte_value(call_leg)
        dte_match = put_dte == call_dte

    return {
        "legs_valid": legs_valid,
        "put_leg": compact_option(put_leg),
        "call_leg": compact_option(call_leg),
        "estimated_short_credit": estimated_credit,
        "dte_match": dte_match,
        "put_leg_score": iron_condor_candidate_score(put_leg) if put_leg else None,
        "call_leg_score": iron_condor_candidate_score(call_leg) if call_leg else None,
        "candidates_count": len(candidates),
    }


_evaluate_iron_condor_pro_v10 = evaluate_iron_condor_pro


def evaluate_iron_condor_pro(ticker, technical, ibkr, market):
    base = _evaluate_iron_condor_pro_v10(ticker, technical, ibkr, market)
    structure = build_iron_condor_structure(ibkr)

    result = dict(base)
    details = dict(result.get("details", {}))
    blockers = list(result.get("blockers", []))
    missing = list(result.get("missing_data", []))

    details["iron_condor_structure"] = structure

    if not structure.get("put_leg"):
        missing.append("iron_condor_put_leg")

    if not structure.get("call_leg"):
        missing.append("iron_condor_call_leg")

    if structure.get("put_leg") and structure.get("call_leg"):
        result["score"] = min(100, safe_float(result.get("score"), 0) + 10)

        if structure.get("dte_match") is False:
            blockers.append("Las alas seleccionadas no tienen el mismo DTE.")

        credit = structure.get("estimated_short_credit")
        if credit is None or credit <= 0:
            missing.append("estimated_credit")
        elif credit > 0:
            details["credit_comment"] = "Hay crédito estimado positivo usando short put + short call."

        put_leg = structure.get("put_leg") or {}
        call_leg = structure.get("call_leg") or {}

        put_delta = abs(safe_float(put_leg.get("delta"), 999))
        call_delta = abs(safe_float(call_leg.get("delta"), 999))

        if 0.10 <= put_delta <= 0.30 and 0.10 <= call_delta <= 0.30:
            result["score"] = min(100, safe_float(result.get("score"), 0) + 10)
        else:
            blockers.append("Delta de una o ambas alas fuera de zona razonable 0.10–0.30.")

    result["details"] = details
    result["blockers"] = sorted(list(set(blockers)))
    result["missing_data"] = sorted(list(set(missing)))

    has_core_legs = bool(structure.get("put_leg") and structure.get("call_leg"))
    has_major_missing = any(
        item in result["missing_data"]
        for item in ["rsi", "adx", "range_20d", "vix", "iv_rank"]
    )

    if not has_core_legs:
        result["decision"] = "MISSING_DATA"
        result["reason"] = "Iron Condor potencial, pero faltan ambas alas o una de las alas."
    elif has_major_missing:
        result["decision"] = "MISSING_DATA"
        result["reason"] = "Iron Condor armado con opciones, pero faltan datos técnicos críticos para confirmar."
    elif result["blockers"]:
        result["decision"] = "RADAR" if safe_float(result.get("score"), 0) >= 70 else "BLOCKED"
        result["reason"] = "Iron Condor armado, pero existen bloqueos que deben revisarse."
    elif safe_float(result.get("score"), 0) >= 85:
        result["decision"] = "OPERAR"
        result["reason"] = "Iron Condor PRO cumple estructura, crédito estimado y condiciones principales."
    elif safe_float(result.get("score"), 0) >= 70:
        result["decision"] = "RADAR"
        result["reason"] = "Iron Condor PRO en radar con estructura válida."
    else:
        result["decision"] = "ESPERAR"
        result["reason"] = "Iron Condor todavía no tiene suficiente calidad."

    return result


@app.get("/debug/iron_condor")
def debug_iron_condor(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()

    if ticker not in trade_store:
        return {
            "engine": "v11_iron_condor",
            "ticker": ticker,
            "status": "missing_ticker",
        }

    technical = get_technical_context(ticker)
    ibkr = get_ibkr_context(ticker)
    market = get_market_context()
    result = evaluate_iron_condor_pro(ticker, technical, ibkr, market)

    return {
        "engine": "v11_iron_condor",
        "ticker": ticker,
        "technical_available": technical.get("available"),
        "ibkr_available": ibkr.get("available"),
        "options_candidates_count": ibkr.get("options_candidates_count"),
        "iron_condor": result,
    }


@app.get("/gpt_iron_condors")
def gpt_iron_condors():
    rows = []

    for ticker in sorted(trade_store.keys()):
        technical = get_technical_context(ticker)
        ibkr = get_ibkr_context(ticker)
        market = get_market_context()

        if not ibkr.get("options_candidates_count"):
            continue

        result = evaluate_iron_condor_pro(ticker, technical, ibkr, market)
        structure = result.get("details", {}).get("iron_condor_structure", {})

        rows.append({
            "ticker": ticker,
            "decision": result.get("decision"),
            "score": result.get("score"),
            "reason": result.get("reason"),
            "blockers": result.get("blockers", []),
            "missing_data": result.get("missing_data", []),
            "estimated_short_credit": structure.get("estimated_short_credit"),
            "put_leg": structure.get("put_leg"),
            "call_leg": structure.get("call_leg"),
            "dte_match": structure.get("dte_match"),
            "candidates_count": structure.get("candidates_count"),
        })

    rows = sorted(
        rows,
        key=lambda x: (decision_rank(x.get("decision")), safe_float(x.get("score"), 0)),
        reverse=True,
    )

    return {
        "engine": "v11_iron_condor",
        "generated_at": now_utc().isoformat(),
        "count": len(rows),
        "iron_condor_candidates": rows,
        "note": "V11 arma Iron Condor con mejor PUT y mejor CALL disponibles. Falta conectar ancho de spread, VIX, IV Rank, RSI, ADX y rango 20d para decisión final institucional.",
    }


@app.get("/debug/routes_v11")
def debug_routes_v11():
    return {
        "engine": "v11",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/gpt_action_plan",
            "/gpt_iron_condors",
            "/debug/iron_condor",
            "/debug/options",
            "/debug/rebuild",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V11 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V12 PATCH
# Technical Context Upgrade + Manual Market Context
# ============================================================

manual_market_store = {
    "vix": None,
    "event_risk": False,
    "macro_risk": False,
    "notes": None,
    "updated_at": None,
    "ticker_overrides": {}
}


def normalize_bool_or_none(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ["true", "1", "yes", "y", "si", "sí"]:
            return True
        if value in ["false", "0", "no", "n"]:
            return False
    return bool(value)


def merge_manual_overrides_into_classification(ticker, classification):
    ticker = ticker.upper().strip()
    classification = dict(classification)
    latest = dict(classification.get("latest_data", {}))

    overrides = manual_market_store.get("ticker_overrides", {}).get(ticker, {})

    for key in [
        "iv_rank",
        "iv_percentile",
        "earnings_soon",
        "event_risk",
        "support_near",
        "resistance_near",
        "rsi",
        "adx",
        "range_20d",
        "range_breakout",
        "institutional_flow_bias",
        "options_flow_bias",
    ]:
        if key in overrides and overrides.get(key) is not None:
            latest[key] = overrides.get(key)

    if manual_market_store.get("event_risk") is True:
        latest["event_risk"] = True

    classification["latest_data"] = latest
    return classification


_get_technical_context_v11 = get_technical_context


def get_technical_context(ticker: str):
    ticker = ticker.upper().strip()
    ctx = _get_technical_context_v11(ticker)

    if ctx.get("classification"):
        ctx["classification"] = merge_manual_overrides_into_classification(
            ticker,
            ctx["classification"]
        )

    ctx["manual_overrides"] = manual_market_store.get("ticker_overrides", {}).get(ticker, {})
    return ctx


_get_market_context_v11 = get_market_context


def get_market_context():
    base = _get_market_context_v11()

    if manual_market_store.get("vix") is not None:
        base["vix"] = manual_market_store.get("vix")

    base["manual_market_context"] = manual_market_store
    base["event_risk"] = manual_market_store.get("event_risk")
    base["macro_risk"] = manual_market_store.get("macro_risk")
    base["notes"] = manual_market_store.get("notes")
    base["manual_updated_at"] = manual_market_store.get("updated_at")

    return base


@app.post("/manual_market_context")
async def manual_market_context(request: Request):
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="ignore").strip()
    parsed = extract_json_from_text(raw_text)

    if not isinstance(parsed, dict):
        return {
            "status": "error",
            "message": "Invalid JSON payload."
        }

    if "vix" in parsed:
        manual_market_store["vix"] = safe_float(parsed.get("vix"), None)

    if "event_risk" in parsed:
        manual_market_store["event_risk"] = normalize_bool_or_none(parsed.get("event_risk"))

    if "macro_risk" in parsed:
        manual_market_store["macro_risk"] = normalize_bool_or_none(parsed.get("macro_risk"))

    if "notes" in parsed:
        manual_market_store["notes"] = parsed.get("notes")

    ticker = parsed.get("ticker")
    if ticker:
        ticker = str(ticker).upper().strip()
        manual_market_store.setdefault("ticker_overrides", {})
        manual_market_store["ticker_overrides"].setdefault(ticker, {})

        for key in [
            "iv_rank",
            "iv_percentile",
            "earnings_soon",
            "event_risk",
            "support_near",
            "resistance_near",
            "rsi",
            "adx",
            "range_20d",
            "range_breakout",
            "institutional_flow_bias",
            "options_flow_bias",
        ]:
            if key in parsed:
                manual_market_store["ticker_overrides"][ticker][key] = parsed.get(key)

        manual_market_store["ticker_overrides"][ticker]["updated_at"] = now_utc().isoformat()

    manual_market_store["updated_at"] = now_utc().isoformat()

    return {
        "status": "ok",
        "engine": "v12_manual_market_context",
        "manual_market_store": manual_market_store,
        "message": "Manual market context updated."
    }


@app.post("/technical_snapshot")
async def technical_snapshot(request: Request, x_webhook_secret: Optional[str] = Header(default=None)):
    verify_webhook_secret(x_webhook_secret)

    parsed, raw_text = await parse_request_payload(request)

    ticker = find_ticker(parsed, raw_text)
    timeframe = normalize_timeframe(parsed.get("timeframe", "1h"))

    parsed = dict(parsed)
    parsed.update({
        "ticker": ticker,
        "timeframe": timeframe,
        "received_at": now_utc().isoformat(),
        "saved_at": now_utc().isoformat(),
        "source": "TECHNICAL_SNAPSHOT",
        "raw_payload_preview": raw_text[:500],
    })

    trade_store.setdefault(ticker, {})
    trade_store[ticker][timeframe] = parsed

    # Also keep latest technical snapshot in a dedicated layer
    trade_store[ticker]["technical_snapshot"] = parsed

    classification = classify_asset(trade_store[ticker])
    parsed.update({
        "state": classification["state"],
        "grade": classification["grade"],
        "conviction": classification["conviction"],
        "priority_score": classification["priority_score"],
        "final_decision": classification["final_decision"],
        "v6_strategy": classification["v6_strategy"],
        "master_score": classification["master_score"],
    })

    storage_result = save_signal(parsed)
    unified = build_unified_context(ticker)

    return {
        "status": "ok",
        "engine": "v12_technical_snapshot",
        "message": f"Technical snapshot received for {ticker} {timeframe}",
        "ticker": ticker,
        "timeframe": timeframe,
        "storage": storage_result,
        "unified_context": unified,
        "data": parsed,
    }


@app.get("/debug/market_context")
def debug_market_context():
    return {
        "engine": "v12_market_context",
        "market_context": get_market_context(),
        "manual_market_store": manual_market_store,
    }


@app.get("/gpt_missing_data")
def gpt_missing_data():
    dashboard = build_dashboard()
    decision_rows = [compact_decision_row(x) for x in dashboard]
    plan_rows = [compact_action_plan_row(x) for x in decision_rows]
    missing = collect_critical_missing_data(plan_rows)

    return {
        "engine": "v12_missing_data",
        "generated_at": now_utc().isoformat(),
        "critical_missing_data": missing,
        "recommended_manual_updates": [
            {
                "type": "market",
                "endpoint": "/manual_market_context",
                "example": {
                    "vix": 18.5,
                    "event_risk": False,
                    "macro_risk": False,
                    "notes": "No major macro event in next 24h"
                }
            },
            {
                "type": "ticker",
                "endpoint": "/manual_market_context",
                "example": {
                    "ticker": "QQQ",
                    "iv_rank": 45,
                    "rsi": 51,
                    "adx": 18,
                    "range_20d": True,
                    "range_breakout": False,
                    "earnings_soon": False,
                    "event_risk": False
                }
            }
        ],
        "note": "Estos datos pueden alimentarse manualmente, desde TradingView o desde un futuro proveedor externo."
    }


@app.get("/debug/routes_v12")
def debug_routes_v12():
    return {
        "engine": "v12",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/manual_market_context",
            "/technical_snapshot",
            "/debug/market_context",
            "/gpt_missing_data",
            "/gpt_action_plan",
            "/gpt_iron_condors",
            "/debug/iron_condor",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V12 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V12.1 PATCH
# Manual Data Safety Cap
# ============================================================

def ticker_has_manual_override(ticker):
    ticker = str(ticker or "").upper().strip()
    overrides = manual_market_store.get("ticker_overrides", {}).get(ticker, {})
    if not overrides:
        return False

    meaningful_keys = [
        "iv_rank",
        "iv_percentile",
        "earnings_soon",
        "event_risk",
        "support_near",
        "resistance_near",
        "rsi",
        "adx",
        "range_20d",
        "range_breakout",
        "institutional_flow_bias",
        "options_flow_bias",
    ]

    return any(key in overrides and overrides.get(key) is not None for key in meaningful_keys)


def market_has_manual_context():
    return any([
        manual_market_store.get("vix") is not None,
        manual_market_store.get("event_risk") is not None,
        manual_market_store.get("macro_risk") is not None,
        manual_market_store.get("notes") is not None,
    ])


def manual_data_used_for_strategy(ticker, strategy_name):
    strategy_name = str(strategy_name or "").upper()

    # Iron Condor depende mucho de VIX, IV Rank, RSI, ADX y rango.
    if strategy_name == "IRON_CONDOR_PRO":
        return ticker_has_manual_override(ticker) or market_has_manual_context()

    # Naked Put y Covered Call también pueden depender de IV Rank / soporte / resistencia.
    if strategy_name in ["NAKED_PUT_PRO", "COVERED_CALL_PRO"]:
        return ticker_has_manual_override(ticker)

    return False


def apply_manual_data_safety_cap(ticker, result):
    result = dict(result)
    strategy_name = str(result.get("strategy") or "").upper()

    if not manual_data_used_for_strategy(ticker, strategy_name):
        return result

    details = dict(result.get("details", {}))
    blockers = list(result.get("blockers", []))

    details["manual_data_safety_cap"] = {
        "active": True,
        "reason": "La decisión usa datos manuales/provisionales. Se limita la decisión máxima a RADAR.",
        "manual_market_updated_at": manual_market_store.get("updated_at"),
        "ticker_manual_override": manual_market_store.get("ticker_overrides", {}).get(str(ticker).upper().strip(), {}),
    }

    if result.get("decision") == "OPERAR":
        result["decision"] = "RADAR"
        result["reason"] = str(result.get("reason", "")) + " Decisión limitada a RADAR por uso de datos manuales."
        blockers.append("Manual data safety cap: confirmar datos desde fuente automatizada antes de operar.")

    result["details"] = details
    result["blockers"] = sorted(list(set(blockers)))

    return result


_evaluate_iron_condor_pro_v12 = evaluate_iron_condor_pro
_evaluate_naked_put_pro_v12 = evaluate_naked_put_pro
_evaluate_covered_call_pro_v12 = evaluate_covered_call_pro


def evaluate_iron_condor_pro(ticker, technical, ibkr, market):
    result = _evaluate_iron_condor_pro_v12(ticker, technical, ibkr, market)
    return apply_manual_data_safety_cap(ticker, result)


def evaluate_naked_put_pro(ticker, technical, ibkr, market):
    result = _evaluate_naked_put_pro_v12(ticker, technical, ibkr, market)
    return apply_manual_data_safety_cap(ticker, result)


def evaluate_covered_call_pro(ticker, technical, ibkr, market):
    result = _evaluate_covered_call_pro_v12(ticker, technical, ibkr, market)
    return apply_manual_data_safety_cap(ticker, result)


@app.get("/debug/manual_safety")
def debug_manual_safety(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()

    technical = get_technical_context(ticker)
    ibkr = get_ibkr_context(ticker)
    market = get_market_context()

    iron = evaluate_iron_condor_pro(ticker, technical, ibkr, market)
    naked_put = evaluate_naked_put_pro(ticker, technical, ibkr, market)
    covered_call = evaluate_covered_call_pro(ticker, technical, ibkr, market)

    return {
        "engine": "v12.1_manual_safety",
        "ticker": ticker,
        "market_has_manual_context": market_has_manual_context(),
        "ticker_has_manual_override": ticker_has_manual_override(ticker),
        "manual_market_store": manual_market_store,
        "iron_condor": iron,
        "naked_put": naked_put,
        "covered_call": covered_call,
        "note": "Si una estrategia dependía de datos manuales y antes decía OPERAR, ahora debe quedar limitada a RADAR."
    }


@app.get("/debug/routes_v12_1")
def debug_routes_v12_1():
    return {
        "engine": "v12.1",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/debug/manual_safety",
            "/debug/iron_condor",
            "/gpt_iron_condors",
            "/gpt_action_plan",
            "/manual_market_context",
            "/technical_snapshot",
            "/debug/market_context",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V12.1 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V13 PATCH
# Automated TradingView Technical Snapshot Integration
# ============================================================

TECHNICAL_SNAPSHOT_FIELDS = [
    "rsi",
    "adx",
    "range_20d",
    "range_breakout",
    "support_near",
    "resistance_near",
    "vwap_position",
    "volume_relative",
    "iv_rank",
    "iv_percentile",
    "earnings_soon",
    "event_risk",
    "institutional_flow_bias",
    "options_flow_bias",
]


def get_latest_technical_snapshot(ticker):
    ticker = str(ticker or "").upper().strip()
    raw = trade_store.get(ticker, {})
    snap = raw.get("technical_snapshot")

    if isinstance(snap, dict):
        return snap

    # fallback: look through common timeframes for TECHNICAL_SNAPSHOT source
    for tf in ["5m", "15m", "1h", "1d", "live"]:
        item = raw.get(tf)
        if isinstance(item, dict) and str(item.get("source", "")).upper() == "TECHNICAL_SNAPSHOT":
            return item

    return None


def merge_technical_snapshot_into_classification(ticker, classification):
    ticker = str(ticker or "").upper().strip()
    classification = dict(classification)
    latest = dict(classification.get("latest_data", {}))

    snap = get_latest_technical_snapshot(ticker)

    if not snap:
        classification["latest_data"] = latest
        classification["technical_snapshot_used"] = False
        return classification

    for key in TECHNICAL_SNAPSHOT_FIELDS:
        if key in snap and snap.get(key) is not None:
            latest[key] = snap.get(key)

    classification["latest_data"] = latest
    classification["technical_snapshot_used"] = True
    classification["technical_snapshot_received_at"] = snap.get("received_at")
    classification["technical_snapshot_timeframe"] = snap.get("timeframe")
    classification["technical_snapshot_source"] = snap.get("source")

    return classification


_get_technical_context_v12_1 = get_technical_context


def get_technical_context(ticker: str):
    ticker = ticker.upper().strip()
    ctx = _get_technical_context_v12_1(ticker)

    if ctx.get("classification"):
        ctx["classification"] = merge_technical_snapshot_into_classification(
            ticker,
            ctx["classification"]
        )

    ctx["technical_snapshot"] = get_latest_technical_snapshot(ticker)
    ctx["technical_snapshot_available"] = ctx["technical_snapshot"] is not None

    return ctx


@app.get("/debug/technical_context")
def debug_technical_context(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()

    return {
        "engine": "v13_technical_context",
        "ticker": ticker,
        "ticker_in_memory": ticker in trade_store,
        "technical_context": get_technical_context(ticker),
        "latest_technical_snapshot": get_latest_technical_snapshot(ticker),
        "available_layers": list(trade_store.get(ticker, {}).keys()),
    }


@app.get("/gpt_technical_payload_template")
def gpt_technical_payload_template(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()

    return {
        "engine": "v13_technical_payload_template",
        "endpoint": "/technical_snapshot",
        "method": "POST",
        "content_type": "application/json",
        "example_payload": {
            "ticker": ticker,
            "timeframe": "1h",
            "price": 714.51,
            "trend": "neutral",
            "score": 70,
            "rsi": 51,
            "adx": 18,
            "range_20d": True,
            "range_breakout": False,
            "support_near": False,
            "resistance_near": False,
            "vwap_position": "near",
            "volume_relative": 1.0,
            "iv_rank": 45,
            "earnings_soon": False,
            "event_risk": False
        },
        "tradingview_alert_message_example": {
            "ticker": "{{ticker}}",
            "timeframe": "{{interval}}",
            "price": "{{close}}",
            "trend": "neutral",
            "score": 70,
            "rsi": "{{plot(\"RSI\")}}",
            "adx": "{{plot(\"ADX\")}}",
            "range_20d": True,
            "range_breakout": False,
            "support_near": False,
            "resistance_near": False,
            "vwap_position": "near",
            "volume_relative": 1.0,
            "iv_rank": None,
            "earnings_soon": False,
            "event_risk": False
        },
        "note": "TradingView debe mandar estos campos a /technical_snapshot para que el motor use datos técnicos automatizados y deje de depender de manual_market_context."
    }


@app.get("/debug/routes_v13")
def debug_routes_v13():
    return {
        "engine": "v13",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/technical_snapshot",
            "/debug/technical_context",
            "/gpt_technical_payload_template",
            "/debug/iron_condor",
            "/gpt_iron_condors",
            "/gpt_action_plan",
            "/manual_market_context",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V13 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V13.1 PATCH
# Prefer automated technical snapshot over manual context
# + clear manual context endpoint
# ============================================================

def ticker_has_automated_technical_snapshot(ticker):
    ticker = str(ticker or "").upper().strip()
    snap = get_latest_technical_snapshot(ticker)

    if not isinstance(snap, dict):
        return False

    if str(snap.get("source", "")).upper() != "TECHNICAL_SNAPSHOT":
        return False

    meaningful_keys = [
        "rsi",
        "adx",
        "range_20d",
        "range_breakout",
        "support_near",
        "resistance_near",
        "vwap_position",
        "volume_relative",
        "iv_rank",
        "iv_percentile",
        "earnings_soon",
        "event_risk",
    ]

    return any(key in snap and snap.get(key) is not None for key in meaningful_keys)


_apply_manual_data_safety_cap_v12_1 = apply_manual_data_safety_cap


def apply_manual_data_safety_cap(ticker, result):
    ticker = str(ticker or "").upper().strip()

    # If TradingView/technical_snapshot is available, treat it as preferred automated context.
    # Manual context should not cap the decision when automated technical data exists.
    if ticker_has_automated_technical_snapshot(ticker):
        result = dict(result)
        details = dict(result.get("details", {}))
        details["manual_data_safety_cap"] = {
            "active": False,
            "reason": "Automated technical snapshot is available; manual context is not capping this decision.",
            "technical_snapshot_available": True,
            "technical_snapshot_received_at": (get_latest_technical_snapshot(ticker) or {}).get("received_at"),
        }
        result["details"] = details
        return result

    return _apply_manual_data_safety_cap_v12_1(ticker, result)


@app.post("/clear_manual_context")
def clear_manual_context():
    manual_market_store["vix"] = None
    manual_market_store["event_risk"] = False
    manual_market_store["macro_risk"] = False
    manual_market_store["notes"] = None
    manual_market_store["updated_at"] = now_utc().isoformat()
    manual_market_store["ticker_overrides"] = {}

    return {
        "status": "ok",
        "engine": "v13.1_clear_manual_context",
        "message": "Manual market context cleared.",
        "manual_market_store": manual_market_store,
    }


@app.get("/debug/data_sources")
def debug_data_sources(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()

    snap = get_latest_technical_snapshot(ticker)
    ibkr = get_ibkr_context(ticker)
    manual_override = manual_market_store.get("ticker_overrides", {}).get(ticker, {})

    return {
        "engine": "v13.1_data_sources",
        "ticker": ticker,
        "sources": {
            "ibkr_available": ibkr.get("available"),
            "ibkr_price_source": ibkr.get("price_source"),
            "ibkr_options_candidates_count": ibkr.get("options_candidates_count"),
            "technical_snapshot_available": snap is not None,
            "technical_snapshot_source": (snap or {}).get("source") if snap else None,
            "technical_snapshot_received_at": (snap or {}).get("received_at") if snap else None,
            "manual_market_context_active": market_has_manual_context(),
            "manual_ticker_override_active": ticker_has_manual_override(ticker),
            "automated_snapshot_preferred": ticker_has_automated_technical_snapshot(ticker),
        },
        "technical_snapshot": snap,
        "manual_override": manual_override,
        "manual_market_store": manual_market_store,
    }


@app.get("/debug/routes_v13_1")
def debug_routes_v13_1():
    return {
        "engine": "v13.1",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/clear_manual_context",
            "/debug/data_sources",
            "/debug/technical_context",
            "/technical_snapshot",
            "/debug/iron_condor",
            "/gpt_iron_condors",
            "/gpt_action_plan",
            "/manual_market_context",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V13.1 PATCH
