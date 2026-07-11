import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_local_environment_dashboard
from scripts import install_market_environment_launchd
from scripts import run_environment_alerts
from scripts import run_environment_auth_check


class EnvironmentToolsTests(unittest.TestCase):
    def test_auth_check_local_only_uses_env_without_printing_secrets(self):
        env = {
            "READ_ACCESS_TOKEN": "read-secret",
            "TRADING_ENGINE_INGEST_TOKEN": "ingest-secret",
            "PUSHOVER_USER_KEY": "user-secret",
            "PUSHOVER_API_TOKEN": "api-secret",
        }
        args = argparse.Namespace(
            base_url="https://example.test",
            timeout=1,
            local_only=True,
            no_keychain=True,
        )
        with mock.patch.dict(os.environ, env, clear=False):
            report = run_environment_auth_check.build_report(args)

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "OK")
        self.assertFalse(report["secrets_printed"])
        self.assertNotIn("read-secret", json.dumps(report))
        self.assertTrue(report["checks"]["pushover_channel_configured"]["ok"])

    def test_local_dashboard_renders_runtime_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runtime.joinpath("market_open_readiness_latest.json").write_text(
                json.dumps(
                    {
                        "status": "WAITING_TV",
                        "next_required_action": "Wait for TV",
                        "ibkr_primary_gap": "INCOMPLETE_OPTION_MARKET_DATA",
                        "operational_gate_state": "EVIDENCE_COLLECTION_ONLY",
                        "tradingview_bundle": {
                            "real_e2e_confirmed": False,
                            "total_production_active_alert_count": 5,
                            "total_received_required_event_count": 0,
                            "total_required_logical_event_count": 16,
                            "total_required_alert_count": 16,
                        },
                    }
                )
            )

            payload = build_local_environment_dashboard.build_dashboard(
                runtime,
                generated_at="2026-07-05T12:00:00+00:00",
            )

        self.assertEqual(payload["available_report_count"], 1)
        self.assertIn("Stock Ultimus Local Environment", payload["html"])
        self.assertIn("WAITING_TV", payload["html"])
        self.assertFalse(payload["execution_authorized"])

    def test_launchd_dry_run_keeps_secrets_out_of_plists(self):
        jobs = install_market_environment_launchd.selected_jobs("auth-preflight,market-open-readiness")
        result = install_market_environment_launchd.install(jobs, dry_run=True)
        raw = json.dumps(result)

        self.assertEqual(result["action"], "install")
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["results"]), 2)
        self.assertNotIn("READ_ACCESS_TOKEN", raw)
        self.assertIn("run_market_open_readiness.py", raw)

    def test_environment_alerts_dedupes_same_watch_signature(self):
        monitor = {
            "alert_level": "WATCH",
            "status": "WAITING_TV",
            "findings": [{"code": "TV_REAL_E2E_PENDING"}],
        }
        args = argparse.Namespace(force=False, notify_watch=True)
        first = run_environment_alerts.should_notify(monitor, args, {})
        second = run_environment_alerts.should_notify(
            monitor,
            args,
            {"last_signature": run_environment_alerts.signature(monitor)},
        )

        self.assertEqual(first, (True, "ENVIRONMENT_WATCH"))
        self.assertEqual(second, (False, "DUPLICATE_SUPPRESSED"))


if __name__ == "__main__":
    unittest.main()
