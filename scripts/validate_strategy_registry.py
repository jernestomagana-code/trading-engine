#!/usr/bin/env python3
"""Validate Stock Ultimus strategy registry and playbook."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_registry
import strategy_input_contracts
import strategy_exit_playbook
import strategy_regime_policy


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

    input_contracts = strategy_input_contracts.load_input_contracts(
        ROOT / strategy_input_contracts.DEFAULT_INPUT_CONTRACT_PATH
    )
    input_summary = strategy_input_contracts.input_contract_summary(input_contracts)
    require(
        input_summary["tradingview_not_required_for_candidate_generation"] is True,
        "candidate generation must not depend exclusively on TradingView",
    )
    require(
        "CASH_SECURED_PUT" in input_summary["local_or_ibkr_fallback_available"],
        "cash secured puts need local/IBKR fallback",
    )
    require(
        "INTRADAY_INDEX_FUTURES" in input_summary["tradingview_preferred_but_not_exclusive"],
        "futures should prefer but not require TradingView",
    )
    csp_input = strategy_input_contracts.get_input_contract(input_contracts, "NAKED_PUT")
    require(csp_input["state_when_missing"]["technical_confirmation"] == "WAIT_TECHNICAL", "missing technical must wait technical")
    require(csp_input["state_when_missing"]["candidate_contract"] == "WAIT_OPTIONS_DATA", "missing contract must wait options data")
    require(csp_input["execution_authorized"] is False, "input contracts must never authorize execution")

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

    regime_policy = strategy_regime_policy.load_regime_policy(
        ROOT / strategy_regime_policy.DEFAULT_REGIME_POLICY_PATH
    )
    regime_summary = strategy_regime_policy.regime_policy_summary(regime_policy)
    require("BULLISH_LOW_VOL" in regime_summary["market_regimes"], "bullish low vol regime missing")
    require("HIGH_VOL_EVENT_RISK" in regime_summary["market_regimes"], "high vol event risk regime missing")
    require(
        regime_summary["research_promotion_policy"]["minimum_closed_outcomes"] >= 30,
        "research promotion needs closed outcome minimum",
    )
    require(regime_summary["execution_authorized"] is False, "regime policy must never authorize execution")

    regime_doc = ROOT / "referencias/strategy_regime_policy_v1.md"
    require(regime_doc.exists(), "strategy regime policy doc missing")
    regime_text = regime_doc.read_text()
    require("UNDEFINED_MAX_LOSS" in regime_text, "regime policy must document hard promotion blockers")
    require("WAIT_OPTIONS_DATA" in regime_text, "regime policy must preserve WAIT_OPTIONS_DATA")

    print("Strategy registry validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
