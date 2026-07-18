import json
import tempfile
import unittest
from pathlib import Path

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
                "GATE": {"score": 98, "trend": "UNKNOWN"},
            }))

            payload = publisher.build_payload(runtime)

        self.assertEqual(payload["source"], "LOCAL_RUNTIME_V31_PUBLISHER")
        self.assertEqual(len(payload["options_rows"]), 1)
        self.assertEqual(payload["options_rows"][0]["ticker"], "QQQ")
        self.assertEqual(payload["options_rows"][0]["strategy"], "NAKED_PUT")
        self.assertIn("QQQ", payload["technical_snapshot"])
        self.assertNotIn("CONTROL_PANEL", payload["technical_snapshot"])
        self.assertNotIn("RAW", payload["technical_snapshot"])
        self.assertNotIn("GATE", payload["technical_snapshot"])
        self.assertFalse(payload["market"]["is_regular_market_open"])
        self.assertTrue(payload["not_order_instruction"])
        self.assertEqual(payload["bridge_status"], "PUBLISHED_FROM_LOCAL_RUNTIME_WITHOUT_IBKR_CONNECTION")


if __name__ == "__main__":
    unittest.main()
