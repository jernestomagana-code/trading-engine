import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import strategy_performance


def complete_outcome(index=1, strategy="CASH_SECURED_PUT", outcome="WIN"):
    return {
        "outcome_id": f"OUT-{index}",
        "strategy": strategy,
        "ticker": "QQQ",
        "outcome": outcome,
        "pnl_r": 0.35 if outcome == "WIN" else -0.25,
        "mfe_r": 0.7,
        "mae_r": -0.2,
        "market_regime": "BULLISH_LOW_VOL",
        "candidate_source": "IBKR_OPTION_CHAIN",
        "confirmation_source": "TRADINGVIEW_ALERT",
        "signal_source": "TRADINGVIEW_ALERT",
        "selected_contract": {"delta": -0.2, "dte": 42, "spread_pct": 7.0, "iv": 0.32},
    }


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
                "candidate_source": "LOCAL_SCANNER",
                "confirmation_source": "TRADINGVIEW_ALERT",
                "signal_source": "TRADINGVIEW_ALERT",
                "selected_contract": {"delta": -0.18, "dte": 48, "spread_pct": 6.5, "iv": 0.31},
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
                "candidate_source": "IBKR_OPTION_CHAIN",
                "confirmation_source": "TRADINGVIEW_ALERT",
                "signal_source": "IBKR_OPTION_CHAIN",
                "selected_contract": {"delta": -0.22, "dte": 35, "spread_pct": 9.5, "iv": 0.28},
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
        self.assertEqual(report["summary"]["source_group_count"], 3)
        self.assertEqual(report["summary"]["complete_closed_outcomes"], 2)
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
        by_source = {item["group"]: item for item in cash_secured["by_source"]}
        self.assertEqual(by_source["TRADINGVIEW_ALERT"]["avg_abs_delta"], 0.18)
        self.assertEqual(by_source["IBKR_OPTION_CHAIN"]["avg_spread_pct"], 9.5)
        self.assertTrue(cash_secured["not_order_instruction"])

        review = strategy_performance.parameter_review_evidence_report(
            report,
            generated_at="2026-07-04T00:00:00+00:00",
            minimum_closed_outcomes=1,
        )
        self.assertEqual(review["parameter_review_report_version"], "parameter_review_evidence_report_v1")
        self.assertEqual(review["candidate_count"], 1)
        self.assertEqual(review["candidates"][0]["strategy"], "CASH_SECURED_PUT")
        self.assertEqual(
            review["candidates"][0]["reviewable_strategy_regimes"],
            ["CASH_SECURED_PUT::BULLISH_LOW_VOL", "CASH_SECURED_PUT::HIGH_VOL_EVENT_RISK"],
        )
        self.assertEqual(review["blocked"][0]["recommended_action"], "ACCUMULATE_COMPLETE_OUTCOMES")
        self.assertFalse(review["execution_authorized"])

    def test_outcome_completeness_blocks_parameter_changes_until_evidence_is_complete(self):
        incomplete = complete_outcome()
        incomplete.pop("confirmation_source")
        incomplete["selected_contract"].pop("iv")

        report = strategy_performance.strategy_performance_report([], [incomplete])
        completeness = report["outcome_completeness"]
        self.assertEqual(completeness["closed_outcomes"], 1)
        self.assertEqual(completeness["complete_closed_outcomes"], 0)
        self.assertEqual(completeness["missing_field_counts"]["confirmation_source"], 1)
        self.assertEqual(completeness["missing_contract_field_counts"]["iv"], 1)

        review = strategy_performance.parameter_review_evidence_report(
            report,
            minimum_closed_outcomes=1,
        )
        self.assertEqual(review["candidate_count"], 0)
        self.assertEqual(review["blocked"][0]["parameter_change_guard_status"], "BLOCK_PARAMETER_CHANGE")
        self.assertIn("INSUFFICIENT_COMPLETE_CLOSED_OUTCOMES", review["blocked"][0]["reasons"])

    def test_parameter_change_guard_allows_only_human_review_after_complete_sample(self):
        outcomes = [
            complete_outcome(index, outcome="WIN" if index % 2 else "LOSS")
            for index in range(30)
        ]

        report = strategy_performance.strategy_performance_report([], outcomes)
        guard = report["parameter_change_guard"]

        self.assertEqual(report["summary"]["complete_closed_outcomes"], 30)
        self.assertEqual(guard["allowed_count"], 1)
        self.assertEqual(guard["allowed"][0]["guard_status"], "ALLOW_HUMAN_PARAMETER_REVIEW")
        self.assertEqual(guard["allowed"][0]["recommended_action"], "HUMAN_PARAMETER_REVIEW_ONLY")
        self.assertFalse(guard["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
