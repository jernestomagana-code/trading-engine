#!/usr/bin/env python3
"""Guard the GPT daily radar contract and WAIT_MARKET answer policy."""

from __future__ import annotations

import ast
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
    wanted = {"_v31_data_readiness_payload", "_v31_gpt_daily_answer_guidance"}
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

    print("Validated GPT daily radar contract and WAIT_MARKET answer policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
