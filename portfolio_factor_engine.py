"""Advanced read-only portfolio factor, history, correlation and Greeks analysis."""

from __future__ import annotations

import json
import math
import statistics
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import broker_control_tower as control_tower
import portfolio_stress_engine as stress_engine


FACTOR_ENGINE_VERSION = "stock_ultimus_portfolio_factor_engine_v1"
DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": "stock_ultimus_portfolio_factor_policy_v1",
    "minimum_history_bars": 30,
    "minimum_history_coverage_ratio": 0.80,
    "minimum_greeks_coverage_ratio": 0.80,
    "high_correlation_threshold": 0.75,
    "dominant_factor_threshold": 0.50,
    "annualized_volatility_watch": 0.25,
    "annualized_volatility_high": 0.40,
    "ticker_factors": {},
    "default_factors": {},
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
            warnings.append(f"FACTOR_POLICY_LOAD_FAILED:{type(exc).__name__}")
    policy["_policy_warnings"] = warnings
    return policy


def _returns(closes: list[Any]) -> list[float]:
    clean = [value for value in (_number(raw) for raw in closes) if value is not None and value > 0]
    return [round(clean[index] / clean[index - 1] - 1.0, 8) for index in range(1, len(clean))]


def _correlation(left: list[float], right: list[float]) -> float | None:
    size = min(len(left), len(right))
    if size < 20:
        return None
    x, y = left[-size:], right[-size:]
    mean_x, mean_y = statistics.mean(x), statistics.mean(y)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - mean_x) ** 2 for a in x) * sum((b - mean_y) ** 2 for b in y))
    return round(numerator / denominator, 6) if denominator else None


def _max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    value = peak = 1.0
    worst = 0.0
    for daily_return in returns:
        value *= 1.0 + daily_return
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return round(worst, 6)


