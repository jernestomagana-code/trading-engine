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
import sys
import hashlib
from pathlib import Path
import requests

try:
    from strategy_rules import (
        MIN_PRICE_FOR_THETA,
        OPTION_SPREAD_PCT_READY_MAX,
        OPTION_MIN_VOLUME_READY,
        OPTION_MIN_OPEN_INTEREST_READY,
        NAKED_PUT_READY_DTE_MIN,
        NAKED_PUT_READY_DTE_MAX,
        NAKED_PUT_REVIEW_DELTA_MIN,
        NAKED_PUT_REVIEW_DELTA_MAX,
        NAKED_PUT_READY_DELTA_MIN,
        NAKED_PUT_READY_DELTA_MAX,
        COVERED_CALL_READY_DELTA_MIN,
        COVERED_CALL_READY_DELTA_MAX,
        COVERED_CALL_REVIEW_DELTA_MIN,
        COVERED_CALL_REVIEW_DELTA_MAX,
        IRON_CONDOR_ALLOWED_TICKERS,
        IRON_CONDOR_DTE_MIN,
        IRON_CONDOR_DTE_MAX,
        IRON_CONDOR_IVR_MIN,
        IRON_CONDOR_IVR_MAX,
        IRON_CONDOR_VIX_RADAR_MIN,
        IRON_CONDOR_VIX_READY_MIN,
        IRON_CONDOR_VIX_MAX,
        IRON_CONDOR_VIX_IDEAL_MIN,
        IRON_CONDOR_VIX_IDEAL_MAX,
        IRON_CONDOR_RSI_MIN,
        IRON_CONDOR_RSI_MAX,
        IRON_CONDOR_ADX_MAX,
        IRON_CONDOR_SHORT_DELTA_MIN,
        IRON_CONDOR_SHORT_DELTA_MAX,
        IRON_CONDOR_CREDIT_WIDTH_MIN,
        liquidity_blockers as shared_liquidity_blockers,
        technical_event_blockers as shared_technical_event_blockers,
    )
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from strategy_rules import (
        MIN_PRICE_FOR_THETA,
        OPTION_SPREAD_PCT_READY_MAX,
        OPTION_MIN_VOLUME_READY,
        OPTION_MIN_OPEN_INTEREST_READY,
        NAKED_PUT_READY_DTE_MIN,
        NAKED_PUT_READY_DTE_MAX,
        NAKED_PUT_REVIEW_DELTA_MIN,
        NAKED_PUT_REVIEW_DELTA_MAX,
        NAKED_PUT_READY_DELTA_MIN,
        NAKED_PUT_READY_DELTA_MAX,
        COVERED_CALL_READY_DELTA_MIN,
        COVERED_CALL_READY_DELTA_MAX,
        COVERED_CALL_REVIEW_DELTA_MIN,
        COVERED_CALL_REVIEW_DELTA_MAX,
        IRON_CONDOR_ALLOWED_TICKERS,
        IRON_CONDOR_DTE_MIN,
        IRON_CONDOR_DTE_MAX,
        IRON_CONDOR_IVR_MIN,
        IRON_CONDOR_IVR_MAX,
        IRON_CONDOR_VIX_RADAR_MIN,
        IRON_CONDOR_VIX_READY_MIN,
        IRON_CONDOR_VIX_MAX,
        IRON_CONDOR_VIX_IDEAL_MIN,
        IRON_CONDOR_VIX_IDEAL_MAX,
        IRON_CONDOR_RSI_MIN,
        IRON_CONDOR_RSI_MAX,
        IRON_CONDOR_ADX_MAX,
        IRON_CONDOR_SHORT_DELTA_MIN,
        IRON_CONDOR_SHORT_DELTA_MAX,
        IRON_CONDOR_CREDIT_WIDTH_MIN,
        liquidity_blockers as shared_liquidity_blockers,
        technical_event_blockers as shared_technical_event_blockers,
    )

# ============================================================
# SUPER ENGINE BOLSA — APP MAIN V8
# Unified Decision Engine:
# TradingView + IBKR + Strategy Commander + GPT Report
# ============================================================

app = FastAPI(title="Super Engine Bolsa", version="8.0.0")

_CANONICAL_DECISION_ENGINES = [
    {
        "engine": "V27_TECHNICAL_RESOLVER",
        "status": "active",
        "primary_endpoints": [
            "/v27_system_status",
            "/v27_trade_decision/{ticker}",
        ],
        "scope": "Technical resolver baseline.",
    },
    {
        "engine": "V27_1_CANONICAL_RUNTIME_INVENTORY",
        "status": "active",
        "primary_endpoints": [
            "/v27_1_runtime_inventory",
            "/v27_1_system_status",
            "/v27_1_trade_decision/{ticker}",
        ],
        "scope": "Canonical runtime inventory and normalized trade decision.",
    },
    {
        "engine": "V28_REMOTE_SNAPSHOT_CANONICAL",
        "status": "active",
        "primary_endpoints": [
            "/v28_ingest_snapshot",
            "/v28_system_status",
            "/v28_trade_decision/{ticker}",
        ],
        "scope": "Canonical remote snapshot ingest and normalized decision path.",
    },
    {
        "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
        "status": "active_primary",
        "primary_endpoints": [
            "/v29_system_status",
            "/v29_trade_decision/{ticker}",
            "/v29_dashboard",
        ],
        "scope": "Primary source of truth for decision readiness and blocker priority.",
    },
    {
        "engine": "V31_CANONICAL_DECISION_CONTRACT",
        "status": "active_contract",
        "primary_endpoints": [
            "/v31_system_status",
            "/v31_trade_decision/{ticker}",
            "/gpt_v31_trade_decision/{ticker}",
        ],
        "scope": "Versioned canonical decision contract backed by the V29 decision engine.",
    },
    {
        "engine": "V32_OUTCOMES_TRACKING",
        "status": "active_learning",
        "primary_endpoints": [
            "/v32_decision_history",
            "/v32_record_followup",
            "/v32_record_outcome",
            "/v32_outcomes_summary",
        ],
        "scope": "Persistent decision journal and post-signal outcome tracking for forward evaluation.",
    },
    {
        "engine": "shared_strategy_rules",
        "status": "active_shared_rules",
        "primary_endpoints": [
            "/decision_engine_inventory",
        ],
        "scope": "Shared thresholds in strategy_rules.py used by bridge and cloud evaluators.",
    },
]

_LEGACY_COMPATIBILITY_ENGINES = [
    {
        "engine": "V22_UNIFIED_TRADING_DECISION_ENGINE",
        "status": "legacy_compatibility_only",
        "replacement_endpoints": [
            "/v29_trade_decision/{ticker}",
            "/v29_system_status",
            "/decision_engine_inventory",
        ],
    },
    {
        "engine": "V22_1_SNAPSHOT_NORMALIZER_UNIFIED_READER",
        "status": "legacy_compatibility_only",
        "replacement_endpoints": [
            "/v29_trade_decision/{ticker}",
            "/v29_system_status",
            "/decision_engine_inventory",
        ],
    },
    {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "status": "legacy_compatibility_only",
        "replacement_endpoints": [
            "/v28_ingest_snapshot",
            "/v29_trade_decision/{ticker}",
            "/decision_engine_inventory",
        ],
    },
    {
        "engine": "V23_TRADE_READINESS_EXECUTION_GUARD",
        "status": "legacy_compatibility_only",
        "replacement_endpoints": [
            "/v29_trade_decision/{ticker}",
            "/v29_system_status",
            "/decision_engine_inventory",
        ],
    },
    {
        "engine": "V24_UNIFIED_DATA_RESOLVER",
        "status": "legacy_compatibility_only",
        "replacement_endpoints": [
            "/v27_1_runtime_inventory",
            "/v29_trade_decision/{ticker}",
            "/decision_engine_inventory",
        ],
    },
    {
        "engine": "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD",
        "status": "legacy_compatibility_only",
        "replacement_endpoints": [
            "/v27_1_runtime_inventory",
            "/v29_trade_decision/{ticker}",
            "/decision_engine_inventory",
        ],
    },
    {
        "engine": "V25_REMOTE_SNAPSHOT_STORE",
        "status": "legacy_compatibility_only",
        "replacement_endpoints": [
            "/v28_ingest_snapshot",
            "/v29_trade_decision/{ticker}",
            "/decision_engine_inventory",
        ],
    },
]


def _legacy_replacement_endpoints(engine_name: str) -> List[str]:
    for engine in _LEGACY_COMPATIBILITY_ENGINES:
        if engine.get("engine") == engine_name:
            return list(engine.get("replacement_endpoints") or [])
    return ["/v29_trade_decision/{ticker}", "/decision_engine_inventory"]


def _legacy_compatibility_metadata(
    engine_name: str,
    endpoints: Optional[List[str]] = None,
    replacements: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "engine": engine_name,
        "lifecycle": "legacy_compatibility_only",
        "canonical_source_of_truth": False,
        "rule_change_policy": "Do not add new strategy or blocker rules here. Route new rules through V27-V29 and shared helpers.",
        "legacy_endpoints": endpoints or [],
        "replacement_endpoints": replacements or _legacy_replacement_endpoints(engine_name),
    }


def _annotate_legacy_response(
    payload: Dict[str, Any],
    engine_name: str,
    endpoints: Optional[List[str]] = None,
    replacements: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return payload

    annotated = dict(payload)
    annotated["engine_lifecycle"] = "legacy_compatibility_only"
    annotated["canonical_source_of_truth"] = False
    annotated["legacy_compatibility"] = _legacy_compatibility_metadata(
        engine_name,
        endpoints=endpoints,
        replacements=replacements,
    )
    return annotated


@app.get("/decision_engine_inventory")
def decision_engine_inventory():
    return {
        "generated_at": now_utc().isoformat(),
        "status": "OK",
        "policy": "Add new decision rules only to canonical engines and shared helpers. Keep V22-V25 stable for compatibility.",
        "canonical_source_of_truth": _CANONICAL_DECISION_ENGINES,
        "legacy_compatibility_only": _LEGACY_COMPATIBILITY_ENGINES,
    }

SIGNALS_FILE = "signals_history.json"
OUTCOMES_FILE = "trade_outcomes.json"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
REQUIRE_WEBHOOK_SECRET = os.getenv("REQUIRE_WEBHOOK_SECRET", "false").lower() == "true"
ADMIN_DEBUG_TOKEN = os.getenv("ADMIN_DEBUG_TOKEN", "")
OPERATING_MODE = os.getenv("OPERATING_MODE", "ANALYSIS_ONLY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
MONITOR_EMAIL_TO = os.getenv("MONITOR_EMAIL_TO") or os.getenv("PREMARKET_EMAIL_TO", "")
MONITOR_EMAIL_FROM = os.getenv("MONITOR_EMAIL_FROM") or os.getenv("PREMARKET_EMAIL_FROM", "Stock Ultimus <onboarding@resend.dev>")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

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
        "option_iv": safe_float((options or {}).get("implied_volatility") or (options or {}).get("iv"), None) if options else None,
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
    elif NAKED_PUT_READY_DTE_MIN <= dte <= NAKED_PUT_READY_DTE_MAX:
        score += 12
    elif 25 <= dte <= 65:
        score += 3
        blockers.append("DTE fuera del rango de readiness 30–60 para Naked Put.")
    else:
        score -= 10
        blockers.append("DTE fuera del rango ideal para Naked Put.")

    if delta is None:
        missing.append("delta")
        score -= 15
    else:
        abs_delta = abs(delta)
        if NAKED_PUT_READY_DELTA_MIN <= abs_delta <= NAKED_PUT_READY_DELTA_MAX:
            score += 22
        elif NAKED_PUT_REVIEW_DELTA_MIN <= abs_delta <= NAKED_PUT_REVIEW_DELTA_MAX:
            score += 6
            blockers.append("Delta fuera del rango de readiness 0.14–0.22 para Naked Put.")
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
    elif alignment in ["neutral", "mixed", "range", "sideways"]:
        score += 2
        blockers.append("Contexto técnico no es alcista confirmado para Naked Put.")
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
    event_risk = safe_bool(latest.get("event_risk"), False)
    earnings = safe_bool(latest.get("earnings_soon"), False)

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
        if COVERED_CALL_READY_DELTA_MIN <= abs_delta <= COVERED_CALL_READY_DELTA_MAX:
            score += 22
        elif COVERED_CALL_REVIEW_DELTA_MIN <= abs_delta <= COVERED_CALL_REVIEW_DELTA_MAX:
            score += 6
            blockers.append("Delta de call fuera del rango de readiness 0.15–0.25.")
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

    if event_risk:
        blockers.append("Event risk activo.")
        score -= 15

    if earnings:
        blockers.append("Earnings próximos.")
        score -= 15

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
    elif IRON_CONDOR_VIX_READY_MIN <= vix <= IRON_CONDOR_VIX_MAX:
        score += 10
        if IRON_CONDOR_VIX_IDEAL_MIN <= vix <= IRON_CONDOR_VIX_IDEAL_MAX:
            score += 5
    elif IRON_CONDOR_VIX_RADAR_MIN <= vix < IRON_CONDOR_VIX_READY_MIN:
        score += 2
        blockers.append("VIX por debajo del rango de readiness; dejar en radar.")
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
def debug_supabase(x_admin_debug_token: Optional[str] = Header(default=None)):
    if not ADMIN_DEBUG_TOKEN or x_admin_debug_token != ADMIN_DEBUG_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")

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
        "spread_pct": option.get("spread_pct"),
        "delta": option.get("delta"),
        "iv": option.get("implied_volatility") or option.get("iv"),
        "implied_volatility": option.get("implied_volatility") or option.get("iv"),
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

# ============================================================
# SUPER ENGINE BOLSA — V14 PATCH
# Decision Quality & Liquidity Rules
# ============================================================

ACCEPTABLE_OPTION_QUALITY_FOR_OPERAR = [
    "FULL_WITH_GREEKS",
    "PRICE_WITH_GREEKS_NO_BIDASK",
]

POOR_OPTION_QUALITY = [
    "PRICE_ONLY_NO_GREEKS",
    "NO_DATA",
    "UNKNOWN",
    "",
]


def option_has_greeks(option):
    if not option:
        return False

    return (
        option.get("delta") is not None
        and (option.get("implied_volatility") is not None or option.get("iv") is not None)
    )


def option_has_price(option):
    if not option:
        return False

    mid = safe_float(option.get("mid"), None)
    last = safe_float(option.get("last"), None)
    close = safe_float(option.get("close"), None)

    return any(x is not None and x > 0 for x in [mid, last, close])


def option_has_bidask(option):
    if not option:
        return False

    bid = safe_float(option.get("bid"), None)
    ask = safe_float(option.get("ask"), None)

    return bool(bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid)


def option_spread_ok(option, max_spread_pct=OPTION_SPREAD_PCT_READY_MAX):
    if not option:
        return False

    spread_pct = safe_float(option.get("spread_pct"), None)

    if spread_pct is None:
        return False

    return spread_pct <= max_spread_pct


def option_quality_value(option):
    if not option:
        return "NO_DATA"
    return str(option.get("data_quality") or "UNKNOWN").upper()


def option_quality_allows_operar(option):
    quality = option_quality_value(option)
    return quality in ACCEPTABLE_OPTION_QUALITY_FOR_OPERAR and option_has_greeks(option) and option_has_price(option)


def option_quality_allows_radar(option):
    quality = option_quality_value(option)

    if quality in ACCEPTABLE_OPTION_QUALITY_FOR_OPERAR:
        return option_has_price(option)

    if quality == "PRICE_ONLY_NO_GREEKS":
        return option_has_price(option)

    return False


def delta_zone_for_short_leg(option):
    if not option or option.get("delta") is None:
        return "MISSING"

    d = abs(safe_float(option.get("delta"), 999))

    if 0.15 <= d <= 0.20:
        return "IDEAL"

    if 0.10 <= d < 0.15:
        return "CONSERVATIVE"

    if 0.20 < d <= 0.30:
        return "AGGRESSIVE"

    return "OUT_OF_RANGE"


def iron_condor_leg_quality_report(option):
    if not option:
        return {
            "available": False,
            "quality": "NO_DATA",
            "has_greeks": False,
            "has_price": False,
            "has_bidask": False,
            "spread_ok": False,
            "delta_zone": "MISSING",
            "can_operar": False,
            "can_radar": False,
        }

    quality = option_quality_value(option)

    return {
        "available": True,
        "quality": quality,
        "has_greeks": option_has_greeks(option),
        "has_price": option_has_price(option),
        "has_bidask": option_has_bidask(option),
        "spread_ok": option_spread_ok(option),
        "delta_zone": delta_zone_for_short_leg(option),
        "can_operar": option_quality_allows_operar(option),
        "can_radar": option_quality_allows_radar(option),
    }


def iron_condor_quality_gate(structure):
    blockers = []
    missing = []
    warnings = []

    put_leg = structure.get("put_leg")
    call_leg = structure.get("call_leg")

    put_quality = iron_condor_leg_quality_report(put_leg)
    call_quality = iron_condor_leg_quality_report(call_leg)

    if not put_leg:
        missing.append("put_leg")
    if not call_leg:
        missing.append("call_leg")

    if put_leg and not put_quality["has_greeks"]:
        missing.append("put_greeks")
    if call_leg and not call_quality["has_greeks"]:
        missing.append("call_greeks")

    if put_leg and not put_quality["has_price"]:
        missing.append("put_price")
    if call_leg and not call_quality["has_price"]:
        missing.append("call_price")
    if put_leg and put_quality["has_bidask"] and not put_quality["spread_ok"]:
        blockers.append("Put spread supera el máximo permitido para OPERAR.")
    if call_leg and call_quality["has_bidask"] and not call_quality["spread_ok"]:
        blockers.append("Call spread supera el máximo permitido para OPERAR.")

    if put_leg and put_quality["delta_zone"] == "OUT_OF_RANGE":
        blockers.append("Put delta fuera de rango aceptable 0.10–0.30.")
    if call_leg and call_quality["delta_zone"] == "OUT_OF_RANGE":
        blockers.append("Call delta fuera de rango aceptable 0.10–0.30.")

    if put_leg and put_quality["delta_zone"] in ["CONSERVATIVE", "AGGRESSIVE"]:
        warnings.append("Put delta no está en zona ideal 0.15–0.20.")
    if call_leg and call_quality["delta_zone"] in ["CONSERVATIVE", "AGGRESSIVE"]:
        warnings.append("Call delta no está en zona ideal 0.15–0.20.")

    if structure.get("dte_match") is False:
        blockers.append("Las dos alas no tienen el mismo DTE.")

    credit = safe_float(structure.get("estimated_short_credit"), None)
    if credit is None or credit <= 0:
        missing.append("estimated_credit")

    # Bid/ask no siempre llega desde IBKR para todos los contratos; si falta, máximo RADAR.
    if put_leg and not put_quality["has_bidask"]:
        warnings.append("Put sin bid/ask completo; no permite OPERAR directo.")
    if call_leg and not call_quality["has_bidask"]:
        warnings.append("Call sin bid/ask completo; no permite OPERAR directo.")

    can_operar = (
        put_quality["can_operar"]
        and call_quality["can_operar"]
        and put_quality["has_bidask"]
        and call_quality["has_bidask"]
        and put_quality["spread_ok"]
        and call_quality["spread_ok"]
        and put_quality["delta_zone"] == "IDEAL"
        and call_quality["delta_zone"] == "IDEAL"
        and structure.get("dte_match") is True
        and credit is not None
        and credit >= IRON_CONDOR_CREDIT_WIDTH_MIN
        and not blockers
        and not missing
    )

    can_radar = (
        put_quality["can_radar"]
        and call_quality["can_radar"]
        and put_quality["delta_zone"] in ["IDEAL", "CONSERVATIVE", "AGGRESSIVE"]
        and call_quality["delta_zone"] in ["IDEAL", "CONSERVATIVE", "AGGRESSIVE"]
        and structure.get("dte_match") is True
        and credit is not None
        and credit > 0
        and not blockers
    )

    return {
        "put_quality": put_quality,
        "call_quality": call_quality,
        "blockers": sorted(list(set(blockers))),
        "missing_data": sorted(list(set(missing))),
        "warnings": sorted(list(set(warnings))),
        "can_operar": can_operar,
        "can_radar": can_radar,
    }


_evaluate_iron_condor_pro_v13_1 = evaluate_iron_condor_pro


def evaluate_iron_condor_pro(ticker, technical, ibkr, market):
    result = _evaluate_iron_condor_pro_v13_1(ticker, technical, ibkr, market)

    result = dict(result)
    details = dict(result.get("details", {}))
    blockers = list(result.get("blockers", []))
    missing = list(result.get("missing_data", []))

    structure = details.get("iron_condor_structure") or build_iron_condor_structure(ibkr)
    quality_gate = iron_condor_quality_gate(structure)

    details["v14_quality_gate"] = quality_gate

    blockers.extend(quality_gate.get("blockers", []))
    missing.extend(quality_gate.get("missing_data", []))

    result["details"] = details
    result["blockers"] = sorted(list(set(blockers)))
    result["missing_data"] = sorted(list(set(missing)))

    if quality_gate["can_operar"]:
        # Still respect higher-level event/technical blockers if any exist.
        if result["blockers"]:
            result["decision"] = "RADAR"
            result["reason"] = "Iron Condor tiene calidad suficiente, pero existen bloqueos de riesgo."
        else:
            result["decision"] = "OPERAR"
            result["reason"] = "Iron Condor PRO cumple calidad de datos, griegas, delta ideal, DTE y crédito estimado."

    elif quality_gate["can_radar"]:
        result["decision"] = "RADAR"
        result["reason"] = "Iron Condor PRO tiene estructura válida, pero no cumple todos los requisitos para OPERAR."

    elif result["missing_data"]:
        result["decision"] = "MISSING_DATA"
        result["reason"] = "Iron Condor potencial, pero faltan datos de calidad, griegas, precio o confirmaciones."

    elif result["blockers"]:
        result["decision"] = "BLOCKED"
        result["reason"] = "Iron Condor bloqueado por reglas de delta, DTE, liquidez o riesgo."

    else:
        result["decision"] = "ESPERAR"
        result["reason"] = "Iron Condor sin edge suficiente bajo reglas V14."

    return result


@app.get("/debug/quality_gate")
def debug_quality_gate(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()

    technical = get_technical_context(ticker)
    ibkr = get_ibkr_context(ticker)
    market = get_market_context()

    structure = build_iron_condor_structure(ibkr)
    quality_gate = iron_condor_quality_gate(structure)
    decision = evaluate_iron_condor_pro(ticker, technical, ibkr, market)

    return {
        "engine": "v14_quality_gate",
        "ticker": ticker,
        "options_candidates_count": ibkr.get("options_candidates_count"),
        "structure": structure,
        "quality_gate": quality_gate,
        "decision": decision,
        "note": "V14 limita OPERAR si faltan griegas, bid/ask, precio, DTE match, delta ideal o crédito válido."
    }


@app.get("/debug/routes_v14")
def debug_routes_v14():
    return {
        "engine": "v14",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/debug/quality_gate",
            "/debug/iron_condor",
            "/gpt_iron_condors",
            "/gpt_action_plan",
            "/debug/data_sources",
            "/technical_snapshot",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V14 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V15 PATCH
# TradingView Technical Snapshot Setup & Alert Payload Builder
# ============================================================

TRADINGVIEW_TECHNICAL_WEBHOOK_URL = "https://trading-engine-p097.onrender.com/technical_snapshot"


@app.get("/gpt_tradingview_setup")
def gpt_tradingview_setup():
    return {
        "engine": "v15_tradingview_setup",
        "purpose": "Configurar TradingView para mandar technical_snapshot automático al Super Engine Bolsa.",
        "webhook_url": TRADINGVIEW_TECHNICAL_WEBHOOK_URL,
        "required_alert_settings": {
            "condition": "Usar alerta del indicador Super Engine / Technical Snapshot",
            "webhook_url": TRADINGVIEW_TECHNICAL_WEBHOOK_URL,
            "message_format": "JSON",
            "timeframe_recommended": ["1h", "15m", "5m", "1d"],
        },
        "required_fields": [
            "ticker",
            "timeframe",
            "price",
            "trend",
            "score",
            "rsi",
            "adx",
            "range_20d",
            "range_breakout",
            "support_near",
            "resistance_near",
            "vwap_position",
            "volume_relative",
            "iv_rank",
            "earnings_soon",
            "event_risk",
        ],
        "next_step": "Crear/actualizar Pine Script para exponer plots RSI, ADX, range_20d, range_breakout, soporte, resistencia, VWAP y volumen relativo."
    }


@app.get("/gpt_tradingview_alert_message")
def gpt_tradingview_alert_message(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()

    return {
        "engine": "v15_tradingview_alert_message",
        "webhook_url": TRADINGVIEW_TECHNICAL_WEBHOOK_URL,
        "ticker": ticker,
        "alert_message_to_copy": """
{
  "ticker": "{{ticker}}",
  "timeframe": "{{interval}}",
  "price": {{close}},
  "trend": "{{plot(\"TrendCode\")}}",
  "score": {{plot("TechScore")}},
  "rsi": {{plot("RSI")}},
  "adx": {{plot("ADX")}},
  "range_20d": {{plot("Range20D")}},
  "range_breakout": {{plot("RangeBreakout")}},
  "support_near": {{plot("SupportNear")}},
  "resistance_near": {{plot("ResistanceNear")}},
  "vwap_position": "{{plot(\"VWAPPosition\")}}",
  "volume_relative": {{plot("VolumeRelative")}},
  "iv_rank": null,
  "earnings_soon": false,
  "event_risk": false
}
""".strip(),
        "important_note": "TradingView solo puede usar {{plot(\"Nombre\")}} si el Pine Script tiene plots con esos nombres exactos.",
        "fallback_alert_message_if_string_plots_fail": """
{
  "ticker": "{{ticker}}",
  "timeframe": "{{interval}}",
  "price": {{close}},
  "trend": "neutral",
  "score": {{plot("TechScore")}},
  "rsi": {{plot("RSI")}},
  "adx": {{plot("ADX")}},
  "range_20d": {{plot("Range20D")}},
  "range_breakout": {{plot("RangeBreakout")}},
  "support_near": {{plot("SupportNear")}},
  "resistance_near": {{plot("ResistanceNear")}},
  "vwap_position": "near",
  "volume_relative": {{plot("VolumeRelative")}},
  "iv_rank": null,
  "earnings_soon": false,
  "event_risk": false
}
""".strip()
    }


@app.get("/gpt_pine_snapshot_template")
def gpt_pine_snapshot_template():
    pine = r'''
//@version=5
indicator("Super Engine Bolsa - Technical Snapshot V15", overlay=true)

// ==========================
// Core indicators
// ==========================
rsiLen = input.int(14, "RSI Length")
adxLen = input.int(14, "ADX Length")
rangeLen = input.int(20, "Range Length")
volLen = input.int(20, "Relative Volume Length")

rsiValue = ta.rsi(close, rsiLen)
adxValue = ta.adx(adxLen)

rangeHigh = ta.highest(high, rangeLen)
rangeLow = ta.lowest(low, rangeLen)
rangeMid = (rangeHigh + rangeLow) / 2.0

insideRange20D = close <= rangeHigh and close >= rangeLow
rangeBreakout = close > rangeHigh or close < rangeLow

rangeSize = rangeHigh - rangeLow
supportNear = rangeSize > 0 ? math.abs(close - rangeLow) / close <= 0.01 : false
resistanceNear = rangeSize > 0 ? math.abs(close - rangeHigh) / close <= 0.01 : false

vwapValue = ta.vwap(hlc3)
vwapPositionCode = close > vwapValue ? 1 : close < vwapValue ? -1 : 0

volAvg = ta.sma(volume, volLen)
volumeRelative = volAvg > 0 ? volume / volAvg : na

// ==========================
// Technical score
// ==========================
neutralRSI = rsiValue >= 45 and rsiValue <= 55
lowADX = adxValue <= 22
rangeGood = insideRange20D and not rangeBreakout

score = 0.0
score += neutralRSI ? 30 : 0
score += lowADX ? 30 : 0
score += rangeGood ? 25 : 0
score += volumeRelative <= 1.3 ? 15 : 0

// trend code:
// 1 = bullish
// 0 = neutral
// -1 = bearish
trendCode = close > rangeMid and adxValue > 22 ? 1 : close < rangeMid and adxValue > 22 ? -1 : 0

// ==========================
// Plots for TradingView alert placeholders
// IMPORTANT: names must match alert JSON
// ==========================
plot(rsiValue, title="RSI", display=display.none)
plot(adxValue, title="ADX", display=display.none)
plot(insideRange20D ? 1 : 0, title="Range20D", display=display.none)
plot(rangeBreakout ? 1 : 0, title="RangeBreakout", display=display.none)
plot(supportNear ? 1 : 0, title="SupportNear", display=display.none)
plot(resistanceNear ? 1 : 0, title="ResistanceNear", display=display.none)
plot(vwapPositionCode, title="VWAPPosition", display=display.none)
plot(volumeRelative, title="VolumeRelative", display=display.none)
plot(score, title="TechScore", display=display.none)
plot(trendCode, title="TrendCode", display=display.none)

// ==========================
// Visual aids
// ==========================
plot(rangeHigh, "20D Range High")
plot(rangeLow, "20D Range Low")
plot(vwapValue, "VWAP")

bgcolor(insideRange20D and lowADX and neutralRSI ? color.new(color.green, 88) : na)

alertcondition(true, title="Technical Snapshot V15", message="Send webhook using JSON message from /gpt_tradingview_alert_message")
'''
    return {
        "engine": "v15_pine_snapshot_template",
        "pine_script": pine.strip(),
        "important_note": "Este Pine Script expone plots para que TradingView pueda construir el JSON del technical_snapshot."
    }


@app.get("/debug/routes_v15")
def debug_routes_v15():
    return {
        "engine": "v15",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/gpt_tradingview_setup",
            "/gpt_tradingview_alert_message",
            "/gpt_pine_snapshot_template",
            "/technical_snapshot",
            "/debug/technical_context",
            "/debug/data_sources",
            "/debug/quality_gate",
            "/gpt_action_plan",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V15 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V15.1 PATCH
# TradingView Technical Snapshot Normalizer
# ============================================================

BOOLEAN_NUMERIC_FIELDS_V15_1 = [
    "range_20d",
    "range_breakout",
    "support_near",
    "resistance_near",
    "earnings_soon",
    "event_risk",
]

NUMERIC_FIELDS_V15_1 = [
    "price",
    "score",
    "rsi",
    "adx",
    "volume_relative",
    "iv_rank",
    "iv_percentile",
    "trend_code",
    "vwap_position_code",
]


def normalize_numeric_bool(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    try:
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ["true", "yes", "y", "si", "sí"]:
                return True
            if v in ["false", "no", "n"]:
                return False
            if v in ["1", "1.0"]:
                return True
            if v in ["0", "0.0"]:
                return False

        n = float(value)
        if math.isnan(n) or math.isinf(n):
            return None
        return n >= 0.5

    except Exception:
        return None


def normalize_number_or_none(value):
    if value is None:
        return None

    try:
        if isinstance(value, str):
            value = value.strip()
            if value.lower() in ["na", "nan", "none", "null", ""]:
                return None

        n = float(value)
        if math.isnan(n) or math.isinf(n):
            return None

        return round(n, 6)

    except Exception:
        return None


def normalize_trend_code(value):
    n = normalize_number_or_none(value)

    if n is None:
        return None

    if n > 0:
        return "bullish"

    if n < 0:
        return "bearish"

    return "neutral"


def normalize_vwap_position_code(value):
    n = normalize_number_or_none(value)

    if n is None:
        return None

    if n > 0:
        return "above"

    if n < 0:
        return "below"

    return "near"


def normalize_technical_snapshot_payload(payload):
    payload = dict(payload or {})

    for key in NUMERIC_FIELDS_V15_1:
        if key in payload:
            payload[key] = normalize_number_or_none(payload.get(key))

    for key in BOOLEAN_NUMERIC_FIELDS_V15_1:
        if key in payload:
            payload[key] = normalize_numeric_bool(payload.get(key))

    if payload.get("trend") in [None, "", "null"]:
        trend = normalize_trend_code(payload.get("trend_code"))
        if trend:
            payload["trend"] = trend

    if payload.get("vwap_position") in [None, "", "null"]:
        vwap_position = normalize_vwap_position_code(payload.get("vwap_position_code"))
        if vwap_position:
            payload["vwap_position"] = vwap_position

    payload["normalizer_version"] = "v15.1"
    payload["normalized_at"] = now_utc().isoformat()

    return payload


# Preserve existing V13/V15 technical_snapshot endpoint logic
@app.post("/technical_snapshot_v15_1")
async def technical_snapshot_v15_1(request: Request, x_webhook_secret: Optional[str] = Header(default=None)):
    verify_webhook_secret(x_webhook_secret)

    parsed, raw_text = await parse_request_payload(request)

    if not isinstance(parsed, dict):
        return {
            "status": "error",
            "engine": "v15.1_technical_snapshot",
            "message": "Invalid JSON payload",
            "raw_preview": raw_text[:500],
        }

    parsed = normalize_technical_snapshot_payload(parsed)

    ticker = find_ticker(parsed, raw_text)
    timeframe = normalize_timeframe(parsed.get("timeframe", "1h"))

    parsed.update({
        "ticker": ticker,
        "timeframe": timeframe,
        "received_at": now_utc().isoformat(),
        "saved_at": now_utc().isoformat(),
        "source": "TECHNICAL_SNAPSHOT",
        "engine_layer": "TRADINGVIEW_TECHNICAL_SNAPSHOT_V15_1",
        "raw_payload_preview": raw_text[:500],
    })

    trade_store.setdefault(ticker, {})
    trade_store[ticker][timeframe] = parsed
    trade_store[ticker]["technical_snapshot"] = parsed

    classification = classify_asset(trade_store[ticker])

    parsed.update({
        "state": classification.get("state"),
        "grade": classification.get("grade"),
        "conviction": classification.get("conviction"),
        "priority_score": classification.get("priority_score"),
        "final_decision": classification.get("final_decision"),
        "v6_strategy": classification.get("v6_strategy"),
        "master_score": classification.get("master_score"),
    })

    trade_store[ticker][timeframe] = parsed
    trade_store[ticker]["technical_snapshot"] = parsed

    storage_result = save_signal(parsed)
    unified = build_unified_context(ticker)

    return {
        "status": "ok",
        "engine": "v15.1_technical_snapshot",
        "message": f"Normalized technical snapshot received for {ticker} {timeframe}",
        "ticker": ticker,
        "timeframe": timeframe,
        "storage": storage_result,
        "normalized_payload": parsed,
        "unified_context": unified,
    }



@app.get("/debug/normalizer")
def debug_normalizer(
    ticker: str = "QQQ",
    trend_code: Optional[float] = 0,
    vwap_position_code: Optional[float] = 0,
    range_20d: Optional[float] = 1,
    range_breakout: Optional[float] = 0,
    support_near: Optional[float] = 0,
    resistance_near: Optional[float] = 0,
):
    sample = {
        "ticker": ticker.upper().strip(),
        "timeframe": "1h",
        "price": 714.51,
        "score": 70,
        "rsi": 51,
        "adx": 18,
        "trend_code": trend_code,
        "vwap_position_code": vwap_position_code,
        "range_20d": range_20d,
        "range_breakout": range_breakout,
        "support_near": support_near,
        "resistance_near": resistance_near,
        "volume_relative": 1.0,
        "iv_rank": 45,
        "earnings_soon": 0,
        "event_risk": 0,
    }

    return {
        "engine": "v15.1_normalizer_debug",
        "raw_sample": sample,
        "normalized_sample": normalize_technical_snapshot_payload(sample),
        "mapping": {
            "trend_code": {
                "1": "bullish",
                "0": "neutral",
                "-1": "bearish",
            },
            "vwap_position_code": {
                "1": "above",
                "0": "near",
                "-1": "below",
            },
            "numeric_booleans": {
                "1": True,
                "0": False,
            },
        },
    }


@app.get("/debug/routes_v15_1")
def debug_routes_v15_1():
    return {
        "engine": "v15.1",
        "routes": sorted([route.path for route in app.routes]),
        "key_routes": [
            "/technical_snapshot",
            "/technical_snapshot_v15_1",
            "/debug/normalizer",
            "/debug/technical_context",
            "/debug/data_sources",
            "/debug/quality_gate",
            "/gpt_action_plan",
            "/gpt_tradingview_alert_message",
            "/webhook/ibkr",
            "/webhook/tradingview",
        ],
    }

# END SUPER ENGINE BOLSA — V15.1 PATCH

# ============================================================
# SUPER ENGINE BOLSA — V15.2 PATCH
# Force /technical_snapshot to use normalized V15.1 handler
# Removes older duplicate routes registered earlier in the file.
# ============================================================

_STRATEGY_SIGNAL_CONTEXT_FILE = Path("runtime/strategy_signal_by_ticker_context.json")
_STRATEGY_SIGNAL_CONTEXTS = {
    "NAKED_PUT",
    "CASH_SECURED_PUT",
    "COVERED_CALL",
    "IRON_CONDOR",
    "FUTURES",
    "CANSLIM_FILTER",
    "GENERAL_TECHNICAL",
}


def _strategy_signal_context(payload):
    context = str((payload or {}).get("strategy_context") or "GENERAL_TECHNICAL").upper().strip()
    return context if context in _STRATEGY_SIGNAL_CONTEXTS else "GENERAL_TECHNICAL"


def _strategy_signal_read_store():
    try:
        if not _STRATEGY_SIGNAL_CONTEXT_FILE.exists():
            return {}
        data = json.loads(_STRATEGY_SIGNAL_CONTEXT_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _strategy_signal_merge_contexts(ticker, contexts):
    ticker = str(ticker or "").upper().strip()
    contexts = {
        str(k).upper().strip(): dict(v)
        for k, v in (contexts or {}).items()
        if isinstance(v, dict)
    }
    technical_candidates = [value for key, value in contexts.items() if key != "CANSLIM_FILTER"]
    technical_candidates.sort(
        key=lambda value: str(value.get("received_at") or value.get("saved_at") or ""),
        reverse=True,
    )

    if technical_candidates:
        merged = dict(technical_candidates[0])
    else:
        merged = {
            "ticker": ticker,
            "trend": "UNKNOWN",
            "score": None,
            "source": "STRATEGY_SIGNAL_CONTEXT_STORE",
        }

    canslim_snapshot = contexts.get("CANSLIM_FILTER")
    if isinstance(canslim_snapshot, dict):
        canslim = canslim_snapshot.get("canslim")
        if isinstance(canslim, dict):
            merged["canslim"] = dict(canslim)
        else:
            merged["canslim"] = {
                "passes": canslim_snapshot.get("canslim_passes"),
                "score": canslim_snapshot.get("canslim_score") or canslim_snapshot.get("score"),
                "rating": canslim_snapshot.get("canslim_rating"),
            }
        merged["canslim_received_at"] = canslim_snapshot.get("received_at")

    merged["ticker"] = ticker
    merged["strategy_context"] = merged.get("strategy_context") or "GENERAL_TECHNICAL"
    merged["available_strategy_contexts"] = sorted(contexts.keys())
    merged["by_strategy_context"] = contexts
    merged["context_store_version"] = "strategy_context_store_v1"
    return merged


def _strategy_signal_store_snapshot(payload):
    ticker = str((payload or {}).get("ticker") or "").upper().strip()
    context = _strategy_signal_context(payload)
    store = _strategy_signal_read_store()
    ticker_contexts = store.get(ticker) if isinstance(store.get(ticker), dict) else {}

    clean_snapshot = dict(payload or {})
    clean_snapshot.pop("raw_payload_preview", None)
    clean_snapshot["ticker"] = ticker
    clean_snapshot["strategy_context"] = context
    ticker_contexts[context] = clean_snapshot
    store[ticker] = ticker_contexts

    _STRATEGY_SIGNAL_CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STRATEGY_SIGNAL_CONTEXT_FILE.write_text(json.dumps(store, indent=2, ensure_ascii=False, default=str))

    merged = _strategy_signal_merge_contexts(ticker, ticker_contexts)
    canonical_sync = globals().get("_v22_2_sync_technical_to_canonical")
    if callable(canonical_sync):
        canonical_sync(ticker, merged)

    return {
        "ticker": ticker,
        "strategy_context": context,
        "available_strategy_contexts": merged.get("available_strategy_contexts", []),
        "merged_snapshot": merged,
        "path": str(_STRATEGY_SIGNAL_CONTEXT_FILE),
    }


async def technical_snapshot_forced_v15_2(request: Request, x_webhook_secret: Optional[str] = Header(default=None)):
    verify_webhook_secret(x_webhook_secret)

    parsed, raw_text = await parse_request_payload(request)

    if not isinstance(parsed, dict):
        return {
            "status": "error",
            "engine": "v15.2_technical_snapshot_forced",
            "message": "Invalid JSON payload",
            "raw_preview": raw_text[:500],
        }

    parsed = normalize_technical_snapshot_payload(parsed)

    ticker = find_ticker(parsed, raw_text)
    timeframe = normalize_timeframe(parsed.get("timeframe", "1h"))

    original_source = parsed.get("source")
    parsed.update({
        "ticker": ticker,
        "timeframe": timeframe,
        "strategy_context": _strategy_signal_context(parsed),
        "received_at": now_utc().isoformat(),
        "saved_at": now_utc().isoformat(),
        "source": original_source or "TECHNICAL_SNAPSHOT",
        "engine_layer": "TRADINGVIEW_TECHNICAL_SNAPSHOT_V15_2_FORCED",
        "raw_payload_preview": raw_text[:500],
    })

    trade_store.setdefault(ticker, {})
    context_storage = _strategy_signal_store_snapshot(parsed)
    merged_snapshot = context_storage["merged_snapshot"]
    trade_store[ticker][timeframe] = parsed
    trade_store[ticker]["technical_snapshot"] = merged_snapshot
    trade_store[ticker]["technical_snapshots_by_context"] = merged_snapshot.get("by_strategy_context", {})

    classification = classify_asset(trade_store[ticker])

    parsed.update({
        "state": classification.get("state"),
        "grade": classification.get("grade"),
        "conviction": classification.get("conviction"),
        "priority_score": classification.get("priority_score"),
        "final_decision": classification.get("final_decision"),
        "v6_strategy": classification.get("v6_strategy"),
        "master_score": classification.get("master_score"),
    })

    trade_store[ticker][timeframe] = parsed
    trade_store[ticker]["technical_snapshot"] = parsed

    storage_result = save_signal(parsed)
    unified = build_unified_context(ticker)

    return {
        "status": "ok",
        "engine": "v15.2_technical_snapshot_forced",
        "message": f"Normalized technical snapshot received for {ticker} {timeframe}",
        "ticker": ticker,
        "timeframe": timeframe,
        "strategy_context": parsed.get("strategy_context"),
        "available_strategy_contexts": context_storage.get("available_strategy_contexts"),
        "context_storage": {
            "path": context_storage.get("path"),
            "version": "strategy_context_store_v1",
        },
        "storage": storage_result,
        "normalized_payload": parsed,
        "merged_snapshot": merged_snapshot,
        "unified_context": unified,
    }


# Remove all previous POST /technical_snapshot routes.
app.router.routes = [
    route for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/technical_snapshot"
        and "POST" in getattr(route, "methods", set())
    )
]

# Re-register clean normalized route.
app.add_api_route(
    "/technical_snapshot",
    technical_snapshot_forced_v15_2,
    methods=["POST"],
    name="technical_snapshot_forced_v15_2"
)


@app.get("/debug/routes_v15_2")
def debug_routes_v15_2():
    technical_snapshot_routes = [
        {
            "path": getattr(route, "path", None),
            "name": getattr(route, "name", None),
            "methods": sorted(list(getattr(route, "methods", [])))
        }
        for route in app.routes
        if getattr(route, "path", None) == "/technical_snapshot"
    ]

    return {
        "engine": "v15.2",
        "technical_snapshot_routes": technical_snapshot_routes,
        "routes": sorted([route.path for route in app.routes]),
        "expected": "Only one POST /technical_snapshot route should exist and it should be technical_snapshot_forced_v15_2."
    }

# END SUPER ENGINE BOLSA — V15.2 PATCH


# ============================================================
# SUPER ENGINE BOLSA — V18 OPERATIONAL DECISION API ENDPOINTS
# ============================================================

from pathlib import Path as _v18_api_Path
from datetime import datetime as _v18_api_datetime, timezone as _v18_api_timezone
import json as _v18_api_json

_V18_API_SNAPSHOT_PATHS = [
    _v18_api_Path("runtime/decision_desk_snapshot.json"),
    _v18_api_Path("../runtime/decision_desk_snapshot.json"),
    _v18_api_Path("/tmp/decision_desk_snapshot.json"),
]

def _v18_api_load_snapshot():
    for path in _V18_API_SNAPSHOT_PATHS:
        try:
            if path.exists():
                return _v18_api_json.loads(path.read_text())
        except Exception:
            pass

    return {
        "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
        "generated_at": _v18_api_datetime.now(_v18_api_timezone.utc).isoformat(),
        "snapshot_available": False,
        "summary": {
            "entry": 0,
            "manage_position": 0,
            "radar": 0,
            "wait_greeks": 0,
            "wait_data": 0,
            "blocked": 0,
            "total": 0,
        },
        "next_best_action": None,
        "recommendation": "No hay snapshot operativo disponible todavía. Corre ibkr_bridge.py para generar el último decision desk.",
        "by_ticker": [],
        "by_strategy": [],
        "top": [],
        "health": {
            "snapshot_available": False,
            "rows_captured": 0,
            "can_operate_count": 0,
        },
    }

@app.get("/decision_desk")
def decision_desk():
    return _v18_api_load_snapshot()

@app.get("/decision_desk/health")
def decision_desk_health():
    data = _v18_api_load_snapshot()
    return {
        "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
        "status": "OK" if data.get("health", {}).get("snapshot_available") else "NO_SNAPSHOT",
        "generated_at": data.get("generated_at"),
        "summary": data.get("summary"),
        "health": data.get("health"),
    }

@app.get("/decision_desk/{ticker}")
def decision_desk_ticker(ticker: str):
    data = _v18_api_load_snapshot()
    t = str(ticker or "").upper().strip()

    top = [
        row for row in data.get("top", [])
        if str(row.get("ticker", "")).upper() == t
    ]

    ticker_summary = None
    for item in data.get("by_ticker", []):
        if str(item.get("ticker", "")).upper() == t:
            ticker_summary = item
            break

    best = top[0] if top else None

    return {
        "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
        "ticker": t,
        "generated_at": data.get("generated_at"),
        "summary": ticker_summary or {
            "ticker": t,
            "total": 0,
            "entry": 0,
            "radar": 0,
            "wait_greeks": 0,
            "wait_data": 0,
            "blocked": 0,
            "best": None,
        },
        "next_best_action": best,
        "recommendation": best.get("recommendation") if best else f"No hay oportunidades capturadas para {t} en el último ciclo.",
        "top": top[:10],
    }


# ============================================================
# SUPER ENGINE BOLSA — V18.1 REMOTE SNAPSHOT INGEST ENDPOINT
# ============================================================

from fastapi import Request as _v18_1_Request, Header as _v18_1_Header
import os as _v18_1_api_os

_V18_1_API_INGEST_TOKEN = _v18_1_api_os.getenv("DECISION_DESK_INGEST_TOKEN", "")

@app.post("/decision_desk/ingest")
async def decision_desk_ingest(
    request: _v18_1_Request,
    x_decision_desk_token: Optional[str] = _v18_1_Header(default=None)
):
    """
    Recibe desde ibkr_bridge.py el snapshot operativo generado localmente
    y lo guarda en Render para que los endpoints GET lo puedan leer.
    """
    try:
        if _V18_1_API_INGEST_TOKEN:
            if x_decision_desk_token != _V18_1_API_INGEST_TOKEN:
                return {
                    "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
                    "status": "UNAUTHORIZED",
                    "saved": False,
                }

        payload = await request.json()

        if not isinstance(payload, dict):
            return {
                "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
                "status": "INVALID_PAYLOAD",
                "saved": False,
            }

        payload["remote_ingested_at"] = _v18_api_datetime.now(_v18_api_timezone.utc).isoformat()
        payload["snapshot_available"] = True

        try:
            payload.setdefault("health", {})
            payload["health"]["snapshot_available"] = True
            payload["health"]["remote_ingested"] = True
        except Exception:
            pass

        save_path = _v18_api_Path("runtime/decision_desk_snapshot.json")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(_v18_api_json.dumps(payload, ensure_ascii=False, indent=2))

        return {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "status": "OK",
            "saved": True,
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary"),
            "next_best_action": payload.get("next_best_action"),
            "rows_captured": payload.get("health", {}).get("rows_captured"),
        }

    except Exception as e:
        return {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "status": "ERROR",
            "saved": False,
            "error": str(e),
        }


# ============================================================
# SUPER ENGINE BOLSA — V19 OPERATIONAL TRADING DASHBOARD
# ============================================================

from fastapi.responses import HTMLResponse as _v19_HTMLResponse
from datetime import datetime as _v19_datetime, timezone as _v19_timezone
import html as _v19_html

def _v19_safe_data():
    try:
        return _v18_api_load_snapshot()
    except Exception as e:
        return {
            "engine": "V19_OPERATIONAL_TRADING_DASHBOARD",
            "status": "ERROR",
            "generated_at": _v19_datetime.now(_v19_timezone.utc).isoformat(),
            "summary": {
                "entry": 0,
                "manage_position": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "total": 0,
            },
            "next_best_action": None,
            "recommendation": f"No se pudo cargar snapshot: {e}",
            "by_ticker": [],
            "by_strategy": [],
            "top": [],
            "health": {
                "snapshot_available": False,
                "rows_captured": 0,
                "can_operate_count": 0,
                "remote_ingested": False,
            },
        }

def _v19_parse_dt(value):
    try:
        if not value:
            return None
        v = str(value).replace("Z", "+00:00")
        return _v19_datetime.fromisoformat(v)
    except Exception:
        return None

def _v19_snapshot_age_minutes(data):
    dt = _v19_parse_dt(data.get("remote_ingested_at") or data.get("generated_at"))
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_v19_timezone.utc)
        now = _v19_datetime.now(_v19_timezone.utc)
        return round((now - dt).total_seconds() / 60, 2)
    except Exception:
        return None

def _v19_freshness(data):
    age = _v19_snapshot_age_minutes(data)
    if age is None:
        return {
            "status": "UNKNOWN",
            "label": "Sin timestamp",
            "age_minutes": None,
            "color": "#64748b",
        }
    if age <= 5:
        return {
            "status": "FRESH",
            "label": f"Fresh: {age} min",
            "age_minutes": age,
            "color": "#16a34a",
        }
    if age <= 15:
        return {
            "status": "WARNING",
            "label": f"Warning: {age} min",
            "age_minutes": age,
            "color": "#f59e0b",
        }
    return {
        "status": "STALE",
        "label": f"Stale: {age} min",
        "age_minutes": age,
        "color": "#dc2626",
    }

def _v19_decision_color(decision):
    d = str(decision or "").upper()
    if d == "ENTRY":
        return "#16a34a"
    if d == "MANAGE_POSITION":
        return "#2563eb"
    if d == "RADAR":
        return "#f59e0b"
    if d == "WAIT_GREEKS":
        return "#fb923c"
    if d == "WAIT_DATA":
        return "#64748b"
    if d == "BLOCKED":
        return "#dc2626"
    return "#64748b"

def _v19_decision_label(decision):
    d = str(decision or "").upper()
    labels = {
        "ENTRY": "OPERAR / VALIDAR",
        "MANAGE_POSITION": "GESTIONAR POSICIÓN",
        "RADAR": "RADAR",
        "WAIT_GREEKS": "ESPERAR GRIEGAS",
        "WAIT_DATA": "ESPERAR DATOS",
        "BLOCKED": "BLOQUEADO",
    }
    return labels.get(d, d or "SIN DECISIÓN")

def _v19_market_call(data):
    summary = data.get("summary", {}) or {}
    nba = data.get("next_best_action")

    entry = int(summary.get("entry") or 0)
    manage = int(summary.get("manage_position") or 0)
    radar = int(summary.get("radar") or 0)
    blocked = int(summary.get("blocked") or 0)
    wait_greeks = int(summary.get("wait_greeks") or 0)
    wait_data = int(summary.get("wait_data") or 0)

    if manage > 0:
        return {
            "market_call": "GESTIONAR POSICIONES",
            "can_operate_now": False,
            "tone": "blue",
            "message": "Hay posiciones que requieren revisión antes de abrir nuevas operaciones.",
        }

    if entry > 0:
        can_operate = bool(nba and nba.get("can_operate"))
        return {
            "market_call": "POSIBLE ENTRADA",
            "can_operate_now": can_operate,
            "tone": "green" if can_operate else "yellow",
            "message": "Existe al menos una oportunidad en ENTRY. Validar riesgo y liquidez antes de ejecutar.",
        }

    if radar > 0:
        return {
            "market_call": "RADAR",
            "can_operate_now": False,
            "tone": "yellow",
            "message": "Hay oportunidades interesantes, pero todavía no son entrada operable.",
        }

    if wait_greeks > 0 or wait_data > 0:
        return {
            "market_call": "ESPERAR",
            "can_operate_now": False,
            "tone": "gray",
            "message": "El sistema requiere más datos, griegas o confirmaciones antes de operar.",
        }

    if blocked > 0:
        return {
            "market_call": "BLOQUEADO",
            "can_operate_now": False,
            "tone": "red",
            "message": "Las oportunidades actuales están bloqueadas por reglas de seguridad o calidad.",
        }

    return {
        "market_call": "SIN OPORTUNIDAD",
        "can_operate_now": False,
        "tone": "gray",
        "message": "No hay oportunidades relevantes capturadas en el último ciclo.",
    }

def _v19_escape(value):
    return _v19_html.escape(str(value if value is not None else ""))

def _v19_money(value):
    try:
        if value is None:
            return "—"
        return f"{float(value):.2f}"
    except Exception:
        return _v19_escape(value) if value not in [None, ""] else "—"

def _v19_card(title, value, subtitle="", color="#0f172a"):
    return f"""
    <div class="card">
      <div class="card-title">{_v19_escape(title)}</div>
      <div class="card-value" style="color:{color};">{_v19_escape(value)}</div>
      <div class="card-subtitle">{_v19_escape(subtitle)}</div>
    </div>
    """

def _v19_top_rows_html(rows, limit=25):
    if not rows:
        return """
        <tr>
          <td colspan="9" class="empty">Sin oportunidades capturadas.</td>
        </tr>
        """

    html_rows = []
    for row in rows[:limit]:
        decision = row.get("decision")
        color = _v19_decision_color(decision)
        missing = row.get("missing_confirmations") or []
        if isinstance(missing, list):
            missing_text = ", ".join(str(x) for x in missing) if missing else "—"
        else:
            missing_text = str(missing) if missing else "—"

        can_operate = "Sí" if row.get("can_operate") else "No"
        action = row.get("recommendation") or "—"

        html_rows.append(f"""
        <tr>
          <td class="ticker">{_v19_escape(row.get("ticker"))}</td>
          <td>{_v19_escape(row.get("strategy"))}</td>
          <td><span class="pill" style="background:{color};">{_v19_escape(_v19_decision_label(decision))}</span></td>
          <td class="num">{_v19_escape(row.get("score"))}</td>
          <td class="num">{_v19_money(row.get("price"))}</td>
          <td>{_v19_escape(row.get("data_quality"))}</td>
          <td>{_v19_escape(row.get("operational_state") or missing_text)}</td>
          <td>{_v19_escape(can_operate)}</td>
          <td class="small">{_v19_escape(row.get("operational_next_action") or action)}</td>
        </tr>
        """)

    return "\n".join(html_rows)

def _v19_group_rows_html(items, group_name):
    if not items:
        return """
        <tr>
          <td colspan="8" class="empty">Sin datos.</td>
        </tr>
        """

    rows = []
    for item in items:
        best = item.get("best") or {}
        rows.append(f"""
        <tr>
          <td class="ticker">{_v19_escape(item.get(group_name))}</td>
          <td class="num">{_v19_escape(item.get("total", 0))}</td>
          <td class="num green">{_v19_escape(item.get("entry", 0))}</td>
          <td class="num amber">{_v19_escape(item.get("radar", 0))}</td>
          <td class="num orange">{_v19_escape(item.get("wait_greeks", 0))}</td>
          <td class="num gray">{_v19_escape(item.get("wait_data", 0))}</td>
          <td class="num red">{_v19_escape(item.get("blocked", 0))}</td>
          <td class="small">{_v19_escape(best.get("strategy") or best.get("ticker") or "—")} / {_v19_escape(best.get("decision") or "—")}</td>
        </tr>
        """)
    return "\n".join(rows)

def _v19_css():
    return """
    <style>
      body {
        margin: 0;
        padding: 0;
        background: #f8fafc;
        color: #0f172a;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      }
      .page {
        max-width: 1380px;
        margin: 0 auto;
        padding: 28px;
      }
      .header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 18px;
        margin-bottom: 22px;
      }
      h1 {
        margin: 0;
        font-size: 30px;
        letter-spacing: -0.03em;
      }
      .muted {
        color: #64748b;
        font-size: 13px;
      }
      .status {
        padding: 10px 14px;
        border-radius: 14px;
        color: white;
        font-weight: 700;
        white-space: nowrap;
      }
      .hero {
        background: linear-gradient(135deg, #0f172a, #1e293b);
        color: white;
        border-radius: 24px;
        padding: 24px;
        margin-bottom: 22px;
        box-shadow: 0 20px 50px rgba(15, 23, 42, 0.18);
      }
      .hero-grid {
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 22px;
      }
      .hero-label {
        color: #cbd5e1;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 8px;
      }
      .hero-title {
        font-size: 38px;
        font-weight: 800;
        letter-spacing: -0.04em;
        margin-bottom: 8px;
      }
      .hero-message {
        color: #e2e8f0;
        font-size: 16px;
        line-height: 1.45;
      }
      .next-box {
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 18px;
        padding: 18px;
      }
      .next-title {
        font-size: 22px;
        font-weight: 800;
        margin-bottom: 6px;
      }
      .next-subtitle {
        color: #cbd5e1;
        font-size: 14px;
        line-height: 1.4;
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        gap: 14px;
        margin-bottom: 22px;
      }
      .card {
        background: white;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
        border: 1px solid #e2e8f0;
      }
      .card-title {
        color: #64748b;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        font-weight: 700;
      }
      .card-value {
        font-size: 28px;
        font-weight: 850;
        margin-top: 8px;
      }
      .card-subtitle {
        color: #64748b;
        font-size: 12px;
        margin-top: 5px;
      }
      .section {
        background: white;
        border-radius: 22px;
        padding: 20px;
        margin-bottom: 22px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
      }
      .section h2 {
        margin: 0 0 14px 0;
        font-size: 20px;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      th {
        text-align: left;
        color: #475569;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        border-bottom: 1px solid #e2e8f0;
        padding: 10px 8px;
      }
      td {
        border-bottom: 1px solid #f1f5f9;
        padding: 10px 8px;
        vertical-align: top;
      }
      tr:hover td {
        background: #f8fafc;
      }
      .ticker {
        font-weight: 800;
      }
      .num {
        text-align: right;
        font-variant-numeric: tabular-nums;
      }
      .small {
        font-size: 12px;
        color: #334155;
        line-height: 1.35;
      }
      .pill {
        color: white;
        border-radius: 999px;
        padding: 5px 9px;
        font-size: 11px;
        font-weight: 800;
        white-space: nowrap;
      }
      .green { color: #16a34a; font-weight: 800; }
      .amber { color: #d97706; font-weight: 800; }
      .orange { color: #ea580c; font-weight: 800; }
      .red { color: #dc2626; font-weight: 800; }
      .gray { color: #64748b; font-weight: 800; }
      .empty {
        text-align: center;
        color: #64748b;
        padding: 30px;
      }
      .two-col {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 22px;
      }
      .footer {
        color: #64748b;
        font-size: 12px;
        text-align: center;
        padding: 18px 0 4px;
      }
      @media (max-width: 1000px) {
        .grid { grid-template-columns: repeat(2, 1fr); }
        .hero-grid { grid-template-columns: 1fr; }
        .two-col { grid-template-columns: 1fr; }
        .header { flex-direction: column; }
      }
    </style>
    """

@app.get("/dashboard_decision", response_class=_v19_HTMLResponse)
def dashboard_decision():
    data = _v19_safe_data()
    try:
        data = _v20_enrich_snapshot(data)
    except Exception:
        pass
    summary = data.get("summary", {}) or {}
    health = data.get("health", {}) or {}
    nba = data.get("next_best_action") or {}
    freshness = _v19_freshness(data)
    call = _v19_market_call(data)

    call_color = {
        "green": "#16a34a",
        "yellow": "#f59e0b",
        "gray": "#64748b",
        "red": "#dc2626",
        "blue": "#2563eb",
    }.get(call.get("tone"), "#64748b")

    if nba:
        next_title = f"{nba.get('ticker', '—')} / {nba.get('strategy', '—')}"
        next_subtitle = nba.get("recommendation") or nba.get("reason") or "Sin recomendación."
        next_decision = _v19_decision_label(nba.get("decision"))
    else:
        next_title = "Sin oportunidad"
        next_subtitle = data.get("recommendation") or "No hay oportunidad capturada."
        next_decision = "SIN DECISIÓN"

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Super Engine Bolsa — Decision Dashboard</title>
      {_v19_css()}
    </head>
    <body>
      <div class="page">
        <div class="header">
          <div>
            <h1>Super Engine Bolsa — Operational Trading Dashboard</h1>
            <div class="muted">
              Engine: {_v19_escape(data.get("engine"))} · Generated: {_v19_escape(data.get("generated_at"))} · Remote ingested: {_v19_escape(data.get("remote_ingested_at", "—"))}
            </div>
          </div>
          <div class="status" style="background:{freshness.get('color')};">
            {_v19_escape(freshness.get("label"))}
          </div>
        </div>

        <div class="hero">
          <div class="hero-grid">
            <div>
              <div class="hero-label">Estado operativo</div>
              <div class="hero-title" style="color:{call_color};">{_v19_escape(call.get("market_call"))}</div>
              <div class="hero-message">{_v19_escape(call.get("message"))}</div>
            </div>
            <div class="next-box">
              <div class="hero-label">Next Best Action</div>
              <div class="next-title">{_v19_escape(next_title)}</div>
              <div class="pill" style="display:inline-block;background:{_v19_decision_color(nba.get("decision"))};margin-bottom:10px;">{_v19_escape(next_decision)}</div>
              <div class="next-subtitle">{_v19_escape(next_subtitle)}</div>
            </div>
          </div>
        </div>

        <div class="grid">
          {_v19_card("Entry", summary.get("entry", 0), "Entradas posibles", "#16a34a")}
          {_v19_card("Manage", summary.get("manage_position", 0), "Gestión de posición", "#2563eb")}
          {_v19_card("Radar", summary.get("radar", 0), "Oportunidades en observación", "#d97706")}
          {_v19_card("Wait Greeks", summary.get("wait_greeks", 0), "Faltan griegas", "#ea580c")}
          {_v19_card("Wait Data", summary.get("wait_data", 0), "Faltan datos", "#64748b")}
          {_v19_card("Total", summary.get("total", 0), f"Rows: {health.get('rows_captured', 0)}", "#0f172a")}
        </div>

        <div class="section">
          <h2>Oportunidades priorizadas</h2>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Estrategia</th>
                <th>Decisión</th>
                <th class="num">Score</th>
                <th class="num">Prima/Precio</th>
                <th>Calidad</th>
                <th>Falta</th>
                <th>Operable</th>
                <th>Acción</th>
              </tr>
            </thead>
            <tbody>
              {_v19_top_rows_html(data.get("top", []), limit=30)}
            </tbody>
          </table>
        </div>

        <div class="two-col">
          <div class="section">
            <h2>Resumen por ticker</h2>
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th class="num">Total</th>
                  <th class="num">Entry</th>
                  <th class="num">Radar</th>
                  <th class="num">Greeks</th>
                  <th class="num">Data</th>
                  <th class="num">Blocked</th>
                  <th>Best</th>
                </tr>
              </thead>
              <tbody>
                {_v19_group_rows_html(data.get("by_ticker", []), "ticker")}
              </tbody>
            </table>
          </div>

          <div class="section">
            <h2>Resumen por estrategia</h2>
            <table>
              <thead>
                <tr>
                  <th>Estrategia</th>
                  <th class="num">Total</th>
                  <th class="num">Entry</th>
                  <th class="num">Radar</th>
                  <th class="num">Greeks</th>
                  <th class="num">Data</th>
                  <th class="num">Blocked</th>
                  <th>Best</th>
                </tr>
              </thead>
              <tbody>
                {_v19_group_rows_html(data.get("by_strategy", []), "strategy")}
              </tbody>
            </table>
          </div>
        </div>

        <div class="section">
          <h2>Conclusión ejecutiva</h2>
          <p class="small" style="font-size:15px;">
            {_v19_escape(data.get("recommendation") or call.get("message"))}
          </p>
          <p class="muted">
            Snapshot available: {_v19_escape(health.get("snapshot_available"))} · Remote ingested: {_v19_escape(health.get("remote_ingested"))} · Can operate count: {_v19_escape(health.get("can_operate_count"))}
          </p>
        </div>

        <div class="footer">
          Super Engine Bolsa · V19 Operational Trading Dashboard
        </div>
      </div>
    </body>
    </html>
    """
    return html

@app.get("/dashboard_ticker/{ticker}", response_class=_v19_HTMLResponse)
def dashboard_ticker(ticker: str):
    data = _v19_safe_data()
    try:
        data = _v20_enrich_snapshot(data)
    except Exception:
        pass
    t = str(ticker or "").upper().strip()

    top = [
        row for row in data.get("top", [])
        if str(row.get("ticker", "")).upper() == t
    ]

    ticker_summary = None
    for item in data.get("by_ticker", []):
        if str(item.get("ticker", "")).upper() == t:
            ticker_summary = item
            break

    best = top[0] if top else None
    freshness = _v19_freshness(data)

    if best:
        title = f"{t} — {best.get('strategy')} / {_v19_decision_label(best.get('decision'))}"
        recommendation = best.get("recommendation") or "Sin recomendación."
        reason = best.get("reason") or "Sin razón disponible."
    else:
        title = f"{t} — Sin oportunidad capturada"
        recommendation = f"No hay oportunidades capturadas para {t} en el último ciclo."
        reason = "El ticker no aparece dentro del top operativo actual."

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{_v19_escape(t)} — Super Engine Bolsa</title>
      {_v19_css()}
    </head>
    <body>
      <div class="page">
        <div class="header">
          <div>
            <h1>{_v19_escape(title)}</h1>
            <div class="muted">Generated: {_v19_escape(data.get("generated_at"))}</div>
          </div>
          <div class="status" style="background:{freshness.get('color')};">
            {_v19_escape(freshness.get("label"))}
          </div>
        </div>

        <div class="hero">
          <div class="hero-grid">
            <div>
              <div class="hero-label">Recomendación</div>
              <div class="hero-title" style="font-size:28px;">{_v19_escape(recommendation)}</div>
              <div class="hero-message">{_v19_escape(reason)}</div>
            </div>
            <div class="next-box">
              <div class="hero-label">Resumen del ticker</div>
              <div class="next-subtitle">
                Total: {_v19_escape((ticker_summary or {}).get("total", 0))}<br>
                Entry: {_v19_escape((ticker_summary or {}).get("entry", 0))}<br>
                Radar: {_v19_escape((ticker_summary or {}).get("radar", 0))}<br>
                Wait Greeks: {_v19_escape((ticker_summary or {}).get("wait_greeks", 0))}<br>
                Blocked: {_v19_escape((ticker_summary or {}).get("blocked", 0))}
              </div>
            </div>
          </div>
        </div>

        <div class="section">
          <h2>Oportunidades para {_v19_escape(t)}</h2>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Estrategia</th>
                <th>Decisión</th>
                <th class="num">Score</th>
                <th class="num">Prima/Precio</th>
                <th>Calidad</th>
                <th>Falta</th>
                <th>Operable</th>
                <th>Acción</th>
              </tr>
            </thead>
            <tbody>
              {_v19_top_rows_html(top, limit=30)}
            </tbody>
          </table>
        </div>

        <div class="footer">
          <a href="/dashboard_decision">Volver al dashboard</a>
        </div>
      </div>
    </body>
    </html>
    """
    return html

@app.get("/gpt_decision_summary")
def gpt_decision_summary():
    data = _v19_safe_data()
    try:
        data = _v20_enrich_snapshot(data)
    except Exception:
        pass
    summary = data.get("summary", {}) or {}
    nba = data.get("next_best_action") or {}
    freshness = _v19_freshness(data)
    call = _v19_market_call(data)

    top_3 = []
    for row in (data.get("top", []) or [])[:3]:
        top_3.append({
            "ticker": row.get("ticker"),
            "strategy": row.get("strategy"),
            "decision": row.get("decision"),
            "score": row.get("score"),
            "price": row.get("price"),
            "can_operate": row.get("can_operate"),
            "missing_confirmations": row.get("missing_confirmations"),
            "recommendation": row.get("recommendation"),
            "reason": row.get("reason"),
            "operational_state": row.get("operational_state"),
            "operational_reason": row.get("operational_reason"),
            "operational_next_action": row.get("operational_next_action"),
        })

    return {
        "engine": "V19_OPERATIONAL_TRADING_DASHBOARD",
        "status": "OK" if data.get("health", {}).get("snapshot_available") else "NO_SNAPSHOT",
        "freshness": freshness,
        "market_hours": data.get("market_hours"),
        "market_call": call.get("market_call"),
        "can_operate_now": call.get("can_operate_now"),
        "summary": summary,
        "best_opportunity": {
            "ticker": nba.get("ticker"),
            "strategy": nba.get("strategy"),
            "decision": nba.get("decision"),
            "score": nba.get("score"),
            "price": nba.get("price"),
            "can_operate": nba.get("can_operate"),
            "missing_confirmations": nba.get("missing_confirmations"),
            "recommendation": nba.get("recommendation"),
            "reason": nba.get("reason"),
            "operational_state": nba.get("operational_state"),
            "operational_reason": nba.get("operational_reason"),
            "operational_next_action": nba.get("operational_next_action"),
        } if nba else None,
        "executive_conclusion": data.get("recommendation") or call.get("message"),
        "top_3": top_3,
        "health": data.get("health", {}),
    }

@app.get("/system_status")
def system_status():
    data = _v19_safe_data()
    freshness = _v19_freshness(data)
    health = data.get("health", {}) or {}

    return {
        "engine": "V19_OPERATIONAL_TRADING_DASHBOARD",
        "api_status": "OK",
        "snapshot_status": "OK" if health.get("snapshot_available") else "NO_SNAPSHOT",
        "remote_ingested": bool(health.get("remote_ingested")),
        "rows_captured": health.get("rows_captured", 0),
        "can_operate_count": health.get("can_operate_count", 0),
        "generated_at": data.get("generated_at"),
        "remote_ingested_at": data.get("remote_ingested_at"),
        "freshness": freshness,
        "summary": data.get("summary", {}),
        "urls": {
            "dashboard": "/dashboard_decision",
            "gpt_summary": "/gpt_decision_summary",
            "system_status": "/system_status",
            "ticker_example": "/dashboard_ticker/QQQ",
        },
    }


# ============================================================
# SUPER ENGINE BOLSA — V20 MARKET HOURS & LIQUIDITY INTELLIGENCE
# ============================================================

from datetime import datetime as _v20_datetime, timezone as _v20_timezone, time as _v20_time
try:
    from zoneinfo import ZoneInfo as _v20_ZoneInfo
except Exception:
    _v20_ZoneInfo = None

def _v20_now_ny():
    try:
        if _v20_ZoneInfo:
            return _v20_datetime.now(_v20_ZoneInfo("America/New_York"))
    except Exception:
        pass
    return _v20_datetime.now(_v20_timezone.utc)

def _v20_market_hours_status():
    """
    V20:
    Determina estado simple de mercado USA.
    No reemplaza calendario oficial de feriados, pero mejora muchísimo la lectura
    respecto a bid/ask ausente fuera de horario.
    """
    now = _v20_now_ny()
    weekday = now.weekday()  # Monday=0, Sunday=6

    market_open = _v20_time(9, 30)
    market_close = _v20_time(16, 0)
    option_liquidity_start = _v20_time(9, 35)
    option_liquidity_end = _v20_time(15, 55)

    is_weekend = weekday >= 5
    current_time = now.time()

    if is_weekend:
        status = "WEEKEND_CLOSED"
        is_open = False
        options_expected = False
        next_check = "Próxima sesión hábil, después de 09:35 ET."
        label = "Mercado cerrado por fin de semana"
    elif current_time < market_open:
        status = "PRE_MARKET"
        is_open = False
        options_expected = False
        next_check = "Revisar después de 09:35 ET."
        label = "Pre-market: opciones aún no confiables"
    elif market_open <= current_time < option_liquidity_start:
        status = "OPENING_NOISE"
        is_open = True
        options_expected = False
        next_check = "Revisar después de 09:35 ET."
        label = "Apertura: esperar liquidez inicial"
    elif option_liquidity_start <= current_time <= option_liquidity_end:
        status = "REGULAR_OPTIONS_SESSION"
        is_open = True
        options_expected = True
        next_check = "Datos deberían ser operables si hay liquidez."
        label = "Mercado abierto: opciones en ventana operable"
    elif option_liquidity_end < current_time <= market_close:
        status = "LATE_SESSION"
        is_open = True
        options_expected = True
        next_check = "Precaución: cerca del cierre, spreads pueden abrirse."
        label = "Mercado abierto cerca del cierre"
    else:
        status = "AFTER_HOURS"
        is_open = False
        options_expected = False
        next_check = "Revisar próxima sesión después de 09:35 ET."
        label = "After-hours: opciones no confiables"

    return {
        "status": status,
        "label": label,
        "is_regular_market_open": bool(is_open),
        "options_bidask_expected": bool(options_expected),
        "new_york_time": now.isoformat(),
        "next_check": next_check,
    }

def _v20_row_operational_reason(row, market_status=None):
    """
    Interpreta por qué una fila no es operable.
    """
    market_status = market_status or _v20_market_hours_status()
    decision = str(row.get("decision") or "").upper()
    data_quality = str(row.get("data_quality") or "")
    missing = row.get("missing_confirmations") or []

    if isinstance(missing, str):
        missing_list = [x.strip() for x in missing.split(",") if x.strip()]
    elif isinstance(missing, list):
        missing_list = [str(x).strip() for x in missing if str(x).strip()]
    else:
        missing_list = []

    can_operate = bool(row.get("can_operate"))

    has_bidask_issue = (
        "bid_ask" in missing_list
        or "spread" in missing_list
        or "NO_BIDASK" in data_quality
        or "PRICE_ONLY" in data_quality
    )

    has_greeks_issue = (
        "greeks" in missing_list
        or "delta" in missing_list
        or "iv" in missing_list
        or "WAIT_GREEKS" in decision
        or "NO_GREEKS" in data_quality
    )

    if can_operate:
        return {
            "operational_state": "ENTRY_READY",
            "severity": "green",
            "reason": "Oportunidad operable. Validar tamaño, riesgo y precio límite antes de ejecutar.",
            "next_action": "Validar orden sugerida y gestión de riesgo.",
        }

    if not market_status.get("options_bidask_expected") and has_bidask_issue:
        return {
            "operational_state": "MARKET_CLOSED_OR_NOT_LIQUID_YET",
            "severity": "gray",
            "reason": "La falta de bid/ask o spread es esperada porque las opciones no están en una ventana confiable.",
            "next_action": market_status.get("next_check"),
        }

    if has_bidask_issue:
        return {
            "operational_state": "WAIT_LIQUIDITY",
            "severity": "orange",
            "reason": "La oportunidad tiene score alto, pero falta confirmar bid/ask y spread real.",
            "next_action": "Esperar bid/ask completo y spread razonable antes de operar.",
        }

    if has_greeks_issue:
        return {
            "operational_state": "WAIT_GREEKS",
            "severity": "orange",
            "reason": "Faltan griegas o datos críticos de opciones para validar riesgo.",
            "next_action": "Esperar actualización de delta, IV y griegas.",
        }

    if decision == "RADAR":
        return {
            "operational_state": "RADAR",
            "severity": "yellow",
            "reason": "Oportunidad interesante, pero aún no cumple todas las reglas de entrada.",
            "next_action": "Mantener en radar.",
        }

    if decision == "BLOCKED":
        return {
            "operational_state": "BLOCKED",
            "severity": "red",
            "reason": "Bloqueada por reglas de seguridad, calidad o riesgo.",
            "next_action": "No operar.",
        }

    return {
        "operational_state": "WAIT_DATA",
        "severity": "gray",
        "reason": "Faltan datos suficientes para clasificar la oportunidad.",
        "next_action": "Esperar siguiente ciclo.",
    }

def _v20_enrich_rows(rows):
    market_status = _v20_market_hours_status()
    enriched = []
    for row in rows or []:
        try:
            r = dict(row)
            op = _v20_row_operational_reason(r, market_status)
            r["market_hours"] = market_status
            r["operational_state"] = op.get("operational_state")
            r["operational_reason"] = op.get("reason")
            r["operational_next_action"] = op.get("next_action")
            r["operational_severity"] = op.get("severity")
            enriched.append(r)
        except Exception:
            enriched.append(row)
    return enriched

def _v20_enrich_snapshot(data):
    try:
        d = dict(data or {})
        market_status = _v20_market_hours_status()
        d["market_hours"] = market_status

        top = d.get("top") or []
        enriched_top = _v20_enrich_rows(top)
        d["top"] = enriched_top

        nba = d.get("next_best_action")
        if isinstance(nba, dict):
            nba2 = dict(nba)
            op = _v20_row_operational_reason(nba2, market_status)
            nba2["market_hours"] = market_status
            nba2["operational_state"] = op.get("operational_state")
            nba2["operational_reason"] = op.get("reason")
            nba2["operational_next_action"] = op.get("next_action")
            nba2["operational_severity"] = op.get("severity")

            if not nba2.get("can_operate") and op.get("operational_state") == "MARKET_CLOSED_OR_NOT_LIQUID_YET":
                nba2["recommendation"] = (
                    "Mantener en radar. No operar ahora porque las opciones no están en una ventana "
                    "confiable para bid/ask. " + str(market_status.get("next_check"))
                )
            elif not nba2.get("can_operate") and op.get("operational_state") == "WAIT_LIQUIDITY":
                nba2["recommendation"] = (
                    "Mantener en radar. No operar directo hasta confirmar liquidez real: bid/ask y spread."
                )

            d["next_best_action"] = nba2

        d.setdefault("health", {})
        d["health"]["market_hours_status"] = market_status.get("status")
        d["health"]["options_bidask_expected"] = market_status.get("options_bidask_expected")
        d["health"]["market_hours_label"] = market_status.get("label")
        return d
    except Exception:
        return data

@app.get("/market_hours")
def market_hours():
    return {
        "engine": "V20_MARKET_HOURS_LIQUIDITY_INTELLIGENCE",
        "market_hours": _v20_market_hours_status(),
    }

@app.get("/liquidity_desk")
def liquidity_desk():
    data = _v19_safe_data()
    data = _v20_enrich_snapshot(data)
    market_status = data.get("market_hours", {})
    top = data.get("top", []) or []

    counts = {
        "ENTRY_READY": 0,
        "MARKET_CLOSED_OR_NOT_LIQUID_YET": 0,
        "WAIT_LIQUIDITY": 0,
        "WAIT_GREEKS": 0,
        "RADAR": 0,
        "WAIT_DATA": 0,
        "BLOCKED": 0,
    }

    for row in top:
        state = row.get("operational_state") or "WAIT_DATA"
        counts[state] = counts.get(state, 0) + 1

    return {
        "engine": "V20_MARKET_HOURS_LIQUIDITY_INTELLIGENCE",
        "status": "OK",
        "market_hours": market_status,
        "operational_counts": counts,
        "best_opportunity": data.get("next_best_action"),
        "top": top[:20],
        "summary": data.get("summary", {}),
        "health": data.get("health", {}),
    }


# ============================================================
# SUPER ENGINE BOLSA — V21 TECHNICAL + OPTIONS FUSION
# ============================================================

import json as _v21_json
from pathlib import Path as _v21_Path
from datetime import datetime as _v21_datetime, timezone as _v21_timezone

def _v21_safe_float(value, default=None):
    try:
        if value is None:
            return default
        if value == "":
            return default
        return float(value)
    except Exception:
        return default

def _v21_safe_int(value, default=0):
    try:
        if value is None:
            return default
        if value == "":
            return default
        return int(float(value))
    except Exception:
        return default

def _v21_candidate_technical_paths():
    return [
        _v21_Path("runtime/technical_snapshot.json"),
        _v21_Path("runtime/technical_snapshot_v15_1.json"),
        _v21_Path("runtime/latest_technical_snapshot.json"),
        _v21_Path("/tmp/technical_snapshot.json"),
        _v21_Path("/tmp/technical_snapshot_v15_1.json"),
        _v21_Path("/tmp/latest_technical_snapshot.json"),
    ]

def _v21_load_technical_store():
    """
    V21:
    Carga el technical snapshot desde las ubicaciones probables.
    También intenta usar funciones globales existentes si el backend ya las tiene.
    """
    # 1) Intentar funciones existentes del app si están definidas
    possible_functions = [
        "_get_latest_technical_snapshot",
        "get_latest_technical_snapshot",
        "_technical_snapshot_store",
        "_load_technical_snapshot",
    ]

    for fn_name in possible_functions:
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                data = fn()
                if data:
                    return {
                        "available": True,
                        "source": f"function:{fn_name}",
                        "data": data,
                    }
        except Exception:
            pass

    # 2) Intentar variables globales existentes
    possible_vars = [
        "TECHNICAL_SNAPSHOT_STORE",
        "technical_snapshot_store",
        "latest_technical_snapshot",
        "LATEST_TECHNICAL_SNAPSHOT",
    ]

    for var_name in possible_vars:
        try:
            data = globals().get(var_name)
            if data:
                return {
                    "available": True,
                    "source": f"global:{var_name}",
                    "data": data,
                }
        except Exception:
            pass

    # 3) Intentar archivos runtime/tmp
    for p in _v21_candidate_technical_paths():
        try:
            if p.exists():
                raw = p.read_text()
                if raw.strip():
                    data = _v21_json.loads(raw)
                    return {
                        "available": True,
                        "source": str(p),
                        "data": data,
                    }
        except Exception:
            pass

    return {
        "available": False,
        "source": None,
        "data": None,
    }

def _v21_extract_technical_by_ticker():
    store = _v21_load_technical_store()
    data = store.get("data")

    result = {}

    if not data:
        return {
            "available": False,
            "source": store.get("source"),
            "by_ticker": {},
            "raw": data,
        }

    try:
        # Caso A: payload directo de un solo ticker
        if isinstance(data, dict) and data.get("ticker"):
            t = str(data.get("ticker")).upper()
            result[t] = data

        # Caso B: dict con technical_snapshot
        if isinstance(data, dict) and isinstance(data.get("technical_snapshot"), dict):
            ts = data.get("technical_snapshot")
            if ts.get("ticker"):
                result[str(ts.get("ticker")).upper()] = ts

        # Caso C: dict por ticker
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    if v.get("ticker"):
                        result[str(v.get("ticker")).upper()] = v
                    elif str(k).isalpha() and len(str(k)) <= 6:
                        vv = dict(v)
                        vv.setdefault("ticker", str(k).upper())
                        result[str(k).upper()] = vv

        # Caso D: lista de snapshots
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("ticker"):
                    result[str(item.get("ticker")).upper()] = item

        # Caso E: payload con rows/items
        if isinstance(data, dict):
            for key in ["rows", "items", "snapshots", "data"]:
                rows = data.get(key)
                if isinstance(rows, list):
                    for item in rows:
                        if isinstance(item, dict) and item.get("ticker"):
                            result[str(item.get("ticker")).upper()] = item
    except Exception:
        pass

    return {
        "available": bool(result),
        "source": store.get("source"),
        "by_ticker": result,
        "raw": data,
    }

def _v21_technical_bias(ts):
    if not isinstance(ts, dict) or not ts:
        return {
            "bias": "UNKNOWN",
            "confirmation": False,
            "score": 0,
            "reason": "Sin technical snapshot disponible para el ticker.",
        }

    trend = str(ts.get("trend") or ts.get("trend_label") or "").lower()
    trend_code = _v21_safe_float(ts.get("trend_code"), None)
    score = _v21_safe_float(ts.get("score"), None)
    rsi = _v21_safe_float(ts.get("rsi"), None)
    adx = _v21_safe_float(ts.get("adx"), None)
    range_breakout = ts.get("range_breakout")
    support_near = ts.get("support_near")
    resistance_near = ts.get("resistance_near")
    vwap_position = str(ts.get("vwap_position") or "").lower()
    vwap_position_code = _v21_safe_float(ts.get("vwap_position_code"), None)
    volume_relative = _v21_safe_float(ts.get("volume_relative"), None)
    event_risk = bool(ts.get("event_risk") or False)
    earnings_soon = bool(ts.get("earnings_soon") or False)

    bullish_points = 0
    bearish_points = 0
    neutral_points = 0
    reasons = []

    # Trend
    if "bull" in trend or trend_code == 1:
        bullish_points += 2
        reasons.append("tendencia alcista")
    elif "bear" in trend or trend_code == -1:
        bearish_points += 2
        reasons.append("tendencia bajista")
    elif "neutral" in trend or trend_code == 0:
        neutral_points += 1
        reasons.append("tendencia neutral")

    # Score técnico
    if score is not None:
        if score >= 75:
            bullish_points += 1
            reasons.append(f"score técnico fuerte ({score})")
        elif score <= 35:
            bearish_points += 1
            reasons.append(f"score técnico débil ({score})")
        else:
            neutral_points += 1
            reasons.append(f"score técnico mixto ({score})")

    # RSI
    if rsi is not None:
        if 45 <= rsi <= 65:
            neutral_points += 1
            reasons.append(f"RSI saludable/neutral ({rsi})")
        elif rsi < 35:
            bullish_points += 1
            reasons.append(f"RSI en zona baja/sobreventa relativa ({rsi})")
        elif rsi > 70:
            bearish_points += 1
            reasons.append(f"RSI extendido/sobrecompra ({rsi})")

    # ADX
    if adx is not None:
        if adx >= 25:
            if bullish_points >= bearish_points:
                bullish_points += 1
                reasons.append(f"ADX confirma fuerza de tendencia ({adx})")
            else:
                bearish_points += 1
                reasons.append(f"ADX confirma presión direccional ({adx})")
        elif adx < 20:
            neutral_points += 1
            reasons.append(f"ADX bajo/rango ({adx})")

    # VWAP
    if "above" in vwap_position or vwap_position_code == 1:
        bullish_points += 1
        reasons.append("precio sobre VWAP")
    elif "below" in vwap_position or vwap_position_code == -1:
        bearish_points += 1
        reasons.append("precio bajo VWAP")
    elif "near" in vwap_position or vwap_position_code == 0:
        neutral_points += 1
        reasons.append("precio cerca de VWAP")

    # Breakout / soportes
    if range_breakout is True or str(range_breakout).lower() == "true":
        bullish_points += 1
        reasons.append("ruptura de rango detectada")
    if support_near is True or str(support_near).lower() == "true":
        bullish_points += 1
        reasons.append("soporte cercano")
    if resistance_near is True or str(resistance_near).lower() == "true":
        bearish_points += 1
        reasons.append("resistencia cercana")

    # Volumen
    if volume_relative is not None:
        if volume_relative >= 1.5:
            if bullish_points >= bearish_points:
                bullish_points += 1
            else:
                bearish_points += 1
            reasons.append(f"volumen relativo elevado ({volume_relative})")
        elif volume_relative < 0.8:
            neutral_points += 1
            reasons.append(f"volumen relativo bajo ({volume_relative})")

    # Eventos
    if event_risk or earnings_soon:
        bearish_points += 2
        reasons.append("riesgo de evento/earnings")

    if bullish_points > bearish_points and bullish_points >= 2:
        bias = "BULLISH"
    elif bearish_points > bullish_points and bearish_points >= 2:
        bias = "BEARISH"
    elif neutral_points >= 1:
        bias = "NEUTRAL"
    else:
        bias = "UNKNOWN"

    confidence_score = max(0, min(100, (bullish_points - bearish_points + 4) * 12.5))
    if bias == "NEUTRAL":
        confidence_score = max(40, min(65, confidence_score))
    if bias == "UNKNOWN":
        confidence_score = 0

    confirmation = bias in ["BULLISH", "NEUTRAL"] and not event_risk and not earnings_soon

    return {
        "bias": bias,
        "confirmation": bool(confirmation),
        "score": round(confidence_score, 1),
        "bullish_points": bullish_points,
        "bearish_points": bearish_points,
        "neutral_points": neutral_points,
        "reason": "; ".join(reasons) if reasons else "Technical snapshot sin señales suficientes.",
    }

def _v21_strategy_technical_fit(strategy, technical_bias):
    strategy = str(strategy or "").upper()
    bias = str(technical_bias or "UNKNOWN").upper()

    if strategy == "NAKED_PUT":
        if bias == "BULLISH":
            return {
                "fit": "STRONG_FIT",
                "score_adjustment": 15,
                "reason": "Naked Put favorecida por sesgo técnico alcista.",
            }
        if bias == "NEUTRAL":
            return {
                "fit": "ACCEPTABLE_FIT",
                "score_adjustment": 5,
                "reason": "Naked Put aceptable con técnico neutral/rango.",
            }
        if bias == "BEARISH":
            return {
                "fit": "POOR_FIT",
                "score_adjustment": -25,
                "reason": "Naked Put desfavorecida por sesgo técnico bajista.",
            }

    if strategy == "COVERED_CALL":
        if bias == "BEARISH":
            return {
                "fit": "STRONG_FIT",
                "score_adjustment": 15,
                "reason": "Covered Call favorecida por sesgo técnico bajista o de techo.",
            }
        if bias == "NEUTRAL":
            return {
                "fit": "ACCEPTABLE_FIT",
                "score_adjustment": 8,
                "reason": "Covered Call aceptable con técnico neutral/rango.",
            }
        if bias == "BULLISH":
            return {
                "fit": "CAUTION",
                "score_adjustment": -8,
                "reason": "Covered Call requiere cautela si el activo está muy alcista.",
            }

    return {
        "fit": "UNKNOWN_FIT",
        "score_adjustment": 0,
        "reason": "Sin regla técnica específica para esta estrategia.",
    }

def _v21_fuse_row(row, technical_by_ticker):
    r = dict(row or {})
    ticker = str(r.get("ticker") or "").upper()
    strategy = str(r.get("strategy") or "").upper()

    ts = technical_by_ticker.get(ticker)
    tech = _v21_technical_bias(ts)
    fit = _v21_strategy_technical_fit(strategy, tech.get("bias"))

    base_score = _v21_safe_float(r.get("score"), 0) or 0
    adjustment = _v21_safe_float(fit.get("score_adjustment"), 0) or 0
    combined_score = max(0, min(100, base_score + adjustment))

    can_operate = bool(r.get("can_operate"))
    operational_state = r.get("operational_state") or r.get("decision")
    technical_confirmation = bool(tech.get("confirmation"))

    if can_operate and technical_confirmation and combined_score >= 80:
        final_state = "ENTRY_CONFIRMED"
        final_action = "Oportunidad técnicamente confirmada. Validar precio límite, tamaño y riesgo antes de ejecutar."
    elif str(operational_state).upper() in ["MARKET_CLOSED_OR_NOT_LIQUID_YET"]:
        final_state = "WAIT_MARKET_OPEN"
        final_action = "No operar ahora. Esperar ventana confiable de opciones y revalidar técnico."
    elif str(operational_state).upper() in ["WAIT_LIQUIDITY"]:
        final_state = "WAIT_LIQUIDITY"
        final_action = "Esperar bid/ask y spread real antes de considerar entrada."
    elif str(operational_state).upper() in ["WAIT_GREEKS"]:
        final_state = "WAIT_GREEKS"
        final_action = "Esperar griegas completas antes de considerar entrada."
    elif tech.get("bias") == "BEARISH" and strategy == "NAKED_PUT":
        final_state = "TECHNICAL_CONFLICT"
        final_action = "No operar Naked Put hasta que mejore el técnico o exista soporte confirmado."
    elif tech.get("bias") == "BULLISH" and strategy == "COVERED_CALL":
        final_state = "TECHNICAL_CAUTION"
        final_action = "Covered Call con cautela: técnico alcista puede limitar upside si se vende call muy cerca."
    elif combined_score >= 80:
        final_state = "RADAR_TECH_OK"
        final_action = "Mantener en radar. Técnico aceptable, pero falta confirmación operativa."
    elif combined_score >= 60:
        final_state = "RADAR_MIXED"
        final_action = "Mantener en observación. Señal mixta entre opciones y técnico."
    else:
        final_state = "LOW_PRIORITY"
        final_action = "Baja prioridad por score combinado o falta de confirmación técnica."

    r["technical_snapshot_available"] = bool(ts)
    r["technical_bias"] = tech.get("bias")
    r["technical_confirmation"] = tech.get("confirmation")
    r["technical_score"] = tech.get("score")
    r["technical_reason"] = tech.get("reason")
    r["strategy_technical_fit"] = fit.get("fit")
    r["strategy_technical_reason"] = fit.get("reason")
    r["combined_score"] = round(combined_score, 1)
    r["fusion_state"] = final_state
    r["fusion_action"] = final_action

    return r

def _v21_fusion_snapshot():
    base = _v19_safe_data()
    try:
        base = _v20_enrich_snapshot(base)
    except Exception:
        pass

    technical = _v21_extract_technical_by_ticker()
    technical_by_ticker = technical.get("by_ticker", {}) or {}

    top = base.get("top") or []
    fused_top = [_v21_fuse_row(row, technical_by_ticker) for row in top]
    fused_top = sorted(
        fused_top,
        key=lambda x: (
            _v21_safe_float(x.get("combined_score"), 0) or 0,
            _v21_safe_float(x.get("score"), 0) or 0,
        ),
        reverse=True,
    )

    best = fused_top[0] if fused_top else None

    counts = {
        "ENTRY_CONFIRMED": 0,
        "RADAR_TECH_OK": 0,
        "RADAR_MIXED": 0,
        "TECHNICAL_CONFLICT": 0,
        "TECHNICAL_CAUTION": 0,
        "WAIT_MARKET_OPEN": 0,
        "WAIT_LIQUIDITY": 0,
        "WAIT_GREEKS": 0,
        "LOW_PRIORITY": 0,
    }

    for row in fused_top:
        state = row.get("fusion_state") or "LOW_PRIORITY"
        counts[state] = counts.get(state, 0) + 1

    by_ticker = {}
    for row in fused_top:
        t = row.get("ticker") or "UNKNOWN"
        if t not in by_ticker:
            by_ticker[t] = {
                "ticker": t,
                "total": 0,
                "best": None,
                "technical_bias": row.get("technical_bias"),
                "technical_confirmation": row.get("technical_confirmation"),
                "avg_combined_score": 0,
                "states": {},
            }
        by_ticker[t]["total"] += 1
        by_ticker[t]["states"][row.get("fusion_state")] = by_ticker[t]["states"].get(row.get("fusion_state"), 0) + 1
        if by_ticker[t]["best"] is None or (_v21_safe_float(row.get("combined_score"), 0) or 0) > (_v21_safe_float(by_ticker[t]["best"].get("combined_score"), 0) or 0):
            by_ticker[t]["best"] = row

    for t, item in by_ticker.items():
        scores = [
            _v21_safe_float(r.get("combined_score"), 0) or 0
            for r in fused_top
            if r.get("ticker") == t
        ]
        item["avg_combined_score"] = round(sum(scores) / len(scores), 1) if scores else 0

    if best:
        executive = (
            f"Mejor oportunidad fusionada: {best.get('ticker')} / {best.get('strategy')} "
            f"con estado {best.get('fusion_state')} y score combinado {best.get('combined_score')}. "
            f"{best.get('fusion_action')}"
        )
    else:
        executive = "No hay oportunidades fusionadas disponibles. Revisar snapshot IBKR y technical snapshot."

    return {
        "engine": "V21_TECHNICAL_OPTIONS_FUSION",
        "status": "OK" if base.get("health", {}).get("snapshot_available") else "NO_SNAPSHOT",
        "generated_at": _v21_datetime.now(_v21_timezone.utc).isoformat(),
        "market_hours": base.get("market_hours"),
        "technical_snapshot_available": technical.get("available"),
        "technical_snapshot_source": technical.get("source"),
        "technical_tickers": sorted(list(technical_by_ticker.keys())),
        "summary": base.get("summary", {}),
        "fusion_counts": counts,
        "best_fusion_opportunity": best,
        "executive_conclusion": executive,
        "top": fused_top[:30],
        "by_ticker": list(by_ticker.values()),
        "health": base.get("health", {}),
    }

@app.get("/fusion_desk")
def fusion_desk():
    return _v21_fusion_snapshot()

@app.get("/fusion_ticker/{ticker}")
def fusion_ticker(ticker: str):
    data = _v21_fusion_snapshot()
    t = str(ticker or "").upper().strip()
    rows = [r for r in data.get("top", []) if str(r.get("ticker", "")).upper() == t]
    best = rows[0] if rows else None

    return {
        "engine": "V21_TECHNICAL_OPTIONS_FUSION",
        "ticker": t,
        "status": "OK" if rows else "NO_ROWS_FOR_TICKER",
        "market_hours": data.get("market_hours"),
        "technical_snapshot_available": data.get("technical_snapshot_available"),
        "technical_tickers": data.get("technical_tickers"),
        "best": best,
        "rows": rows,
        "executive_conclusion": (
            f"{t}: mejor oportunidad {best.get('strategy')} con estado {best.get('fusion_state')} "
            f"y score combinado {best.get('combined_score')}. {best.get('fusion_action')}"
            if best else f"No hay oportunidades fusionadas para {t}."
        ),
    }

@app.get("/gpt_fusion_summary")
def gpt_fusion_summary():
    data = _v21_fusion_snapshot()
    best = data.get("best_fusion_opportunity") or {}

    compact_top = []
    for row in data.get("top", [])[:5]:
        compact_top.append({
            "ticker": row.get("ticker"),
            "strategy": row.get("strategy"),
            "decision": row.get("decision"),
            "operational_state": row.get("operational_state"),
            "technical_bias": row.get("technical_bias"),
            "technical_confirmation": row.get("technical_confirmation"),
            "strategy_technical_fit": row.get("strategy_technical_fit"),
            "score": row.get("score"),
            "technical_score": row.get("technical_score"),
            "combined_score": row.get("combined_score"),
            "fusion_state": row.get("fusion_state"),
            "can_operate": row.get("can_operate"),
            "fusion_action": row.get("fusion_action"),
        })

    return {
        "engine": "V21_TECHNICAL_OPTIONS_FUSION",
        "status": data.get("status"),
        "market_hours": data.get("market_hours"),
        "technical_snapshot_available": data.get("technical_snapshot_available"),
        "technical_tickers": data.get("technical_tickers"),
        "fusion_counts": data.get("fusion_counts"),
        "best": {
            "ticker": best.get("ticker"),
            "strategy": best.get("strategy"),
            "fusion_state": best.get("fusion_state"),
            "combined_score": best.get("combined_score"),
            "technical_bias": best.get("technical_bias"),
            "technical_confirmation": best.get("technical_confirmation"),
            "can_operate": best.get("can_operate"),
            "fusion_action": best.get("fusion_action"),
            "technical_reason": best.get("technical_reason"),
            "strategy_technical_reason": best.get("strategy_technical_reason"),
        } if best else None,
        "top_5": compact_top,
        "executive_conclusion": data.get("executive_conclusion"),
        "health": data.get("health"),
    }


# ============================================================
# SUPER ENGINE BOLSA — V21.1 TECHNICAL SNAPSHOT INGEST + STORAGE
# ============================================================

import json as _v211_json
from pathlib import Path as _v211_Path
from datetime import datetime as _v211_datetime, timezone as _v211_timezone

_V211_RUNTIME_DIR = _v211_Path("runtime")
_V211_RUNTIME_DIR.mkdir(exist_ok=True)

_V211_TECHNICAL_SNAPSHOT_PATH = _V211_RUNTIME_DIR / "technical_snapshot.json"
_V211_TECHNICAL_BY_TICKER_PATH = _V211_RUNTIME_DIR / "technical_snapshot_by_ticker.json"

TECHNICAL_SNAPSHOT_STORE = globals().get("TECHNICAL_SNAPSHOT_STORE", {})
LATEST_TECHNICAL_SNAPSHOT = globals().get("LATEST_TECHNICAL_SNAPSHOT", {})

def _v211_now():
    return _v211_datetime.now(_v211_timezone.utc).isoformat()

def _v211_safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default

def _v211_safe_bool(value, default=False):
    try:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        s = str(value).strip().lower()
        if s in ["1", "true", "yes", "y", "si", "sí"]:
            return True
        if s in ["0", "false", "no", "n"]:
            return False
        return default
    except Exception:
        return default

def _v211_load_json_file(path, default):
    try:
        p = _v211_Path(path)
        if p.exists():
            raw = p.read_text()
            if raw.strip():
                return _v211_json.loads(raw)
    except Exception:
        pass
    return default

def _v211_write_json_file(path, payload):
    try:
        p = _v211_Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_v211_json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return True
    except Exception:
        return False

def _v211_normalize_technical_payload(payload):
    """
    Acepta payloads flexibles desde TradingView, curl, Make/Zapier o JSON manual.
    Devuelve lista normalizada de snapshots técnicos.
    """
    rows = []

    if payload is None:
        return rows

    # Si llega string JSON
    if isinstance(payload, str):
        try:
            payload = _v211_json.loads(payload)
        except Exception:
            payload = {"raw_message": payload}

    # Si llega lista
    if isinstance(payload, list):
        for item in payload:
            rows.extend(_v211_normalize_technical_payload(item))
        return rows

    if not isinstance(payload, dict):
        return rows

    # Si viene envuelto
    for key in ["technical_snapshot", "snapshot", "data", "payload"]:
        if isinstance(payload.get(key), dict):
            rows.extend(_v211_normalize_technical_payload(payload.get(key)))
            return rows

    for key in ["rows", "items", "snapshots", "tickers"]:
        if isinstance(payload.get(key), list):
            for item in payload.get(key):
                rows.extend(_v211_normalize_technical_payload(item))
            return rows

    ticker = (
        payload.get("ticker")
        or payload.get("symbol")
        or payload.get("syminfo.ticker")
        or payload.get("tv_ticker")
        or payload.get("asset")
    )

    if not ticker:
        # A veces TradingView manda ticker dentro de texto
        raw = str(payload.get("raw_message") or "")
        if raw:
            parts = raw.replace(",", " ").replace("|", " ").split()
            for p in parts:
                pp = p.strip().upper()
                if pp.isalpha() and 1 <= len(pp) <= 6:
                    ticker = pp
                    break

    if not ticker:
        return rows

    ticker = str(ticker).upper().strip()

    price = (
        payload.get("price")
        or payload.get("close")
        or payload.get("last")
        or payload.get("last_price")
    )

    trend = (
        payload.get("trend")
        or payload.get("trend_label")
        or payload.get("market_trend")
        or payload.get("bias")
    )

    score = (
        payload.get("score")
        or payload.get("technical_score")
        or payload.get("setup_score")
    )

    rsi = payload.get("rsi") or payload.get("RSI")
    macd = payload.get("macd") or payload.get("MACD")
    adx = payload.get("adx") or payload.get("ADX")
    vwap_position = payload.get("vwap_position") or payload.get("vwap")
    volume_relative = payload.get("volume_relative") or payload.get("relative_volume") or payload.get("rel_volume")
    support_near = payload.get("support_near") or payload.get("near_support")
    resistance_near = payload.get("resistance_near") or payload.get("near_resistance")
    range_breakout = payload.get("range_breakout") or payload.get("breakout")
    earnings_soon = payload.get("earnings_soon") or payload.get("earnings")
    event_risk = payload.get("event_risk")

    normalized = {
        "ticker": ticker,
        "received_at": _v211_now(),
        "source": payload.get("source") or "TRADINGVIEW_WEBHOOK_V21_1",
        "price": _v211_safe_float(price, price),
        "trend": trend,
        "score": _v211_safe_float(score, score),
        "rsi": _v211_safe_float(rsi, rsi),
        "macd": _v211_safe_float(macd, macd),
        "adx": _v211_safe_float(adx, adx),
        "vwap_position": vwap_position,
        "volume_relative": _v211_safe_float(volume_relative, volume_relative),
        "support_near": _v211_safe_bool(support_near, False),
        "resistance_near": _v211_safe_bool(resistance_near, False),
        "range_breakout": _v211_safe_bool(range_breakout, False),
        "earnings_soon": _v211_safe_bool(earnings_soon, False),
        "event_risk": _v211_safe_bool(event_risk, False),
        "raw": payload,
    }

    # Clasificación flexible si TradingView manda action/señal
    signal = str(payload.get("signal") or payload.get("action") or "").upper()
    if signal and not normalized.get("trend"):
        if "BUY" in signal or "LONG" in signal or "BULL" in signal:
            normalized["trend"] = "BULLISH"
        elif "SELL" in signal or "SHORT" in signal or "BEAR" in signal:
            normalized["trend"] = "BEARISH"
        elif "NEUTRAL" in signal or "RANGE" in signal:
            normalized["trend"] = "NEUTRAL"

    rows.append(normalized)
    return rows

def _v211_load_technical_by_ticker():
    by_ticker = {}

    try:
        if isinstance(globals().get("TECHNICAL_SNAPSHOT_STORE"), dict):
            by_ticker.update(globals().get("TECHNICAL_SNAPSHOT_STORE") or {})
    except Exception:
        pass

    file_data = _v211_load_json_file(_V211_TECHNICAL_BY_TICKER_PATH, {})
    if isinstance(file_data, dict):
        by_ticker.update(file_data)

    return by_ticker

def _v211_save_technical_snapshots(rows):
    global TECHNICAL_SNAPSHOT_STORE
    global LATEST_TECHNICAL_SNAPSHOT

    by_ticker = _v211_load_technical_by_ticker()

    for row in rows:
        t = str(row.get("ticker") or "").upper().strip()
        if not t:
            continue
        by_ticker[t] = row
        LATEST_TECHNICAL_SNAPSHOT = row

    TECHNICAL_SNAPSHOT_STORE = by_ticker

    payload = {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "updated_at": _v211_now(),
        "count": len(by_ticker),
        "tickers": sorted(list(by_ticker.keys())),
        "by_ticker": by_ticker,
    }

    _v211_write_json_file(_V211_TECHNICAL_BY_TICKER_PATH, by_ticker)
    _v211_write_json_file(_V211_TECHNICAL_SNAPSHOT_PATH, payload)

    return payload

def _v211_get_technical_snapshot_store():
    by_ticker = _v211_load_technical_by_ticker()
    return {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "available": bool(by_ticker),
        "updated_at": _v211_now(),
        "count": len(by_ticker),
        "tickers": sorted(list(by_ticker.keys())),
        "by_ticker": by_ticker,
    }

# Alias que V21 puede intentar encontrar
def get_latest_technical_snapshot():
    return _v211_get_technical_snapshot_store()

def _load_technical_snapshot():
    return _v211_get_technical_snapshot_store()

def _get_latest_technical_snapshot():
    return _v211_get_technical_snapshot_store()

@app.post("/technical_snapshot")
async def technical_snapshot_ingest(request: Request):
    try:
        payload = await request.json()
    except Exception:
        try:
            raw = await request.body()
            payload = raw.decode("utf-8")
        except Exception:
            payload = {}

    rows = _v211_normalize_technical_payload(payload)
    saved = _v211_save_technical_snapshots(rows)

    return {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "status": "OK" if rows else "NO_VALID_TECHNICAL_ROWS",
        "received_rows": len(rows),
        "stored_tickers": saved.get("tickers", []),
        "stored_count": saved.get("count", 0),
        "updated_at": saved.get("updated_at"),
    }

@app.post("/webhook/technical_snapshot")
async def technical_snapshot_webhook(request: Request):
    return await technical_snapshot_ingest(request)

@app.post("/webhook/tradingview_technical")
async def tradingview_technical_webhook(request: Request):
    return await technical_snapshot_ingest(request)

@app.get("/technical_snapshot")
def technical_snapshot_get():
    return _v211_get_technical_snapshot_store()

@app.get("/technical_snapshot/{ticker}")
def technical_snapshot_ticker(ticker: str):
    data = _v211_get_technical_snapshot_store()
    t = str(ticker or "").upper().strip()
    row = (data.get("by_ticker") or {}).get(t)
    return {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "ticker": t,
        "status": "OK" if row else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": row,
        "available_tickers": data.get("tickers", []),
    }

@app.get("/technical_snapshot_health")
def technical_snapshot_health():
    data = _v211_get_technical_snapshot_store()
    return {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "status": "OK" if data.get("available") else "EMPTY",
        "available": data.get("available"),
        "count": data.get("count"),
        "tickers": data.get("tickers"),
        "path_by_ticker": str(_V211_TECHNICAL_BY_TICKER_PATH),
        "path_snapshot": str(_V211_TECHNICAL_SNAPSHOT_PATH),
    }


# ============================================================
# V21.1 FIX — SAFE TECHNICAL SNAPSHOT INGEST
# ============================================================

import json as _v211f_json
from pathlib import Path as _v211f_Path
from datetime import datetime as _v211f_datetime, timezone as _v211f_timezone

_V211F_RUNTIME = _v211f_Path("runtime")
_V211F_RUNTIME.mkdir(exist_ok=True)
_V211F_FILE = _V211F_RUNTIME / "technical_snapshot_by_ticker_safe.json"

TECHNICAL_SNAPSHOT_STORE_SAFE = globals().get("TECHNICAL_SNAPSHOT_STORE_SAFE", {})

def _v211f_now():
    return _v211f_datetime.now(_v211f_timezone.utc).isoformat()

def _v211f_load():
    try:
        if _V211F_FILE.exists():
            txt = _V211F_FILE.read_text()
            if txt.strip():
                data = _v211f_json.loads(txt)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _v211f_save(data):
    try:
        _V211F_FILE.parent.mkdir(parents=True, exist_ok=True)
        _V211F_FILE.write_text(_v211f_json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return True
    except Exception:
        return False

def _v211f_float(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default

def _v211f_bool(x, default=False):
    if isinstance(x, bool):
        return x
    if x is None:
        return default
    v = str(x).strip().lower()
    if v in ["true", "1", "yes", "y", "si", "sí"]:
        return True
    if v in ["false", "0", "no", "n"]:
        return False
    return default

def _v211f_normalize_one(payload):
    if not isinstance(payload, dict):
        return None

    ticker = payload.get("ticker") or payload.get("symbol") or payload.get("asset")
    if not ticker:
        return None

    ticker = str(ticker).upper().strip()

    trend = payload.get("trend") or payload.get("bias") or payload.get("signal") or "UNKNOWN"
    trend = str(trend).upper().strip()

    row = {
        "ticker": ticker,
        "received_at": _v211f_now(),
        "source": payload.get("source") or "TECHNICAL_SNAPSHOT_SAFE_INGEST",
        "price": _v211f_float(payload.get("price") or payload.get("close") or payload.get("last")),
        "trend": trend,
        "score": _v211f_float(payload.get("score") or payload.get("technical_score"), 0),
        "rsi": _v211f_float(payload.get("rsi")),
        "adx": _v211f_float(payload.get("adx")),
        "macd": payload.get("macd"),
        "vwap_position": payload.get("vwap_position") or payload.get("vwap"),
        "volume_relative": _v211f_float(payload.get("volume_relative") or payload.get("relative_volume")),
        "support_near": _v211f_bool(payload.get("support_near")),
        "resistance_near": _v211f_bool(payload.get("resistance_near")),
        "range_breakout": _v211f_bool(payload.get("range_breakout")),
        "event_risk": _v211f_bool(payload.get("event_risk")),
        "raw": payload,
    }

    return row

def _v211f_extract_rows(payload):
    if isinstance(payload, list):
        out = []
        for item in payload:
            row = _v211f_normalize_one(item)
            if row:
                out.append(row)
        return out

    if isinstance(payload, dict):
        for k in ["rows", "items", "tickers", "snapshots"]:
            if isinstance(payload.get(k), list):
                return _v211f_extract_rows(payload.get(k))

        row = _v211f_normalize_one(payload)
        return [row] if row else []

    return []

def _v211f_get_store():
    data = _v211f_load()
    mem = globals().get("TECHNICAL_SNAPSHOT_STORE_SAFE", {})
    if isinstance(mem, dict):
        data.update(mem)

    return {
        "engine": "V21_1_FIX_SAFE_TECHNICAL_INGEST",
        "available": bool(data),
        "count": len(data),
        "tickers": sorted(list(data.keys())),
        "by_ticker": data,
        "path": str(_V211F_FILE),
        "updated_at": _v211f_now(),
    }

# Estos aliases ayudan a que V21 pueda detectar el snapshot técnico.
def get_latest_technical_snapshot_safe():
    return _v211f_get_store()

def get_latest_technical_snapshot():
    return _v211f_get_store()

def _get_latest_technical_snapshot():
    return _v211f_get_store()

def _load_technical_snapshot():
    return _v211f_get_store()

@app.post("/technical_snapshot_ingest")
async def technical_snapshot_ingest_safe(request: Request):
    try:
        payload = await request.json()
    except Exception as e:
        return {
            "engine": "V21_1_FIX_SAFE_TECHNICAL_INGEST",
            "status": "BAD_JSON",
            "error": str(e),
        }

    rows = _v211f_extract_rows(payload)

    store = _v211f_load()

    for row in rows:
        ticker = row.get("ticker")
        if ticker:
            store[ticker] = row

    globals()["TECHNICAL_SNAPSHOT_STORE_SAFE"] = store
    globals()["TECHNICAL_SNAPSHOT_STORE"] = store
    globals()["LATEST_TECHNICAL_SNAPSHOT"] = rows[-1] if rows else {}

    saved = _v211f_save(store)

    return {
        "engine": "V21_1_FIX_SAFE_TECHNICAL_INGEST",
        "status": "OK" if rows else "NO_VALID_ROWS",
        "received_rows": len(rows),
        "stored_count": len(store),
        "stored_tickers": sorted(list(store.keys())),
        "saved_to_file": saved,
        "path": str(_V211F_FILE),
    }

@app.get("/technical_snapshot_safe")
def technical_snapshot_safe_get():
    return _v211f_get_store()

@app.get("/technical_snapshot_safe/{ticker}")
def technical_snapshot_safe_ticker(ticker: str):
    data = _v211f_get_store()
    t = str(ticker or "").upper().strip()
    row = (data.get("by_ticker") or {}).get(t)
    return {
        "engine": "V21_1_FIX_SAFE_TECHNICAL_INGEST",
        "ticker": t,
        "status": "OK" if row else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": row,
        "available_tickers": data.get("tickers", []),
    }


# ============================================================
# V21.2 — FUSION READS SAFE TECHNICAL SNAPSHOT STORE
# ============================================================

import json as _v212_json
from pathlib import Path as _v212_Path
from datetime import datetime as _v212_datetime, timezone as _v212_timezone

_V212_SAFE_TECH_FILE = _v212_Path("runtime") / "technical_snapshot_by_ticker_safe.json"
_V212_ALT_TECH_FILE = _v212_Path("runtime") / "technical_snapshot_by_ticker.json"

def _v212_now():
    return _v212_datetime.now(_v212_timezone.utc).isoformat()

def _v212_load_json(path):
    try:
        p = _v212_Path(path)
        if p.exists():
            txt = p.read_text()
            if txt.strip():
                data = _v212_json.loads(txt)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _v212_get_safe_technical_by_ticker():
    data = {}

    # 1) Prioridad: memoria safe
    try:
        mem_safe = globals().get("TECHNICAL_SNAPSHOT_STORE_SAFE", {})
        if isinstance(mem_safe, dict):
            data.update(mem_safe)
    except Exception:
        pass

    # 2) Memoria standard
    try:
        mem_std = globals().get("TECHNICAL_SNAPSHOT_STORE", {})
        if isinstance(mem_std, dict):
            data.update(mem_std)
    except Exception:
        pass

    # 3) Archivo safe
    try:
        file_safe = _v212_load_json(_V212_SAFE_TECH_FILE)
        if isinstance(file_safe, dict):
            data.update(file_safe)
    except Exception:
        pass

    # 4) Archivo alternativo
    try:
        file_alt = _v212_load_json(_V212_ALT_TECH_FILE)
        if isinstance(file_alt, dict):
            data.update(file_alt)
    except Exception:
        pass

    # Limpieza de keys
    clean = {}
    for k, v in data.items():
        try:
            t = str(k or "").upper().strip()
            if t and isinstance(v, dict):
                clean[t] = v
        except Exception:
            pass

    return clean

def _v212_latest_technical_snapshot_store():
    by_ticker = _v212_get_safe_technical_by_ticker()
    return {
        "engine": "V21_2_FUSION_READS_SAFE_TECHNICAL",
        "available": bool(by_ticker),
        "technical_snapshot_available": bool(by_ticker),
        "updated_at": _v212_now(),
        "count": len(by_ticker),
        "tickers": sorted(list(by_ticker.keys())),
        "technical_tickers": sorted(list(by_ticker.keys())),
        "by_ticker": by_ticker,
        "source": "SAFE_TECHNICAL_SNAPSHOT_STORE",
        "path_safe": str(_V212_SAFE_TECH_FILE),
        "path_alt": str(_V212_ALT_TECH_FILE),
    }

# Sobrescribimos aliases usados por V21 fusion.
def get_latest_technical_snapshot(ticker=None):
    store = _v212_latest_technical_snapshot_store()
    if ticker is None:
        return store
    return dict((store.get("by_ticker") or {}).get(str(ticker or "").upper().strip()) or {})

def _get_latest_technical_snapshot(ticker=None):
    return get_latest_technical_snapshot(ticker)

def _load_technical_snapshot():
    return _v212_latest_technical_snapshot_store()

def get_technical_snapshot_store():
    return _v212_latest_technical_snapshot_store()

def _v212_get_technical_for_ticker(ticker):
    t = str(ticker or "").upper().strip()
    store = _v212_latest_technical_snapshot_store()
    return (store.get("by_ticker") or {}).get(t)

@app.get("/technical_snapshot_fusion_health")
def technical_snapshot_fusion_health():
    store = _v212_latest_technical_snapshot_store()
    return {
        "engine": "V21_2_FUSION_READS_SAFE_TECHNICAL",
        "status": "OK" if store.get("available") else "EMPTY",
        "technical_snapshot_available": store.get("technical_snapshot_available"),
        "technical_tickers": store.get("technical_tickers"),
        "count": store.get("count"),
        "source": store.get("source"),
        "path_safe": store.get("path_safe"),
        "path_alt": store.get("path_alt"),
    }

@app.get("/technical_snapshot_fusion/{ticker}")
def technical_snapshot_fusion_ticker(ticker: str):
    t = str(ticker or "").upper().strip()
    row = _v212_get_technical_for_ticker(t)
    return {
        "engine": "V21_2_FUSION_READS_SAFE_TECHNICAL",
        "ticker": t,
        "status": "OK" if row else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": row,
        "available_tickers": _v212_latest_technical_snapshot_store().get("technical_tickers", []),
    }


# ============================================================
# V22 — UNIFIED TRADING DECISION ENGINE
# ============================================================

import json as _v22_json
from pathlib import Path as _v22_Path
from datetime import datetime as _v22_datetime, timezone as _v22_timezone

_V22_SAFE_TECH_FILE = _v22_Path("runtime") / "technical_snapshot_by_ticker_safe.json"
_V22_ALT_TECH_FILE = _v22_Path("runtime") / "technical_snapshot_by_ticker.json"
_V22_DECISION_FILE = _v22_Path("runtime") / "decision_desk_snapshot.json"
_V22_ALT_DECISION_FILE = _v22_Path("/tmp") / "decision_desk_snapshot.json"

def _v22_now():
    return _v22_datetime.now(_v22_timezone.utc).isoformat()

def _v22_load_json(path):
    try:
        p = _v22_Path(path)
        if p.exists():
            txt = p.read_text()
            if txt and txt.strip():
                data = _v22_json.loads(txt)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _v22_norm_ticker(ticker):
    return str(ticker or "").upper().strip()

def _v22_safe_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _v22_safe_int(x, default=0):
    try:
        if x is None:
            return default
        return int(float(x))
    except Exception:
        return default

def _v22_load_technical_store():
    data = {}

    # 1) Memory safe store
    try:
        mem = globals().get("TECHNICAL_SNAPSHOT_STORE_SAFE", {})
        if isinstance(mem, dict):
            data.update(mem)
    except Exception:
        pass

    # 2) Memory standard store
    try:
        mem = globals().get("TECHNICAL_SNAPSHOT_STORE", {})
        if isinstance(mem, dict):
            data.update(mem)
    except Exception:
        pass

    # 3) Safe runtime file
    try:
        file_data = _v22_load_json(_V22_SAFE_TECH_FILE)
        if isinstance(file_data, dict):
            data.update(file_data)
    except Exception:
        pass

    # 4) Alternate runtime file
    try:
        file_data = _v22_load_json(_V22_ALT_TECH_FILE)
        if isinstance(file_data, dict):
            data.update(file_data)
    except Exception:
        pass

    clean = {}
    for k, v in data.items():
        t = _v22_norm_ticker(k)
        if t and isinstance(v, dict):
            clean[t] = v

    return clean

def _v22_get_market_hours():
    # Try existing V20/V21 helper if present.
    for fn_name in [
        "_v20_market_hours_status",
        "v20_market_hours_status",
        "_get_market_hours_status",
        "get_market_hours_status",
    ]:
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                mh = fn()
                if isinstance(mh, dict):
                    return mh
        except Exception:
            pass

    # Fallback from current system status if available.
    try:
        fn = globals().get("system_status")
        if callable(fn):
            st = fn()
            if isinstance(st, dict):
                mh = st.get("market_hours")
                if isinstance(mh, dict):
                    return mh
    except Exception:
        pass

    return {
        "status": "UNKNOWN",
        "label": "Market hours unknown",
        "is_regular_market_open": False,
        "options_bidask_expected": False,
        "next_check": "Revisar próxima sesión después de 09:35 ET.",
    }

def _v22_load_decision_snapshot():
    data = {}

    # Try existing snapshot helpers.
    for fn_name in [
        "_v18_get_decision_snapshot",
        "get_decision_snapshot",
        "_get_latest_decision_snapshot",
        "_v19_get_operational_dashboard",
    ]:
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                d = fn()
                if isinstance(d, dict):
                    data.update(d)
                    break
        except Exception:
            pass

    # Try runtime files.
    if not data:
        for path in [_V22_DECISION_FILE, _V22_ALT_DECISION_FILE]:
            d = _v22_load_json(path)
            if d:
                data.update(d)
                break

    return data if isinstance(data, dict) else {}

def _v22_extract_rows_from_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return []

    candidates = []

    for key in ["top", "top_3", "rows", "opportunities", "by_ticker", "by_strategy"]:
        val = snapshot.get(key)
        if isinstance(val, list):
            candidates.extend([x for x in val if isinstance(x, dict)])

    # Sometimes summary contains top_3.
    summary = snapshot.get("summary")
    if isinstance(summary, dict):
        for key in ["top", "top_3", "rows", "opportunities"]:
            val = summary.get(key)
            if isinstance(val, list):
                candidates.extend([x for x in val if isinstance(x, dict)])

    # Best opportunity.
    for key in ["best", "best_opportunity", "next_best_action"]:
        val = snapshot.get(key)
        if isinstance(val, dict):
            candidates.append(val)
    if isinstance(summary, dict):
        for key in ["best", "best_opportunity", "next_best_action"]:
            val = summary.get(key)
            if isinstance(val, dict):
                candidates.append(val)

    # Deduplicate by rough signature.
    out = []
    seen = set()
    for r in candidates:
        t = _v22_norm_ticker(r.get("ticker") or r.get("symbol") or r.get("underlying"))
        strategy = str(r.get("strategy") or r.get("strategy_hint") or r.get("option_type") or "").upper()
        price = str(r.get("price") or r.get("mid") or r.get("premium") or "")
        decision = str(r.get("decision") or r.get("state") or r.get("fusion_state") or "")
        sig = (t, strategy, price, decision)
        if sig not in seen:
            seen.add(sig)
            out.append(r)

    return out

def _v22_get_option_rows_for_ticker(ticker):
    t = _v22_norm_ticker(ticker)
    snapshot = _v22_load_decision_snapshot()
    rows = _v22_extract_rows_from_snapshot(snapshot)
    filtered = []
    for r in rows:
        rt = _v22_norm_ticker(r.get("ticker") or r.get("symbol") or r.get("underlying"))
        if rt == t:
            filtered.append(r)
    return filtered, snapshot

def _v22_best_row(rows):
    if not rows:
        return None

    def score_row(r):
        score = _v22_safe_float(r.get("combined_score"), None)
        if score is None:
            score = _v22_safe_float(r.get("score"), None)
        if score is None:
            score = _v22_safe_float(r.get("technical_score"), 0)
        decision = str(r.get("decision") or r.get("fusion_state") or r.get("state") or "").upper()
        can = bool(r.get("can_operate") is True)
        bonus = 0
        if can:
            bonus += 1000
        if "ENTRY" in decision or decision == "OPERAR":
            bonus += 500
        if "RADAR" in decision:
            bonus += 200
        return bonus + float(score or 0)

    try:
        return sorted(rows, key=score_row, reverse=True)[0]
    except Exception:
        return rows[0]

def _v22_technical_bias_from_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return "UNKNOWN"

    trend = str(snapshot.get("trend") or snapshot.get("bias") or snapshot.get("technical_bias") or "").upper().strip()
    score = _v22_safe_float(snapshot.get("score") or snapshot.get("technical_score"), None)
    rsi = _v22_safe_float(snapshot.get("rsi"), None)
    vwap = str(snapshot.get("vwap_position") or snapshot.get("vwap") or "").lower()

    if trend in ["BULLISH", "ALCISTA", "UP", "LONG"]:
        return "BULLISH"
    if trend in ["BEARISH", "BAJISTA", "DOWN", "SHORT"]:
        return "BEARISH"
    if trend in ["NEUTRAL", "RANGE", "SIDEWAYS"]:
        return "NEUTRAL"

    if score is not None:
        if score >= 70:
            return "BULLISH"
        if score <= 30:
            return "BEARISH"

    if rsi is not None and vwap:
        if rsi >= 50 and vwap == "above":
            return "BULLISH"
        if rsi <= 45 and vwap == "below":
            return "BEARISH"

    return "UNKNOWN"

def _v22_strategy_from_row(row, technical_bias="UNKNOWN"):
    if isinstance(row, dict):
        for key in ["strategy", "strategy_hint", "best_strategy", "option_strategy"]:
            val = row.get(key)
            if val:
                return str(val).upper().strip()
        opt_type = str(row.get("option_type") or row.get("right") or "").upper()
        if opt_type in ["PUT", "P"]:
            return "NAKED_PUT"
        if opt_type in ["CALL", "C"]:
            return "COVERED_CALL"

    if technical_bias == "BULLISH":
        return "NAKED_PUT"
    if technical_bias == "BEARISH":
        return "COVERED_CALL"
    return "UNKNOWN"

def _v22_is_strategy_aligned(strategy, technical_bias):
    s = str(strategy or "").upper()
    b = str(technical_bias or "").upper()

    if b == "UNKNOWN" or s == "UNKNOWN":
        return None

    if b == "BULLISH" and s in ["NAKED_PUT", "PUT_CREDIT_SPREAD", "BULL_PUT_SPREAD"]:
        return True

    if b == "BEARISH" and s in ["COVERED_CALL", "CALL_CREDIT_SPREAD", "BEAR_CALL_SPREAD"]:
        return True

    if b == "NEUTRAL" and s in ["IRON_CONDOR", "COVERED_CALL", "NAKED_PUT"]:
        return True

    return False

def _v22_main_blocker(market_hours, best_row, technical_snapshot, strategy_alignment):
    mh_status = str((market_hours or {}).get("status") or "").upper()
    options_ok = bool((market_hours or {}).get("options_bidask_expected") is True)

    if mh_status in ["WEEKEND_CLOSED", "HOLIDAY_CLOSED"]:
        return "MARKET_CLOSED"
    if not options_ok:
        return "OPTIONS_MARKET_NOT_RELIABLE"

    if not technical_snapshot:
        return "NO_TECHNICAL_SNAPSHOT"

    if strategy_alignment is False:
        return "TECHNICAL_CONFLICT"

    if not best_row:
        return "WAIT_OPTIONS_DATA"

    missing = best_row.get("missing_confirmations") or best_row.get("missing_data") or []
    if isinstance(missing, str):
        missing = [missing]
    missing_text = " ".join([str(x).upper() for x in missing])

    if "GREEK" in missing_text or "GREEKS" in missing_text:
        return "WAIT_GREEKS"
    if "BID" in missing_text or "ASK" in missing_text or "SPREAD" in missing_text:
        return "WAIT_LIQUIDITY"

    quality = str(best_row.get("data_quality") or best_row.get("quality") or "").upper()
    if "NO_BIDASK" in quality or "PRICE_ONLY" in quality:
        return "WAIT_LIQUIDITY"

    return None

def _v22_final_state(market_hours, best_row, technical_snapshot, technical_bias, strategy, strategy_alignment):
    blocker = _v22_main_blocker(market_hours, best_row, technical_snapshot, strategy_alignment)

    if blocker == "MARKET_CLOSED":
        return "WAIT_MARKET_OPEN"
    if blocker == "OPTIONS_MARKET_NOT_RELIABLE":
        return "WAIT_MARKET_OPEN"
    if blocker == "NO_TECHNICAL_SNAPSHOT":
        return "WAIT_TECHNICAL_DATA"
    if blocker == "TECHNICAL_CONFLICT":
        return "TECHNICAL_CONFLICT"
    if blocker == "WAIT_OPTIONS_DATA":
        return "WAIT_OPTIONS_DATA"
    if blocker == "WAIT_GREEKS":
        return "WAIT_GREEKS"
    if blocker == "WAIT_LIQUIDITY":
        return "WAIT_LIQUIDITY"

    if not best_row and technical_snapshot:
        return "RADAR_TECH_OK"

    can_row = bool(isinstance(best_row, dict) and best_row.get("can_operate") is True)
    decision = str((best_row or {}).get("decision") or (best_row or {}).get("fusion_state") or "").upper()

    if can_row or "ENTRY" in decision or decision == "OPERAR":
        return "ENTRY_READY"

    if technical_snapshot and best_row:
        if strategy_alignment is True:
            return "RADAR_MIXED"
        return "RADAR_OPTIONS_OK"

    if best_row:
        return "RADAR_OPTIONS_OK"

    return "NO_DATA"

def _v22_can_operate(final_state):
    return str(final_state or "").upper() == "ENTRY_READY"

def _v22_action_text(final_state, blocker, market_hours, technical_bias, strategy):
    next_check = (market_hours or {}).get("next_check") or "Revisar próxima ventana operativa."

    if final_state == "ENTRY_READY":
        return "Entrada potencial lista. Validar tamaño, riesgo, spread y confirmación final antes de ejecutar."
    if final_state == "WAIT_MARKET_OPEN":
        return f"No operar ahora. Esperar ventana confiable de mercado/opciones. {next_check}"
    if final_state == "WAIT_LIQUIDITY":
        return "No operar todavía. Confirmar bid/ask y spread real en opciones antes de considerar entrada."
    if final_state == "WAIT_GREEKS":
        return "No operar todavía. Esperar griegas completas para validar delta, IV y riesgo."
    if final_state == "WAIT_OPTIONS_DATA":
        return "No operar todavía. Hay lectura técnica, pero faltan candidatos/opciones completas."
    if final_state == "WAIT_TECHNICAL_DATA":
        return "No operar todavía. Falta snapshot técnico para confirmar dirección y contexto."
    if final_state == "TECHNICAL_CONFLICT":
        return "No operar. La estrategia de opciones no está alineada con el sesgo técnico actual."
    if final_state in ["RADAR_TECH_OK", "RADAR_OPTIONS_OK", "RADAR_MIXED"]:
        return "Mantener en radar. Aún no es entrada operable; esperar confirmaciones completas."
    return "Sin decisión operativa. Revisar datos técnicos, opciones y estado de mercado."

def _v22_severity(final_state):
    if final_state == "ENTRY_READY":
        return "green"
    if final_state in ["RADAR_TECH_OK", "RADAR_OPTIONS_OK", "RADAR_MIXED"]:
        return "amber"
    if final_state in ["WAIT_MARKET_OPEN", "WAIT_LIQUIDITY", "WAIT_GREEKS", "WAIT_OPTIONS_DATA", "WAIT_TECHNICAL_DATA"]:
        return "gray"
    if final_state in ["TECHNICAL_CONFLICT", "BLOCKED"]:
        return "red"
    return "gray"

def _v22_build_trade_decision(ticker):
    t = _v22_norm_ticker(ticker)
    tech_store = _v22_load_technical_store()
    technical_snapshot = tech_store.get(t)
    technical_available = bool(technical_snapshot)

    rows, decision_snapshot = _v22_get_option_rows_for_ticker(t)
    best_row = _v22_best_row(rows)

    market_hours = _v22_get_market_hours()
    technical_bias = _v22_technical_bias_from_snapshot(technical_snapshot)
    technical_score = _v22_safe_float((technical_snapshot or {}).get("score") or (technical_snapshot or {}).get("technical_score"), None)

    strategy = _v22_strategy_from_row(best_row, technical_bias)
    strategy_alignment = _v22_is_strategy_aligned(strategy, technical_bias)

    final_state = _v22_final_state(
        market_hours=market_hours,
        best_row=best_row,
        technical_snapshot=technical_snapshot,
        technical_bias=technical_bias,
        strategy=strategy,
        strategy_alignment=strategy_alignment,
    )

    blocker = _v22_main_blocker(market_hours, best_row, technical_snapshot, strategy_alignment)
    can_operate = _v22_can_operate(final_state)
    action = _v22_action_text(final_state, blocker, market_hours, technical_bias, strategy)

    options_score = None
    if isinstance(best_row, dict):
        options_score = _v22_safe_float(best_row.get("combined_score"), None)
        if options_score is None:
            options_score = _v22_safe_float(best_row.get("score"), None)

    executive_summary = (
        f"{t}: estado {final_state}. "
        f"Sesgo técnico {technical_bias}"
        + (f" con score {technical_score:g}" if technical_score is not None else "")
        + f". Estrategia sugerida/observada: {strategy}. "
        + action
    )

    return {
        "engine": "V22_UNIFIED_TRADING_DECISION_ENGINE",
        "generated_at": _v22_now(),
        "ticker": t,
        "status": "OK",
        "final_state": final_state,
        "decision": final_state,
        "can_operate": can_operate,
        "severity": _v22_severity(final_state),
        "main_blocker": blocker,
        "action": action,
        "executive_summary": executive_summary,

        "technical": {
            "available": technical_available,
            "bias": technical_bias,
            "score": technical_score,
            "snapshot": technical_snapshot,
            "available_tickers": sorted(list(tech_store.keys())),
        },

        "options": {
            "rows_found": len(rows),
            "best_strategy": strategy,
            "strategy_alignment": strategy_alignment,
            "best_row": best_row,
            "options_score": options_score,
            "rows": rows[:10],
        },

        "market_hours": market_hours,

        "diagnostics": {
            "technical_snapshot_available": technical_available,
            "options_rows_found": len(rows),
            "decision_snapshot_available": bool(decision_snapshot),
            "safe_technical_file": str(_V22_SAFE_TECH_FILE),
            "decision_file": str(_V22_DECISION_FILE),
        }
    }

def _v22_default_tickers():
    tickers = set()
    try:
        tickers.update(_v22_load_technical_store().keys())
    except Exception:
        pass

    try:
        snap = _v22_load_decision_snapshot()
        rows = _v22_extract_rows_from_snapshot(snap)
        for r in rows:
            t = _v22_norm_ticker(r.get("ticker") or r.get("symbol") or r.get("underlying"))
            if t:
                tickers.add(t)
    except Exception:
        pass

    if not tickers:
        tickers.update(["QQQ", "SPY", "NVDA", "TSLA", "NFLX", "META", "TLT"])

    return sorted(list(tickers))

# LEGACY COMPATIBILITY ONLY: keep V22 routes stable for older clients.
@app.get("/v22_trade_decision/{ticker}")
def v22_trade_decision(ticker: str):
    return _annotate_legacy_response(
        _v22_build_trade_decision(ticker),
        "V22_UNIFIED_TRADING_DECISION_ENGINE",
        endpoints=["/v22_trade_decision/{ticker}"],
    )

@app.get("/gpt_trade_decision/{ticker}")
def gpt_trade_decision(ticker: str):
    d = _v22_build_trade_decision(ticker)
    return _annotate_legacy_response({
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "technical_bias": (d.get("technical") or {}).get("bias"),
        "technical_score": (d.get("technical") or {}).get("score"),
        "technical_available": (d.get("technical") or {}).get("available"),
        "options_strategy": (d.get("options") or {}).get("best_strategy"),
        "options_score": (d.get("options") or {}).get("options_score"),
        "options_rows_found": (d.get("options") or {}).get("rows_found"),
        "market_hours": d.get("market_hours"),
        "engine": d.get("engine"),
        "generated_at": d.get("generated_at"),
    }, "V22_UNIFIED_TRADING_DECISION_ENGINE", endpoints=["/gpt_trade_decision/{ticker}"])

@app.get("/v22_trade_summary")
def v22_trade_summary():
    tickers = _v22_default_tickers()
    decisions = [_v22_build_trade_decision(t) for t in tickers]

    counts = {}
    for d in decisions:
        state = d.get("final_state") or "UNKNOWN"
        counts[state] = counts.get(state, 0) + 1

    entry_ready = [d for d in decisions if d.get("final_state") == "ENTRY_READY"]
    radar = [d for d in decisions if str(d.get("final_state") or "").startswith("RADAR")]
    waiting = [d for d in decisions if str(d.get("final_state") or "").startswith("WAIT")]
    conflicts = [d for d in decisions if d.get("final_state") in ["TECHNICAL_CONFLICT", "BLOCKED"]]

    def rank(d):
        tech_score = (d.get("technical") or {}).get("score") or 0
        opt_score = (d.get("options") or {}).get("options_score") or 0
        state = d.get("final_state")
        bonus = 0
        if state == "ENTRY_READY":
            bonus += 1000
        elif str(state or "").startswith("RADAR"):
            bonus += 500
        return bonus + float(tech_score or 0) + float(opt_score or 0)

    ranked = sorted(decisions, key=rank, reverse=True)
    best = ranked[0] if ranked else None

    return _annotate_legacy_response({
        "engine": "V22_UNIFIED_TRADING_DECISION_ENGINE",
        "generated_at": _v22_now(),
        "status": "OK",
        "tickers": tickers,
        "counts": counts,
        "best": {
            "ticker": best.get("ticker"),
            "state": best.get("final_state"),
            "can_operate": best.get("can_operate"),
            "summary": best.get("executive_summary"),
        } if best else None,
        "entry_ready_count": len(entry_ready),
        "radar_count": len(radar),
        "waiting_count": len(waiting),
        "conflict_count": len(conflicts),
        "top": [
            {
                "ticker": d.get("ticker"),
                "state": d.get("final_state"),
                "can_operate": d.get("can_operate"),
                "technical_bias": (d.get("technical") or {}).get("bias"),
                "technical_score": (d.get("technical") or {}).get("score"),
                "strategy": (d.get("options") or {}).get("best_strategy"),
                "options_score": (d.get("options") or {}).get("options_score"),
                "blocker": d.get("main_blocker"),
                "action": d.get("action"),
            }
            for d in ranked[:10]
        ],
        "market_hours": _v22_get_market_hours(),
    }, "V22_UNIFIED_TRADING_DECISION_ENGINE", endpoints=["/v22_trade_summary", "/gpt_trade_summary"])

@app.get("/gpt_trade_summary")
def gpt_trade_summary():
    return v22_trade_summary()

@app.get("/v22_system_status")
def v22_system_status():
    tech_store = _v22_load_technical_store()
    decision_snapshot = _v22_load_decision_snapshot()
    rows = _v22_extract_rows_from_snapshot(decision_snapshot)
    mh = _v22_get_market_hours()

    return _annotate_legacy_response({
        "engine": "V22_UNIFIED_TRADING_DECISION_ENGINE",
        "generated_at": _v22_now(),
        "status": "OK",
        "technical_snapshot_available": bool(tech_store),
        "technical_tickers": sorted(list(tech_store.keys())),
        "technical_count": len(tech_store),
        "decision_snapshot_available": bool(decision_snapshot),
        "option_rows_detected": len(rows),
        "market_hours": mh,
        "endpoints": {
            "v22_trade_summary": "/v22_trade_summary",
            "v22_trade_decision_example": "/v22_trade_decision/QQQ",
            "gpt_trade_summary": "/gpt_trade_summary",
            "gpt_trade_decision_example": "/gpt_trade_decision/QQQ",
        }
    }, "V22_UNIFIED_TRADING_DECISION_ENGINE", endpoints=["/v22_system_status"])


# === V22.1 SNAPSHOT NORMALIZER + UNIFIED DECISION READER ===

from pathlib import Path as _V22Path
import json as _v22_json
from datetime import datetime as _v22_dt
from zoneinfo import ZoneInfo as _V22ZoneInfo

V22_1_ENGINE = "V22_1_SNAPSHOT_NORMALIZER"

V22_TECH_FILES = [
    "runtime/technical_snapshot_by_ticker_safe.json",
    "runtime/technical_snapshot_by_ticker.json",
    "technical_snapshot_by_ticker_safe.json",
    "technical_snapshot_by_ticker.json",
]

V22_DECISION_FILES = [
    "runtime/decision_desk_snapshot.json",
    "runtime/decision_snapshot.json",
    "runtime/v18_decision_snapshot.json",
    "runtime/v18_decision_desk_snapshot.json",
    "decision_desk_snapshot.json",
    "decision_snapshot.json",
]


def _v22_safe_load_json(path: str):
    try:
        fp = _V22Path(path)
        if not fp.exists():
            return None
        raw = fp.read_text().strip()
        if not raw:
            return None
        return _v22_json.loads(raw)
    except Exception:
        return None


def _v22_find_first_json(paths):
    for path in paths:
        data = _v22_safe_load_json(path)
        if data is not None:
            return path, data
    return None, None


def _v22_normalize_ticker(ticker: str):
    return str(ticker or "").strip().upper()


def _v22_extract_snapshot_payload(obj):
    """
    Acepta estructuras como:
    {"QQQ": {"trend": "BULLISH"}}
    {"QQQ": {"snapshot": {"trend": "BULLISH"}}}
    {"ticker": "QQQ", "snapshot": {...}}
    {"snapshot": {"ticker": "QQQ", ...}}
    """
    if not isinstance(obj, dict):
        return {}

    if isinstance(obj.get("snapshot"), dict):
        snap = obj.get("snapshot")
        merged = dict(obj)
        merged.update(snap)
        return merged

    if isinstance(obj.get("raw"), dict):
        raw = obj.get("raw")
        merged = dict(obj)
        merged.update(raw)
        return merged

    return obj


def _v22_get_technical_snapshot(ticker: str):
    ticker = _v22_normalize_ticker(ticker)
    path, data = _v22_find_first_json(V22_TECH_FILES)

    out = {
        "available": False,
        "path": path,
        "available_tickers": [],
        "ticker": ticker,
        "snapshot": None,
        "bias": "UNKNOWN",
        "score": None,
        "trend": "UNKNOWN",
        "reason": "No technical snapshot available",
    }

    if data is None:
        return out

    if isinstance(data, dict):
        out["available_tickers"] = list(data.keys())

        candidate = None

        if ticker in data:
            candidate = data.get(ticker)
        elif data.get("ticker") == ticker:
            candidate = data
        elif isinstance(data.get("snapshot"), dict) and data.get("snapshot", {}).get("ticker") == ticker:
            candidate = data.get("snapshot")

        if candidate is None:
            # fallback: buscar por ticker interno en valores
            for k, v in data.items():
                if isinstance(v, dict):
                    payload = _v22_extract_snapshot_payload(v)
                    if _v22_normalize_ticker(payload.get("ticker") or k) == ticker:
                        candidate = v
                        break

        if candidate is not None:
            payload = _v22_extract_snapshot_payload(candidate)
            trend = str(payload.get("trend") or payload.get("bias") or payload.get("technical_bias") or "UNKNOWN").upper()
            score = payload.get("score", payload.get("technical_score", payload.get("confidence")))

            bias = trend
            if trend in ["BULL", "BULLISH", "ALCISTA", "UP"]:
                bias = "BULLISH"
            elif trend in ["BEAR", "BEARISH", "BAJISTA", "DOWN"]:
                bias = "BEARISH"
            elif trend in ["NEUTRAL", "SIDEWAYS", "RANGE", "LATERAL"]:
                bias = "NEUTRAL"

            out.update({
                "available": True,
                "snapshot": payload,
                "bias": bias,
                "trend": trend,
                "score": score,
                "reason": "Technical snapshot loaded",
            })
            return out

    return out


def _v22_extract_rows_from_decision_snapshot(data):
    if data is None:
        return []

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if isinstance(data, dict):
        for key in ["rows", "top", "top_5", "opportunities", "items", "data"]:
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]

        summary = data.get("summary")
        if isinstance(summary, dict):
            for key in ["top", "top_5", "rows", "opportunities", "items"]:
                val = summary.get(key)
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]

        by_ticker = data.get("by_ticker")
        if isinstance(by_ticker, dict):
            rows = []
            for tk, payload in by_ticker.items():
                if isinstance(payload, dict):
                    best = payload.get("best")
                    if isinstance(best, dict):
                        best = dict(best)
                        best.setdefault("ticker", tk)
                        rows.append(best)
                    nested = payload.get("rows")
                    if isinstance(nested, list):
                        for r in nested:
                            if isinstance(r, dict):
                                rr = dict(r)
                                rr.setdefault("ticker", tk)
                                rows.append(rr)
            return rows

    return []


def _v22_get_decision_snapshot():
    path, data = _v22_find_first_json(V22_DECISION_FILES)
    rows = _v22_extract_rows_from_decision_snapshot(data)
    return {
        "available": data is not None,
        "path": path,
        "raw": data,
        "rows": rows,
        "rows_found": len(rows),
    }


def _v22_market_hours_state():
    try:
        now = _v22_dt.now(_V22ZoneInfo("America/New_York"))
        weekday = now.weekday()
        minutes = now.hour * 60 + now.minute

        if weekday >= 5:
            return {
                "status": "WEEKEND_CLOSED",
                "label": "Mercado cerrado por fin de semana",
                "is_regular_market_open": False,
                "options_bidask_expected": False,
                "new_york_time": now.isoformat(),
                "next_check": "Próxima sesión hábil después de 09:35 ET.",
            }

        regular_open = 9 * 60 + 30
        reliable_options = 9 * 60 + 35
        regular_close = 16 * 60

        if minutes < regular_open:
            return {
                "status": "PRE_MARKET",
                "label": "Pre-market: opciones todavía no confiables",
                "is_regular_market_open": False,
                "options_bidask_expected": False,
                "new_york_time": now.isoformat(),
                "next_check": "Revisar después de 09:35 ET.",
            }

        if regular_open <= minutes < reliable_options:
            return {
                "status": "MARKET_OPEN_NOT_LIQUID_YET",
                "label": "Mercado recién abierto: esperar bid/ask confiable",
                "is_regular_market_open": True,
                "options_bidask_expected": False,
                "new_york_time": now.isoformat(),
                "next_check": "Revisar después de 09:35 ET.",
            }

        if reliable_options <= minutes < regular_close:
            return {
                "status": "REGULAR_MARKET_OPEN",
                "label": "Mercado regular abierto",
                "is_regular_market_open": True,
                "options_bidask_expected": True,
                "new_york_time": now.isoformat(),
                "next_check": "Monitoreo activo.",
            }

        return {
            "status": "AFTER_HOURS",
            "label": "After-hours: opciones no confiables",
            "is_regular_market_open": False,
            "options_bidask_expected": False,
            "new_york_time": now.isoformat(),
            "next_check": "Revisar próxima sesión después de 09:35 ET.",
        }
    except Exception as e:
        return {
            "status": "UNKNOWN",
            "label": f"Market hours unavailable: {e}",
            "is_regular_market_open": False,
            "options_bidask_expected": False,
            "new_york_time": None,
            "next_check": "Validar horario manualmente.",
        }


def _v22_score_row(row):
    try:
        return float(row.get("combined_score", row.get("score", row.get("master_score", 0))) or 0)
    except Exception:
        return 0.0


def _v22_row_ticker(row):
    return _v22_normalize_ticker(row.get("ticker") or row.get("symbol") or row.get("underlying") or row.get("underlying_symbol"))


def _v22_row_strategy(row):
    return str(row.get("strategy") or row.get("strategy_hint") or row.get("option_type") or row.get("setup") or "UNKNOWN").upper()


def _v22_rows_for_ticker(rows, ticker):
    ticker = _v22_normalize_ticker(ticker)
    return [r for r in rows if _v22_row_ticker(r) == ticker]


def _v22_best_row(rows):
    if not rows:
        return None
    return sorted(rows, key=_v22_score_row, reverse=True)[0]


def _v22_unified_decision(ticker: str):
    ticker = _v22_normalize_ticker(ticker)
    tech = _v22_get_technical_snapshot(ticker)
    decision = _v22_get_decision_snapshot()
    market = _v22_market_hours_state()

    rows = _v22_rows_for_ticker(decision["rows"], ticker)
    best = _v22_best_row(rows)

    technical_bias = tech.get("bias", "UNKNOWN")
    technical_score = tech.get("score")
    options_rows_found = len(rows)
    decision_snapshot_available = decision.get("available", False)
    technical_snapshot_available = tech.get("available", False)

    final_state = "NO_DATA"
    main_blocker = None
    can_operate = False
    severity = "gray"
    action = "No operar. Faltan datos suficientes."
    decision_label = "NO_DATA"

    if not market.get("options_bidask_expected"):
        final_state = "WAIT_MARKET_OPEN"
        decision_label = "WAIT_MARKET_OPEN"
        main_blocker = "OPTIONS_MARKET_NOT_RELIABLE"
        severity = "gray"
        action = f"No operar ahora. Esperar ventana confiable de mercado/opciones. {market.get('next_check')}"
    elif not technical_snapshot_available and not decision_snapshot_available:
        final_state = "NO_SNAPSHOTS"
        decision_label = "WAIT_DATA"
        main_blocker = "NO_TECHNICAL_OR_OPTIONS_SNAPSHOT"
        severity = "red"
        action = "No operar. Falta snapshot técnico y snapshot de opciones."
    elif not technical_snapshot_available:
        final_state = "WAIT_TECHNICAL"
        decision_label = "WAIT_DATA"
        main_blocker = "NO_TECHNICAL_SNAPSHOT"
        severity = "orange"
        action = "No operar. Falta confirmación técnica."
    elif not decision_snapshot_available or options_rows_found == 0:
        final_state = "WAIT_OPTIONS"
        decision_label = "WAIT_DATA"
        main_blocker = "NO_OPTIONS_DECISION_ROWS"
        severity = "orange"
        action = "No operar. Falta snapshot de opciones/decision desk."
    else:
        best_strategy = _v22_row_strategy(best)
        best_score = _v22_score_row(best)

        strategy_is_bullish = best_strategy in ["NAKED_PUT", "PUT", "BULL_PUT", "BULL_PUT_SPREAD", "CSP"]
        strategy_is_bearish = best_strategy in ["COVERED_CALL", "CALL", "BEAR_CALL", "BEAR_CALL_SPREAD"]

        technical_supports_strategy = (
            technical_bias == "BULLISH" and strategy_is_bullish
        ) or (
            technical_bias == "BEARISH" and strategy_is_bearish
        ) or (
            technical_bias == "NEUTRAL"
        )

        if technical_bias == "UNKNOWN":
            final_state = "RADAR_TECH_UNKNOWN"
            decision_label = "RADAR"
            main_blocker = "TECHNICAL_BIAS_UNKNOWN"
            severity = "orange"
            action = "Mantener en radar. Falta interpretar sesgo técnico con claridad."
        elif not technical_supports_strategy:
            final_state = "TECHNICAL_CONFLICT"
            decision_label = "WAIT_DATA"
            main_blocker = "TECHNICAL_STRATEGY_CONFLICT"
            severity = "red"
            action = f"No operar. Sesgo técnico {technical_bias} no confirma estrategia {best_strategy}."
        elif best_score >= 85:
            final_state = "ENTRY_CONFIRMED"
            decision_label = "ENTRY_CONFIRMED"
            can_operate = True
            severity = "green"
            action = f"Entrada candidata confirmada: {ticker} / {best_strategy}. Validar manualmente spread, liquidez, tamaño y riesgo antes de operar."
        elif best_score >= 60:
            final_state = "RADAR_TECH_OK"
            decision_label = "RADAR"
            severity = "orange"
            action = f"Mantener en radar: {ticker} / {best_strategy}. Técnica acompaña, pero score todavía no confirma entrada."
        else:
            final_state = "LOW_PRIORITY"
            decision_label = "LOW_PRIORITY"
            severity = "gray"
            action = "No operar. Oportunidad de baja prioridad."

    return {
        "engine": V22_1_ENGINE,
        "generated_at": _v22_dt.utcnow().isoformat() + "+00:00",
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision_label,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": main_blocker,
        "action": action,
        "executive_summary": f"{ticker}: estado {final_state}. Sesgo técnico {technical_bias}. {action}",
        "technical": {
            "available": technical_snapshot_available,
            "path": tech.get("path"),
            "bias": technical_bias,
            "trend": tech.get("trend"),
            "score": technical_score,
            "available_tickers": tech.get("available_tickers", []),
            "snapshot": tech.get("snapshot"),
        },
        "options": {
            "available": decision_snapshot_available,
            "path": decision.get("path"),
            "rows_found_for_ticker": options_rows_found,
            "total_rows_found": decision.get("rows_found", 0),
            "best": best,
            "rows": rows[:25],
        },
        "market_hours": market,
        "diagnostics": {
            "technical_snapshot_available": technical_snapshot_available,
            "decision_snapshot_available": decision_snapshot_available,
            "options_rows_found": options_rows_found,
            "safe_technical_files": V22_TECH_FILES,
            "decision_files": V22_DECISION_FILES,
        },
    }

# LEGACY COMPATIBILITY ONLY: keep V22.1 routes stable for older clients.
@app.get("/v22_1_trade_decision/{ticker}")
def v22_1_trade_decision(ticker: str):
    return _annotate_legacy_response(
        _v22_unified_decision(ticker),
        "V22_1_SNAPSHOT_NORMALIZER_UNIFIED_READER",
        endpoints=["/v22_1_trade_decision/{ticker}"],
    )


@app.get("/v22_1_system_status")
def v22_1_system_status():
    tech_path, tech_data = _v22_find_first_json(V22_TECH_FILES)
    dec = _v22_get_decision_snapshot()
    market = _v22_market_hours_state()

    technical_tickers = []
    if isinstance(tech_data, dict):
        technical_tickers = list(tech_data.keys())

    return _annotate_legacy_response({
        "engine": V22_1_ENGINE,
        "status": "OK",
        "generated_at": _v22_dt.utcnow().isoformat() + "+00:00",
        "technical_snapshot_available": tech_data is not None,
        "technical_snapshot_path": tech_path,
        "technical_tickers": technical_tickers,
        "decision_snapshot_available": dec.get("available"),
        "decision_snapshot_path": dec.get("path"),
        "decision_rows_found": dec.get("rows_found"),
        "market_hours": market,
        "endpoints": {
            "v22_1_trade_decision_example": "/v22_1_trade_decision/QQQ",
            "v22_1_system_status": "/v22_1_system_status",
        },
    }, "V22_1_SNAPSHOT_NORMALIZER_UNIFIED_READER", endpoints=["/v22_1_system_status"])
# === END V22.1 SNAPSHOT NORMALIZER + UNIFIED DECISION READER ===


# ============================================================
# V22.2 REMOTE SNAPSHOT SYNC — SERVER INGEST + STORE
# ============================================================

import json as _v22_2_json
from pathlib import Path as _v22_2_Path
from datetime import datetime as _v22_2_datetime, timezone as _v22_2_timezone

_V22_2_RUNTIME_DIR = _v22_2_Path("runtime")
_V22_2_RUNTIME_DIR.mkdir(exist_ok=True)

_V22_2_TECH_FILE = _V22_2_RUNTIME_DIR / "technical_snapshot_by_ticker_safe.json"
_V22_2_DECISION_FILE = _V22_2_RUNTIME_DIR / "decision_desk_snapshot.json"
_V22_2_UNIFIED_FILE = _V22_2_RUNTIME_DIR / "v22_2_unified_remote_snapshot.json"

def _v22_2_now_iso():
    return _v22_2_datetime.now(_v22_2_timezone.utc).isoformat()

def _v22_2_safe_read_json(path, default):
    try:
        if path.exists():
            return _v22_2_json.loads(path.read_text())
    except Exception:
        pass
    return default

def _v22_2_safe_write_json(path, payload):
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(_v22_2_json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    except Exception:
        return False

def _v22_2_extract_ticker(payload):
    try:
        ticker = payload.get("ticker")
        if not ticker and isinstance(payload.get("snapshot"), dict):
            ticker = payload["snapshot"].get("ticker")
        if not ticker and isinstance(payload.get("technical"), dict):
            ticker = payload["technical"].get("ticker")
        return str(ticker or "").upper().strip()
    except Exception:
        return ""

def _v22_2_normalize_technical_payload(payload):
    ticker = _v22_2_extract_ticker(payload)
    if not ticker:
        ticker = "UNKNOWN"

    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
    if isinstance(payload.get("technical"), dict):
        snapshot = payload.get("technical")

    snapshot = dict(snapshot or {})
    snapshot["ticker"] = str(snapshot.get("ticker") or ticker).upper()
    snapshot["received_at"] = _v22_2_now_iso()
    snapshot["source"] = snapshot.get("source") or payload.get("source") or "REMOTE_V22_2"

    return ticker, snapshot

def _v22_2_normalize_decision_payload(payload):
    data = dict(payload or {})
    data["received_at"] = _v22_2_now_iso()
    data["source"] = data.get("source") or "REMOTE_V22_2"
    return data

@app.post("/v22_2_ingest_technical_snapshot")
def v22_2_ingest_technical_snapshot(payload: dict):
    ticker, snapshot = _v22_2_normalize_technical_payload(payload)

    store = _v22_2_safe_read_json(_V22_2_TECH_FILE, {})
    if not isinstance(store, dict):
        store = {}

    store[ticker] = snapshot
    ok = _v22_2_safe_write_json(_V22_2_TECH_FILE, store)
    canonical_saved = _v22_2_sync_technical_to_canonical(ticker, snapshot)

    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "type": "technical",
        "status": "OK" if ok else "WRITE_FAILED",
        "ticker": ticker,
        "technical_snapshot_available": bool(store),
        "technical_tickers": sorted(list(store.keys())),
        "path": str(_V22_2_TECH_FILE),
        "received_at": snapshot.get("received_at"),
        "canonical_stored_file": str(_V28_MASTER_FILE),
        "canonical_alias_file": str(_V28_ALIAS_V25_FILE),
        "canonical_technical_available": canonical_saved.get("technical_available"),
        "canonical_tickers_detected": canonical_saved.get("tickers_detected"),
    }

@app.post("/v22_2_ingest_decision_snapshot")
def v22_2_ingest_decision_snapshot(payload: dict):
    data = _v22_2_normalize_decision_payload(payload)
    ok = _v22_2_safe_write_json(_V22_2_DECISION_FILE, data)
    canonical_saved = _v22_2_sync_decision_to_canonical(data)

    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "type": "decision",
        "status": "OK" if ok else "WRITE_FAILED",
        "decision_snapshot_available": ok,
        "rows_found": len(data.get("rows") or data.get("top") or []),
        "path": str(_V22_2_DECISION_FILE),
        "received_at": data.get("received_at"),
        "canonical_stored_file": str(_V28_MASTER_FILE),
        "canonical_alias_file": str(_V28_ALIAS_V25_FILE),
        "canonical_rows_found": canonical_saved.get("rows_found"),
        "canonical_tickers_detected": canonical_saved.get("tickers_detected"),
    }

@app.post("/v22_2_ingest_unified_snapshot")
def v22_2_ingest_unified_snapshot(payload: dict):
    data = dict(payload or {})
    data["received_at"] = _v22_2_now_iso()
    data["source"] = data.get("source") or "REMOTE_V22_2_UNIFIED"
    ok = _v22_2_safe_write_json(_V22_2_UNIFIED_FILE, data)
    canonical_saved = _v28_ingest_payload(
        data,
        ingest_engine="V22_2_REMOTE_SNAPSHOT_SYNC",
        ingest_path="/v22_2_ingest_unified_snapshot",
    )

    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "type": "unified",
        "status": "OK" if ok else "WRITE_FAILED",
        "unified_snapshot_available": ok,
        "ticker": data.get("ticker"),
        "decision": data.get("decision") or data.get("final_state"),
        "can_operate": data.get("can_operate"),
        "path": str(_V22_2_UNIFIED_FILE),
        "received_at": data.get("received_at"),
        "canonical_stored_file": str(_V28_MASTER_FILE),
        "canonical_alias_file": str(_V28_ALIAS_V25_FILE),
        "canonical_rows_found": canonical_saved.get("rows_found"),
    }

# LEGACY COMPATIBILITY ONLY: keep V22.2 routes stable for older clients.
@app.get("/v22_2_snapshot_status")
def v22_2_snapshot_status():
    technical = _v22_2_safe_read_json(_V22_2_TECH_FILE, {})
    decision = _v22_2_safe_read_json(_V22_2_DECISION_FILE, {})
    unified = _v22_2_safe_read_json(_V22_2_UNIFIED_FILE, {})

    if not isinstance(technical, dict):
        technical = {}
    if not isinstance(decision, dict):
        decision = {}
    if not isinstance(unified, dict):
        unified = {}

    return _annotate_legacy_response({
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "status": "OK",
        "technical_snapshot_available": bool(technical),
        "technical_tickers": sorted(list(technical.keys())),
        "decision_snapshot_available": bool(decision),
        "unified_snapshot_available": bool(unified),
        "decision_rows_found": len(decision.get("rows") or decision.get("top") or []),
        "files": {
            "technical": str(_V22_2_TECH_FILE),
            "decision": str(_V22_2_DECISION_FILE),
            "unified": str(_V22_2_UNIFIED_FILE),
        },
    }, "V22_2_REMOTE_SNAPSHOT_SYNC", endpoints=["/v22_2_snapshot_status"])

@app.get("/v22_2_technical_snapshot/{ticker}")
def v22_2_technical_snapshot(ticker: str):
    ticker = ticker.upper().strip()
    technical = _v22_2_safe_read_json(_V22_2_TECH_FILE, {})
    if not isinstance(technical, dict):
        technical = {}

    snap = technical.get(ticker)
    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "ticker": ticker,
        "status": "OK" if snap else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": snap,
        "available_tickers": sorted(list(technical.keys())),
    }

@app.get("/v22_2_decision_snapshot")
def v22_2_decision_snapshot():
    decision = _v22_2_safe_read_json(_V22_2_DECISION_FILE, {})
    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "status": "OK" if decision else "NO_DECISION_SNAPSHOT",
        "snapshot": decision,
    }

@app.get("/v22_2_trade_decision/{ticker}")
def v22_2_trade_decision(ticker: str):
    ticker = ticker.upper().strip()
    technical = _v22_2_safe_read_json(_V22_2_TECH_FILE, {})
    decision = _v22_2_safe_read_json(_V22_2_DECISION_FILE, {})
    unified = _v22_2_safe_read_json(_V22_2_UNIFIED_FILE, {})

    if not isinstance(technical, dict):
        technical = {}
    if not isinstance(decision, dict):
        decision = {}
    if not isinstance(unified, dict):
        unified = {}

    tech = technical.get(ticker)

    rows = decision.get("rows") or decision.get("top") or []
    ticker_rows = []
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and str(r.get("ticker", "")).upper() == ticker:
                ticker_rows.append(r)

    best = ticker_rows[0] if ticker_rows else None

    final_state = "NO_DATA"
    decision_text = "No hay datos suficientes para tomar decisión."
    can_operate = False
    main_blocker = "NO_REMOTE_DATA"

    if not tech and not best:
        final_state = "NO_DATA"
        main_blocker = "NO_TECHNICAL_OR_OPTIONS_DATA"
        decision_text = f"{ticker}: no hay snapshot técnico ni snapshot operativo disponible todavía."
    elif tech and not best:
        final_state = "TECH_ONLY"
        main_blocker = "NO_OPTIONS_DECISION_ROW"
        decision_text = f"{ticker}: hay snapshot técnico, pero no hay oportunidad de opciones capturada."
    elif best:
        base_decision = str(best.get("decision") or best.get("final_state") or "RADAR").upper()
        missing = best.get("missing_confirmations") or best.get("missing_data") or best.get("falta") or []
        if isinstance(missing, str):
            missing = [missing]

        market_hours = decision.get("market_hours") or {}
        market_status = str(market_hours.get("status") or "").upper()
        options_expected = bool(market_hours.get("options_bidask_expected", False))

        can_operate = bool(best.get("can_operate", False))

        if market_status and market_status != "REGULAR":
            final_state = "WAIT_MARKET_OPEN"
            main_blocker = "OPTIONS_MARKET_NOT_RELIABLE"
            decision_text = f"{ticker}: oportunidad en radar, pero no operar ahora. Revisar próxima sesión después de 09:35 ET."
            can_operate = False
        elif missing:
            final_state = "RADAR_CONFIRMATION_PENDING"
            main_blocker = ",".join(missing)
            decision_text = f"{ticker}: mantener en radar. Falta confirmar: {', '.join(missing)}."
            can_operate = False
        elif base_decision in ("ENTRY", "ENTRY_CONFIRMED", "OPERAR") and can_operate:
            final_state = "ENTRY_CONFIRMED"
            main_blocker = None
            decision_text = f"{ticker}: entrada confirmada según snapshot remoto."
        else:
            final_state = base_decision
            main_blocker = best.get("main_blocker") or "NOT_ENTRY_CONFIRMED"
            decision_text = best.get("recommendation") or best.get("action") or f"{ticker}: mantener en observación."

    return _annotate_legacy_response({
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": final_state,
        "can_operate": can_operate,
        "main_blocker": main_blocker,
        "action": decision_text,
        "executive_summary": decision_text,
        "technical_available": bool(tech),
        "options_rows_found": len(ticker_rows),
        "technical": tech,
        "best_row": best,
        "market_hours": decision.get("market_hours") if isinstance(decision, dict) else None,
        "generated_at": _v22_2_now_iso(),
    }, "V22_2_REMOTE_SNAPSHOT_SYNC", endpoints=["/v22_2_trade_decision/{ticker}"])


# === V22.3 SAFE TECHNICAL SNAPSHOT ENDPOINT ===
@app.post("/technical_snapshot")
async def technical_snapshot(payload: dict):
    """
    Endpoint seguro para recibir snapshot técnico desde curl / TradingView / puente externo.
    Guarda el snapshot en runtime/technical_snapshot_by_ticker_safe.json.
    Nunca debe romper el servidor por campos faltantes.
    """
    from pathlib import Path
    from datetime import datetime, timezone
    import json

    try:
        runtime = Path("runtime")
        runtime.mkdir(exist_ok=True)

        ticker = str(payload.get("ticker") or payload.get("symbol") or "UNKNOWN").upper().strip()

        clean_payload = dict(payload)
        clean_payload["ticker"] = ticker
        clean_payload["received_at"] = datetime.now(timezone.utc).isoformat()
        clean_payload["source"] = clean_payload.get("source") or "TECHNICAL_SNAPSHOT_ENDPOINT"

        path = runtime / "technical_snapshot_by_ticker_safe.json"

        try:
            existing = json.loads(path.read_text()) if path.exists() else {}
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}

        existing[ticker] = clean_payload
        path.write_text(json.dumps(existing, indent=2, sort_keys=True))

        return {
            "engine": "V22_3_SAFE_TECHNICAL_SNAPSHOT_ENDPOINT",
            "status": "OK",
            "ticker": ticker,
            "snapshot": clean_payload,
            "available_tickers": sorted(existing.keys()),
            "path": str(path),
        }

    except Exception as e:
        return {
            "engine": "V22_3_SAFE_TECHNICAL_SNAPSHOT_ENDPOINT",
            "status": "ERROR_HANDLED",
            "error": str(e),
            "payload_preview": str(payload)[:500],
        }


@app.post("/technical-snapshot")
async def technical_snapshot_dash(payload: dict):
    return await technical_snapshot(payload)
# === END V22.3 SAFE TECHNICAL SNAPSHOT ENDPOINT ===



# === V22.4 SAFE TECHNICAL SNAPSHOT GATEWAY ===
from pathlib import Path as _V224Path
from datetime import datetime as _V224DateTime, timezone as _V224Timezone
import json as _v224_json

_V224_RUNTIME_DIR = _V224Path("runtime")
_V224_RUNTIME_DIR.mkdir(exist_ok=True)

_V224_SAFE_TECH_FILE = _V224_RUNTIME_DIR / "technical_snapshot_by_ticker_safe.json"


def _v224_utc_now():
    return _V224DateTime.now(_V224Timezone.utc).isoformat()


def _v224_load_safe_technical_store():
    try:
        if not _V224_SAFE_TECH_FILE.exists():
            return {}
        raw = _V224_SAFE_TECH_FILE.read_text()
        if not raw.strip():
            return {}
        data = _v224_json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _v224_save_safe_technical_store(store: dict):
    try:
        _V224_SAFE_TECH_FILE.parent.mkdir(exist_ok=True)
        _V224_SAFE_TECH_FILE.write_text(
            _v224_json.dumps(store, indent=2, ensure_ascii=False)
        )
        return True
    except Exception:
        return False


def _v224_normalize_technical_payload(payload: dict):
    if not isinstance(payload, dict):
        payload = {}

    ticker = str(payload.get("ticker") or "").upper().strip()
    if not ticker:
        ticker = "UNKNOWN"

    def _num(x, default=None):
        try:
            if x is None or x == "":
                return default
            return float(x)
        except Exception:
            return default

    trend = str(payload.get("trend") or payload.get("bias") or "UNKNOWN").upper().strip()

    snapshot = {
        "ticker": ticker,
        "received_at": _v224_utc_now(),
        "source": payload.get("source") or "TECHNICAL_SNAPSHOT_SAFE_V22_4",
        "price": _num(payload.get("price")),
        "trend": trend,
        "score": _num(payload.get("score")),
        "rsi": _num(payload.get("rsi")),
        "adx": _num(payload.get("adx")),
        "macd": payload.get("macd"),
        "vwap_position": payload.get("vwap_position"),
        "volume_relative": _num(payload.get("volume_relative")),
        "support_near": bool(payload.get("support_near", False)),
        "resistance_near": bool(payload.get("resistance_near", False)),
        "range_breakout": bool(payload.get("range_breakout", False)),
        "event_risk": bool(payload.get("event_risk", False)),
        "raw": payload,
    }

    return ticker, snapshot


@app.post("/technical_snapshot_safe")
async def v224_post_technical_snapshot_safe(payload: dict):
    try:
        ticker, snapshot = _v224_normalize_technical_payload(payload)
        store = _v224_load_safe_technical_store()
        store[ticker] = snapshot
        ok = _v224_save_safe_technical_store(store)

        return {
            "engine": "V22_4_SAFE_TECHNICAL_GATEWAY",
            "status": "OK" if ok else "SAVE_FAILED",
            "ticker": ticker,
            "snapshot": snapshot,
            "available_tickers": sorted(list(store.keys())),
            "path": str(_V224_SAFE_TECH_FILE),
        }
    except Exception as e:
        return {
            "engine": "V22_4_SAFE_TECHNICAL_GATEWAY",
            "status": "ERROR_HANDLED",
            "error": str(e),
            "payload_preview": str(payload)[:500],
        }


@app.get("/technical_snapshot_safe_status")
async def v224_get_technical_snapshot_safe_status():
    store = _v224_load_safe_technical_store()
    return {
        "engine": "V22_4_SAFE_TECHNICAL_GATEWAY",
        "status": "OK",
        "technical_snapshot_available": bool(store),
        "technical_tickers": sorted(list(store.keys())),
        "count": len(store),
        "path": str(_V224_SAFE_TECH_FILE),
    }


@app.get("/technical_snapshot_safe/{ticker}")
async def v224_get_technical_snapshot_safe_ticker(ticker: str):
    store = _v224_load_safe_technical_store()
    t = str(ticker or "").upper().strip()
    snap = store.get(t)

    return {
        "engine": "V22_4_SAFE_TECHNICAL_GATEWAY",
        "ticker": t,
        "status": "OK" if snap else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": snap,
        "available_tickers": sorted(list(store.keys())),
    }

# === END V22.4 SAFE TECHNICAL SNAPSHOT GATEWAY ===


# === V22.5 DEPLOY UNBLOCKER / COMPATIBILITY ALIAS ===
@app.post("/technical-snapshot")
async def technical_snapshot_dash_alias(payload: dict):
    return await technical_snapshot(payload)

@app.get("/v22_5_system_status")
async def v22_5_system_status():
    return {
        "engine": "V22_5_DEPLOY_UNBLOCKER",
        "status": "OK",
        "technical_snapshot_route": "/technical_snapshot",
        "technical_snapshot_alias": "/technical-snapshot",
        "safe_route": "/technical_snapshot_safe",
        "deploy_unblocked": True,
    }
# === END V22.5 DEPLOY UNBLOCKER ===



# ============================================================
# V23 TRADE READINESS & EXECUTION GUARD
# ============================================================

from pathlib import Path as _V23Path
from datetime import datetime as _V23DateTime, timezone as _V23Timezone
import json as _v23_json

_V23_RUNTIME = _V23Path("runtime")
_V23_TECH_FILE = _V23_RUNTIME / "technical_snapshot_by_ticker_safe.json"
_V23_DECISION_FILE = _V23_RUNTIME / "decision_desk_snapshot.json"
_V23_UNIFIED_FILE = _V23_RUNTIME / "v22_2_unified_remote_snapshot.json"


def _v23_now():
    return _V23DateTime.now(_V23Timezone.utc).isoformat()


def _v23_read_json(path, default=None):
    try:
        path = _V23Path(path)
        if not path.exists():
            return default
        return _v23_json.loads(path.read_text())
    except Exception as e:
        return default


def _v23_get_technical_snapshot(ticker: str):
    ticker = (ticker or "").upper().strip()
    data = _v23_read_json(_V23_TECH_FILE, {})
    if not isinstance(data, dict):
        return None

    # soporta formato directo por ticker
    if ticker in data:
        return data.get(ticker)

    # soporta formato {"snapshots": {"QQQ": {...}}}
    snapshots = data.get("snapshots")
    if isinstance(snapshots, dict) and ticker in snapshots:
        return snapshots.get(ticker)

    # soporta formato de snapshot único
    if str(data.get("ticker", "")).upper() == ticker:
        return data

    return None


def _v23_get_decision_rows():
    data = _v23_read_json(_V23_DECISION_FILE, None)

    if data is None:
        data = _v23_read_json(_V23_UNIFIED_FILE, None)

    if not isinstance(data, dict):
        return [], None

    rows = data.get("rows")
    if isinstance(rows, list):
        return rows, data

    top = data.get("top")
    if isinstance(top, list):
        return top, data

    best = data.get("best") or data.get("best_row") or data.get("best_opportunity")
    if isinstance(best, dict):
        return [best], data

    return [], data


def _v23_find_best_option_row(ticker: str):
    ticker = (ticker or "").upper().strip()
    rows, raw = _v23_get_decision_rows()

    candidates = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("ticker", "")).upper() != ticker:
            continue
        candidates.append(r)

    if not candidates:
        return None, rows, raw

    def score_row(r):
        try:
            return float(
                r.get("combined_score")
                or r.get("score")
                or r.get("options_score")
                or 0
            )
        except Exception:
            return 0

    candidates = sorted(candidates, key=score_row, reverse=True)
    return candidates[0], rows, raw


def _v23_market_context(raw_decision):
    if not isinstance(raw_decision, dict):
        return {
            "status": "UNKNOWN",
            "label": "Estado de mercado desconocido",
            "is_regular_market_open": False,
            "options_bidask_expected": False,
        }

    mh = raw_decision.get("market_hours") or {}
    if not isinstance(mh, dict):
        mh = {}

    return {
        "status": mh.get("status") or raw_decision.get("market_hours_status") or "UNKNOWN",
        "label": mh.get("label") or raw_decision.get("market_hours_label") or "Estado de mercado desconocido",
        "is_regular_market_open": bool(mh.get("is_regular_market_open") or raw_decision.get("is_regular_market_open")),
        "options_bidask_expected": bool(mh.get("options_bidask_expected") or raw_decision.get("options_bidask_expected")),
        "new_york_time": mh.get("new_york_time") or raw_decision.get("new_york_time"),
        "next_check": mh.get("next_check") or raw_decision.get("next_check"),
    }


def _v23_extract_technical_bias(tech):
    if not isinstance(tech, dict):
        return "UNKNOWN", None

    bias = (
        tech.get("bias")
        or tech.get("trend")
        or tech.get("technical_bias")
        or tech.get("direction")
        or "UNKNOWN"
    )

    score = tech.get("score") or tech.get("technical_score")

    try:
        score = float(score) if score is not None else None
    except Exception:
        score = None

    return str(bias).upper(), score


def _v23_extract_option_strategy(row):
    if not isinstance(row, dict):
        return "UNKNOWN", None

    strategy = (
        row.get("strategy")
        or row.get("best_strategy")
        or row.get("strategy_hint")
        or "UNKNOWN"
    )

    score = (
        row.get("combined_score")
        or row.get("score")
        or row.get("options_score")
    )

    try:
        score = float(score) if score is not None else None
    except Exception:
        score = None

    return str(strategy).upper(), score


def _v23_strategy_aligns(strategy, bias):
    strategy = (strategy or "").upper()
    bias = (bias or "").upper()

    if bias in ["UNKNOWN", "", "NONE"]:
        return None

    bullish_strategies = ["NAKED_PUT", "CASH_SECURED_PUT", "BULL_PUT", "PUT_CREDIT_SPREAD"]
    bearish_strategies = ["COVERED_CALL", "BEAR_CALL", "CALL_CREDIT_SPREAD"]

    if bias in ["BULLISH", "ALCISTA", "UP", "LONG"]:
        return strategy in bullish_strategies

    if bias in ["BEARISH", "BAJISTA", "DOWN", "SHORT"]:
        return strategy in bearish_strategies

    if bias in ["NEUTRAL", "RANGE", "SIDEWAYS"]:
        return strategy in bullish_strategies + bearish_strategies

    return None


def _v23_build_trade_readiness(ticker: str):
    ticker = (ticker or "").upper().strip()

    tech = _v23_get_technical_snapshot(ticker)
    best_row, rows, raw_decision = _v23_find_best_option_row(ticker)
    market = _v23_market_context(raw_decision)

    technical_available = isinstance(tech, dict)
    options_available = isinstance(best_row, dict)

    technical_bias, technical_score = _v23_extract_technical_bias(tech)
    strategy, options_score = _v23_extract_option_strategy(best_row)

    blockers = []
    warnings = []

    if not ticker:
        blockers.append("NO_TICKER")

    if not technical_available:
        blockers.append("NO_TECHNICAL_SNAPSHOT")

    if not options_available:
        blockers.append("NO_OPTIONS_ROW")

    if not market.get("is_regular_market_open"):
        blockers.append("MARKET_NOT_REGULAR_OPEN")

    if not market.get("options_bidask_expected"):
        blockers.append("OPTIONS_BIDASK_NOT_RELIABLE")

    if strategy == "UNKNOWN":
        warnings.append("Estrategia no identificada con claridad.")

    if technical_bias == "UNKNOWN":
        warnings.append("Sesgo técnico desconocido.")

    alignment = _v23_strategy_aligns(strategy, technical_bias)

    if alignment is False:
        blockers.append("TECHNICAL_STRATEGY_CONFLICT")

    if alignment is None:
        warnings.append("No se pudo validar alineación técnica de la estrategia.")

    row_can_operate = False
    if isinstance(best_row, dict):
        row_can_operate = bool(best_row.get("can_operate"))

    if options_available and not row_can_operate:
        row_missing = best_row.get("missing_confirmations") if isinstance(best_row, dict) else None
        if row_missing:
            warnings.append(f"Faltan confirmaciones: {row_missing}")

    can_operate = len(blockers) == 0 and technical_available and options_available

    if can_operate:
        final_state = "ENTRY_READY"
        decision = "ENTRY_READY"
        severity = "green"
        action = "Entrada candidata. Validar tamaño, riesgo, spread y confirmación final antes de ejecutar."
    else:
        if "MARKET_NOT_REGULAR_OPEN" in blockers or "OPTIONS_BIDASK_NOT_RELIABLE" in blockers:
            final_state = "WAIT_MARKET_OPEN"
            decision = "WAIT_MARKET_OPEN"
            severity = "gray"
            action = "No operar ahora. Esperar ventana confiable de mercado/opciones."
        elif "NO_TECHNICAL_SNAPSHOT" in blockers:
            final_state = "WAIT_TECHNICAL_DATA"
            decision = "WAIT_TECHNICAL_DATA"
            severity = "gray"
            action = "No operar todavía. Falta snapshot técnico."
        elif "NO_OPTIONS_ROW" in blockers:
            final_state = "WAIT_OPTIONS_DATA"
            decision = "WAIT_OPTIONS_DATA"
            severity = "gray"
            action = "No operar todavía. Falta oportunidad de opciones."
        elif "TECHNICAL_STRATEGY_CONFLICT" in blockers:
            final_state = "BLOCKED"
            decision = "BLOCKED"
            severity = "red"
            action = "No operar. Existe conflicto entre sesgo técnico y estrategia."
        else:
            final_state = "RADAR_ONLY"
            decision = "RADAR_ONLY"
            severity = "yellow"
            action = "Mantener en radar. Faltan validaciones para operar."

    return {
        "engine": "V23_TRADE_READINESS_EXECUTION_GUARD",
        "generated_at": _v23_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": can_operate,
        "severity": severity,
        "strategy": strategy,
        "technical_bias": technical_bias,
        "technical_score": technical_score,
        "options_score": options_score,
        "strategy_alignment": alignment,
        "technical_available": technical_available,
        "options_available": options_available,
        "market_hours": market,
        "blockers": blockers,
        "warnings": warnings,
        "action": action,
        "best_row": best_row,
        "technical": tech,
        "diagnostics": {
            "technical_file": str(_V23_TECH_FILE),
            "decision_file": str(_V23_DECISION_FILE),
            "fallback_unified_file": str(_V23_UNIFIED_FILE),
            "options_rows_found": len(rows),
        },
    }

# LEGACY COMPATIBILITY ONLY: keep V23 routes stable for older clients.
@app.get("/v23_trade_readiness/{ticker}")
async def v23_trade_readiness(ticker: str):
    return _annotate_legacy_response(
        _v23_build_trade_readiness(ticker),
        "V23_TRADE_READINESS_EXECUTION_GUARD",
        endpoints=["/v23_trade_readiness/{ticker}"],
    )


@app.get("/v23_trade_decision/{ticker}")
async def v23_trade_decision(ticker: str):
    return _annotate_legacy_response(
        _v23_build_trade_readiness(ticker),
        "V23_TRADE_READINESS_EXECUTION_GUARD",
        endpoints=["/v23_trade_decision/{ticker}"],
    )


@app.get("/v23_system_status")
async def v23_system_status():
    rows, raw = _v23_get_decision_rows()
    tickers = set()

    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and r.get("ticker"):
                tickers.add(str(r.get("ticker")).upper())

    tech_data = _v23_read_json(_V23_TECH_FILE, {})
    technical_tickers = []

    if isinstance(tech_data, dict):
        if "snapshots" in tech_data and isinstance(tech_data.get("snapshots"), dict):
            technical_tickers = sorted([str(x).upper() for x in tech_data.get("snapshots", {}).keys()])
        elif tech_data.get("ticker"):
            technical_tickers = [str(tech_data.get("ticker")).upper()]
        else:
            technical_tickers = sorted([str(x).upper() for x in tech_data.keys() if isinstance(x, str)])

    return _annotate_legacy_response({
        "engine": "V23_TRADE_READINESS_EXECUTION_GUARD",
        "generated_at": _v23_now(),
        "status": "OK",
        "decision_rows_found": len(rows),
        "decision_tickers": sorted(tickers),
        "technical_snapshot_available": bool(technical_tickers),
        "technical_tickers": technical_tickers,
        "endpoints": {
            "v23_trade_readiness_example": "/v23_trade_readiness/QQQ",
            "v23_trade_decision_example": "/v23_trade_decision/QQQ",
            "v23_dashboard": "/v23_dashboard",
            "v23_dashboard_ticker_example": "/v23_dashboard/QQQ",
        },
    }, "V23_TRADE_READINESS_EXECUTION_GUARD", endpoints=["/v23_system_status"])


def _v23_html_escape(x):
    try:
        import html
        return html.escape(str(x))
    except Exception:
        return str(x)


def _v23_badge(state):
    color = {
        "ENTRY_READY": "#16a34a",
        "WAIT_MARKET_OPEN": "#64748b",
        "WAIT_TECHNICAL_DATA": "#64748b",
        "WAIT_OPTIONS_DATA": "#64748b",
        "RADAR_ONLY": "#f59e0b",
        "BLOCKED": "#dc2626",
        "NO_DATA": "#64748b",
    }.get(str(state), "#64748b")
    return f'<span style="background:{color};color:white;padding:6px 10px;border-radius:999px;font-weight:700;">{_v23_html_escape(state)}</span>'


@app.get("/v23_dashboard/{ticker}", response_class=HTMLResponse)
async def v23_dashboard_ticker(ticker: str):
    d = _v23_build_trade_readiness(ticker)

    blockers = d.get("blockers") or []
    warnings = d.get("warnings") or []
    market = d.get("market_hours") or {}

    html_body = f"""
    <html>
    <head>
        <title>V23 Trade Readiness - {_v23_html_escape(ticker)}</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
                background:#f4f6f8;
                color:#0f172a;
                margin:40px;
            }}
            .hero {{
                background:#111827;
                color:white;
                padding:32px;
                border-radius:24px;
                margin-bottom:24px;
            }}
            .grid {{
                display:grid;
                grid-template-columns: repeat(4, 1fr);
                gap:16px;
                margin-bottom:24px;
            }}
            .card {{
                background:white;
                padding:20px;
                border-radius:18px;
                box-shadow:0 10px 25px rgba(15,23,42,0.08);
            }}
            .label {{
                color:#64748b;
                font-size:12px;
                letter-spacing:.08em;
                text-transform:uppercase;
                font-weight:700;
            }}
            .value {{
                font-size:24px;
                font-weight:800;
                margin-top:8px;
            }}
            ul {{
                margin-top:8px;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                background:white;
                border-radius:18px;
                overflow:hidden;
            }}
            th, td {{
                text-align:left;
                padding:12px 14px;
                border-bottom:1px solid #e5e7eb;
                font-size:14px;
            }}
            th {{
                color:#64748b;
                font-size:12px;
                letter-spacing:.08em;
                text-transform:uppercase;
            }}
        </style>
    </head>
    <body>
        <h1>V23 Trade Readiness — {_v23_html_escape(ticker).upper()}</h1>
        <div class="hero">
            <div class="label">Estado operativo</div>
            <h2>{_v23_badge(d.get("final_state"))}</h2>
            <h1>{_v23_html_escape(d.get("action"))}</h1>
            <p>Generado: {_v23_html_escape(d.get("generated_at"))}</p>
        </div>

        <div class="grid">
            <div class="card"><div class="label">Operable</div><div class="value">{'Sí' if d.get("can_operate") else 'No'}</div></div>
            <div class="card"><div class="label">Estrategia</div><div class="value">{_v23_html_escape(d.get("strategy"))}</div></div>
            <div class="card"><div class="label">Sesgo técnico</div><div class="value">{_v23_html_escape(d.get("technical_bias"))}</div></div>
            <div class="card"><div class="label">Alineación</div><div class="value">{_v23_html_escape(d.get("strategy_alignment"))}</div></div>
        </div>

        <div class="grid">
            <div class="card"><div class="label">Score técnico</div><div class="value">{_v23_html_escape(d.get("technical_score"))}</div></div>
            <div class="card"><div class="label">Score opciones</div><div class="value">{_v23_html_escape(d.get("options_score"))}</div></div>
            <div class="card"><div class="label">Mercado</div><div class="value">{_v23_html_escape(market.get("status"))}</div></div>
            <div class="card"><div class="label">Bid/Ask opciones</div><div class="value">{'Confiable' if market.get("options_bidask_expected") else 'No confiable'}</div></div>
        </div>

        <div class="card">
            <h2>Bloqueadores</h2>
            <ul>{"".join(f"<li>{_v23_html_escape(x)}</li>" for x in blockers) or "<li>Sin bloqueadores críticos.</li>"}</ul>
        </div>

        <br/>

        <div class="card">
            <h2>Advertencias</h2>
            <ul>{"".join(f"<li>{_v23_html_escape(x)}</li>" for x in warnings) or "<li>Sin advertencias relevantes.</li>"}</ul>
        </div>

        <br/>

        <table>
            <tr>
                <th>Campo</th>
                <th>Valor</th>
            </tr>
            <tr><td>Technical available</td><td>{_v23_html_escape(d.get("technical_available"))}</td></tr>
            <tr><td>Options available</td><td>{_v23_html_escape(d.get("options_available"))}</td></tr>
            <tr><td>Market label</td><td>{_v23_html_escape(market.get("label"))}</td></tr>
            <tr><td>Next check</td><td>{_v23_html_escape(market.get("next_check"))}</td></tr>
        </table>

        <p style="margin-top:30px;"><a href="/v23_system_status">Ver V23 system status</a></p>
    </body>
    </html>
    """

    return HTMLResponse(content=html_body)


@app.get("/v23_dashboard", response_class=HTMLResponse)
async def v23_dashboard():
    status = await v23_system_status()
    tickers = status.get("decision_tickers") or status.get("technical_tickers") or ["QQQ"]

    cards = ""
    for t in tickers:
        d = _v23_build_trade_readiness(t)
        cards += f"""
        <tr>
            <td><a href="/v23_dashboard/{_v23_html_escape(t)}">{_v23_html_escape(t)}</a></td>
            <td>{_v23_badge(d.get("final_state"))}</td>
            <td>{_v23_html_escape(d.get("strategy"))}</td>
            <td>{_v23_html_escape(d.get("technical_bias"))}</td>
            <td>{'Sí' if d.get("can_operate") else 'No'}</td>
            <td>{_v23_html_escape(d.get("action"))}</td>
        </tr>
        """

    html_body = f"""
    <html>
    <head>
        <title>V23 Dashboard</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
                background:#f4f6f8;
                color:#0f172a;
                margin:40px;
            }}
            .hero {{
                background:#111827;
                color:white;
                padding:32px;
                border-radius:24px;
                margin-bottom:24px;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                background:white;
                border-radius:18px;
                overflow:hidden;
                box-shadow:0 10px 25px rgba(15,23,42,0.08);
            }}
            th, td {{
                text-align:left;
                padding:14px;
                border-bottom:1px solid #e5e7eb;
                font-size:14px;
            }}
            th {{
                color:#64748b;
                font-size:12px;
                letter-spacing:.08em;
                text-transform:uppercase;
            }}
        </style>
    </head>
    <body>
        <h1>V23 — Trade Readiness Dashboard</h1>
        <div class="hero">
            <h2>Execution Guard activo</h2>
            <p>Este dashboard consolida técnico + opciones + estado de mercado para evitar operar sin confirmaciones críticas.</p>
            <p>Generado: {_v23_html_escape(_v23_now())}</p>
        </div>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Estado</th>
                <th>Estrategia</th>
                <th>Sesgo técnico</th>
                <th>Operable</th>
                <th>Acción</th>
            </tr>
            {cards}
        </table>
    </body>
    </html>
    """

    return HTMLResponse(content=html_body)

# ============================================================
# END V23 TRADE READINESS & EXECUTION GUARD
# ============================================================



# === V24 UNIFIED DATA RESOLVER ===
from pathlib import Path as _V24Path
from datetime import datetime as _V24DateTime, timezone as _V24Timezone
import json as _v24_json

_V24_RUNTIME = _V24Path("runtime")
_V24_RUNTIME.mkdir(exist_ok=True)

_V24_DECISION_FILES = [
    _V24Path("runtime/v22_2_unified_remote_snapshot.json"),
    _V24Path("runtime/v22_unified_remote_snapshot.json"),
    _V24Path("runtime/decision_desk_snapshot.json"),
    _V24Path("runtime/decision_snapshot.json"),
    _V24Path("runtime/v18_decision_desk_snapshot.json"),
    _V24Path("runtime/v18_decision_snapshot.json"),
    _V24Path("decision_desk_snapshot.json"),
    _V24Path("decision_snapshot.json"),
]

_V24_TECHNICAL_FILES = [
    _V24Path("runtime/technical_snapshot_by_ticker_safe.json"),
    _V24Path("runtime/technical_snapshot_by_ticker.json"),
    _V24Path("technical_snapshot_by_ticker_safe.json"),
    _V24Path("technical_snapshot_by_ticker.json"),
]

def _v24_now():
    return _V24DateTime.now(_V24Timezone.utc).isoformat()

def _v24_load_json(path):
    try:
        if not path.exists():
            return None
        txt = path.read_text().strip()
        if not txt:
            return None
        return _v24_json.loads(txt)
    except Exception:
        return None

def _v24_as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

def _v24_norm_ticker(t):
    return str(t or "").upper().strip()

def _v24_find_rows(obj):
    rows = []
    if obj is None:
        return rows

    if isinstance(obj, list):
        return obj

    if not isinstance(obj, dict):
        return rows

    candidate_keys = [
        "rows",
        "top",
        "top_5",
        "opportunities",
        "items",
        "data",
        "records",
        "decision_rows",
    ]

    for k in candidate_keys:
        v = obj.get(k)
        if isinstance(v, list):
            rows.extend(v)

    for k in ["best", "best_row", "best_opportunity", "next_best_action"]:
        v = obj.get(k)
        if isinstance(v, dict):
            rows.append(v)

    by_ticker = obj.get("by_ticker")
    if isinstance(by_ticker, dict):
        for _, v in by_ticker.items():
            if isinstance(v, dict):
                if isinstance(v.get("rows"), list):
                    rows.extend(v.get("rows"))
                if isinstance(v.get("best"), dict):
                    rows.append(v.get("best"))
                else:
                    rows.append(v)
            elif isinstance(v, list):
                rows.extend(v)

    summary = obj.get("summary")
    if isinstance(summary, dict):
        rows.extend(_v24_find_rows(summary))

    return [r for r in rows if isinstance(r, dict)]

def _v24_extract_ticker(row):
    return _v24_norm_ticker(
        row.get("ticker")
        or row.get("symbol")
        or row.get("underlying")
        or row.get("underlying_symbol")
        or row.get("option_symbol")
    )

def _v24_extract_strategy(row):
    return str(
        row.get("strategy")
        or row.get("strategy_hint")
        or row.get("best_strategy")
        or row.get("primary_focus")
        or row.get("setup")
        or "UNKNOWN"
    ).upper()

def _v24_extract_score(row):
    for k in ["combined_score", "score", "master_score", "technical_score", "options_score"]:
        try:
            v = row.get(k)
            if v is not None:
                return float(v)
        except Exception:
            pass
    return None

def _v24_pick_best_row(rows, ticker=None):
    ticker = _v24_norm_ticker(ticker)
    filtered = []
    for r in rows:
        if ticker and _v24_extract_ticker(r) != ticker:
            continue
        filtered.append(r)

    if not filtered:
        return None

    def sort_key(r):
        can = bool(r.get("can_operate") or r.get("can_trade"))
        decision = str(r.get("decision") or r.get("final_decision") or r.get("state") or "").upper()
        entry_bonus = 1000 if ("ENTRY" in decision or can) else 0
        score = _v24_extract_score(r) or 0
        return entry_bonus + score

    return sorted(filtered, key=sort_key, reverse=True)[0]

def _v24_load_decision_context(ticker=None):
    all_rows = []
    files_seen = []
    raw_sources = []

    for f in _V24_DECISION_FILES:
        obj = _v24_load_json(f)
        if obj is not None:
            files_seen.append(str(f))
            raw_sources.append({"file": str(f), "type": type(obj).__name__})
            all_rows.extend(_v24_find_rows(obj))

    best = _v24_pick_best_row(all_rows, ticker)

    return {
        "available": bool(all_rows),
        "rows_found": len(all_rows),
        "files_seen": files_seen,
        "sources": raw_sources,
        "best_row": best,
        "rows": all_rows[:100],
    }

def _v24_load_technical_context(ticker=None):
    ticker = _v24_norm_ticker(ticker)
    files_seen = []
    available_tickers = []
    snapshot = None

    for f in _V24_TECHNICAL_FILES:
        obj = _v24_load_json(f)
        if obj is None:
            continue

        files_seen.append(str(f))

        if isinstance(obj, dict):
            if ticker and ticker in obj and isinstance(obj.get(ticker), dict):
                snapshot = obj.get(ticker)
                available_tickers = list(obj.keys())
                break

            if ticker and _v24_norm_ticker(obj.get("ticker")) == ticker:
                snapshot = obj
                available_tickers = [ticker]
                break

            for k, v in obj.items():
                if isinstance(v, dict):
                    available_tickers.append(str(k).upper())

    return {
        "available": snapshot is not None,
        "ticker": ticker,
        "snapshot": snapshot,
        "available_tickers": sorted(list(set(available_tickers))),
        "files_seen": files_seen,
    }

def _v24_market_context():
    try:
        mh = globals().get("market_hours", None)
        if callable(mh):
            return mh()
    except Exception:
        pass

    return {
        "status": "UNKNOWN",
        "label": "Market hours unknown",
        "is_regular_market_open": None,
        "options_bidask_expected": None,
        "new_york_time": None,
        "next_check": "Validate market hours manually.",
    }

def _v24_get_value(d, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if d.get(k) is not None:
            return d.get(k)
    return default

def _v24_decision_for_ticker(ticker):
    ticker = _v24_norm_ticker(ticker)
    decision_ctx = _v24_load_decision_context(ticker)
    technical_ctx = _v24_load_technical_context(ticker)
    market_ctx = _v24_market_context()

    row = decision_ctx.get("best_row") or {}

    strategy = _v24_extract_strategy(row)
    score = _v24_extract_score(row)
    technical = technical_ctx.get("snapshot") or {}

    tech_bias = str(
        _v24_get_value(
            technical,
            "bias",
            "trend",
            "technical_bias",
            default="UNKNOWN"
        )
    ).upper()

    tech_score = _v24_get_value(technical, "score", "technical_score", default=None)

    options_available = bool(decision_ctx.get("rows_found", 0) > 0)
    technical_available = bool(technical_ctx.get("available"))

    market_status = str((market_ctx or {}).get("status") or "UNKNOWN").upper()
    options_bidask_expected = bool((market_ctx or {}).get("options_bidask_expected"))

    row_can_operate = bool(row.get("can_operate") or row.get("can_trade"))

    decision_text = str(
        row.get("decision")
        or row.get("final_decision")
        or row.get("state")
        or ""
    ).upper()

    if not options_available and not technical_available:
        final_state = "NO_DATA"
        can_operate = False
        main_blocker = "NO_TECHNICAL_OR_OPTIONS_DATA"
        action = f"{ticker}: no hay datos técnicos ni datos de opciones disponibles todavía."
        severity = "red"
    elif not technical_available:
        final_state = "WAIT_TECHNICAL_DATA"
        can_operate = False
        main_blocker = "NO_TECHNICAL_SNAPSHOT"
        action = f"{ticker}: no operar todavía. Falta snapshot técnico para confirmar dirección y contexto."
        severity = "gray"
    elif not options_available:
        final_state = "WAIT_OPTIONS_DATA"
        can_operate = False
        main_blocker = "NO_OPTIONS_ROWS"
        action = f"{ticker}: no operar todavía. Hay técnico disponible, pero faltan filas de opciones."
        severity = "gray"
    elif market_status != "REGULAR_OPTIONS_SESSION" and not options_bidask_expected:
        final_state = "WAIT_MARKET_OPEN"
        can_operate = False
        main_blocker = "OPTIONS_MARKET_NOT_RELIABLE"
        action = "No operar ahora. Esperar ventana confiable de mercado/opciones. Revisar después de 09:35 ET."
        severity = "gray"
    elif row_can_operate or "ENTRY" in decision_text:
        final_state = "ENTRY_READY"
        can_operate = True
        main_blocker = None
        action = "Entrada potencial lista. Validar tamaño, riesgo, spread y confirmación final antes de ejecutar."
        severity = "green"
    else:
        final_state = "RADAR"
        can_operate = False
        main_blocker = "NOT_FULLY_CONFIRMED"
        action = "Mantener en radar. Faltan confirmaciones para entrada operable."
        severity = "yellow"

    return {
        "engine": "V24_UNIFIED_DATA_RESOLVER",
        "generated_at": _v24_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": final_state,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": main_blocker,
        "action": action,
        "strategy": strategy,
        "score": score,
        "technical": {
            "available": technical_available,
            "bias": tech_bias,
            "score": tech_score,
            "snapshot": technical,
            "available_tickers": technical_ctx.get("available_tickers", []),
        },
        "options": {
            "available": options_available,
            "rows_found": decision_ctx.get("rows_found", 0),
            "best_row": row,
            "sample_rows": decision_ctx.get("rows", [])[:10],
        },
        "market_hours": market_ctx,
        "diagnostics": {
            "decision_files_seen": decision_ctx.get("files_seen", []),
            "technical_files_seen": technical_ctx.get("files_seen", []),
        },
    }

# LEGACY COMPATIBILITY ONLY: keep V24 routes stable for older clients.
@app.get("/v24_trade_decision/{ticker}")
async def v24_trade_decision(ticker: str):
    return _annotate_legacy_response(
        _v24_decision_for_ticker(ticker),
        "V24_UNIFIED_DATA_RESOLVER",
        endpoints=["/v24_trade_decision/{ticker}"],
    )

@app.get("/v24_system_status")
async def v24_system_status():
    tickers = set()
    decision_ctx = _v24_load_decision_context()
    tech_ctx = _v24_load_technical_context()

    for r in decision_ctx.get("rows", []):
        t = _v24_extract_ticker(r)
        if t:
            tickers.add(t)

    for t in tech_ctx.get("available_tickers", []):
        tickers.add(t)

    return _annotate_legacy_response({
        "engine": "V24_UNIFIED_DATA_RESOLVER",
        "generated_at": _v24_now(),
        "status": "OK",
        "decision_rows_found": decision_ctx.get("rows_found", 0),
        "technical_snapshot_available": tech_ctx.get("available", False),
        "technical_tickers": tech_ctx.get("available_tickers", []),
        "tickers_detected": sorted(list(tickers)),
        "market_hours": _v24_market_context(),
        "endpoints": {
            "v24_system_status": "/v24_system_status",
            "v24_trade_decision_example": "/v24_trade_decision/QQQ",
            "v24_dashboard": "/v24_dashboard",
            "v24_dashboard_ticker_example": "/v24_dashboard/QQQ",
        },
        "diagnostics": {
            "decision_files_seen": decision_ctx.get("files_seen", []),
            "technical_files_seen": tech_ctx.get("files_seen", []),
        },
    }, "V24_UNIFIED_DATA_RESOLVER", endpoints=["/v24_system_status"])

def _v24_html_escape(x):
    import html
    return html.escape(str(x if x is not None else ""))

def _v24_badge_color(state):
    s = str(state or "").upper()
    if "ENTRY" in s:
        return "#16a34a"
    if "RADAR" in s:
        return "#f59e0b"
    if "WAIT" in s:
        return "#64748b"
    if "NO_DATA" in s:
        return "#dc2626"
    return "#64748b"

def _v24_render_dashboard(ticker=None):
    status = _v24_system_status
    tlist = []
    system = {
        "tickers_detected": [],
        "decision_rows_found": 0,
        "technical_tickers": [],
    }

    try:
        decision_ctx = _v24_load_decision_context()
        tech_ctx = _v24_load_technical_context()
        for r in decision_ctx.get("rows", []):
            rt = _v24_extract_ticker(r)
            if rt:
                tlist.append(rt)
        tlist.extend(tech_ctx.get("available_tickers", []))
    except Exception:
        pass

    tickers = sorted(list(set(tlist)))
    if ticker:
        tickers = [_v24_norm_ticker(ticker)]

    if not tickers:
        tickers = ["QQQ"]

    rows_html = ""
    cards = []

    for t in tickers:
        d = _v24_decision_for_ticker(t)
        color = _v24_badge_color(d.get("final_state"))
        rows_html += f"""
        <tr>
            <td><a href="/v24_dashboard/{_v24_html_escape(t)}">{_v24_html_escape(t)}</a></td>
            <td><span class="badge" style="background:{color}">{_v24_html_escape(d.get("final_state"))}</span></td>
            <td>{_v24_html_escape(d.get("strategy"))}</td>
            <td>{_v24_html_escape(d.get("technical", {}).get("bias"))}</td>
            <td>{_v24_html_escape(d.get("score"))}</td>
            <td>{'Sí' if d.get("can_operate") else 'No'}</td>
            <td>{_v24_html_escape(d.get("action"))}</td>
        </tr>
        """
        cards.append(d)

    headline = "Execution Guard activo"
    if any(c.get("can_operate") for c in cards):
        headline = "Entrada potencial detectada"
    elif any(c.get("final_state") == "RADAR" for c in cards):
        headline = "Oportunidades en radar"

    generated = _v24_now()

    return f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title>V24 Unified Data Resolver</title>
        <style>
            body {{
                font-family: Inter, Arial, sans-serif;
                background:#f6f7fb;
                color:#0f172a;
                padding:32px;
            }}
            h1 {{
                font-size:34px;
                margin-bottom:20px;
            }}
            .hero {{
                background:#0f172a;
                color:white;
                border-radius:24px;
                padding:36px;
                margin-bottom:24px;
            }}
            .hero h2 {{
                margin:0 0 14px 0;
                font-size:26px;
            }}
            .grid {{
                display:grid;
                grid-template-columns: repeat(4, 1fr);
                gap:16px;
                margin-bottom:24px;
            }}
            .card {{
                background:white;
                padding:22px;
                border-radius:18px;
                box-shadow:0 12px 28px rgba(15,23,42,.08);
            }}
            .card .num {{
                font-size:30px;
                font-weight:800;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                background:white;
                border-radius:18px;
                overflow:hidden;
                box-shadow:0 12px 28px rgba(15,23,42,.08);
            }}
            th, td {{
                text-align:left;
                padding:14px 16px;
                border-bottom:1px solid #e5e7eb;
                font-size:14px;
            }}
            th {{
                text-transform:uppercase;
                letter-spacing:.08em;
                font-size:12px;
                color:#64748b;
            }}
            .badge {{
                display:inline-block;
                color:white;
                padding:6px 10px;
                border-radius:999px;
                font-weight:800;
                font-size:12px;
            }}
            .footer {{
                margin-top:24px;
                color:#64748b;
                font-size:13px;
            }}
        </style>
    </head>
    <body>
        <h1>V24 — Unified Data Resolver</h1>
        <div class="hero">
            <h2>{_v24_html_escape(headline)}</h2>
            <p>Consolida datos técnicos, opciones, snapshots remotos y estado de mercado para evitar decisiones ciegas.</p>
            <p>Generado: {_v24_html_escape(generated)}</p>
        </div>

        <div class="grid">
            <div class="card"><div>Tickers detectados</div><div class="num">{len(tickers)}</div></div>
            <div class="card"><div>Technical disponibles</div><div class="num">{sum(1 for c in cards if c.get("technical", {}).get("available"))}</div></div>
            <div class="card"><div>Options disponibles</div><div class="num">{sum(1 for c in cards if c.get("options", {}).get("available"))}</div></div>
            <div class="card"><div>Operables</div><div class="num">{sum(1 for c in cards if c.get("can_operate"))}</div></div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Estado</th>
                    <th>Estrategia</th>
                    <th>Sesgo técnico</th>
                    <th>Score</th>
                    <th>Operable</th>
                    <th>Acción</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div class="footer">
            Endpoints: /v24_system_status · /v24_trade_decision/QQQ · /v24_dashboard · /v24_dashboard/QQQ
        </div>
    </body>
    </html>
    """

@app.get("/v24_dashboard")
async def v24_dashboard():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_v24_render_dashboard())

@app.get("/v24_dashboard/{ticker}")
async def v24_dashboard_ticker(ticker: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_v24_render_dashboard(ticker))

# === END V24 UNIFIED DATA RESOLVER ===



# === V24.1 RUNTIME DISCOVERY + SAFE DASHBOARD FIX ===
from pathlib import Path as _V241Path
from datetime import datetime as _V241DateTime, timezone as _V241Timezone
import json as _v241_json

_V241_RUNTIME = _V241Path("runtime")
_V241_RUNTIME.mkdir(exist_ok=True)

def _v241_now():
    return _V241DateTime.now(_V241Timezone.utc).isoformat()

def _v241_read_json(path):
    try:
        path = _V241Path(path)
        if not path.exists():
            return None
        txt = path.read_text().strip()
        if not txt:
            return None
        return _v241_json.loads(txt)
    except Exception as e:
        return {"__read_error__": str(e), "__path__": str(path)}

def _v241_runtime_json_files():
    files = []
    try:
        for f in _V241_RUNTIME.glob("*.json"):
            files.append(str(f))
    except Exception:
        pass

    root_candidates = [
        "decision_snapshot.json",
        "decision_desk_snapshot.json",
        "technical_snapshot_by_ticker.json",
        "technical_snapshot_by_ticker_safe.json",
        "v18_decision_snapshot.json",
        "v18_decision_desk_snapshot.json",
    ]

    for name in root_candidates:
        if _V241Path(name).exists():
            files.append(name)

    return sorted(list(set(files)))

def _v241_extract_rows_from_any(obj):
    rows = []

    if obj is None:
        return rows

    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]

    if not isinstance(obj, dict):
        return rows

    # Si el objeto mismo parece una fila operativa
    if any(k in obj for k in ["ticker", "strategy", "decision", "final_state", "can_operate", "score", "price"]):
        rows.append(obj)

    keys = [
        "rows", "top", "top_3", "top_5", "items", "data", "records",
        "opportunities", "decision_rows", "sample_rows"
    ]

    for k in keys:
        v = obj.get(k)
        if isinstance(v, list):
            rows.extend([x for x in v if isinstance(x, dict)])
        elif isinstance(v, dict):
            rows.extend(_v241_extract_rows_from_any(v))

    for k in ["best", "best_row", "best_opportunity", "next_best_action", "best_fusion_opportunity"]:
        v = obj.get(k)
        if isinstance(v, dict):
            rows.append(v)

    for k in ["summary", "by_ticker", "by_strategy", "fusion_counts", "options"]:
        v = obj.get(k)
        if isinstance(v, dict):
            rows.extend(_v241_extract_rows_from_any(v))
        elif isinstance(v, list):
            rows.extend([x for x in v if isinstance(x, dict)])

    # Búsqueda profunda limitada en diccionarios anidados
    for v in obj.values():
        if isinstance(v, dict):
            rows.extend(_v241_extract_rows_from_any(v))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    rows.extend(_v241_extract_rows_from_any(item))

    # Deduplicar conservando orden
    seen = set()
    clean = []
    for r in rows:
        key = str(sorted(r.items()))[:500]
        if key not in seen:
            seen.add(key)
            clean.append(r)

    return clean

def _v241_ticker(row):
    if not isinstance(row, dict):
        return ""
    return str(
        row.get("ticker")
        or row.get("symbol")
        or row.get("underlying")
        or row.get("underlying_symbol")
        or row.get("option_symbol")
        or ""
    ).upper().strip()

def _v241_strategy(row):
    if not isinstance(row, dict):
        return "UNKNOWN"
    return str(
        row.get("strategy")
        or row.get("strategy_hint")
        or row.get("best_strategy")
        or row.get("primary_focus")
        or row.get("setup")
        or "UNKNOWN"
    ).upper().strip()

def _v241_score(row):
    if not isinstance(row, dict):
        return None
    for k in ["combined_score", "score", "master_score", "technical_score", "options_score", "entry_score"]:
        try:
            v = row.get(k)
            if v is not None:
                return float(v)
        except Exception:
            pass
    return None

def _v241_can_operate(row):
    if not isinstance(row, dict):
        return False

    if row.get("can_operate") is True or row.get("can_trade") is True:
        return True

    decision = str(row.get("decision") or row.get("final_decision") or row.get("final_state") or "").upper()
    state = str(row.get("state") or row.get("fusion_state") or "").upper()

    if "ENTRY" in decision or "ENTRY" in state:
        return True

    return False

def _v241_load_all_runtime_context():
    files = _v241_runtime_json_files()
    all_rows = []
    file_report = []

    technical_by_ticker = {}

    for f in files:
        obj = _v241_read_json(f)

        report = {
            "file": f,
            "loaded": obj is not None,
            "type": type(obj).__name__,
            "rows_found": 0,
            "tickers": [],
            "technical_like": False,
            "error": None,
        }

        if isinstance(obj, dict) and obj.get("__read_error__"):
            report["error"] = obj.get("__read_error__")
            file_report.append(report)
            continue

        rows = _v241_extract_rows_from_any(obj)
        report["rows_found"] = len(rows)

        for r in rows:
            t = _v241_ticker(r)
            if t:
                report["tickers"].append(t)
            all_rows.append(r)

        # technical snapshot style: {"QQQ": {...}}
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, dict) and any(x in v for x in ["trend", "bias", "score", "rsi", "adx", "vwap_position"]):
                    technical_by_ticker[str(k).upper()] = v
                    report["technical_like"] = True

            # technical single object style
            t = _v241_ticker(obj)
            if t and any(x in obj for x in ["trend", "bias", "score", "rsi", "adx", "vwap_position"]):
                technical_by_ticker[t] = obj
                report["technical_like"] = True

        report["tickers"] = sorted(list(set(report["tickers"])))
        file_report.append(report)

    tickers = sorted(list(set([_v241_ticker(r) for r in all_rows if _v241_ticker(r)] + list(technical_by_ticker.keys()))))

    return {
        "files": files,
        "file_report": file_report,
        "rows": all_rows,
        "rows_found": len(all_rows),
        "technical_by_ticker": technical_by_ticker,
        "technical_tickers": sorted(list(technical_by_ticker.keys())),
        "tickers": tickers,
    }

def _v241_market_hours():
    try:
        fn = globals().get("market_hours")
        if callable(fn):
            return fn()
    except Exception:
        pass
    return {
        "status": "UNKNOWN",
        "label": "Market hours unknown",
        "is_regular_market_open": None,
        "options_bidask_expected": None,
    }

def _v241_pick_best(ticker=None):
    ctx = _v241_load_all_runtime_context()
    ticker = str(ticker or "").upper().strip()

    rows = []
    for r in ctx["rows"]:
        if ticker and _v241_ticker(r) != ticker:
            continue
        rows.append(r)

    def rank(r):
        entry = 10000 if _v241_can_operate(r) else 0
        score = _v241_score(r) or 0
        has_price = 50 if r.get("price") or r.get("premium") or r.get("mark_price") else 0
        return entry + score + has_price

    best = sorted(rows, key=rank, reverse=True)[0] if rows else None
    return ctx, best

def _v241_trade_decision(ticker):
    ticker = str(ticker or "").upper().strip()
    ctx, best = _v241_pick_best(ticker)
    tech = ctx["technical_by_ticker"].get(ticker)
    mh = _v241_market_hours()

    has_rows = best is not None
    has_tech = tech is not None

    market_status = str((mh or {}).get("status") or "").upper()
    options_bidask_expected = bool((mh or {}).get("options_bidask_expected"))

    if not has_rows and not has_tech:
        final_state = "NO_DATA"
        can_operate = False
        blocker = "NO_RUNTIME_ROWS_OR_TECHNICAL"
        action = f"{ticker}: no hay datos detectados en runtime para opciones ni técnico."
        severity = "red"
    elif not has_tech:
        final_state = "WAIT_TECHNICAL_DATA"
        can_operate = False
        blocker = "NO_TECHNICAL_SNAPSHOT"
        action = f"{ticker}: hay datos de opciones/decisión, pero falta snapshot técnico."
        severity = "gray"
    elif not has_rows:
        final_state = "WAIT_OPTIONS_DATA"
        can_operate = False
        blocker = "NO_OPTIONS_OR_DECISION_ROWS"
        action = f"{ticker}: hay técnico disponible, pero faltan oportunidades/opciones."
        severity = "gray"
    elif market_status not in ["REGULAR_OPTIONS_SESSION", "REGULAR_MARKET_OPEN"] and not options_bidask_expected:
        final_state = "WAIT_MARKET_OPEN"
        can_operate = False
        blocker = "OPTIONS_MARKET_NOT_RELIABLE"
        action = "No operar ahora. Esperar ventana confiable de mercado/opciones."
        severity = "gray"
    elif _v241_can_operate(best):
        final_state = "ENTRY_READY"
        can_operate = True
        blocker = None
        action = "Entrada potencial lista. Validar riesgo, tamaño, spread, liquidez y confirmación final."
        severity = "green"
    else:
        final_state = "RADAR"
        can_operate = False
        blocker = "NOT_FULLY_CONFIRMED"
        action = "Mantener en radar. Aún no cumple confirmaciones completas."
        severity = "yellow"

    return {
        "engine": "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD",
        "generated_at": _v241_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": final_state,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": blocker,
        "action": action,
        "strategy": _v241_strategy(best) if best else "UNKNOWN",
        "score": _v241_score(best) if best else None,
        "technical": {
            "available": has_tech,
            "snapshot": tech,
            "bias": str((tech or {}).get("bias") or (tech or {}).get("trend") or "UNKNOWN").upper(),
            "score": (tech or {}).get("score"),
        },
        "options": {
            "available": has_rows,
            "rows_found_total": ctx["rows_found"],
            "best_row": best,
        },
        "market_hours": mh,
        "diagnostics": {
            "runtime_files": ctx["files"],
            "technical_tickers": ctx["technical_tickers"],
            "tickers_detected": ctx["tickers"],
        }
    }

# LEGACY COMPATIBILITY ONLY: keep V24.1 routes stable for older clients.
@app.get("/v24_1_runtime_inventory")
async def v24_1_runtime_inventory():
    ctx = _v241_load_all_runtime_context()
    return _annotate_legacy_response({
        "engine": "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD",
        "generated_at": _v241_now(),
        "status": "OK",
        "runtime_files": ctx["files"],
        "file_report": ctx["file_report"],
        "rows_found_total": ctx["rows_found"],
        "technical_tickers": ctx["technical_tickers"],
        "tickers_detected": ctx["tickers"],
    }, "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD", endpoints=["/v24_1_runtime_inventory"])

@app.get("/v24_1_trade_decision/{ticker}")
async def v24_1_trade_decision(ticker: str):
    return _annotate_legacy_response(
        _v241_trade_decision(ticker),
        "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD",
        endpoints=["/v24_1_trade_decision/{ticker}"],
    )

def _v241_escape(x):
    import html
    return html.escape(str(x if x is not None else ""))

def _v241_badge(state):
    s = str(state or "").upper()
    if "ENTRY" in s:
        return "#16a34a"
    if "RADAR" in s:
        return "#f59e0b"
    if "WAIT" in s:
        return "#64748b"
    if "NO_DATA" in s:
        return "#dc2626"
    return "#64748b"

def _v241_dashboard_html(ticker=None):
    try:
        ctx = _v241_load_all_runtime_context()
        tickers = ctx["tickers"]

        if ticker:
            tickers = [str(ticker).upper().strip()]

        if not tickers:
            tickers = ["QQQ"]

        rows_html = ""
        decisions = []

        for t in tickers:
            d = _v241_trade_decision(t)
            decisions.append(d)
            color = _v241_badge(d.get("final_state"))
            rows_html += f"""
            <tr>
                <td><a href="/v24_1_dashboard/{_v241_escape(t)}">{_v241_escape(t)}</a></td>
                <td><span class="badge" style="background:{color}">{_v241_escape(d.get("final_state"))}</span></td>
                <td>{_v241_escape(d.get("strategy"))}</td>
                <td>{_v241_escape(d.get("technical", {}).get("bias"))}</td>
                <td>{_v241_escape(d.get("score"))}</td>
                <td>{'Sí' if d.get("can_operate") else 'No'}</td>
                <td>{_v241_escape(d.get("main_blocker"))}</td>
                <td>{_v241_escape(d.get("action"))}</td>
            </tr>
            """

        headline = "Execution Guard activo"
        if any(d.get("can_operate") for d in decisions):
            headline = "Entrada potencial detectada"
        elif any(d.get("final_state") == "RADAR" for d in decisions):
            headline = "Oportunidades en radar"

        return f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1"/>
            <title>V24.1 Runtime Discovery Dashboard</title>
            <style>
                body {{
                    font-family: Inter, Arial, sans-serif;
                    background:#f6f7fb;
                    color:#0f172a;
                    padding:32px;
                }}
                h1 {{ font-size:34px; margin-bottom:20px; }}
                .hero {{
                    background:#0f172a;
                    color:white;
                    border-radius:24px;
                    padding:34px;
                    margin-bottom:24px;
                }}
                .hero h2 {{ margin:0 0 12px 0; font-size:26px; }}
                .grid {{
                    display:grid;
                    grid-template-columns: repeat(4, 1fr);
                    gap:16px;
                    margin-bottom:24px;
                }}
                .card {{
                    background:white;
                    padding:20px;
                    border-radius:18px;
                    box-shadow:0 12px 28px rgba(15,23,42,.08);
                }}
                .num {{ font-size:30px; font-weight:800; }}
                table {{
                    width:100%;
                    border-collapse:collapse;
                    background:white;
                    border-radius:18px;
                    overflow:hidden;
                    box-shadow:0 12px 28px rgba(15,23,42,.08);
                }}
                th, td {{
                    text-align:left;
                    padding:13px 15px;
                    border-bottom:1px solid #e5e7eb;
                    font-size:14px;
                }}
                th {{
                    text-transform:uppercase;
                    letter-spacing:.08em;
                    font-size:12px;
                    color:#64748b;
                }}
                .badge {{
                    color:white;
                    padding:6px 10px;
                    border-radius:999px;
                    font-weight:800;
                    font-size:12px;
                    display:inline-block;
                }}
                .footer {{
                    margin-top:24px;
                    font-size:13px;
                    color:#64748b;
                }}
            </style>
        </head>
        <body>
            <h1>V24.1 — Runtime Discovery Dashboard</h1>
            <div class="hero">
                <h2>{_v241_escape(headline)}</h2>
                <p>Busca automáticamente archivos runtime JSON y consolida técnico + opciones + decisión + market hours.</p>
                <p>Generado: {_v241_escape(_v241_now())}</p>
            </div>

            <div class="grid">
                <div class="card"><div>Runtime files</div><div class="num">{len(ctx["files"])}</div></div>
                <div class="card"><div>Rows encontradas</div><div class="num">{ctx["rows_found"]}</div></div>
                <div class="card"><div>Technical tickers</div><div class="num">{len(ctx["technical_tickers"])}</div></div>
                <div class="card"><div>Tickers detectados</div><div class="num">{len(tickers)}</div></div>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>Estado</th>
                        <th>Estrategia</th>
                        <th>Sesgo técnico</th>
                        <th>Score</th>
                        <th>Operable</th>
                        <th>Bloqueador</th>
                        <th>Acción</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>

            <div class="footer">
                Endpoints: /v24_1_runtime_inventory · /v24_1_trade_decision/QQQ · /v24_1_dashboard · /v24_1_dashboard/QQQ
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return f"""
        <html><body style="font-family:Arial;padding:30px">
        <h1>V24.1 Dashboard Error Capturado</h1>
        <p>El dashboard no explotó el servicio, pero capturó este error:</p>
        <pre>{_v241_escape(type(e).__name__)}: {_v241_escape(e)}</pre>
        <p>Revisar /v24_1_runtime_inventory para diagnóstico.</p>
        </body></html>
        """

@app.get("/v24_1_dashboard")
async def v24_1_dashboard():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_v241_dashboard_html())

@app.get("/v24_1_dashboard/{ticker}")
async def v24_1_dashboard_ticker(ticker: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_v241_dashboard_html(ticker))

# === END V24.1 RUNTIME DISCOVERY + SAFE DASHBOARD FIX ===


# === V25 REMOTE SNAPSHOT STORE / UNIFIED INGEST ===
from pathlib import Path as _V25Path
from datetime import datetime as _V25DateTime, timezone as _V25Timezone
import json as _v25_json

_V25_RUNTIME_DIR = _V25Path("runtime")
_V25_RUNTIME_DIR.mkdir(exist_ok=True)

_V25_MASTER_FILE = _V25_RUNTIME_DIR / "v25_master_snapshot.json"


def _v25_now_iso():
    return _V25DateTime.now(_V25Timezone.utc).isoformat()


def _v25_safe_read_json(path, default=None):
    if default is None:
        default = {}
    try:
        p = _V25Path(path)
        if not p.exists():
            return default
        return _v25_json.loads(p.read_text())
    except Exception:
        return default


def _v25_safe_write_json(path, payload):
    p = _V25Path(path)
    p.parent.mkdir(exist_ok=True)
    p.write_text(_v25_json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return str(p)


def _v25_load_master():
    return _v25_safe_read_json(_V25_MASTER_FILE, default={})


def _v25_extract_rows(snapshot):
    if not isinstance(snapshot, dict):
        return []

    possible_keys = [
        "options_rows",
        "rows",
        "top",
        "top_5",
        "opportunities",
        "decision_rows",
        "sample_rows",
    ]

    for k in possible_keys:
        v = snapshot.get(k)
        if isinstance(v, list):
            return v

    options = snapshot.get("options")
    if isinstance(options, dict):
        for k in possible_keys:
            v = options.get(k)
            if isinstance(v, list):
                return v

    decision = snapshot.get("decision")
    if isinstance(decision, dict):
        for k in possible_keys:
            v = decision.get(k)
            if isinstance(v, list):
                return v

    return []


def _v25_extract_technical(snapshot):
    if not isinstance(snapshot, dict):
        return {}

    tech = snapshot.get("technical_snapshot")
    if isinstance(tech, dict):
        return tech

    tech = snapshot.get("technical")
    if isinstance(tech, dict):
        return tech

    safe = _v25_safe_read_json("runtime/technical_snapshot_by_ticker_safe.json", default={})
    if isinstance(safe, dict):
        return safe

    return {}


def _v25_extract_market(snapshot):
    if not isinstance(snapshot, dict):
        return {}
    market = snapshot.get("market_data")
    if isinstance(market, dict):
        return market
    market = snapshot.get("market")
    if isinstance(market, dict):
        return market
    return {}


def _v25_extract_portfolio(snapshot):
    if not isinstance(snapshot, dict):
        return {}
    portfolio = snapshot.get("portfolio")
    if isinstance(portfolio, dict):
        return portfolio
    return {}


def _v25_ticker_upper(ticker):
    return str(ticker or "").upper().strip()


def _v25_rows_for_ticker(rows, ticker):
    t = _v25_ticker_upper(ticker)
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        rt = _v25_ticker_upper(r.get("ticker") or r.get("symbol") or r.get("underlying"))
        if rt == t:
            out.append(r)
    return out


def _v25_best_row(rows):
    if not rows:
        return None

    def score_key(r):
        if not isinstance(r, dict):
            return -999999
        for k in ["combined_score", "score", "master_score", "technical_score"]:
            try:
                if r.get(k) is not None:
                    return float(r.get(k))
            except Exception:
                pass
        return 0

    return sorted(rows, key=score_key, reverse=True)[0]


def _v25_get_technical_for_ticker(technical, ticker):
    t = _v25_ticker_upper(ticker)
    if not isinstance(technical, dict):
        return {}

    direct = technical.get(t)
    if isinstance(direct, dict):
        return direct

    snap = technical.get("snapshot")
    if isinstance(snap, dict):
        direct = snap.get(t)
        if isinstance(direct, dict):
            return direct

    by_ticker = technical.get("by_ticker")
    if isinstance(by_ticker, dict):
        direct = by_ticker.get(t)
        if isinstance(direct, dict):
            return direct

    return {}


def _v25_has_bullish_technical(tech):
    if not isinstance(tech, dict):
        return False

    trend = str(tech.get("trend") or tech.get("bias") or "").upper()
    score = tech.get("score")
    rsi = tech.get("rsi")
    adx = tech.get("adx")
    support_near = tech.get("support_near")
    resistance_near = tech.get("resistance_near")

    try:
        score_ok = score is not None and float(score) >= 70
    except Exception:
        score_ok = False

    try:
        rsi_ok = rsi is not None and 45 <= float(rsi) <= 70
    except Exception:
        rsi_ok = False

    try:
        adx_ok = adx is not None and float(adx) >= 18
    except Exception:
        adx_ok = False

    trend_ok = trend in ["BULLISH", "ALCISTA", "UP", "LONG"]

    return bool(trend_ok and (score_ok or rsi_ok or adx_ok or support_near is True) and resistance_near is not True)


def _v25_has_bearish_technical(tech):
    if not isinstance(tech, dict):
        return False

    trend = str(tech.get("trend") or tech.get("bias") or "").upper()
    score = tech.get("score")
    rsi = tech.get("rsi")
    adx = tech.get("adx")
    resistance_near = tech.get("resistance_near")
    support_near = tech.get("support_near")

    try:
        score_ok = score is not None and float(score) >= 70
    except Exception:
        score_ok = False

    try:
        rsi_ok = rsi is not None and 30 <= float(rsi) <= 55
    except Exception:
        rsi_ok = False

    try:
        adx_ok = adx is not None and float(adx) >= 18
    except Exception:
        adx_ok = False

    trend_ok = trend in ["BEARISH", "BAJISTA", "DOWN", "SHORT"]

    return bool(trend_ok and (score_ok or rsi_ok or adx_ok or resistance_near is True) and support_near is not True)


def _v25_market_hours():
    # Prefer existing market-hours endpoint if available indirectly through runtime behavior.
    # Conservative fallback: unknown/open. Final decision still requires live options rows.
    return {
        "status": "UNKNOWN",
        "label": "Market hours no confirmado por V25",
        "is_regular_market_open": None,
        "options_bidask_expected": None,
        "generated_at": _v25_now_iso(),
    }


def _v25_make_decision(ticker):
    t = _v25_ticker_upper(ticker)
    master = _v25_load_master()

    rows = _v25_extract_rows(master)
    technical = _v25_extract_technical(master)
    market = _v25_extract_market(master)
    portfolio = _v25_extract_portfolio(master)

    ticker_rows = _v25_rows_for_ticker(rows, t)
    best = _v25_best_row(ticker_rows)
    tech = _v25_get_technical_for_ticker(technical, t)

    if not master:
        return {
            "engine": "V25_REMOTE_SNAPSHOT_STORE",
            "ticker": t,
            "status": "NO_MASTER_SNAPSHOT",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_V25_MASTER_SNAPSHOT",
            "action": f"{t}: no hay v25_master_snapshot.json todavía. Ejecutar ibkr_bridge.py o enviar POST /v28_ingest_snapshot.",
            "generated_at": _v25_now_iso(),
        }

    if not ticker_rows:
        return {
            "engine": "V25_REMOTE_SNAPSHOT_STORE",
            "ticker": t,
            "status": "NO_ROWS_FOR_TICKER",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_OPTIONS_ROWS_FOR_TICKER",
            "action": f"{t}: hay snapshot maestro, pero no hay rows de opciones para este ticker.",
            "technical": tech,
            "snapshot_meta": {
                "generated_at": master.get("generated_at"),
                "received_at": master.get("received_at"),
                "source": master.get("source"),
            },
            "generated_at": _v25_now_iso(),
        }

    strategy = str((best or {}).get("strategy") or (best or {}).get("strategy_hint") or "UNKNOWN").upper()
    operational_decision = str((best or {}).get("decision") or (best or {}).get("final_decision") or "").upper()
    can_operate_row = bool((best or {}).get("can_operate") is True)
    data_quality = str((best or {}).get("data_quality") or "").upper()
    missing = (best or {}).get("missing_confirmations") or []

    bullish = _v25_has_bullish_technical(tech)
    bearish = _v25_has_bearish_technical(tech)

    technical_fit = "UNKNOWN"
    if strategy in ["NAKED_PUT", "BULL_PUT", "PUT_CREDIT_SPREAD", "CASH_SECURED_PUT"]:
        technical_fit = "CONFIRMED" if bullish else "NOT_CONFIRMED"
    elif strategy in ["COVERED_CALL", "BEAR_CALL", "CALL_CREDIT_SPREAD"]:
        technical_fit = "CONFIRMED" if bearish else "NOT_CONFIRMED"

    full_greeks = "FULL_WITH_GREEKS" in data_quality or not missing
    entry_like = operational_decision in ["ENTRY", "ENTRY_READY", "OPERAR", "READY"]

    if can_operate_row and full_greeks and technical_fit == "CONFIRMED":
        final_state = "ENTRY_READY"
        decision = "ENTRY_READY"
        can_operate = True
        severity = "green"
        main_blocker = None
        action = f"{t}: posible entrada. Validar tamaño, spread, liquidez y riesgo final antes de ejecutar."
    elif can_operate_row and full_greeks and technical_fit != "CONFIRMED":
        final_state = "WAIT_TECHNICAL_CONFIRMATION"
        decision = "WAIT_TECHNICAL_CONFIRMATION"
        can_operate = False
        severity = "yellow"
        main_blocker = "TECHNICAL_NOT_CONFIRMED"
        action = f"{t}: opciones operables, pero falta confirmación técnica para estrategia {strategy}."
    elif ticker_rows:
        final_state = "RADAR"
        decision = "RADAR"
        can_operate = False
        severity = "gray"
        main_blocker = "NOT_FULLY_CONFIRMED"
        action = f"{t}: mantener en radar. Validar greeks, bid/ask, spread, liquidez y confirmación técnica."
    else:
        final_state = "NO_DATA"
        decision = "NO_DATA"
        can_operate = False
        severity = "red"
        main_blocker = "NO_DATA"
        action = f"{t}: sin datos suficientes."

    return {
        "engine": "V25_REMOTE_SNAPSHOT_STORE",
        "ticker": t,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": main_blocker,
        "action": action,
        "strategy": strategy,
        "technical_fit": technical_fit,
        "technical": tech,
        "best_row": best,
        "rows_found_for_ticker": len(ticker_rows),
        "total_rows_found": len(rows),
        "market": market,
        "portfolio_available": bool(portfolio),
        "snapshot_meta": {
            "generated_at": master.get("generated_at"),
            "received_at": master.get("received_at"),
            "source": master.get("source"),
        },
        "generated_at": _v25_now_iso(),
    }


def _v25_html_escape(x):
    return (
        str(x)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@app.post("/v25_ingest_snapshot")
async def v25_ingest_snapshot(payload: dict):
    saved = _v28_ingest_payload(
        payload,
        ingest_engine="V25_REMOTE_SNAPSHOT_STORE",
        ingest_path="/v25_ingest_snapshot",
    )

    return {
        "engine": "V25_REMOTE_SNAPSHOT_STORE",
        "status": "OK",
        "stored_file": str(_V25_MASTER_FILE),
        "canonical_stored_file": str(_V28_MASTER_FILE),
        "rows_found": saved.get("rows_found"),
        "technical_available": saved.get("technical_available"),
        "tickers_detected": saved.get("tickers_detected"),
        "received_at": saved.get("received_at"),
        "delegated_to": "/v28_ingest_snapshot",
    }

# LEGACY COMPATIBILITY ONLY: keep V25 routes stable for older clients.
@app.get("/v25_system_status")
async def v25_system_status():
    master = _v25_load_master()
    rows = _v25_extract_rows(master)
    technical = _v25_extract_technical(master)

    tickers = set()
    for r in rows:
        if isinstance(r, dict):
            tk = _v25_ticker_upper(r.get("ticker") or r.get("symbol") or r.get("underlying"))
            if tk:
                tickers.add(tk)

    if isinstance(technical, dict):
        for k in technical.keys():
            if isinstance(k, str) and len(k) <= 8 and k.upper() == k:
                tickers.add(k)

    return _annotate_legacy_response({
        "engine": "V25_REMOTE_SNAPSHOT_STORE",
        "status": "OK" if bool(master) else "NO_MASTER_SNAPSHOT",
        "master_snapshot_available": bool(master),
        "master_file": str(_V25_MASTER_FILE),
        "rows_found": len(rows),
        "technical_available": bool(technical),
        "tickers_detected": sorted(tickers),
        "snapshot_meta": {
            "generated_at": master.get("generated_at") if isinstance(master, dict) else None,
            "received_at": master.get("received_at") if isinstance(master, dict) else None,
            "source": master.get("source") if isinstance(master, dict) else None,
        },
        "endpoints": {
            "ingest": "/v25_ingest_snapshot",
            "canonical_ingest": "/v28_ingest_snapshot",
            "status": "/v25_system_status",
            "decision_example": "/v25_trade_decision/QQQ",
            "dashboard": "/v25_dashboard",
            "dashboard_ticker_example": "/v25_dashboard/QQQ",
        },
        "generated_at": _v25_now_iso(),
    }, "V25_REMOTE_SNAPSHOT_STORE", endpoints=["/v25_system_status"])


@app.get("/v25_trade_decision/{ticker}")
async def v25_trade_decision(ticker: str):
    return _annotate_legacy_response(
        _v25_make_decision(ticker),
        "V25_REMOTE_SNAPSHOT_STORE",
        endpoints=["/v25_trade_decision/{ticker}"],
    )


@app.get("/v25_dashboard")
async def v25_dashboard():
    master = _v25_load_master()
    rows = _v25_extract_rows(master)
    technical = _v25_extract_technical(master)

    tickers = set()
    for r in rows:
        if isinstance(r, dict):
            tk = _v25_ticker_upper(r.get("ticker") or r.get("symbol") or r.get("underlying"))
            if tk:
                tickers.add(tk)

    if isinstance(technical, dict):
        for k in technical.keys():
            if isinstance(k, str) and len(k) <= 8 and k.upper() == k:
                tickers.add(k)

    if not tickers:
        tickers = {"QQQ"}

    decisions = [_v25_make_decision(t) for t in sorted(tickers)]

    rows_html = ""
    for d in decisions:
        sev = d.get("severity", "gray")
        color = {"green": "#16a34a", "yellow": "#ca8a04", "red": "#dc2626", "gray": "#64748b"}.get(sev, "#64748b")
        rows_html += f"""
        <tr>
          <td><a href="/v25_dashboard/{_v25_html_escape(d.get('ticker'))}">{_v25_html_escape(d.get('ticker'))}</a></td>
          <td><span class="pill" style="background:{color};">{_v25_html_escape(d.get('final_state'))}</span></td>
          <td>{_v25_html_escape(d.get('strategy'))}</td>
          <td>{_v25_html_escape(d.get('technical_fit'))}</td>
          <td>{_v25_html_escape(d.get('rows_found_for_ticker'))}</td>
          <td>{'Sí' if d.get('can_operate') else 'No'}</td>
          <td>{_v25_html_escape(d.get('main_blocker'))}</td>
          <td>{_v25_html_escape(d.get('action'))}</td>
        </tr>
        """

    html = f"""
    <html>
    <head>
      <title>V25 Remote Snapshot Store</title>
      <style>
        body {{ font-family: Inter, Arial, sans-serif; background:#f5f7fb; color:#0f172a; margin:0; padding:32px; }}
        h1 {{ font-size:34px; margin-bottom:18px; }}
        .hero {{ background:#0f172a; color:white; border-radius:26px; padding:34px; margin-bottom:24px; }}
        .grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:16px; margin-bottom:24px; }}
        .card {{ background:white; border-radius:18px; padding:20px; box-shadow:0 12px 30px rgba(15,23,42,.08); }}
        .num {{ font-size:32px; font-weight:800; }}
        table {{ width:100%; border-collapse:collapse; background:white; border-radius:18px; overflow:hidden; box-shadow:0 12px 30px rgba(15,23,42,.08); }}
        th, td {{ text-align:left; padding:14px 16px; border-bottom:1px solid #e5e7eb; font-size:14px; }}
        th {{ color:#64748b; letter-spacing:.08em; text-transform:uppercase; font-size:12px; }}
        .pill {{ color:white; padding:7px 11px; border-radius:999px; font-weight:800; font-size:12px; }}
        a {{ color:#1d4ed8; font-weight:700; }}
        .small {{ color:#64748b; font-size:13px; margin-top:18px; }}
      </style>
    </head>
    <body>
      <h1>V25 — Remote Snapshot Store Dashboard</h1>
      <div class="hero">
        <h2>Fuente única maestra activa</h2>
        <p>Consolida snapshot local de IBKR + opciones + técnico + decisión en un solo archivo remoto.</p>
        <p>Generado: {_v25_html_escape(_v25_now_iso())}</p>
      </div>
      <div class="grid">
        <div class="card"><div>Master snapshot</div><div class="num">{'Sí' if bool(master) else 'No'}</div></div>
        <div class="card"><div>Rows encontradas</div><div class="num">{len(rows)}</div></div>
        <div class="card"><div>Technical disponible</div><div class="num">{'Sí' if bool(technical) else 'No'}</div></div>
        <div class="card"><div>Tickers detectados</div><div class="num">{len(tickers)}</div></div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Estado</th>
            <th>Estrategia</th>
            <th>Técnico</th>
            <th>Rows</th>
            <th>Operable</th>
            <th>Bloqueador</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p class="small">Endpoints: /v25_system_status · /v25_trade_decision/QQQ · /v25_dashboard/QQQ · POST /v25_ingest_snapshot (legacy) · POST /v28_ingest_snapshot (canonical)</p>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/v25_dashboard/{ticker}")
async def v25_dashboard_ticker(ticker: str):
    d = _v25_make_decision(ticker)
    sev = d.get("severity", "gray")
    color = {"green": "#16a34a", "yellow": "#ca8a04", "red": "#dc2626", "gray": "#64748b"}.get(sev, "#64748b")

    best = d.get("best_row") or {}
    tech = d.get("technical") or {}

    html = f"""
    <html>
    <head>
      <title>V25 {ticker}</title>
      <style>
        body {{ font-family: Inter, Arial, sans-serif; background:#f5f7fb; color:#0f172a; margin:0; padding:32px; }}
        h1 {{ font-size:34px; }}
        .hero {{ background:#0f172a; color:white; border-radius:26px; padding:34px; margin-bottom:24px; }}
        .pill {{ display:inline-block; color:white; background:{color}; padding:8px 14px; border-radius:999px; font-weight:800; }}
        .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
        .card {{ background:white; border-radius:18px; padding:22px; box-shadow:0 12px 30px rgba(15,23,42,.08); }}
        pre {{ white-space:pre-wrap; background:#0f172a; color:white; padding:18px; border-radius:14px; overflow:auto; }}
        a {{ color:#1d4ed8; font-weight:700; }}
      </style>
    </head>
    <body>
      <h1>V25 — {_v25_html_escape(ticker)}</h1>
      <div class="hero">
        <div class="pill">{_v25_html_escape(d.get('final_state'))}</div>
        <h2>{_v25_html_escape(d.get('decision'))}</h2>
        <p>{_v25_html_escape(d.get('action'))}</p>
      </div>
      <div class="grid">
        <div class="card">
          <h3>Resumen</h3>
          <p><b>Can operate:</b> {'Sí' if d.get('can_operate') else 'No'}</p>
          <p><b>Estrategia:</b> {_v25_html_escape(d.get('strategy'))}</p>
          <p><b>Technical fit:</b> {_v25_html_escape(d.get('technical_fit'))}</p>
          <p><b>Rows ticker:</b> {_v25_html_escape(d.get('rows_found_for_ticker'))}</p>
          <p><b>Bloqueador:</b> {_v25_html_escape(d.get('main_blocker'))}</p>
        </div>
        <div class="card">
          <h3>Técnico</h3>
          <pre>{_v25_html_escape(_v25_json.dumps(tech, ensure_ascii=False, indent=2, default=str))}</pre>
        </div>
      </div>
      <div class="card" style="margin-top:18px;">
        <h3>Best Row</h3>
        <pre>{_v25_html_escape(_v25_json.dumps(best, ensure_ascii=False, indent=2, default=str))}</pre>
      </div>
      <p><a href="/v25_dashboard">Volver al dashboard V25</a></p>
    </body>
    </html>
    """
    return HTMLResponse(html)

# === END V25 REMOTE SNAPSHOT STORE / UNIFIED INGEST ===



# ============================================================
# V27 TECHNICAL RESOLVER + UNIFIED DECISION QUALITY
# ============================================================
from pathlib import Path as _V27Path
from datetime import datetime as _V27DateTime, timezone as _V27Timezone
import json as _v27_json
import math as _v27_math
from fastapi.responses import HTMLResponse as _V27HTMLResponse

_V27_RUNTIME_DIR = _V27Path("runtime")
_V27_MASTER_FILE = _V27_RUNTIME_DIR / "v25_master_snapshot.json"
_V27_TECH_SAFE_FILE = _V27_RUNTIME_DIR / "technical_snapshot_by_ticker_safe.json"
_V27_TECH_ALT_FILE = _V27_RUNTIME_DIR / "technical_snapshot_by_ticker.json"
_V27_DECISION_FILE = _V27_RUNTIME_DIR / "v27_last_decision.json"

_V27_ALLOWED_TICKERS = {
    "QQQ", "SPY", "NVDA", "TSLA", "META", "AAPL", "MSFT", "AMZN", "NFLX", "TLT", "IWM", "DIA", "AMD", "GOOGL", "GOOG"
}

_V27_REJECT_KEYS = {
    "NEXT_BEST_ACTION", "SUMMARY", "DASHBOARD", "SYSTEM_STATUS", "GPT_SUMMARY",
    "DECISION", "EXECUTIVE_CONCLUSION", "MARKET_HOURS", "URLS", "HEALTH"
}

def _v27_now():
    return _V27DateTime.now(_V27Timezone.utc).isoformat()

def _v27_safe_float(x, default=None):
    try:
        if x is None:
            return default
        if isinstance(x, str) and not x.strip():
            return default
        v = float(x)
        if _v27_math.isnan(v) or _v27_math.isinf(v):
            return default
        return v
    except Exception:
        return default

def _v27_load_json_file(path):
    try:
        p = _V27Path(path)
        if not p.exists():
            return None
        return _v27_json.loads(p.read_text())
    except Exception:
        return None

def _v27_save_json_file(path, payload):
    try:
        p = _V27Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_v27_json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return True
    except Exception:
        return False

def _v27_normalize_ticker(t):
    if t is None:
        return None
    t = str(t).upper().strip()
    t = t.replace("/", "").replace("\\", "")
    t = t.replace(":", "").replace(" ", "")
    if not t:
        return None
    if t in _V27_REJECT_KEYS:
        return None
    if len(t) > 8:
        return None
    if not all(ch.isalnum() or ch in {".", "-"} for ch in t):
        return None
    return t

def _v27_is_valid_ticker(t):
    t = _v27_normalize_ticker(t)
    if not t:
        return False
    if t in _V27_REJECT_KEYS:
        return False
    if t in _V27_ALLOWED_TICKERS:
        return True
    # Allow normal equity/ETF tickers but reject obvious metadata words.
    if 1 <= len(t) <= 6 and t.isalpha():
        return True
    return False

def _v27_extract_technical_candidate(obj):
    if not isinstance(obj, dict):
        return None

    raw_ticker = obj.get("ticker") or obj.get("symbol") or obj.get("underlying") or obj.get("asset")
    ticker = _v27_normalize_ticker(raw_ticker)
    if not _v27_is_valid_ticker(ticker):
        return None

    trend = str(obj.get("trend") or obj.get("bias") or obj.get("technical_bias") or "UNKNOWN").upper().strip()
    if trend in {"UP", "BULL", "BULLISH_TREND"}:
        trend = "BULLISH"
    elif trend in {"DOWN", "BEAR", "BEARISH_TREND"}:
        trend = "BEARISH"
    elif trend in {"SIDEWAYS", "FLAT", "RANGE"}:
        trend = "NEUTRAL"

    score = _v27_safe_float(obj.get("score") or obj.get("technical_score"), None)
    rsi = _v27_safe_float(obj.get("rsi"), None)
    adx = _v27_safe_float(obj.get("adx"), None)
    volume_relative = _v27_safe_float(obj.get("volume_relative") or obj.get("relative_volume"), None)

    vwap_position = str(obj.get("vwap_position") or obj.get("vwap") or "UNKNOWN").lower().strip()
    support_near = bool(obj.get("support_near", False))
    resistance_near = bool(obj.get("resistance_near", False))
    range_breakout = bool(obj.get("range_breakout", False))
    event_risk = bool(obj.get("event_risk", False))

    # Minimum shape: must have ticker and at least one real technical field.
    technical_fields_present = any([
        trend != "UNKNOWN",
        score is not None,
        rsi is not None,
        adx is not None,
        vwap_position not in {"", "unknown", "none"},
        volume_relative is not None,
        support_near,
        resistance_near,
        range_breakout,
    ])

    if not technical_fields_present:
        return None

    return {
        "ticker": ticker,
        "trend": trend,
        "bias": trend,
        "score": score,
        "rsi": rsi,
        "adx": adx,
        "vwap_position": vwap_position,
        "volume_relative": volume_relative,
        "support_near": support_near,
        "resistance_near": resistance_near,
        "range_breakout": range_breakout,
        "event_risk": event_risk,
        "source": obj.get("source") or "V27_TECHNICAL_RESOLVER",
        "received_at": obj.get("received_at") or obj.get("generated_at") or _v27_now(),
        "raw": obj,
    }

def _v27_flatten_possible_technical_objects(data):
    out = []

    def walk(x):
        if isinstance(x, dict):
            cand = _v27_extract_technical_candidate(x)
            if cand:
                out.append(cand)

            # Common structures: by ticker, snapshot, technical_snapshot, technical.
            for k, v in x.items():
                nk = _v27_normalize_ticker(k)
                if isinstance(v, dict) and _v27_is_valid_ticker(nk):
                    merged = dict(v)
                    merged.setdefault("ticker", nk)
                    cand2 = _v27_extract_technical_candidate(merged)
                    if cand2:
                        out.append(cand2)
                if isinstance(v, (dict, list)):
                    walk(v)

        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(data)
    return out

def _v27_load_technical_map():
    sources = []
    for path in [_V27_TECH_SAFE_FILE, _V27_TECH_ALT_FILE, _V27_MASTER_FILE]:
        data = _v27_load_json_file(path)
        if data is not None:
            sources.append((str(path), data))

    tech_map = {}
    diagnostics = []

    for path, data in sources:
        candidates = _v27_flatten_possible_technical_objects(data)
        diagnostics.append({
            "path": path,
            "candidates_found": len(candidates),
            "tickers": sorted(list({c["ticker"] for c in candidates if c.get("ticker")})),
        })
        for cand in candidates:
            t = cand.get("ticker")
            if _v27_is_valid_ticker(t):
                existing = tech_map.get(t)
                # Prefer candidate with score and more fields.
                current_quality = sum(1 for k in ["score", "rsi", "adx", "vwap_position", "volume_relative"] if cand.get(k) not in [None, "", "UNKNOWN"])
                previous_quality = 0
                if existing:
                    previous_quality = sum(1 for k in ["score", "rsi", "adx", "vwap_position", "volume_relative"] if existing.get(k) not in [None, "", "UNKNOWN"])
                if not existing or current_quality >= previous_quality:
                    tech_map[t] = cand

    return tech_map, diagnostics

def _v27_get_master_snapshot():
    master = _v27_load_json_file(_V27_MASTER_FILE)
    if isinstance(master, dict):
        return master
    return {}

def _v27_extract_option_rows(master):
    rows = []
    if not isinstance(master, dict):
        return rows

    possible_keys = ["options_rows", "rows", "top", "sample_rows", "best_rows"]
    for key in possible_keys:
        val = master.get(key)
        if isinstance(val, list):
            rows.extend([x for x in val if isinstance(x, dict)])

    # Some previous versions store rows nested under options.
    options = master.get("options")
    if isinstance(options, dict):
        for key in possible_keys:
            val = options.get(key)
            if isinstance(val, list):
                rows.extend([x for x in val if isinstance(x, dict)])

    # Deduplicate lightly.
    cleaned = []
    seen = set()
    for r in rows:
        t = _v27_normalize_ticker(r.get("ticker"))
        strategy = str(r.get("strategy") or r.get("strategy_hint") or "").upper()
        price = str(r.get("price") or r.get("premium") or r.get("option_price") or "")
        decision = str(r.get("decision") or r.get("final_decision") or "").upper()
        key = (t, strategy, price, decision)
        if t and key not in seen:
            seen.add(key)
            rr = dict(r)
            rr["ticker"] = t
            cleaned.append(rr)
    return cleaned

def _v27_market_hours(master):
    mh = {}
    if isinstance(master, dict):
        mh = master.get("market_hours") or {}
        if isinstance(mh, dict) and "market_hours" in mh and isinstance(mh.get("market_hours"), dict):
            mh = mh.get("market_hours")
    if not isinstance(mh, dict):
        mh = {}
    label = mh.get("label") or mh.get("market_hours_label") or "UNKNOWN"
    is_open = bool(mh.get("is_regular_market_open", False) or mh.get("is_open", False))
    options_bidask_expected = bool(mh.get("options_bidask_expected", False))
    return {
        "label": label,
        "is_regular_market_open": is_open,
        "options_bidask_expected": options_bidask_expected,
        "raw": mh,
    }

def _v27_strategy_matches_technical(strategy, technical):
    strategy = str(strategy or "").upper()
    trend = str((technical or {}).get("trend") or (technical or {}).get("bias") or "UNKNOWN").upper()

    if strategy in {"NAKED_PUT", "SHORT_PUT", "BULL_PUT_SPREAD"}:
        return trend in {"BULLISH", "NEUTRAL"}
    if strategy in {"COVERED_CALL", "SHORT_CALL", "BEAR_CALL_SPREAD"}:
        return trend in {"BEARISH", "NEUTRAL", "BULLISH"}  # covered call can be management/neutral-income
    if strategy in {"IRON_CONDOR"}:
        return trend in {"NEUTRAL", "RANGE", "SIDEWAYS"}
    return False

def _v27_technical_confirmed_for_strategy(strategy, technical):
    if not technical:
        return False, "NO_TECHNICAL_SNAPSHOT"

    trend = str(technical.get("trend") or "UNKNOWN").upper()
    score = _v27_safe_float(technical.get("score"), None)
    rsi = _v27_safe_float(technical.get("rsi"), None)
    adx = _v27_safe_float(technical.get("adx"), None)
    event_risk = bool(technical.get("event_risk", False))

    if event_risk:
        return False, "TECHNICAL_EVENT_RISK"

    if trend == "UNKNOWN":
        return False, "TECHNICAL_TREND_UNKNOWN"

    if score is not None and score < 60:
        return False, "TECHNICAL_SCORE_LOW"

    if rsi is not None and (rsi < 35 or rsi > 75):
        return False, "TECHNICAL_RSI_EXTREME"

    if adx is not None and adx < 10:
        return False, "TECHNICAL_ADX_WEAK"

    if not _v27_strategy_matches_technical(strategy, technical):
        return False, "TECHNICAL_STRATEGY_MISMATCH"

    return True, "TECHNICAL_CONFIRMED"

def _v27_row_operable(row):
    decision = str(row.get("decision") or row.get("final_decision") or "").upper()
    can_operate = bool(row.get("can_operate", False))
    quality = str(row.get("data_quality") or row.get("quality") or "").upper()
    missing = row.get("missing_confirmations") or row.get("missing_data") or []
    if missing is None:
        missing = []
    if isinstance(missing, str):
        missing = [missing]

    has_full_greeks = "FULL_WITH_GREEKS" in quality or "WITH_GREEKS" in quality
    entry_like = decision in {"ENTRY", "OPERAR", "ENTRY_READY", "BUY", "SELL", "RADAR"} or can_operate

    if can_operate and has_full_greeks and not missing:
        return True, "OPTIONS_CONFIRMED"
    if entry_like and has_full_greeks and not missing:
        return True, "OPTIONS_CONFIRMED"
    if not has_full_greeks:
        return False, "WAIT_OPTIONS_GREEKS"
    if missing:
        return False, "WAIT_OPTIONS_CONFIRMATIONS"
    return False, "WAIT_OPTIONS_DATA"

def _v27_score_row(row):
    score = _v27_safe_float(row.get("score") or row.get("combined_score") or row.get("master_score"), 0) or 0
    price = _v27_safe_float(row.get("price") or row.get("premium") or row.get("option_price"), 0) or 0
    can_operate = 1 if row.get("can_operate") else 0
    quality_bonus = 10 if "FULL_WITH_GREEKS" in str(row.get("data_quality") or "").upper() else 0
    return score + quality_bonus + can_operate * 25 + min(price, 20) * 0.1

def _v27_choose_best_option_row(ticker, rows):
    ticker = _v27_normalize_ticker(ticker)
    filtered = [r for r in rows if _v27_normalize_ticker(r.get("ticker")) == ticker]
    if not filtered:
        return None
    return sorted(filtered, key=_v27_score_row, reverse=True)[0]

def _v27_decide_for_ticker(ticker):
    ticker = _v27_normalize_ticker(ticker)
    master = _v27_get_master_snapshot()
    rows = _v27_extract_option_rows(master)
    tech_map, tech_diag = _v27_load_technical_map()
    market = _v27_market_hours(master)

    best_row = _v27_choose_best_option_row(ticker, rows)
    technical = tech_map.get(ticker)

    if not best_row and not technical:
        result = {
            "engine": "V27_TECHNICAL_RESOLVER_DECISION",
            "generated_at": _v27_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_OPTIONS_OR_TECHNICAL_DATA",
            "action": f"{ticker}: no hay datos técnicos ni opciones disponibles.",
            "executive_summary": f"{ticker}: no hay datos suficientes para evaluar operación.",
            "strategy": "UNKNOWN",
            "technical_fit": "NO_TECHNICAL",
            "technical": technical or {},
            "best_row": best_row or {},
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "market": market,
            "diagnostics": {
                "technical_sources": tech_diag,
                "technical_tickers": sorted(list(tech_map.keys())),
                "master_snapshot_available": bool(master),
            },
        }
        _v27_save_json_file(_V27_DECISION_FILE, result)
        return result

    if not best_row:
        result = {
            "engine": "V27_TECHNICAL_RESOLVER_DECISION",
            "generated_at": _v27_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "WAIT_OPTIONS_DATA",
            "decision": "WAIT_OPTIONS_DATA",
            "can_operate": False,
            "severity": "yellow",
            "main_blocker": "NO_OPTIONS_ROW_FOR_TICKER",
            "action": f"{ticker}: técnico disponible, pero falta oportunidad de opciones.",
            "executive_summary": f"{ticker}: técnico disponible, pero no hay fila de opciones operable.",
            "strategy": "UNKNOWN",
            "technical_fit": "TECHNICAL_AVAILABLE",
            "technical": technical or {},
            "best_row": {},
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "market": market,
            "diagnostics": {
                "technical_sources": tech_diag,
                "technical_tickers": sorted(list(tech_map.keys())),
                "master_snapshot_available": bool(master),
            },
        }
        _v27_save_json_file(_V27_DECISION_FILE, result)
        return result

    strategy = str(best_row.get("strategy") or best_row.get("strategy_hint") or "UNKNOWN").upper()
    option_ok, option_reason = _v27_row_operable(best_row)
    technical_ok, technical_reason = _v27_technical_confirmed_for_strategy(strategy, technical)

    market_open = bool(market.get("is_regular_market_open"))
    bidask_expected = bool(market.get("options_bidask_expected"))
    market_ok = market_open and bidask_expected

    canonical = _canonical_decision_state(
        ticker=ticker,
        strategy=strategy,
        option_ok=option_ok,
        option_reason=option_reason,
        technical_ok=technical_ok,
        technical_reason=technical_reason,
        market_ok=market_ok,
        row=best_row,
        technical=technical,
    )
    final_state = canonical["final_state"]
    decision = canonical["decision"]
    severity = canonical["severity"]
    blocker = canonical["main_blocker"]
    action = canonical["action"]

    tech_score = None if not technical else technical.get("score")
    opt_score = best_row.get("score") or best_row.get("combined_score") or best_row.get("master_score")
    executive_summary = (
        f"{ticker}: estado {final_state}. Estrategia sugerida/observada: {strategy}. "
        f"Opciones: {option_reason}. Técnico: {technical_reason}. "
        f"Sesgo técnico: {(technical or {}).get('trend', 'UNKNOWN')}. "
        f"Score opciones: {opt_score}. Score técnico: {tech_score}. "
        f"Acción: {action}"
    )

    result = {
        "engine": "V27_TECHNICAL_RESOLVER_DECISION",
        "generated_at": _v27_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": canonical["can_operate"],
        "severity": severity,
        "main_blocker": blocker,
        "blockers": canonical["blockers"],
        "action": action,
        "executive_summary": executive_summary,
        "strategy": strategy,
        "technical_fit": technical_reason,
        "options_fit": option_reason,
        "risk_fit": "STRATEGY_RISK_CONFIRMED" if canonical["risk_gate"]["ok"] else ",".join(canonical["risk_gate"]["blockers"]),
        "technical": technical or {},
        "technical_score": tech_score,
        "technical_bias": (technical or {}).get("trend", "UNKNOWN"),
        "options_score": opt_score,
        "best_row": best_row,
        "rows_found_for_ticker": len([r for r in rows if _v27_normalize_ticker(r.get("ticker")) == ticker]),
        "total_rows_found": len(rows),
        "market": market,
        "risk_gate": canonical["risk_gate"],
        "diagnostics": {
            "technical_sources": tech_diag,
            "technical_tickers": sorted(list(tech_map.keys())),
            "master_snapshot_available": bool(master),
            "technical_available": bool(technical),
            "options_available": bool(best_row),
        },
    }
    _v27_save_json_file(_V27_DECISION_FILE, result)
    return result

def _v27_html_escape(x):
    import html
    return html.escape("" if x is None else str(x))

def _v27_badge_color(state):
    state = str(state or "").upper()
    if state == "ENTRY_READY":
        return "#16a34a"
    if "WAIT_TECHNICAL" in state:
        return "#f59e0b"
    if "WAIT_OPTIONS" in state:
        return "#f97316"
    if "WAIT_MARKET" in state:
        return "#64748b"
    if "BLOCKED" in state or "NO_DATA" in state:
        return "#dc2626"
    return "#64748b"

def _v27_dashboard_html(tickers=None):
    if not tickers:
        tickers = ["QQQ", "SPY", "NVDA", "TSLA", "META", "TLT"]

    decisions = [_v27_decide_for_ticker(t) for t in tickers]
    entry_count = sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY")
    wait_tech = sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL")
    wait_options = sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA")
    risk_blocked = sum(1 for d in decisions if d.get("final_state") == "RISK_BLOCKED")
    no_data = sum(1 for d in decisions if d.get("final_state") == "NO_DATA")

    rows = ""
    for d in decisions:
        state = d.get("final_state")
        color = _v27_badge_color(state)
        ticker = d.get("ticker")
        rows += f"""
        <tr>
          <td><a href="/v27_trade_decision/{_v27_html_escape(ticker)}">{_v27_html_escape(ticker)}</a></td>
          <td><span class="badge" style="background:{color};">{_v27_html_escape(state)}</span></td>
          <td>{_v27_html_escape(d.get("strategy"))}</td>
          <td>{_v27_html_escape(d.get("technical_bias"))}</td>
          <td>{_v27_html_escape(d.get("technical_score"))}</td>
          <td>{_v27_html_escape(d.get("options_score"))}</td>
          <td>{'Sí' if d.get("can_operate") else 'No'}</td>
          <td>{_v27_html_escape(d.get("main_blocker"))}</td>
          <td>{_v27_html_escape(d.get("action"))}</td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>V27 Trading Decision Dashboard</title>
      <style>
        body {{
          margin:0;
          padding:36px;
          background:#f4f6fa;
          color:#0f172a;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
        }}
        h1 {{ font-size:34px; margin:0 0 22px; }}
        .hero {{
          background:#0f172a;
          color:white;
          padding:34px;
          border-radius:24px;
          margin-bottom:28px;
          box-shadow:0 20px 50px rgba(15,23,42,.12);
        }}
        .hero h2 {{ margin:0 0 12px; font-size:28px; }}
        .cards {{
          display:grid;
          grid-template-columns:repeat(5,minmax(0,1fr));
          gap:16px;
          margin-bottom:24px;
        }}
        .card {{
          background:white;
          border-radius:16px;
          padding:20px;
          box-shadow:0 12px 30px rgba(15,23,42,.08);
        }}
        .card .label {{ color:#64748b; font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.06em; }}
        .card .value {{ font-size:32px; font-weight:800; margin-top:8px; }}
        table {{
          width:100%;
          border-collapse:collapse;
          background:white;
          border-radius:18px;
          overflow:hidden;
          box-shadow:0 16px 40px rgba(15,23,42,.08);
        }}
        th,td {{
          text-align:left;
          padding:14px 16px;
          border-bottom:1px solid #e5e7eb;
          font-size:14px;
          vertical-align:top;
        }}
        th {{
          color:#64748b;
          text-transform:uppercase;
          font-size:12px;
          letter-spacing:.08em;
        }}
        .badge {{
          display:inline-block;
          color:white;
          padding:7px 11px;
          border-radius:999px;
          font-size:12px;
          font-weight:800;
        }}
        .footer {{
          margin-top:20px;
          color:#64748b;
          font-size:13px;
        }}
        a {{ color:#2563eb; font-weight:700; }}
      </style>
    </head>
    <body>
      <h1>V27 — Technical Resolver + Unified Decision Dashboard</h1>
      <div class="hero">
        <h2>Execution Guard activo</h2>
        <p>Consolida técnico real + opciones + mercado para evitar entradas sin confirmación crítica.</p>
        <p>Generado: {_v27_html_escape(_v27_now())}</p>
      </div>

      <div class="cards">
        <div class="card"><div class="label">Entry Ready</div><div class="value">{entry_count}</div></div>
        <div class="card"><div class="label">Wait Technical</div><div class="value">{wait_tech}</div></div>
        <div class="card"><div class="label">Wait Options</div><div class="value">{wait_options}</div></div>
        <div class="card"><div class="label">Risk Blocked</div><div class="value">{risk_blocked}</div></div>
        <div class="card"><div class="label">No Data</div><div class="value">{no_data}</div></div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Estado</th>
            <th>Estrategia</th>
            <th>Sesgo técnico</th>
            <th>Score técnico</th>
            <th>Score opciones</th>
            <th>Operable</th>
            <th>Bloqueador</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>

      <div class="footer">
        Endpoints: /v27_system_status · /v27_trade_decision/QQQ · /v27_dashboard · /v27_technical_resolver
      </div>
    </body>
    </html>
    """
    return html

@app.get("/v27_technical_resolver")
async def v27_technical_resolver():
    tech_map, diagnostics = _v27_load_technical_map()
    return {
        "engine": "V27_TECHNICAL_RESOLVER",
        "generated_at": _v27_now(),
        "status": "OK",
        "technical_available": bool(tech_map),
        "technical_tickers": sorted(list(tech_map.keys())),
        "technical_count": len(tech_map),
        "technical": tech_map,
        "diagnostics": diagnostics,
        "rejected_keywords": sorted(list(_V27_REJECT_KEYS)),
    }

@app.get("/v27_system_status")
async def v27_system_status():
    master = _v27_get_master_snapshot()
    rows = _v27_extract_option_rows(master)
    tech_map, tech_diag = _v27_load_technical_map()
    market = _v27_market_hours(master)
    detected = sorted(list(set([r.get("ticker") for r in rows if r.get("ticker")] + list(tech_map.keys()))))

    return {
        "engine": "V27_TECHNICAL_RESOLVER_DECISION",
        "generated_at": _v27_now(),
        "status": "OK",
        "master_snapshot_available": bool(master),
        "master_file": str(_V27_MASTER_FILE),
        "options_rows_found": len(rows),
        "technical_available": bool(tech_map),
        "technical_tickers": sorted(list(tech_map.keys())),
        "tickers_detected": detected,
        "market": market,
        "endpoints": {
            "technical_resolver": "/v27_technical_resolver",
            "trade_decision_example": "/v27_trade_decision/QQQ",
            "dashboard": "/v27_dashboard",
            "dashboard_ticker_example": "/v27_dashboard/QQQ",
        },
        "diagnostics": {
            "technical_sources": tech_diag,
        },
    }

@app.get("/v27_trade_decision/{ticker}")
async def v27_trade_decision(ticker: str):
    return _v27_decide_for_ticker(ticker)

@app.get("/gpt_v27_trade_decision/{ticker}")
async def gpt_v27_trade_decision(ticker: str):
    d = _v27_decide_for_ticker(ticker)
    return {
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "strategy": d.get("strategy"),
        "technical_bias": d.get("technical_bias"),
        "technical_score": d.get("technical_score"),
        "options_score": d.get("options_score"),
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "risk_note": "No ejecutar sin validar manualmente tamaño, liquidez, spread, evento, capital y tolerancia de riesgo.",
        "engine": d.get("engine"),
        "generated_at": d.get("generated_at"),
    }

@app.get("/v27_dashboard", response_class=_V27HTMLResponse)
async def v27_dashboard():
    return _v27_dashboard_html()

@app.get("/v27_dashboard/{ticker}", response_class=_V27HTMLResponse)
async def v27_dashboard_ticker(ticker: str):
    return _v27_dashboard_html([ticker])

# ============================================================
# END V27 TECHNICAL RESOLVER + UNIFIED DECISION QUALITY
# ============================================================



# ============================================================
# V27.1 RUNTIME DATA RESOLVER HOTFIX
# ============================================================
from pathlib import Path as _V271Path
from datetime import datetime as _V271DateTime, timezone as _V271Timezone
import json as _v271_json
from fastapi.responses import HTMLResponse as _V271HTMLResponse

_V271_RUNTIME_DIR = _V271Path("runtime")

_V271_CANDIDATE_FILES = [
    "v25_master_snapshot.json",
    "v26_master_snapshot.json",
    "v22_2_unified_remote_snapshot.json",
    "v22_1_trade_decision.json",
    "v22_trade_decision.json",
    "decision_desk_snapshot.json",
    "decision_snapshot.json",
    "v18_decision_snapshot.json",
    "v18_decision_desk_snapshot.json",
    "technical_snapshot_by_ticker_safe.json",
    "technical_snapshot_by_ticker.json",
]

def _v271_now():
    return _V271DateTime.now(_V271Timezone.utc).isoformat()

def _v271_load_json(path):
    try:
        p = _V271Path(path)
        if not p.exists():
            return None, f"missing:{p}"
        return _v271_json.loads(p.read_text()), None
    except Exception as e:
        return None, str(e)

def _v271_runtime_inventory_payload():
    files = []
    discovered = []

    try:
        _V271_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        for p in sorted(_V271_RUNTIME_DIR.glob("*.json")):
            discovered.append(str(p))
    except Exception:
        pass

    candidate_paths = []
    for name in _V271_CANDIDATE_FILES:
        candidate_paths.append(_V271_RUNTIME_DIR / name)

    for p in sorted(set(candidate_paths + [_V271Path(x) for x in discovered]), key=lambda x: str(x)):
        data, err = _v271_load_json(p)
        item = {
            "path": str(p),
            "exists": p.exists(),
            "error": err,
            "type": type(data).__name__ if data is not None else None,
            "keys": [],
            "rows_like": 0,
            "ticker_like": [],
            "usable_score": 0,
        }

        if isinstance(data, dict):
            item["keys"] = list(data.keys())[:80]

            rows_like = 0
            for k in ["rows", "top", "top_5", "options_rows", "sample_rows", "best_rows"]:
                if isinstance(data.get(k), list):
                    rows_like += len(data.get(k) or [])

            if isinstance(data.get("options"), dict):
                for k in ["rows", "top", "top_5", "options_rows", "sample_rows", "best_rows"]:
                    if isinstance(data["options"].get(k), list):
                        rows_like += len(data["options"].get(k) or [])

            item["rows_like"] = rows_like

            tickers = set()
            for k in ["ticker", "tickers", "tickers_detected", "technical_tickers", "available_tickers"]:
                v = data.get(k)
                if isinstance(v, str):
                    tickers.add(v.upper())
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, str):
                            tickers.add(x.upper())

            item["ticker_like"] = sorted(list(tickers))[:30]

            score = 0
            if rows_like:
                score += 50
            if "best_row" in data or "best" in data or "next_best_action" in data:
                score += 20
            if "technical" in data or "technical_snapshot" in data or "snapshot" in data:
                score += 20
            if "market_hours" in data or "market" in data:
                score += 10
            if "ticker" in data:
                score += 10
            item["usable_score"] = score

        elif isinstance(data, list):
            item["rows_like"] = len(data)
            item["usable_score"] = 30 if len(data) else 0

        files.append(item)

    best = sorted(files, key=lambda x: x.get("usable_score", 0), reverse=True)
    return {
        "engine": "V27_1_RUNTIME_DATA_RESOLVER",
        "generated_at": _v271_now(),
        "status": "OK",
        "runtime_dir": str(_V271_RUNTIME_DIR),
        "files": files,
        "best_candidates": best[:10],
    }

def _v271_find_best_runtime_snapshot():
    inv = _v271_runtime_inventory_payload()
    candidates = inv.get("best_candidates", [])

    for item in candidates:
        if not item.get("exists"):
            continue
        if item.get("usable_score", 0) <= 0:
            continue
        data, err = _v271_load_json(item.get("path"))
        if data is not None:
            return data, item, inv

    return {}, None, inv

def _v271_rows_from_anywhere(data):
    rows = []

    def add_rows(x):
        if isinstance(x, list):
            for r in x:
                if isinstance(r, dict):
                    rows.append(dict(r))

    if isinstance(data, list):
        add_rows(data)

    if isinstance(data, dict):
        for k in ["rows", "top", "top_5", "options_rows", "sample_rows", "best_rows"]:
            add_rows(data.get(k))

        if isinstance(data.get("options"), dict):
            opt = data.get("options")
            for k in ["rows", "top", "top_5", "options_rows", "sample_rows", "best_rows"]:
                add_rows(opt.get(k))

        for k in ["best_row", "best", "next_best_action", "best_fusion_opportunity"]:
            v = data.get(k)
            if isinstance(v, dict):
                rows.append(dict(v))

        # Some decision objects have one ticker/strategy/decision at top level.
        if any(k in data for k in ["ticker", "strategy", "decision", "final_state", "can_operate"]):
            rows.append(dict(data))

    cleaned = []
    seen = set()
    for r in rows:
        t = None
        try:
            t = _v27_normalize_ticker(r.get("ticker"))
        except Exception:
            t = str(r.get("ticker") or "").upper().strip()

        if not t:
            continue

        if "strategy" not in r:
            r["strategy"] = r.get("best_strategy") or r.get("strategy_hint") or r.get("options_strategy") or "UNKNOWN"

        if "decision" not in r:
            r["decision"] = r.get("final_decision") or r.get("final_state") or r.get("state") or "RADAR"

        if "score" not in r:
            r["score"] = r.get("combined_score") or r.get("master_score") or r.get("options_score")

        if "data_quality" not in r:
            r["data_quality"] = r.get("quality") or r.get("option_quality") or "UNKNOWN"

        r["ticker"] = t

        key = (
            r.get("ticker"),
            str(r.get("strategy")),
            str(r.get("decision")),
            str(r.get("price") or r.get("premium") or r.get("option_price")),
        )
        if key not in seen:
            seen.add(key)
            cleaned.append(r)

    return cleaned

def _v271_technical_from_anywhere(data):
    technical = {}

    def ingest_obj(obj, forced_ticker=None):
        if not isinstance(obj, dict):
            return
        candidate = dict(obj)
        if forced_ticker and "ticker" not in candidate:
            candidate["ticker"] = forced_ticker
        try:
            cand = _v27_extract_technical_candidate(candidate)
        except Exception:
            cand = None
        if cand and cand.get("ticker"):
            technical[cand["ticker"]] = cand

    def walk(x):
        if isinstance(x, dict):
            # dict keyed by ticker
            for k, v in x.items():
                kt = None
                try:
                    kt = _v27_normalize_ticker(k)
                except Exception:
                    kt = str(k).upper().strip()
                if isinstance(v, dict):
                    ingest_obj(v, kt)
                    walk(v)
                elif isinstance(v, list):
                    walk(v)

            for k in ["technical", "technical_snapshot", "snapshot", "raw"]:
                if isinstance(x.get(k), dict):
                    ingest_obj(x.get(k))
                    walk(x.get(k))

            ingest_obj(x)

        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(data)
    return technical

def _v271_market_from_anywhere(data):
    if isinstance(data, dict):
        try:
            return _v27_market_hours(data)
        except Exception:
            pass

        mh = data.get("market_hours") or data.get("market") or {}
        if isinstance(mh, dict):
            return {
                "label": mh.get("label") or mh.get("market_hours_label") or "UNKNOWN",
                "is_regular_market_open": bool(mh.get("is_regular_market_open", False) or mh.get("is_open", False)),
                "options_bidask_expected": bool(mh.get("options_bidask_expected", False)),
                "raw": mh,
            }

    return {
        "label": "UNKNOWN",
        "is_regular_market_open": False,
        "options_bidask_expected": False,
        "raw": {},
    }

def _v271_decide_for_ticker(ticker):
    ticker = _v27_normalize_ticker(ticker)
    data, source_item, inv = _v271_find_best_runtime_snapshot()

    rows = _v271_rows_from_anywhere(data)
    technical_map = _v271_technical_from_anywhere(data)

    # Also merge V27 technical file resolver.
    try:
        tech2, diag2 = _v27_load_technical_map()
        for k, v in tech2.items():
            technical_map.setdefault(k, v)
    except Exception:
        diag2 = []

    market = _v271_market_from_anywhere(data)

    best_row = None
    try:
        best_row = _v27_choose_best_option_row(ticker, rows)
    except Exception:
        filtered = [r for r in rows if str(r.get("ticker")).upper() == ticker]
        best_row = filtered[0] if filtered else None

    technical = technical_map.get(ticker)

    if not best_row and not technical:
        return {
            "engine": "V27_1_RUNTIME_DATA_RESOLVER",
            "generated_at": _v271_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_OPTIONS_OR_TECHNICAL_DATA",
            "action": f"{ticker}: no hay datos técnicos ni opciones disponibles en runtime.",
            "executive_summary": f"{ticker}: V27.1 no encontró filas ni técnico utilizable.",
            "strategy": "UNKNOWN",
            "technical_bias": "UNKNOWN",
            "technical_score": None,
            "options_score": None,
            "best_row": {},
            "technical": {},
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "runtime_source": source_item,
            "inventory_summary": inv.get("best_candidates", [])[:5],
        }

    if not best_row:
        return {
            "engine": "V27_1_RUNTIME_DATA_RESOLVER",
            "generated_at": _v271_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "WAIT_OPTIONS_DATA",
            "decision": "WAIT_OPTIONS_DATA",
            "can_operate": False,
            "severity": "yellow",
            "main_blocker": "NO_OPTIONS_ROW_FOR_TICKER",
            "action": f"{ticker}: técnico disponible, pero falta fila de opciones.",
            "executive_summary": f"{ticker}: técnico disponible sin oportunidad de opciones.",
            "strategy": "UNKNOWN",
            "technical_bias": technical.get("trend", "UNKNOWN") if technical else "UNKNOWN",
            "technical_score": technical.get("score") if technical else None,
            "options_score": None,
            "best_row": {},
            "technical": technical or {},
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "runtime_source": source_item,
        }

    strategy = str(best_row.get("strategy") or best_row.get("strategy_hint") or "UNKNOWN").upper()

    try:
        option_ok, option_reason = _v27_row_operable(best_row)
    except Exception:
        option_ok, option_reason = bool(best_row.get("can_operate")), "OPTIONS_EVALUATED"

    try:
        technical_ok, technical_reason = _v27_technical_confirmed_for_strategy(strategy, technical)
    except Exception:
        technical_ok, technical_reason = bool(technical), "TECHNICAL_EVALUATED"

    market_open = bool(market.get("is_regular_market_open"))
    bidask_expected = bool(market.get("options_bidask_expected"))
    market_ok = market_open and bidask_expected

    canonical = _canonical_decision_state(
        ticker=ticker,
        strategy=strategy,
        option_ok=option_ok,
        option_reason=option_reason,
        technical_ok=technical_ok,
        technical_reason=technical_reason,
        market_ok=market_ok,
        row=best_row,
        technical=technical,
    )
    final_state = canonical["final_state"]
    decision = canonical["decision"]
    severity = canonical["severity"]
    blocker = canonical["main_blocker"]
    action = canonical["action"]

    return {
        "engine": "V27_1_RUNTIME_DATA_RESOLVER",
        "generated_at": _v271_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": canonical["can_operate"],
        "severity": severity,
        "main_blocker": blocker,
        "blockers": canonical["blockers"],
        "action": action,
        "executive_summary": (
            f"{ticker}: estado {final_state}. Estrategia {strategy}. "
            f"Opciones: {option_reason}. Técnico: {technical_reason}. Acción: {action}"
        ),
        "strategy": strategy,
        "technical_bias": (technical or {}).get("trend", "UNKNOWN"),
        "technical_score": (technical or {}).get("score"),
        "options_score": best_row.get("score") or best_row.get("combined_score") or best_row.get("master_score"),
        "options_fit": option_reason,
        "technical_fit": technical_reason,
        "risk_fit": "STRATEGY_RISK_CONFIRMED" if canonical["risk_gate"]["ok"] else ",".join(canonical["risk_gate"]["blockers"]),
        "best_row": best_row,
        "technical": technical or {},
        "rows_found_for_ticker": len([r for r in rows if r.get("ticker") == ticker]),
        "total_rows_found": len(rows),
        "market": market,
        "runtime_source": source_item,
        "risk_gate": canonical["risk_gate"],
    }

def _v271_dashboard_html(tickers=None):
    if not tickers:
        tickers = ["QQQ", "SPY", "NVDA", "TSLA", "META", "TLT"]

    decisions = [_v271_decide_for_ticker(t) for t in tickers]
    entry_count = sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY")
    wait_tech = sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL")
    wait_options = sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA")
    risk_blocked = sum(1 for d in decisions if d.get("final_state") == "RISK_BLOCKED")
    wait_data = sum(1 for d in decisions if d.get("final_state") == "NO_DATA")

    rows = ""
    for d in decisions:
        state = d.get("final_state")
        color = _v27_badge_color(state)
        ticker = d.get("ticker")
        rows += f"""
        <tr>
          <td><a href="/v27_1_trade_decision/{_v27_html_escape(ticker)}">{_v27_html_escape(ticker)}</a></td>
          <td><span class="badge" style="background:{color};">{_v27_html_escape(state)}</span></td>
          <td>{_v27_html_escape(d.get("strategy"))}</td>
          <td>{_v27_html_escape(d.get("technical_bias"))}</td>
          <td>{_v27_html_escape(d.get("technical_score"))}</td>
          <td>{_v27_html_escape(d.get("options_score"))}</td>
          <td>{'Sí' if d.get("can_operate") else 'No'}</td>
          <td>{_v27_html_escape(d.get("main_blocker"))}</td>
          <td>{_v27_html_escape(d.get("action"))}</td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>V27.1 Runtime Data Resolver Dashboard</title>
      <style>
        body {{
          margin:0;
          padding:36px;
          background:#f4f6fa;
          color:#0f172a;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
        }}
        h1 {{ font-size:34px; margin:0 0 22px; }}
        .hero {{
          background:#0f172a;
          color:white;
          padding:34px;
          border-radius:24px;
          margin-bottom:28px;
          box-shadow:0 20px 50px rgba(15,23,42,.12);
        }}
        .hero h2 {{ margin:0 0 12px; font-size:28px; }}
        .cards {{
          display:grid;
          grid-template-columns:repeat(5,minmax(0,1fr));
          gap:16px;
          margin-bottom:24px;
        }}
        .card {{
          background:white;
          border-radius:16px;
          padding:20px;
          box-shadow:0 12px 30px rgba(15,23,42,.08);
        }}
        .card .label {{ color:#64748b; font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.06em; }}
        .card .value {{ font-size:32px; font-weight:800; margin-top:8px; }}
        table {{
          width:100%;
          border-collapse:collapse;
          background:white;
          border-radius:18px;
          overflow:hidden;
          box-shadow:0 16px 40px rgba(15,23,42,.08);
        }}
        th,td {{
          text-align:left;
          padding:14px 16px;
          border-bottom:1px solid #e5e7eb;
          font-size:14px;
          vertical-align:top;
        }}
        th {{
          color:#64748b;
          text-transform:uppercase;
          font-size:12px;
          letter-spacing:.08em;
        }}
        .badge {{
          display:inline-block;
          color:white;
          padding:7px 11px;
          border-radius:999px;
          font-size:12px;
          font-weight:800;
        }}
        .footer {{
          margin-top:20px;
          color:#64748b;
          font-size:13px;
        }}
        a {{ color:#2563eb; font-weight:700; }}
      </style>
    </head>
    <body>
      <h1>V27.1 — Runtime Data Resolver Dashboard</h1>
      <div class="hero">
        <h2>Execution Guard activo</h2>
        <p>Busca automáticamente snapshots runtime y consolida técnico + opciones + mercado.</p>
        <p>Generado: {_v27_html_escape(_v271_now())}</p>
      </div>

      <div class="cards">
        <div class="card"><div class="label">Entry Ready</div><div class="value">{entry_count}</div></div>
        <div class="card"><div class="label">Wait Technical</div><div class="value">{wait_tech}</div></div>
        <div class="card"><div class="label">Wait Options</div><div class="value">{wait_options}</div></div>
        <div class="card"><div class="label">Risk Blocked</div><div class="value">{risk_blocked}</div></div>
        <div class="card"><div class="label">No Data</div><div class="value">{wait_data}</div></div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Estado</th>
            <th>Estrategia</th>
            <th>Sesgo técnico</th>
            <th>Score técnico</th>
            <th>Score opciones</th>
            <th>Operable</th>
            <th>Bloqueador</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>

      <div class="footer">
        Endpoints: /v27_1_runtime_inventory · /v27_1_system_status · /v27_1_trade_decision/QQQ · /v27_1_dashboard
      </div>
    </body>
    </html>
    """
    return html

@app.get("/v27_1_runtime_inventory")
async def v27_1_runtime_inventory():
    return _v271_runtime_inventory_payload()

@app.get("/v27_1_system_status")
async def v27_1_system_status():
    data, source_item, inv = _v271_find_best_runtime_snapshot()
    rows = _v271_rows_from_anywhere(data)
    technical = _v271_technical_from_anywhere(data)
    detected = sorted(list(set([r.get("ticker") for r in rows if r.get("ticker")] + list(technical.keys()))))
    return {
        "engine": "V27_1_RUNTIME_DATA_RESOLVER",
        "generated_at": _v271_now(),
        "status": "OK",
        "best_runtime_source": source_item,
        "rows_found": len(rows),
        "technical_available": bool(technical),
        "technical_tickers": sorted(list(technical.keys())),
        "tickers_detected": detected,
        "market": _v271_market_from_anywhere(data),
        "endpoints": {
            "runtime_inventory": "/v27_1_runtime_inventory",
            "trade_decision_example": "/v27_1_trade_decision/QQQ",
            "dashboard": "/v27_1_dashboard",
            "dashboard_ticker_example": "/v27_1_dashboard/QQQ",
        },
        "inventory_best_candidates": inv.get("best_candidates", [])[:10],
    }

@app.get("/v27_1_trade_decision/{ticker}")
async def v27_1_trade_decision(ticker: str):
    return _v271_decide_for_ticker(ticker)

@app.get("/gpt_v27_1_trade_decision/{ticker}")
async def gpt_v27_1_trade_decision(ticker: str):
    d = _v271_decide_for_ticker(ticker)
    return {
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "strategy": d.get("strategy"),
        "technical_bias": d.get("technical_bias"),
        "technical_score": d.get("technical_score"),
        "options_score": d.get("options_score"),
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "risk_note": "No ejecutar sin validar manualmente tamaño, liquidez, spread, evento, capital y tolerancia de riesgo.",
        "runtime_source": d.get("runtime_source"),
        "engine": d.get("engine"),
        "generated_at": d.get("generated_at"),
    }

@app.get("/v27_1_dashboard", response_class=_V271HTMLResponse)
async def v27_1_dashboard():
    return _v271_dashboard_html()

@app.get("/v27_1_dashboard/{ticker}", response_class=_V271HTMLResponse)
async def v27_1_dashboard_ticker(ticker: str):
    return _v271_dashboard_html([ticker])

# ============================================================
# END V27.1 RUNTIME DATA RESOLVER HOTFIX
# ============================================================



# ============================================================
# V28 AUTO PUBLISHER + TRADE COMMAND CENTER
# ============================================================
from pathlib import Path as _V28Path
from datetime import datetime as _V28DateTime, timezone as _V28Timezone
import json as _v28_json
from fastapi.responses import HTMLResponse as _V28HTMLResponse

_V28_RUNTIME_DIR = _V28Path("runtime")
_V28_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
_V28_MASTER_FILE = _V28_RUNTIME_DIR / "v28_master_snapshot.json"
_V28_ALIAS_V25_FILE = _V28_RUNTIME_DIR / "v25_master_snapshot.json"

def _v28_now():
    return _V28DateTime.now(_V28Timezone.utc).isoformat()

def _v28_safe_load(path):
    try:
        p = _V28Path(path)
        if not p.exists():
            return None
        return _v28_json.loads(p.read_text())
    except Exception:
        return None

def _v28_write_master(payload: dict):
    payload = dict(payload or {})
    payload["engine"] = "V28_AUTO_PUBLISHER_TRADE_COMMAND"
    payload["received_at"] = _v28_now()

    options_rows = payload.get("options_rows")
    if options_rows is None:
        options_rows = payload.get("rows") or payload.get("top") or payload.get("top_5") or []
    if not isinstance(options_rows, list):
        options_rows = []
    payload["options_rows"] = options_rows

    technical_snapshot = payload.get("technical_snapshot")
    if technical_snapshot is None:
        technical_snapshot = payload.get("technical") or payload.get("snapshot") or {}
    if not isinstance(technical_snapshot, dict):
        technical_snapshot = {}
    payload["technical_snapshot"] = technical_snapshot

    market = payload.get("market")
    if market is None:
        market = payload.get("market_hours") or {}
    if not isinstance(market, dict):
        market = {}
    payload["market"] = market

    tickers = set()
    for r in options_rows:
        if isinstance(r, dict) and r.get("ticker"):
            tickers.add(str(r.get("ticker")).upper().strip())
    for k in technical_snapshot.keys():
        if isinstance(k, str):
            tickers.add(k.upper().strip())

    payload["tickers_detected"] = sorted([t for t in tickers if t])
    payload["rows_found"] = len(options_rows)
    payload["technical_available"] = bool(technical_snapshot)
    payload["generated_at"] = payload.get("generated_at") or _v28_now()

    _V28_MASTER_FILE.write_text(_v28_json.dumps(payload, indent=2, ensure_ascii=False))
    _V28_ALIAS_V25_FILE.write_text(_v28_json.dumps(payload, indent=2, ensure_ascii=False))
    return payload

def _v28_ingest_payload(payload, ingest_engine=None, ingest_path=None):
    normalized = dict(payload or {}) if isinstance(payload, dict) else {"raw_payload": payload}
    if ingest_engine:
        normalized["legacy_ingest_engine"] = ingest_engine
    if ingest_path:
        normalized["legacy_ingest_path"] = ingest_path
    return _v28_write_master(normalized)

def _v28_ingest_response(saved):
    return {
        "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
        "status": "OK",
        "stored_file": str(_V28_MASTER_FILE),
        "alias_file": str(_V28_ALIAS_V25_FILE),
        "rows_found": saved.get("rows_found"),
        "technical_available": saved.get("technical_available"),
        "tickers_detected": saved.get("tickers_detected"),
        "received_at": saved.get("received_at"),
    }

def _v28_stored_technical_snapshot(data):
    technical = {}
    if not isinstance(data, dict):
        return technical

    raw = data.get("technical_snapshot")
    if raw is None:
        raw = data.get("technical") or data.get("snapshot") or {}

    if not isinstance(raw, dict):
        return technical

    if any(isinstance(v, dict) for v in raw.values()):
        for k, v in raw.items():
            if not isinstance(v, dict):
                continue
            t = _v28_norm_ticker(v.get("ticker") or k)
            vv = dict(v)
            vv["ticker"] = t
            technical[t] = vv
        return technical

    if any(key in raw for key in ["ticker", "trend", "bias", "score", "rsi", "adx", "event_risk", "earnings_soon"]):
        t = _v28_norm_ticker(raw.get("ticker") or data.get("ticker") or "UNKNOWN")
        vv = dict(raw)
        vv["ticker"] = t
        technical[t] = vv

    return technical

def _v28_raw_market(data):
    if not isinstance(data, dict):
        return {}

    market = data.get("market")
    if isinstance(market, dict):
        return market

    market = data.get("market_hours")
    if isinstance(market, dict):
        return market

    return {}

def _v22_2_sync_technical_to_canonical(ticker, snapshot):
    existing_data, _source = _v28_load_master()
    rows = _v28_rows(existing_data)
    technical_snapshot = _v28_stored_technical_snapshot(existing_data)
    technical_snapshot[ticker] = dict(snapshot or {})
    market = _v28_raw_market(existing_data)

    payload = {
        "source": (snapshot or {}).get("source") or (existing_data or {}).get("source") or "REMOTE_V22_2_TECHNICAL",
        "generated_at": (existing_data or {}).get("generated_at") or (snapshot or {}).get("received_at") or _v28_now(),
        "options_rows": rows,
        "technical_snapshot": technical_snapshot,
        "market": market,
    }
    return _v28_ingest_payload(
        payload,
        ingest_engine="V22_2_REMOTE_SNAPSHOT_SYNC",
        ingest_path="/v22_2_ingest_technical_snapshot",
    )

def _v22_2_sync_decision_to_canonical(data):
    existing_data, _source = _v28_load_master()
    technical_snapshot = _v28_stored_technical_snapshot(existing_data)
    incoming_rows = _v28_rows(data)
    rows = incoming_rows or _v28_rows(existing_data)
    market = _v28_raw_market(data) or _v28_raw_market(existing_data)

    payload = {
        "source": (data or {}).get("source") or (existing_data or {}).get("source") or "REMOTE_V22_2_DECISION",
        "generated_at": (data or {}).get("generated_at") or (existing_data or {}).get("generated_at") or _v28_now(),
        "options_rows": rows,
        "technical_snapshot": technical_snapshot,
        "market": market,
    }
    return _v28_ingest_payload(
        payload,
        ingest_engine="V22_2_REMOTE_SNAPSHOT_SYNC",
        ingest_path="/v22_2_ingest_decision_snapshot",
    )

def _v28_load_master():
    data = _v28_safe_load(_V28_MASTER_FILE)
    if data:
        return data, str(_V28_MASTER_FILE)
    data = _v28_safe_load(_V28_ALIAS_V25_FILE)
    if data:
        return data, str(_V28_ALIAS_V25_FILE)
    return {}, None

def _v28_norm_ticker(t):
    try:
        return _v27_normalize_ticker(t)
    except Exception:
        return str(t or "").upper().strip()

def _v28_rows(data):
    rows = []
    if isinstance(data, dict):
        for key in ["options_rows", "rows", "top", "top_5", "sample_rows"]:
            v = data.get(key)
            if isinstance(v, list):
                rows += [x for x in v if isinstance(x, dict)]
        opt = data.get("options")
        if isinstance(opt, dict):
            for key in ["options_rows", "rows", "top", "top_5", "sample_rows"]:
                v = opt.get(key)
                if isinstance(v, list):
                    rows += [x for x in v if isinstance(x, dict)]
        for key in ["best_row", "best", "next_best_action"]:
            v = data.get(key)
            if isinstance(v, dict):
                rows.append(v)
    elif isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]

    cleaned = []
    seen = set()
    for r in rows:
        rr = dict(r)
        ticker = _v28_norm_ticker(rr.get("ticker"))
        if not ticker:
            continue
        rr["ticker"] = ticker
        rr["strategy"] = str(rr.get("strategy") or rr.get("strategy_hint") or rr.get("best_strategy") or "UNKNOWN").upper()
        rr["decision"] = str(rr.get("decision") or rr.get("final_decision") or rr.get("state") or "RADAR").upper()
        rr["score"] = rr.get("score") or rr.get("combined_score") or rr.get("master_score") or rr.get("options_score")
        rr["price"] = rr.get("price") or rr.get("premium") or rr.get("option_price") or rr.get("mid")
        rr["data_quality"] = rr.get("data_quality") or rr.get("quality") or "UNKNOWN"
        k = (rr.get("ticker"), rr.get("strategy"), rr.get("decision"), str(rr.get("price")))
        if k not in seen:
            seen.add(k)
            cleaned.append(rr)
    return cleaned

def _v28_technical_map(data):
    technical = _v28_stored_technical_snapshot(data)

    # Merge V27 technical if available.
    try:
        tech2, _diag = _v27_load_technical_map()
        for k, v in tech2.items():
            technical.setdefault(k, v)
    except Exception:
        pass

    return technical

def _v28_market(data):
    if isinstance(data, dict):
        m = data.get("market") or data.get("market_hours") or {}
        if isinstance(m, dict):
            is_open = bool(
                m.get("is_regular_market_open")
                or m.get("is_open")
                or str(m.get("status", "")).upper() in ["REGULAR_OPTIONS_SESSION", "OPEN", "REGULAR"]
            )
            bidask = bool(
                m.get("options_bidask_expected")
                or m.get("bidask_expected")
                or m.get("bid_ask_expected")
                or is_open
            )
            label = m.get("label") or m.get("status") or ("Mercado abierto" if is_open else "Mercado no confirmado")
            return {
                "is_regular_market_open": is_open,
                "options_bidask_expected": bidask,
                "label": label,
                "raw": m,
            }

    # Fallback: if data was freshly ingested with complete bid/ask rows, do not hard-block.
    return {
        "is_regular_market_open": False,
        "options_bidask_expected": False,
        "label": "UNKNOWN",
        "raw": {},
    }

def _v28_choose_best(ticker, rows):
    ticker = _v28_norm_ticker(ticker)
    filtered = [r for r in rows if _v28_norm_ticker(r.get("ticker")) == ticker]
    if not filtered:
        return None
    try:
        return _v27_choose_best_option_row(ticker, filtered)
    except Exception:
        def score(r):
            try:
                return float(r.get("score") or 0)
            except Exception:
                return 0
        return sorted(filtered, key=score, reverse=True)[0]

def _v28_row_operable(row):
    if not row:
        return False, "NO_OPTIONS_ROW"

    missing = row.get("missing_confirmations")
    if isinstance(missing, list) and len(missing) > 0:
        return False, "MISSING_CONFIRMATIONS"

    dq = str(row.get("data_quality") or "").upper()
    decision = str(row.get("decision") or "").upper()

    if row.get("can_operate") is True:
        return True, "OPTIONS_CONFIRMED"

    if "FULL_WITH_GREEKS" in dq and decision in ["ENTRY", "OPERAR", "ENTRY_READY"]:
        return True, "OPTIONS_CONFIRMED"

    if "NO_BIDASK" in dq or "PRICE_ONLY" in dq:
        return False, dq or "OPTIONS_NOT_CONFIRMED"

    return False, "OPTIONS_NOT_CONFIRMED"

def _v28_technical_confirmed(strategy, technical):
    if not technical:
        return False, "NO_TECHNICAL_SNAPSHOT"

    trend = str(technical.get("trend") or technical.get("bias") or "").upper()
    score = technical.get("score")

    try:
        score_ok = float(score or 0) >= 60
    except Exception:
        score_ok = False

    s = str(strategy or "").upper()

    if s in ["NAKED_PUT", "BULL_PUT", "PUT_CREDIT_SPREAD"]:
        if trend in ["BULLISH", "UP", "ALCISTA"] and score_ok:
            return True, "TECHNICAL_CONFIRMED"

    if s in ["COVERED_CALL"]:
        if trend in ["BULLISH", "NEUTRAL", "RANGE", "ALCISTA"] and score_ok:
            return True, "TECHNICAL_CONFIRMED"

    if s in ["SHORT", "BEAR_CALL", "CALL_CREDIT_SPREAD"]:
        if trend in ["BEARISH", "DOWN", "BAJISTA"] and score_ok:
            return True, "TECHNICAL_CONFIRMED"

    if score_ok:
        return True, "TECHNICAL_SCORE_CONFIRMED"

    return False, "TECHNICAL_NOT_CONFIRMED"

def _v28_decide(ticker):
    ticker = _v28_norm_ticker(ticker)
    data, source = _v28_load_master()
    rows = _v28_rows(data)
    technical_map = _v28_technical_map(data)
    market = _v28_market(data)

    best = _v28_choose_best(ticker, rows)
    technical = technical_map.get(ticker)

    if not best and not technical:
        return {
            "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
            "generated_at": _v28_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_OPTIONS_OR_TECHNICAL_DATA",
            "strategy": "UNKNOWN",
            "technical_bias": "UNKNOWN",
            "technical_score": None,
            "options_score": None,
            "action": f"{ticker}: no hay datos técnicos ni opciones disponibles.",
            "executive_summary": f"{ticker}: sin datos suficientes para evaluar operación.",
            "best_row": {},
            "technical": {},
            "market": market,
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "master_source": source,
        }

    if not best:
        return {
            "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
            "generated_at": _v28_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "WAIT_OPTIONS_DATA",
            "decision": "WAIT_OPTIONS_DATA",
            "can_operate": False,
            "severity": "yellow",
            "main_blocker": "NO_OPTIONS_ROW_FOR_TICKER",
            "strategy": "UNKNOWN",
            "technical_bias": technical.get("trend", "UNKNOWN") if technical else "UNKNOWN",
            "technical_score": technical.get("score") if technical else None,
            "options_score": None,
            "action": f"{ticker}: técnico disponible, pero faltan opciones.",
            "executive_summary": f"{ticker}: falta fila de opciones para confirmar operación.",
            "best_row": {},
            "technical": technical or {},
            "market": market,
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "master_source": source,
        }

    strategy = str(best.get("strategy") or "UNKNOWN").upper()
    opt_ok, opt_reason = _v28_row_operable(best)
    tech_ok, tech_reason = _v28_technical_confirmed(strategy, technical)

    market_ok = bool(market.get("is_regular_market_open") and market.get("options_bidask_expected"))
    canonical = _canonical_decision_state(
        ticker=ticker,
        strategy=strategy,
        option_ok=opt_ok,
        option_reason=opt_reason,
        technical_ok=tech_ok,
        technical_reason=tech_reason,
        market_ok=market_ok,
        row=best,
        technical=technical,
    )
    state = canonical["final_state"]
    can_operate = canonical["can_operate"]
    severity = canonical["severity"]
    blocker = canonical["main_blocker"]
    action = canonical["action"]

    return {
        "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
        "generated_at": _v28_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": state,
        "decision": canonical["decision"],
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": blocker,
        "blockers": canonical["blockers"],
        "strategy": strategy,
        "technical_bias": (technical or {}).get("trend", "UNKNOWN"),
        "technical_score": (technical or {}).get("score"),
        "options_score": best.get("score"),
        "options_fit": opt_reason,
        "technical_fit": tech_reason,
        "risk_fit": "STRATEGY_RISK_CONFIRMED" if canonical["risk_gate"]["ok"] else ",".join(canonical["risk_gate"]["blockers"]),
        "action": action,
        "executive_summary": (
            f"{ticker}: {state}. Estrategia {strategy}. "
            f"Opciones: {opt_reason}. Técnico: {tech_reason}. Acción: {action}"
        ),
        "best_row": best,
        "technical": technical or {},
        "market": market,
        "risk_gate": canonical["risk_gate"],
        "rows_found_for_ticker": len([r for r in rows if _v28_norm_ticker(r.get("ticker")) == ticker]),
        "total_rows_found": len(rows),
        "master_source": source,
    }

def _v28_badge_color(state):
    s = str(state or "").upper()
    if "ENTRY_READY" in s:
        return "#16a34a"
    if "WAIT" in s:
        return "#64748b"
    if "NO_DATA" in s or "BLOCK" in s:
        return "#dc2626"
    return "#f59e0b"

def _v28_escape(x):
    try:
        return _v27_html_escape(x)
    except Exception:
        import html
        return html.escape(str(x if x is not None else ""))

def _v28_dashboard_html(tickers=None):
    if not tickers:
        data, _source = _v28_load_master()
        detected = data.get("tickers_detected") if isinstance(data, dict) else None
        if isinstance(detected, list) and detected:
            tickers = detected
        else:
            tickers = ["QQQ", "SPY", "NVDA", "TSLA", "META", "TLT"]

    decisions = [_v28_decide(t) for t in tickers]

    entry = sum(1 for d in decisions if "ENTRY_READY" in str(d.get("final_state")))
    wait_tech = sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL")
    wait_options = sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA")
    risk_blocked = sum(1 for d in decisions if d.get("final_state") == "RISK_BLOCKED")
    no_data = sum(1 for d in decisions if d.get("final_state") == "NO_DATA")

    rows_html = ""
    for d in decisions:
        state = d.get("final_state")
        color = _v28_badge_color(state)
        ticker = d.get("ticker")
        rows_html += f"""
        <tr>
          <td><a href="/v28_trade_decision/{_v28_escape(ticker)}">{_v28_escape(ticker)}</a></td>
          <td><span class="badge" style="background:{color};">{_v28_escape(state)}</span></td>
          <td>{_v28_escape(d.get("strategy"))}</td>
          <td>{_v28_escape(d.get("technical_bias"))}</td>
          <td>{_v28_escape(d.get("technical_score"))}</td>
          <td>{_v28_escape(d.get("options_score"))}</td>
          <td>{'Sí' if d.get("can_operate") else 'No'}</td>
          <td>{_v28_escape(d.get("main_blocker"))}</td>
          <td>{_v28_escape(d.get("action"))}</td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>V28 Trade Command Center</title>
      <style>
        body {{
          margin:0;
          padding:36px;
          background:#f4f6fa;
          color:#0f172a;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
        }}
        h1 {{ font-size:36px; margin:0 0 22px; }}
        .hero {{
          background:#0f172a;
          color:white;
          padding:34px;
          border-radius:24px;
          margin-bottom:28px;
          box-shadow:0 20px 50px rgba(15,23,42,.12);
        }}
        .hero h2 {{ margin:0 0 12px; font-size:28px; }}
        .cards {{
          display:grid;
          grid-template-columns:repeat(5,minmax(0,1fr));
          gap:16px;
          margin-bottom:24px;
        }}
        .card {{
          background:white;
          border-radius:16px;
          padding:20px;
          box-shadow:0 12px 30px rgba(15,23,42,.08);
        }}
        .label {{
          color:#64748b;
          font-weight:800;
          font-size:13px;
          text-transform:uppercase;
          letter-spacing:.08em;
        }}
        .value {{ font-size:34px; font-weight:900; margin-top:8px; }}
        table {{
          width:100%;
          border-collapse:collapse;
          background:white;
          border-radius:18px;
          overflow:hidden;
          box-shadow:0 16px 40px rgba(15,23,42,.08);
        }}
        th,td {{
          text-align:left;
          padding:14px 16px;
          border-bottom:1px solid #e5e7eb;
          font-size:14px;
          vertical-align:top;
        }}
        th {{
          color:#64748b;
          text-transform:uppercase;
          font-size:12px;
          letter-spacing:.08em;
        }}
        .badge {{
          display:inline-block;
          color:white;
          padding:7px 11px;
          border-radius:999px;
          font-size:12px;
          font-weight:900;
        }}
        .footer {{
          margin-top:20px;
          color:#64748b;
          font-size:13px;
        }}
        a {{ color:#2563eb; font-weight:800; }}
      </style>
    </head>
    <body>
      <h1>V28 — Trade Command Center</h1>
      <div class="hero">
        <h2>Execution Guard activo</h2>
        <p>Consolida publicación automática del bridge + técnico + opciones + mercado.</p>
        <p>Generado: {_v28_escape(_v28_now())}</p>
      </div>

      <div class="cards">
        <div class="card"><div class="label">Entry Ready</div><div class="value">{entry}</div></div>
        <div class="card"><div class="label">Wait Technical</div><div class="value">{wait_tech}</div></div>
        <div class="card"><div class="label">Wait Options</div><div class="value">{wait_options}</div></div>
        <div class="card"><div class="label">Risk Blocked</div><div class="value">{risk_blocked}</div></div>
        <div class="card"><div class="label">No Data</div><div class="value">{no_data}</div></div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Estado</th>
            <th>Estrategia</th>
            <th>Sesgo técnico</th>
            <th>Score técnico</th>
            <th>Score opciones</th>
            <th>Operable</th>
            <th>Bloqueador</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>

      <div class="footer">
        Endpoints: /v28_system_status · /v28_trade_decision/QQQ · /gpt_v28_trade_decision/QQQ · /v28_dashboard · POST /v28_ingest_snapshot
      </div>
    </body>
    </html>
    """
    return html

@app.post("/v28_ingest_snapshot")
async def v28_ingest_snapshot(payload: dict):
    saved = _v28_ingest_payload(payload)
    return _v28_ingest_response(saved)

@app.get("/v28_system_status")
async def v28_system_status():
    data, source = _v28_load_master()
    rows = _v28_rows(data)
    tech = _v28_technical_map(data)
    tickers = sorted(list(set([r.get("ticker") for r in rows if r.get("ticker")] + list(tech.keys()))))
    return {
        "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
        "generated_at": _v28_now(),
        "status": "OK",
        "master_snapshot_available": bool(data),
        "master_source": source,
        "rows_found": len(rows),
        "technical_available": bool(tech),
        "technical_tickers": sorted(list(tech.keys())),
        "tickers_detected": tickers,
        "market": _v28_market(data),
        "snapshot_meta": {
            "generated_at": data.get("generated_at") if isinstance(data, dict) else None,
            "received_at": data.get("received_at") if isinstance(data, dict) else None,
            "source": data.get("source") if isinstance(data, dict) else None,
        },
        "endpoints": {
            "ingest": "/v28_ingest_snapshot",
            "trade_decision_example": "/v28_trade_decision/QQQ",
            "gpt_trade_decision_example": "/gpt_v28_trade_decision/QQQ",
            "dashboard": "/v28_dashboard",
            "dashboard_ticker_example": "/v28_dashboard/QQQ",
        },
    }

@app.get("/v28_trade_decision/{ticker}")
async def v28_trade_decision(ticker: str):
    return _v28_decide(ticker)

@app.get("/gpt_v28_trade_decision/{ticker}")
async def gpt_v28_trade_decision(ticker: str):
    d = _v28_decide(ticker)
    return {
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "strategy": d.get("strategy"),
        "technical_bias": d.get("technical_bias"),
        "technical_score": d.get("technical_score"),
        "options_score": d.get("options_score"),
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "risk_note": "No ejecutar sin validar manualmente tamaño, liquidez, spread, evento, capital disponible y tolerancia de riesgo.",
        "market": d.get("market"),
        "master_source": d.get("master_source"),
        "engine": d.get("engine"),
        "generated_at": d.get("generated_at"),
    }

@app.get("/v28_dashboard", response_class=_V28HTMLResponse)
async def v28_dashboard():
    return _v28_dashboard_html()

@app.get("/v28_dashboard/{ticker}", response_class=_V28HTMLResponse)
async def v28_dashboard_ticker(ticker: str):
    return _v28_dashboard_html([ticker])

# ============================================================
# END V28 AUTO PUBLISHER + TRADE COMMAND CENTER
# ============================================================


# ============================================================
# V29 FINAL DECISION QUALITY ENGINE
# ============================================================

from fastapi.responses import HTMLResponse as _V29HTMLResponse
from pathlib import Path as _V29Path
from datetime import datetime as _V29Datetime, timezone as _V29Timezone
import json as _v29_json
import math as _v29_math
import html as _v29_html

_V29_RUNTIME_DIR = _V29Path("runtime")
_V29_MASTER_FILES = [
    "v28_master_snapshot.json",
    "v25_master_snapshot.json",
    "v22_2_unified_remote_snapshot.json",
    "decision_desk_snapshot.json",
    "decision_snapshot.json",
]
_V29_IGNORED_RUNTIME_FILES = {
    "v32_decision_journal.json",
    "v32_outcomes_journal.json",
}

_V29_DEFAULT_TICKERS = ["QQQ", "SPY", "NVDA", "TSLA", "META", "NFLX", "TLT", "AAPL", "AMZN", "MSFT"]

_V29_MAX_SPREAD_PCT = OPTION_SPREAD_PCT_READY_MAX
_V29_MAX_ABS_SPREAD = 0.35
_V29_MIN_BID = 0.05
_V29_MIN_ASK = 0.05
_V29_MIN_OPTION_SCORE = 70
_V29_MIN_TECH_SCORE = 65

_V31_DECISION_VERSION = "v31.0"
_V31_STRATEGY_VERSION = "strategy_rules_v1"
_V31_RULESET_VERSION = "v31_canonical_rules_v1"
_V31_SNAPSHOT_VERSION = "v30_master_snapshot_contract_v1"
_STRATEGY_SIGNAL_CONTRACT_VERSION = "strategy_signal_contract_v1"
_CANSLIM_RULESET_VERSION = "canslim_filter_v1"
_V32_ENGINE = "V32_OUTCOMES_TRACKING"
_V32_DECISION_JOURNAL_FILE = _V29_RUNTIME_DIR / "v32_decision_journal.json"
_V32_OUTCOMES_JOURNAL_FILE = _V29_RUNTIME_DIR / "v32_outcomes_journal.json"
_V31_CANONICAL_STATES = [
    "NO_DATA",
    "WAIT_MARKET",
    "WAIT_ACCOUNT_CONTEXT",
    "WAIT_OPTIONS_DATA",
    "WAIT_TECHNICAL",
    "RISK_BLOCKED",
    "MANUAL_REVIEW",
    "ENTRY_READY",
]

_STRATEGY_SIGNAL_REQUIRED_FIELDS = [
    "ticker",
    "timeframe",
    "strategy_context",
    "trend",
    "score",
]

_STRATEGY_SIGNAL_OPTIONAL_FIELDS = [
    "rsi",
    "adx",
    "support_near",
    "resistance_near",
    "range_20d",
    "range_breakout",
    "vwap_position",
    "volume_relative",
    "iv_rank",
    "earnings_soon",
    "event_risk",
    "canslim",
    "canslim_score",
    "canslim_passes",
]

_CANSLIM_MIN_SCORE = 70


def _v29_now():
    return _V29Datetime.now(_V29Timezone.utc).isoformat()


def _v29_safe_float(x, default=None):
    try:
        if x is None:
            return default
        if isinstance(x, str) and not x.strip():
            return default
        val = float(x)
        if _v29_math.isnan(val) or _v29_math.isinf(val):
            return default
        return val
    except Exception:
        return default


def _v29_safe_upper(x, default="UNKNOWN"):
    try:
        if x is None:
            return default
        txt = str(x).strip()
        return txt.upper() if txt else default
    except Exception:
        return default


def _v29_load_json_file(path):
    try:
        p = _V29Path(path)
        if not p.exists():
            return None
        return _v29_json.loads(p.read_text())
    except Exception:
        return None


def _v29_discover_master_snapshot():
    candidates = []

    for name in _V29_MASTER_FILES:
        p = _V29_RUNTIME_DIR / name
        if p.exists():
            candidates.append(p)

    if _V29_RUNTIME_DIR.exists():
        for p in _V29_RUNTIME_DIR.glob("*.json"):
            if p.name in _V29_IGNORED_RUNTIME_FILES:
                continue
            if p not in candidates:
                candidates.append(p)

    best = None
    best_score = -1

    for p in candidates:
        data = _v29_load_json_file(p)
        if not isinstance(data, dict):
            continue

        rows = _v29_extract_options_rows_from_obj(data)
        tech = _v29_extract_technical_from_obj(data)
        score = len(rows) * 5 + len(tech) * 3

        # Preferir explícitamente master snapshots recientes
        if "v28_master_snapshot" in p.name:
            score += 500
        if "v25_master_snapshot" in p.name:
            score += 250

        if score > best_score:
            best_score = score
            best = {
                "path": str(p),
                "data": data,
                "rows": rows,
                "technical": tech,
                "score": score,
            }

    if best is None:
        return {
            "path": None,
            "data": {},
            "rows": [],
            "technical": {},
            "score": 0,
        }

    return best


def _v29_extract_options_rows_from_obj(obj):
    rows = []

    def scan(x):
        if isinstance(x, dict):
            direct_lists = [
                "options_rows",
                "rows",
                "sample_rows",
                "best_rows",
                "entry_candidates",
                "radar_candidates",
                "top",
                "top_5",
                "candidates",
            ]

            for key in direct_lists:
                v = x.get(key)
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            rows.append(dict(item))

            ticker = _v29_safe_upper(x.get("ticker") or x.get("symbol"), "")
            strategy = x.get("strategy") or x.get("strategy_hint") or x.get("best_strategy")
            decision = x.get("decision") or x.get("final_decision") or x.get("state")
            quality = x.get("data_quality") or x.get("quality")

            option_like = False
            if ticker and strategy:
                option_like = True
            if ticker and any(k in x for k in ["bid", "ask", "strike", "delta", "expiration", "dte", "mid", "price"]):
                option_like = True
            if ticker and quality:
                option_like = True
            if ticker and decision and any(word in _v29_safe_upper(strategy, "") for word in ["PUT", "CALL", "CONDOR"]):
                option_like = True

            if option_like:
                rows.append(dict(x))

            for v in x.values():
                if isinstance(v, (dict, list)):
                    scan(v)

        elif isinstance(x, list):
            for item in x:
                scan(item)

    scan(obj)

    cleaned = []
    seen = set()

    for r in rows:
        ticker = _v29_safe_upper(r.get("ticker") or r.get("symbol"), "")
        if not ticker:
            continue

        strategy = _v29_safe_upper(r.get("strategy") or r.get("strategy_hint") or r.get("best_strategy"), "UNKNOWN")
        decision = _v29_safe_upper(r.get("decision") or r.get("final_decision") or r.get("state"), "RADAR")

        r["ticker"] = ticker
        r["strategy"] = strategy
        r["decision"] = decision
        r["score"] = _v29_safe_float(
            r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"),
            0
        )

        r["price"] = _v29_safe_float(r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"), None)

        r["bid"] = _v29_safe_float(r.get("bid") or r.get("option_bid"), None)
        r["ask"] = _v29_safe_float(r.get("ask") or r.get("option_ask"), None)
        r["mid"] = _v29_safe_float(r.get("mid") or r.get("mark") or r.get("price"), None)
        r["spread"] = _v29_safe_float(r.get("spread"), None)
        r["spread_pct"] = _v29_safe_float(r.get("spread_pct"), None)
        r["delta"] = _v29_safe_float(r.get("delta"), None)
        r["gamma"] = _v29_safe_float(r.get("gamma"), None)
        r["theta"] = _v29_safe_float(r.get("theta"), None)
        r["vega"] = _v29_safe_float(r.get("vega"), None)
        r["iv"] = _v29_safe_float(r.get("iv") or r.get("implied_volatility"), None)
        r["volume"] = _v29_safe_float(r.get("volume"), None)
        r["open_interest"] = _v29_safe_float(r.get("open_interest") or r.get("oi"), None)
        r["strike"] = _v29_safe_float(r.get("strike"), None)
        r["dte"] = _v29_safe_float(r.get("dte"), None)
        r["expiration"] = r.get("expiration") or r.get("expiry") or r.get("exp")
        r["can_operate"] = bool(r.get("can_operate")) if r.get("can_operate") is not None else False
        r["missing_confirmations"] = r.get("missing_confirmations") if isinstance(r.get("missing_confirmations"), list) else []
        r["recommendation"] = r.get("recommendation")
        r["reason"] = r.get("reason") or r.get("strategy_reason")
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"

        if r["spread"] is None or r["mid"] is None or r["spread_pct"] is None:
            spread, mid, spread_pct = _v29_spread_metrics(r)
            if r["spread"] is None:
                r["spread"] = spread
            if r["mid"] is None:
                r["mid"] = mid
            if r["spread_pct"] is None:
                r["spread_pct"] = spread_pct

        key = (
            ticker,
            strategy,
            decision,
            str(r.get("strike")),
            str(r.get("expiration")),
            str(r.get("price")),
            str(r.get("bid")),
            str(r.get("ask")),
        )

        if key not in seen:
            seen.add(key)
            cleaned.append(r)

    return cleaned


def _v29_extract_technical_from_obj(obj):
    tech = {}

    def scan(x, parent_key=None):
        if isinstance(x, dict):
            ticker = _v29_safe_upper(x.get("ticker") or x.get("symbol") or parent_key, "")

            looks_technical = any(k in x for k in [
                "trend",
                "bias",
                "technical_bias",
                "rsi",
                "adx",
                "vwap_position",
                "volume_relative",
                "support_near",
                "resistance_near",
                "range_breakout",
                "event_risk",
                "technical_score",
                "score",
            ])

            if ticker and looks_technical:
                item = dict(x)
                item["ticker"] = ticker
                item["trend"] = _v29_safe_upper(
                    item.get("trend") or item.get("bias") or item.get("technical_bias"),
                    "UNKNOWN"
                )
                item["score"] = _v29_safe_float(item.get("technical_score") or item.get("score"), None)
                tech[ticker] = item

            for k, v in x.items():
                if isinstance(v, dict):
                    scan(v, k)
                elif isinstance(v, list):
                    scan(v, None)

        elif isinstance(x, list):
            for item in x:
                scan(item, parent_key)

    scan(obj)
    return tech


def _v29_spread_metrics(row):
    bid = _v29_safe_float(row.get("bid"), None)
    ask = _v29_safe_float(row.get("ask"), None)

    if bid is None or ask is None:
        return None, None, None

    if bid <= 0 or ask <= 0 or ask < bid:
        return None, None, None

    spread = round(ask - bid, 4)
    mid = round((ask + bid) / 2, 4)

    if mid <= 0:
        return spread, mid, None

    spread_pct = round((spread / mid) * 100, 2)
    return spread, mid, spread_pct


def _v29_expiration_parseable(value):
    if not value:
        return False

    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            pass

    return False


def _v29_listify(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _v29_risk_manual_gate(row):
    risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
    blockers = []

    for key in [
        "blockers",
        "manual_review_blockers",
        "risk_blockers",
        "missing_confirmations",
    ]:
        blockers.extend(_v29_listify(row.get(key)))

    blockers.extend(_v29_listify(risk.get("blockers")))

    risk_pass_value = None
    for value in [
        risk.get("passes"),
        risk.get("pass"),
        row.get("risk_passes"),
        row.get("risk_ok"),
        row.get("risk_pass"),
        row.get("trade_allowed"),
    ]:
        if value is not None:
            risk_pass_value = value
            break

    risk_ok = risk_pass_value is True
    risk_blocker = risk.get("blocker") or row.get("risk_blocker")

    if risk_pass_value is False and not risk_blocker:
        risk_blocker = "RISK_RULE_FAILED"
    if risk_pass_value is None:
        risk_blocker = "RISK_NOT_CONFIRMED"

    manual_review_required = bool(
        row.get("manual_review_required") is True
        or row.get("manual_review") is True
        or row.get("requires_manual_review") is True
    )
    manual_blockers = [
        str(x)
        for x in blockers
        if "MANUAL" in _v29_safe_upper(x, "") or "REVIEW" in _v29_safe_upper(x, "")
    ]

    if manual_review_required and not manual_blockers:
        manual_blockers.append("MANUAL_REVIEW_REQUIRED")

    return {
        "risk_ok": risk_ok,
        "risk_blocker": risk_blocker,
        "manual_ok": not manual_blockers,
        "manual_blockers": manual_blockers,
        "blockers": [str(x) for x in blockers if x not in [None, ""]],
    }


def _v29_quality_gate(row):
    missing = []

    bid = _v29_safe_float(row.get("bid"), None)
    ask = _v29_safe_float(row.get("ask"), None)
    price = _v29_safe_float(row.get("price"), None)
    score = _v29_safe_float(row.get("score"), 0)
    delta = _v29_safe_float(row.get("delta"), None)
    strike = _v29_safe_float(row.get("strike"), None)
    dte = _v29_safe_float(row.get("dte"), None)
    expiration = row.get("expiration")

    spread, mid, spread_pct = _v29_spread_metrics(row)

    if bid is None or bid < _V29_MIN_BID:
        missing.append("bid")
    if ask is None or ask < _V29_MIN_ASK:
        missing.append("ask")
    if bid is not None and ask is not None and ask < bid:
        missing.append("bid_ask_order")
    if mid is None or mid <= 0:
        missing.append("mid")
    if spread is None:
        missing.append("spread")
    if spread_pct is None:
        missing.append("spread_pct")
    if strike is None:
        missing.append("strike")
    elif strike <= 0:
        missing.append("strike")
    if dte is None:
        missing.append("dte")
    elif dte < 0:
        missing.append("dte")
    if not _v29_expiration_parseable(expiration):
        missing.append("expiration")
    if delta is None:
        missing.append("delta")
    elif delta < -1 or delta > 1:
        missing.append("delta")
    if price is None and mid is None:
        missing.append("price_or_mid")
    if score < _V29_MIN_OPTION_SCORE:
        missing.append("option_score")

    spread_ok = False
    if spread is not None and spread_pct is not None:
        spread_ok = spread <= _V29_MAX_ABS_SPREAD or spread_pct <= _V29_MAX_SPREAD_PCT
        if not spread_ok:
            missing.append("spread_too_wide")

    executable = len(missing) == 0

    quality = "EXECUTABLE" if executable else "NOT_EXECUTABLE"

    return {
        "executable": executable,
        "quality": quality,
        "missing": missing,
        "spread": spread,
        "mid": mid,
        "spread_pct": spread_pct,
        "bid": bid,
        "ask": ask,
        "strike": strike,
        "expiration": expiration,
        "dte": dte,
        "delta": delta,
        "gamma": _v29_safe_float(row.get("gamma"), None),
        "theta": _v29_safe_float(row.get("theta"), None),
        "vega": _v29_safe_float(row.get("vega"), None),
        "iv": _v29_safe_float(row.get("iv") or row.get("implied_volatility"), None),
        "volume": _v29_safe_float(row.get("volume"), None),
        "open_interest": _v29_safe_float(row.get("open_interest") or row.get("oi"), None),
    }


def _v29_score_row(row):
    q = _v29_quality_gate(row)
    base = _v29_safe_float(row.get("score"), 0)

    bonus = 0
    if q["executable"]:
        bonus += 1000
    if q["spread_pct"] is not None:
        bonus += max(0, 100 - q["spread_pct"])
    if row.get("data_quality") == "FULL_WITH_GREEKS":
        bonus += 50
    if _v29_safe_upper(row.get("decision"), "") in ["ENTRY", "ENTRY_READY", "OPERAR"]:
        bonus += 30

    return base + bonus


def _v29_best_row_for_ticker(ticker, rows):
    ticker = _v29_safe_upper(ticker)
    ticker_rows = [r for r in rows if _v29_safe_upper(r.get("ticker")) == ticker]

    if not ticker_rows:
        return None, [], []

    enriched = []
    for r in ticker_rows:
        rr = dict(r)
        q = _v29_quality_gate(rr)
        rr["v29_quality"] = q["quality"]
        rr["v29_missing"] = q["missing"]
        rr["spread"] = q["spread"]
        rr["mid"] = q["mid"]
        rr["spread_pct"] = q["spread_pct"]
        rr["bid"] = q["bid"]
        rr["ask"] = q["ask"]
        rr["v29_executable"] = q["executable"]
        enriched.append(rr)

    executable = [r for r in enriched if r.get("v29_executable")]

    if executable:
        best = sorted(executable, key=_v29_score_row, reverse=True)[0]
    else:
        best = sorted(enriched, key=_v29_score_row, reverse=True)[0]

    return best, enriched, executable


def _v29_technical_state(ticker, technical, strategy="UNKNOWN"):
    ticker = _v29_safe_upper(ticker)
    root = technical.get(ticker) or {}
    contexts = root.get("by_strategy_context") if isinstance(root.get("by_strategy_context"), dict) else {}
    strategy = _v29_safe_upper(strategy, "UNKNOWN")
    context_preferences = {
        "NAKED_PUT": ["NAKED_PUT", "CASH_SECURED_PUT"],
        "CASH_SECURED_PUT": ["CASH_SECURED_PUT", "NAKED_PUT"],
        "COVERED_CALL": ["COVERED_CALL"],
        "IRON_CONDOR": ["IRON_CONDOR"],
        "FUTURES": ["FUTURES"],
        "FUTURES_PRO": ["FUTURES"],
    }

    selected = None
    selected_context = None
    for context in context_preferences.get(strategy, []):
        candidate = contexts.get(context)
        if isinstance(candidate, dict):
            selected = candidate
            selected_context = context
            break

    t = dict(root)
    if selected:
        t.update(selected)
        t["selected_strategy_context"] = selected_context
    if isinstance(root.get("canslim"), dict):
        t["canslim"] = dict(root.get("canslim"))
    if contexts:
        t["by_strategy_context"] = contexts
        t["available_strategy_contexts"] = sorted(contexts.keys())

    score = _v29_safe_float(t.get("score") or t.get("technical_score"), None)
    trend = _v29_safe_upper(t.get("trend") or t.get("bias") or t.get("technical_bias"), "UNKNOWN")

    confirmed = score is not None and score >= _V29_MIN_TECH_SCORE

    return {
        "available": bool(t),
        "confirmed": confirmed,
        "score": score,
        "trend": trend,
        "strategy_context": t.get("selected_strategy_context") or t.get("strategy_context"),
        "available_strategy_contexts": t.get("available_strategy_contexts", []),
        "raw": t,
    }


def _v29_strategy_signal_contract():
    return {
        "contract_version": _STRATEGY_SIGNAL_CONTRACT_VERSION,
        "technical_endpoint": "/technical_snapshot",
        "strategy_contexts": [
            "NAKED_PUT",
            "CASH_SECURED_PUT",
            "COVERED_CALL",
            "IRON_CONDOR",
            "FUTURES",
            "CANSLIM_FILTER",
        ],
        "required_fields": list(_STRATEGY_SIGNAL_REQUIRED_FIELDS),
        "optional_fields": list(_STRATEGY_SIGNAL_OPTIONAL_FIELDS),
        "technical_confirmation": {
            "minimum_score": _V29_MIN_TECH_SCORE,
            "notes": [
                "Technical confirmation is an input to deterministic blocker logic.",
                "Missing or unconfirmed technical data keeps option candidates out of ENTRY_READY.",
            ],
        },
        "canslim": {
            "ruleset_version": _CANSLIM_RULESET_VERSION,
            "minimum_score": _CANSLIM_MIN_SCORE,
            "accepted_shapes": [
                {"canslim": {"passes": True, "score": 82}},
                {"canslim_passes": True, "canslim_score": 82},
            ],
            "blocking_behavior": "If CANSLIM data is provided and fails, ENTRY_READY is blocked as RISK_BLOCKED. Missing CANSLIM data is advisory until the feed is intentionally required.",
        },
        "not_order_instruction": True,
    }


def _v29_strategy_signal_template(ticker="QQQ", strategy_context="NAKED_PUT"):
    ticker = _v29_safe_upper(ticker, "QQQ")
    strategy_context = _v29_safe_upper(strategy_context, "NAKED_PUT")
    return {
        "ticker": ticker,
        "timeframe": "1h",
        "strategy_context": strategy_context,
        "trend": "bullish" if strategy_context in ["NAKED_PUT", "CASH_SECURED_PUT"] else "neutral",
        "score": 72,
        "rsi": 52,
        "adx": 18,
        "support_near": strategy_context in ["NAKED_PUT", "CASH_SECURED_PUT"],
        "resistance_near": strategy_context == "COVERED_CALL",
        "range_20d": strategy_context == "IRON_CONDOR",
        "range_breakout": False,
        "vwap_position": "near",
        "volume_relative": 1.0,
        "iv_rank": 45,
        "earnings_soon": False,
        "event_risk": False,
        "canslim": {
            "passes": True,
            "score": 78,
            "rating": "PASS",
            "notes": "Optional fundamental-growth filter. Do not include secrets or account data.",
        },
        "source": "TRADINGVIEW_STRATEGY_SIGNAL",
        "contract_version": _STRATEGY_SIGNAL_CONTRACT_VERSION,
    }


def _v29_canslim_payload(row, technical):
    row = row or {}
    technical = technical or {}

    for container in [technical, row]:
        value = container.get("canslim")
        if isinstance(value, dict):
            return dict(value)

        snapshot = container.get("fundamental_snapshot")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("canslim"), dict):
            return dict(snapshot.get("canslim"))

    payload = {}
    for key in [
        "canslim_score",
        "canslim_passes",
        "canslim_rating",
        "canslim_notes",
    ]:
        if key in technical:
            payload[key] = technical.get(key)
        elif key in row:
            payload[key] = row.get(key)

    return payload


def _v29_canslim_gate(row, technical, strategy):
    strategy = _v29_safe_upper(strategy, "UNKNOWN")

    if strategy in ["FUTURES", "FUTURES_PRO", "MNQ", "NQ", "ES", "MES"]:
        return {
            "applicable": False,
            "status": "NOT_APPLICABLE",
            "ok": True,
            "blockers": [],
            "score": None,
            "passes": None,
            "ruleset_version": _CANSLIM_RULESET_VERSION,
        }

    payload = _v29_canslim_payload(row, technical)
    if not payload:
        return {
            "applicable": True,
            "status": "NOT_PROVIDED",
            "ok": True,
            "blockers": [],
            "score": None,
            "passes": None,
            "ruleset_version": _CANSLIM_RULESET_VERSION,
        }

    score = _v29_safe_float(
        payload.get("score")
        or payload.get("canslim_score")
        or payload.get("rating_score"),
        None,
    )
    passes_raw = payload.get("passes")
    if passes_raw is None:
        passes_raw = payload.get("pass")
    if passes_raw is None:
        passes_raw = payload.get("canslim_passes")

    passes = None
    if isinstance(passes_raw, bool):
        passes = passes_raw
    elif isinstance(passes_raw, str):
        val = passes_raw.strip().upper()
        if val in ["TRUE", "PASS", "PASSES", "OK", "YES", "SI", "SÍ", "1"]:
            passes = True
        elif val in ["FALSE", "FAIL", "FAILED", "NO", "0"]:
            passes = False

    if passes is None and score is not None:
        passes = score >= _CANSLIM_MIN_SCORE

    blockers = []
    if passes is False:
        blockers.append("CANSLIM_BLOCKED")
    elif score is not None and score < _CANSLIM_MIN_SCORE:
        blockers.append("CANSLIM_SCORE_BELOW_MIN")

    return {
        "applicable": True,
        "status": "PASS" if not blockers else "BLOCKED",
        "ok": not blockers,
        "blockers": blockers,
        "score": score,
        "passes": passes,
        "minimum_score": _CANSLIM_MIN_SCORE,
        "ruleset_version": _CANSLIM_RULESET_VERSION,
        "raw": payload,
    }


def _selected_contract_from_v29(v29_decision):
    row = v29_decision.get("best_row") or {}
    quality = v29_decision.get("best_row_quality") or {}
    return {
        "ticker": v29_decision.get("ticker"),
        "strategy": v29_decision.get("strategy"),
        "strike": row.get("strike"),
        "expiration": row.get("expiration"),
        "dte": row.get("dte"),
        "bid": quality.get("bid"),
        "ask": quality.get("ask"),
        "mid": quality.get("mid"),
        "spread": quality.get("spread"),
        "spread_pct": quality.get("spread_pct"),
        "delta": quality.get("delta"),
        "iv": quality.get("iv"),
        "volume": quality.get("volume"),
        "open_interest": quality.get("open_interest"),
        "data_quality": row.get("data_quality"),
        "source_decision": row.get("decision"),
        "source_score": row.get("score"),
    }


def _v32_read_list(path):
    try:
        p = _V29Path(path)
        if not p.exists():
            return []
        data = _v29_json.loads(p.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _v32_write_list(path, items):
    p = _V29Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_v29_json.dumps(items, indent=2, ensure_ascii=False, default=str))


def _v32_load_decision_journal():
    return _v32_read_list(_V32_DECISION_JOURNAL_FILE)


def _v32_load_outcomes_journal():
    return _v32_read_list(_V32_OUTCOMES_JOURNAL_FILE)


def _v32_hash_id(prefix, payload):
    raw = _v29_json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}-{digest}"


def _v32_followup_summary(followups):
    underlying_values = [f.get("underlying_price") for f in followups if _v29_safe_float(f.get("underlying_price"), None) is not None]
    option_mid_values = [f.get("option_mid") for f in followups if _v29_safe_float(f.get("option_mid"), None) is not None]
    pnl_r_values = [f.get("pnl_r") for f in followups if _v29_safe_float(f.get("pnl_r"), None) is not None]

    return {
        "observation_count": len(followups),
        "last_observed_at": followups[-1].get("recorded_at") if followups else None,
        "underlying_price_min": min(underlying_values) if underlying_values else None,
        "underlying_price_max": max(underlying_values) if underlying_values else None,
        "option_mid_min": min(option_mid_values) if option_mid_values else None,
        "option_mid_max": max(option_mid_values) if option_mid_values else None,
        "mfe_r": max(pnl_r_values) if pnl_r_values else None,
        "mae_r": min(pnl_r_values) if pnl_r_values else None,
    }


def _v32_decision_record(v29_decision):
    selected_contract = _selected_contract_from_v29(v29_decision)
    identity_payload = {
        "ticker": v29_decision.get("ticker"),
        "final_state": v29_decision.get("final_state"),
        "strategy": v29_decision.get("strategy"),
        "main_blocker": v29_decision.get("main_blocker"),
        "blockers": list(v29_decision.get("blockers") or []),
        "selected_contract": selected_contract,
        "technical_score": v29_decision.get("technical_score"),
        "options_score": v29_decision.get("options_score"),
        "snapshot_generated_at": v29_decision.get("snapshot_generated_at"),
        "snapshot_received_at": v29_decision.get("snapshot_received_at"),
        "master_source": v29_decision.get("master_source"),
    }
    decision_id = _v32_hash_id("DEC", identity_payload)
    return {
        "decision_id": decision_id,
        "engine": _V32_ENGINE,
        "source_engine": v29_decision.get("engine"),
        "decision_version": _V31_DECISION_VERSION,
        "strategy_version": _V31_STRATEGY_VERSION,
        "ruleset_version": _V31_RULESET_VERSION,
        "snapshot_version": _V31_SNAPSHOT_VERSION,
        "recorded_at": _v29_now(),
        "decision_generated_at": v29_decision.get("generated_at"),
        "snapshot_generated_at": v29_decision.get("snapshot_generated_at"),
        "snapshot_received_at": v29_decision.get("snapshot_received_at"),
        "ticker": v29_decision.get("ticker"),
        "strategy": v29_decision.get("strategy"),
        "final_state": v29_decision.get("final_state"),
        "decision": v29_decision.get("decision"),
        "main_blocker": v29_decision.get("main_blocker"),
        "blockers": list(v29_decision.get("blockers") or []),
        "required_missing_fields": list(v29_decision.get("required_missing_fields") or []),
        "technical": {
            "bias": v29_decision.get("technical_bias"),
            "score": v29_decision.get("technical_score"),
            "fit": v29_decision.get("technical_fit"),
        },
        "risk": {
            "fit": v29_decision.get("risk_fit"),
            "manual_review_fit": v29_decision.get("manual_review_fit"),
            "gate": v29_decision.get("risk_gate"),
        },
        "selected_contract": selected_contract,
        "market": v29_decision.get("market"),
        "master_source": v29_decision.get("master_source"),
        "action": v29_decision.get("action"),
        "explanation": v29_decision.get("executive_summary"),
        "ready_for_manual_review": v29_decision.get("final_state") == "ENTRY_READY",
        "outcome_status": "OPEN",
        "followup_summary": _v32_followup_summary([]),
        "followups": [],
        "latest_outcome": None,
    }


def _v32_upsert_decision_record(record):
    journal = _v32_load_decision_journal()
    for index, item in enumerate(journal):
        if item.get("decision_id") == record.get("decision_id"):
            preserved = {
                "followups": item.get("followups") or [],
                "followup_summary": item.get("followup_summary") or _v32_followup_summary(item.get("followups") or []),
                "outcome_status": item.get("outcome_status") or record.get("outcome_status"),
                "latest_outcome": item.get("latest_outcome"),
                "recorded_at": item.get("recorded_at") or record.get("recorded_at"),
            }
            merged = dict(record)
            merged.update(preserved)
            journal[index] = merged
            _v32_write_list(_V32_DECISION_JOURNAL_FILE, journal[-5000:])
            return merged, False

    journal.append(record)
    journal = journal[-5000:]
    _v32_write_list(_V32_DECISION_JOURNAL_FILE, journal)
    return record, True


def _v32_record_decision(v29_decision):
    record = _v32_decision_record(v29_decision)
    saved, created = _v32_upsert_decision_record(record)
    return saved, created


def _v32_find_decision_record(decision_id):
    for record in reversed(_v32_load_decision_journal()):
        if record.get("decision_id") == decision_id:
            return record
    return None


def _v32_replace_decision_record(updated):
    journal = _v32_load_decision_journal()
    replaced = False
    for index, item in enumerate(journal):
        if item.get("decision_id") == updated.get("decision_id"):
            journal[index] = updated
            replaced = True
            break
    if not replaced:
        journal.append(updated)
    journal = journal[-5000:]
    _v32_write_list(_V32_DECISION_JOURNAL_FILE, journal)
    return updated


def _v32_followup_entry(payload):
    decision_id = str((payload or {}).get("decision_id") or "").strip()
    if not decision_id:
        return {"status": "error", "message": "decision_id is required."}

    decision = _v32_find_decision_record(decision_id)
    if not decision:
        return {"status": "error", "message": "decision_id not found.", "decision_id": decision_id}

    followups = list(decision.get("followups") or [])
    followup = {
        "followup_id": _v32_hash_id("FUP", {"decision_id": decision_id, "count": len(followups) + 1, "payload": payload}),
        "recorded_at": _v29_now(),
        "tag": payload.get("tag") or "FOLLOWUP",
        "note": payload.get("note"),
        "underlying_price": _v29_safe_float(payload.get("underlying_price"), None),
        "option_mid": _v29_safe_float(payload.get("option_mid"), None),
        "option_bid": _v29_safe_float(payload.get("option_bid"), None),
        "option_ask": _v29_safe_float(payload.get("option_ask"), None),
        "pnl": _v29_safe_float(payload.get("pnl"), None),
        "pnl_r": _v29_safe_float(payload.get("pnl_r"), None),
        "status": payload.get("status"),
    }
    followups.append(followup)
    decision["followups"] = followups[-200:]
    decision["followup_summary"] = _v32_followup_summary(decision["followups"])
    _v32_replace_decision_record(decision)

    return {
        "status": "ok",
        "engine": _V32_ENGINE,
        "decision_id": decision_id,
        "followup": followup,
        "followup_summary": decision.get("followup_summary"),
    }


def _v32_duration_minutes(decision, closed_at):
    start = decision.get("recorded_at") or decision.get("decision_generated_at")
    try:
        start_dt = datetime.fromisoformat(str(start))
        end_dt = datetime.fromisoformat(str(closed_at))
        return round((end_dt - start_dt).total_seconds() / 60.0, 2)
    except Exception:
        return None


def _v32_outcome_entry(payload):
    decision_id = str((payload or {}).get("decision_id") or "").strip()
    if not decision_id:
        return {"status": "error", "message": "decision_id is required."}

    decision = _v32_find_decision_record(decision_id)
    if not decision:
        return {"status": "error", "message": "decision_id not found.", "decision_id": decision_id}

    closed_at = _v29_now()
    outcome = {
        "outcome_id": _v32_hash_id("OUT", {"decision_id": decision_id, "payload": payload, "closed_at": closed_at}),
        "decision_id": decision_id,
        "recorded_at": closed_at,
        "ticker": decision.get("ticker"),
        "strategy": decision.get("strategy"),
        "final_state_at_entry": decision.get("final_state"),
        "outcome": _v29_safe_upper(payload.get("outcome"), "UNKNOWN"),
        "pnl": _v29_safe_float(payload.get("pnl"), None),
        "pnl_r": _v29_safe_float(payload.get("pnl_r"), None),
        "mfe_r": _v29_safe_float(payload.get("mfe_r"), None),
        "mae_r": _v29_safe_float(payload.get("mae_r"), None),
        "exit_underlying_price": _v29_safe_float(payload.get("exit_underlying_price"), None),
        "exit_option_mid": _v29_safe_float(payload.get("exit_option_mid"), None),
        "note": payload.get("note"),
        "duration_minutes": _v32_duration_minutes(decision, closed_at),
    }

    outcomes = _v32_load_outcomes_journal()
    outcomes.append(outcome)
    outcomes = outcomes[-5000:]
    _v32_write_list(_V32_OUTCOMES_JOURNAL_FILE, outcomes)

    decision["outcome_status"] = outcome["outcome"]
    decision["latest_outcome"] = outcome
    if outcome.get("mfe_r") is not None or outcome.get("mae_r") is not None:
        summary = dict(decision.get("followup_summary") or {})
        if outcome.get("mfe_r") is not None:
            summary["mfe_r"] = outcome.get("mfe_r")
        if outcome.get("mae_r") is not None:
            summary["mae_r"] = outcome.get("mae_r")
        decision["followup_summary"] = summary
    _v32_replace_decision_record(decision)

    return {
        "status": "ok",
        "engine": _V32_ENGINE,
        "decision_id": decision_id,
        "outcome": outcome,
    }


def _v32_outcome_stats(outcomes):
    closed = [o for o in outcomes if _v29_safe_upper(o.get("outcome"), "UNKNOWN") in ["WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"]]
    wins = [o for o in closed if _v29_safe_upper(o.get("outcome"), "UNKNOWN") == "WIN"]
    losses = [o for o in closed if _v29_safe_upper(o.get("outcome"), "UNKNOWN") == "LOSS"]
    pnl_values = [o.get("pnl") for o in closed if _v29_safe_float(o.get("pnl"), None) is not None]

    by_strategy = {}
    by_ticker = {}
    for item in outcomes:
        strategy = _v29_safe_upper(item.get("strategy"), "UNKNOWN")
        ticker = _v29_safe_upper(item.get("ticker"), "UNKNOWN")
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1
        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1

    return {
        "total_outcomes": len(outcomes),
        "closed_outcomes": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / max(len(wins) + len(losses), 1)) * 100, 2),
        "net_pnl": round(sum(pnl_values), 2) if pnl_values else 0,
        "avg_pnl": round(sum(pnl_values) / len(pnl_values), 2) if pnl_values else 0,
        "by_strategy": by_strategy,
        "by_ticker": by_ticker,
    }


def _v32_history_summary(decisions, outcomes):
    by_state = {}
    for decision in decisions:
        state = str(decision.get("final_state") or "UNKNOWN")
        by_state[state] = by_state.get(state, 0) + 1

    return {
        "decision_count": len(decisions),
        "open_decisions": sum(1 for d in decisions if str(d.get("outcome_status") or "OPEN") == "OPEN"),
        "entry_ready_decisions": sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY"),
        "risk_blocked_decisions": sum(1 for d in decisions if d.get("final_state") == "RISK_BLOCKED"),
        "wait_options_decisions": sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA"),
        "by_state": by_state,
        "outcomes": _v32_outcome_stats(outcomes),
    }


def _v29_finalize_decision(decision, master):
    payload = dict(decision)
    payload["snapshot_generated_at"] = (master.get("data") or {}).get("generated_at")
    payload["snapshot_received_at"] = (master.get("data") or {}).get("received_at")
    payload["selected_contract"] = _selected_contract_from_v29(payload)
    record, _created = _v32_record_decision(payload)
    payload["decision_id"] = record.get("decision_id")
    return payload


def _v29_strategy_risk_gate(quality_gate, technical_state, row=None, strategy="UNKNOWN"):
    technical_raw = technical_state.get("raw") if isinstance(technical_state, dict) else {}
    event_risk = bool(technical_raw.get("event_risk", False))
    earnings_soon = bool(technical_raw.get("earnings_soon", False))
    volume = quality_gate.get("volume")
    open_interest = quality_gate.get("open_interest")
    canslim_gate = _v29_canslim_gate(row or {}, technical_raw, strategy)

    blockers = []
    blockers.extend(shared_technical_event_blockers(event_risk=event_risk, earnings_soon=earnings_soon))
    blockers.extend(shared_liquidity_blockers(volume=volume, open_interest=open_interest))
    blockers.extend(canslim_gate.get("blockers", []))

    return {
        "ok": not blockers,
        "blockers": blockers,
        "event_risk": event_risk,
        "earnings_soon": earnings_soon,
        "volume": volume,
        "open_interest": open_interest,
        "canslim": canslim_gate,
    }


def _canonical_strategy_risk_gate_from_sources(row, technical, strategy="UNKNOWN"):
    technical = technical or {}
    row = row or {}

    event_risk = bool(technical.get("event_risk", False))
    earnings_soon = bool(technical.get("earnings_soon", False))
    volume = _v29_safe_float(row.get("volume"), None)
    open_interest = _v29_safe_float(row.get("open_interest") or row.get("oi"), None)
    canslim_gate = _v29_canslim_gate(row, technical, strategy)

    blockers = []
    blockers.extend(shared_technical_event_blockers(event_risk=event_risk, earnings_soon=earnings_soon))
    blockers.extend(shared_liquidity_blockers(volume=volume, open_interest=open_interest))
    blockers.extend(canslim_gate.get("blockers", []))

    return {
        "ok": not blockers,
        "blockers": blockers,
        "event_risk": event_risk,
        "earnings_soon": earnings_soon,
        "volume": volume,
        "open_interest": open_interest,
        "canslim": canslim_gate,
    }


def _canonical_decision_state(
    *,
    ticker,
    strategy,
    option_ok,
    option_reason,
    technical_ok,
    technical_reason,
    market_ok,
    row,
    technical,
):
    strategy_risk = _canonical_strategy_risk_gate_from_sources(row, technical, strategy)

    if option_ok and strategy_risk["ok"] and technical_ok and market_ok:
        return {
            "final_state": "ENTRY_READY",
            "decision": "ENTRY_READY",
            "can_operate": True,
            "severity": "green",
            "main_blocker": None,
            "blockers": [],
            "action": f"{ticker}: entrada potencial lista. Validar tamaño, spread, liquidez, evento y riesgo final antes de ejecutar.",
            "risk_gate": strategy_risk,
        }

    if option_ok and not strategy_risk["ok"]:
        blocker = strategy_risk["blockers"][0]
        action = f"{ticker}: contrato ejecutable, pero existe un bloqueo adicional de riesgo/liquidez."
        if blocker == "EVENT_RISK_ACTIVE":
            action = f"{ticker}: contrato ejecutable, pero event risk activo bloquea la entrada."
        elif blocker == "EARNINGS_SOON":
            action = f"{ticker}: contrato ejecutable, pero earnings próximos bloquean la entrada."
        elif blocker == "LOW_OPTION_VOLUME":
            action = f"{ticker}: contrato ejecutable, pero el volumen de la opción está por debajo del mínimo de {OPTION_MIN_VOLUME_READY}."
        elif blocker == "LOW_OPEN_INTEREST":
            action = f"{ticker}: contrato ejecutable, pero el open interest está por debajo del mínimo de {OPTION_MIN_OPEN_INTEREST_READY}."
        elif blocker in ["CANSLIM_BLOCKED", "CANSLIM_SCORE_BELOW_MIN"]:
            action = f"{ticker}: contrato ejecutable, pero CANSLIM/fundamental filter bloquea la entrada."

        return {
            "final_state": "RISK_BLOCKED",
            "decision": "RISK_BLOCKED",
            "can_operate": False,
            "severity": "red",
            "main_blocker": blocker,
            "blockers": strategy_risk["blockers"],
            "action": action,
            "risk_gate": strategy_risk,
        }

    if option_ok and technical_ok and not market_ok:
        return {
            "final_state": "WAIT_MARKET_OPEN",
            "decision": "WAIT_MARKET_OPEN",
            "can_operate": False,
            "severity": "gray",
            "main_blocker": "MARKET_OR_OPTIONS_WINDOW_NOT_RELIABLE",
            "blockers": ["MARKET_OR_OPTIONS_WINDOW_NOT_RELIABLE"],
            "action": f"{ticker}: setup válido, pero esperar ventana confiable de mercado/opciones.",
            "risk_gate": strategy_risk,
        }

    if not technical_ok:
        return {
            "final_state": "WAIT_TECHNICAL",
            "decision": "WAIT_TECHNICAL",
            "can_operate": False,
            "severity": "yellow",
            "main_blocker": technical_reason or "TECHNICAL_NOT_CONFIRMED",
            "blockers": [technical_reason or "TECHNICAL_NOT_CONFIRMED"],
            "action": f"{ticker}: opciones evaluadas, pero falta confirmación técnica para {strategy}.",
            "risk_gate": strategy_risk,
        }

    if not option_ok:
        return {
            "final_state": "WAIT_OPTIONS_DATA",
            "decision": "WAIT_OPTIONS_DATA",
            "can_operate": False,
            "severity": "yellow",
            "main_blocker": option_reason or "WAIT_OPTIONS_DATA",
            "blockers": [option_reason or "WAIT_OPTIONS_DATA"],
            "action": f"{ticker}: técnico confirmado, pero faltan datos/confirmaciones de opciones.",
            "risk_gate": strategy_risk,
        }

    return {
        "final_state": "NO_DATA",
        "decision": "NO_DATA",
        "can_operate": False,
        "severity": "red",
        "main_blocker": "NO_DATA",
        "blockers": ["NO_DATA"],
        "action": f"{ticker}: no hay datos suficientes para evaluar operación.",
        "risk_gate": strategy_risk,
    }


def _v29_market_state(master):
    data = master.get("data") or {}
    market = data.get("market") or data.get("market_hours") or {}

    if not isinstance(market, dict):
        market = {}

    is_open = bool(
        market.get("is_regular_market_open") or
        market.get("regular_market_open") or
        market.get("is_open")
    )

    options_expected = bool(
        market.get("options_bidask_expected") or
        market.get("options_market_open") or
        is_open
    )

    label = market.get("label") or market.get("status") or "UNKNOWN"

    return {
        "is_regular_market_open": is_open,
        "options_bidask_expected": options_expected,
        "label": label,
        "raw": market,
    }


def _v29_decide_ticker(ticker):
    ticker = _v29_safe_upper(ticker)
    master = _v29_discover_master_snapshot()
    rows = master["rows"]
    technical = master["technical"]
    market = _v29_market_state(master)

    best, ticker_rows, executable_rows = _v29_best_row_for_ticker(ticker, rows)
    best_strategy = _v29_safe_upper((best or {}).get("strategy"), "UNKNOWN")
    tech_state = _v29_technical_state(ticker, technical, best_strategy)

    if not best:
        if tech_state["confirmed"]:
            return _v29_finalize_decision({
                "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
                "generated_at": _v29_now(),
                "ticker": ticker,
                "status": "OK",
                "final_state": "WAIT_OPTIONS_DATA",
                "decision": "WAIT_OPTIONS_DATA",
                "can_operate": False,
                "severity": "yellow",
                "strategy": "UNKNOWN",
                "technical_bias": tech_state["trend"],
                "technical_score": tech_state["score"],
                "options_score": None,
                "main_blocker": "NO_OPTIONS_ROWS_FOR_TICKER",
                "blockers": ["NO_OPTIONS_ROWS_FOR_TICKER"],
                "action": f"{ticker}: técnico confirmado, pero faltan filas de opciones para evaluar contrato ejecutable.",
                "executive_summary": f"{ticker}: WAIT_OPTIONS_DATA. Hay técnico confirmado, pero aún no hay filas de opciones para evaluar operación.",
                "risk_note": "No ejecutar sin validar manualmente datos, liquidez, spread, evento, capital y tolerancia de riesgo.",
                "best_row": None,
                "rows_found_for_ticker": 0,
                "total_rows_found": len(rows),
                "executable_rows_found": 0,
                "technical": tech_state,
                "market": market,
                "master_source": master["path"],
            }, master)
        return _v29_finalize_decision({
            "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
            "generated_at": _v29_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "strategy": "UNKNOWN",
            "technical_bias": tech_state["trend"],
            "technical_score": tech_state["score"],
            "options_score": None,
            "main_blocker": "NO_OPTIONS_ROWS_FOR_TICKER",
            "action": f"{ticker}: no hay filas de opciones detectadas.",
            "executive_summary": f"{ticker}: NO_DATA. No hay datos de opciones para evaluar operación.",
            "risk_note": "No ejecutar sin validar manualmente datos, liquidez, spread, evento, capital y tolerancia de riesgo.",
            "best_row": None,
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "executable_rows_found": 0,
            "technical": tech_state,
            "market": market,
            "master_source": master["path"],
        }, master)

    q = _v29_quality_gate(best)
    strategy = _v29_safe_upper(best.get("strategy"), "UNKNOWN")
    options_score = _v29_safe_float(best.get("score"), 0)

    market_ok = bool(market.get("is_regular_market_open")) and bool(market.get("options_bidask_expected"))
    technical_ok = tech_state["confirmed"]
    options_ok = q["executable"]
    risk_manual = _v29_risk_manual_gate(best)
    strategy_risk = _v29_strategy_risk_gate(q, tech_state, best, strategy)
    risk_ok = risk_manual["risk_ok"] and strategy_risk["ok"]
    manual_ok = risk_manual["manual_ok"]

    if technical_ok and not options_ok:
        final_state = "WAIT_OPTIONS_DATA"
        decision = "WAIT_OPTIONS_DATA"
        can_operate = False
        severity = "yellow"
        blocker = "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY"
        action = f"{ticker}: técnico confirmado, pero falta contrato ejecutable con bid/ask/mid/spread/spread_pct/delta/DTE/expiration/strike completos."
    elif not technical_ok:
        final_state = "WAIT_TECHNICAL"
        decision = "WAIT_TECHNICAL"
        can_operate = False
        severity = "yellow"
        blocker = "TECHNICAL_NOT_CONFIRMED"
        action = f"{ticker}: opciones evaluadas, pero falta confirmación técnica."
    elif not risk_manual["risk_ok"]:
        final_state = "RISK_BLOCKED"
        decision = "RISK_BLOCKED"
        can_operate = False
        severity = "red"
        blocker = risk_manual["risk_blocker"] or "RISK_NOT_CONFIRMED"
        action = f"{ticker}: contrato y técnico disponibles, pero falta aprobación explícita de riesgo."
    elif not strategy_risk["ok"]:
        final_state = "RISK_BLOCKED"
        decision = "RISK_BLOCKED"
        can_operate = False
        severity = "red"
        blocker = strategy_risk["blockers"][0]
        if blocker == "EVENT_RISK_ACTIVE":
            action = f"{ticker}: contrato ejecutable, pero event risk activo bloquea la entrada."
        elif blocker == "EARNINGS_SOON":
            action = f"{ticker}: contrato ejecutable, pero earnings próximos bloquean la entrada."
        elif blocker == "LOW_OPTION_VOLUME":
            action = f"{ticker}: contrato ejecutable, pero el volumen de la opción está por debajo del mínimo de {OPTION_MIN_VOLUME_READY}."
        elif blocker == "LOW_OPEN_INTEREST":
            action = f"{ticker}: contrato ejecutable, pero el open interest está por debajo del mínimo de {OPTION_MIN_OPEN_INTEREST_READY}."
        elif blocker in ["CANSLIM_BLOCKED", "CANSLIM_SCORE_BELOW_MIN"]:
            action = f"{ticker}: contrato y técnico disponibles, pero CANSLIM/fundamental filter bloquea la entrada."
        else:
            action = f"{ticker}: contrato ejecutable, pero existe un bloqueo adicional de riesgo/liquidez."
    elif not manual_ok:
        final_state = "MANUAL_REVIEW_BLOCKED"
        decision = "MANUAL_REVIEW_BLOCKED"
        can_operate = False
        severity = "orange"
        blocker = ",".join(risk_manual["manual_blockers"]) or "MANUAL_REVIEW_REQUIRED"
        action = f"{ticker}: oportunidad bloqueada por revisión manual pendiente."
    elif not market_ok:
        final_state = "WAIT_MARKET_OPEN"
        decision = "WAIT_MARKET_OPEN"
        can_operate = False
        severity = "gray"
        blocker = "MARKET_OR_OPTIONS_WINDOW_NOT_RELIABLE"
        action = f"{ticker}: setup completo, pero esperar ventana confiable de mercado/opciones."
    elif market_ok and technical_ok and options_ok and risk_ok and manual_ok:
        final_state = "ENTRY_READY"
        decision = "ENTRY_READY"
        can_operate = True
        severity = "green"
        blocker = None
        action = f"{ticker}: entrada potencial lista. Validar tamaño, spread, liquidez, evento y riesgo final antes de ejecutar."
    else:
        final_state = "RADAR"
        decision = "RADAR"
        can_operate = False
        severity = "yellow"
        blocker = "UNKNOWN_CONFIRMATION_GAP"
        action = f"{ticker}: mantener en radar. Confirmaciones incompletas."

    result_blockers = [blocker] if blocker else []
    if final_state == "RISK_BLOCKED" and strategy_risk["blockers"] and risk_manual["risk_ok"]:
        result_blockers = strategy_risk["blockers"]
    elif final_state == "MANUAL_REVIEW_BLOCKED" and risk_manual["manual_blockers"]:
        result_blockers = risk_manual["manual_blockers"]

    executive_summary = (
        f"{ticker}: {final_state}. "
        f"Estrategia {strategy}. "
        f"Técnico {tech_state['trend']} score {tech_state['score']}. "
        f"Opciones score {options_score}. "
        f"Spread {q.get('spread')} / {q.get('spread_pct')}%. "
        f"Vol/OI {q.get('volume')} / {q.get('open_interest')}. "
        f"Bloqueador: {blocker or 'None'}."
    )

    return _v29_finalize_decision({
        "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
        "generated_at": _v29_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": can_operate,
        "severity": severity,
        "strategy": strategy,
        "technical_bias": tech_state["trend"],
        "technical_score": tech_state["score"],
        "options_score": options_score,
        "options_fit": "EXECUTABLE_CONTRACT_CONFIRMED" if options_ok else "OPTIONS_DATA_INCOMPLETE_BID_ASK_SPREAD_STRIKE_EXPIRATION_DTE_DELTA",
        "technical_fit": "TECHNICAL_CONFIRMED_BY_SCORE" if technical_ok else "TECHNICAL_NOT_CONFIRMED",
        "risk_fit": "RISK_CONFIRMED" if risk_ok else (risk_manual["risk_blocker"] or ",".join(strategy_risk["blockers"]) or "RISK_NOT_CONFIRMED"),
        "strategy_risk_fit": "STRATEGY_RISK_CONFIRMED" if strategy_risk["ok"] else ",".join(strategy_risk["blockers"]),
        "manual_review_fit": "NO_MANUAL_BLOCKERS" if manual_ok else "MANUAL_REVIEW_BLOCKED",
        "main_blocker": blocker,
        "blockers": result_blockers,
        "required_missing_fields": q["missing"],
        "action": action,
        "executive_summary": executive_summary,
        "risk_note": "No ejecutar sin validar manualmente tamaño, liquidez, spread, evento, capital disponible y tolerancia de riesgo.",
        "risk_gate": {
            **risk_manual,
            "strategy_risk_ok": strategy_risk["ok"],
            "strategy_risk_blockers": strategy_risk["blockers"],
            "event_risk": strategy_risk["event_risk"],
            "earnings_soon": strategy_risk["earnings_soon"],
            "volume": strategy_risk["volume"],
            "open_interest": strategy_risk["open_interest"],
            "canslim": strategy_risk.get("canslim"),
        },
        "best_row": best,
        "best_row_quality": q,
        "rows_found_for_ticker": len(ticker_rows),
        "total_rows_found": len(rows),
        "executable_rows_found": len(executable_rows),
        "technical": tech_state,
        "market": market,
        "master_source": master["path"],
    }, master)


def _v29_all_decisions(tickers=None):
    if not tickers:
        tickers = _V29_DEFAULT_TICKERS
    return [_v29_decide_ticker(t) for t in tickers]


def _v31_canonical_state(v29_state):
    mapping = {
        "WAIT_MARKET_OPEN": "WAIT_MARKET",
        "MANUAL_REVIEW_BLOCKED": "MANUAL_REVIEW",
        "RADAR": "MANUAL_REVIEW",
    }
    state = mapping.get(str(v29_state or ""), v29_state)
    if state not in _V31_CANONICAL_STATES:
        return "NO_DATA"
    return state


def _v31_selected_contract(v29_decision):
    return _selected_contract_from_v29(v29_decision)


def _v31_decision_contract(v29_decision):
    final_state = _v31_canonical_state(v29_decision.get("final_state"))
    blockers = list(v29_decision.get("blockers") or [])
    main_blocker = v29_decision.get("main_blocker")
    if main_blocker and main_blocker not in blockers:
        blockers.insert(0, main_blocker)

    return {
        "engine": "V31_CANONICAL_DECISION_CONTRACT",
        "source_engine": v29_decision.get("engine"),
        "decision_id": v29_decision.get("decision_id"),
        "decision_version": _V31_DECISION_VERSION,
        "strategy_version": _V31_STRATEGY_VERSION,
        "ruleset_version": _V31_RULESET_VERSION,
        "snapshot_version": _V31_SNAPSHOT_VERSION,
        "generated_at": _v29_now(),
        "ticker": v29_decision.get("ticker"),
        "status": v29_decision.get("status", "OK"),
        "final_state": final_state,
        "decision": final_state,
        "main_blocker": main_blocker,
        "blockers": blockers,
        "required_missing_fields": list(v29_decision.get("required_missing_fields") or []),
        "risk_notes": [
            v29_decision.get("risk_note"),
            "ENTRY_READY means ready for manual review, not authorization to trade.",
        ],
        "explanation": v29_decision.get("executive_summary") or v29_decision.get("action"),
        "next_required_action": v29_decision.get("action"),
        "not_order_instruction": True,
        "ready_for_manual_review": final_state == "ENTRY_READY",
        "execution_authorized": False,
        "selected_contract": _v31_selected_contract(v29_decision),
        "technical": {
            "bias": v29_decision.get("technical_bias"),
            "score": v29_decision.get("technical_score"),
            "fit": v29_decision.get("technical_fit"),
            "raw": v29_decision.get("technical"),
        },
        "risk": {
            "fit": v29_decision.get("risk_fit"),
            "manual_review_fit": v29_decision.get("manual_review_fit"),
            "gate": v29_decision.get("risk_gate"),
        },
        "market": v29_decision.get("market"),
        "audit": {
            "decision_id": v29_decision.get("decision_id"),
            "master_source": v29_decision.get("master_source"),
            "snapshot_generated_at": v29_decision.get("snapshot_generated_at"),
            "snapshot_received_at": v29_decision.get("snapshot_received_at"),
            "rows_found_for_ticker": v29_decision.get("rows_found_for_ticker"),
            "total_rows_found": v29_decision.get("total_rows_found"),
            "executable_rows_found": v29_decision.get("executable_rows_found"),
            "source_final_state": v29_decision.get("final_state"),
            "source_decision": v29_decision.get("decision"),
        },
    }


def _v31_decide_ticker(ticker):
    return _v31_decision_contract(_v29_decide_ticker(ticker))


def _v31_all_decisions(tickers=None):
    if not tickers:
        tickers = _V29_DEFAULT_TICKERS
    return [_v31_decide_ticker(t) for t in tickers]


def _v29_html_escape(x):
    return _v29_html.escape("" if x is None else str(x))


def _v29_badge(state):
    color = "#64748b"
    if state == "ENTRY_READY":
        color = "#16a34a"
    elif state in ["NO_DATA"]:
        color = "#dc2626"
    elif state.startswith("WAIT"):
        color = "#ca8a04"
    elif state == "RADAR":
        color = "#2563eb"

    return f'<span style="background:{color};color:white;padding:7px 12px;border-radius:999px;font-weight:800;font-size:12px;">{_v29_html_escape(state)}</span>'


def _v29_dashboard_html(tickers=None):
    decisions = _v29_all_decisions(tickers)

    counts = {
        "ENTRY_READY": 0,
        "WAIT_TECHNICAL": 0,
        "WAIT_OPTIONS": 0,
        "WAIT_MARKET": 0,
        "NO_DATA": 0,
        "RADAR": 0,
    }

    for d in decisions:
        fs = d.get("final_state")
        if fs == "ENTRY_READY":
            counts["ENTRY_READY"] += 1
        elif fs == "WAIT_TECHNICAL":
            counts["WAIT_TECHNICAL"] += 1
        elif fs == "WAIT_OPTIONS_DATA":
            counts["WAIT_OPTIONS"] += 1
        elif fs == "WAIT_MARKET_OPEN":
            counts["WAIT_MARKET"] += 1
        elif fs == "NO_DATA":
            counts["NO_DATA"] += 1
        else:
            counts["RADAR"] += 1

    rows_html = ""

    for d in decisions:
        br = d.get("best_row") or {}
        q = d.get("best_row_quality") or {}
        rows_html += f"""
        <tr>
            <td><a href="/v29_trade_decision/{_v29_html_escape(d.get('ticker'))}">{_v29_html_escape(d.get('ticker'))}</a></td>
            <td>{_v29_badge(d.get('final_state'))}</td>
            <td>{_v29_html_escape(d.get('strategy'))}</td>
            <td>{_v29_html_escape(d.get('technical_bias'))}</td>
            <td>{_v29_html_escape(d.get('technical_score'))}</td>
            <td>{_v29_html_escape(d.get('options_score'))}</td>
            <td>{_v29_html_escape(br.get('strike'))}</td>
            <td>{_v29_html_escape(br.get('expiration'))}</td>
            <td>{_v29_html_escape(br.get('dte'))}</td>
            <td>{_v29_html_escape(q.get('bid'))}</td>
            <td>{_v29_html_escape(q.get('ask'))}</td>
            <td>{_v29_html_escape(q.get('mid'))}</td>
            <td>{_v29_html_escape(q.get('spread'))}</td>
            <td>{_v29_html_escape(q.get('spread_pct'))}</td>
            <td>{'Sí' if d.get('can_operate') else 'No'}</td>
            <td>{_v29_html_escape(d.get('main_blocker'))}</td>
            <td>{_v29_html_escape(d.get('action'))}</td>
        </tr>
        """

    generated = _v29_now()

    return f"""
    <!doctype html>
    <html>
    <head>
        <title>V29 Final Decision Quality Engine</title>
        <style>
            body {{
                font-family: Inter, Arial, sans-serif;
                background:#f5f7fb;
                color:#0f172a;
                margin:0;
                padding:32px;
            }}
            h1 {{font-size:34px; margin-bottom:22px;}}
            .hero {{
                background:#0f172a;
                color:white;
                border-radius:26px;
                padding:34px;
                margin-bottom:26px;
            }}
            .hero h2 {{margin:0 0 14px 0; font-size:26px;}}
            .cards {{
                display:grid;
                grid-template-columns: repeat(6, 1fr);
                gap:16px;
                margin-bottom:24px;
            }}
            .card {{
                background:white;
                border-radius:18px;
                padding:20px;
                box-shadow:0 12px 30px rgba(15,23,42,.08);
            }}
            .label {{
                color:#64748b;
                font-size:12px;
                text-transform:uppercase;
                font-weight:800;
                letter-spacing:.08em;
            }}
            .num {{
                font-size:34px;
                font-weight:900;
                margin-top:8px;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                background:white;
                border-radius:18px;
                overflow:hidden;
                box-shadow:0 12px 30px rgba(15,23,42,.08);
                font-size:13px;
            }}
            th {{
                text-align:left;
                padding:14px;
                color:#64748b;
                font-size:11px;
                text-transform:uppercase;
                letter-spacing:.08em;
                border-bottom:1px solid #e2e8f0;
            }}
            td {{
                padding:14px;
                border-bottom:1px solid #e2e8f0;
                vertical-align:top;
            }}
            .foot {{
                color:#64748b;
                margin-top:18px;
                font-size:14px;
            }}
            a {{color:#2563eb; font-weight:800;}}
        </style>
    </head>
    <body>
        <h1>V29 — Final Decision Quality Engine</h1>

        <div class="hero">
            <h2>Execution Guard activo</h2>
            <p>Selecciona únicamente contratos realmente ejecutables: bid/ask/spread/delta/DTE/strike + técnico + mercado.</p>
            <p>Generado: {generated}</p>
        </div>

        <div class="cards">
            <div class="card"><div class="label">Entry Ready</div><div class="num">{counts["ENTRY_READY"]}</div></div>
            <div class="card"><div class="label">Wait Technical</div><div class="num">{counts["WAIT_TECHNICAL"]}</div></div>
            <div class="card"><div class="label">Wait Options</div><div class="num">{counts["WAIT_OPTIONS"]}</div></div>
            <div class="card"><div class="label">Wait Market</div><div class="num">{counts["WAIT_MARKET"]}</div></div>
            <div class="card"><div class="label">No Data</div><div class="num">{counts["NO_DATA"]}</div></div>
            <div class="card"><div class="label">Radar</div><div class="num">{counts["RADAR"]}</div></div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Estado</th>
                    <th>Estrategia</th>
                    <th>Sesgo técnico</th>
                    <th>Score técnico</th>
                    <th>Score opciones</th>
                    <th>Strike</th>
                    <th>Exp</th>
                    <th>DTE</th>
                    <th>Bid</th>
                    <th>Ask</th>
                    <th>Mid</th>
                    <th>Spread</th>
                    <th>Spread %</th>
                    <th>Operable</th>
                    <th>Bloqueador</th>
                    <th>Acción</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div class="foot">
            Endpoints: /v29_system_status · /v29_trade_decision/QQQ · /gpt_v29_trade_decision/QQQ · /v29_dashboard
        </div>
    </body>
    </html>
    """


@app.get("/v29_system_status")
async def v29_system_status():
    master = _v29_discover_master_snapshot()
    market = _v29_market_state(master)
    decisions = _v29_all_decisions()

    return {
        "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
        "generated_at": _v29_now(),
        "status": "OK",
        "master_snapshot_available": bool(master.get("path")),
        "master_source": master.get("path"),
        "rows_found": len(master.get("rows", [])),
        "technical_count": len(master.get("technical", {})),
        "technical_tickers": sorted(list(master.get("technical", {}).keys())),
        "market": market,
        "summary": {
            "entry_ready": sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY"),
            "wait_technical": sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL"),
            "wait_options": sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA"),
            "wait_market": sum(1 for d in decisions if d.get("final_state") == "WAIT_MARKET_OPEN"),
            "no_data": sum(1 for d in decisions if d.get("final_state") == "NO_DATA"),
        },
        "endpoints": {
            "trade_decision_example": "/v29_trade_decision/QQQ",
            "gpt_trade_decision_example": "/gpt_v29_trade_decision/QQQ",
            "dashboard": "/v29_dashboard",
            "dashboard_ticker_example": "/v29_dashboard/QQQ",
        },
    }


@app.get("/v29_trade_decision/{ticker}")
async def v29_trade_decision(ticker: str):
    return _v29_decide_ticker(ticker)


@app.get("/gpt_v29_trade_decision/{ticker}")
async def gpt_v29_trade_decision(ticker: str):
    d = _v29_decide_ticker(ticker)
    return {
        "decision_id": d.get("decision_id"),
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "strategy": d.get("strategy"),
        "technical_bias": d.get("technical_bias"),
        "technical_score": d.get("technical_score"),
        "technical_fit": d.get("technical_fit"),
        "options_score": d.get("options_score"),
        "options_fit": d.get("options_fit"),
        "risk_fit": d.get("risk_fit"),
        "strategy_risk_fit": d.get("strategy_risk_fit"),
        "manual_review_fit": d.get("manual_review_fit"),
        "risk_gate": d.get("risk_gate"),
        "best_contract": {
            "strike": (d.get("best_row") or {}).get("strike"),
            "expiration": (d.get("best_row") or {}).get("expiration"),
            "dte": (d.get("best_row") or {}).get("dte"),
            "bid": (d.get("best_row_quality") or {}).get("bid"),
            "ask": (d.get("best_row_quality") or {}).get("ask"),
            "mid": (d.get("best_row_quality") or {}).get("mid"),
            "spread": (d.get("best_row_quality") or {}).get("spread"),
            "spread_pct": (d.get("best_row_quality") or {}).get("spread_pct"),
            "delta": (d.get("best_row_quality") or {}).get("delta"),
            "gamma": (d.get("best_row_quality") or {}).get("gamma"),
            "theta": (d.get("best_row_quality") or {}).get("theta"),
            "vega": (d.get("best_row_quality") or {}).get("vega"),
            "iv": (d.get("best_row_quality") or {}).get("iv"),
            "volume": (d.get("best_row_quality") or {}).get("volume"),
            "open_interest": (d.get("best_row_quality") or {}).get("open_interest"),
            "data_quality": (d.get("best_row") or {}).get("data_quality"),
            "can_operate": d.get("can_operate"),
            "missing_confirmations": (d.get("best_row") or {}).get("missing_confirmations") or (d.get("best_row_quality") or {}).get("missing"),
            "recommendation": (d.get("best_row") or {}).get("recommendation"),
            "reason": (d.get("best_row") or {}).get("reason"),
            "missing": (d.get("best_row_quality") or {}).get("missing"),
        },
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "risk_note": d.get("risk_note"),
        "master_source": d.get("master_source"),
        "engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
        "generated_at": _v29_now(),
    }


@app.get("/strategy_signal_contract")
async def strategy_signal_contract():
    return _v29_strategy_signal_contract()


@app.get("/strategy_signal_template")
async def strategy_signal_template(ticker: str = "QQQ", strategy_context: str = "NAKED_PUT"):
    return {
        "contract": _v29_strategy_signal_contract(),
        "alert_payload_template": _v29_strategy_signal_template(ticker, strategy_context),
        "not_order_instruction": True,
    }


@app.get("/v31_system_status")
async def v31_system_status():
    master = _v29_discover_master_snapshot()
    decisions = _v31_all_decisions()

    return {
        "engine": "V31_CANONICAL_DECISION_CONTRACT",
        "decision_version": _V31_DECISION_VERSION,
        "strategy_version": _V31_STRATEGY_VERSION,
        "ruleset_version": _V31_RULESET_VERSION,
        "snapshot_version": _V31_SNAPSHOT_VERSION,
        "generated_at": _v29_now(),
        "status": "OK",
        "canonical_states": _V31_CANONICAL_STATES,
        "source_engine": "V29_FINAL_DECISION_QUALITY_ENGINE",
        "master_snapshot_available": bool(master.get("path")),
        "master_source": master.get("path"),
        "summary": {
            "entry_ready": sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY"),
            "manual_review": sum(1 for d in decisions if d.get("final_state") == "MANUAL_REVIEW"),
            "risk_blocked": sum(1 for d in decisions if d.get("final_state") == "RISK_BLOCKED"),
            "wait_technical": sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL"),
            "wait_options": sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA"),
            "wait_market": sum(1 for d in decisions if d.get("final_state") == "WAIT_MARKET"),
            "no_data": sum(1 for d in decisions if d.get("final_state") == "NO_DATA"),
        },
        "not_order_instruction": True,
        "endpoints": {
            "trade_decision_example": "/v31_trade_decision/QQQ",
            "gpt_trade_decision_example": "/gpt_v31_trade_decision/QQQ",
            "source_status": "/v29_system_status",
        },
    }


@app.get("/v31_trade_decision/{ticker}")
async def v31_trade_decision(ticker: str):
    return _v31_decide_ticker(ticker)


@app.get("/gpt_v31_trade_decision/{ticker}")
async def gpt_v31_trade_decision(ticker: str):
    d = _v31_decide_ticker(ticker)
    return {
        "engine": d.get("engine"),
        "decision_id": d.get("decision_id"),
        "decision_version": d.get("decision_version"),
        "strategy_version": d.get("strategy_version"),
        "ruleset_version": d.get("ruleset_version"),
        "snapshot_version": d.get("snapshot_version"),
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "main_blocker": d.get("main_blocker"),
        "blockers": d.get("blockers"),
        "required_missing_fields": d.get("required_missing_fields"),
        "selected_contract": d.get("selected_contract"),
        "technical": d.get("technical"),
        "risk": d.get("risk"),
        "explanation": d.get("explanation"),
        "next_required_action": d.get("next_required_action"),
        "risk_notes": d.get("risk_notes"),
        "ready_for_manual_review": d.get("ready_for_manual_review"),
        "execution_authorized": False,
        "not_order_instruction": True,
        "audit": d.get("audit"),
        "generated_at": d.get("generated_at"),
    }


@app.get("/v32_decision_history")
async def v32_decision_history(limit: int = 100, ticker: Optional[str] = None):
    decisions = _v32_load_decision_journal()
    if ticker:
        wanted = _v29_safe_upper(ticker)
        decisions = [d for d in decisions if _v29_safe_upper(d.get("ticker")) == wanted]

    trimmed = decisions[-max(1, min(limit, 500)):]
    outcomes = _v32_load_outcomes_journal()
    return {
        "engine": _V32_ENGINE,
        "generated_at": _v29_now(),
        "showing": len(trimmed),
        "ticker_filter": _v29_safe_upper(ticker, "") if ticker else None,
        "summary": _v32_history_summary(decisions, outcomes),
        "decisions": trimmed,
    }


@app.post("/v32_record_followup")
async def v32_record_followup(payload: dict):
    return _v32_followup_entry(payload or {})


@app.post("/v32_record_outcome")
async def v32_record_outcome(payload: dict):
    return _v32_outcome_entry(payload or {})


@app.get("/v32_outcomes_summary")
async def v32_outcomes_summary(limit: int = 100):
    decisions = _v32_load_decision_journal()
    outcomes = _v32_load_outcomes_journal()
    trimmed_decisions = decisions[-max(1, min(limit, 500)):]
    trimmed_outcomes = outcomes[-max(1, min(limit, 500)):]
    return {
        "engine": _V32_ENGINE,
        "generated_at": _v29_now(),
        "decision_version": _V31_DECISION_VERSION,
        "strategy_version": _V31_STRATEGY_VERSION,
        "ruleset_version": _V31_RULESET_VERSION,
        "snapshot_version": _V31_SNAPSHOT_VERSION,
        "summary": _v32_history_summary(decisions, outcomes),
        "recent_decisions": trimmed_decisions,
        "recent_outcomes": trimmed_outcomes,
        "endpoints": {
            "decision_history": "/v32_decision_history",
            "record_followup": "/v32_record_followup",
            "record_outcome": "/v32_record_outcome",
        },
    }


@app.get("/v29_dashboard", response_class=_V29HTMLResponse)
async def v29_dashboard():
    return _v29_dashboard_html()


@app.get("/v29_dashboard/{ticker}", response_class=_V29HTMLResponse)
async def v29_dashboard_ticker(ticker: str):
    return _v29_dashboard_html([ticker])


# ============================================================
# V30 PASSIVE MONITOR + MANUAL EMAIL NOTIFICATION
# ============================================================

def _v30_monitor_base_url():
    return PUBLIC_BASE_URL or "https://trading-engine-p097.onrender.com"


def _v30_send_resend_email(to_email, subject, text_body, html_body=None):
    missing = []
    if not RESEND_API_KEY:
        missing.append("RESEND_API_KEY")
    if not to_email:
        missing.append("MONITOR_EMAIL_TO or PREMARKET_EMAIL_TO")
    if not MONITOR_EMAIL_FROM:
        missing.append("MONITOR_EMAIL_FROM or PREMARKET_EMAIL_FROM")

    if missing:
        return {
            "email_sent": False,
            "provider": "resend",
            "reason": "EMAIL_CONFIG_MISSING",
            "missing": missing,
        }

    payload = {
        "from": MONITOR_EMAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
    }
    if html_body:
        payload["html"] = html_body

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=12,
        )
        ok = 200 <= response.status_code < 300
        return {
            "email_sent": ok,
            "provider": "resend",
            "status_code": response.status_code,
            "reason": None if ok else "EMAIL_PROVIDER_REJECTED",
            "response": response.text[:500],
        }
    except Exception as exc:
        return {
            "email_sent": False,
            "provider": "resend",
            "reason": "EMAIL_SEND_ERROR",
            "error": str(exc),
        }


def _v30_monitor_status_payload():
    master = _v29_discover_master_snapshot()
    market = _v29_market_state(master)
    decisions = _v29_all_decisions()
    summary = {
        "entry_ready": sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY"),
        "manual_review_blocked": sum(1 for d in decisions if d.get("final_state") == "MANUAL_REVIEW_BLOCKED"),
        "risk_blocked": sum(1 for d in decisions if d.get("final_state") == "RISK_BLOCKED"),
        "wait_options": sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA"),
        "wait_technical": sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL"),
        "wait_market": sum(1 for d in decisions if d.get("final_state") == "WAIT_MARKET_OPEN"),
        "no_data": sum(1 for d in decisions if d.get("final_state") == "NO_DATA"),
    }

    entry_ready = [d for d in decisions if d.get("final_state") == "ENTRY_READY"]
    risk_blocked = [d for d in decisions if d.get("final_state") == "RISK_BLOCKED"]
    wait_options = [d for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA"]
    no_data = [d for d in decisions if d.get("final_state") == "NO_DATA"]

    market_open = bool(market.get("is_regular_market_open"))
    market_context = "REGULAR_MARKET_HOURS" if market_open else "OUTSIDE_MARKET_HOURS_OR_UNKNOWN"
    snapshot_available = bool(master.get("path"))

    if entry_ready:
        alert_level = "ACTION_REQUIRED"
        message = "Hay setups ENTRY_READY para revision manual. No es instruccion de operar."
        next_action = "Abrir el dashboard, revisar contrato, spread, liquidez, evento, sizing y riesgo antes de cualquier decision manual."
    elif not snapshot_available and market_open:
        alert_level = "ACTION_REQUIRED"
        message = "No hay snapshot maestro durante horario regular. Revisar bridge/publicador."
        next_action = "Validar que ibkr_bridge.py publique snapshot reciente y que Render lo reciba."
    elif risk_blocked:
        alert_level = "WARNING"
        message = "Hay setups bloqueados por riesgo. No intentar entrada hasta resolver blockers."
        next_action = "Revisar main_blocker y risk_gate por ticker."
    elif wait_options:
        alert_level = "WARNING"
        message = "Hay tecnico confirmado o candidatos, pero faltan datos ejecutables de opciones."
        next_action = "Confirmar bid/ask/mid/spread/spread_pct/strike/expiration/dte/delta desde IBKR."
    elif not snapshot_available:
        alert_level = "INFO"
        message = "No hay snapshot maestro; fuera de mercado no requiere accion inmediata."
        next_action = "Esperar siguiente ventana operativa o publicar snapshot manual si estas probando."
    elif no_data and len(no_data) == len(decisions):
        alert_level = "INFO"
        message = "El motor no encontro datos suficientes para tickers monitoreados."
        next_action = "Verificar universo, snapshot y technical_snapshot."
    else:
        alert_level = "OK"
        message = "Monitor activo sin setups listos para revision manual."
        next_action = "No hacer nada; seguir monitoreando."

    return {
        "engine": "V30_PASSIVE_PIPELINE_MONITOR",
        "generated_at": _v29_now(),
        "alert_level": alert_level,
        "market_context": market_context,
        "master_snapshot_available": snapshot_available,
        "master_source": master.get("path"),
        "rows_found": len(master.get("rows", [])),
        "technical_count": len(master.get("technical", {})),
        "technical_tickers": sorted(list(master.get("technical", {}).keys())),
        "summary": summary,
        "entry_ready_tickers": [d.get("ticker") for d in entry_ready],
        "risk_blocked_tickers": [d.get("ticker") for d in risk_blocked],
        "wait_options_tickers": [d.get("ticker") for d in wait_options],
        "message": message,
        "next_required_action": next_action,
        "notification_sent": False,
        "notification_channel": None,
        "not_order_instruction": True,
    }


def _v30_monitor_should_notify(monitor, force=False):
    if force:
        return True, "FORCED"
    if monitor.get("alert_level") == "ACTION_REQUIRED":
        return True, "ACTION_REQUIRED"
    if int(monitor.get("summary", {}).get("entry_ready") or 0) > 0:
        return True, "ENTRY_READY"
    return False, "NO_ACTIONABLE_ALERT"


def _v30_monitor_email_content(monitor):
    base = _v30_monitor_base_url()
    subject = f"Stock Ultimus V30 Monitor: {monitor.get('alert_level')}"
    lines = [
        "Stock Ultimus V30 Monitor",
        "",
        f"Alerta: {monitor.get('alert_level')}",
        f"Mensaje: {monitor.get('message')}",
        f"Accion requerida: {monitor.get('next_required_action')}",
        "",
        f"Mercado: {monitor.get('market_context')}",
        f"Snapshot maestro: {monitor.get('master_snapshot_available')}",
        f"Fuente: {monitor.get('master_source')}",
        f"Filas opciones: {monitor.get('rows_found')}",
        f"Snapshots tecnicos: {monitor.get('technical_count')}",
        f"ENTRY_READY: {monitor.get('entry_ready_tickers')}",
        f"RISK_BLOCKED: {monitor.get('risk_blocked_tickers')}",
        f"WAIT_OPTIONS_DATA: {monitor.get('wait_options_tickers')}",
        "",
        f"Dashboard: {base}/v29_dashboard",
        f"Estado monitor: {base}/v30_monitor_status",
        "",
        "Decision support solamente. No es instruccion de operar ni autorizacion para ejecutar ordenes.",
    ]
    text = "\n".join(lines)
    html_body = f"""
    <h2>Stock Ultimus V30 Monitor</h2>
    <p><strong>Alerta:</strong> {_v29_html_escape(monitor.get('alert_level'))}</p>
    <p><strong>Mensaje:</strong> {_v29_html_escape(monitor.get('message'))}</p>
    <p><strong>Accion requerida:</strong> {_v29_html_escape(monitor.get('next_required_action'))}</p>
    <ul>
      <li>Mercado: {_v29_html_escape(monitor.get('market_context'))}</li>
      <li>Snapshot maestro: {_v29_html_escape(monitor.get('master_snapshot_available'))}</li>
      <li>Filas opciones: {_v29_html_escape(monitor.get('rows_found'))}</li>
      <li>Snapshots tecnicos: {_v29_html_escape(monitor.get('technical_count'))}</li>
      <li>ENTRY_READY: {_v29_html_escape(monitor.get('entry_ready_tickers'))}</li>
      <li>RISK_BLOCKED: {_v29_html_escape(monitor.get('risk_blocked_tickers'))}</li>
      <li>WAIT_OPTIONS_DATA: {_v29_html_escape(monitor.get('wait_options_tickers'))}</li>
    </ul>
    <p><a href="{_v29_html_escape(base)}/v29_dashboard">Abrir dashboard</a></p>
    <p><a href="{_v29_html_escape(base)}/v30_monitor_status">Abrir estado del monitor</a></p>
    <p><em>Decision support solamente. No es instruccion de operar ni autorizacion para ejecutar ordenes.</em></p>
    """
    return subject, text, html_body


def _v30_monitor_notify_payload(force=False, to_email=None, dry_run=False):
    monitor = _v30_monitor_status_payload()
    should_notify, reason = _v30_monitor_should_notify(monitor, force=force)
    subject, text_body, html_body = _v30_monitor_email_content(monitor)

    base_payload = {
        "engine": "V30_PASSIVE_PIPELINE_MONITOR",
        "generated_at": _v29_now(),
        "would_notify": should_notify,
        "notify_reason": reason,
        "subject": subject,
        "monitor": monitor,
        "notification_channel": "email",
        "not_order_instruction": True,
    }

    if dry_run:
        return {
            **base_payload,
            "status": "preview",
            "email_sent": False,
            "text": text_body,
            "html": html_body,
        }

    if not should_notify:
        return {
            **base_payload,
            "status": "skipped",
            "email_sent": False,
            "reason": reason,
        }

    email_result = _v30_send_resend_email(
        to_email or MONITOR_EMAIL_TO,
        subject,
        text_body,
        html_body,
    )

    return {
        **base_payload,
        "status": "sent" if email_result.get("email_sent") else "not_sent",
        "email_sent": bool(email_result.get("email_sent")),
        "email_result": email_result,
    }


@app.get("/v30_monitor_status")
async def v30_monitor_status():
    return _v30_monitor_status_payload()


@app.get("/v30_monitor_notify/preview")
async def v30_monitor_notify_preview(force: bool = False):
    return _v30_monitor_notify_payload(force=force, dry_run=True)


@app.post("/v30_monitor_notify")
async def v30_monitor_notify(force: bool = False, to_email: Optional[str] = None):
    return _v30_monitor_notify_payload(force=force, to_email=to_email, dry_run=False)


# ============================================================
# END V29 FINAL DECISION QUALITY ENGINE
# ============================================================
