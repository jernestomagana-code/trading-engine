#!/usr/bin/env python3
"""Guard canonical V31-style states on newer legacy-compatible paths."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_v31_guard", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")

    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def option_row(**overrides):
    row = {
        "ticker": "AAPL",
        "strategy": "NAKED_PUT",
        "strategy_hint": "NAKED_PUT",
        "decision": "ENTRY",
        "score": 90,
        "data_quality": "FULL_WITH_GREEKS",
        "can_operate": True,
        "missing_confirmations": [],
        "volume": 150,
        "open_interest": 500,
    }
    row.update(overrides)
    return row


def technical(**overrides):
    data = {
        "ticker": "AAPL",
        "trend": "BULLISH",
        "score": 85,
        "rsi": 50,
        "adx": 18,
        "event_risk": False,
        "earnings_soon": False,
    }
    data.update(overrides)
    return data


def market(is_open=True):
    return {
        "label": "TEST",
        "is_regular_market_open": is_open,
        "options_bidask_expected": is_open,
        "raw": {},
    }


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def validate_decision_contract_schema_cases(app):
    fixture_path = ROOT / "fixtures" / "v31" / "decision_contract_schema_cases.json"
    fixture = json.loads(fixture_path.read_text())
    require(
        fixture.get("fixture_version") == "v31_decision_contract_schema_cases_v1",
        f"unexpected V31 contract fixture version: {fixture}",
    )
    for case in fixture.get("cases") or []:
        decision = app._v31_decision_contract(case.get("input") or {})
        expected = case.get("expected") or {}
        selected_contract = decision.get("selected_contract") or {}
        require(
            decision.get("contract_schema_version") == expected.get("contract_schema_version"),
            f"{case.get('name')} wrong contract schema version: {decision}",
        )
        require(
            selected_contract.get("selected_contract_version") == expected.get("selected_contract_version"),
            f"{case.get('name')} wrong selected contract version: {decision}",
        )
        for key in ["final_state", "main_blocker", "ready_for_manual_review", "execution_authorized"]:
            if key in expected:
                require(
                    decision.get(key) == expected.get(key),
                    f"{case.get('name')} wrong {key}: expected {expected.get(key)}, got {decision.get(key)} in {decision}",
                )


def main() -> int:
    app = load_app_module()
    fresh_now = app._v29_now()
    validate_decision_contract_schema_cases(app)

    app._v27_save_json_file = lambda *args, **kwargs: None
    app._v27_get_master_snapshot = lambda: {"source": "test"}
    app._v27_extract_option_rows = lambda master: [option_row()]
    app._v27_load_technical_map = lambda: ({"AAPL": technical(event_risk=True)}, [])
    app._v27_market_hours = lambda master: market(True)
    v27 = app._v27_decide_for_ticker("AAPL")
    require(v27.get("final_state") == "RISK_BLOCKED", f"v27 should risk-block event risk, got {v27}")
    require(v27.get("main_blocker") == "EVENT_RISK_ACTIVE", f"v27 wrong blocker: {v27}")

    app._v271_find_best_runtime_snapshot = lambda: ({}, "test-runtime", {"best_candidates": []})
    app._v271_rows_from_anywhere = lambda data: [option_row()]
    app._v271_technical_from_anywhere = lambda data: {"AAPL": None}
    app._v27_load_technical_map = lambda: ({}, [])
    app._v271_market_from_anywhere = lambda data: market(True)
    v271 = app._v271_decide_for_ticker("AAPL")
    require(v271.get("final_state") == "WAIT_TECHNICAL", f"v27.1 should use canonical WAIT_TECHNICAL, got {v271}")

    app._v28_load_master = lambda: ({}, "test-master")
    app._v28_rows = lambda data: [option_row()]
    app._v28_technical_map = lambda data: {"AAPL": technical()}
    app._v28_market = lambda data: market(False)
    v28_market = app._v28_decide("AAPL")
    require(v28_market.get("final_state") == "WAIT_MARKET_OPEN", f"v28 should use WAIT_MARKET_OPEN, got {v28_market}")
    require(v28_market.get("can_operate") is False, f"v28 WAIT_MARKET_OPEN must not be operable, got {v28_market}")

    app._v28_market = lambda data: market(True)
    app._v28_rows = lambda data: [option_row(volume=10, open_interest=500)]
    v28_liquidity = app._v28_decide("AAPL")
    require(v28_liquidity.get("final_state") == "RISK_BLOCKED", f"v28 should risk-block low volume, got {v28_liquidity}")
    require(v28_liquidity.get("main_blocker") == "LOW_OPTION_VOLUME", f"v28 wrong liquidity blocker: {v28_liquidity}")

    iron_condor_entry = app._v31_decision_contract({
        "engine": "TEST",
        "decision_id": "DEC-TEST",
        "ticker": "SPY",
        "strategy": "IRON_CONDOR",
        "status": "OK",
        "final_state": "ENTRY_READY",
        "decision": "ENTRY_READY",
        "blockers": [],
        "required_missing_fields": [],
        "risk_note": "test",
        "executive_summary": "test",
    })
    require(
        iron_condor_entry.get("final_state") == "MANUAL_REVIEW",
        f"V31 registry cap should downgrade RADAR_ONLY strategy, got {iron_condor_entry}",
    )
    require(
        iron_condor_entry.get("main_blocker") == "STRATEGY_RADAR_ONLY",
        f"V31 registry cap should expose STRATEGY_RADAR_ONLY, got {iron_condor_entry}",
    )
    require(
        iron_condor_entry.get("ready_for_manual_review") is False,
        f"V31 registry-capped strategy must not be ready, got {iron_condor_entry}",
    )
    score_components = iron_condor_entry.get("score_components") or {}
    require(
        score_components.get("score_version") == "strategy_score_components_v1",
        f"V31 should expose score component version, got {score_components}",
    )
    require(
        score_components.get("ranking_label") == "RADAR_ONLY_RESEARCH",
        f"V31 registry-capped strategy should be research-ranked only, got {score_components}",
    )
    components = score_components.get("components") or {}
    for key in ["technical_fit", "option_quality", "risk_fit", "fundamental_fit", "regime_fit", "outcome_evidence", "freshness", "strategy_registry"]:
        require(key in components, f"V31 score components missing {key}: {score_components}")

    entry_ready = app._v31_decision_contract({
        "engine": "TEST",
        "decision_id": "DEC-ENTRY",
        "ticker": "AAPL",
        "strategy": "NAKED_PUT",
        "status": "OK",
        "final_state": "ENTRY_READY",
        "decision": "ENTRY_READY",
        "blockers": [],
        "required_missing_fields": [],
        "technical_score": 90,
        "technical_fit": "TECHNICAL_CONFIRMED_BY_SCORE",
        "options_score": 95,
        "risk_note": "test",
        "executive_summary": "test",
        "market": {**market(True), "generated_at": fresh_now},
        "technical": {"raw": {"received_at": fresh_now}},
        "snapshot_generated_at": fresh_now,
        "snapshot_received_at": fresh_now,
        "source_context": {
            "fundamental_canslim": {"timestamp": fresh_now, "available": True},
            "account_context": {"timestamp": fresh_now, "available": True},
        },
    })
    wait_options = app._v31_decision_contract({
        "engine": "TEST",
        "decision_id": "DEC-WAIT",
        "ticker": "MSFT",
        "strategy": "NAKED_PUT",
        "status": "OK",
        "final_state": "WAIT_OPTIONS_DATA",
        "decision": "WAIT_OPTIONS_DATA",
        "main_blocker": "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY",
        "blockers": ["MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY"],
        "required_missing_fields": ["bid", "ask"],
        "technical_score": 88,
        "technical_fit": "TECHNICAL_CONFIRMED_BY_SCORE",
        "options_score": 40,
        "risk_note": "test",
        "executive_summary": "test",
        "market": {**market(True), "generated_at": fresh_now},
        "technical": {"raw": {"received_at": fresh_now}},
        "snapshot_generated_at": fresh_now,
        "snapshot_received_at": fresh_now,
    })
    app._v31_all_decisions = lambda tickers=None: [iron_condor_entry, wait_options, entry_ready]
    daily = app._v31_daily_rankings()
    require(daily.get("ranking_version") == "strategy_daily_ranking_v1", f"V31 daily ranking version mismatch: {daily}")
    require(daily.get("summary", {}).get("top_manual_review") == 1, f"V31 daily ranking should have one top candidate: {daily}")
    require(daily.get("summary", {}).get("blocked") == 1, f"V31 daily ranking should have one blocked candidate: {daily}")
    require(daily.get("summary", {}).get("research_only") == 1, f"V31 daily ranking should have one research-only candidate: {daily}")
    require(daily.get("top_manual_review", [])[0].get("ticker") == "AAPL", f"V31 daily ranking should rank AAPL as top manual review: {daily}")
    require(daily.get("research_only", [])[0].get("main_blocker") == "STRATEGY_RADAR_ONLY", f"V31 daily ranking should keep radar-only separate: {daily}")
    freshness = entry_ready.get("freshness") or {}
    gates = freshness.get("gates") or {}
    require(
        gates.get("fundamental_canslim", {}).get("status") == "FRESH",
        f"V31 should read real fundamental/CANSLIM timestamp from source_context: {freshness}",
    )
    require(
        gates.get("account_context", {}).get("status") == "FRESH",
        f"V31 should read real account-context timestamp from source_context: {freshness}",
    )

    stale_entry = app._v31_decision_contract({
        "engine": "TEST",
        "decision_id": "DEC-STALE",
        "ticker": "NVDA",
        "strategy": "NAKED_PUT",
        "status": "OK",
        "final_state": "ENTRY_READY",
        "decision": "ENTRY_READY",
        "blockers": [],
        "required_missing_fields": [],
        "technical_score": 90,
        "technical_fit": "TECHNICAL_CONFIRMED_BY_SCORE",
        "options_score": 95,
        "risk_note": "test",
        "executive_summary": "test",
        "market": market(True),
    })
    require(
        stale_entry.get("freshness", {}).get("blocks_actionable_ranking") is True,
        f"V31 stale or missing freshness must block actionable ranking: {stale_entry}",
    )
    app._v31_all_decisions = lambda tickers=None: [stale_entry]
    stale_daily = app._v31_daily_rankings()
    require(
        stale_daily.get("summary", {}).get("top_manual_review") == 0 and stale_daily.get("summary", {}).get("watchlist") == 1,
        f"V31 stale ENTRY_READY should be watchlist, not top manual review: {stale_daily}",
    )

    print("Validated V31 canonical states, strategy registry caps, score components, freshness gates, and daily rankings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
