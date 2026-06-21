#!/usr/bin/env python3
"""Validate Stock Ultimus strategy registry and playbook."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_registry
import strategy_exit_playbook


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    registry = strategy_registry.load_registry(ROOT / strategy_registry.DEFAULT_REGISTRY_PATH)
    summary = strategy_registry.playbook_summary(registry)
    require("CASH_SECURED_PUT" in summary["active_manual_review"], "cash secured put must be active")
    require("COVERED_CALL" in summary["active_manual_review"], "covered call must be active")
    require("INTRADAY_INDEX_FUTURES" in summary["active_manual_review"], "intraday futures must be active")
    require("IRON_CONDOR" in summary["research_only"], "iron condor must remain research-only")
    require("CANSLIM_GROWTH_FILTER" in summary["filters"], "CANSLIM filter missing")

    overlay = strategy_registry.recommendation_overlay(
        {"strategy": "IRON_CONDOR", "final_state": "ENTRY_READY", "blockers": []},
        registry,
    )
    require(overlay["research_only"] is True, "research-only overlay missing")
    require("RESEARCH_ONLY" in overlay["strategy_blockers"], "research-only blocker missing")
    require(overlay["not_order_instruction"] is True, "no-order guard missing")

    playbook = ROOT / "referencias/strategy_playbook_v1.md"
    require(playbook.exists(), "strategy playbook missing")
    text = playbook.read_text()
    require("WAIT_OPTIONS_DATA" in text, "playbook must preserve WAIT_OPTIONS_DATA")
    require("ENTRY_READY" in text and "revision manual" in text.lower(), "playbook must define manual review semantics")

    exit_playbook = strategy_exit_playbook.load_exit_playbook(
        ROOT / strategy_exit_playbook.DEFAULT_EXIT_PLAYBOOK_PATH
    )
    exit_summary = strategy_exit_playbook.exit_playbook_summary(exit_playbook)
    require("CASH_SECURED_PUT" in exit_summary["active_exit_strategies"], "cash secured put exit rules missing")
    require("COVERED_CALL" in exit_summary["active_exit_strategies"], "covered call exit rules missing")
    require("ROLL_REVIEW" in exit_summary["canonical_exit_states"], "roll review exit state missing")
    require(exit_summary["execution_authorized"] is False, "exit playbook must never authorize execution")

    exit_doc = ROOT / "referencias/strategy_exit_playbook_v1.md"
    require(exit_doc.exists(), "strategy exit playbook doc missing")
    exit_text = exit_doc.read_text()
    require("TAKE_PROFIT_REVIEW" in exit_text, "exit playbook must define take-profit review")
    require("rollea" in exit_text.lower() or "roll" in exit_text.lower(), "exit playbook must define roll review")

    print("Strategy registry validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
