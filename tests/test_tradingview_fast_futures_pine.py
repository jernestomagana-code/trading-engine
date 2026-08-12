from pathlib import Path
import unittest


class TradingViewFastFuturesPineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pine = (
            Path(__file__).resolve().parents[1]
            / "tradingview"
            / "stock_ultimus_intraday_futures_fast_v2.pine"
        ).read_text()

    def test_fast_payload_contains_required_futures_context(self):
        string_fields = (
            "session_state",
            "major_event_window",
            "risk_daily_status",
        )
        numeric_fields = ("premarket_high", "premarket_low")
        for field in string_fields:
            self.assertIn(f'pair("{field}"', self.pine)
        for field in numeric_fields:
            self.assertIn(f'numpair("{field}"', self.pine)

    def test_fast_alert_emits_silent_session_heartbeat(self):
        self.assertIn('payload("SESSION_SNAPSHOT"', self.pine)
        self.assertIn('"_SESSION_SNAPSHOT_5M"', self.pine)
        self.assertIn("heartbeatEveryBars", self.pine)


if __name__ == "__main__":
    unittest.main()
