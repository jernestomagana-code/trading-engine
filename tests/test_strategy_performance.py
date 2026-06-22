import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_performance


class StrategyPerformanceTests(unittest.TestCase):
    def test_report_groups_outcomes_by_regime_and_parameter_review(self):
        outcomes = [
            {
                "strategy": "CASH_SECURED_PUT",
                "ticker": "QQQ",
                "outcome": "WIN",
                "pnl_r": 0.6,
                "mfe_r": 0.8,
                "mae_r": -0.2,
                "market_regime": "BULLISH_LOW_VOL",
                "parameter_review_status": "PASS",
            },
            {
                "strategy": "CASH_SECURED_PUT",
                "ticker": "AAPL",
                "outcome": "LOSS",
                "pnl_r": -1.0,
                "mfe_r": 0.1,
                "mae_r": -1.2,
                "market_regime": "HIGH_VOL_EVENT_RISK",
                "parameter_review_status": "REVIEW_REQUIRED",
            },
            {
                "strategy": "COVERED_CALL",
                "ticker": "MSFT",
                "outcome": "PENDING",
                "market_regime": "NEUTRAL_RANGE",
                "parameter_review_status": "PASS",
            },
        ]

        report = strategy_performance.strategy_performance_report([], outcomes)

        self.assertEqual(report["strategy_performance_version"], "strategy_performance_v1")
        self.assertEqual(report["summary"]["strategy_regime_group_count"], 3)
        self.assertEqual(report["summary"]["parameter_review_group_count"], 2)
        self.assertFalse(report["execution_authorized"])

        regime_groups = {item["group"]: item for item in report["strategy_regime_performance"]}
        self.assertEqual(regime_groups["CASH_SECURED_PUT::BULLISH_LOW_VOL"]["closed_outcomes"], 1)
        self.assertEqual(regime_groups["CASH_SECURED_PUT::BULLISH_LOW_VOL"]["win_rate"], 100.0)
        self.assertEqual(regime_groups["CASH_SECURED_PUT::HIGH_VOL_EVENT_RISK"]["expectancy_r"], -1.0)

        review_groups = {item["group"]: item for item in report["parameter_review_performance"]}
        self.assertEqual(review_groups["PASS"]["total_outcomes"], 2)
        self.assertEqual(review_groups["PASS"]["closed_outcomes"], 1)
        self.assertEqual(review_groups["PASS"]["expectancy_r"], 0.6)
        self.assertEqual(review_groups["REVIEW_REQUIRED"]["closed_outcomes"], 1)
        self.assertEqual(review_groups["REVIEW_REQUIRED"]["expectancy_r"], -1.0)

        strategy_rows = {item["strategy"]: item for item in report["strategies"]}
        cash_secured = strategy_rows["CASH_SECURED_PUT"]
        by_regime = {item["group"]: item for item in cash_secured["by_market_regime"]}
        self.assertIn("BULLISH_LOW_VOL", by_regime)
        self.assertIn("HIGH_VOL_EVENT_RISK", by_regime)
        by_review = {item["group"]: item for item in cash_secured["by_parameter_review_status"]}
        self.assertEqual(by_review["PASS"]["expectancy_r"], 0.6)
        self.assertTrue(cash_secured["not_order_instruction"])


if __name__ == "__main__":
    unittest.main()
