"""Virtual-only portfolio rebalance and capital-allocation simulator."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import broker_control_tower as control_tower
import portfolio_factor_engine as factor_engine
import portfolio_stress_engine as stress_engine


REBALANCE_ENGINE_VERSION = "stock_ultimus_portfolio_rebalance_engine_v1"
DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": "stock_ultimus_portfolio_rebalance_policy_v1",
    "target_max_ticker_gross_share": 0.35,
    "minimum_excess_liquidity_ratio": 0.30,
    "maximum_option_dollar_delta_nav_ratio": 0.10,
    "maximum_single_simulation_turnover_nav_ratio": 0.25,
    "linear_margin_release_ratio": 0.50,
    "option_margin_release_multiple": 3.0,
    "default_custom_reduction_pct": 10,
    "maximum_custom_reduction_pct": 100,
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
            warnings.append(f"REBALANCE_POLICY_LOAD_FAILED:{type(exc).__name__}")
    policy["_policy_warnings"] = warnings
    return policy


def _nav(payload: dict[str, Any]) -> float:
    return _number((payload.get("consolidated_capacity") or {}).get("net_liquidation")) or 0.0


def _position_value(position: dict[str, Any]) -> float | None:
    value, _ = stress_engine._position_value(position)
    return value


def _ticker_gross(payload: dict[str, Any], *, linear_only: bool = False) -> dict[str, float]:
    values: dict[str, float] = {}
    for account in payload.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        for position in account.get("positions") or []:
            if not isinstance(position, dict):
                continue
            security_type = str(position.get("security_type") or "").upper()
            if linear_only and security_type in {"OPT", "FOP"}:
                continue
            value = _position_value(position)
            if value is None:
                continue
            ticker = str(position.get("ticker") or "UNKNOWN").upper()
            values[ticker] = values.get(ticker, 0.0) + abs(value)
    return values


def _reduce_capacity(account: dict[str, Any], reduction: float, policy: dict[str, Any], *, option: bool = False) -> None:
    capacity = account.get("capacity") if isinstance(account.get("capacity"), dict) else {}
    release_ratio = (_number(policy.get("option_margin_release_multiple")) or 3.0) if option else (_number(policy.get("linear_margin_release_ratio")) or 0.50)
    release = reduction * release_ratio
    for field in ("gross_position_value", "maintenance_margin_required", "initial_margin_required"):
        current = _number(capacity.get(field))
        if current is None:
            continue
        capacity[field] = round(max(0.0, current - (reduction if field == "gross_position_value" else release)), 4)
    cash = _number(capacity.get("total_cash_value"))
    if cash is not None:
        capacity["total_cash_value"] = round(cash + (0.0 if option else reduction), 4)
    for field in ("excess_liquidity", "available_funds", "available_capacity"):
        current = _number(capacity.get(field))
        if current is not None:
            capacity[field] = round(current + release, 4)


def _apply_ticker_reduction(
    payload: dict[str, Any], ticker: str, reduction_pct: float, policy: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    simulated = deepcopy(payload)
    ticker = str(ticker or "").upper().strip()
    fraction = max(0.0, min(float(reduction_pct) / 100.0, 1.0))
    actions = []
    turnover = 0.0
    for account in simulated.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        alias = str(account.get("account_alias") or "unknown")
        for position in account.get("positions") or []:
            if not isinstance(position, dict) or str(position.get("ticker") or "").upper() != ticker:
                continue
            if str(position.get("security_type") or "").upper() in {"OPT", "FOP"}:
                continue
            value = _position_value(position)
            if value is None or value <= 0:
                continue
            reduction = abs(value) * fraction
            quantity = _number(position.get("quantity"))
            previous_quantity = quantity
            if quantity is not None:
                position["quantity"] = round(quantity * (1.0 - fraction), 4)
            if position.get("market_value") is not None:
                position["market_value"] = round(value * (1.0 - fraction), 4)
            turnover += reduction
            _reduce_capacity(account, reduction, policy)
            actions.append({
                "simulation_action": "VIRTUAL_REDUCTION",
                "account_alias": alias,
                "ticker": ticker,
                "reduction_pct": round(fraction * 100, 2),
                "simulated_value_change": round(-reduction, 2),
                "quantity_before": previous_quantity,
                "quantity_after": position.get("quantity"),
                "virtual_only": True,
                "order_created": False,
            })
    return simulated, actions, round(turnover, 2)


def _concentration_request(payload: dict[str, Any], policy: dict[str, Any]) -> tuple[str, float] | None:
    values = _ticker_gross(payload, linear_only=True)
    gross = sum(values.values())
    if not values or gross <= 0:
        return None
    ticker, value = max(values.items(), key=lambda item: item[1])
    target = _number(policy.get("target_max_ticker_gross_share")) or 0.35
    if value / gross <= target:
        return None
    required = max(0.0, (value - target * gross) / max(0.0001, 1.0 - target))
    nav = _nav(payload)
    cap = nav * (_number(policy.get("maximum_single_simulation_turnover_nav_ratio")) or 0.25)
    reduction = min(required, cap if cap > 0 else required)
    return ticker, round(min(100.0, reduction / value * 100.0), 4)


def _apply_option_delta_relief(payload: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    simulated = deepcopy(payload)
    nav = _nav(payload)
    target = nav * (_number(policy.get("maximum_option_dollar_delta_nav_ratio")) or 0.10)
    rows = []
    total_delta = 0.0
    for account in simulated.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        for position in account.get("positions") or []:
            if not isinstance(position, dict) or str(position.get("security_type") or "").upper() not in {"OPT", "FOP"}:
                continue
            delta = _number(position.get("delta"))
            quantity = _number(position.get("quantity"))
            closes = position.get("historical_closes") if isinstance(position.get("historical_closes"), list) else []
            underlying = _number(closes[-1]) if closes else None
            multiplier = _number(position.get("multiplier")) or 100.0
            if delta is None or quantity is None or underlying is None:
                continue
            dollar_delta = delta * quantity * multiplier * underlying
            total_delta += dollar_delta
            rows.append((abs(dollar_delta), dollar_delta, account, position))
    if abs(total_delta) <= target:
        return simulated, [], 0.0
    actions = []
    turnover = 0.0
    for _, contribution, account, position in sorted(rows, reverse=True, key=lambda row: row[0]):
        if abs(total_delta) <= target:
            break
        if contribution == 0 or contribution * total_delta <= 0:
            continue
        value = abs(_position_value(position) or 0.0)
        quantity = _number(position.get("quantity")) or 0.0
        total_delta -= contribution
        position["quantity"] = 0.0
        if position.get("market_value") is not None:
            position["market_value"] = 0.0
        turnover += value
        _reduce_capacity(account, value, policy, option=True)
        actions.append({
            "simulation_action": "VIRTUAL_OPTION_CLOSE",
            "account_alias": account.get("account_alias") or "unknown",
            "ticker": str(position.get("ticker") or "UNKNOWN").upper(),
            "expiration": position.get("expiration") or "",
            "strike": position.get("strike"),
            "right": position.get("right") or "",
            "quantity_before": quantity,
            "quantity_after": 0.0,
            "simulated_dollar_delta_removed": round(contribution, 2),
            "virtual_only": True,
            "order_created": False,
        })
    return simulated, actions, round(turnover, 2)


def _apply_liquidity_relief(payload: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    simulated = deepcopy(payload)
    target = _number(policy.get("minimum_excess_liquidity_ratio")) or 0.30
    release_ratio = _number(policy.get("linear_margin_release_ratio")) or 0.50
    maximum_turnover_ratio = _number(policy.get("maximum_single_simulation_turnover_nav_ratio")) or 0.25
    actions = []
    turnover = 0.0
    for account in simulated.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        capacity = account.get("capacity") if isinstance(account.get("capacity"), dict) else {}
        nav = _number(capacity.get("net_liquidation"))
        excess = _number(capacity.get("excess_liquidity"))
        if nav is None or nav <= 0 or excess is None or excess / nav >= target:
            continue
        need = target * nav - excess
        requested_reduction = min(need / max(release_ratio, 0.01), nav * maximum_turnover_ratio)
        eligible = []
        for position in account.get("positions") or []:
            if not isinstance(position, dict) or str(position.get("security_type") or "").upper() in {"OPT", "FOP"}:
                continue
            value = _position_value(position)
            if value is not None and value > 0:
                eligible.append((value, position))
        if not eligible:
            continue
        value, position = max(eligible, key=lambda row: row[0])
        reduction = min(value, requested_reduction)
        fraction = reduction / value if value else 0.0
        quantity = _number(position.get("quantity"))
        previous_quantity = quantity
        if quantity is not None:
            position["quantity"] = round(quantity * (1.0 - fraction), 4)
        if position.get("market_value") is not None:
            position["market_value"] = round(value - reduction, 4)
        _reduce_capacity(account, reduction, policy)
        turnover += reduction
        actions.append({
            "simulation_action": "VIRTUAL_LIQUIDITY_BUFFER",
            "account_alias": account.get("account_alias") or "unknown",
            "ticker": str(position.get("ticker") or "UNKNOWN").upper(),
            "simulated_value_change": round(-reduction, 2),
            "quantity_before": previous_quantity,
            "quantity_after": position.get("quantity"),
            "target_excess_liquidity_ratio": target,
            "virtual_only": True,
            "order_created": False,
        })
    return simulated, actions, round(turnover, 2)


def _minimum_liquidity_ratio(payload: dict[str, Any]) -> float | None:
    ratios = []
    for account in payload.get("accounts") or []:
        capacity = account.get("capacity") if isinstance(account.get("capacity"), dict) else {}
        nav = _number(capacity.get("net_liquidation"))
        excess = _number(capacity.get("excess_liquidity"))
        if nav is not None and nav > 0 and excess is not None:
            ratios.append(excess / nav)
    return round(min(ratios), 6) if ratios else None


def _dominant_factor_share(factor_payload: dict[str, Any]) -> float | None:
    shares = []
    for group in factor_payload.get("factor_groups") or []:
        rows = group.get("factors") if isinstance(group, dict) and isinstance(group.get("factors"), list) else []
        if rows and isinstance(rows[0], dict):
            value = _number(rows[0].get("gross_share"))
            if value is not None:
                shares.append(value)
    return max(shares) if shares else None


def _metrics(payload: dict[str, Any], stress_policy: dict[str, Any], factor_policy: dict[str, Any]) -> dict[str, Any]:
    stress = stress_engine.evaluate(payload, stress_policy)
    factors = factor_engine.evaluate(payload, factor_policy)
    historical = factors.get("historical_risk") if isinstance(factors.get("historical_risk"), dict) else {}
    greeks = factors.get("option_greeks") if isinstance(factors.get("option_greeks"), dict) else {}
    concentrations = stress.get("concentrations") if isinstance(stress.get("concentrations"), list) else []
    top = concentrations[0] if concentrations and isinstance(concentrations[0], dict) else {}
    return {
        "worst_stress_loss_ratio": _number(stress.get("worst_loss_nav_ratio")),
        "annualized_volatility": _number(historical.get("annualized_volatility")),
        "estimated_tail_loss_dollars": _number(historical.get("estimated_tail_loss_dollars")),
        "maximum_drawdown": _number(historical.get("max_drawdown")),
        "dominant_factor_share": _dominant_factor_share(factors),
        "top_ticker": top.get("ticker") or "",
        "top_ticker_share": _number(top.get("gross_share")),
        "minimum_excess_liquidity_ratio": _minimum_liquidity_ratio(payload),
        "option_dollar_delta": _number(greeks.get("dollar_delta")),
        "factor_status": factors.get("status"),
        "stress_status": stress.get("status"),
    }


def _improvement(before: Any, after: Any, *, lower_is_better: bool = True) -> float | None:
    old, new = _number(before), _number(after)
    if old is None or new is None:
        return None
    return round((old - new) if lower_is_better else (new - old), 6)


def _candidate(
    candidate_id: str,
    name: str,
    description: str,
    simulated: dict[str, Any],
    actions: list[dict[str, Any]],
    turnover: float,
    baseline: dict[str, Any],
    stress_policy: dict[str, Any],
    factor_policy: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    metrics = _metrics(simulated, stress_policy, factor_policy)
    nav = _nav(simulated)
    improvements = {
        "stress_loss_ratio_reduction": _improvement(baseline.get("worst_stress_loss_ratio"), metrics.get("worst_stress_loss_ratio")),
        "volatility_reduction": _improvement(baseline.get("annualized_volatility"), metrics.get("annualized_volatility")),
        "tail_loss_reduction_dollars": _improvement(baseline.get("estimated_tail_loss_dollars"), metrics.get("estimated_tail_loss_dollars")),
        "dominant_factor_reduction": _improvement(baseline.get("dominant_factor_share"), metrics.get("dominant_factor_share")),
        "liquidity_ratio_improvement": _improvement(baseline.get("minimum_excess_liquidity_ratio"), metrics.get("minimum_excess_liquidity_ratio"), lower_is_better=False),
        "absolute_option_delta_reduction": _improvement(abs(baseline.get("option_dollar_delta") or 0), abs(metrics.get("option_dollar_delta") or 0)),
    }
    turnover_ratio = turnover / nav if nav > 0 else 0.0
    turnover_limit = _number(policy.get("maximum_single_simulation_turnover_nav_ratio")) or 0.25
    within_turnover_limit = turnover_ratio <= turnover_limit + 0.000001
    score = (
        (improvements["stress_loss_ratio_reduction"] or 0) * 100
        + (improvements["volatility_reduction"] or 0) * 50
        + (improvements["dominant_factor_reduction"] or 0) * 30
        + (improvements["liquidity_ratio_improvement"] or 0) * 20
        + ((improvements["tail_loss_reduction_dollars"] or 0) / nav * 100 if nav else 0)
        + ((improvements["absolute_option_delta_reduction"] or 0) / nav * 25 if nav else 0)
        - turnover_ratio * 5
        - (100.0 if not within_turnover_limit else 0.0)
    )
    return {
        "candidate_id": candidate_id,
        "name": name,
        "description": description,
        "model_score": round(score, 4),
        "turnover_dollars": round(turnover, 2),
        "turnover_nav_ratio": round(turnover_ratio, 6),
        "constraints": {
            "turnover_limit_nav_ratio": turnover_limit,
            "within_turnover_limit": within_turnover_limit,
            "all_satisfied": within_turnover_limit,
        },
        "metrics": metrics,
        "improvements": improvements,
        "virtual_actions": actions,
        "manual_decision_required": True,
        "execution_authorized": False,
        "order_created": False,
        "not_order_instruction": True,
    }


def evaluate(
    control_tower_payload: dict[str, Any],
    policy: dict[str, Any],
    stress_policy: dict[str, Any],
    factor_policy: dict[str, Any],
    *,
    custom_ticker: str = "",
    custom_reduction_pct: float | None = None,
    reference: datetime | None = None,
) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    warnings = list(policy.get("_policy_warnings") or [])
    tower_status = str(control_tower_payload.get("status") or "").upper()
    if tower_status != "READY":
        warnings.append("CONTROL_TOWER_NOT_READY")
    baseline = _metrics(control_tower_payload, stress_policy, factor_policy)
    candidates = []

    concentration = _concentration_request(control_tower_payload, policy)
    if concentration:
        ticker, reduction_pct = concentration
        simulated, actions, turnover = _apply_ticker_reduction(control_tower_payload, ticker, reduction_pct, policy)
        candidates.append(_candidate(
            "concentration_relief", "Reducir concentración", f"Simula una reducción gradual de {ticker} limitada por rotación máxima.",
            simulated, actions, turnover, baseline, stress_policy, factor_policy,
            policy,
        ))

    option_simulated, option_actions, option_turnover = _apply_option_delta_relief(control_tower_payload, policy)
    if option_actions:
        candidates.append(_candidate(
            "option_sensitivity_relief", "Reducir sensibilidad de opciones",
            "Simula retirar contratos completos hasta acercar dollar delta de opciones al límite configurado.",
            option_simulated, option_actions, option_turnover, baseline, stress_policy, factor_policy,
            policy,
        ))

    liquidity_simulated, liquidity_actions, liquidity_turnover = _apply_liquidity_relief(control_tower_payload, policy)
    if liquidity_actions:
        candidates.append(_candidate(
            "liquidity_buffer", "Mejorar colchón de liquidez",
            "Simula una reducción limitada en la mayor posición de cada cuenta por debajo del colchón objetivo.",
            liquidity_simulated, liquidity_actions, liquidity_turnover, baseline, stress_policy, factor_policy,
            policy,
        ))

    if concentration and option_actions:
        ticker, reduction_pct = concentration
        max_turnover = _nav(control_tower_payload) * (_number(policy.get("maximum_single_simulation_turnover_nav_ratio")) or 0.25)
        ticker_value = _ticker_gross(control_tower_payload, linear_only=True).get(ticker, 0.0)
        remaining_turnover = max(0.0, max_turnover - option_turnover)
        combined_reduction_pct = min(reduction_pct, (remaining_turnover / ticker_value * 100.0) if ticker_value else 0.0)
        combined, concentration_actions, concentration_turnover = _apply_ticker_reduction(control_tower_payload, ticker, combined_reduction_pct, policy)
        combined, combined_option_actions, option_turnover = _apply_option_delta_relief(combined, policy)
        candidates.append(_candidate(
            "balanced_relief", "Alivio combinado",
            "Combina reducción gradual de concentración y menor sensibilidad de opciones.",
            combined, concentration_actions + combined_option_actions, concentration_turnover + option_turnover,
            baseline, stress_policy, factor_policy,
            policy,
        ))

    custom_ticker = str(custom_ticker or "").upper().strip()
    if custom_ticker:
        maximum = _number(policy.get("maximum_custom_reduction_pct")) or 100.0
        requested = _number(custom_reduction_pct)
        requested = requested if requested is not None else (_number(policy.get("default_custom_reduction_pct")) or 10.0)
        requested = max(0.0, min(requested, maximum))
        simulated, actions, turnover = _apply_ticker_reduction(control_tower_payload, custom_ticker, requested, policy)
        if actions:
            candidates.append(_candidate(
                "custom_reduction", f"Simulación personalizada {custom_ticker}",
                f"Evalúa virtualmente una reducción de {requested:.1f}% en {custom_ticker}.",
                simulated, actions, turnover, baseline, stress_policy, factor_policy,
                policy,
            ))
        else:
            warnings.append("CUSTOM_TICKER_NOT_REDUCIBLE")

    candidates.sort(key=lambda row: row["model_score"], reverse=True)
    preferred = candidates[0]["candidate_id"] if candidates else ""
    status = "BLOCKED" if "CONTROL_TOWER_NOT_READY" in warnings or policy.get("_policy_warnings") else "READY" if candidates else "NO_CHANGE_NEEDED"
    return {
        "rebalance_engine_version": REBALANCE_ENGINE_VERSION,
        "policy_version": str(policy.get("policy_version") or "unknown"),
        "generated_at": reference.isoformat(),
        "source_control_tower_generated_at": control_tower_payload.get("generated_at"),
        "status": status,
        "baseline": baseline,
        "candidate_count": len(candidates),
        "preferred_simulation_id": preferred,
        "preferred_label": "MEJOR_EQUILIBRIO_MODELADO" if preferred else "SIN_CAMBIO_PROPUESTO",
        "candidates": candidates,
        "available_tickers": sorted(_ticker_gross(control_tower_payload, linear_only=True)),
        "warnings": sorted(set(warnings)),
        "methodology": "Virtual marked-to-market alternatives; ignores taxes, slippage and execution constraints unless explicitly modeled.",
        "manual_decision_required": True,
        "simulation_only": True,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_rebalance_authorized": False,
        "automatic_liquidation_authorized": False,
        "orders_created": 0,
        "not_order_instruction": True,
    }


def write_result(path: Path, payload: dict[str, Any]) -> None:
    control_tower.write_control_tower(path, payload)
