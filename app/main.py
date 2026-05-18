from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import re
import os
import math
import requests

app = FastAPI(title="Super Engine Bolsa", version="7.0.0")

SIGNALS_FILE = "signals_history.json"
OUTCOMES_FILE = "trade_outcomes.json"
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
    closed = [o for o in outcomes if str(o.get("outcome", "")).upper() in ["WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"]]
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
    return match.group(1).upper().strip() if match else "UNKNOWN"


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

    priority_score = calculate_priority_score(state, grade, conviction, weighted_score, freshness_weighted, alignment)
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
    return {"regime": regime, "summary": summary, "spy": spy, "qqq": qqq, "tlt": tlt, "iwm": iwm, "vix": vix, "dxy": dxy}


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
    return {"probability_estimate": probability, "confidence": confidence, "risk": risk, "alignment_score": alignment_score}


def expected_pl_engine(classification, account_size=None):
    priority = safe_float(classification.get("priority_score"), 0)
    entry = safe_float(classification.get("entry"), 0)
    stop = safe_float(classification.get("stop"), 0)
    risk_budget = (account_size * 0.01) if account_size else 1000
    units = math.floor(risk_budget / abs(entry - stop)) if entry and stop and abs(entry - stop) > 0 else None
    base = round((priority - 50) * 12, 2)
    return {"base_case_pl": base, "favorable_case_pl": round(base * 2, 2), "adverse_case_pl": round(-risk_budget, 2), "risk_budget_assumption": risk_budget, "suggested_units_if_entry_stop_available": units}


def grade_from_score(score):
    if score >= 88:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    return "C"


