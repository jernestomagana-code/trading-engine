import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_registry
import strategy_input_contracts


class StrategyRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = strategy_registry.load_registry(ROOT / "config" / "strategy_registry_v1.json")
        self.input_contracts = strategy_input_contracts.load_input_contracts(
            ROOT / "config" / "strategy_input_contract_v1.json"
        )

    def test_required_strategies_are_versioned_and_manual_only(self):
        summary = strategy_registry.playbook_summary(self.registry)

        self.assertEqual(summary["registry_version"], "strategy_registry_v1")
        self.assertIn("CASH_SECURED_PUT", summary["active_manual_review"])
        self.assertIn("COVERED_CALL", summary["active_manual_review"])
        self.assertIn("INTRADAY_INDEX_FUTURES", summary["active_manual_review"])
        self.assertIn("IRON_CONDOR", summary["research_only"])
        self.assertIn("CANSLIM_GROWTH_FILTER", summary["filters"])
        self.assertTrue(summary["not_order_instruction"])
        self.assertFalse(summary["execution_authorized"])

    def test_aliases_map_to_canonical_strategy(self):
        strategy = strategy_registry.get_strategy(self.registry, "naked_put")

        self.assertIsNotNone(strategy)
        self.assertEqual(strategy["id"], "CASH_SECURED_PUT")
        self.assertEqual(strategy["status"], "ACTIVE_MANUAL_REVIEW")

    def test_option_income_strategies_expose_assignment_and_dividend_blockers(self):
        put_strategy = strategy_registry.get_strategy(self.registry, "CASH_SECURED_PUT")
        covered_call = strategy_registry.get_strategy(self.registry, "COVERED_CALL")

        self.assertIn("ASSIGNMENT_UNACCEPTABLE", put_strategy["primary_blockers"])
        self.assertIn("ASSIGNMENT_UNACCEPTABLE", covered_call["primary_blockers"])
        self.assertIn("EX_DIVIDEND_WITHIN_WINDOW", covered_call["primary_blockers"])

    def test_research_only_strategy_adds_blocker_and_never_authorizes_execution(self):
        overlay = strategy_registry.recommendation_overlay(
            {
                "ticker": "SPY",
                "strategy": "IRON_CONDOR",
                "final_state": "ENTRY_READY",
                "blockers": [],
            },
            self.registry,
        )

        self.assertTrue(overlay["research_only"])
        self.assertIn("RESEARCH_ONLY", overlay["strategy_blockers"])
        self.assertTrue(overlay["manual_review_required"])
        self.assertTrue(overlay["not_order_instruction"])
        self.assertFalse(overlay["execution_authorized"])

    def test_wait_options_data_priority_is_preserved_for_option_strategies(self):
        overlay = strategy_registry.recommendation_overlay(
            {
                "ticker": "QQQ",
                "strategy": "CASH_SECURED_PUT",
                "final_state": "WAIT_OPTIONS_DATA",
                "blockers": [],
            },
            self.registry,
        )

        self.assertIn("WAIT_OPTIONS_DATA", overlay["strategy_blockers"])
        self.assertFalse(overlay["execution_authorized"])

    def test_strategy_input_contracts_do_not_require_tradingview_for_candidate_generation(self):
        summary = strategy_input_contracts.input_contract_summary(self.input_contracts)

        self.assertEqual(summary["contract_version"], "strategy_input_contract_v1")
        self.assertTrue(summary["tradingview_not_required_for_candidate_generation"])
        self.assertIn("CASH_SECURED_PUT", summary["tradingview_optional_confirmation"])
        self.assertIn("COVERED_CALL", summary["tradingview_optional_confirmation"])
        self.assertIn("INTRADAY_INDEX_FUTURES", summary["tradingview_preferred_but_not_exclusive"])
        self.assertIn("CASH_SECURED_PUT", summary["local_or_ibkr_fallback_available"])
        self.assertIn("INTRADAY_INDEX_FUTURES", summary["local_or_ibkr_fallback_available"])
        self.assertTrue(summary["not_order_instruction"])
        self.assertFalse(summary["execution_authorized"])

    def test_cash_secured_put_contract_has_ibkr_candidate_and_local_technical_fallback(self):
        contract = strategy_input_contracts.get_input_contract(self.input_contracts, "naked_put")

        self.assertIsNotNone(contract)
        self.assertEqual(contract["strategy_id"], "CASH_SECURED_PUT")
        self.assertIn("IBKR_OPTION_CHAIN", contract["candidate_sources"])
        self.assertIn("LOCAL_TECHNICAL_ENGINE", contract["confirmation_sources"])
        self.assertIn("TRADINGVIEW_ALERT", contract["confirmation_sources"])
        self.assertEqual(contract["tradingview_dependency"], "OPTIONAL_CONFIRMATION")
        self.assertEqual(contract["state_when_missing"]["technical_confirmation"], "WAIT_TECHNICAL")
        self.assertEqual(contract["state_when_missing"]["candidate_contract"], "WAIT_OPTIONS_DATA")
        self.assertIn("Continue scanning IBKR candidates", contract["no_tradingview_alert_behavior"])

    def test_input_overlay_never_authorizes_execution(self):
        overlay = strategy_input_contracts.input_overlay("covered_call", self.input_contracts)

        self.assertEqual(overlay["strategy_id"], "COVERED_CALL")
        self.assertIn("IBKR_PORTFOLIO_POSITIONS", overlay["candidate_sources"])
        self.assertIn("LOCAL_TECHNICAL_ENGINE", overlay["confirmation_sources"])
        self.assertTrue(overlay["manual_review_required"])
        self.assertTrue(overlay["not_order_instruction"])
        self.assertFalse(overlay["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
