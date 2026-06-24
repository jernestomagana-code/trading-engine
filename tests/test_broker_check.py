import unittest

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
        }

        enriched = broker_check.merge_broker_checks(snapshot)
        check = enriched["broker_checks"][0]

        self.assertEqual(check["status"], "WARNING")
        self.assertEqual(check["checks"][0]["name"], "PUT_CAPACITY_CHECK")
        self.assertEqual(check["checks"][0]["status"], "PASS")
        self.assertIn("BROKER_POSITIONS_MISSING", check["warnings"])
        self.assertFalse(check["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
