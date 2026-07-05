"""Strategy-level outcome and performance summaries for Stock Ultimus."""

from __future__ import annotations

import math
from typing import Any


STRATEGY_PERFORMANCE_VERSION = "strategy_performance_v1"
PARAMETER_REVIEW_REPORT_VERSION = "parameter_review_evidence_report_v1"
OUTCOME_COMPLETENESS_VERSION = "outcome_completeness_v1"
PARAMETER_CHANGE_GUARD_VERSION = "parameter_change_guard_v1"
CLOSED_OUTCOMES = {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"}
REQUIRED_OUTCOME_FIELDS = [
    "pnl_r",
    "mfe_r",
    "mae_r",
    "market_regime",
    "candidate_source",
    "confirmation_source",
]
REQUIRED_OUTCOME_CONTRACT_FIELDS = ["delta", "dte", "spread_pct", "iv"]


def safe_upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _sum(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values), 4)


def _evidence_level(closed_count: int) -> str:
    if closed_count <= 0:
        return "NO_OUTCOMES"
    if closed_count < 10:
        return "INSUFFICIENT_SAMPLE"
    if closed_count < 30:
        return "EMERGING_SAMPLE"
    return "REVIEWABLE_SAMPLE"


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _contract_value(contract: dict[str, Any], field: str) -> Any:
    if field == "iv":
        return contract.get("iv") if _has_value(contract.get("iv")) else contract.get("implied_volatility")
    return contract.get(field)


