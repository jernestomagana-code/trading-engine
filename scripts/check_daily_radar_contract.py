#!/usr/bin/env python3
"""Guard the GPT daily radar contract and WAIT_MARKET answer policy."""

from __future__ import annotations

import ast
import math
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_app_module():
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    app_path = ROOT / "app" / "main.py"
    module = types.ModuleType("stock_ultimus_app_for_daily_radar_guard")
    module.__dict__["__file__"] = str(app_path)
    source = app_path.read_text()
    parsed = ast.parse(source)
    wanted = {
        "_v31_data_readiness_payload",
        "_v31_gpt_daily_answer_guidance",
        "_v31_gpt_compact_contract",
        "_v31_gpt_compact_daily_item",
        "_v31_gpt_compact_daily_payload",
        "_v31_first_blocked_check_detail",
        "_v31_primary_block_reason",
        "_v31_blocker_cause_bucket",
        "_v31_blocker_cause_summary",
        "_v31_command_center_payload",
        "_v29_safe_float",
        "_v29_spread_metrics",
        "_v29_derived_option_score",
        "_v29_quality_gate",
    }
    selected = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    extracted = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(extracted)
    exec(compile(extracted, str(app_path), "exec"), module.__dict__)
    return module


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    app = load_app_module()
    app._v29_now = lambda: "2026-06-24T00:00:00+00:00"
    app._v29_math = math
    app._V29_MIN_BID = 0.05
    app._V29_MIN_ASK = 0.05
    app._V29_MIN_OPTION_SCORE = 70
    app._V29_MAX_SPREAD_PCT = 18.0
    app._V29_MAX_ABS_SPREAD = 0.35

    derived_quality = app._v29_quality_gate({
        "ticker": "NVDA",
        "strategy": "NAKED_PUT",
        "strike": 118,
        "expiration": "2026-07-17",
        "dte": 35,
        "bid": 1.32,
        "ask": 1.49,
        "mid": 1.405,
        "delta": -0.26,
    })
    require(derived_quality["option_score"] >= app._V29_MIN_OPTION_SCORE, derived_quality)
    require(derived_quality["option_score_source"] == "DERIVED_FROM_CONTRACT_FIELDS", derived_quality)
    require("option_score" not in derived_quality["missing"], derived_quality)
    require(derived_quality["executable"] is True, derived_quality)

    wide_quality = app._v29_quality_gate({
        "ticker": "WIDE",
        "strategy": "NAKED_PUT",
        "strike": 100,
        "expiration": "2026-07-17",
        "dte": 35,
        "bid": 1.0,
        "ask": 1.7,
        "delta": -0.25,
    })
    require("spread_too_wide" in wide_quality["missing"], wide_quality)
    require(wide_quality["executable"] is False, wide_quality)
    app._v31_runtime_file_status = lambda: [
        {
            "exists": True,
            "path": "runtime/test_master_snapshot.json",
            "age_minutes": 1,
            "rows_found": 2,
            "technical_count": 1,
        }
    ]

    status = {
        "master_snapshot_available": True,
        "master_source": "runtime/test_master_snapshot.json",
        "rows_found": 2,
        "technical_count": 1,
        "technical_tickers": ["AAPL"],
        "market": {"label": "LOCAL_TEST"},
        "summary": {
            "total": 2,
            "entry_ready": 0,
            "manual_review": 0,
            "risk_blocked": 0,
            "wait_options_data": 0,
            "wait_technical": 0,
            "wait_market": 2,
            "wait_account_context": 0,
            "no_data": 0,
        },
    }
    diagnostics = app._v31_data_readiness_payload(status)
    require(diagnostics["status"] == "READY_FOR_DECISION_REVIEW", diagnostics)
    require(diagnostics["all_wait_market"] is True, diagnostics)
    require(diagnostics["wait_market_like_count"] == 2, diagnostics)
    require(diagnostics["dominant_state"] == "wait_market", diagnostics)
    require(diagnostics["dominant_state_count"] == 2, diagnostics)
    require(diagnostics["operational_readiness"] == "WAIT_MARKET_WINDOW", diagnostics)
    require(diagnostics["safe_to_invent_opportunities"] is False, diagnostics)
    require(diagnostics["execution_authorized"] is False, diagnostics)
    require(any("WAIT_MARKET" in action for action in diagnostics["next_required_actions"]), diagnostics)

    payload = {"summary": {"total": 2, "manual_review_ready": 0, "entry_ready": 0}}
    guidance = app._v31_gpt_daily_answer_guidance(payload, diagnostics)
    require(guidance["must_call_action_first"] is True, guidance)
    require(guidance["manual_review_only"] is True, guidance)
    require(guidance["execution_authorized"] is False, guidance)
    require("ventana operativa confiable" in guidance["lead_message"], guidance)
    require("when_wait_market" in guidance, guidance)

    compact = app._v31_gpt_compact_daily_payload({
        "engine": "TEST_ENGINE",
        "summary": {"total": 2, "manual_review_ready": 1, "entry_ready": 1},
        "items": [
            {
                "rank": 1,
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "final_state": "ENTRY_READY",
                "manual_review_ready": True,
                "conviction_score": 100,
                "evidence": {"options": {"contract": {"strike": 500, "bid": 1.0, "ask": 1.1}}},
                "technical": {"large": "not needed"},
            },
            {
                "rank": 2,
                "ticker": "NVDA",
                "strategy": "NAKED_PUT",
                "final_state": "WAIT_OPTIONS_DATA",
                "manual_review_ready": False,
                "main_blocker": "WAIT_OPTIONS_DATA",
                "evidence": {"options": {"contract": {"strike": 120}}},
            },
        ],
    })
    require(len(compact["top_recommendations"]) == 1, compact)
    require(compact["top_recommendations"][0]["ticker"] == "QQQ", compact)
    require(len(compact["blocked_or_waiting"]) == 1, compact)
    require(compact["blocked_or_waiting"][0]["ticker"] == "NVDA", compact)
    require("technical" not in compact["items"][0], compact)
    require(compact["execution_authorized"] is False, compact)

    app._v31_daily_recommendations_payload = lambda: {
        "engine": "TEST_ENGINE",
        "generated_at": "2026-06-24T00:00:00+00:00",
        "status": "OK",
        "summary": {"total": 2, "manual_review_ready": 1, "entry_ready": 1},
        "data_readiness": diagnostics,
        "source_status": {"master_source": "runtime/test_master_snapshot.json", "rows_found": 2, "technical_count": 1},
        "items": [
            {
                "rank": 1,
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "final_state": "ENTRY_READY",
                "manual_review_ready": True,
                "conviction_score": 100,
                "evidence": {"options": {"contract": {"strike": 500, "bid": 1.0, "ask": 1.1}}},
            },
            {
                "rank": 2,
                "ticker": "NVDA",
                "strategy": "NAKED_PUT",
                "final_state": "WAIT_OPTIONS_DATA",
                "manual_review_ready": False,
                "main_blocker": "WAIT_OPTIONS_DATA",
            },
        ],
    }
    command_center = app._v31_command_center_payload()
    require(command_center["engine"] == "V31_COMMAND_CENTER", command_center)
    require(command_center["summary"]["entry_ready"] == 1, command_center)
    require(command_center["summary"]["blocked_or_waiting"] == 1, command_center)
    require(command_center["execution_authorized"] is False, command_center)
    require(command_center["not_order_instruction"] is True, command_center)

    print("Validated GPT daily radar contract and WAIT_MARKET answer policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