def decision_rank(decision):
    return {"OPERAR": 5, "RADAR": 4, "ESPERAR": 3, "EXPIRADO": 2, "EVITAR": 1}.get(decision, 0)


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
            intraday = {"state": "VALID", "decision": "OPERAR", "score": priority + 12, "reason": "1h + 15m + 5m alineados dentro de ventana intradía."}
        elif score >= 75:
            intraday = {"state": "EXPIRED", "decision": "EXPIRADO", "score": priority - 10, "reason": "Setup intradía válido, pero fuera de la ventana inicial."}
        else:
            intraday = {"state": "FORMING", "decision": "RADAR", "score": priority, "reason": "Alineación intradía parcial o score insuficiente."}
    else:
        intraday = {"state": "NO_EDGE", "decision": "ESPERAR", "score": priority - 20, "reason": "No hay alineación 1h + 15m + 5m para intradía."}
    brains["intraday"] = {"strategy": "INTRADAY_BREAKOUT", "requires_window": True, **intraday}

    if bull1h and (bull1d or not flags.get("has_1d", False)) and score >= 70:
        decision = "OPERAR" if score >= 78 and classification.get("state") != "EXTENDED_LONG" else "RADAR"
        swing = {"state": "BULLISH", "decision": decision, "score": priority + 8, "reason": "Contexto 1h alcista con 1d alcista/neutro."}
    elif bear1h and bear1d and score >= 70:
        decision = "OPERAR" if score >= 78 else "RADAR"
        swing = {"state": "BEARISH", "decision": decision, "score": priority + 8, "reason": "Contexto 1h y 1d bajista."}
    else:
        swing = {"state": "NO_EDGE", "decision": "ESPERAR", "score": priority - 10, "reason": "No hay contexto swing suficiente."}
    brains["swing"] = {"strategy": "SWING", "requires_window": False, **swing}

    if not bear1h and not bear1d and priority >= 60 and (not price or price >= MIN_PRICE_FOR_THETA) and (iv_rank is None or iv_rank >= 30) and not event_risk:
        if support or (iv_rank is not None and iv_rank >= 50):
            theta_np = {"state": "NAKED_PUT_FAVORABLE", "decision": "OPERAR", "score": priority + 9, "reason": "Naked put favorable: tendencia no bajista, soporte/IV adecuados."}
        else:
            theta_np = {"state": "NAKED_PUT_WATCH", "decision": "ESPERAR", "score": priority + 2, "reason": "Naked put posible, falta soporte claro o IV más atractiva."}
    else:
        theta_np = {"state": "NAKED_PUT_AVOID", "decision": "EVITAR", "score": priority - 15, "reason": "No cumple condiciones mínimas para naked put."}

    if has_position and (classification.get("state") == "EXTENDED_LONG" or resistance):
        theta_cc = {"state": "COVERED_CALL_FAVORABLE", "decision": "OPERAR", "score": priority + 6, "reason": "Covered call favorable si ya tienes acciones y hay resistencia/extensión."}
    elif resistance or classification.get("state") == "EXTENDED_LONG":
        theta_cc = {"state": "COVERED_CALL_RADAR", "decision": "RADAR", "score": priority, "reason": "Covered call en radar; confirmar posición o resistencia."}
    else:
        theta_cc = {"state": "COVERED_CALL_NEUTRAL", "decision": "ESPERAR", "score": priority - 5, "reason": "Sin extensión/resistencia suficiente para covered call."}

    brains["theta"] = {"strategy": "THETA", "requires_window": False, "naked_put": theta_np, "covered_call": theta_cc, **(theta_np if decision_rank(theta_np["decision"]) >= decision_rank(theta_cc["decision"]) else theta_cc)}

    if earnings_soon:
        if iv_rank is not None and iv_rank >= 50 and not event_risk:
            earnings = {"state": "EARNINGS_IV_HIGH", "decision": "OPERAR", "score": priority + 5, "reason": "Earnings próximo con IV alta; evaluar play definido."}
        else:
            earnings = {"state": "EARNINGS_WAIT", "decision": "ESPERAR", "score": priority - 2, "reason": "Earnings próximo, pero IV insuficiente o riesgo elevado."}
    else:
        earnings = {"state": "NO_EVENT", "decision": "ESPERAR", "score": priority - 10, "reason": "No hay evento de earnings próximo."}
    brains["earnings"] = {"strategy": "EARNINGS", "requires_window": False, **earnings}

    if asset_class in ["FUTURE", "FUTURES"] or hint in ["FUTURES", "FUTURE", "MNQ", "NQ", "ES"]:
        if has_5 and has_15 and has_1h and score >= 75:
            futures = {"state": "FUTURES_READY", "decision": "OPERAR", "score": priority + 6, "reason": "Futuros con alineación multi-timeframe; gestionar por sesión."}
        else:
            futures = {"state": "FUTURES_RADAR", "decision": "RADAR", "score": priority, "reason": "Futuros en observación; falta alineación completa."}
    else:
        futures = {"state": "NOT_FUTURES", "decision": "ESPERAR", "score": priority - 20, "reason": "Activo no marcado como futuro."}
    brains["futures"] = {"strategy": "FUTURES", "requires_window": False, **futures}

    candidates = [brains[k] for k in ["intraday", "swing", "theta", "earnings", "futures"]]
    final = sorted(candidates, key=lambda x: (decision_rank(x["decision"]), x["score"]), reverse=True)[0]
    brains["final"] = {"final_decision": final["decision"], "strategy": final["strategy"], "state": final["state"], "score": round(final["score"], 2), "reason": final["reason"]}
    return brains


def risk_engine(classification, regime="MIXED_OR_CHOP", brain=None):
    brain = brain or {"strategy": "NO_TRADE", "requires_window": False, "decision": "ESPERAR"}
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
    return {"trade_allowed": allowed, "risk_level": "LOW" if allowed and priority >= 85 else "MEDIUM" if priority >= 70 else "HIGH", "warnings": warnings, "capital_preservation_bias": not allowed}


