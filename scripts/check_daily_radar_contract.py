#!/usr/bin/env python3
"""Guard the GPT daily radar contract and WAIT_MARKET answer policy."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_daily_radar_guard", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    app = load_app_module()

    master = {
        "path": "runtime/test_master_snapshot.json",
        "rows": [{"ticker": "AAPL"}, {"ticker": "MSFT"}],
        "technical": {"AAPL": {"score": 80}},
        "market": {"label": "LOCAL_TEST"},
    }
    decisions = [
        {"ticker": "AAPL", "final_state": "WAIT_MARKET_OPEN"},
        {"ticker": "MSFT", "final_state": "WAIT_MARKET"},
    ]
    app._v31_runtime_file_summary = lambda: {
        "runtime_dir_exists": True,
        "file_count": 1,
        "newest_file": "test_master_snapshot.json",
        "newest_age_minutes": 1,
        "files": [],
    }
    diagnostics = app._v31_data_readiness_diagnostics(master, decisions)
    require(diagnostics.get("status") == "READY_FOR_DECISION_REVIEW", diagnostics)
    require(diagnostics.get("all_wait_market") is True, diagnostics)
    require(diagnostics.get("wait_market_like_count") == 2, diagnostics)
    require(diagnostics.get("operational_readiness") == "WAIT_MARKET_WINDOW", diagnostics)
    require(diagnostics.get("safe_to_invent_opportunities") is False, diagnostics)
    require(diagnostics.get("execution_authorized") is False, diagnostics)
    require(any("WAIT_MARKET" in action for action in diagnostics.get("next_required_actions", [])), diagnostics)

    rankings = {
        "summary": {
            "decisions_evaluated": 2,
            "top_manual_review": 0,
            "watchlist": 2,
            "blocked": 0,
            "research_only": 0,
        }
    }
    guidance = app._v31_gpt_daily_answer_guidance(rankings, diagnostics)
    require(guidance.get("must_call_action_first") is True, guidance)
    require(guidance.get("manual_review_only") is True, guidance)
    require(guidance.get("execution_authorized") is False, guidance)
    require("ventana operativa confiable" in guidance.get("lead_message", ""), guidance)
    require("when_wait_market" in guidance, guidance)
    require(
        "usar Web Search para inventar oportunidades" in guidance["when_wait_market"].get("do_not_do", []),
        guidance,
    )

    compact_payload = app._v31_gpt_compact_daily_payload(
        {
            "engine": "V31_DAILY_STRATEGY_RANKING",
            "ranking_version": "test",
            "score_version": "test",
            "generated_at": "2026-06-24T00:00:00+00:00",
            "summary": {"decisions_evaluated": 2, "top_manual_review": 1, "watchlist": 0, "blocked": 1, "research_only": 0},
            "top_manual_review": [
                {
                    "ticker": "AAPL",
                    "strategy": "NAKED_PUT",
                    "final_state": "ENTRY_READY",
                    "ranking_score": 95,
                    "selected_contract": {
                        "strike": 180,
                        "expiration": "2026-07-17",
                        "dte": 23,
                        "bid": 1.2,
                        "ask": 1.3,
                        "mid": 1.25,
                        "spread": 0.1,
                        "spread_pct": 8,
                        "delta": -0.28,
                    },
                }
            ],
            "watchlist": [],
            "blocked": [
                {
                    "ticker": "MSFT",
                    "strategy": "NAKED_PUT",
                    "final_state": "WAIT_OPTIONS_DATA",
                    "main_blocker": "WAIT_OPTIONS_DATA",
                    "required_missing_fields": ["bid", "ask", "delta"],
                }
            ],
            "research_only": [],
            "all_ranked": [],
        },
        diagnostics,
    )
    require(compact_payload.get("engine") == "V31_DAILY_RECOMMENDATION_ENGINE", compact_payload)
    require(len(compact_payload.get("top_recommendations") or []) == 1, compact_payload)
    require(len(compact_payload.get("blocked_or_waiting") or []) == 1, compact_payload)
    require(compact_payload.get("execution_authorized") is False, compact_payload)
    require(compact_payload.get("not_order_instruction") is True, compact_payload)

    app._v31_daily_rankings = lambda tickers=None: {
        "engine": "V31_DAILY_STRATEGY_RANKING",
        "ranking_version": "test",
        "score_version": "test",
        "generated_at": "2026-06-24T00:00:00+00:00",
        "summary": {"decisions_evaluated": 2, "top_manual_review": 0, "watchlist": 0, "blocked": 2, "research_only": 0},
        "top_manual_review": [],
        "watchlist": [],
        "blocked": [
            {
                "ticker": "AAPL",
                "strategy": "NAKED_PUT",
                "final_state": "WAIT_MARKET",
                "main_blocker": "WAIT_MARKET",
                "required_missing_fields": [],
            },
            {
                "ticker": "MSFT",
                "strategy": "NAKED_PUT",
                "final_state": "WAIT_OPTIONS_DATA",
                "main_blocker": "WAIT_OPTIONS_DATA",
                "required_missing_fields": ["bid", "ask", "delta"],
            },
        ],
        "research_only": [],
        "all_ranked": [],
    }
    app._v31_data_readiness_diagnostics = lambda master=None, decisions=None: diagnostics
    daily_now = app._v31_daily_now_answer(limit=2)
    require(daily_now.get("response_mode") == "copy_answer_to_user_exactly", daily_now)
    require(daily_now.get("answer_to_user"), daily_now)
    require("no autoriza ordenes" in daily_now.get("first_line", "").lower(), daily_now)
    require(daily_now.get("execution_authorized") is False, daily_now)
    require(daily_now.get("not_order_instruction") is True, daily_now)

    print("Validated GPT daily radar contract and WAIT_MARKET answer policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
