"""Shared alert lifecycle and backtesting eligibility policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


ALERT_LIFECYCLE_VERSION = "alert_lifecycle_policy_v1"

ACTIONABLE_STATES = {"ENTRY_READY", "MANUAL_REVIEW"}
WAIT_STATES = {"WAIT_OPTIONS_DATA", "WAIT_TECHNICAL", "WAIT_MARKET", "WAIT_ACCOUNT_CONTEXT"}
RISK_STATES = {"RISK_BLOCKED"}
NOISE_STATES = {"NO_DATA"}

CLOSED_OPERATOR_STATUSES = {
    "REJECTED",
    "EXPIRED",
    "CLOSED",
    "APPROVED_FOR_MANUAL_REVIEW",
    "APPROVED_FOR_MANUAL_TRADE",
    "IBKR_NOT_APPLIED",
    "MISSED",
}

PAPER_OPERATOR_STATUSES = {"PAPER_TRACKED"}
REAL_OPERATOR_STATUSES = {"IBKR_APPLIED"}

INTRADAY_FUTURES_TTL_MINUTES = 30
OPTIONS_ACTION_TTL_MINUTES = 390
WAIT_CONTEXT_TTL_MINUTES = 1440


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _number(value: Any) -> float | None:
    try:
        if value in [None, "", "None", "null", "NULL"]:
            return None
        return float(value)
    except Exception:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        try:
            parsed = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _first_datetime(alert: dict[str, Any]) -> datetime | None:
    for key in (
        "alert_created_at",
        "generated_at",
        "received_at",
        "timestamp",
        "updated_at",
        "created_at",
        "session_date",
    ):
        parsed = _parse_datetime(alert.get(key))
        if parsed:
            return parsed
    return None


def _selected_contract(alert: dict[str, Any]) -> dict[str, Any]:
    contract = alert.get("selected_contract")
    if isinstance(contract, dict):
        return contract
    evidence = alert.get("evidence") if isinstance(alert.get("evidence"), dict) else {}
    options = evidence.get("options") if isinstance(evidence.get("options"), dict) else {}
    contract = options.get("contract")
    return contract if isinstance(contract, dict) else {}


def _strategy_or_symbol_is_intraday_futures(alert: dict[str, Any]) -> bool:
    strategy = _upper(alert.get("strategy"), "")
    ticker = _upper(alert.get("ticker") or alert.get("symbol"), "")
    if "FUTURES" in strategy or "INTRADAY_INDEX" in strategy:
        return True
    return ticker in {"ES", "MES", "NQ", "MNQ", "YM", "MYM", "RTY", "M2K"}


def _state(alert: dict[str, Any]) -> str:
    return _upper(alert.get("final_state") or alert.get("state"), "NO_DATA")


def _operator_status(alert: dict[str, Any]) -> str:
    return _upper(alert.get("operator_status"), "NEW")


def alert_ttl_minutes(alert: dict[str, Any]) -> int:
    alert = alert if isinstance(alert, dict) else {}
    state = _state(alert)
    if _strategy_or_symbol_is_intraday_futures(alert):
        return INTRADAY_FUTURES_TTL_MINUTES
    if state in ACTIONABLE_STATES:
        return OPTIONS_ACTION_TTL_MINUTES
    if state in WAIT_STATES:
        return WAIT_CONTEXT_TTL_MINUTES
    return 0


def contract_completeness(alert: dict[str, Any]) -> dict[str, Any]:
    contract = _selected_contract(alert if isinstance(alert, dict) else {})
    required = ["strike", "expiration", "dte", "delta"]
    present = [field for field in required if contract.get(field) not in [None, "", "None"]]
    has_price = any(contract.get(field) not in [None, "", "None"] for field in ("bid", "ask", "mid"))
    missing = [field for field in required if field not in present]
    if not has_price:
        missing.append("bid_or_ask_or_mid")
    total = len(required) + 1
    score = (len(present) + (1 if has_price else 0)) / total
    return {
        "status": "COMPLETE" if score >= 1 else "PARTIAL" if score >= 0.75 else "INCOMPLETE",
        "score": round(score * 100, 2),
        "missing_fields": missing,
    }


def has_ibkr_fill_details(alert: dict[str, Any]) -> bool:
    alert = alert if isinstance(alert, dict) else {}
    fill_price = _number(
        alert.get("ibkr_fill_price")
        or alert.get("fill_price")
        or alert.get("execution_price")
        or alert.get("price")
    )
    fill_quantity = _number(
        alert.get("ibkr_fill_quantity")
        or alert.get("fill_quantity")
        or alert.get("quantity")
        or alert.get("contracts")
    )
    return fill_price is not None and fill_price > 0 and fill_quantity is not None and fill_quantity > 0


def alert_lifecycle_state(alert: dict[str, Any], *, now: datetime | str | None = None) -> dict[str, Any]:
    alert = alert if isinstance(alert, dict) else {}
    state = _state(alert)
    operator_status = _operator_status(alert)
    created_at = _first_datetime(alert)
    now_dt = _parse_datetime(now) if isinstance(now, str) else now
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    now_dt = now_dt.astimezone(timezone.utc)

    ttl = alert_ttl_minutes(alert)
    age_minutes = None
    expires_at = None
    if created_at is not None and ttl > 0:
        age_minutes = max(0.0, (now_dt - created_at).total_seconds() / 60.0)
        expires_at = created_at + timedelta(minutes=ttl)

    closed_by_operator = operator_status in CLOSED_OPERATOR_STATUSES
    expired_by_time = age_minutes is not None and ttl > 0 and age_minutes > ttl
    stale_by_time = age_minutes is not None and ttl > 0 and age_minutes > min(ttl * 0.75, 240)
    if closed_by_operator:
        lifecycle_state = "CLOSED"
    elif expired_by_time or ttl == 0:
        lifecycle_state = "EXPIRED"
    elif stale_by_time:
        lifecycle_state = "STALE"
    else:
        lifecycle_state = "LIVE"

    completeness = contract_completeness(alert)
    risk_blocked = state in RISK_STATES or _upper(alert.get("risk_profile", {}).get("status") if isinstance(alert.get("risk_profile"), dict) else "") == "BLOCKED"
    rejected = operator_status in {"REJECTED", "IBKR_NOT_APPLIED", "MISSED"}
    actionable_state = state in ACTIONABLE_STATES or alert.get("manual_review_ready") is True
    enough_contract = completeness["score"] >= 80
    valid_paper_signal = (
        actionable_state
        and not risk_blocked
        and not rejected
        and lifecycle_state in {"LIVE", "STALE"}
        and enough_contract
    )
    real_applied = operator_status in REAL_OPERATOR_STATUSES and has_ibkr_fill_details(alert)

    if real_applied:
        bucket = "IBKR_REAL"
    elif operator_status in PAPER_OPERATOR_STATUSES and valid_paper_signal:
        bucket = "PAPER_ONLY"
    elif rejected:
        bucket = "REJECTED"
    elif risk_blocked:
        bucket = "RISK_BLOCKED"
    elif state in WAIT_STATES:
        bucket = "NEAR_VALID"
    elif valid_paper_signal:
        bucket = "VALID_SIGNAL"
    else:
        bucket = "NOISE"

    return {
        "alert_lifecycle_version": ALERT_LIFECYCLE_VERSION,
        "lifecycle_state": lifecycle_state,
        "state": state,
        "operator_status": operator_status,
        "ttl_minutes": ttl,
        "age_minutes": round(age_minutes, 2) if age_minutes is not None else None,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "contract_completeness": completeness,
        "paper_tracking_allowed": bool(valid_paper_signal),
        "performance_eligible": bool(valid_paper_signal),
        "ibkr_real_performance_allowed": bool(real_applied),
        "requires_ibkr_fill_for_real_performance": True,
        "backtesting_bucket": bucket,
        "learning_bucket": "COMPLETE_OUTCOME_CANDIDATE" if bucket in {"VALID_SIGNAL", "PAPER_ONLY", "IBKR_REAL"} else "DIAGNOSTIC_ONLY",
        "reason": _reason_for(bucket, lifecycle_state, completeness),
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _reason_for(bucket: str, lifecycle_state: str, completeness: dict[str, Any]) -> str:
    if lifecycle_state == "EXPIRED":
        return "La alerta ya no esta vigente para decision/backtesting de entrada."
    if bucket == "IBKR_REAL":
        return "Cuenta como performance real porque fue marcada como aplicada en IBKR con fill."
    if bucket in {"VALID_SIGNAL", "PAPER_ONLY"}:
        return "Cumple condiciones minimas para paper/backtesting; no autoriza ejecucion."
    if bucket == "NEAR_VALID":
        return "Cerca de ser valida, pero falta una condicion; sirve como diagnostico, no performance."
    if bucket == "RISK_BLOCKED":
        return "Bloqueada por riesgo/reglas; no cuenta como senal valida."
    if bucket == "REJECTED":
        return "Descartada por operador; se conserva para auditoria, no como senal valida."
    missing = ", ".join(completeness.get("missing_fields") or [])
    return f"No cumple contrato/evidencia minima para backtesting valido{': ' + missing if missing else ''}."