def outcome_completeness(outcome: dict[str, Any]) -> dict[str, Any]:
    """Score whether a closed paper outcome is complete enough for parameter review."""

    item = outcome if isinstance(outcome, dict) else {}
    status = safe_upper(item.get("outcome"))
    is_closed = status in CLOSED_OUTCOMES
    contract = item.get("selected_contract") if isinstance(item.get("selected_contract"), dict) else {}
    missing_fields = [field for field in REQUIRED_OUTCOME_FIELDS if not _has_value(item.get(field))]
    missing_contract_fields = [
        field
        for field in REQUIRED_OUTCOME_CONTRACT_FIELDS
        if not _has_value(_contract_value(contract, field))
    ]
    total_required = len(REQUIRED_OUTCOME_FIELDS) + len(REQUIRED_OUTCOME_CONTRACT_FIELDS)
    missing_total = len(missing_fields) + len(missing_contract_fields)
    score = round(((total_required - missing_total) / total_required) * 100, 2) if total_required else 100.0
    complete = is_closed and missing_total == 0
    return {
        "outcome_completeness_version": OUTCOME_COMPLETENESS_VERSION,
        "outcome_id": item.get("outcome_id") or item.get("id"),
        "strategy": safe_upper(item.get("strategy")),
        "ticker": safe_upper(item.get("ticker")),
        "outcome": status,
        "is_closed": is_closed,
        "complete": complete,
        "completeness_score": score,
        "missing_fields": missing_fields,
        "missing_contract_fields": missing_contract_fields,
        "status": "COMPLETE" if complete else ("OPEN_OUTCOME_NOT_COUNTED" if not is_closed else "INCOMPLETE"),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _completion_bucket() -> dict[str, Any]:
    return {
        "total_outcomes": 0,
        "closed_outcomes": 0,
        "complete_closed_outcomes": 0,
        "incomplete_closed_outcomes": 0,
        "complete_closed_pct": None,
    }


def _update_completion_bucket(bucket: dict[str, Any], diagnostic: dict[str, Any]) -> None:
    bucket["total_outcomes"] += 1
    if diagnostic.get("is_closed"):
        bucket["closed_outcomes"] += 1
        if diagnostic.get("complete"):
            bucket["complete_closed_outcomes"] += 1
        else:
            bucket["incomplete_closed_outcomes"] += 1
    closed = bucket["closed_outcomes"]
    bucket["complete_closed_pct"] = (
        round((bucket["complete_closed_outcomes"] / closed) * 100, 2) if closed else None
    )


def outcome_completeness_report(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics = [outcome_completeness(item) for item in outcomes or [] if isinstance(item, dict)]
    summary = _completion_bucket()
    missing_field_counts: dict[str, int] = {}
    missing_contract_field_counts: dict[str, int] = {}
    by_strategy: dict[str, dict[str, Any]] = {}
    by_strategy_regime: dict[str, dict[str, Any]] = {}
    incomplete_samples = []

    for raw, diagnostic in zip([item for item in outcomes or [] if isinstance(item, dict)], diagnostics):
        _update_completion_bucket(summary, diagnostic)
        strategy = diagnostic.get("strategy") or "UNKNOWN"
        regime = safe_upper(raw.get("market_regime"))
        by_strategy.setdefault(strategy, _completion_bucket())
        by_strategy_regime.setdefault(f"{strategy}::{regime}", _completion_bucket())
        _update_completion_bucket(by_strategy[strategy], diagnostic)
        _update_completion_bucket(by_strategy_regime[f"{strategy}::{regime}"], diagnostic)

        if diagnostic.get("is_closed") and not diagnostic.get("complete"):
            for field in diagnostic.get("missing_fields") or []:
                missing_field_counts[field] = missing_field_counts.get(field, 0) + 1
            for field in diagnostic.get("missing_contract_fields") or []:
                missing_contract_field_counts[field] = missing_contract_field_counts.get(field, 0) + 1
            if len(incomplete_samples) < 10:
                incomplete_samples.append(diagnostic)

    return {
        "outcome_completeness_version": OUTCOME_COMPLETENESS_VERSION,
        "required_outcome_fields": REQUIRED_OUTCOME_FIELDS,
        "required_contract_fields": REQUIRED_OUTCOME_CONTRACT_FIELDS,
        **summary,
        "missing_field_counts": dict(sorted(missing_field_counts.items())),
        "missing_contract_field_counts": dict(sorted(missing_contract_field_counts.items())),
        "by_strategy": [
            {"strategy": key, **value}
            for key, value in sorted(by_strategy.items())
        ],
        "by_strategy_regime": [
            {"strategy_regime": key, **value}
            for key, value in sorted(by_strategy_regime.items())
        ],
        "incomplete_closed_samples": incomplete_samples,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _registry_strategy_names(registry: dict[str, Any] | None) -> list[str]:
    if not isinstance(registry, dict):
        return []
    strategies = registry.get("strategies") or {}
    if isinstance(strategies, dict):
        return sorted(safe_upper(key) for key in strategies.keys())
    if isinstance(strategies, list):
        names = []
        for item in strategies:
            if isinstance(item, dict):
                names.append(safe_upper(item.get("strategy") or item.get("id")))
        return sorted(name for name in names if name != "UNKNOWN")
    return []


def _registry_meta(strategy: str, registry: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(registry, dict):
        return {}
    strategies = registry.get("strategies") or {}
    entry = None
    if isinstance(strategies, dict):
        entry = strategies.get(strategy)
    elif isinstance(strategies, list):
        for item in strategies:
            if isinstance(item, dict) and safe_upper(item.get("strategy") or item.get("id")) == strategy:
                entry = item
                break
    if not isinstance(entry, dict):
        return {}
    return {
        "registry_state": entry.get("state") or entry.get("status"),
        "strategy_version": entry.get("strategy_version"),
        "ruleset_version": entry.get("ruleset_version"),
        "research_stage": entry.get("research_stage"),
        "entry_ready_cap": entry.get("entry_ready_cap"),
    }


def _performance_group(label: str, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [o for o in outcomes or [] if safe_upper(o.get("outcome")) in CLOSED_OUTCOMES]
    wins = [o for o in closed if safe_upper(o.get("outcome")) == "WIN"]
    losses = [o for o in closed if safe_upper(o.get("outcome")) == "LOSS"]
    pnl_r = [safe_float(o.get("pnl_r")) for o in closed]
    mfe_r = [safe_float(o.get("mfe_r")) for o in closed]
    mae_r = [safe_float(o.get("mae_r")) for o in closed]
    deltas = []
    dtes = []
    spreads = []
    ivs = []
    for outcome in closed:
        contract = outcome.get("selected_contract") if isinstance(outcome.get("selected_contract"), dict) else {}
        deltas.append(safe_float(contract.get("delta")))
        dtes.append(safe_float(contract.get("dte")))
        spreads.append(safe_float(contract.get("spread_pct")))
        ivs.append(safe_float(contract.get("iv") or contract.get("implied_volatility")))
    pnl_r = [value for value in pnl_r if value is not None]
    mfe_r = [value for value in mfe_r if value is not None]
    mae_r = [value for value in mae_r if value is not None]
    deltas = [value for value in deltas if value is not None]
    dtes = [value for value in dtes if value is not None]
    spreads = [value for value in spreads if value is not None]
    ivs = [value for value in ivs if value is not None]
    denominator = len(wins) + len(losses)
    closed_count = len(closed)
    return {
        "group": label,
        "total_outcomes": len(outcomes or []),
        "closed_outcomes": closed_count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / denominator) * 100, 2) if denominator else None,
        "net_pnl_r": _sum(pnl_r),
        "expectancy_r": _avg(pnl_r),
        "avg_mfe_r": _avg(mfe_r),
        "avg_mae_r": _avg(mae_r),
        "avg_abs_delta": _avg([abs(value) for value in deltas]),
        "avg_dte": _avg(dtes),
        "avg_spread_pct": _avg(spreads),
        "avg_iv": _avg(ivs),
        "evidence_level": _evidence_level(closed_count),
        "sample_size_warning": closed_count < 30,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _grouped_performance(outcomes: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes or []:
        key = safe_upper(key_fn(outcome))
        grouped.setdefault(key, []).append(outcome)
    return [
        _performance_group(key, grouped[key])
        for key in sorted(grouped.keys())
        if key != "UNKNOWN" or grouped[key]
    ]


def strategy_performance_report(
    decisions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    *,
    registry: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build an auditable per-strategy performance report.

    This report is evidence for parameter review. It never authorizes execution.
    """

    strategy_names = set(_registry_strategy_names(registry))
    for item in decisions or []:
        strategy_names.add(safe_upper(item.get("strategy")))
    for item in outcomes or []:
        strategy_names.add(safe_upper(item.get("strategy")))
    strategy_names.discard("UNKNOWN")

    rows = []
    for strategy in sorted(strategy_names):
        strategy_decisions = [d for d in decisions or [] if safe_upper(d.get("strategy")) == strategy]
        strategy_outcomes = [o for o in outcomes or [] if safe_upper(o.get("strategy")) == strategy]
        strategy_completeness = outcome_completeness_report(strategy_outcomes)
        closed = [o for o in strategy_outcomes if safe_upper(o.get("outcome")) in CLOSED_OUTCOMES]
        wins = [o for o in closed if safe_upper(o.get("outcome")) == "WIN"]
        losses = [o for o in closed if safe_upper(o.get("outcome")) == "LOSS"]
        breakeven = [o for o in closed if safe_upper(o.get("outcome")) == "BREAKEVEN"]
        expired = [o for o in closed if safe_upper(o.get("outcome")) == "EXPIRED"]
        cancelled = [o for o in closed if safe_upper(o.get("outcome")) == "CANCELLED"]

        pnl = [safe_float(o.get("pnl")) for o in closed]
        pnl_r = [safe_float(o.get("pnl_r")) for o in closed]
        mfe_r = [safe_float(o.get("mfe_r")) for o in closed]
        mae_r = [safe_float(o.get("mae_r")) for o in closed]
        pnl = [value for value in pnl if value is not None]
        pnl_r = [value for value in pnl_r if value is not None]
        mfe_r = [value for value in mfe_r if value is not None]
        mae_r = [value for value in mae_r if value is not None]

        ticker_counts: dict[str, int] = {}
        for outcome in strategy_outcomes:
            ticker = safe_upper(outcome.get("ticker"))
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

        decision_states: dict[str, int] = {}
        for decision in strategy_decisions:
            state = safe_upper(decision.get("final_state"))
            decision_states[state] = decision_states.get(state, 0) + 1

        denominator = len(wins) + len(losses)
        win_rate = round((len(wins) / denominator) * 100, 2) if denominator else None
        closed_count = len(closed)
        outcome_timestamps = [str(o.get("recorded_at")) for o in strategy_outcomes if o.get("recorded_at")]
        by_market_regime = _grouped_performance(strategy_outcomes, lambda o: o.get("market_regime"))
        by_parameter_review_status = _grouped_performance(
            strategy_outcomes,
            lambda o: o.get("parameter_review_status"),
        )
        by_source = _grouped_performance(
            strategy_outcomes,
            lambda o: o.get("signal_source") or o.get("confirmation_source") or o.get("candidate_source"),
        )
        row = {
            "strategy": strategy,
            **_registry_meta(strategy, registry),
            "decision_count": len(strategy_decisions),
            "entry_ready_decisions": sum(1 for d in strategy_decisions if safe_upper(d.get("final_state")) == "ENTRY_READY"),
            "open_decisions": sum(1 for d in strategy_decisions if safe_upper(d.get("outcome_status"), "OPEN") == "OPEN"),
            "decision_states": decision_states,
            "total_outcomes": len(strategy_outcomes),
            "closed_outcomes": closed_count,
            "complete_closed_outcomes": strategy_completeness.get("complete_closed_outcomes"),
            "incomplete_closed_outcomes": strategy_completeness.get("incomplete_closed_outcomes"),
            "complete_closed_pct": strategy_completeness.get("complete_closed_pct"),
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(breakeven),
            "expired": len(expired),
            "cancelled": len(cancelled),
            "win_rate": win_rate,
            "net_pnl": _sum(pnl),
            "avg_pnl": _avg(pnl),
            "net_pnl_r": _sum(pnl_r),
            "avg_pnl_r": _avg(pnl_r),
            "avg_mfe_r": _avg(mfe_r),
            "avg_mae_r": _avg(mae_r),
            "expectancy_r": _avg(pnl_r),
            "tickers": dict(sorted(ticker_counts.items())),
            "by_market_regime": by_market_regime,
            "by_parameter_review_status": by_parameter_review_status,
            "by_source": by_source,
            "latest_outcome_at": max(outcome_timestamps) if outcome_timestamps else None,
            "evidence_level": _evidence_level(closed_count),
            "parameter_review_ready": int(strategy_completeness.get("complete_closed_outcomes") or 0) >= 30,
            "sample_size_warning": int(strategy_completeness.get("complete_closed_outcomes") or 0) < 30,
            "manual_review_required": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        rows.append(row)

    closed_total = sum(item["closed_outcomes"] for item in rows)
    strategy_regime_performance = _grouped_performance(
        outcomes or [],
        lambda o: f"{safe_upper(o.get('strategy'))}::{safe_upper(o.get('market_regime'))}",
    )
    parameter_review_performance = _grouped_performance(
        outcomes or [],
        lambda o: safe_upper(o.get("parameter_review_status")),
    )
    source_performance = _grouped_performance(
        outcomes or [],
        lambda o: safe_upper(o.get("signal_source") or o.get("confirmation_source") or o.get("candidate_source")),
    )
    completeness = outcome_completeness_report(outcomes or [])
    report = {
        "engine": "V32_STRATEGY_PERFORMANCE",
        "strategy_performance_version": STRATEGY_PERFORMANCE_VERSION,
        "generated_at": generated_at,
        "summary": {
            "strategy_count": len(rows),
            "decision_count": len(decisions or []),
            "outcome_count": len(outcomes or []),
            "closed_outcomes": closed_total,
            "complete_closed_outcomes": completeness.get("complete_closed_outcomes"),
            "incomplete_closed_outcomes": completeness.get("incomplete_closed_outcomes"),
            "complete_closed_pct": completeness.get("complete_closed_pct"),
            "parameter_review_ready": [item["strategy"] for item in rows if item["parameter_review_ready"]],
            "insufficient_sample": [item["strategy"] for item in rows if item["sample_size_warning"]],
            "strategy_regime_group_count": len(strategy_regime_performance),
            "parameter_review_group_count": len(parameter_review_performance),
            "source_group_count": len(source_performance),
        },
        "strategies": rows,
        "strategy_regime_performance": strategy_regime_performance,
        "parameter_review_performance": parameter_review_performance,
        "source_performance": source_performance,
        "outcome_completeness": completeness,
        "review_policy": {
            "minimum_closed_outcomes_for_parameter_review": 30,
            "minimum_complete_closed_outcomes_for_parameter_review": 30,
            "purpose": "Evidence for strategy and parameter review only.",
            "production_change_requires_versioned_rule": True,
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    report["parameter_change_guard"] = parameter_change_guard(report, outcome_completeness=completeness)
    return report


def _completeness_by_strategy(outcome_completeness_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = outcome_completeness_payload if isinstance(outcome_completeness_payload, dict) else {}
    return {
        str(item.get("strategy")): item
        for item in payload.get("by_strategy") or []
        if isinstance(item, dict) and item.get("strategy")
    }


def _completeness_by_strategy_regime(outcome_completeness_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = outcome_completeness_payload if isinstance(outcome_completeness_payload, dict) else {}
    return {
        str(item.get("strategy_regime")): item
        for item in payload.get("by_strategy_regime") or []
        if isinstance(item, dict) and item.get("strategy_regime")
    }


def _parameter_guard_item(
    *,
    strategy: str,
    closed: int,
    complete_closed: int,
    incomplete_closed: int,
    expectancy: float | None,
    mfe: float | None,
    mae: float | None,
    minimum_complete_closed_outcomes: int,
    strategy_regime: str | None = None,
    extra_reasons: list[str] | None = None,
) -> dict[str, Any]:
    reasons = list(extra_reasons or [])
    if closed < minimum_complete_closed_outcomes:
        reasons.append("INSUFFICIENT_CLOSED_OUTCOMES")
    if complete_closed < minimum_complete_closed_outcomes:
        reasons.append("INSUFFICIENT_COMPLETE_CLOSED_OUTCOMES")
    if incomplete_closed:
        reasons.append("INCOMPLETE_CLOSED_OUTCOME_EVIDENCE")
    if expectancy is None:
        reasons.append("EXPECTANCY_MISSING")
    if mfe is None:
        reasons.append("MFE_MISSING")
    if mae is None:
        reasons.append("MAE_MISSING")
    if expectancy is not None and expectancy < 0:
        reasons.append("NEGATIVE_EXPECTANCY_REVIEW_REQUIRED")
    if mae is not None and mae <= -2.0:
        reasons.append("MAE_RISK_REVIEW_REQUIRED")

    blocking_reasons = {
        "INSUFFICIENT_CLOSED_OUTCOMES",
        "INSUFFICIENT_COMPLETE_CLOSED_OUTCOMES",
        "INCOMPLETE_CLOSED_OUTCOME_EVIDENCE",
        "EXPECTANCY_MISSING",
        "MFE_MISSING",
        "MAE_MISSING",
        "NO_REVIEWABLE_STRATEGY_REGIME_SAMPLE",
    }
    blocked_by_evidence = any(reason in blocking_reasons for reason in reasons)
    item = {
        "strategy": strategy,
        "closed_outcomes": closed,
        "complete_closed_outcomes": complete_closed,
        "incomplete_closed_outcomes": incomplete_closed,
        "minimum_complete_closed_outcomes": minimum_complete_closed_outcomes,
        "expectancy_r": expectancy,
        "avg_mfe_r": mfe,
        "avg_mae_r": mae,
        "guard_status": "BLOCK_PARAMETER_CHANGE" if blocked_by_evidence else "ALLOW_HUMAN_PARAMETER_REVIEW",
        "recommended_action": "ACCUMULATE_COMPLETE_OUTCOMES" if blocked_by_evidence else "HUMAN_PARAMETER_REVIEW_ONLY",
        "reasons": reasons,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if strategy_regime:
        item["strategy_regime"] = strategy_regime
    return item


def parameter_change_guard(
    performance_report: dict[str, Any],
    *,
    outcome_completeness: dict[str, Any] | None = None,
    minimum_complete_closed_outcomes: int = 30,
) -> dict[str, Any]:
    """Gate all parameter-change consideration on complete, closed paper outcomes."""

    try:
        minimum_complete_closed_outcomes = max(1, int(minimum_complete_closed_outcomes))
    except Exception:
        minimum_complete_closed_outcomes = 30

    completeness_payload = outcome_completeness or performance_report.get("outcome_completeness") or {}
    completeness_lookup = _completeness_by_strategy(completeness_payload)
    regime_completeness_lookup = _completeness_by_strategy_regime(completeness_payload)
    allowed_regimes = []
    blocked_regimes = []
    reviewable_regimes_by_strategy: dict[str, list[str]] = {}

    for row in performance_report.get("strategy_regime_performance") or []:
        if not isinstance(row, dict):
            continue
        strategy_regime = str(row.get("group") or "UNKNOWN::UNKNOWN")
        strategy = strategy_regime.split("::", 1)[0]
        completeness_row = regime_completeness_lookup.get(strategy_regime, {})
        regime_item = _parameter_guard_item(
            strategy=strategy,
            strategy_regime=strategy_regime,
            closed=safe_int(row.get("closed_outcomes")),
            complete_closed=safe_int(completeness_row.get("complete_closed_outcomes")),
            incomplete_closed=safe_int(completeness_row.get("incomplete_closed_outcomes")),
            expectancy=safe_float(row.get("expectancy_r")),
            mfe=safe_float(row.get("avg_mfe_r")),
            mae=safe_float(row.get("avg_mae_r")),
            minimum_complete_closed_outcomes=minimum_complete_closed_outcomes,
        )
        if regime_item["guard_status"] == "ALLOW_HUMAN_PARAMETER_REVIEW":
            allowed_regimes.append(regime_item)
            reviewable_regimes_by_strategy.setdefault(strategy, []).append(strategy_regime)
        else:
            blocked_regimes.append(regime_item)

    allowed = []
    blocked = []

    for row in performance_report.get("strategies") or []:
        if not isinstance(row, dict):
            continue
        strategy = str(row.get("strategy") or "UNKNOWN")
        completeness_row = completeness_lookup.get(strategy, {})
        closed = int(row.get("closed_outcomes") or 0)
        complete_closed = safe_int(
            completeness_row.get("complete_closed_outcomes")
            if completeness_row
            else row.get("complete_closed_outcomes")
        )
        incomplete_closed = safe_int(
            completeness_row.get("incomplete_closed_outcomes")
            if completeness_row
            else row.get("incomplete_closed_outcomes")
        )
        expectancy = safe_float(row.get("expectancy_r"))
        mfe = safe_float(row.get("avg_mfe_r"))
        mae = safe_float(row.get("avg_mae_r"))
        reviewable_regimes = sorted(reviewable_regimes_by_strategy.get(strategy, []))
        extra_reasons = [] if reviewable_regimes else ["NO_REVIEWABLE_STRATEGY_REGIME_SAMPLE"]
        item = _parameter_guard_item(
            strategy=strategy,
            closed=closed,
            complete_closed=complete_closed,
            incomplete_closed=incomplete_closed,
            expectancy=expectancy,
            mfe=mfe,
            mae=mae,
            minimum_complete_closed_outcomes=minimum_complete_closed_outcomes,
            extra_reasons=extra_reasons,
        )
        item["reviewable_strategy_regimes"] = reviewable_regimes
        if item["guard_status"] == "BLOCK_PARAMETER_CHANGE":
            blocked.append(item)
        else:
            allowed.append(item)

    return {
        "engine": "PARAMETER_CHANGE_GUARD",
        "parameter_change_guard_version": PARAMETER_CHANGE_GUARD_VERSION,
        "minimum_complete_closed_outcomes": minimum_complete_closed_outcomes,
        "allowed_count": len(allowed),
        "blocked_count": len(blocked),
        "allowed": allowed,
        "blocked": blocked,
        "allowed_strategy_regimes": allowed_regimes,
        "blocked_strategy_regimes": blocked_regimes,
        "policy": {
            "does_not_change_thresholds": True,
            "blocks_incomplete_outcomes": True,
            "requires_30_complete_closed_outcomes_per_strategy": minimum_complete_closed_outcomes == 30,
            "requires_30_complete_closed_outcomes_per_strategy_regime": minimum_complete_closed_outcomes == 30,
            "allows_only_human_review": True,
            "requires_versioned_rule_change": True,
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def parameter_review_evidence_report(
    performance_report: dict[str, Any],
    *,
    generated_at: str | None = None,
    minimum_closed_outcomes: int = 30,
) -> dict[str, Any]:
    """Build a no-order weekly-style parameter review report.

    The report recommends whether a strategy is ready for human parameter
    review. It never mutates thresholds and never promotes a strategy.
    """

    try:
        minimum_closed_outcomes = max(1, int(minimum_closed_outcomes))
    except Exception:
        minimum_closed_outcomes = 30

    candidates = []
    blocked = []
    guard = parameter_change_guard(
        performance_report,
        minimum_complete_closed_outcomes=minimum_closed_outcomes,
    )
    guard_lookup = {
        item.get("strategy"): item
        for item in (guard.get("allowed") or []) + (guard.get("blocked") or [])
        if isinstance(item, dict)
    }
    for row in performance_report.get("strategies") or []:
        if not isinstance(row, dict):
            continue
        closed = int(row.get("closed_outcomes") or 0)
        strategy = row.get("strategy")
        guard_item = guard_lookup.get(strategy) or {}
        complete_closed = safe_int(guard_item.get("complete_closed_outcomes"))
        incomplete_closed = safe_int(guard_item.get("incomplete_closed_outcomes"))
        expectancy = safe_float(row.get("expectancy_r"))
        mae = safe_float(row.get("avg_mae_r"))
        ready = guard_item.get("guard_status") == "ALLOW_HUMAN_PARAMETER_REVIEW"
        item = {
            "strategy": strategy,
            "closed_outcomes": closed,
            "complete_closed_outcomes": complete_closed,
            "incomplete_closed_outcomes": incomplete_closed,
            "minimum_closed_outcomes": minimum_closed_outcomes,
            "minimum_complete_closed_outcomes": minimum_closed_outcomes,
            "expectancy_r": expectancy,
            "avg_mae_r": mae,
            "evidence_level": row.get("evidence_level"),
            "parameter_review_ready": ready,
            "parameter_change_guard_status": guard_item.get("guard_status"),
            "reviewable_strategy_regimes": guard_item.get("reviewable_strategy_regimes") or [],
            "recommended_action": "HUMAN_PARAMETER_REVIEW_ONLY" if ready else "ACCUMULATE_COMPLETE_OUTCOMES",
            "reasons": list(guard_item.get("reasons") or []),
            "manual_review_required": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        }

        if ready:
            candidates.append(item)
        else:
            blocked.append(item)

    return {
        "engine": "PARAMETER_REVIEW_EVIDENCE_REPORT",
        "parameter_review_report_version": PARAMETER_REVIEW_REPORT_VERSION,
        "generated_at": generated_at,
        "minimum_closed_outcomes": minimum_closed_outcomes,
        "candidate_count": len(candidates),
        "blocked_count": len(blocked),
        "candidates": candidates,
        "blocked": blocked,
        "parameter_change_guard": guard,
        "policy": {
            "does_not_change_thresholds": True,
            "requires_complete_outcomes": True,
            "requires_versioned_rule_change": True,
            "requires_manual_review": True,
            "requires_security_review": True,
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
