import unittest
from datetime import datetime, timedelta, timezone

import broker_check


class BrokerCheckTests(unittest.TestCase):
    def test_covered_call_without_100_shares_blocks_manual_review(self):
        snapshot = {
            "options_rows": [
                {
                    "ticker": "TSLA",
                    "strategy": "COVERED_CALL",
                    "strike": 440,
                    "expiration": "20260731",
                    "dte": 39,
                    "bid": 13.35,
                    "ask": 13.60,
                    "delta": 0.34,
                }
            ],
            "positions": [
                {
                    "ticker": "TSLA",
                    "sec_type": "STK",
                    "position_size": 50,
                    "market_value": 18000,
                }
            ],
            "account": {"net_liquidation": 100000, "available_funds": 50000},
        }

        enriched = broker_check.merge_broker_checks(snapshot)
        check = enriched["broker_checks"][0]

        self.assertEqual(check["status"], "BLOCKED")
        self.assertIn("BROKER_COVERED_CALL_SHARES_INSUFFICIENT", check["blockers"])
        self.assertFalse(check["execution_authorized"])
        self.assertTrue(check["not_order_instruction"])

    def test_cash_secured_put_capacity_passes_when_capacity_is_available(self):
        snapshot = {
            "options_rows": [
                {
                    "ticker": "QQQ",
                    "strategy": "NAKED_PUT",
                    "strike": 660,
                    "expiration": "20260731",
                    "dte": 39,
                    "bid": 5.41,
                    "ask": 5.46,
                    "delta": -0.13,
                }
            ],
            "positions": [],
            "account": {"available_funds": 90000},
            "broker_check_policy": {"max_trade_capacity_pct": 100},
        }

        enriched = broker_check.merge_broker_checks(snapshot)
        check = enriched["broker_checks"][0]

        self.assertEqual(check["status"], "WARNING")
        self.assertEqual(check["checks"][0]["name"], "PUT_CAPACITY_CHECK")
        self.assertEqual(check["checks"][0]["status"], "PASS")
        self.assertIn("BROKER_POSITIONS_MISSING", check["warnings"])
        self.assertFalse(check["execution_authorized"])

    def test_naked_put_blocks_when_trade_size_exceeds_capacity_policy(self):
        snapshot = {
            "options_rows": [
                {
                    "ticker": "MSFT",
                    "strategy": "NAKED_PUT",
                    "strike": 365,
                    "expiration": "20260731",
                    "dte": 39,
                    "bid": 4.20,
                    "ask": 4.35,
                    "delta": -0.18,
                }
            ],
            "positions": [{"ticker": "MSFT", "sec_type": "STK", "position_size": 0}],
            "account": {"available_funds": 100000},
            "broker_check_policy": {"max_trade_capacity_pct": 25},
        }

        check = broker_check.merge_broker_checks(snapshot)["broker_checks"][0]

        self.assertEqual(check["status"], "BLOCKED")
        self.assertIn("BROKER_TRADE_SIZE_TOO_LARGE", check["blockers"])
        trade_size = [item for item in check["checks"] if item["name"] == "TRADE_CAPACITY_PCT"][0]
        self.assertEqual(trade_size["status"], "BLOCKED")

    def test_existing_short_put_blocks_additional_naked_put(self):
        snapshot = {
            "options_rows": [
                {
                    "ticker": "MSFT",
                    "strategy": "NAKED_PUT",
                    "strike": 300,
                    "expiration": "20260731",
                    "dte": 39,
                    "bid": 2.20,
                    "ask": 2.35,
                    "delta": -0.18,
                }
            ],
            "positions": [{"ticker": "MSFT", "sec_type": "OPT", "right": "P", "position_size": -1}],
            "account": {"available_funds": 100000},
            "broker_check_policy": {"max_short_puts_per_ticker": 1, "max_trade_capacity_pct": 50},
        }

        check = broker_check.merge_broker_checks(snapshot)["broker_checks"][0]

        self.assertEqual(check["status"], "BLOCKED")
        self.assertIn("BROKER_EXISTING_SHORT_PUT_EXPOSURE", check["blockers"])
        self.assertEqual(check["position"]["short_put_count"], 1)

    def test_broker_check_freshness_marks_old_check_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()

        freshness = broker_check.broker_check_freshness({"generated_at": old}, max_age_minutes=15)

        self.assertEqual(freshness["status"], "STALE")
        self.assertFalse(freshness["ok"])
        self.assertIn("BROKER_CHECK_STALE", freshness["blockers"])


if __name__ == "__main__":
    unittest.main()
