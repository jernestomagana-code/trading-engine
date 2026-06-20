import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_registry


class StrategyRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = strategy_registry.load_registry(ROOT / "config" / "strategy_registry_v1.json")

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


if __name__ == "__main__":
    unittest.main()
