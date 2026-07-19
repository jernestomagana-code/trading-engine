import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import preventive_maintenance
from scripts import ibkr_account_profile as account_console
from scripts import install_market_environment_launchd as installer


class PreventiveMaintenanceTests(unittest.TestCase):
    def seed(self, runtime: Path, agents: Path, generated_at: str) -> None:
        for filename in preventive_maintenance.FILE_POLICIES:
            payload = {"generated_at": generated_at, "status": "READY"}
            if filename == "ibkr_bridge_health_latest.json":
                payload.update({"status": "CONNECTED", "connected": True})
            (runtime / filename).write_text(json.dumps(payload))
        for label in preventive_maintenance.EXPECTED_JOBS:
            (agents / f"{label}.plist").write_text("plist")

    def test_ready_when_files_jobs_bridge_and_storage_are_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            agents = Path(tmp) / "agents"
            runtime.mkdir()
            agents.mkdir()
            self.seed(runtime, agents, "2026-07-19T09:00:00+00:00")
            disk = SimpleNamespace(total=100 * 1024**3, used=20 * 1024**3, free=80 * 1024**3)
            with patch.object(preventive_maintenance.shutil, "disk_usage", return_value=disk):
                report = preventive_maintenance.build_maintenance_report(
                    runtime, launch_agents_dir=agents,
                    reference=datetime(2026, 7, 19, 12, tzinfo=timezone.utc), disk_path=runtime,
                )

        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["summary"]["healthy_file_count"], len(preventive_maintenance.FILE_POLICIES))
        self.assertEqual(report["summary"]["installed_job_count"], len(preventive_maintenance.EXPECTED_JOBS))
        self.assertTrue(report["summary"]["bridge_connected"])
        self.assertFalse(report["automatic_deletion_authorized"])
        self.assertFalse(report["automatic_restart_authorized"])

    def test_invalid_required_file_and_low_disk_require_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            agents = Path(tmp) / "agents"
            runtime.mkdir()
            agents.mkdir()
            self.seed(runtime, agents, "2026-07-19T09:00:00+00:00")
            (runtime / "portfolio_risk_latest.json").write_text("not-json")
            disk = SimpleNamespace(total=100 * 1024**3, used=97 * 1024**3, free=3 * 1024**3)
            with patch.object(preventive_maintenance.shutil, "disk_usage", return_value=disk):
                report = preventive_maintenance.build_maintenance_report(
                    runtime, launch_agents_dir=agents,
                    reference=datetime(2026, 7, 19, 12, tzinfo=timezone.utc), disk_path=runtime,
                )

        self.assertEqual(report["status"], "ACTION_REQUIRED")
        self.assertEqual(report["summary"]["storage_status"], "CRITICAL")
        self.assertEqual(report["summary"]["high_file_count"], 1)

    def test_history_is_idempotent_per_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            report = {
                "report_id": "maint-day", "generated_at": "2026-07-19T12:00:00+00:00",
                "status": "READY", "execution_authorized": False, "not_order_instruction": True,
            }
            preventive_maintenance.persist_report(runtime, report)
            preventive_maintenance.persist_report(runtime, report)
            history = json.loads((runtime / "preventive_maintenance_history.json").read_text())

        self.assertEqual(history["report_count"], 1)

    def test_console_renders_safe_maintenance_panel(self):
        payload = {
            "maintenance_version": "v1", "generated_at": "2026-07-19T12:00:00+00:00", "status": "WATCH",
            "summary": {"healthy_file_count": 7, "file_check_count": 8, "stale_or_warning_file_count": 1,
                        "high_file_count": 0, "installed_job_count": 7, "expected_job_count": 7,
                        "bridge_connected": True, "action_count": 1, "runtime_file_count": 80,
                        "runtime_size_mb": 3.0, "disk_free_gb": 80.0, "storage_status": "OK"},
            "actions": [{"priority": "WARN", "title": "Revisar reporte", "detail": "STALE"}],
        }
        with patch.object(account_console, "load_preventive_maintenance", return_value=payload):
            rendered = account_console.render_preventive_maintenance_panel()

        self.assertIn("Mantenimiento preventivo", rendered)
        self.assertIn("Autoeliminación", rendered)
        self.assertIn("DESACTIVADA", rendered)
        self.assertIn("Revisar mantenimiento ahora", rendered)
        self.assertIn("Revisar reporte", rendered)

    def test_daily_schedule_is_installed_through_console_runner(self):
        plist = installer.plist_payload(installer.JOBS["preventive-maintenance"])
        self.assertEqual(plist["StartCalendarInterval"], {"Hour": 6, "Minute": 45})
        self.assertIn("preventive-maintenance", plist["ProgramArguments"][-1])


if __name__ == "__main__":
    unittest.main()
