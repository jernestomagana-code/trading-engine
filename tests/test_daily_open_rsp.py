from __future__ import annotations

import unittest
from pathlib import Path

from scripts import daily_open_checklist as daily_open


def base_report() -> dict:
    return {
        "refresh_requested": True,
        "refresh_step": {"ok": True},
        "capacity_refresh_step": {"ok": True},
        "rsp_refresh_step": {"ok": True},
        "publish_step": {"ok": True},
        "coberturas_rsp": {
            "ok": True,
            "manual_context_available": True,
            "manual_context_fresh": True,
            "chain_has_rsp": True,
        },
        "checks": {
            "read_token_available": {"ok": True},
            "production_auth": {"ok": True},
            "v32_operator_today": {"ok": True},
            "foundation_health": {"status": "PASS"},
            "operational_evidence_gate": {"state": "READY"},
        },
        "operator_today": {"status": "WAIT_MARKET"},
        "operator_counts": {},
    }


class DailyOpenRspTests(unittest.TestCase):
    def test_bridge_can_defer_incremental_posts_to_final_publish(self):
        source = (Path(__file__).resolve().parents[1] / "ibkr_bridge.py").read_text(encoding="utf-8")

        self.assertIn('if _env_bool("IBKR_DISABLE_INCREMENTAL_ENGINE_POSTS", False):', source)
        self.assertIn('return "SKIPPED_FINAL_PUBLISH"', source)

    def test_rsp_refresh_failure_has_specific_operator_message(self):
        report = base_report()
        report["rsp_refresh_step"] = {"ok": False, "error": "TIMEOUT_AFTER_165_SECONDS"}

        status, action = daily_open.classify(report)

        self.assertEqual(status, "ACTION_REQUIRED")
        self.assertIn("Coberturas RSP", action)
        self.assertIn("7-14 DTE", action)

    def test_capacity_refresh_failure_blocks_rsp_assessment(self):
        report = base_report()
        report["capacity_refresh_step"] = {"ok": False, "error": "ACCOUNT_SUMMARY_FAILED"}

        status, action = daily_open.classify(report)

        self.assertEqual(status, "ACTION_REQUIRED")
        self.assertIn("capacidad actual", action)

    def test_fresh_context_without_rsp_chain_is_not_reported_ready(self):
        report = base_report()
        report["coberturas_rsp"]["ok"] = False
        report["coberturas_rsp"]["chain_has_rsp"] = False

        status, action = daily_open.classify(report)

        self.assertEqual(status, "ACTION_REQUIRED")
        self.assertIn("cadena IBKR RSP fresca", action)

    def test_connected_bridge_timeout_does_not_blame_tws(self):
        report = base_report()
        report["refresh_step"] = {"ok": False, "error": "TIMEOUT_AFTER_240_SECONDS"}

        status, action = daily_open.classify(report)

        self.assertEqual(status, "ACTION_REQUIRED")
        self.assertIn("IBKR conecto", action)
        self.assertNotIn("Abrir/desbloquear", action)

    def test_long_term_evidence_gap_is_not_reported_as_opening_failure(self):
        report = base_report()
        report["checks"]["foundation_health"] = {
            "status": "FAIL",
            "priorities": ["Collect real TradingView events."],
        }

        status, action = daily_open.classify(report)

        self.assertEqual(status, "EVIDENCE_COLLECTION_ONLY")
        self.assertIn("Apertura tecnica completa", action)


if __name__ == "__main__":
    unittest.main()
