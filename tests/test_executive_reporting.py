import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import executive_reporting
from scripts import ibkr_account_profile as account_console
from scripts import install_market_environment_launchd as installer


class ExecutiveReportingTests(unittest.TestCase):
    def build_runtime(self, root: Path) -> None:
        payloads = {
            "broker_control_tower_latest.json": {"account_count": 3, "ready_account_count": 3, "stale_account_count": 0, "failed_account_count": 0},
            "portfolio_risk_latest.json": {"status": "ACTION_REQUIRED", "risk_score": 72, "decision_support": "REDUCE_RISK", "alerts": [{"severity": "HIGH", "rule": "MARGIN_HIGH"}]},
            "portfolio_stress_latest.json": {"status": "READY", "valuation_coverage_ratio": 1.0},
            "portfolio_factor_latest.json": {"history_coverage_ratio": 1.0, "greeks_coverage_ratio": 1.0},
            "portfolio_risk_operations_status.json": {"status": "READY", "mode": "digest"},
            "portfolio_risk_observation.json": {"status": "OBSERVING", "consecutive_clean_sessions": 2, "target_sessions": 5, "remaining_clean_sessions": 3},
            "portfolio_risk_history.json": {"events": [
                {"generated_at": "2026-07-18T12:00:00+00:00", "transition": "OPENED", "severity": "HIGH"},
                {"generated_at": "2026-07-18T13:00:00+00:00", "transition": "RESOLVED", "severity": "NONE"},
            ]},
            "v32_decision_journal.json": [],
            "v32_outcomes_journal.json": [],
        }
        for name, payload in payloads.items():
            (root / name).write_text(json.dumps(payload))

    def test_builds_sanitized_daily_and_weekly_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self.build_runtime(runtime)
            reference = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
            daily = executive_reporting.build_report(runtime, "daily", reference=reference)
            weekly = executive_reporting.build_report(runtime, "weekly", reference=reference)

        self.assertEqual(daily["status"], "ACTION_REQUIRED")
        self.assertEqual(daily["portfolio"]["critical_high_alert_count"], 1)
        self.assertEqual(weekly["period_activity"]["risk_event_count"], 2)
        self.assertGreater(daily["pending_action_count"], 0)
        self.assertTrue(daily["sensitive_identifiers_excluded"])
        self.assertFalse(daily["execution_authorized"])
        self.assertFalse(daily["automatic_rule_changes_authorized"])

    def test_persistence_is_idempotent_per_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self.build_runtime(runtime)
            report = executive_reporting.build_report(
                runtime, "daily", reference=datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
            )
            executive_reporting.persist_report(runtime, report)
            executive_reporting.persist_report(runtime, report)
            history = json.loads((runtime / "executive_report_history.json").read_text())

        self.assertEqual(history["report_count"], 1)
        self.assertEqual(history["reports"][0]["report_id"], report["report_id"])

    def test_console_renders_daily_and_weekly_executive_view(self):
        daily = {
            "report_version": "v1", "status": "BUILDING_EVIDENCE", "headline": "Sin alertas prioritarias.",
            "generated_at": "2026-07-19T12:00:00+00:00", "pending_action_count": 1,
            "portfolio": {"account_count": 3, "risk_status": "READY", "risk_score": 20, "critical_high_alert_count": 0},
            "decisions_and_results": {"complete_closed_outcomes": 0, "verified_precision_pct": None},
            "pending_actions": [{"priority": "BUILDING", "title": "Acumular resultados", "detail": "0/30 completos."}],
        }
        weekly = {
            "report_version": "v1", "generated_at": "2026-07-19T12:00:00+00:00",
            "period_activity": {"risk_event_count": 4, "risk_events_opened": 3, "risk_events_resolved": 1},
        }
        with patch.object(account_console, "load_executive_reports", return_value={"daily": daily, "weekly": weekly}):
            rendered = account_console.render_executive_report_panel()

        self.assertIn("Reporte ejecutivo", rendered)
        self.assertIn("Eventos semanales", rendered)
        self.assertIn("Actualizar reporte diario", rendered)
        self.assertIn("Actualizar reporte semanal", rendered)
        self.assertIn("Acumular resultados", rendered)

    def test_daily_and_weekly_launchd_schedules_are_separate(self):
        daily = installer.plist_payload(installer.JOBS["executive-report-daily"])
        weekly = installer.plist_payload(installer.JOBS["executive-report-weekly"])

        self.assertEqual(len(daily["StartCalendarInterval"]), 5)
        self.assertEqual(weekly["StartCalendarInterval"]["Weekday"], 5)
        self.assertIn("executive-report-daily", daily["ProgramArguments"][-1])
        self.assertIn("executive-report-weekly", weekly["ProgramArguments"][-1])


if __name__ == "__main__":
    unittest.main()