def classify_asset(timeframes):
    core = technical_core(timeframes)
    regime = "MIXED_OR_CHOP"
    brains = build_brains(core, regime)
    probability = probability_engine(core, regime)
    risk = risk_engine(core, regime, brains.get("final"))
    core["brains"] = brains
    core["final_decision"] = brains["final"]["final_decision"]
    core["v6_strategy"] = brains["final"]["strategy"]
    core["v6_state"] = brains["final"]["state"]
    core["v6_reason"] = brains["final"]["reason"]
    core["master_score"] = round((safe_float(core.get("priority_score"), 0) * 0.45) + (safe_float(brains["final"].get("score"), 0) * 0.35) + (probability["probability_estimate"] * 0.20), 2)
    core["probability"] = probability
    core["risk"] = risk
    core["expected_pl"] = expected_pl_engine(core)
    return core


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
        master_score = round((safe_float(c.get("priority_score"), 0) * 0.45) + (safe_float(final.get("score"), 0) * 0.35) + (probability["probability_estimate"] * 0.20), 2)
        dashboard.append({
            "ticker": ticker,
            "final_decision": final["final_decision"],
            "v6_strategy": final["strategy"],
            "v6_state": final["state"],
            "v6_reason": final["reason"],
            "master_score": master_score,
            "brains": brains,
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
        })
    return sorted(dashboard, key=lambda x: (decision_rank(x["final_decision"]), x["master_score"], x["priority_score"]), reverse=True)


def stats_from_signals(signals):
    by_ticker, by_timeframe, by_setup, by_state, by_decision = {}, {}, {}, {}, {}
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
    return {"total_signals": len(signals), "by_ticker": by_ticker, "by_timeframe": by_timeframe, "by_setup": by_setup, "by_state": by_state, "by_decision": by_decision}


def verify_webhook_secret(x_webhook_secret: Optional[str]):
    if REQUIRE_WEBHOOK_SECRET:
        if not WEBHOOK_SECRET:
            raise HTTPException(status_code=500, detail="WEBHOOK_SECRET required but not configured")
        if x_webhook_secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")


def grouped_dashboard():
    dashboard = build_dashboard()
    groups = {"OPERAR": [], "RADAR": [], "ESPERAR": [], "EVITAR": [], "EXPIRADO": []}
    for item in dashboard:
        groups.setdefault(item["final_decision"], []).append(item)
    return groups


@app.on_event("startup")
def startup():
    global trade_store
    trade_store = rebuild_store_from_history()


@app.get("/")
def root():
    return {"status": "alive", "engine": "Super Engine Bolsa v7.0", "mode": "Release Candidate Institutional Desk Core"}


@app.get("/health")
def health():
    signals = load_signals(limit=100)
    return {
        "status": "ok",
        "engine": "Super Engine Bolsa v7.0",
        "mode": "Release Candidate Institutional Desk Core",
        "operating_mode": OPERATING_MODE,
        "supabase_enabled": supabase_enabled(),
        "webhook_secret_required": REQUIRE_WEBHOOK_SECRET,
        "total_recent_signals_loaded": len(signals),
        "tickers_in_memory": list(trade_store.keys()),
        "last_signal": signals[-1] if signals else None,
        "expiration_minutes": EXPIRATION_MINUTES,
        "market_clock": {"market_timezone": "America/New_York", "session_state": market_session_state(), "execution_window": inside_execution_window(), "minutes_since_open": minutes_since_open(), "initial_window_minutes": INITIAL_WINDOW_MINUTES},
    }


