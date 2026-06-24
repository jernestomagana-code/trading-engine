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
        self.assertFalse(payload["items"][0]["can_operate"])
        self.assertTrue(payload["items"][0]["manual_review_required"])
        self.assertTrue(payload["not_order_instruction"])
        self.assertEqual(payload["summary"]["entry_ready"], 1)
        self.assertEqual(payload["summary"]["wait_options_data"], 1)

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


if __name__ == "__main__":
    unittest.main()
