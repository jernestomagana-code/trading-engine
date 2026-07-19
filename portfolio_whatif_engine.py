"""Build and summarize safe IBKR what-if previews for virtual reductions."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import broker_control_tower as control_tower


WHATIF_ENGINE_VERSION = "stock_ultimus_portfolio_whatif_engine_v1"
DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": "stock_ultimus_portfolio_whatif_policy_v1",
    "maximum_preview_actions": 10,
    "whole_share_stock_previews": True,
    "allowed_simulation_actions": ["VIRTUAL_REDUCTION", "VIRTUAL_OPTION_CLOSE", "VIRTUAL_LIQUIDITY_BUFFER"],
    "require_open_orders_unchanged": True,
    "require_transmit_false": True,
    "require_what_if_true": True,
}


def _number(value: Any) -> float | None:
    return control_tower.safe_float(value)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_policy(path: Path | None = None) -> dict[str, Any]:
    policy = deepcopy(DEFAULT_POLICY)
    warnings = []
    if path:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("policy must be an object")
            policy = _merge(policy, raw)
        except Exception as exc:
            warnings.append(f"WHATIF_POLICY_LOAD_FAILED:{type(exc).__name__}")
    policy["_policy_warnings"] = warnings
    return policy


def select_candidate(rebalance_payload: dict[str, Any], candidate_id: str = "") -> dict[str, Any]:
    requested = str(candidate_id or rebalance_payload.get("preferred_simulation_id") or "").strip()
    for candidate in rebalance_payload.get("candidates") or []:
        if isinstance(candidate, dict) and str(candidate.get("candidate_id") or "") == requested:
            return candidate
    return {}


def build_preview_requests(
    rebalance_payload: dict[str, Any], policy: dict[str, Any], *, candidate_id: str = ""
) -> dict[str, Any]:
    warnings = list(policy.get("_policy_warnings") or [])
    candidate = select_candidate(rebalance_payload, candidate_id)
    if not candidate:
        warnings.append("CANDIDATE_NOT_FOUND")
    allowed = {str(value) for value in (policy.get("allowed_simulation_actions") or [])}
    maximum = max(1, int(policy.get("maximum_preview_actions") or 10))
    requests = []
    rejected = []
    for index, action in enumerate(candidate.get("virtual_actions") or []):
        if not isinstance(action, dict):
            continue
        reason = ""
        action_type = str(action.get("simulation_action") or "")
        before = _number(action.get("quantity_before"))
        after = _number(action.get("quantity_after"))
        if action_type not in allowed:
            reason = "ACTION_NOT_ALLOWED"
        elif action.get("virtual_only") is not True or action.get("order_created") is not False:
            reason = "ACTION_NOT_PROVEN_VIRTUAL"
        elif before is None or after is None or abs(after) > abs(before) or before * after < 0:
            reason = "POSITION_REDUCTION_NOT_PROVEN"
        elif abs(before - after) <= 0:
            reason = "ZERO_QUANTITY_CHANGE"
        elif len(requests) >= maximum:
            reason = "MAXIMUM_PREVIEW_ACTIONS_EXCEEDED"
        if reason:
            rejected.append({"index": index, "reason": reason, "simulation_action": action_type})
            continue
        security_type = "OPT" if action_type == "VIRTUAL_OPTION_CLOSE" else "STK"
        raw_quantity = abs(before - after)
        quantity = float(math.floor(raw_quantity)) if security_type == "STK" and policy.get("whole_share_stock_previews", True) else raw_quantity
        if quantity <= 0:
            rejected.append({"index": index, "reason": "QUANTITY_BELOW_PREVIEW_INCREMENT", "simulation_action": action_type})
            continue
        rounded = abs(quantity - raw_quantity) > 0.000001
        effective_after = before - quantity if before > 0 else before + quantity
        requests.append({
            "request_id": f"whatif_{index + 1}",
            "account_alias": control_tower.normalize_alias(action.get("account_alias")),
            "ticker": str(action.get("ticker") or "UNKNOWN").upper().strip(),
            "security_type": security_type,
            "expiration": str(action.get("expiration") or ""),
            "strike": _number(action.get("strike")),
            "right": str(action.get("right") or "").upper(),
            "action": "SELL" if before > 0 else "BUY",
            "quantity": round(quantity, 4),
            "requested_virtual_quantity_change": round(raw_quantity, 4),
            "quantity_rounded_to_whole_share": rounded,
            "position_quantity_before": before,
            "position_quantity_after": round(effective_after, 4),
            "order_type": "MKT",
            "what_if": True,
            "transmit": False,
            "reduce_only": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        })
    if rejected:
        warnings.append("PREVIEW_ACTIONS_REJECTED")
    status = "BLOCKED" if policy.get("_policy_warnings") or not candidate or not requests else "READY"
    return {
        "request_build_version": "stock_ultimus_whatif_request_build_v1",
        "status": status,
        "candidate_id": candidate.get("candidate_id") or "",
        "candidate_name": candidate.get("name") or "",
        "request_count": len(requests),
        "requests": requests,
        "rejected_count": len(rejected),
        "rejected": rejected,
        "warnings": sorted(set(warnings)),
        "execution_authorized": False,
        "orders_created": 0,
        "not_order_instruction": True,
    }


def order_state_payload(order_state: Any) -> dict[str, Any]:
    def margin(name: str) -> float | None:
        return _number(getattr(order_state, name, None))

    return {
        "init_margin_before": margin("initMarginBefore"),
        "init_margin_change": margin("initMarginChange"),
        "init_margin_after": margin("initMarginAfter"),
        "maintenance_margin_before": margin("maintMarginBefore"),
        "maintenance_margin_change": margin("maintMarginChange"),
        "maintenance_margin_after": margin("maintMarginAfter"),
        "equity_with_loan_before": margin("equityWithLoanBefore"),
        "equity_with_loan_change": margin("equityWithLoanChange"),
        "equity_with_loan_after": margin("equityWithLoanAfter"),
        "commission": margin("commission"),
        "minimum_commission": margin("minCommission"),
        "maximum_commission": margin("maxCommission"),
        "commission_currency": str(getattr(order_state, "commissionCurrency", "") or ""),
        "warning_text": str(getattr(order_state, "warningText", "") or "")[:500],
    }


def summarize(
    request_build: dict[str, Any],
    previews: list[dict[str, Any]],
    *,
    open_orders_before: int,
    open_orders_after: int,
    open_order_fingerprint_unchanged: bool,
    reference: datetime | None = None,
) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    ready = [item for item in previews if str(item.get("status") or "") == "READY"]
    failed = [item for item in previews if str(item.get("status") or "") != "READY"]
    commission_values = [_number(item.get("commission")) for item in ready]
    commission_values = [value for value in commission_values if value is not None]
    initial_changes = [_number(item.get("init_margin_change")) for item in ready]
    initial_changes = [value for value in initial_changes if value is not None]
    maintenance_changes = [_number(item.get("maintenance_margin_change")) for item in ready]
    maintenance_changes = [value for value in maintenance_changes if value is not None]
    if not open_order_fingerprint_unchanged:
        status = "SAFETY_VIOLATION"
    elif request_build.get("status") != "READY":
        status = "BLOCKED"
    elif failed:
        status = "PARTIAL"
    else:
        status = "READY"
    return {
        "whatif_engine_version": WHATIF_ENGINE_VERSION,
        "generated_at": reference.isoformat(),
        "status": status,
        "candidate_id": request_build.get("candidate_id") or "",
        "candidate_name": request_build.get("candidate_name") or "",
        "requested_preview_count": request_build.get("request_count") or 0,
        "ready_preview_count": len(ready),
        "failed_preview_count": len(failed),
        "previews": previews,
        "estimated_commission_total": round(sum(commission_values), 4) if commission_values else None,
        "independent_init_margin_change_sum": round(sum(initial_changes), 4) if initial_changes else None,
        "independent_maintenance_margin_change_sum": round(sum(maintenance_changes), 4) if maintenance_changes else None,
        "margin_changes_are_independent_not_portfolio_combined": True,
        "open_orders_before": int(open_orders_before),
        "open_orders_after": int(open_orders_after),
        "open_order_fingerprint_unchanged": bool(open_order_fingerprint_unchanged),
        "orders_created": 0 if open_order_fingerprint_unchanged else None,
        "warnings": request_build.get("warnings") or [],
        "manual_decision_required": True,
        "what_if_only": True,
        "transmit": False,
        "execution_authorized": False,
        "automatic_rebalance_authorized": False,
        "sensitive_identifiers_excluded": True,
        "real_account_ids_excluded": True,
        "not_order_instruction": True,
    }


def write_result(path: Path, payload: dict[str, Any]) -> None:
    control_tower.write_control_tower(path, payload)