@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request, x_webhook_secret: Optional[str] = Header(default=None)):
    verify_webhook_secret(x_webhook_secret)
    raw_body = await request.body()
    raw_text = raw_body.decode("utf-8", errors="ignore").strip()
    parsed = extract_json_from_text(raw_text)
    if not isinstance(parsed, dict):
        parsed = {"raw_message": raw_text, "parse_warning": "payload not valid json"}
    ticker = find_ticker(parsed, raw_text)
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))
    parsed.update({"ticker": ticker, "timeframe": timeframe, "received_at": now_utc().isoformat(), "saved_at": now_utc().isoformat(), "source": "tradingview", "raw_payload_preview": raw_text[:500]})
    trade_store.setdefault(ticker, {})[timeframe] = parsed
    classification = classify_asset(trade_store[ticker])
    parsed.update({"state": classification["state"], "grade": classification["grade"], "conviction": classification["conviction"], "priority_score": classification["priority_score"], "final_decision": classification["final_decision"], "v6_strategy": classification["v6_strategy"], "master_score": classification["master_score"]})
    trade_store[ticker][timeframe] = parsed
    storage_result = save_signal(parsed)
    return {"status": "ok", "engine": "v7.0", "message": f"Webhook received for {ticker} {timeframe}", "ticker": ticker, "timeframe": timeframe, "storage": storage_result, "classification": classification, "data": parsed}


@app.post("/test_signal")
def test_signal(signal: TradingSignal):
    parsed = signal.dict(exclude_none=True)
    if parsed.get("extra"):
        parsed.update(parsed.pop("extra"))
    ticker = find_ticker(parsed, json.dumps(parsed))
    timeframe = normalize_timeframe(parsed.get("timeframe", "unknown"))
    parsed.update({"ticker": ticker, "timeframe": timeframe, "received_at": now_utc().isoformat(), "saved_at": now_utc().isoformat(), "source": "manual_test"})
    trade_store.setdefault(ticker, {})[timeframe] = parsed
    classification = classify_asset(trade_store[ticker])
    parsed.update({"state": classification["state"], "grade": classification["grade"], "conviction": classification["conviction"], "priority_score": classification["priority_score"], "final_decision": classification["final_decision"], "v6_strategy": classification["v6_strategy"], "master_score": classification["master_score"]})
    trade_store[ticker][timeframe] = parsed
    storage_result = save_signal(parsed)
    return {"status": "ok", "engine": "v7.0", "message": f"Test signal saved for {ticker} {timeframe}", "storage": storage_result, "classification": classification, "data": parsed}


@app.get("/get_trade_context")
def get_trade_context(ticker: str):
    ticker = ticker.upper().strip()
    if ticker not in trade_store:
        return {"ticker": ticker, "status": "missing_data", "message": "No hay datos todavía para este ticker."}
    return {"ticker": ticker, "engine": "v7.0", "classification": classify_asset(trade_store[ticker])}


@app.get("/get_dashboard")
def get_dashboard():
    dashboard = build_dashboard()
    for i, item in enumerate(dashboard, start=1):
        item["priority_rank"] = i
    return {"generated_at": now_utc().isoformat(), "engine": "v7.0", "supabase_enabled": supabase_enabled(), "market_regime": market_regime(), "dashboard": dashboard, "groups": grouped_dashboard(), "best_setups": dashboard[:5]}


@app.get("/get_report")
def get_report():
    groups = grouped_dashboard()
    regime = market_regime()
    lines = ["SUPER ENGINE BOLSA v6.0 — RELEASE CANDIDATE INSTITUTIONAL DESK", f"Generado UTC: {now_utc().isoformat()}", "", "RÉGIMEN DE MERCADO", f"- Estado: {regime['regime']}", f"- Lectura: {regime['summary']}", f"- Sesión: {market_session_state()}", f"- Minutos desde apertura: {round(minutes_since_open(), 1)}", f"- Ventana intradía activa: {inside_execution_window()}", ""]
    for decision in ["OPERAR", "RADAR", "ESPERAR", "EVITAR", "EXPIRADO"]:
        lines.append(decision)
        items = groups.get(decision, [])
        if not items:
            lines.append("- Sin candidatos")
        for x in items[:10]:
            lines.append(f"- {x['ticker']} | {x['v6_strategy']} | {x['v6_state']} | Master {x['master_score']} | Priority {x['priority_score']} | Prob {x['probability']['probability_estimate']}% | Risk {x['risk']['risk_level']} | {x['v6_reason']}")
        lines.append("")
    return {"generated_at": now_utc().isoformat(), "engine": "v7.0", "supabase_enabled": supabase_enabled(), "report": "\n".join(lines), "groups": groups, "best_setups": build_dashboard()[:5]}