def _factor_labels(position: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    ticker = str(position.get("ticker") or "UNKNOWN").upper()
    ticker_map = policy.get("ticker_factors") if isinstance(policy.get("ticker_factors"), dict) else {}
    if isinstance(ticker_map.get(ticker), dict):
        return {str(key): str(value) for key, value in ticker_map[ticker].items()}
    defaults = policy.get("default_factors") if isinstance(policy.get("default_factors"), dict) else {}
    security_type = str(position.get("security_type") or "UNKNOWN").upper()
    base = defaults.get(security_type) if isinstance(defaults.get(security_type), dict) else {}
    return {str(key): str(value) for key, value in base.items()}


def _exposure(position: dict[str, Any]) -> tuple[float | None, str]:
    value, basis = stress_engine._position_value(position)
    if value is None:
        return None, "UNAVAILABLE"
    security_type = str(position.get("security_type") or "").upper()
    if security_type not in {"OPT", "FOP"}:
        return value, basis
    delta = _number(position.get("delta"))
    closes = position.get("historical_closes") if isinstance(position.get("historical_closes"), list) else []
    underlying = _number(closes[-1]) if closes else None
    quantity = _number(position.get("quantity"))
    multiplier = _number(position.get("multiplier")) or 100.0
    if delta is not None and underlying is not None and quantity is not None:
        return round(delta * underlying * quantity * multiplier, 4), "DELTA_EQUIVALENT"
    return value, f"PREMIUM_PROXY:{basis}"


def evaluate(control_tower_payload: dict[str, Any], policy: dict[str, Any], *, reference: datetime | None = None) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    warnings = list(policy.get("_policy_warnings") or [])
    if str(control_tower_payload.get("status") or "").upper() != "READY":
        warnings.append("CONTROL_TOWER_NOT_READY")
    positions = []
    option_count = options_with_greeks = 0
    gross_exposure = history_covered_exposure = 0.0
    factor_buckets: dict[str, dict[str, float]] = {}
    ticker_buckets: dict[str, dict[str, Any]] = {}
    greek_totals = {"delta_contracts": 0.0, "dollar_delta": 0.0, "gamma_pnl_1pct": 0.0, "theta_daily": 0.0, "vega_per_vol_point": 0.0}

    for account in control_tower_payload.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        alias = str(account.get("account_alias") or "unknown")
        for raw_position in account.get("positions") or []:
            if not isinstance(raw_position, dict):
                continue
            exposure, basis = _exposure(raw_position)
            if exposure is None:
                continue
            absolute = abs(exposure)
            gross_exposure += absolute
            closes = raw_position.get("historical_closes") if isinstance(raw_position.get("historical_closes"), list) else []
            returns = _returns(closes)
            if len(closes) >= int(policy.get("minimum_history_bars") or 30):
                history_covered_exposure += absolute
            ticker = str(raw_position.get("ticker") or "UNKNOWN").upper()
            bucket = ticker_buckets.setdefault(ticker, {"ticker": ticker, "signed_exposure": 0.0, "gross_exposure": 0.0, "returns": returns})
            bucket["signed_exposure"] += exposure
            bucket["gross_exposure"] += absolute
            if len(returns) > len(bucket.get("returns") or []):
                bucket["returns"] = returns
            for group, label in _factor_labels(raw_position, policy).items():
                factor_buckets.setdefault(group, {})[label] = factor_buckets.setdefault(group, {}).get(label, 0.0) + exposure

            security_type = str(raw_position.get("security_type") or "").upper()
            if security_type in {"OPT", "FOP"}:
                option_count += 1
                delta = _number(raw_position.get("delta"))
                gamma = _number(raw_position.get("gamma"))
                theta = _number(raw_position.get("theta"))
                vega = _number(raw_position.get("vega"))
                complete = all(value is not None for value in (delta, gamma, theta, vega))
                options_with_greeks += int(complete)
                quantity = _number(raw_position.get("quantity")) or 0.0
                multiplier = _number(raw_position.get("multiplier")) or 100.0
                underlying = _number(closes[-1]) if closes else None
                if delta is not None:
                    greek_totals["delta_contracts"] += delta * quantity * multiplier
                    if underlying is not None:
                        greek_totals["dollar_delta"] += delta * quantity * multiplier * underlying
                if gamma is not None and underlying is not None:
                    greek_totals["gamma_pnl_1pct"] += 0.5 * gamma * quantity * multiplier * (underlying * 0.01) ** 2
                if theta is not None:
                    greek_totals["theta_daily"] += theta * quantity * multiplier
                if vega is not None:
                    greek_totals["vega_per_vol_point"] += vega * quantity * multiplier
            positions.append({
                "account_alias": alias,
                "ticker": ticker,
                "security_type": security_type,
                "signed_exposure": round(exposure, 2),
                "exposure_basis": basis,
                "history_bar_count": len(closes),
            })

    history_coverage = round(history_covered_exposure / gross_exposure, 6) if gross_exposure else 1.0
    greeks_coverage = round(options_with_greeks / option_count, 6) if option_count else 1.0
    if history_coverage < (_number(policy.get("minimum_history_coverage_ratio")) or 0.80):
        warnings.append("LOW_HISTORY_COVERAGE")
    if greeks_coverage < (_number(policy.get("minimum_greeks_coverage_ratio")) or 0.80):
        warnings.append("LOW_OPTION_GREEKS_COVERAGE")

    ticker_rows = list(ticker_buckets.values())
    usable = [row for row in ticker_rows if len(row.get("returns") or []) >= 20]
    minimum_size = min([len(row["returns"]) for row in usable], default=0)
    portfolio_returns = []
    if minimum_size and gross_exposure:
        for index in range(-minimum_size, 0):
            portfolio_returns.append(sum((row["signed_exposure"] / gross_exposure) * row["returns"][index] for row in usable))
    annualized_volatility = statistics.pstdev(portfolio_returns) * math.sqrt(252) if len(portfolio_returns) >= 2 else None
    tail_size = max(1, int(len(portfolio_returns) * 0.05)) if portfolio_returns else 0
    expected_shortfall = statistics.mean(sorted(portfolio_returns)[:tail_size]) if tail_size else None
    historical = {
        "observation_count": len(portfolio_returns),
        "annualized_volatility": round(annualized_volatility, 6) if annualized_volatility is not None else None,
        "worst_daily_return": round(min(portfolio_returns), 6) if portfolio_returns else None,
        "expected_shortfall_95": round(expected_shortfall, 6) if expected_shortfall is not None else None,
        "max_drawdown": _max_drawdown(portfolio_returns),
        "estimated_tail_loss_dollars": round(abs(expected_shortfall) * gross_exposure, 2) if expected_shortfall is not None else None,
    }

    correlations = []
    threshold = _number(policy.get("high_correlation_threshold")) or 0.75
    for left_index, left in enumerate(usable):
        for right in usable[left_index + 1:]:
            value = _correlation(left["returns"], right["returns"])
            if value is None:
                continue
            correlations.append({
                "left": left["ticker"], "right": right["ticker"], "correlation": value,
                "high_correlation": value >= threshold,
            })
    correlations.sort(key=lambda row: abs(row["correlation"]), reverse=True)
    if any(row["high_correlation"] for row in correlations):
        warnings.append("HIGH_CORRELATION_CLUSTER")

    factor_groups = []
    dominant_threshold = _number(policy.get("dominant_factor_threshold")) or 0.50
    for group, labels in sorted(factor_buckets.items()):
        group_gross = sum(abs(value) for value in labels.values())
        rows = [
            {"label": label, "signed_exposure": round(value, 2), "gross_share": round(abs(value) / group_gross, 6) if group_gross else 0.0}
            for label, value in sorted(labels.items(), key=lambda item: abs(item[1]), reverse=True)
        ]
        factor_groups.append({"group": group, "factors": rows, "dominant": bool(rows and rows[0]["gross_share"] >= dominant_threshold)})
    if any(group["dominant"] for group in factor_groups):
        warnings.append("DOMINANT_FACTOR_EXPOSURE")

    if annualized_volatility is not None:
        if annualized_volatility >= (_number(policy.get("annualized_volatility_high")) or 0.40):
            warnings.append("HISTORICAL_VOLATILITY_HIGH")
        elif annualized_volatility >= (_number(policy.get("annualized_volatility_watch")) or 0.25):
            warnings.append("HISTORICAL_VOLATILITY_WATCH")
    status = "BLOCKED" if "CONTROL_TOWER_NOT_READY" in warnings or policy.get("_policy_warnings") else "PARTIAL" if any(item.startswith("LOW_") for item in warnings) else "READY"
    return {
        "factor_engine_version": FACTOR_ENGINE_VERSION,
        "policy_version": str(policy.get("policy_version") or "unknown"),
        "generated_at": reference.isoformat(),
        "source_control_tower_generated_at": control_tower_payload.get("generated_at"),
        "status": status,
        "gross_factor_exposure": round(gross_exposure, 2),
        "history_coverage_ratio": history_coverage,
        "greeks_coverage_ratio": greeks_coverage,
        "option_position_count": option_count,
        "factor_groups": factor_groups,
        "historical_risk": historical,
        "correlations": correlations,
        "high_correlation_pair_count": sum(1 for row in correlations if row["high_correlation"]),
        "option_greeks": {key: round(value, 4) for key, value in greek_totals.items()},
        "positions": positions,
        "warnings": sorted(set(warnings)),
        "methodology": "Historical close-to-close sensitivities and position-level factor/Greek aggregation; diagnostic, not a forecast.",
        "manual_review_required": bool(warnings),
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    }


def write_result(path: Path, payload: dict[str, Any]) -> None:
    control_tower.write_control_tower(path, payload)
