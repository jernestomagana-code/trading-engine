import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_regime_policy


class StrategyRegimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = strategy_regime_policy.load_regime_policy(
            ROOT / "config" / "strategy_regime_policy_v1.json"
        )

    def test_required_regimes_and_promotion_policy_are_manual_only(self):
        summary = strategy_regime_policy.regime_policy_summary(self.policy)

        self.assertEqual(summary["regime_policy_version"], "strategy_regime_policy_v1")
        self.assertIn("BULLISH_LOW_VOL", summary["market_regimes"])
        self.assertIn("HIGH_VOL_EVENT_RISK", summary["market_regimes"])
        self.assertTrue(summary["parameter_matrix_available"])
        self.assertIn("CASH_SECURED_PUT", summary["strategy_parameter_coverage"]["BULLISH_LOW_VOL"])
        self.assertIn("INTRADAY_INDEX_FUTURES", summary["strategy_parameter_coverage"]["INTRADAY_TREND"])
        self.assertEqual(summary["research_promotion_policy"]["minimum_closed_outcomes"], 30)
        self.assertIn("UNDEFINED_MAX_LOSS", summary["research_promotion_policy"]["blocked_if_any"])
        self.assertTrue(summary["manual_review_required"])
        self.assertTrue(summary["not_order_instruction"])
        self.assertFalse(summary["execution_authorized"])

    def test_regime_overlay_blocks_intraday_futures_in_high_event_risk(self):
        overlay = strategy_regime_policy.regime_overlay(
            "INTRADAY_INDEX_FUTURES",
            "HIGH_VOL_EVENT_RISK",
            self.policy,
        )

        self.assertEqual(overlay["regime_state"], "REGIME_BLOCKED")
        self.assertIn("EVENT_RISK_REVIEWED", overlay["required_confirmations"])
        self.assertFalse(overlay["execution_authorized"])

    def test_regime_overlay_aligns_cash_secured_put_in_bullish_low_vol(self):
        overlay = strategy_regime_policy.regime_overlay(
            "NAKED_PUT",
            "BULLISH_LOW_VOL",
            self.policy,
        )

        self.assertEqual(overlay["strategy_id"], "CASH_SECURED_PUT")
        self.assertEqual(overlay["regime_state"], "REGIME_ALIGNED")
        self.assertIn("cash_secured_put", overlay["parameter_bias"])
        self.assertEqual(overlay["parameter_guidance_state"], "GUIDANCE_AVAILABLE")
        self.assertEqual(overlay["strategy_parameters"]["priority"], "PRIMARY")
        self.assertEqual(overlay["strategy_parameters"]["preferred_abs_delta_max"], 0.2)
        self.assertEqual(overlay["strategy_parameters"]["preferred_dte_min"], 30)
        self.assertEqual(overlay["global_parameters"]["minimum_decision_score"], 70)
        self.assertTrue(overlay["not_order_instruction"])

    def test_regime_overlay_exposes_research_only_iron_condor_parameters(self):
        overlay = strategy_regime_policy.regime_overlay(
            "IRON_CONDOR",
            "NEUTRAL_RANGE",
            self.policy,
        )

        self.assertEqual(overlay["regime_state"], "REGIME_CAUTION")
        self.assertEqual(overlay["strategy_parameters"]["priority"], "RESEARCH_ONLY")
        self.assertEqual(overlay["strategy_parameters"]["preferred_short_abs_delta_max"], 0.18)
        self.assertIn("MISSING_OUTCOME_METRICS", overlay["strategy_parameters"]["avoid_if"])
        self.assertFalse(overlay["execution_authorized"])

    def test_research_promotion_requires_outcomes_regimes_and_no_hard_blockers(self):
        blocked = strategy_regime_policy.promotion_review(
            "IRON_CONDOR",
            {
                "closed_outcomes": 12,
                "distinct_market_regimes": 2,
                "expectancy_r": 0.2,
                "max_sample_mae_r": -1.5,
                "known_blockers": ["MISSING_EXIT_PLAYBOOK"],
            },
            self.policy,
        )

        self.assertFalse(blocked["promotion_ready"])
        self.assertIn("INSUFFICIENT_CLOSED_OUTCOMES", blocked["promotion_blockers"])
        self.assertIn("INSUFFICIENT_REGIME_COVERAGE", blocked["promotion_blockers"])
        self.assertIn("MISSING_EXIT_PLAYBOOK", blocked["promotion_blockers"])
        self.assertFalse(blocked["execution_authorized"])

        ready = strategy_regime_policy.promotion_review(
            "IRON_CONDOR",
            {
                "closed_outcomes": 35,
                "distinct_market_regimes": 3,
                "expectancy_r": 0.25,
                "max_sample_mae_r": -1.0,
                "known_blockers": [],
            },
            self.policy,
        )

        self.assertTrue(ready["promotion_ready"])
        self.assertEqual(ready["promotion_blockers"], [])
        self.assertTrue(ready["requires_version_bump"])


if __name__ == "__main__":
    unittest.main()
