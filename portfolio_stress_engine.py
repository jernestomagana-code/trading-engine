"""Read-only, explainable multi-account portfolio stress scenarios."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import broker_control_tower as control_tower


STRESS_ENGINE_VERSION = "stock_ultimus_portfolio_stress_engine_v1"
DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": "stock_ultimus_portfolio_stress_policy_v1",
    "max_data_age_minutes": 15,
    "minimum_valuation_coverage_ratio": 0.80,
    "loss_thresholds": {"watch_nav_ratio": 0.05, "high_nav_ratio": 0.10, "critical_nav_ratio": 0.20},
    "scenarios": [],
}


def _number(value: Any) -> float | None:
    return control_tower.safe_float(value)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    output = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(output.get(key), dict):
            output[key] = _deep_merge(output[key], value)
        else:
            output[key] = deepcopy(value)
    return output


def load_policy(path: Path | None = None) -> dict[str, Any]:
    policy = deepcopy(DEFAULT_POLICY)
    warnings = []
    if path:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("policy must be an object")
            policy = _deep_merge(policy, raw)
        except Exception as exc:
            warnings.append(f"STRESS_POLICY_LOAD_FAILED:{type(exc).__name__}")
    policy["_policy_warnings"] = warnings
    return policy


def _position_value(position: dict[str, Any]) -> tuple[float | None, str]:
    security_type = str(position.get("security_type") or "").upper()
    market_value = _number(position.get("market_value"))
    if market_value is not None and (security_type not in {"FUT", "CONTFUT"} or market_value != 0):
        return market_value, "MARKET_VALUE"
    quantity = _number(position.get("quantity"))
    average_cost = _number(position.get("average_cost"))
    if quantity is None:
        return None, "UNAVAILABLE"
    multiplier = _number(position.get("multiplier"))
    if security_type in {"FUT", "CONTFUT"}:
        reference = _number(position.get("market_price") or position.get("price"))
        closes = position.get("historical_closes") if isinstance(position.get("historical_closes"), list) else []
        if reference is None and closes:
            reference = _number(closes[-1])
        if reference is not None:
            return round(quantity * reference * (multiplier or 1.0), 4), "FUTURES_REFERENCE_NOTIONAL"
        # IBKR averageCost for futures is commonly already expressed as the
        # contract value. Do not multiply it a second time.
        if average_cost is not None:
            return round(quantity * average_cost, 4), "FUTURES_AVERAGE_COST_NOTIONAL"
        return None, "UNAVAILABLE"
    if average_cost is None:
        return None, "UNAVAILABLE"
    # IBKR averageCost for options may already include the multiplier. Avoid
    # silently multiplying it twice; mark the fallback as an estimate instead.
    factor = 1.0 if security_type in {"OPT", "FOP"} else (multiplier or 1.0)
    return round(quantity * average_cost * factor, 4), "AVERAGE_COST_ESTIMATE"


def _scenario_return(position: dict[str, Any], scenario: dict[str, Any]) -> float:
    security_type = str(position.get("security_type") or "").upper()
    quantity = _number(position.get("quantity")) or 0.0
    if security_type not in {"OPT", "FOP"}:
        base = _number(scenario.get("linear_return")) or 0.0
        return base if quantity >= 0 else -base
    right = str(position.get("right") or "").upper()
    side = "long" if quantity >= 0 else "short"
    key = f"{side}_{'call' if right == 'C' else 'put'}_return" if right in {"C", "P"} else "other_option_return"
    return _number(scenario.get(key)) or 0.0


def _severity(loss_ratio: float, thresholds: dict[str, Any]) -> str:
    if loss_ratio >= (_number(thresholds.get("critical_nav_ratio")) or 0.20):
        return "CRITICAL"
    if loss_ratio >= (_number(thresholds.get("high_nav_ratio")) or 0.10):
        return "HIGH"
    if loss_ratio >= (_number(thresholds.get("watch_nav_ratio")) or 0.05):
        return "WATCH"
    return "INFO"


def evaluate(control_tower_payload: dict[str, Any], policy: dict[str, Any], *, reference: datetime | None = None) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    accounts = [row for row in (control_tower_payload.get("accounts") or []) if isinstance(row, dict)]
    consolidated_nav = _number((control_tower_payload.get("consolidated_capacity") or {}).get("net_liquidation")) or 0.0
    warnings = list(policy.get("_policy_warnings") or [])
    if str(control_tower_payload.get("status") or "").upper() != "READY":
        warnings.append("CONTROL_TOWER_NOT_READY")

    prepared_accounts = []
    ticker_values: dict[str, float] = {}
    exact_value = estimated_value = unavailable_positions = 0.0
    for account in accounts:
        alias = str(account.get("account_alias") or "unknown")
        capacity = account.get("capacity") if isinstance(account.get("capacity"), dict) else {}
        positions = []
        for position in account.get("positions") or []:
            if not isinstance(position, dict):
                continue
            value, basis = _position_value(position)
            if value is None:
                unavailable_positions += 1
                continue
            absolute_value = abs(value)
            exact_value += absolute_value if basis == "MARKET_VALUE" else 0.0
            estimated_value += absolute_value if basis != "MARKET_VALUE" else 0.0
            ticker = str(position.get("ticker") or "UNKNOWN").upper()
            ticker_values[ticker] = ticker_values.get(ticker, 0.0) + absolute_value
            positions.append({**position, "stress_value": value, "valuation_basis": basis})
        prepared_accounts.append({
            "account_alias": alias,
            "nav": _number(capacity.get("net_liquidation")) or 0.0,
            "excess_liquidity": _number(capacity.get("excess_liquidity")),
            "positions": positions,
        })

    valued_total = exact_value + estimated_value
    # Estimated references still cover the position for scenario purposes;
    # disclose their basis separately instead of calling the portfolio absent.
    coverage_ratio = 1.0 if valued_total > 0 and not unavailable_positions else (
        round(exact_value / valued_total, 6) if valued_total > 0 else (1.0 if not unavailable_positions else 0.0)
    )
    if coverage_ratio < (_number(policy.get("minimum_valuation_coverage_ratio")) or 0.80):
        warnings.append("LOW_MARKET_VALUE_COVERAGE")
    if unavailable_positions:
        warnings.append("POSITIONS_WITHOUT_VALUATION")
    if estimated_value:
        warnings.append("ESTIMATED_POSITION_VALUATION")

    scenario_results = []
    thresholds = policy.get("loss_thresholds") if isinstance(policy.get("loss_thresholds"), dict) else {}
    for scenario in policy.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        account_results = []
        consolidated_pnl = 0.0
        for account in prepared_accounts:
            pnl = round(sum(abs(item["stress_value"]) * _scenario_return(item, scenario) for item in account["positions"]), 2)
            consolidated_pnl += pnl
            nav = account["nav"]
            loss_ratio = max(0.0, -pnl / nav) if nav > 0 else 0.0
            excess = account["excess_liquidity"]
            account_results.append({
                "account_alias": account["account_alias"],
                "estimated_pnl": pnl,
                "loss_nav_ratio": round(loss_ratio, 6),
                "projected_nav": round(nav + pnl, 2),
                "projected_excess_liquidity": round(excess + pnl, 2) if excess is not None else None,
                "severity": _severity(loss_ratio, thresholds),
            })
        consolidated_pnl = round(consolidated_pnl, 2)
        loss_ratio = max(0.0, -consolidated_pnl / consolidated_nav) if consolidated_nav > 0 else 0.0
        account_results.sort(key=lambda row: row["loss_nav_ratio"], reverse=True)
        worst_account_loss = max((row["loss_nav_ratio"] for row in account_results), default=0.0)
        consolidated_severity = _severity(loss_ratio, thresholds)
        account_severity = _severity(worst_account_loss, thresholds)
        severity_order = {"INFO": 0, "WATCH": 1, "HIGH": 2, "CRITICAL": 3}
        scenario_results.append({
            "scenario_id": str(scenario.get("id") or "scenario"),
            "name": str(scenario.get("name") or scenario.get("id") or "Escenario"),
            "description": str(scenario.get("description") or ""),
            "estimated_pnl": consolidated_pnl,
            "loss_nav_ratio": round(loss_ratio, 6),
            "projected_nav": round(consolidated_nav + consolidated_pnl, 2),
            "severity": account_severity if severity_order[account_severity] > severity_order[consolidated_severity] else consolidated_severity,
            "consolidated_severity": consolidated_severity,
            "worst_account_loss_nav_ratio": round(worst_account_loss, 6),
            "worst_account_severity": account_severity,
            "most_exposed_account": account_results[0]["account_alias"] if account_results else "",
            "accounts": account_results,
        })
    scenario_results.sort(
        key=lambda row: max(row.get("loss_nav_ratio") or 0.0, row.get("worst_account_loss_nav_ratio") or 0.0),
        reverse=True,
    )
    gross = sum(ticker_values.values())
    concentrations = [
        {"ticker": ticker, "gross_value": round(value, 2), "gross_share": round(value / gross, 6) if gross else 0.0}
        for ticker, value in sorted(ticker_values.items(), key=lambda item: item[1], reverse=True)[:10]
    ]
    status = "BLOCKED" if "CONTROL_TOWER_NOT_READY" in warnings or policy.get("_policy_warnings") else "PARTIAL" if warnings else "READY"
    worst = scenario_results[0] if scenario_results else {}
    return {
        "stress_engine_version": STRESS_ENGINE_VERSION,
        "policy_version": str(policy.get("policy_version") or "unknown"),
        "generated_at": reference.isoformat(),
        "source_control_tower_generated_at": control_tower_payload.get("generated_at"),
        "status": status,
        "scenario_count": len(scenario_results),
        "consolidated_nav": consolidated_nav,
        "valuation_coverage_ratio": coverage_ratio,
        "market_value_covered": round(exact_value, 2),
        "estimated_value": round(estimated_value, 2),
        "unavailable_position_count": int(unavailable_positions),
        "worst_scenario_id": worst.get("scenario_id") or "",
        "worst_estimated_pnl": worst.get("estimated_pnl"),
        "worst_loss_nav_ratio": max(worst.get("loss_nav_ratio") or 0.0, worst.get("worst_account_loss_nav_ratio") or 0.0),
        "worst_account_loss_nav_ratio": worst.get("worst_account_loss_nav_ratio"),
        "scenarios": scenario_results,
        "concentrations": concentrations,
        "warnings": sorted(set(warnings)),
        "methodology": "Deterministic position-level shocks; estimates are decision support, not forecasts or VaR.",
        "manual_review_required": bool(warnings) or any(row.get("severity") in {"HIGH", "CRITICAL"} for row in scenario_results),
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }


def write_result(path: Path, payload: dict[str, Any]) -> None:
    control_tower.write_control_tower(path, payload)
