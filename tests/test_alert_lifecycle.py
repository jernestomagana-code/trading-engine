import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import alert_lifecycle


class AlertLifecycleTests(unittest.TestCase):
    def test_intraday_futures_expires_after_fast_ttl(self):
        alert = {
            "ticker": "MNQ",
            "strategy": "INTRADAY_INDEX_FUTURES",
            "state": "ENTRY_READY",
            "alert_created_at": "2026-07-11T14:00:00+00:00",
            "selected_contract": {"strike": 22000, "dte": 0, "delta": 1, "bid": 3.0},
        }

        lifecycle = alert_lifecycle.alert_lifecycle_state(
            alert,
            now=datetime(2026, 7, 11, 14, 31, tzinfo=timezone.utc),
        )

        self.assertEqual(lifecycle["ttl_minutes"], 30)
        self.assertEqual(lifecycle["lifecycle_state"], "EXPIRED")
        self.assertFalse(lifecycle["performance_eligible"])

    def test_entry_ready_with_contract_is_valid_paper_but_not_real_without_fill(self):
        alert = {
            "ticker": "MSFT",
            "strategy": "NAKED_PUT",
            "state": "ENTRY_READY",
            "manual_review_ready": True,
            "alert_created_at": "2026-07-11T14:00:00+00:00",
            "selected_contract": {
                "strike": 350,
                "expiration": "20260821",
                "dte": 41,
                "delta": -0.21,
                "bid": 5.4,
            },
        }

        lifecycle = alert_lifecycle.alert_lifecycle_state(
            alert,
            now=datetime(2026, 7, 11, 15, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(lifecycle["lifecycle_state"], "LIVE")
        self.assertEqual(lifecycle["backtesting_bucket"], "VALID_SIGNAL")
        self.assertTrue(lifecycle["performance_eligible"])
        self.assertTrue(lifecycle["paper_tracking_allowed"])
        self.assertFalse(lifecycle["ibkr_real_performance_allowed"])

    def test_ibkr_applied_requires_fill_for_real_performance(self):
        base = {
            "ticker": "AAPL",
            "strategy": "NAKED_PUT",
            "state": "ENTRY_READY",
            "manual_review_ready": True,
            "selected_contract": {
                "strike": 190,
                "expiration": "20260821",
                "dte": 41,
                "delta": -0.2,
                "mid": 2.1,
            },
            "operator_status": "IBKR_APPLIED",
        }

        without_fill = alert_lifecycle.alert_lifecycle_state(base)
        with_fill = alert_lifecycle.alert_lifecycle_state({
            **base,
            "ibkr_fill_price": 2.1,
            "ibkr_fill_quantity": 1,
        })

        self.assertFalse(without_fill["ibkr_real_performance_allowed"])
        self.assertEqual(with_fill["backtesting_bucket"], "IBKR_REAL")
        self.assertTrue(with_fill["ibkr_real_performance_allowed"])

    def test_wait_and_rejected_alerts_are_not_valid_performance(self):
        wait = alert_lifecycle.alert_lifecycle_state({
            "ticker": "NVDA",
            "strategy": "NAKED_PUT",
            "state": "WAIT_TECHNICAL",
            "selected_contract": {"strike": 150, "expiration": "20260821", "dte": 41, "delta": -0.2, "bid": 4.0},
        })
        rejected = alert_lifecycle.alert_lifecycle_state({
            "ticker": "NVDA",
            "strategy": "NAKED_PUT",
            "state": "ENTRY_READY",
            "operator_status": "REJECTED",
            "selected_contract": {"strike": 150, "expiration": "20260821", "dte": 41, "delta": -0.2, "bid": 4.0},
        })

        self.assertEqual(wait["backtesting_bucket"], "NEAR_VALID")
        self.assertFalse(wait["performance_eligible"])
        self.assertEqual(rejected["backtesting_bucket"], "REJECTED")
        self.assertFalse(rejected["performance_eligible"])


if __name__ == "__main__":
    unittest.main()
