"""Strategy Intelligence helpers for Stock Ultimus V31 contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any


STRATEGY_REGISTRY_VERSION = "strategy_registry_v1"
FRESHNESS_VERSION = "freshness_gates_v1"
SCORE_VERSION = "strategy_score_components_v1"
DAILY_RANKING_VERSION = "strategy_daily_ranking_v1"
SOURCE_CONTEXT_VERSION = "source_context_timestamps_v1"

FRESHNESS_LIMITS_MINUTES = {
    "ibkr_snapshot": 30,
    "technical": 390,
    "market_regime": 30,
    "fundamental_canslim": 1440,
    "account_context": 30,
}


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


def load_json_file(path: str | Path) -> Any:
    try:
        p = Path(path)
        if not p.exists():
            return None
        return json.loads(p.read_text())
    except Exception:
        return None


def strategy_registry(path: str | Path = "config/strategy_registry.json") -> dict[str, Any]:
    data = load_json_file(path)
    if not isinstance(data, dict):
        return {
            "registry_version": STRATEGY_REGISTRY_VERSION,
            "strategies": {},
            "available": False,
        }

    strategies: dict[str, dict[str, Any]] = {}
    for item in data.get("strategies") or []:
        if not isinstance(item, dict):
            continue
        name = safe_upper(item.get("strategy"), "")
        if name:
            strategies[name] = item

    return {
        "registry_version": data.get("registry_version") or STRATEGY_REGISTRY_VERSION,
        "playbook_version": data.get("playbook_version"),
        "intelligence_loop_version": data.get("intelligence_loop_version"),
        "strategies": strategies,
        "available": True,
    }


def strategy_registry_entry(strategy: Any, path: str | Path = "config/strategy_registry.json") -> dict[str, Any]:
    source_strategy = safe_upper(strategy, "UNKNOWN")
    registry = strategy_registry(path)
    strategies = registry.get("strategies") or {}
    aliases = {
        "PUT": "NAKED_PUT",
        "SHORT_PUT": "NAKED_PUT",
        "BULL_PUT_SPREAD": "NAKED_PUT",
        "CSP": "CASH_SECURED_PUT",
        "CALL": "COVERED_CALL",
        "SHORT_CALL": "COVERED_CALL",
        "BEAR_CALL_SPREAD": "COVERED_CALL",
        "FUTURES": "FUTURES_INTRADAY",
        "FUTURES_PRO": "FUTURES_INTRADAY",
    }
    canonical = aliases.get(source_strategy, source_strategy)
    entry = strategies.get(canonical)
    if not isinstance(entry, dict):
        entry = {
            "strategy": canonical,
            "state": "ENABLED",
            "entry_ready_cap": "MANUAL_REVIEW_ONLY",
            "research_stage": "UNREGISTERED",
            "notes": "Strategy not present in registry; defaulting to compatibility mode.",
        }
    return {
        "registry_version": registry.get("registry_version"),
        "playbook_version": registry.get("playbook_version"),
        "intelligence_loop_version": registry.get("intelligence_loop_version"),
        "strategy": canonical,
        "source_strategy": source_strategy,
        "state": entry.get("state"),
        "entry_ready_cap": entry.get("entry_ready_cap"),
        "research_stage": entry.get("research_stage"),
        "strategy_version": entry.get("strategy_version"),
        "ruleset_version": entry.get("ruleset_version"),
        "notes": entry.get("notes"),
        "available": registry.get("available"),
    }


def timestamp_candidate_from_obj(obj: Any) -> Any:
    if not isinstance(obj, dict):
        return None
    for key in [
        "received_at",
        "generated_at",
        "timestamp",
        "source_timestamp",
        "updated_at",
        "saved_at",
        "as_of",
        "received_at_bridge",
        "canslim_received_at",
        "fundamental_received_at",
    ]:
        value = obj.get(key)
        if value:
            return value
    return None


def first_timestamp_in_obj(obj: Any, max_depth: int = 4) -> Any:
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        direct = timestamp_candidate_from_obj(obj)
        if direct:
            return direct
        for value in obj.values():
            found = first_timestamp_in_obj(value, max_depth - 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = first_timestamp_in_obj(item, max_depth - 1)
            if found:
                return found
    return None


def pick_context_timestamp(master_data: dict[str, Any], row: dict[str, Any], technical_raw: dict[str, Any], context_keys: list[str]) -> Any:
    sources: list[Any] = []
    if isinstance(row, dict):
        sources.append(row)
    if isinstance(technical_raw, dict):
        sources.append(technical_raw)
    if isinstance(master_data, dict):
        for key in context_keys:
            value = master_data.get(key)
            if value is not None:
                sources.append(value)

    for source in sources:
        found = first_timestamp_in_obj(source)
        if found:
            return found
    return None


def source_context(decision: dict[str, Any], master_data: dict[str, Any]) -> dict[str, Any]:
    row = decision.get("best_row") if isinstance(decision.get("best_row"), dict) else {}
    technical = decision.get("technical") if isinstance(decision.get("technical"), dict) else {}
    technical_raw = technical.get("raw") if isinstance(technical.get("raw"), dict) else {}

    fundamental_timestamp = pick_context_timestamp(
        master_data,
        row,
        technical_raw,
        [
            "fundamental",
            "fundamentals",
            "fundamental_snapshot",
            "fundamental_context",
            "canslim",
            "canslim_snapshot",
            "technical_snapshot",
        ],
    )
    account_timestamp = pick_context_timestamp(
        master_data,
        row,
        technical_raw,
        [
            "account_context",
            "account_snapshot",
            "account_summary",
            "portfolio",
            "portfolio_snapshot",
            "positions",
            "positions_rows",
            "balances",
            "risk_profile",
        ],
    )
    master_timestamp = (
        (master_data or {}).get("received_at")
        or (master_data or {}).get("generated_at")
        or decision.get("snapshot_received_at")
        or decision.get("snapshot_generated_at")
    )

    return {
        "context_version": SOURCE_CONTEXT_VERSION,
        "ibkr_snapshot": {
            "timestamp": master_timestamp,
            "available": bool(master_timestamp),
        },
        "fundamental_canslim": {
            "timestamp": fundamental_timestamp,
            "available": bool(fundamental_timestamp),
            "sensitive_values_excluded": True,
        },
        "account_context": {
            "timestamp": account_timestamp,
            "available": bool(account_timestamp),
            "sensitive_values_excluded": True,
        },
    }


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def first_timestamp(*values: Any) -> tuple[datetime | None, Any]:
    for value in values:
        parsed = parse_datetime(value)
        if parsed is not None:
            return parsed, value
    return None, None


def freshness_gate(name: str, timestamp_value: Any, max_age_minutes: int, *, required: bool = True, fallback_note: str | None = None) -> dict[str, Any]:
    parsed, raw_value = first_timestamp(timestamp_value)
    if parsed is None:
        status = "UNKNOWN_REQUIRED" if required else "NOT_PROVIDED"
        return {
            "status": status,
            "fresh": not required,
            "required": required,
            "timestamp": None,
            "age_minutes": None,
            "max_age_minutes": max_age_minutes,
            "score": 0 if required else 50,
            "blocker": f"{name.upper()}_FRESHNESS_UNKNOWN" if required else None,
            "notes": ["timestamp missing"] + ([fallback_note] if fallback_note else []),
        }

    age_minutes = round((datetime.now(timezone.utc) - parsed).total_seconds() / 60, 2)
    fresh = age_minutes <= max_age_minutes
    score = 100 if fresh else max(0, round(100 - min(100, ((age_minutes - max_age_minutes) / max(max_age_minutes, 1)) * 100), 2))
    return {
        "status": "FRESH" if fresh else "STALE",
        "fresh": fresh,
        "required": required,
        "timestamp": parsed.isoformat(),
        "source_timestamp": raw_value,
        "age_minutes": age_minutes,
        "max_age_minutes": max_age_minutes,
        "score": score,
        "blocker": None if fresh else f"{name.upper()}_STALE",
        "notes": [fallback_note] if fallback_note else [],
    }


def freshness_gates(v29_decision: dict[str, Any]) -> dict[str, Any]:
    snapshot_timestamp = v29_decision.get("snapshot_received_at") or v29_decision.get("snapshot_generated_at")
    src_context = v29_decision.get("source_context") if isinstance(v29_decision.get("source_context"), dict) else {}
    technical_raw = ((v29_decision.get("technical") or {}).get("raw") or {}) if isinstance(v29_decision.get("technical"), dict) else {}
    market = v29_decision.get("market") if isinstance(v29_decision.get("market"), dict) else {}
    market_raw = market.get("raw") if isinstance(market.get("raw"), dict) else {}
    risk_gate = v29_decision.get("risk_gate") if isinstance(v29_decision.get("risk_gate"), dict) else {}
    canslim = risk_gate.get("canslim") if isinstance(risk_gate.get("canslim"), dict) else {}
    canslim_raw = canslim.get("raw") if isinstance(canslim.get("raw"), dict) else {}
    fundamental_context = src_context.get("fundamental_canslim") if isinstance(src_context.get("fundamental_canslim"), dict) else {}
    account_context = src_context.get("account_context") if isinstance(src_context.get("account_context"), dict) else {}
    ibkr_context = src_context.get("ibkr_snapshot") if isinstance(src_context.get("ibkr_snapshot"), dict) else {}

    technical_timestamp = (
        technical_raw.get("received_at")
        or technical_raw.get("saved_at")
        or technical_raw.get("generated_at")
        or technical_raw.get("timestamp")
        or technical_raw.get("time")
    )
    technical_note = None
    if not technical_timestamp and snapshot_timestamp:
        technical_timestamp = snapshot_timestamp
        technical_note = "technical timestamp missing; using snapshot timestamp fallback"

    market_timestamp = (
        market.get("generated_at")
        or market.get("received_at")
        or market_raw.get("generated_at")
        or market_raw.get("received_at")
        or market_raw.get("timestamp")
    )
    market_note = None
    if not market_timestamp and snapshot_timestamp:
        market_timestamp = snapshot_timestamp
        market_note = "market timestamp missing; using snapshot timestamp fallback"

    canslim_timestamp = (
        fundamental_context.get("timestamp")
        or canslim.get("timestamp")
        or canslim.get("source_timestamp")
        or canslim.get("generated_at")
        or canslim.get("received_at")
        or canslim_raw.get("canslim_received_at")
        or canslim_raw.get("fundamental_received_at")
        or canslim_raw.get("source_timestamp")
        or canslim_raw.get("received_at")
        or canslim_raw.get("generated_at")
        or canslim_raw.get("timestamp")
    )
    account_timestamp = account_context.get("timestamp")

    gates = {
        "ibkr_snapshot": freshness_gate("ibkr_snapshot", ibkr_context.get("timestamp") or snapshot_timestamp, FRESHNESS_LIMITS_MINUTES["ibkr_snapshot"], required=True),
        "technical": freshness_gate("technical", technical_timestamp, FRESHNESS_LIMITS_MINUTES["technical"], required=True, fallback_note=technical_note),
        "market_regime": freshness_gate("market_regime", market_timestamp, FRESHNESS_LIMITS_MINUTES["market_regime"], required=True, fallback_note=market_note),
        "fundamental_canslim": freshness_gate("fundamental_canslim", canslim_timestamp, FRESHNESS_LIMITS_MINUTES["fundamental_canslim"], required=False),
        "account_context": freshness_gate("account_context", account_timestamp, FRESHNESS_LIMITS_MINUTES["account_context"], required=False),
    }

    critical = ["ibkr_snapshot", "technical", "market_regime"]
    blockers = [gates[name].get("blocker") for name in critical if gates.get(name) and gates[name].get("blocker")]
    unknown_required = [name for name in critical if gates.get(name) and gates[name].get("status") == "UNKNOWN_REQUIRED"]
    scores = [safe_float(gate.get("score"), 0) for gate in gates.values()]
    aggregate_score = round(sum(scores) / len(scores), 2) if scores else 0

    return {
        "freshness_version": FRESHNESS_VERSION,
        "aggregate_score": aggregate_score,
        "all_required_fresh": not blockers and not unknown_required,
        "blocks_actionable_ranking": bool(blockers or unknown_required),
        "blockers": [b for b in blockers if b] + [f"{name.upper()}_FRESHNESS_UNKNOWN" for name in unknown_required],
        "gates": gates,
        "source_context": src_context,
    }


def score_component(value: Any, status: str, notes: list[str] | None = None, weight: int = 0) -> dict[str, Any]:
    score = safe_float(value, 0)
    score = max(0, min(100, score or 0))
    return {
        "score": round(score, 2),
        "status": status,
        "weight": weight,
        "notes": notes or [],
    }


def selected_contract_from_decision(v29_decision: dict[str, Any]) -> dict[str, Any]:
    row = v29_decision.get("best_row") or {}
    quality = v29_decision.get("best_row_quality") or {}
    return {
        "ticker": v29_decision.get("ticker"),
        "strategy": v29_decision.get("strategy"),
        "strike": row.get("strike"),
        "expiration": row.get("expiration"),
        "dte": row.get("dte"),
        "bid": quality.get("bid"),
        "ask": quality.get("ask"),
        "mid": quality.get("mid"),
        "spread": quality.get("spread"),
        "spread_pct": quality.get("spread_pct"),
        "delta": quality.get("delta"),
        "iv": quality.get("iv"),
        "volume": quality.get("volume"),
        "open_interest": quality.get("open_interest"),
        "data_quality": row.get("data_quality"),
        "source_decision": row.get("decision"),
        "source_score": row.get("score"),
    }


def score_components(
    v29_decision: dict[str, Any],
    registry_entry: dict[str, Any],
    final_state: str,
    blockers: list[str],
    *,
    min_tech_score: int = 65,
    freshness: dict[str, Any] | None = None,
    selected_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    technical_score = safe_float(v29_decision.get("technical_score"), None)
    technical_fit = str(v29_decision.get("technical_fit") or "")
    technical_ok = technical_score is not None and technical_score >= min_tech_score and "NOT_CONFIRMED" not in technical_fit
    technical_component = score_component(technical_score if technical_score is not None else 0, "CONFIRMED" if technical_ok else "NOT_CONFIRMED", [technical_fit or "TECHNICAL_SCORE_MISSING"], 25)

    contract = selected_contract or selected_contract_from_decision(v29_decision)
    missing = list(v29_decision.get("required_missing_fields") or [])
    spread_pct = safe_float(contract.get("spread_pct"), None)
    option_source_score = safe_float(v29_decision.get("options_score"), 0)
    if missing:
        option_score = max(0, 50 - (len(missing) * 8))
        option_status = "INCOMPLETE"
    else:
        spread_penalty = 0 if spread_pct is None else min(40, max(0, spread_pct - 5))
        option_score = min(100, max(option_source_score or 0, 75) - spread_penalty)
        option_status = "EXECUTABLE"
    option_component = score_component(option_score, option_status, missing or [f"spread_pct={spread_pct}" if spread_pct is not None else "spread_pct=UNKNOWN"], 25)

    risk_gate = v29_decision.get("risk_gate") if isinstance(v29_decision.get("risk_gate"), dict) else {}
    strategy_blockers = list(risk_gate.get("strategy_risk_blockers") or [])
    risk_blockers = [b for b in blockers if b and b not in ["STRATEGY_RADAR_ONLY"]]
    risk_ok = final_state not in ["RISK_BLOCKED", "WAIT_ACCOUNT_CONTEXT"] and not strategy_blockers
    risk_component = score_component(100 if risk_ok else 25, "PASS" if risk_ok else "BLOCKED", strategy_blockers or risk_blockers or ["RISK_CONFIRMED"], 25)

    canslim = risk_gate.get("canslim") if isinstance(risk_gate.get("canslim"), dict) else None
    canslim_score = safe_float((canslim or {}).get("score"), None) if isinstance(canslim, dict) else None
    canslim_status = (canslim or {}).get("status") if isinstance(canslim, dict) else None
    fundamental_component = score_component(canslim_score if canslim_score is not None else 50, canslim_status or "NOT_PROVIDED", ["CANSLIM/fundamental filter optional until configured as required"] if canslim_score is None else [], 15)

    market = v29_decision.get("market") if isinstance(v29_decision.get("market"), dict) else {}
    market_ok = bool(market.get("is_regular_market_open")) and bool(market.get("options_bidask_expected"))
    regime_component = score_component(100 if market_ok else 40, "SESSION_OK" if market_ok else "WAIT_MARKET", [str(market.get("label") or "UNKNOWN")], 5)
    outcome_component = score_component(50, "NEUTRAL_PENDING_V32_DURABLE_EVIDENCE", ["Outcome evidence is neutral until V32 history is durable and reviewed."], 5)

    freshness = freshness or freshness_gates(v29_decision)
    freshness_component = score_component(freshness.get("aggregate_score"), "FRESH" if freshness.get("all_required_fresh") else "STALE_OR_UNKNOWN", freshness.get("blockers") or ["freshness gates passed"], 10)

    registry_state = safe_upper(registry_entry.get("state"), "ENABLED")
    registry_component = score_component(100 if registry_state == "ENABLED" else (50 if registry_state == "RADAR_ONLY" else 0), registry_state, [registry_entry.get("entry_ready_cap") or "UNKNOWN"], 0)

    components = {
        "technical_fit": technical_component,
        "option_quality": option_component,
        "risk_fit": risk_component,
        "fundamental_fit": fundamental_component,
        "regime_fit": regime_component,
        "outcome_evidence": outcome_component,
        "freshness": freshness_component,
        "strategy_registry": registry_component,
    }
    weighted_total = 0.0
    total_weight = 0.0
    for key, component in components.items():
        if key == "strategy_registry":
            continue
        weight = safe_float(component.get("weight"), 0) or 0
        weighted_total += component["score"] * weight
        total_weight += weight

    ranking_score = round(weighted_total / total_weight, 2) if total_weight else 0
    if registry_state == "RADAR_ONLY":
        ranking_label = "RADAR_ONLY_RESEARCH"
    elif final_state == "ENTRY_READY" and ranking_score >= 90:
        ranking_label = "TOP_MANUAL_REVIEW"
    elif final_state == "ENTRY_READY":
        ranking_label = "MANUAL_REVIEW_CANDIDATE"
    elif final_state in ["WAIT_OPTIONS_DATA", "RISK_BLOCKED", "WAIT_ACCOUNT_CONTEXT"]:
        ranking_label = "BLOCKED"
    else:
        ranking_label = "WATCHLIST"

    return {
        "score_version": SCORE_VERSION,
        "ranking_score": ranking_score,
        "ranking_label": ranking_label,
        "components": components,
        "blocked_from_actionable_ranking": final_state != "ENTRY_READY" or bool(freshness.get("blocks_actionable_ranking")),
    }


def ranking_item(decision: dict[str, Any], rank: int | None = None) -> dict[str, Any]:
    sc = decision.get("score_components") or {}
    registry = decision.get("strategy_registry") or {}
    return {
        "rank": rank,
        "ticker": decision.get("ticker"),
        "strategy": decision.get("strategy"),
        "final_state": decision.get("final_state"),
        "main_blocker": decision.get("main_blocker"),
        "blockers": list(decision.get("blockers") or []),
        "ranking_score": sc.get("ranking_score"),
        "ranking_label": sc.get("ranking_label"),
        "score_components": sc.get("components"),
        "freshness": decision.get("freshness"),
        "strategy_registry_state": registry.get("state"),
        "research_stage": registry.get("research_stage"),
        "ready_for_manual_review": decision.get("ready_for_manual_review") is True,
        "blocked_from_actionable_ranking": sc.get("blocked_from_actionable_ranking") is True,
        "selected_contract": decision.get("selected_contract"),
        "next_required_action": decision.get("next_required_action"),
        "explanation": decision.get("explanation"),
        "audit": decision.get("audit"),
    }


def sort_ranked_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            safe_float(item.get("ranking_score"), 0) or 0,
            str(item.get("ticker") or ""),
            str(item.get("strategy") or ""),
        ),
        reverse=True,
    )


def daily_rankings(decisions: list[dict[str, Any]], *, now_iso: str, decision_version: str, ruleset_version: str) -> dict[str, Any]:
    top_manual_review: list[dict[str, Any]] = []
    watchlist: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    research_only: list[dict[str, Any]] = []

    for decision in decisions:
        registry_state = safe_upper((decision.get("strategy_registry") or {}).get("state"), "ENABLED")
        final_state = decision.get("final_state")
        label = (decision.get("score_components") or {}).get("ranking_label")
        freshness_blocks = bool((decision.get("freshness") or {}).get("blocks_actionable_ranking"))
        item = ranking_item(decision)

        if registry_state == "RADAR_ONLY" or label == "RADAR_ONLY_RESEARCH":
            research_only.append(item)
        elif final_state == "ENTRY_READY" and not freshness_blocks:
            top_manual_review.append(item)
        elif final_state in ["WAIT_OPTIONS_DATA", "RISK_BLOCKED", "WAIT_ACCOUNT_CONTEXT"]:
            blocked.append(item)
        else:
            watchlist.append(item)

    top_manual_review = sort_ranked_items(top_manual_review)
    watchlist = sort_ranked_items(watchlist)
    blocked = sort_ranked_items(blocked)
    research_only = sort_ranked_items(research_only)

    for section in [top_manual_review, watchlist, blocked, research_only]:
        for index, item in enumerate(section, start=1):
            item["rank"] = index

    all_ranked = sort_ranked_items(top_manual_review + watchlist + blocked + research_only)
    for index, item in enumerate(all_ranked, start=1):
        item["overall_rank"] = index

    return {
        "engine": "V31_DAILY_STRATEGY_RANKING",
        "ranking_version": DAILY_RANKING_VERSION,
        "score_version": SCORE_VERSION,
        "decision_version": decision_version,
        "ruleset_version": ruleset_version,
        "generated_at": now_iso,
        "not_order_instruction": True,
        "execution_authorized": False,
        "ranking_policy": {
            "entry_ready_meaning": "READY_FOR_MANUAL_REVIEW_ONLY",
            "blocked_states_excluded_from_top_manual_review": [
                "WAIT_OPTIONS_DATA",
                "WAIT_ACCOUNT_CONTEXT",
                "RISK_BLOCKED",
            ],
            "radar_only_excluded_from_entry_ready": True,
        },
        "summary": {
            "decisions_evaluated": len(decisions),
            "top_manual_review": len(top_manual_review),
            "watchlist": len(watchlist),
            "blocked": len(blocked),
            "research_only": len(research_only),
        },
        "top_manual_review": top_manual_review,
        "watchlist": watchlist,
        "blocked": blocked,
        "research_only": research_only,
        "all_ranked": all_ranked,
    }
