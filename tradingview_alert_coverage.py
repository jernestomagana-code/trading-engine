"""TradingView alert coverage matrix and setup message helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tradingview_payload_contract


COVERAGE_VERSION = "tradingview_alert_coverage_v1"
DEFAULT_COVERAGE_PATH = Path("config/tradingview_alert_coverage_v1.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_coverage(path: Path | str = DEFAULT_COVERAGE_PATH) -> dict[str, Any]:
    coverage_path = Path(path)
    return json.loads(coverage_path.read_text())


def alerts(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in coverage.get("alerts", []) if isinstance(item, dict)]


def production_active_alerts(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in coverage.get("production_active_alerts", [])
        if isinstance(item, dict)
    ]


def production_alert_expiry_status(coverage: dict[str, Any], *, as_of: str | None = None) -> dict[str, Any]:
    try:
        today = datetime.fromisoformat(as_of).date() if as_of else datetime.now(timezone.utc).date()
    except Exception:
        today = datetime.now(timezone.utc).date()
    rows = []
    for item in production_active_alerts(coverage):
        expires_on = item.get("expires_on")
        try:
            expiry = datetime.fromisoformat(str(expires_on)).date()
            days_remaining = (expiry - today).days
        except Exception:
            days_remaining = None
        state = (
            "EXPIRY_UNKNOWN" if days_remaining is None
            else "EXPIRED" if days_remaining < 0
            else "RENEW_NOW" if days_remaining <= 7
            else "RENEW_SOON" if days_remaining <= 14
            else "ACTIVE"
        )
        rows.append({
            "symbol": item.get("symbol"),
            "timeframe": item.get("timeframe"),
            "expires_on": expires_on,
            "renewal_review_on": item.get("renewal_review_on"),
            "days_remaining": days_remaining,
            "status": state,
        })
    ranked = {"EXPIRED": 4, "RENEW_NOW": 3, "RENEW_SOON": 2, "EXPIRY_UNKNOWN": 1, "ACTIVE": 0}
    overall = max((row["status"] for row in rows), key=lambda value: ranked[value], default="NO_ACTIVE_ALERTS")
    return {
        "status": overall,
        "as_of": today.isoformat(),
        "alerts": rows,
        "renewal_required": overall in {"EXPIRED", "RENEW_NOW", "RENEW_SOON"},
    }


def alert_by_code(coverage: dict[str, Any], event_code: str) -> dict[str, Any] | None:
    code = str(event_code or "").strip().upper()
    for item in alerts(coverage):
        if str(item.get("event_code") or "").strip().upper() == code:
            return item
    return None


def validate_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    items = alerts(coverage)
    event_codes = [str(item.get("event_code") or "").strip() for item in items]
    alert_names = [str(item.get("alert_name") or "").strip() for item in items]
    required_alerts = [item for item in items if item.get("required") is True]
    health_alerts = [item for item in items if item.get("alert_role") == "HEARTBEAT_SNAPSHOT"]

    duplicate_event_codes = sorted({code for code in event_codes if event_codes.count(code) > 1 and code})
    duplicate_alert_names = sorted({name for name in alert_names if alert_names.count(name) > 1 and name})
    missing_fields = []
    required_item_fields = [
        "alert_name",
        "event",
        "event_code",
        "symbol",
        "timeframe",
        "strategy_context",
        "condition_hint",
        "breakout_direction",
        "session_state",
        "invalidation",
        "alert_role",
        "freshness_minutes",
    ]
    for item in items:
        missing = [field for field in required_item_fields if not item.get(field)]
        if missing:
            missing_fields.append({"event_code": item.get("event_code"), "missing": missing})

    policy = coverage.get("global_policy") if isinstance(coverage.get("global_policy"), dict) else {}
    min_core = int(policy.get("minimum_core_alert_count") or 0)
    min_health = int(policy.get("minimum_health_alert_count") or 0)
    valid = (
        coverage.get("coverage_version") == COVERAGE_VERSION
        and not duplicate_event_codes
        and not duplicate_alert_names
        and not missing_fields
        and len(required_alerts) >= min_core
        and len(health_alerts) >= min_health
    )
    return {
        "engine": "TRADINGVIEW_ALERT_COVERAGE_VALIDATOR",
        "coverage_version": coverage.get("coverage_version"),
        "generated_at": now_iso(),
        "valid": valid,
        "production_active_alert_count": len(production_active_alerts(coverage)),
        "logical_event_count": len(items),
        "required_logical_event_count": len(required_alerts),
        "health_logical_event_count": len(health_alerts),
        "alert_count": len(items),
        "required_alert_count": len(required_alerts),
        "health_alert_count": len(health_alerts),
        "duplicate_event_codes": duplicate_event_codes,
        "duplicate_alert_names": duplicate_alert_names,
        "missing_fields": missing_fields,
        "required_plot_names": coverage.get("required_plot_names") or [],
        "production_alert_expiry": production_alert_expiry_status(coverage),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def payload_for_alert(alert: dict[str, Any]) -> dict[str, Any]:
    strategy_context = alert.get("strategy_context") or "INTRADAY_INDEX_FUTURES"
    payload = tradingview_payload_contract.tradingview_placeholder_template(strategy_context)
    payload.update(
        {
            "ticker": "{{ticker}}",
            "timeframe": "{{interval}}",
            "strategy_context": strategy_context,
            "event": alert.get("event"),
            "event_code": alert.get("event_code"),
            "action": "ALERT_ONLY",
            "session_state": alert.get("session_state"),
            "breakout_direction": alert.get("breakout_direction"),
            "vwap_position": alert.get("vwap_position") or "UNKNOWN",
            "invalidation": alert.get("invalidation"),
            "source": "TRADINGVIEW",
        }
    )
    for key in [
        "rsi_state",
        "rsi_divergence",
        "trend_state",
        "market_regime",
        "underlying_signal",
        "volatility_state",
        "confirmation_bias",
        "score",
        "score_long",
        "score_short",
        "macd_z",
        "stoch_k",
        "stoch_d",
        "mtf_votes",
        "mtf_long_votes",
        "mtf_short_votes",
        "atr_pct",
        "setup_quality",
        "counter_trend",
        "rebound",
    ]:
        if alert.get(key) is not None:
            payload[key] = alert.get(key)
    return payload


def setup_record(alert: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    payload = payload_for_alert(alert)
    validation = tradingview_payload_contract.validate_payload(payload)
    return {
        "alert_name": alert.get("alert_name"),
        "symbol": alert.get("symbol"),
        "timeframe": alert.get("timeframe"),
        "condition_hint": alert.get("condition_hint"),
        "event_code": alert.get("event_code"),
        "alert_role": alert.get("alert_role"),
        "required": alert.get("required") is True,
        "freshness_minutes": alert.get("freshness_minutes"),
        "webhook_url_template": coverage.get("webhook_url_template"),
        "endpoint": coverage.get("endpoint"),
        "message": payload,
        "message_json": json.dumps(payload, indent=2, sort_keys=True),
        "payload_valid": validation["valid"],
        "payload_warnings": validation["warnings"],
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def setup_records(coverage: dict[str, Any], *, required_only: bool = False) -> list[dict[str, Any]]:
    rows = []
    for item in alerts(coverage):
        if required_only and item.get("required") is not True:
            continue
        rows.append(setup_record(item, coverage))
    return rows
