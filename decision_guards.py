"""Shared decision guard helpers for executable contracts and blockers."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any


EXECUTABLE_OPTION_CONTRACT_VERSION = "executable_option_contract_v1"
BLOCKER_PRIORITY_VERSION = "blocker_priority_v1"
WAIT_OPTIONS_BLOCKER = "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY"


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def safe_upper(value: Any, default: str = "UNKNOWN") -> str:
    try:
        if value is None:
            return default
        text = str(value).strip()
        return text.upper() if text else default
    except Exception:
        return default


def listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def spread_metrics(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    bid = safe_float(row.get("bid"), None)
    ask = safe_float(row.get("ask"), None)

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


def expiration_parseable(value: Any) -> bool:
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


def executable_option_gate(
    row: dict[str, Any],
    *,
    min_bid: float = 0.05,
    min_ask: float = 0.05,
    min_option_score: float = 70,
    max_abs_spread: float = 0.35,
    max_spread_pct: float = 18.0,
) -> dict[str, Any]:
    missing: list[str] = []

    bid = safe_float(row.get("bid"), None)
    ask = safe_float(row.get("ask"), None)
    price = safe_float(row.get("price"), None)
    score = safe_float(row.get("score"), 0)
    delta = safe_float(row.get("delta"), None)
    strike = safe_float(row.get("strike"), None)
    dte = safe_float(row.get("dte"), None)
    expiration = row.get("expiration")

    spread, mid, spread_pct = spread_metrics(row)

    if bid is None or bid < min_bid:
        missing.append("bid")
    if ask is None or ask < min_ask:
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
    if not expiration_parseable(expiration):
        missing.append("expiration")
    if delta is None:
        missing.append("delta")
    elif delta < -1 or delta > 1:
        missing.append("delta")
    if price is None and mid is None:
        missing.append("price_or_mid")
    if score < min_option_score:
        missing.append("option_score")

    spread_ok = False
    if spread is not None and spread_pct is not None:
        spread_ok = spread <= max_abs_spread or spread_pct <= max_spread_pct
        if not spread_ok:
            missing.append("spread_too_wide")

    executable = len(missing) == 0

    return {
        "contract_version": EXECUTABLE_OPTION_CONTRACT_VERSION,
        "executable": executable,
        "quality": "EXECUTABLE" if executable else "NOT_EXECUTABLE",
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
        "gamma": safe_float(row.get("gamma"), None),
        "theta": safe_float(row.get("theta"), None),
        "vega": safe_float(row.get("vega"), None),
        "iv": safe_float(row.get("iv") or row.get("implied_volatility"), None),
        "volume": safe_float(row.get("volume"), None),
        "open_interest": safe_float(row.get("open_interest") or row.get("oi"), None),
    }


def risk_manual_gate(row: dict[str, Any]) -> dict[str, Any]:
    risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
    blockers: list[Any] = []

    for key in [
        "blockers",
        "manual_review_blockers",
        "risk_blockers",
        "missing_confirmations",
    ]:
        blockers.extend(listify(row.get(key)))

    blockers.extend(listify(risk.get("blockers")))

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
        str(item)
        for item in blockers
        if "MANUAL" in safe_upper(item, "") or "REVIEW" in safe_upper(item, "")
    ]

    if manual_review_required and not manual_blockers:
        manual_blockers.append("MANUAL_REVIEW_REQUIRED")

    return {
        "risk_ok": risk_ok,
        "risk_blocker": risk_blocker,
        "manual_ok": not manual_blockers,
        "manual_blockers": manual_blockers,
        "blockers": [str(item) for item in blockers if item not in [None, ""]],
    }


def primary_blockers(final_state: str, blocker: Any, risk_manual: dict[str, Any], strategy_risk: dict[str, Any]) -> list[Any]:
    result = [blocker] if blocker else []
    if final_state == "RISK_BLOCKED" and strategy_risk.get("blockers") and risk_manual.get("risk_ok"):
        return list(strategy_risk.get("blockers") or [])
    if final_state == "MANUAL_REVIEW_BLOCKED" and risk_manual.get("manual_blockers"):
        return list(risk_manual.get("manual_blockers") or [])
    return result


def blocker_metadata() -> dict[str, Any]:
    return {
        "blocker_priority_version": BLOCKER_PRIORITY_VERSION,
        "executable_option_contract_version": EXECUTABLE_OPTION_CONTRACT_VERSION,
        "wait_options_blocker": WAIT_OPTIONS_BLOCKER,
        "entry_ready_requires": [
            "technical_confirmed",
            "executable_option_contract",
            "risk_rules_pass",
            "manual_review_clear",
            "market_options_window_reliable",
        ],
    }
