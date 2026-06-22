"""Market-regime and research-promotion policy helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REGIME_POLICY_VERSION = "strategy_regime_policy_v1"
PROMOTION_POLICY_VERSION = "research_promotion_policy_v1"
DEFAULT_REGIME_POLICY_PATH = Path("config/strategy_regime_policy_v1.json")


def normalize(value: Any) -> str:
    return str(value or "").strip().upper() or "UNKNOWN"


def canonical_strategy(value: Any) -> str:
    strategy = normalize(value)
    aliases = {
        "NAKED_PUT": "CASH_SECURED_PUT",
        "SHORT_PUT": "CASH_SECURED_PUT",
        "SHORT_CALL_COVERED": "COVERED_CALL",
        "FUTURES": "INTRADAY_INDEX_FUTURES",
        "FUTURES_PRO": "INTRADAY_INDEX_FUTURES",
        "MNQ": "INTRADAY_INDEX_FUTURES",
        "NQ": "INTRADAY_INDEX_FUTURES",
        "MES": "INTRADAY_INDEX_FUTURES",
        "ES": "INTRADAY_INDEX_FUTURES",
    }
    return aliases.get(strategy, strategy)


def load_regime_policy(path: str | Path = DEFAULT_REGIME_POLICY_PATH) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    validate_regime_policy(data)
    return data


def regime_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        normalize(item.get("id")): item
        for item in policy.get("market_regimes") or []
        if isinstance(item, dict)
    }


def get_regime(policy: dict[str, Any], regime: Any) -> dict[str, Any] | None:
    return regime_map(policy).get(normalize(regime))


def validate_regime_policy(policy: dict[str, Any]) -> None:
    if policy.get("regime_policy_version") != REGIME_POLICY_VERSION:
        raise ValueError(f"expected {REGIME_POLICY_VERSION}")
    if policy.get("not_order_instruction") is not True:
        raise ValueError("regime policy must preserve not_order_instruction")
    if policy.get("execution_authorized") is not False:
        raise ValueError("regime policy must never authorize execution")

    required_regime_fields = {
        "id",
        "description",
        "allowed_strategy_bias",
        "caution_strategy_bias",
        "blocked_strategy_bias",
        "parameter_bias",
        "strategy_parameters",
        "required_confirmations",
    }
    seen = set()
    for item in policy.get("market_regimes") or []:
        missing = sorted(required_regime_fields - set(item.keys()))
        rid = normalize(item.get("id"))
        if missing:
            raise ValueError(f"market regime {rid} missing {missing}")
        if rid in seen:
            raise ValueError(f"duplicate market regime {rid}")
        seen.add(rid)
        parameters = item.get("strategy_parameters") or {}
        if not isinstance(parameters, dict) or "GLOBAL" not in parameters:
            raise ValueError(f"market regime {rid} missing GLOBAL strategy_parameters")
        for strategy_id, guidance in parameters.items():
            sid = canonical_strategy(strategy_id)
            if sid not in {
                "GLOBAL",
                "CASH_SECURED_PUT",
                "COVERED_CALL",
                "IRON_CONDOR",
                "INTRADAY_INDEX_FUTURES",
                "CANSLIM_GROWTH_FILTER",
            }:
                raise ValueError(f"market regime {rid} has unknown strategy parameter {strategy_id}")
            if not isinstance(guidance, dict):
                raise ValueError(f"market regime {rid} strategy parameter {strategy_id} must be an object")
            if guidance.get("execution_authorized") is True:
                raise ValueError(f"market regime {rid} strategy parameter {strategy_id} cannot authorize execution")

    for rid in ["BULLISH_LOW_VOL", "NEUTRAL_RANGE", "BEARISH_OR_CORRECTION", "HIGH_VOL_EVENT_RISK", "INTRADAY_TREND"]:
        if rid not in seen:
            raise ValueError(f"missing required market regime {rid}")

    promotion = policy.get("research_promotion_policy") or {}
    if promotion.get("promotion_policy_version") != PROMOTION_POLICY_VERSION:
        raise ValueError(f"expected {PROMOTION_POLICY_VERSION}")
    if int(promotion.get("minimum_closed_outcomes") or 0) < 30:
        raise ValueError("promotion policy needs at least 30 closed outcomes")
    for blocker in ["UNDEFINED_MAX_LOSS", "MISSING_EXIT_PLAYBOOK", "MISSING_OUTCOME_METRICS"]:
        if blocker not in (promotion.get("blocked_if_any") or []):
            raise ValueError(f"promotion blocker missing {blocker}")


def regime_policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    regimes = policy.get("market_regimes") or []
    promotion = policy.get("research_promotion_policy") or {}
    return {
        "regime_policy_version": policy.get("regime_policy_version"),
        "ruleset_version": policy.get("ruleset_version"),
        "status": policy.get("status"),
        "market_regimes": [item.get("id") for item in regimes],
        "parameter_matrix_available": all(
            isinstance(item.get("strategy_parameters"), dict) and bool(item.get("strategy_parameters", {}).get("GLOBAL"))
            for item in regimes
        ),
        "strategy_parameter_coverage": {
            item.get("id"): sorted(
                key for key in (item.get("strategy_parameters") or {}).keys() if key != "GLOBAL"
            )
            for item in regimes
        },
        "research_promotion_policy": {
            "promotion_policy_version": promotion.get("promotion_policy_version"),
            "minimum_closed_outcomes": promotion.get("minimum_closed_outcomes"),
            "minimum_distinct_market_regimes": promotion.get("minimum_distinct_market_regimes"),
            "requires_forward_test": promotion.get("requires_forward_test"),
            "requires_version_bump": promotion.get("requires_version_bump"),
            "blocked_if_any": promotion.get("blocked_if_any") or [],
        },
        "manual_review_required": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def regime_overlay(strategy: Any, regime: Any, policy: dict[str, Any]) -> dict[str, Any]:
    strategy_id = canonical_strategy(strategy)
    regime_id = normalize(regime)
    item = get_regime(policy, regime_id) or {}
    allowed = [normalize(value) for value in item.get("allowed_strategy_bias") or []]
    caution = [normalize(value) for value in item.get("caution_strategy_bias") or []]
    blocked = [normalize(value) for value in item.get("blocked_strategy_bias") or []]
    parameter_matrix = item.get("strategy_parameters") if isinstance(item.get("strategy_parameters"), dict) else {}
    strategy_parameters = parameter_matrix.get(strategy_id) or {}

    if strategy_id in blocked:
        regime_state = "REGIME_BLOCKED"
    elif strategy_id in caution:
        regime_state = "REGIME_CAUTION"
    elif strategy_id in allowed:
        regime_state = "REGIME_ALIGNED"
    else:
        regime_state = "REGIME_UNSPECIFIED"

    return {
        "regime_policy_version": policy.get("regime_policy_version"),
        "strategy_id": strategy_id,
        "market_regime": regime_id,
        "regime_state": regime_state,
        "required_confirmations": item.get("required_confirmations") or [],
        "parameter_bias": item.get("parameter_bias") or {},
        "global_parameters": parameter_matrix.get("GLOBAL") or {},
        "strategy_parameters": strategy_parameters,
        "parameter_guidance_state": "GUIDANCE_AVAILABLE" if strategy_parameters else "NO_STRATEGY_GUIDANCE",
        "manual_review_required": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def promotion_review(strategy: Any, evidence: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    promotion = policy.get("research_promotion_policy") or {}
    blockers = []
    closed = int(evidence.get("closed_outcomes") or 0)
    regimes = int(evidence.get("distinct_market_regimes") or 0)
    expectancy = float(evidence.get("expectancy_r") or 0)
    max_mae = float(evidence.get("max_sample_mae_r") or 0)

    if closed < int(promotion.get("minimum_closed_outcomes") or 30):
        blockers.append("INSUFFICIENT_CLOSED_OUTCOMES")
    if regimes < int(promotion.get("minimum_distinct_market_regimes") or 3):
        blockers.append("INSUFFICIENT_REGIME_COVERAGE")
    if expectancy < float(promotion.get("minimum_positive_expectancy_r") or 0.1):
        blockers.append("EXPECTANCY_BELOW_MINIMUM")
    if max_mae < float(promotion.get("max_sample_mae_r") or -2.0):
        blockers.append("MAE_EXCEEDS_LIMIT")
    for blocker in promotion.get("blocked_if_any") or []:
        if blocker in (evidence.get("known_blockers") or []):
            blockers.append(blocker)

    return {
        "promotion_policy_version": promotion.get("promotion_policy_version"),
        "strategy_id": canonical_strategy(strategy),
        "promotion_ready": not blockers,
        "promotion_blockers": blockers,
        "requires_manual_review": True,
        "requires_version_bump": promotion.get("requires_version_bump") is True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }
