import unittest
from datetime import datetime, timezone
from alert_lifecycle import futures_entry_price_check


class FuturesEntryPriceTests(unittest.TestCase):
    def test_long_short_limits_and_invalidation(self):
        now = datetime(2026, 9, 4, 15, tzinfo=timezone.utc)
        base = dict(ticker="MNQ1!", quote_symbol="MNQ1!", quote_timestamp=now.isoformat(), direction="LONG", current_price=101, max_entry_price=102, stop_price=95, tp1_price=110)
        self.assertEqual(futures_entry_price_check(base, now=now)["status"], "WITHIN_LIMIT")
        for price, status in [(103, "DO_NOT_CHASE"), (94, "INVALIDATED")]:
            self.assertEqual(futures_entry_price_check({**base, "current_price": price}, now=now)["status"], status)
        short = {**base, "direction": "SHORT", "max_entry_price": 98, "stop_price": 105, "tp1_price": 90}
        self.assertEqual(futures_entry_price_check({**short, "current_price": 97}, now=now)["status"], "DO_NOT_CHASE")
        self.assertEqual(futures_entry_price_check({**short, "current_price": 106}, now=now)["status"], "INVALIDATED")
        self.assertEqual(futures_entry_price_check({**base, "quote_symbol": "USTEC.F"}, now=now)["status"], "UNVERIFIED")
        self.assertEqual(futures_entry_price_check({**base, "quote_timestamp": "2026-09-04T14:59:00Z"}, now=now)["status"], "UNVERIFIED")
        for value in [float("nan"), float("inf"), 0, -1]:
            for field in ("current_price", "max_entry_price", "stop_price", "tp1_price"):
                with self.subTest(field=field, value=value):
                    self.assertEqual(futures_entry_price_check({**base, field: value}, now=now)["status"], "UNVERIFIED")

    def test_console_keeps_unverified_signal_visible_and_rejects_chasing(self):
        from scripts import ibkr_account_profile as console
        now = datetime.now(timezone.utc).isoformat()
        event = dict(ticker="MNQ1!", strategy="INTRADAY_INDEX_FUTURES", state="ENTRY_READY",
                     final_state="ENTRY_READY", received_at=now, direction="LONG",
                     entry_price=101, stop_price=95, tp1_price=110, tp2_price=115,
                     max_entry_price=102)
        def items(signal):
            result = console.build_unified_opportunity_items(
                {"ok": True, "data": {"active_alerts": [signal]}}, {}, {},
                risk_payload={"alerts": []}, account_capacity={"available_capacity": 50000})
            return [item for item in result if item["type"] == "futures"]
        self.assertEqual(items(event)[0]["state_label"], "Verificar precio actual")
        self.assertEqual(items(event)[0]["target"], "TP1 110 · TP2 115")
        rows = console.build_futures_operational_rows([event], {})
        self.assertEqual(rows[0]["stage"], "Verificar precio actual")
        self.assertTrue(rows[0]["live_opportunity"])
        quoted = {**event, "quote_symbol": "MNQ1!", "quote_timestamp": now, "current_price": 101}
        self.assertEqual(items(quoted)[0]["state"], "ready")
        chased = {**quoted, "current_price": 103}
        self.assertEqual(items(chased), [])
        self.assertFalse(console.build_futures_operational_rows([chased], {})[0]["live_opportunity"])

    def test_declared_minimum_reward_risk_is_independently_checked(self):
        now = datetime(2026, 9, 4, 15, tzinfo=timezone.utc)
        valid = dict(ticker="MNQ1!", quote_symbol="MNQ1!", quote_timestamp=now.isoformat(),
                     direction="LONG", current_price=101, entry_limit_price=102, stop_price=95,
                     tp1_price=110, tp2_price=116, minimum_reward_risk=1.5)
        self.assertEqual(futures_entry_price_check(valid, now=now)["status"], "WITHIN_LIMIT")
        invalid = {**valid, "entry_limit_price": 105, "tp2_price": 110}
        result = futures_entry_price_check(invalid, now=now)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertIn("beneficio/riesgo", result["reason"])


if __name__ == "__main__":
    unittest.main()
