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
from scripts import run_dependency_audit
from scripts import run_security_audit
from scripts import stock_ultimus_launchd_console_runner


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
        jobs = install_market_environment_launchd.selected_jobs("auth-preflight,market-open-readiness,security-audit,dependency-audit")
        result = install_market_environment_launchd.install(jobs, dry_run=True)
        raw = json.dumps(result)

        self.assertEqual(result["action"], "install")
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["results"]), 4)
        self.assertNotIn("READ_ACCESS_TOKEN", raw)
        self.assertIn("stock_ultimus_launchd_console_runner.py", raw)
        self.assertIn("market-open-readiness", raw)
        self.assertIn("security-audit", raw)
        self.assertIn("dependency-audit", raw)

    def test_launchd_console_runner_waits_for_final_job_result(self):
        running = {"job_id": "abc123", "status": "RUNNING", "label": "Security audit"}
        done = {
            "job_id": "abc123",
            "status": "DONE",
            "label": "Security audit",
            "result": {"returncode": 0, "remote_verification_ok": True},
        }
        with mock.patch.object(
            stock_ultimus_launchd_console_runner,
            "get_job_status",
            side_effect=[running, done],
        ):
            completion = stock_ultimus_launchd_console_runner.wait_for_job(
                "abc123",
                request_timeout=1,
                job_timeout=2,
                poll_interval=0,
            )

        self.assertTrue(completion["ok"])
        self.assertEqual(completion["status"], "DONE")
        self.assertEqual(completion["returncode"], 0)
        self.assertNotIn("stdout_tail", completion)

    def test_launchd_console_runner_surfaces_final_job_error(self):
        failed = {
            "job_id": "failed123",
            "status": "ERROR",
            "label": "Dependency audit",
            "error": "audit failed",
            "result": {"returncode": 1},
        }
        with mock.patch.object(
            stock_ultimus_launchd_console_runner,
            "get_job_status",
            return_value=failed,
        ):
            completion = stock_ultimus_launchd_console_runner.wait_for_job(
                "failed123",
                request_timeout=1,
                job_timeout=2,
                poll_interval=0,
            )

        self.assertFalse(completion["ok"])
        self.assertEqual(completion["status"], "ERROR")
        self.assertEqual(completion["returncode"], 1)

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

    def test_security_audit_redacts_secret_values_and_notifies_only_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            app = root / "app"
            app.mkdir()
            runtime.mkdir()
            root.joinpath(".gitignore").write_text("runtime/\n.env\n.env.*\n!.env.example\n*.log\n")
            app.joinpath("main.py").write_text(
                "\n".join(
                    [
                        "import hmac, os",
                        "READ_AUTH_CRITICAL_ENDPOINTS = ['/v31_system_status']",
                        "REQUIRE_SNAPSHOT_INGEST_TOKEN = os.getenv(\"REQUIRE_SNAPSHOT_INGEST_TOKEN\", \"true\").lower() == \"true\"",
                        "def _path_requires_read_auth(path): return True",
                        "async def sensitive_read_auth_middleware(request, call_next): pass",
                        "def verify_snapshot_ingest_token(*tokens): return hmac.compare_digest('a', 'a')",
                        "def read_auth_status():",
                        "    return {'critical_endpoints_protected': True, 'not_order_instruction': True}",
                    ]
                )
            )
            root.joinpath("ibkr_bridge.py").write_text("{'execution_authorized': False, 'not_order_instruction': True}\n")
            root.joinpath("durable_storage.py").write_text("{'execution_authorized': False, 'not_order_instruction': True}\n")
            leaked_value = "real-token-value"
            root.joinpath(".env").write_text("READ_ACCESS_TOKEN=" + leaked_value + "\n")
            args = argparse.Namespace(
                runtime_dir=str(runtime),
                json_out=str(runtime / "security_audit_latest.json"),
                state_file=str(runtime / "security_audit_state.json"),
                max_file_bytes=250000,
                no_write=True,
                no_send=True,
                force=False,
                pushover=False,
                macos_notify=False,
                webhook_url="",
                timeout=1,
            )

            report = run_security_audit.build_report(args, root=root)

        raw = json.dumps(report)
        self.assertEqual(report["status"], "ACTION_REQUIRED")
        self.assertEqual(report["alert_level"], "ACTION")
        self.assertTrue(report["should_notify"])
        self.assertIn("SENSITIVE_VALUE_IN_FILE", raw)
        self.assertNotIn(leaked_value, raw)
        self.assertFalse(report["secrets_printed"])

    def test_security_audit_clean_report_is_dashboard_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runtime.joinpath("security_audit_latest.json").write_text(
                json.dumps(
                    {
                        "status": "OK",
                        "alert_level": "OK",
                        "next_required_action": "Security audit is clean.",
                        "action_count": 0,
                        "watch_count": 0,
                        "should_notify": False,
                        "secrets_printed": False,
                    }
                )
            )

            payload = build_local_environment_dashboard.build_dashboard(
                runtime,
                generated_at="2026-07-05T12:00:00+00:00",
            )

        self.assertEqual(payload["report_count"], 8)
        self.assertEqual(payload["available_report_count"], 1)
        self.assertIn("Security Audit", payload["html"])
        self.assertIn("Security audit is clean.", payload["html"])

    def test_dependency_audit_parses_vulnerabilities_without_secret_output(self):
        raw = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "demo",
                        "version": "1.0",
                        "vulns": [
                            {
                                "id": "PYSEC-TEST",
                                "fix_versions": ["1.1"],
                                "description": "test vulnerability",
                            }
                        ],
                    }
                ]
            }
        )

        findings = run_dependency_audit.parse_pip_audit_json(raw)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "ACTION")
        self.assertEqual(findings[0]["package"], "demo")
        self.assertFalse(findings[0]["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
