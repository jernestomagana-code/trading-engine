"""Strategy-level outcome and performance summaries for Stock Ultimus."""

from __future__ import annotations

import math
from typing import Any


STRATEGY_PERFORMANCE_VERSION = "strategy_performance_v1"
PARAMETER_REVIEW_REPORT_VERSION = "parameter_review_evidence_report_v1"
CLOSED_OUTCOMES = {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"}


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
    pnl_r = [value for value in pnl_r if value is not None]
    mfe_r = [value for value in mfe_r if value is not None]
    mae_r = [value for value in mae_r if value is not None]
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
        row = {
            "strategy": strategy,
            **_registry_meta(strategy, registry),
            "decision_count": len(strategy_decisions),
            "entry_ready_decisions": sum(1 for d in strategy_decisions if safe_upper(d.get("final_state")) == "ENTRY_READY"),
            "open_decisions": sum(1 for d in strategy_decisions if safe_upper(d.get("outcome_status"), "OPEN") == "OPEN"),
            "decision_states": decision_states,
            "total_outcomes": len(strategy_outcomes),
            "closed_outcomes": closed_count,
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
            "latest_outcome_at": max(outcome_timestamps) if outcome_timestamps else None,
            "evidence_level": _evidence_level(closed_count),
            "parameter_review_ready": closed_count >= 30,
            "sample_size_warning": closed_count < 30,
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
    return {
        "engine": "V32_STRATEGY_PERFORMANCE",
        "strategy_performance_version": STRATEGY_PERFORMANCE_VERSION,
        "generated_at": generated_at,
        "summary": {
            "strategy_count": len(rows),
            "decision_count": len(decisions or []),
            "outcome_count": len(outcomes or []),
            "closed_outcomes": closed_total,
            "parameter_review_ready": [item["strategy"] for item in rows if item["parameter_review_ready"]],
            "insufficient_sample": [item["strategy"] for item in rows if item["sample_size_warning"]],
            "strategy_regime_group_count": len(strategy_regime_performance),
            "parameter_review_group_count": len(parameter_review_performance),
        },
        "strategies": rows,
        "strategy_regime_performance": strategy_regime_performance,
        "parameter_review_performance": parameter_review_performance,
        "review_policy": {
            "minimum_closed_outcomes_for_parameter_review": 30,
            "purpose": "Evidence for strategy and parameter review only.",
            "production_change_requires_versioned_rule": True,
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
    for row in performance_report.get("strategies") or []:
        if not isinstance(row, dict):
            continue
        closed = int(row.get("closed_outcomes") or 0)
        expectancy = safe_float(row.get("expectancy_r"))
        mae = safe_float(row.get("avg_mae_r"))
        ready = closed >= minimum_closed_outcomes
        item = {
            "strategy": row.get("strategy"),
            "closed_outcomes": closed,
            "minimum_closed_outcomes": minimum_closed_outcomes,
            "expectancy_r": expectancy,
            "avg_mae_r": mae,
            "evidence_level": row.get("evidence_level"),
            "parameter_review_ready": ready,
            "recommended_action": "HUMAN_PARAMETER_REVIEW" if ready else "ACCUMULATE_MORE_OUTCOMES",
            "reasons": [],
            "manual_review_required": True,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        if not ready:
            item["reasons"].append("INSUFFICIENT_CLOSED_OUTCOMES")
        if expectancy is None:
            item["reasons"].append("EXPECTANCY_MISSING")
        elif expectancy < 0:
            item["reasons"].append("NEGATIVE_EXPECTANCY_REVIEW_REQUIRED")
        if mae is not None and mae <= -2.0:
            item["reasons"].append("MAE_RISK_REVIEW_REQUIRED")

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
        "policy": {
            "does_not_change_thresholds": True,
            "requires_versioned_rule_change": True,
            "requires_manual_review": True,
            "requires_security_review": True,
        },
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