@app.get("/gpt_report")
def gpt_report():
    dashboard = build_dashboard()
    regime = market_regime()
    if not dashboard:
        return {"engine": "v7.0", "market": regime["regime"], "status": "NO_DATA", "plan": "Esperar nuevas señales frescas."}
    return {
        "engine": "v7.0",
        "market_regime": regime["regime"],
        "market_summary": regime["summary"],
        "session_state": market_session_state(),
        "execution_window": inside_execution_window(),
        "minutes_since_open": minutes_since_open(),
        "top_focus": [{"ticker": x["ticker"], "decision": x["final_decision"], "strategy": x["v6_strategy"], "state": x["v6_state"], "master_score": x["master_score"], "grade": x["grade"], "conviction": x["conviction"], "priority_score": x["priority_score"], "probability": x["probability"]["probability_estimate"], "risk": x["risk"]["risk_level"], "trade_allowed": x["risk"]["trade_allowed"], "reason": x["v6_reason"], "warnings": x["risk"].get("warnings", []), "brains": x["brains"]} for x in dashboard[:5]],
        "operate_now": [x for x in dashboard if x["final_decision"] == "OPERAR"][:5],
        "radar": [x for x in dashboard if x["final_decision"] == "RADAR"][:5],
        "avoid": [x for x in dashboard if x["final_decision"] in ["EVITAR", "EXPIRADO"]][:5],
    }


@app.get("/premarket_plan")
def premarket_plan():
    dashboard = build_dashboard()
    regime = market_regime()
    return {"engine": "v7.0", "generated_at": now_utc().isoformat(), "market_regime": regime, "session_state": market_session_state(), "plan": {"operate": [x for x in dashboard if x["final_decision"] == "OPERAR"][:5], "radar": [x for x in dashboard if x["final_decision"] == "RADAR"][:10], "avoid": [x for x in dashboard if x["final_decision"] in ["EVITAR", "EXPIRADO"]][:10]}, "note": "Premarket plan usa las últimas señales disponibles; ideal actualizar 1d/1h antes de apertura."}


@app.get("/after_action_review")
def after_action_review(limit: int = 500):
    signals = load_signals(limit=limit)
    stats = stats_from_signals(signals)
    recent_decisions = [s for s in signals if s.get("final_decision")]
    return {"engine": "v7.0", "generated_at": now_utc().isoformat(), "review_window_signals": len(signals), "stats": stats, "recent_decisions": recent_decisions[-50:], "note": "AAR todavía no calcula win rate real hasta conectar precios posteriores o resultados manuales."}


@app.post("/position_sizing")
def position_sizing(req: PositionSizingRequest):
    risk_budget = req.account_size * (req.risk_percent / 100)
    unit_risk = abs(req.entry - req.stop)
    if unit_risk <= 0:
        return {"error": "Entry and stop cannot be equal."}
    return {"engine": "v7.0", "account_size": req.account_size, "risk_percent": req.risk_percent, "risk_budget": round(risk_budget, 2), "entry": req.entry, "stop": req.stop, "unit_risk": round(unit_risk, 4), "suggested_units": math.floor(risk_budget / unit_risk)}


