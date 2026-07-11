import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import daily_recommendations as daily


class DailyRecommendationTests(unittest.TestCase):
    def test_entry_ready_ranks_above_wait_options_but_remains_manual_only(self):
        payload = daily.build_daily_recommendations(
            [
                {
                    "ticker": "QQQ",
                    "strategy": "NAKED_PUT",
                    "final_state": "WAIT_OPTIONS_DATA",
                    "required_missing_fields": ["delta"],
                    "blockers": ["WAIT_OPTIONS_DATA"],
                    "technical": {"confirmed": True, "score": 82, "trend": "BULLISH"},
                    "options_score": 90,
                    "not_order_instruction": True,
                },
                {
                    "ticker": "SPY",
                    "strategy": "COVERED_CALL",
                    "final_state": "ENTRY_READY",
                    "manual_review_ready": True,
                    "technical": {"confirmed": True, "score": 80, "trend": "BULLISH"},
                    "options_score": 88,
                    "selected_contract": {
                        "strike": 700,
                        "expiration": "20260717",
                        "dte": 33,
                        "bid": 1.2,
                        "ask": 1.35,
                        "mid": 1.275,
                        "spread_pct": 11.76,
                        "delta": 0.2,
                    },
                    "not_order_instruction": True,
                },
            ],
            generated_at="2026-06-19T00:00:00+00:00",
        )

        self.assertEqual(payload["engine"], "V31_DAILY_RECOMMENDATION_ENGINE")
        self.assertEqual(payload["items"][0]["ticker"], "SPY")
        self.assertEqual(payload["items"][0]["recommendation_action"], "REVIEW_MANUALLY")
        self.assertGreaterEqual(payload["items"][0]["evidence_quality_score"], 70)
        self.assertGreaterEqual(payload["items"][0]["setup_validity_pct"], 90)
        self.assertLess(payload["items"][1]["setup_validity_pct"], payload["items"][0]["setup_validity_pct"])
        self.assertGreater(payload["items"][0]["ranking_score"], payload["items"][1]["ranking_score"])
        self.assertFalse(payload["items"][0]["can_operate"])
        self.assertEqual(payload["items"][0]["backtesting_bucket"], "VALID_SIGNAL")
        self.assertTrue(payload["items"][0]["performance_eligible"])
        self.assertEqual(payload["items"][0]["alert_lifecycle"]["lifecycle_state"], "LIVE")
        self.assertTrue(payload["items"][0]["manual_review_required"])
        self.assertTrue(payload["not_order_instruction"])
        self.assertEqual(payload["summary"]["entry_ready"], 1)
        self.assertEqual(payload["summary"]["wait_options_data"], 1)
        self.assertEqual(payload["summary"]["performance_eligible"], 1)
        self.assertEqual(payload["summary"]["near_valid_backtesting_bucket"], 1)

    def test_risk_blocked_is_no_trade(self):
        payload = daily.build_daily_recommendations(
            [
                {
                    "ticker": "TSLA",
                    "strategy": "NAKED_PUT",
                    "final_state": "RISK_BLOCKED",
                    "main_blocker": "CANSLIM_BLOCKED",
                    "blockers": ["CANSLIM_BLOCKED"],
                    "technical": {
                        "confirmed": True,
                        "score": 75,
                        "raw": {"canslim": {"passes": False, "score": 42}},
                    },
                    "not_order_instruction": True,
                }
            ],
            generated_at="2026-06-19T00:00:00+00:00",
        )

        self.assertEqual(payload["items"][0]["recommendation_action"], "DO_NOT_TRADE_RISK_BLOCKED")
        self.assertEqual(payload["no_trade"][0]["ticker"], "TSLA")
        self.assertEqual(payload["items"][0]["evidence"]["fundamental"]["canslim"]["passes"], False)
        self.assertFalse(payload["items"][0]["can_operate"])
        self.assertFalse(payload["items"][0]["performance_eligible"])
        self.assertEqual(payload["items"][0]["backtesting_bucket"], "RISK_BLOCKED")

    def test_risk_blocked_preserves_profile_details(self):
        payload = daily.build_daily_recommendations(
            [
                {
                    "ticker": "MSFT",
                    "strategy": "NAKED_PUT",
                    "final_state": "RISK_BLOCKED",
                    "main_blocker": "RISK_BLOCKED",
                    "blockers": ["RISK_PROFILE_SPREAD_PCT_TOO_WIDE"],
                    "risk_blocker": "RISK_PROFILE_SPREAD_PCT_TOO_WIDE",
                    "risk_profile": {
                        "status": "BLOCKED",
                        "primary_blocker": "RISK_PROFILE_SPREAD_PCT_TOO_WIDE",
                        "blockers": ["RISK_PROFILE_SPREAD_PCT_TOO_WIDE"],
                        "blocked_checks": [
                            {
                                "name": "RISK_PROFILE_SPREAD_PCT_TOO_WIDE",
                                "field": "selected_contract.spread_pct",
                                "value": 12.5,
                                "comparator": "<=",
                                "limit": 10.0,
                                "status": "BLOCKED",
                            }
                        ],
                    },
                    "not_order_instruction": True,
                }
            ],
            generated_at="2026-06-19T00:00:00+00:00",
        )

        item = payload["items"][0]
        self.assertEqual(item["recommendation_action"], "DO_NOT_TRADE_RISK_BLOCKED")
        self.assertEqual(item["risk_profile"]["primary_blocker"], "RISK_PROFILE_SPREAD_PCT_TOO_WIDE")
        self.assertEqual(item["risk_profile"]["blocked_checks"][0]["field"], "selected_contract.spread_pct")
        self.assertEqual(item["risk_blocked_details"][0]["limit"], 10.0)
        self.assertFalse(item["can_operate"])

    def test_wait_options_data_exposes_diagnostic_and_alternatives(self):
        payload = daily.build_daily_recommendations(
            [
                {
                    "ticker": "TSLA",
                    "strategy": "NAKED_PUT",
                    "final_state": "WAIT_OPTIONS_DATA",
                    "main_blocker": "WAIT_OPTIONS_DATA",
                    "blockers": ["WAIT_OPTIONS_DATA"],
                    "required_missing_fields": ["spread_too_wide"],
                    "selected_contract": {
                        "ticker": "TSLA",
                        "strategy": "NAKED_PUT",
                        "strike": 335,
                        "expiration": "20260807",
                        "dte": 43,
                        "bid": 6.45,
                        "ask": 9.4,
                        "mid": 7.925,
                        "spread": 2.95,
                        "spread_pct": 37.22,
                        "delta": -0.2158,
                        "quality": "NOT_EXECUTABLE",
                    },
                    "risk_profile": {
                        "status": "BLOCKED",
                        "primary_blocker": "RISK_PROFILE_SPREAD_TOO_WIDE",
                        "blockers": ["RISK_PROFILE_SPREAD_TOO_WIDE"],
                        "blocked_checks": [
                            {
                                "name": "RISK_PROFILE_SPREAD_TOO_WIDE",
                                "field": "selected_contract.spread",
                                "value": 2.95,
                                "comparator": "<=",
                                "limit": 0.35,
                                "status": "BLOCKED",
                            }
                        ],
                    },
                    "contract_alternatives": [
                        {
                            "ticker": "TSLA",
                            "strategy": "NAKED_PUT",
                            "strike": 330,
                            "expiration": "20260807",
                            "bid": 5.8,
                            "ask": 6.05,
                            "spread": 0.25,
                            "spread_pct": 4.22,
                            "delta": -0.19,
                            "quality": "EXECUTABLE",
                            "executable": True,
                            "selection_score": 1180.0,
                        }
                    ],
                    "not_order_instruction": True,
                }
            ],
            generated_at="2026-06-25T00:00:00+00:00",
        )

        item = payload["items"][0]
        diagnostic = item["option_data_diagnostic"]
        self.assertEqual(item["final_state"], "WAIT_OPTIONS_DATA")
        self.assertEqual(diagnostic["primary_cause"], "SPREAD_TOO_WIDE")
        self.assertEqual(diagnostic["contract_threshold_checks"][0]["limit"], 0.35)
        self.assertTrue(diagnostic["has_executable_alternative"])
        self.assertEqual(item["contract_alternatives"][0]["strike"], 330)
        self.assertFalse(item["can_operate"])
        self.assertTrue(item["not_order_instruction"])


if __name__ == "__main__":
    unittest.main()
