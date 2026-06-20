#!/usr/bin/env python3
"""Validate Stock Ultimus strategy registry and playbook."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_registry


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

    print("Strategy registry validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