@app.post("/portfolio_commander")
def portfolio_commander(req: PortfolioInput):
    dashboard = build_dashboard()
    operate = [x for x in dashboard if x["final_decision"] == "OPERAR"]
    theta_candidates = [x for x in operate if x["v6_strategy"] == "THETA"]
    futures_candidates = [x for x in operate if x["v6_strategy"] == "FUTURES"]
    warnings = []
    if req.open_naked_puts and req.open_naked_puts >= 4:
        warnings.append("Exposición alta en naked puts; considerar concentración y margen.")
    if req.open_futures and req.open_futures >= 2:
        warnings.append("Exposición alta en futuros; controlar drawdown intradía.")
    if len(theta_candidates) >= 3:
        warnings.append("Muchas oportunidades theta simultáneas; priorizar por IV/soporte/correlación.")
    return {"engine": "v7.0", "operating_mode": OPERATING_MODE, "portfolio_input": req.dict(), "summary": {"operate_candidates": len(operate), "theta_candidates": len(theta_candidates), "futures_candidates": len(futures_candidates), "directional_bias": req.directional_bias}, "warnings": warnings, "top_candidates": operate[:5]}


@app.post("/evaluate_option")
def evaluate_option(req: OptionEvalRequest):
    ticker = req.ticker.upper().strip()
    context = technical_core(trade_store.get(ticker, {})) if ticker in trade_store else None
    regime = market_regime().get("regime", "MIXED_OR_CHOP")
    margin_yield = round((req.premium / req.margin_required) * 100, 2) if req.premium and req.margin_required and req.margin_required > 0 else None
    iv_comment = "IV no proporcionada."
    if req.iv_rank is not None:
        iv_comment = "IV rank favorable para venta de prima." if req.iv_rank >= 50 else "IV rank moderada; venta de prima condicional." if req.iv_rank >= 30 else "IV rank baja; prima puede no compensar riesgo."
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
        brains = build_brains(context, regime)
        strategy_context = brains
        dictamen = f"Dictamen V6: {brains['final']['final_decision']} / {brains['final']['strategy']} — {brains['final']['reason']}"
    return {"engine": "v7.0", "ticker": ticker, "strategy": req.strategy, "strike": req.strike, "premium": req.premium, "dte": req.dte, "margin_required": req.margin_required, "premium_on_margin_percent": margin_yield, "iv_rank": req.iv_rank, "iv_comment": iv_comment, "context_available": context is not None, "technical_context": context, "strategy_context": strategy_context, "dictamen": dictamen}


@app.get("/latest")
def latest():
    return trade_store


@app.get("/history")
def history(limit: int = 100):
    signals = load_signals(limit=limit)
    return {"engine": "v7.0", "supabase_enabled": supabase_enabled(), "showing": min(limit, len(signals)), "signals": signals[-limit:]}


@app.get("/stats")
def stats(limit: int = 1000):
    signals = load_signals(limit=limit)
    return {"engine": "v7.0", "generated_at": now_utc().isoformat(), "stats": stats_from_signals(signals)}


@app.get("/stats/ticker/{ticker}")
def stats_ticker(ticker: str, limit: int = 1000):
    ticker = ticker.upper().strip()
    signals = [s for s in load_signals(limit=limit) if str(s.get("ticker", "")).upper() == ticker]
    return {"engine": "v7.0", "ticker": ticker, "generated_at": now_utc().isoformat(), "stats": stats_from_signals(signals), "signals": signals[-50:]}


@app.get("/debug/supabase")
def debug_supabase():
    return {"engine": "v7.0", "supabase_enabled": supabase_enabled(), "supabase_url_present": bool(SUPABASE_URL), "supabase_key_present": bool(SUPABASE_KEY), "count_test": supabase_count_signals()}


@app.get("/debug/regime")
def debug_regime():
    return {"engine": "v7.0", "market_regime": market_regime(), "market_clock": {"market_timezone": "America/New_York", "session_state": market_session_state(), "execution_window": inside_execution_window(), "minutes_since_open": minutes_since_open(), "initial_window_minutes": INITIAL_WINDOW_MINUTES}}


