"""TradingView payload contract and validation for Stock Ultimus."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


PAYLOAD_CONTRACT_VERSION = "tradingview_signal_payload_v2"
OPTIONS_UNDERLYING_CONTEXT = "OPTIONS_UNDERLYING_CONFIRMATION"
REQUIRED_FIELDS = [
    "ticker",
    "timeframe",
    "strategy_context",
    "price",
    "session_state",
    "vwap",
    "opening_range_high",
    "opening_range_low",
    "breakout_direction",
    "adx",
    "atr",
    "volume_relative",
    "premarket_high",
    "premarket_low",
    "major_event_window",
    "risk_daily_status",
    "portfolio_status",
]
CONTEXT_REQUIRED_FIELDS = {
    OPTIONS_UNDERLYING_CONTEXT: [
        "rsi",
        "rsi_state",
        "trend_state",
        "market_regime",
        "underlying_signal",
    ],
}
OPTIONAL_FIELDS = [
    "event",
    "event_code",
    "action",
    "vwap_position",
    "invalidation",
    "logical_stop",
    "logical_target",
    "rsi",
    "rsi_state",
    "rsi_divergence",
    "ema_fast",
    "ema_slow",
    "trend_state",
    "trend_strength",
    "market_regime",
    "underlying_signal",
    "volatility_state",
    "confirmation_bias",
    "source",
]
NUMERIC_FIELDS = [
    "price",
    "vwap",
    "opening_range_high",
    "opening_range_low",
    "adx",
    "atr",
    "volume_relative",
    "premarket_high",
    "premarket_low",
    "logical_stop",
    "logical_target",
    "rsi",
    "ema_fast",
    "ema_slow",
    "trend_strength",
]
ALLOWED_DIRECTIONS = {"LONG", "SHORT", "NONE", "RANGE", "BULLISH", "BEARISH", "NEUTRAL"}
ALLOWED_SESSION_STATES = {
    "PREMARKET",
    "OPENING_RANGE",
    "REGULAR",
    "MIDDAY",
    "POWER_HOUR",
    "POSTMARKET",
    "CLOSED",
}
ALLOWED_RISK_STATUS = {"OK", "CAUTION", "BLOCKED", "UNKNOWN"}
ALLOWED_PORTFOLIO_STATUS = {"OK", "CAUTION", "MAX_RISK", "NO_CAPACITY", "UNKNOWN"}
PLACEHOLDER_RE = re.compile(r"^\{\{[^{}]+\}\}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and bool(PLACEHOLDER_RE.match(value.strip()))


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def numeric_like(value: Any) -> bool:
    if is_placeholder(value):
        return True
    try:
        if value is None or str(value).strip() == "":
            return False
        float(value)
        return True
    except Exception:
        return False


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    normalized = dict(payload)
    aliases = {
        "ticker": ["ticker", "symbol", "chart_ticker"],
        "timeframe": ["timeframe", "interval", "tf"],
        "strategy_context": ["strategy_context", "strategy", "setup"],
        "price": ["price", "close", "last"],
        "vwap": ["vwap", "vwap_value"],
        "breakout_direction": ["breakout_direction", "direction"],
        "volume_relative": ["volume_relative", "relative_volume", "rvol"],
        "logical_stop": ["logical_stop", "stop_logical", "stop"],
        "logical_target": ["logical_target", "target_logical", "target"],
        "session_state": ["session_state", "market_session"],
    }
    for canonical, keys in aliases.items():
        if has_value(normalized.get(canonical)):
            continue
        for key in keys:
            if has_value(payload.get(key)):
                normalized[canonical] = payload.get(key)
                break
    return normalized


def validate_payload(payload: dict[str, Any], *, allow_placeholders: bool = True) -> dict[str, Any]:
    normalized = normalize_payload(payload)
    strategy_context = safe_upper(normalized.get("strategy_context"))
    context_required_fields = CONTEXT_REQUIRED_FIELDS.get(strategy_context, [])
    required_fields = REQUIRED_FIELDS + [field for field in context_required_fields if field not in REQUIRED_FIELDS]
    missing_fields = [field for field in required_fields if not has_value(normalized.get(field))]
    invalid_numeric_fields = [
        field
        for field in NUMERIC_FIELDS
        if has_value(normalized.get(field)) and not numeric_like(normalized.get(field))
    ]
    placeholder_fields = [field for field in required_fields + OPTIONAL_FIELDS if is_placeholder(normalized.get(field))]
    if placeholder_fields and not allow_placeholders:
        invalid_placeholder_fields = placeholder_fields
    else:
        invalid_placeholder_fields = []

    warnings = []
    direction = safe_upper(normalized.get("breakout_direction"))
    if direction and not is_placeholder(normalized.get("breakout_direction")) and direction not in ALLOWED_DIRECTIONS:
        warnings.append("UNUSUAL_BREAKOUT_DIRECTION")
    session_state = safe_upper(normalized.get("session_state"))
    if session_state and not is_placeholder(normalized.get("session_state")) and session_state not in ALLOWED_SESSION_STATES:
        warnings.append("UNUSUAL_SESSION_STATE")
    risk_status = safe_upper(normalized.get("risk_daily_status"))
    if risk_status and not is_placeholder(normalized.get("risk_daily_status")) and risk_status not in ALLOWED_RISK_STATUS:
        warnings.append("UNUSUAL_RISK_DAILY_STATUS")
    portfolio_status = safe_upper(normalized.get("portfolio_status"))
    if portfolio_status and not is_placeholder(normalized.get("portfolio_status")) and portfolio_status not in ALLOWED_PORTFOLIO_STATUS:
        warnings.append("UNUSUAL_PORTFOLIO_STATUS")

    total_required = len(required_fields)
    completeness = round(((total_required - len(missing_fields)) / total_required) * 100, 2)
    valid = not missing_fields and not invalid_numeric_fields and not invalid_placeholder_fields
    return {
        "engine": "TRADINGVIEW_PAYLOAD_CONTRACT_VALIDATOR",
        "payload_contract_version": PAYLOAD_CONTRACT_VERSION,
        "generated_at": now_iso(),
        "valid": valid,
        "context_completeness_pct": completeness,
        "required_fields": required_fields,
        "base_required_fields": REQUIRED_FIELDS,
        "context_required_fields": context_required_fields,
        "optional_fields": OPTIONAL_FIELDS,
        "missing_fields": missing_fields,
        "invalid_numeric_fields": invalid_numeric_fields,
        "placeholder_fields": placeholder_fields,
        "invalid_placeholder_fields": invalid_placeholder_fields,
        "warnings": warnings,
        "normalized_payload": normalized,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def sample_payload() -> dict[str, Any]:
    return {
        "ticker": "MNQ1!",
        "timeframe": "5",
        "strategy_context": "INTRADAY_INDEX_FUTURES",
        "event": "ORB_BREAKOUT",
        "event_code": "MNQ_ORB_BREAKOUT_LONG_5M",
        "action": "ALERT_ONLY",
        "price": 23000.25,
        "session_state": "OPENING_RANGE",
        "vwap": 22980.0,
        "vwap_position": "ABOVE",
        "opening_range_high": 23010.0,
        "opening_range_low": 22920.0,
        "breakout_direction": "LONG",
        "adx": 24.5,
        "atr": 52.0,
        "volume_relative": 1.8,
        "premarket_high": 23040.0,
        "premarket_low": 22880.0,
        "major_event_window": "NONE",
        "risk_daily_status": "OK",
        "portfolio_status": "OK",
        "invalidation": "VWAP_LOST",
        "logical_stop": 22950.0,
        "logical_target": 23120.0,
        "source": "TRADINGVIEW",
    }


def tradingview_placeholder_template(strategy_context: str | None = None) -> dict[str, Any]:
    payload = sample_payload()
    if safe_upper(strategy_context) == OPTIONS_UNDERLYING_CONTEXT:
        payload.update(
            {
                "strategy_context": OPTIONS_UNDERLYING_CONTEXT,
                "event": "TECH_CONFIRM",
                "event_code": "QQQ_TECH_CONFIRM_LONG_15M",
                "ticker": "QQQ",
                "timeframe": "15",
                "session_state": "REGULAR",
                "breakout_direction": "LONG",
                "rsi_state": "BULLISH_CONFIRMATION",
                "rsi_divergence": "NONE",
                "trend_state": "BULLISH",
                "market_regime": "RISK_ON",
                "underlying_signal": "TECH_CONFIRM_LONG",
                "volatility_state": "NORMAL",
                "confirmation_bias": "LONG",
            }
        )
    payload.update(
        {
            "ticker": "{{ticker}}",
            "timeframe": "{{interval}}",
            "price": "{{close}}",
            "vwap": "{{plot(\"VWAP\")}}",
            "opening_range_high": "{{plot(\"ORH\")}}",
            "opening_range_low": "{{plot(\"ORL\")}}",
            "adx": "{{plot(\"ADX\")}}",
            "atr": "{{plot(\"ATR\")}}",
            "volume_relative": "{{plot(\"RVOL\")}}",
            "premarket_high": "{{plot(\"PMH\")}}",
            "premarket_low": "{{plot(\"PML\")}}",
            "logical_stop": "{{plot(\"STOP\")}}",
            "logical_target": "{{plot(\"TARGET\")}}",
        }
    )
    if safe_upper(strategy_context) == OPTIONS_UNDERLYING_CONTEXT:
        payload.update(
            {
                "rsi": "{{plot(\"RSI\")}}",
                "ema_fast": "{{plot(\"EMA_FAST\")}}",
                "ema_slow": "{{plot(\"EMA_SLOW\")}}",
                "trend_strength": "{{plot(\"TREND_STRENGTH\")}}",
            }
        )
    return payload


def dumps_template() -> str:
    return json.dumps(tradingview_placeholder_template(), indent=2, sort_keys=True)
