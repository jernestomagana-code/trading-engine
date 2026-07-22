import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tools import publish_v31_snapshot_from_runtime as publisher


class V31RuntimePublisherTests(unittest.TestCase):
    def test_runtime_freshness_handles_empty_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            freshness = publisher.runtime_freshness(Path(tmp))

        self.assertIsNone(freshness["newest_file"])
        self.assertIsNone(freshness["newest_mtime"])
        self.assertIsNone(freshness["age_minutes"])
        self.assertEqual(freshness["file_count"], 0)

    def test_runtime_freshness_reports_newest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            path = runtime / "sample.json"
            path.write_text("{}")
            freshness = publisher.runtime_freshness(runtime)

        self.assertTrue(freshness["newest_file"].endswith("sample.json"))
        self.assertIsNotNone(freshness["newest_mtime"])
        self.assertGreaterEqual(freshness["age_minutes"], 0)
        self.assertEqual(freshness["file_count"], 1)

    def test_publish_freshness_ignores_newer_notification_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "decision_desk_snapshot.json").write_text("{}")
            (runtime / "v32_pushover_notify_state.json").write_text("{}")

            freshness = publisher.publish_data_freshness(runtime)

        self.assertTrue(freshness["newest_file"].endswith("decision_desk_snapshot.json"))
        self.assertEqual(freshness["considered_files"], ["decision_desk_snapshot.json"])

    def test_build_payload_extracts_options_and_technical_without_ibkr(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "sample.json").write_text(json.dumps({
                "options_rows": [
                    {
                        "ticker": "QQQ",
                        "strategy": "NAKED_PUT",
                        "decision": "ENTRY_READY",
                        "score": 90,
                        "strike": 710,
                        "expiration": "20260717",
                        "dte": 33,
                        "bid": 1.20,
                        "ask": 1.35,
                        "delta": -0.20,
                    }
                ],
                "technical_snapshot": {
                    "QQQ": {
                        "ticker": "QQQ",
                        "trend": "BULLISH",
                        "score": 80,
                    }
                },
                "control_panel": {"ticker": "CONTROL_PANEL", "score": 100},
                "RAW": {"score": 99, "trend": "UNKNOWN"},
                "FUTURES": {"ticker": "FUTURES", "score": 95},
                "ATTEMPTS": {"ticker": "ATTEMPTS", "score": 90},
            }))
            (runtime / "coberturas_rsp_manual_context.json").write_text(json.dumps({
                "context_version": "coberturas_rsp_manual_context_v1",
                "ticker": "RSP",
                "spot": 215.15,
            }))

            payload = publisher.build_payload(runtime)

        self.assertEqual(payload["source"], "LOCAL_RUNTIME_V31_PUBLISHER")
        self.assertEqual(len(payload["options_rows"]), 1)
        self.assertEqual(payload["options_rows"][0]["ticker"], "QQQ")
        self.assertEqual(payload["options_rows"][0]["strategy"], "NAKED_PUT")
        self.assertIn("QQQ", payload["technical_snapshot"])
        self.assertNotIn("CONTROL_PANEL", payload["technical_snapshot"])
        self.assertNotIn("RAW", payload["technical_snapshot"])
        self.assertNotIn("FUTURES", payload["technical_snapshot"])
        self.assertNotIn("ATTEMPTS", payload["technical_snapshot"])
        self.assertEqual(payload["coberturas_rsp_manual_context"]["spot"], 215.15)
        self.assertIn(payload["market"]["is_regular_market_open"], {True, False})
        self.assertEqual(
            payload["market"]["is_regular_market_open"],
            payload["market"]["options_bidask_expected"],
        )
        self.assertTrue(payload["not_order_instruction"])
        self.assertEqual(payload["bridge_status"], "PUBLISHED_FROM_LOCAL_RUNTIME_WITHOUT_IBKR_CONNECTION")

    def test_market_snapshot_detects_regular_session_and_exchange_holiday(self):
        regular = publisher.build_market_snapshot(
            datetime(2026, 7, 22, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        )
        holiday = publisher.build_market_snapshot(
            datetime(2026, 7, 3, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        )

        self.assertTrue(regular["is_regular_market_open"])
        self.assertTrue(regular["options_bidask_expected"])
        self.assertFalse(holiday["is_regular_market_open"])
        self.assertTrue(holiday["market_holiday"])


if __name__ == "__main__":
    unittest.main()
