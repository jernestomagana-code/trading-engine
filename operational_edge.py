"""Integrated next-level operating edge report for Stock Ultimus.

This module turns the existing evidence layers into one auditable readiness
view. It is decision support only: it never authorizes orders or parameter
changes.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import alert_opportunity_audit
import strategy_performance


OPERATIONAL_EDGE_VERSION = "v32_operational_edge_v1"
TOP_SYSTEM_TARGET = "measured_learning_ranking_contract_quality_loop"
CLOSED_OUTCOMES = {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"}


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


def safe_upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, value)), 2)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def list_from_payload(payload: Any, keys: list[str]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def load_runtime(runtime_dir: Path) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    return {
        "runtime_dir": runtime_dir,
        "tradingview_bundle": read_json(runtime_dir / "tradingview_alert_bundle_health.json", {}),
        "market_open_readiness": read_json(runtime_dir / "market_open_readiness_latest.json", {}),
        "daily_radar": read_json(runtime_dir / "daily_radar_latest.json", {}),
        "ibkr_chain": read_json(runtime_dir / "v32_ibkr_chain_coverage.json", {}),
        "canslim": read_json(runtime_dir / "canslim_candidates_latest.json", {}),
        "alert_audit": read_json(runtime_dir / "alert_opportunity_deep_audit_latest.json", {}),
        "decision_journal": read_json(runtime_dir / "v32_decision_journal.json", []),
        "outcomes_journal": read_json(runtime_dir / "v32_outcomes_journal.json", []),
        "operator_events": read_json(runtime_dir / "v32_operator_events.json", []),
        "foundation_health": read_json(runtime_dir / "foundation_health_latest.json", {}),
    }


def status_from_score(score: float, *, ready_at: float = 80.0, review_at: float = 55.0) -> str:
    if score >= ready_at:
        return "READY"
    if score >= review_at:
        return "NEEDS_REVIEW"
    return "BUILDING"


def build_market_confirmation(runtime: dict[str, Any]) -> dict[str, Any]:
    bundle = runtime.get("tradingview_bundle") if isinstance(runtime.get("tradingview_bundle"), dict) else {}
    market = runtime.get("market_open_readiness") if isinstance(runtime.get("market_open_readiness"), dict) else {}
    total_active = safe_int(bundle.get("total_production_active_alert_count"))
    required_logical = safe_int(bundle.get("total_required_logical_event_count"))
    received_required = safe_int(bundle.get("total_received_required_event_count"))
    real_e2e = bool(bundle.get("real_e2e_confirmed"))
    has_five_alert_model = total_active == 5 and required_logical >= 16
    live_ratio = (received_required / required_logical) if required_logical else 0.0
    score = 30.0
    if has_five_alert_model:
        score += 25.0
    if bundle.get("coverage_valid"):
        score += 15.0
    if bundle.get("status") in {"READY", "TV_OK"}:
        score += 15.0
    if real_e2e:
        score += 15.0
    else:
        score += live_ratio * 15.0
    blockers = list(bundle.get("blockers") or [])
    if not real_e2e:
        blockers.append("WAITING_FOR_REAL_TRADINGVIEW_EVENTS")
    return {
        "capability": "real_market_confirmation",
        "score": clamp(score),
        "status": "READY" if real_e2e else ("WAIT_LIVE_CONFIRMATION" if has_five_alert_model else "NEEDS_SETUP"),
        "active_alert_count": total_active,
        "required_logical_event_count": required_logical,
        "received_required_event_count": received_required,
        "real_e2e_confirmed": real_e2e,
        "intraday_futures_primary_timing": "TradingView webhook -> /technical_snapshot -> immediate notify",
        "five_minute_watch_role": "fallback_operator_reminder",
        "market_open_readiness": market.get("status") or market.get("readiness") or "UNKNOWN",
        "blockers": sorted(set(blockers)),
        "next_action": "Confirmar eventos reales MNQ/MES y QQQ/SPY/VIX en mercado abierto.",
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def score_value(item: dict[str, Any]) -> float | None:
    for key in ["setup_validity_pct", "conviction_score", "ranking_score", "score"]:
        value = safe_float(item.get(key))
        if value is not None:
            return value
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    for key in ["setup_validity_pct", "conviction_score", "ranking_score", "score"]:
        value = safe_float(raw.get(key))
        if value is not None:
            return value
    return None


def score_bucket(value: float | None) -> str:
    if value is None:
        return "NO_SCORE"
    if value >= 90:
        return "90_100"
    if value >= 75:
        return "75_89"
    if value >= 60:
        return "60_74"
    return "0_59"


def build_score_calibration(decisions: list[dict[str, Any]], raw_outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [
        item for item in raw_outcomes
        if safe_upper(item.get("outcome")) in CLOSED_OUTCOMES
    ]
    completeness = strategy_performance.outcome_completeness_report(raw_outcomes)
    scored_decisions = [item for item in decisions if score_value(item) is not None]
    scored_outcomes = [item for item in closed if score_value(item) is not None]
    buckets: dict[str, dict[str, Any]] = {}
    for outcome in scored_outcomes:
        bucket = score_bucket(score_value(outcome))
        row = buckets.setdefault(bucket, {"bucket": bucket, "closed_count": 0, "wins": 0, "losses": 0, "pnl_r": [], "mfe_r": [], "mae_r": []})
        row["closed_count"] += 1
        if safe_upper(outcome.get("outcome")) == "WIN":
            row["wins"] += 1
        if safe_upper(outcome.get("outcome")) == "LOSS":
            row["losses"] += 1
        for key in ["pnl_r", "mfe_r", "mae_r"]:
            value = safe_float(outcome.get(key))
            if value is not None:
                row[key].append(value)

    bucket_rows = []
    for key in sorted(buckets.keys()):
        row = buckets[key]
        denominator = row["wins"] + row["losses"]
        bucket_rows.append({
            "bucket": key,
            "closed_count": row["closed_count"],
            "win_rate": round((row["wins"] / denominator) * 100, 2) if denominator else None,
            "expectancy_r": round(sum(row["pnl_r"]) / len(row["pnl_r"]), 4) if row["pnl_r"] else None,
            "avg_mfe_r": round(sum(row["mfe_r"]) / len(row["mfe_r"]), 4) if row["mfe_r"] else None,
            "avg_mae_r": round(sum(row["mae_r"]) / len(row["mae_r"]), 4) if row["mae_r"] else None,
        })

    complete_closed = safe_int(completeness.get("complete_closed_outcomes"))
    score = 20.0
    score += min(complete_closed, 30) / 30 * 45.0
    score += min(len(scored_decisions), 50) / 50 * 20.0
    score += min(len(bucket_rows), 4) / 4 * 15.0
    status = "CALIBRATABLE" if complete_closed >= 30 and bucket_rows else status_from_score(score)
    return {
        "capability": "score_calibration_by_outcome",
        "score": clamp(score),
        "status": status,
        "decision_count": len(decisions),
        "scored_decision_count": len(scored_decisions),
        "closed_outcome_count": len(closed),
        "complete_closed_outcomes": complete_closed,
        "score_bucket_outcomes": bucket_rows,
        "minimum_complete_closed_outcomes": 30,
        "primary_gap": "INSUFFICIENT_COMPLETE_OUTCOMES" if complete_closed < 30 else "REVIEW_SCORE_WEIGHTS",
        "next_action": "Seguir guardando MFE/MAE/PnL R y score original para calibrar pesos con evidencia.",
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def contract_value(decision: dict[str, Any]) -> dict[str, Any]:
    contract = decision.get("contract")
    if isinstance(contract, dict) and contract:
        return contract
    raw = decision.get("raw") if isinstance(decision.get("raw"), dict) else {}
    contract = raw.get("selected_contract")
    return contract if isinstance(contract, dict) else {}


def institutional_opportunity_score(item: dict[str, Any]) -> float:
    final_state = safe_upper(item.get("final_state"))
    base = score_value(item)
    score = clamp(base if base is not None else 35.0)
    if final_state == "ENTRY_READY":
        score += 35
    elif final_state == "MANUAL_REVIEW":
        score += 20
    elif final_state in {"WAIT_OPTIONS_DATA", "WAIT_TECHNICAL", "WAIT_ACCOUNT_CONTEXT"}:
        score -= 12
    elif final_state.startswith("WAIT"):
        score -= 5
    elif final_state in {"RISK_BLOCKED", "NO_DATA"}:
        score -= 35
    if bool(item.get("manual_review_ready")):
        score += 20
    if safe_upper(item.get("candidate_source")) != "UNKNOWN":
        score += 6
    if safe_upper(item.get("confirmation_source")) != "UNKNOWN":
        score += 8
    contract = contract_value(item)
    if has_value(contract.get("delta")):
        score += 6
    if has_value(contract.get("dte")):
        score += 4
    spread = safe_float(contract.get("spread_pct"))
    if spread is not None and spread <= 5:
        score += 8
    if safe_upper(item.get("signal_source")) == "TRADINGVIEW_ALERT":
        score += 5
    blockers = item.get("blockers") or []
    score -= min(len(blockers), 6) * 7
    return clamp(score, 0, 150)


def build_institutional_ranking(decisions: list[dict[str, Any]], top_limit: int) -> dict[str, Any]:
    ranked_by_key: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for item in decisions:
        if safe_upper(item.get("ticker")) == "UNKNOWN":
            continue
        score = institutional_opportunity_score(item)
        contract = contract_value(item)
        blocker = item.get("main_blocker")
        blocker = None if safe_upper(blocker) == "UNKNOWN" else blocker
        row = {
            "ticker": item.get("ticker"),
            "strategy": item.get("strategy"),
            "final_state": item.get("final_state"),
            "main_blocker": blocker,
            "institutional_score": score,
            "raw_score": score_value(item),
            "manual_review_ready": bool(item.get("manual_review_ready")),
            "candidate_source": item.get("candidate_source"),
            "confirmation_source": item.get("confirmation_source"),
            "contract": {
                key: contract.get(key)
                for key in ["expiration", "strike", "dte", "delta", "spread_pct", "bid", "ask", "mid"]
                if contract.get(key) is not None
            },
            "blockers": item.get("blockers") or [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        key = (
            safe_upper(row.get("ticker")),
            safe_upper(row.get("strategy")),
            safe_upper(row.get("final_state")),
            str((row.get("contract") or {}).get("expiration") or "NOEXP"),
            str((row.get("contract") or {}).get("strike") or "NOSTRIKE"),
        )
        current = ranked_by_key.get(key)
        if current is None or row["institutional_score"] > current["institutional_score"]:
            ranked_by_key[key] = row
    ranked = list(ranked_by_key.values())
    ranked = sorted(ranked, key=lambda row: row["institutional_score"], reverse=True)
    top = ranked[:max(1, int(top_limit or 5))]
    score = 45.0 + min(len(top), 5) * 6.0
    if any(row.get("final_state") == "ENTRY_READY" for row in top):
        score += 15.0
    if any(row.get("manual_review_ready") for row in top):
        score += 10.0
    return {
        "capability": "institutional_opportunity_ranking",
        "score": clamp(score),
        "status": "RANKING_AVAILABLE" if top else "NO_RANKABLE_DECISIONS",
        "ranked_count": len(ranked),
        "top_limit": top_limit,
        "top_opportunities": top,
        "ranking_policy": "Prefer ENTRY_READY/manual-review-ready, sourced, liquid, complete-contract setups; penalize blockers.",
        "next_action": "Usar top_opportunities como shortlist, no como instruccion de orden.",
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def option_contract_score(row: dict[str, Any]) -> float:
    score = 0.0
    quality = safe_upper(row.get("data_quality"))
    if quality == "FULL_WITH_GREEKS":
        score += 25
    elif "WITH_GREEKS" in quality:
        score += 18
    elif quality != "UNKNOWN":
        score += 8
    spread = safe_float(row.get("spread_pct"))
    if spread is not None:
        score += max(0, 25 - min(spread, 25))
    delta = safe_float(row.get("delta"))
    if delta is not None:
        abs_delta = abs(delta)
        score += max(0, 20 - abs(abs_delta - 0.18) * 100)
    dte = safe_float(row.get("dte"))
    if dte is not None:
        score += max(0, 15 - abs(dte - 42) * 0.8)
    oi = safe_float(row.get("open_interest"), 0) or 0
    volume = safe_float(row.get("volume"), 0) or 0
    if oi >= 1000:
        score += 8
    if volume >= 100:
        score += 5
    if safe_upper(row.get("decision")) == "ENTRY_READY":
        score += 12
    if row.get("discarded_for_manual_review"):
        score -= 20
    score -= min(len(row.get("discard_reasons") or []), 5) * 6
    return clamp(score, 0, 120)


def build_option_optimizer(runtime: dict[str, Any], top_limit: int) -> dict[str, Any]:
    chain = runtime.get("ibkr_chain") if isinstance(runtime.get("ibkr_chain"), dict) else {}
    rows = list_from_payload(chain.get("option_rows"), ["option_rows", "rows", "items"])
    if not rows and isinstance(chain.get("option_rows"), list):
        rows = [item for item in chain.get("option_rows") if isinstance(item, dict)]
    ranked = []
    for row in rows:
        ranked.append({
            "ticker": safe_upper(row.get("ticker")),
            "strategy": safe_upper(row.get("strategy")),
            "expiration": row.get("expiration"),
            "strike": row.get("strike"),
            "dte": row.get("dte"),
            "delta": row.get("delta"),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "mid": row.get("mid"),
            "spread_pct": row.get("spread_pct"),
            "iv": row.get("iv"),
            "volume": row.get("volume"),
            "open_interest": row.get("open_interest"),
            "data_quality": row.get("data_quality"),
            "decision": row.get("decision"),
            "contract_score": option_contract_score(row),
            "discard_reasons": row.get("discard_reasons") or [],
            "execution_authorized": False,
            "not_order_instruction": True,
        })
    ranked = sorted(ranked, key=lambda row: row["contract_score"], reverse=True)
    by_underlying: dict[str, dict[str, Any]] = {}
    for row in ranked:
        key = f"{row['ticker']}::{row['strategy']}"
        by_underlying.setdefault(key, row)
    plan = chain.get("option_symbol_plan") if isinstance(chain.get("option_symbol_plan"), dict) else {}
    score = 25.0
    if rows:
        score += 25.0
    if plan.get("enabled"):
        score += 20.0
    if chain.get("primary_gap") in {None, "", "NONE", "COVERAGE_REVIEWABLE"}:
        score += 15.0
    if ranked and ranked[0]["contract_score"] >= 80:
        score += 15.0
    return {
        "capability": "option_contract_optimizer",
        "score": clamp(score),
        "status": "CONTRACT_RANKING_AVAILABLE" if ranked else "WAIT_IBKR_CHAIN_ROWS",
        "option_row_count": len(rows),
        "primary_gap": chain.get("primary_gap"),
        "symbol_plan": {
            "enabled": plan.get("enabled"),
            "candidate_count": plan.get("candidate_count"),
            "selected_count": plan.get("selected_count"),
            "selected_symbols": plan.get("selected_symbols") or [],
            "max_symbols_per_run": plan.get("max_symbols_per_run"),
            "max_total_option_contracts_per_run": plan.get("max_total_option_contracts_per_run"),
            "canslim_candidate_count": plan.get("canslim_candidate_count"),
        },
        "best_contracts": ranked[:max(1, int(top_limit or 5))],
        "best_by_underlying_strategy": list(by_underlying.values())[:max(1, int(top_limit or 5))],
        "next_action": "Revisar best_contracts antes de pedir mas cadenas; el presupuesto de IBKR ya limita el universo.",
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def canslim_confidence(row: dict[str, Any]) -> dict[str, Any]:
    score = safe_float(row.get("canslim_score") or row.get("score"))
    passes = row.get("canslim_passes")
    rating = safe_upper(row.get("canslim_rating") or row.get("rating"), "")
    if score is None:
        confidence = "UNAVAILABLE"
        contribution = 0.0
    elif passes is True and score >= 85:
        confidence = "STRONG"
        contribution = 100.0
    elif passes is True or score >= 70:
        confidence = "PARTIAL"
        contribution = 75.0
    elif score >= 55:
        confidence = "WEAK"
        contribution = 45.0
    else:
        confidence = "FAIL"
        contribution = 10.0
    return {
        "ticker": safe_upper(row.get("ticker") or row.get("symbol")),
        "canslim_score": score,
        "canslim_passes": passes,
        "rating": rating,
        "confidence": confidence,
        "score_contribution": contribution,
        "degradation_policy": "Unavailable does not hard-block; weak/fail lowers ranking confidence.",
    }


def build_canslim(runtime: dict[str, Any], top_limit: int) -> dict[str, Any]:
    payload = runtime.get("canslim") if isinstance(runtime.get("canslim"), dict) else {}
    candidates = list_from_payload(payload, ["candidates", "rows", "items"])
    rows = sorted([canslim_confidence(row) for row in candidates], key=lambda row: row["score_contribution"], reverse=True)
    available = [row for row in rows if row["confidence"] != "UNAVAILABLE"]
    strong = [row for row in rows if row["confidence"] == "STRONG"]
    partial = [row for row in rows if row["confidence"] == "PARTIAL"]
    score = 30.0 + min(len(available), 10) * 4.0 + min(len(strong), 5) * 4.0 + min(len(partial), 5) * 2.0
    return {
        "capability": "dynamic_canslim_confidence",
        "score": clamp(score),
        "status": "CANSLIM_DYNAMIC" if available else "WAIT_CANSLIM_DATA",
        "candidate_count": len(candidates),
        "available_count": len(available),
        "strong_count": len(strong),
        "partial_count": len(partial),
        "free_data_only": payload.get("free_data_only"),
        "top_canslim": rows[:max(1, int(top_limit or 5))],
        "next_action": "Usar CANSLIM como boost/degradacion dinamica, no como input manual.",
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_control_panel(runtime: dict[str, Any], capabilities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    foundation = runtime.get("foundation_health") if isinstance(runtime.get("foundation_health"), dict) else {}
    radar = runtime.get("daily_radar") if isinstance(runtime.get("daily_radar"), dict) else {}
    readiness = runtime.get("market_open_readiness") if isinstance(runtime.get("market_open_readiness"), dict) else {}
    scores = [safe_float(item.get("score"), 0) or 0 for item in capabilities.values()]
    overall = round(sum(scores) / len(scores), 2) if scores else 0.0
    blockers = []
    for key, item in capabilities.items():
        if item.get("status") not in {"READY", "CALIBRATABLE", "RANKING_AVAILABLE", "CONTRACT_RANKING_AVAILABLE", "CANSLIM_DYNAMIC"}:
            blockers.append(f"{key}:{item.get('status')}")
    return {
        "capability": "operator_control_panel",
        "score": clamp(overall),
        "status": status_from_score(overall),
        "overall_edge_score": clamp(overall),
        "daily_radar_status": radar.get("status"),
        "foundation_status": foundation.get("status") or foundation.get("health_status"),
        "market_open_readiness": readiness.get("status") or readiness.get("readiness"),
        "capability_scores": {key: item.get("score") for key, item in capabilities.items()},
        "blockers": blockers,
        "dashboard_routes": [
            "/v32_operational_edge",
            "/v32_operational_edge_dashboard",
            "/v32_operator_daily_summary",
            "/v32_strategy_performance_dashboard",
            "/v32_operator_tracking_status",
        ],
        "next_action": "Revisar blockers y top_opportunities antes de cualquier cambio operacional.",
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_post_mortem(runtime: dict[str, Any], raw_outcomes: list[dict[str, Any]], alert_audit: dict[str, Any]) -> dict[str, Any]:
    events = list_from_payload(runtime.get("operator_events"), ["events", "rows", "items"])
    closed_today = [
        item for item in raw_outcomes
        if safe_upper(item.get("outcome")) in CLOSED_OUTCOMES
    ]
    audit_summary = alert_audit.get("summary") if isinstance(alert_audit.get("summary"), dict) else {}
    missing_actions = []
    if safe_int(audit_summary.get("closed_outcome_count")) < 30:
        missing_actions.append("ACCUMULATE_30_COMPLETE_OUTCOMES")
    if not closed_today:
        missing_actions.append("RUN_POST_CLOSE_OUTCOME_REVIEW")
    if safe_int(audit_summary.get("entry_ready_count")) and not closed_today:
        missing_actions.append("MATCH_ENTRY_READY_TO_PAPER_OUTCOMES")
    score = 35.0
    if events:
        score += 20.0
    if closed_today:
        score += 25.0
    if alert_audit:
        score += 20.0
    return {
        "capability": "automatic_post_mortem",
        "score": clamp(score),
        "status": "POST_MORTEM_READY" if alert_audit else "WAIT_AUDIT_INPUTS",
        "operator_event_count": len(events),
        "closed_outcome_count": len(closed_today),
        "audit_decision_count": audit_summary.get("decision_count"),
        "audit_entry_ready_count": audit_summary.get("entry_ready_count"),
        "required_after_close_actions": missing_actions,
        "next_action": "Despues del cierre, ejecutar outcomes y revisar missed_opportunity_review.",
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_operational_edge_report(
    runtime_dir: Path,
    *,
    generated_at: str | None = None,
    recent_days: int = 14,
    top_limit: int = 5,
) -> dict[str, Any]:
    runtime = load_runtime(Path(runtime_dir))
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    decisions, normalized_outcomes, source_files = alert_opportunity_audit.load_runtime_inputs(Path(runtime_dir))
    raw_outcomes = list_from_payload(runtime.get("outcomes_journal"), ["outcomes", "rows", "items"])
    if not raw_outcomes and isinstance(runtime.get("outcomes_journal"), list):
        raw_outcomes = [item for item in runtime.get("outcomes_journal") if isinstance(item, dict)]
    alert_audit = runtime.get("alert_audit")
    if not isinstance(alert_audit, dict) or not alert_audit:
        alert_audit = alert_opportunity_audit.build_alert_opportunity_audit(Path(runtime_dir), generated_at=generated_at, recent_days=recent_days)

    capabilities: dict[str, dict[str, Any]] = {
        "market_confirmation": build_market_confirmation(runtime),
        "score_calibration": build_score_calibration(decisions, raw_outcomes),
        "institutional_ranking": build_institutional_ranking(decisions, top_limit),
        "option_optimizer": build_option_optimizer(runtime, top_limit),
        "canslim_confidence": build_canslim(runtime, top_limit),
        "post_mortem": build_post_mortem(runtime, raw_outcomes, alert_audit),
    }
    capabilities["control_panel"] = build_control_panel(runtime, capabilities)
    scores = [safe_float(item.get("score"), 0) or 0 for item in capabilities.values()]
    overall = round(sum(scores) / len(scores), 2) if scores else 0.0
    top_blockers = []
    for key, item in capabilities.items():
        if item.get("status") not in {"READY", "CALIBRATABLE", "RANKING_AVAILABLE", "CONTRACT_RANKING_AVAILABLE", "CANSLIM_DYNAMIC", "POST_MORTEM_READY"}:
            top_blockers.append({"capability": key, "status": item.get("status"), "next_action": item.get("next_action")})

    return {
        "engine": "V32_OPERATIONAL_EDGE",
        "operational_edge_version": OPERATIONAL_EDGE_VERSION,
        "target": TOP_SYSTEM_TARGET,
        "generated_at": generated_at,
        "runtime_dir": str(Path(runtime_dir)),
        "overall_edge_score": clamp(overall),
        "overall_status": status_from_score(overall, ready_at=82.0, review_at=62.0),
        "summary": {
            "capability_count": len(capabilities),
            "decision_count": len(decisions),
            "outcome_count": len(normalized_outcomes),
            "source_files_found": source_files,
            "top_blockers": top_blockers[:7],
            "best_opportunities": (capabilities["institutional_ranking"].get("top_opportunities") or [])[:top_limit],
            "best_contracts": (capabilities["option_optimizer"].get("best_contracts") or [])[:top_limit],
            "top_canslim": (capabilities["canslim_confidence"].get("top_canslim") or [])[:top_limit],
        },
        "capabilities": capabilities,
        "recommended_sequence": [
            "Confirmar eventos reales TradingView en mercado abierto.",
            "Mantener el ranking institucional como shortlist maxima.",
            "Usar option_optimizer antes de pedir mas cadenas IBKR.",
            "Registrar MFE/MAE/PnL R en cada outcome para calibrar score.",
            "Ejecutar post-mortem al cierre antes de cambiar parametros.",
        ],
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
