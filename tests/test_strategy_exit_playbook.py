import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_exit_playbook


class StrategyExitPlaybookTests(unittest.TestCase):
    def setUp(self):
        self.playbook = strategy_exit_playbook.load_exit_playbook(
            ROOT / "config" / "strategy_exit_playbook_v1.json"
        )

    def test_required_exit_strategies_are_manual_review_only(self):
        summary = strategy_exit_playbook.exit_playbook_summary(self.playbook)

        self.assertEqual(summary["exit_playbook_version"], "strategy_exit_playbook_v1")
        self.assertIn("CASH_SECURED_PUT", summary["active_exit_strategies"])
        self.assertIn("COVERED_CALL", summary["active_exit_strategies"])
        self.assertIn("TAKE_PROFIT_REVIEW", summary["canonical_exit_states"])
        self.assertIn("ROLL_REVIEW", summary["canonical_exit_states"])
        self.assertIn("ASSIGNMENT_REVIEW", summary["canonical_exit_states"])
        self.assertTrue(summary["manual_review_required"])
        self.assertTrue(summary["not_order_instruction"])
        self.assertFalse(summary["execution_authorized"])

    def test_aliases_map_to_canonical_exit_strategy(self):
        strategy = strategy_exit_playbook.get_exit_strategy(self.playbook, "short_put")

        self.assertIsNotNone(strategy)
        self.assertEqual(strategy["id"], "CASH_SECURED_PUT")
        self.assertEqual(strategy["status"], "ACTIVE_MANUAL_REVIEW")

    def test_exit_overlay_requires_position_status_and_never_authorizes_execution(self):
        overlay = strategy_exit_playbook.exit_overlay(
            {
                "ticker": "AAPL",
                "strategy": "COVERED_CALL",
                "exit_state": "ROLL_REVIEW",
                "blockers": [],
            },
            self.playbook,
        )

        self.assertEqual(overlay["strategy_id"], "COVERED_CALL")
        self.assertEqual(overlay["exit_state"], "ROLL_REVIEW")
        self.assertIn("POSITION_STATUS_REQUIRED", overlay["exit_blockers"])
        self.assertIn("premium_capture_pct", overlay["outcome_metrics"])
        self.assertTrue(overlay["manual_review_required"])
        self.assertTrue(overlay["not_order_instruction"])
        self.assertFalse(overlay["execution_authorized"])

    def test_closed_position_maps_to_no_position(self):
        overlay = strategy_exit_playbook.exit_overlay(
            {
                "ticker": "AAPL",
                "strategy": "CASH_SECURED_PUT",
                "position_open": False,
                "exit_state": "MONITOR",
            },
            self.playbook,
        )

        self.assertEqual(overlay["exit_state"], "NO_POSITION")
        self.assertFalse(overlay["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