@app.get("/debug/scoring")
def debug_scoring(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()
    if ticker not in trade_store:
        return {"engine": "v7.0", "ticker": ticker, "error": "Ticker not in memory"}
    regime = market_regime().get("regime", "MIXED_OR_CHOP")
    c = technical_core(trade_store[ticker])
    return {"engine": "v7.0", "ticker": ticker, "classification": classify_asset(trade_store[ticker]), "brains": build_brains(c, regime), "probability": probability_engine(c, regime), "expected_pl": expected_pl_engine(c)}


@app.get("/debug/routes")
def debug_routes():
    return {"engine": "v7.0", "routes": ["/", "/health", "/webhook/tradingview", "/test_signal", "/get_trade_context", "/get_dashboard", "/get_report", "/gpt_report", "/premarket_plan", "/after_action_review", "/record_outcome", "/outcomes", "/live_market_input", "/v7_live_snapshot", "/v7_status", "/record_outcome", "/outcomes", "/live_market_input", "/v7_live_snapshot", "/v7_status", "/portfolio_commander", "/position_sizing", "/evaluate_option", "/latest", "/history", "/stats", "/stats/ticker/{ticker}", "/debug/supabase", "/debug/regime", "/debug/scoring", "/debug/routes", "/dashboard_html"]}


@app.get("/dashboard_html", response_class=HTMLResponse)
def dashboard_html():
    groups = grouped_dashboard()
    regime = market_regime()
    decision_color = {"OPERAR": "#0B6E4F", "RADAR": "#2A9D8F", "ESPERAR": "#F4A261", "EVITAR": "#E76F51", "EXPIRADO": "#6C757D"}
    sections = ""
    for decision in ["OPERAR", "RADAR", "ESPERAR", "EVITAR", "EXPIRADO"]:
        rows = ""
        for i, item in enumerate(groups.get(decision, []), start=1):
            rows += f"""
            <tr>
                <td>{i}</td><td>{item['ticker']}</td><td>{item['v6_strategy']}</td><td>{item['v6_state']}</td>
                <td>{item['master_score']}</td><td>{item['grade']}</td><td>{item['conviction']}</td>
                <td>{item['probability']['probability_estimate']}%</td><td>{item['risk']['risk_level']}</td><td>{item['risk']['trade_allowed']}</td>
                <td>{item['v6_reason']}</td>
            </tr>
            """
        sections += f"""
        <h2 style='border-left:6px solid {decision_color.get(decision, '#999')}; padding-left:10px;'>{decision}</h2>
        <table><tr><th>#</th><th>Ticker</th><th>Strategy</th><th>State</th><th>Master</th><th>Grade</th><th>Conviction</th><th>Prob</th><th>Risk</th><th>Allowed</th><th>Reason</th></tr>{rows}</table>
        """
    html = f"""
    <html><head><title>Super Engine Bolsa v6 Dashboard</title><style>
    body{{font-family:Arial;margin:30px;background:#f7f7f7}} h1{{color:#111}} table{{border-collapse:collapse;width:100%;background:white;margin-bottom:26px}} th,td{{border:1px solid #ddd;padding:9px;text-align:left;font-size:13px}} th{{background:#111;color:white}} .regime{{padding:15px;background:white;margin-bottom:20px;border-left:5px solid #111}} .meta{{font-size:13px;color:#555;margin-bottom:20px}}
    </style></head><body><h1>Super Engine Bolsa v7.0</h1><div class='meta'>Supabase enabled: {supabase_enabled()} | Webhook secret required: {REQUIRE_WEBHOOK_SECRET} | Mode: {OPERATING_MODE}</div><div class='regime'><b>Market Regime:</b> {regime['regime']}<br><b>Lectura:</b> {regime['summary']}<br><b>Sesión:</b> {market_session_state()}<br><b>Ventana intradía activa:</b> {inside_execution_window()}<br><b>Minutos desde apertura:</b> {minutes_since_open()}</div>{sections}</body></html>
    """
    return html

