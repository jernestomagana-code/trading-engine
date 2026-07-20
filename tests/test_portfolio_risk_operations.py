import argparse
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import broker_control_tower as tower
import portfolio_risk_engine as risk
import portfolio_risk_operations as operations
from scripts import install_portfolio_risk_launchd as installer
from scripts import run_portfolio_risk_operations as runner
from scripts import ibkr_account_profile as account_console


class PortfolioRiskOperationsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc)
        snapshot = tower.account_snapshot(
            broker="IBKR",
            alias="primary",
            scope="primary",
            capacity={
                "net_liquidation": 100000,
                "available_funds": 8000,
                "excess_liquidity": 15000,
                "maintenance_margin_required": 75000,
                "initial_margin_required": 80000,
                "gross_position_value": 300000,
                "total_cash_value": -10000,
                "buying_power": 32000,
            },
            generated_at=self.now.isoformat(),
        )
        registry = tower.build_registry({"primary": {"alias": "primary"}})
        self.tower_payload = tower.consolidate(registry, {"primary": snapshot}, reference=self.now)
        self.evaluation = risk.evaluate(self.tower_payload, reference=self.now)
        for alert in self.evaluation["alerts"]:
            alert["first_seen_at"] = (self.now - timedelta(minutes=90)).isoformat()

    def test_acknowledgement_suppresses_notification_until_expiry(self):
        alert_id = self.evaluation["alerts"][0]["alert_id"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "actions.json"
            item = operations.record_action(
                path,
                alert_id=alert_id,
                action="ACKNOWLEDGE",
                reason="Revisado con broker",
                known_alert_ids={alert_id},
                acknowledgement_minutes=60,
                alert_severity="HIGH",
                reference=self.now,
            )
            state = operations.load_json(path)
            active = operations.decorate_evaluation(self.evaluation, state, reference=self.now + timedelta(minutes=30))
            expired = operations.decorate_evaluation(self.evaluation, state, reference=self.now + timedelta(minutes=61))

        active_alert = next(alert for alert in active["alerts"] if alert["alert_id"] == alert_id)
        expired_alert = next(alert for alert in expired["alerts"] if alert["alert_id"] == alert_id)
        self.assertEqual(item["status"], "ACKNOWLEDGE")
        self.assertEqual(active_alert["operational_status"], "ACKNOWLEDGED")
        self.assertFalse(active_alert["notification_eligible"])
        self.assertEqual(expired_alert["operational_status"], "OPEN")
        self.assertTrue(expired_alert["notification_eligible"])

    def test_severity_change_breaks_acknowledgement(self):
        alert = self.evaluation["alerts"][0]
        state = {
            "actions": {
                alert["alert_id"]: {
                    "status": "ACKNOWLEDGE",
                    "alert_severity": "WATCH",
                    "expires_at": (self.now + timedelta(hours=2)).isoformat(),
                }
            }
        }

        decorated = operations.decorate_evaluation(self.evaluation, state, reference=self.now)
        current = next(item for item in decorated["alerts"] if item["alert_id"] == alert["alert_id"])

        self.assertEqual(alert["severity"], "HIGH")
        self.assertEqual(current["operational_status"], "OPEN")
        self.assertTrue(current["notification_eligible"])

    def test_snooze_and_reopen_are_bounded_and_traceable(self):
        alert_id = self.evaluation["alerts"][0]["alert_id"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "actions.json"
            snoozed = operations.record_action(
                path,
                alert_id=alert_id,
                action="SNOOZE",
                snooze_minutes=5000,
                reference=self.now,
            )
            reopened = operations.record_action(
                path,
                alert_id=alert_id,
                action="REOPEN",
                reference=self.now + timedelta(minutes=1),
            )

        self.assertEqual(snoozed["snooze_minutes"], 1440)
        self.assertEqual(reopened["status"], "REOPEN")
        self.assertEqual(reopened["action_count"], 2)
        self.assertFalse(reopened["execution_authorized"])

    def test_unknown_alert_action_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "not active"):
                operations.record_action(
                    Path(tmp) / "actions.json",
                    alert_id="prisk_unknown",
                    action="ACKNOWLEDGE",
                    known_alert_ids={"prisk_other"},
                    reference=self.now,
                )

    def test_outbox_deduplicates_pending_alerts_and_escalates_old_high(self):
        decorated = operations.decorate_evaluation(self.evaluation, {}, reference=self.now)
        outbox, new_items = operations.build_outbox(decorated, {}, reference=self.now)
        repeated, repeated_items = operations.build_outbox(decorated, outbox, reference=self.now + timedelta(minutes=5))

        high_items = [item for item in new_items if item["severity"] == "HIGH"]
        self.assertTrue(high_items)
        self.assertTrue(all(item["notification_type"] == "ESCALATION" for item in high_items))
        self.assertEqual(repeated_items, [])
        self.assertEqual(repeated["pending_count"], outbox["pending_count"])
        self.assertTrue(outbox["sensitive_identifiers_excluded"])

    def test_acknowledged_alert_does_not_enter_outbox(self):
        alert_id = self.evaluation["alerts"][0]["alert_id"]
        open_decorated = operations.decorate_evaluation(self.evaluation, {}, reference=self.now)
        previous_outbox, _ = operations.build_outbox(open_decorated, {}, reference=self.now)
        state = {
            "actions": {
                alert_id: {
                    "status": "ACKNOWLEDGE",
                    "expires_at": (self.now + timedelta(hours=1)).isoformat(),
                }
            }
        }
        decorated = operations.decorate_evaluation(self.evaluation, state, reference=self.now)
        outbox, new_items = operations.build_outbox(
            decorated, previous_outbox, reference=self.now + timedelta(minutes=1)
        )

        self.assertNotIn(alert_id, {item["alert_id"] for item in new_items})
        self.assertFalse(any(
            item.get("alert_id") == alert_id and item.get("status") == "PENDING"
            for item in outbox["items"]
        ))
        self.assertTrue(any(
            item.get("alert_id") == alert_id and item.get("status") == "CANCELLED"
            for item in outbox["items"]
        ))

    def test_digest_is_sanitized_and_human_readable(self):
        decorated = operations.decorate_evaluation(self.evaluation, {}, reference=self.now)
        outbox, _ = operations.build_outbox(decorated, {}, reference=self.now)
        digest, markdown = operations.build_digest(decorated, outbox, reference=self.now)

        self.assertIn("Riesgo de cartera", markdown)
        self.assertIn("Decision support", markdown)
        self.assertEqual(digest["status"], "ACTION_REQUIRED")
        self.assertFalse(digest["execution_authorized"])
        self.assertNotIn('"account_id"', json.dumps(digest))

    def test_monitor_window_respects_timezone_and_weekends(self):
        config = operations.load_config()
        monday_open = datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc)
        sunday = datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)

        self.assertEqual(runner.within_monitor_window(monday_open, config), (True, "ACTIVE_WINDOW"))
        self.assertEqual(runner.within_monitor_window(sunday, config), (False, "WEEKEND"))

    def test_runner_builds_outbox_and_digest_without_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            tower.write_control_tower(runtime / "broker_control_tower_latest.json", self.tower_payload)
            args = argparse.Namespace(
                mode="preflight",
                runtime_dir=str(runtime),
                policy=str(Path(__file__).resolve().parents[1] / "config" / "portfolio_risk_policy.json"),
                operations_config=str(Path(__file__).resolve().parents[1] / "config" / "portfolio_risk_operations.json"),
                refresh_broker=False,
                refresh_timeout=90,
                force_window=False,
                local_notify=False,
            )
            with patch.object(runner, "send_macos_notification") as send:
                result = runner.run_cycle(args, reference=self.now)
            outbox = operations.load_json(runtime / "portfolio_risk_outbox.json")

            self.assertEqual(result["status"], "COMPLETED")
            self.assertFalse(result["local_notifications_enabled"])
            self.assertFalse(result["external_notification_sent"])
            self.assertTrue((runtime / "portfolio_risk_digest_latest.md").exists())
            self.assertGreater(outbox["pending_count"], 0)
            send.assert_not_called()

    def test_five_clean_digest_sessions_unlock_observation_without_enabling_notifications(self):
        outbox = {
            "items": [],
            "pending_count": 0,
            "sensitive_identifiers_excluded": True,
            "execution_authorized": False,
            "automatic_liquidation_authorized": False,
        }
        cycle = {
            "status": "COMPLETED",
            "local_notifications_enabled": False,
            "external_notification_sent": False,
            "execution_authorized": False,
            "automatic_liquidation_authorized": False,
        }
        config = operations.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observation.json"
            first = operations.record_observation_session(
                path,
                tower=self.tower_payload,
                evaluation=self.evaluation,
                outbox=outbox,
                cycle=cycle,
                config=config,
                reference=self.now,
            )
            repeated = operations.record_observation_session(
                path,
                tower=self.tower_payload,
                evaluation=self.evaluation,
                outbox=outbox,
                cycle=cycle,
                config=config,
                reference=self.now + timedelta(hours=1),
            )
            for offset in range(1, 5):
                final = operations.record_observation_session(
                    path,
                    tower=self.tower_payload,
                    evaluation=self.evaluation,
                    outbox=outbox,
                    cycle=cycle,
                    config=config,
                    reference=self.now + timedelta(days=offset),
                )

        self.assertEqual(first["observed_session_count"], 1)
        self.assertEqual(repeated["observed_session_count"], 1)
        self.assertEqual(final["status"], "READY_TO_ENABLE_LOCAL_NOTIFICATIONS")
        self.assertEqual(final["consecutive_clean_sessions"], 5)
        self.assertTrue(final["ready_to_enable_local_notifications"])
        self.assertFalse(final["local_notifications_enabled"])

    def test_weekend_digest_does_not_count_as_observation_session(self):
        outbox = {
            "items": [],
            "pending_count": 0,
            "sensitive_identifiers_excluded": True,
            "execution_authorized": False,
            "automatic_liquidation_authorized": False,
        }
        cycle = {
            "status": "COMPLETED",
            "local_notifications_enabled": False,
            "external_notification_sent": False,
            "execution_authorized": False,
            "automatic_liquidation_authorized": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = operations.record_observation_session(
                Path(tmp) / "observation.json",
                tower=self.tower_payload,
                evaluation=self.evaluation,
                outbox=outbox,
                cycle=cycle,
                config=operations.load_config(),
                reference=datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc),
            )

        self.assertFalse(result["recorded"])
        self.assertEqual(result["observed_session_count"], 0)
        self.assertEqual(result["record_reason"], "NON_TRADING_WEEKDAY")

    def test_local_opt_in_delivers_existing_pending_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            tower.write_control_tower(runtime / "broker_control_tower_latest.json", self.tower_payload)
            base = dict(
                mode="preflight",
                runtime_dir=str(runtime),
                policy=str(Path(__file__).resolve().parents[1] / "config" / "portfolio_risk_policy.json"),
                operations_config=str(Path(__file__).resolve().parents[1] / "config" / "portfolio_risk_operations.json"),
                refresh_broker=False,
                refresh_timeout=90,
                force_window=False,
            )
            runner.run_cycle(argparse.Namespace(**base, local_notify=False), reference=self.now)
            with patch.object(runner, "send_macos_notification", return_value={"sent": True, "provider": "test"}) as send:
                result = runner.run_cycle(
                    argparse.Namespace(**base, local_notify=True),
                    reference=self.now + timedelta(minutes=5),
                )
            outbox = operations.load_json(runtime / "portfolio_risk_outbox.json")

        self.assertTrue(result["local_notifications_enabled"])
        self.assertGreater(send.call_count, 0)
        self.assertEqual(outbox["pending_count"], 0)
        self.assertTrue(any(item.get("status") == "DELIVERED_LOCAL" for item in outbox["items"]))

    def test_exclusive_lock_prevents_overlapping_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cycle.lock"
            with runner.exclusive_operation_lock(path) as first:
                with runner.exclusive_operation_lock(path) as second:
                    self.assertTrue(first)
                    self.assertFalse(second)

    def test_launchd_is_secret_free_and_local_notifications_are_opt_in(self):
        default = installer.plist_payload(installer.JOBS["monitor"])
        enabled = installer.plist_payload(installer.JOBS["monitor"], enable_local_notifications=True)
        encoded = json.dumps(default)

        self.assertEqual(default["StartInterval"], 300)
        self.assertEqual(default["WorkingDirectory"], str(installer.RUNNER_DIR))
        self.assertIn(str(installer.RUNNER_PATH), default["ProgramArguments"])
        self.assertIn("portfolio-risk-monitor", default["ProgramArguments"])
        self.assertNotIn("--local-notify", default["ProgramArguments"])
        self.assertIn("--local-notify", enabled["ProgramArguments"])
        self.assertNotIn("TOKEN", encoded.upper())
        self.assertNotIn("PASSWORD", encoded.upper())
        self.assertNotIn("SECRET", encoded.upper())
        digest = installer.plist_payload(installer.JOBS["digest"])
        preflight = installer.plist_payload(installer.JOBS["preflight"])
        self.assertEqual([item["Weekday"] for item in digest["StartCalendarInterval"]], [1, 2, 3, 4, 5])
        self.assertEqual([item["Weekday"] for item in preflight["StartCalendarInterval"]], [1, 2, 3, 4, 5])

    def test_console_bridge_commands_preserve_silent_defaults(self):
        monitor = account_console.portfolio_risk_operations_command("monitor", refresh_broker=True)
        preflight = account_console.portfolio_risk_operations_command("preflight")

        self.assertIn("--refresh-broker", monitor)
        self.assertNotIn("--local-notify", monitor)
        self.assertNotIn("--refresh-broker", preflight)

    def test_operations_sources_never_place_orders_or_send_external_email(self):
        root = Path(__file__).resolve().parents[1]
        source = "\n".join([
            (root / "portfolio_risk_operations.py").read_text(),
            (root / "scripts" / "run_portfolio_risk_operations.py").read_text(),
            (root / "scripts" / "install_portfolio_risk_launchd.py").read_text(),
        ])
        self.assertNotIn("placeOrder", source)
        self.assertNotIn("send_resend_email", source)
        self.assertNotIn("urllib.request", source)
        self.assertIn("automatic_liquidation_authorized", source)

    def test_console_exposes_human_actions_and_operations_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            original_values = {
                "RUNTIME": account_console.RUNTIME,
                "CONTROL_TOWER_PATH": account_console.CONTROL_TOWER_PATH,
                "PORTFOLIO_RISK_ACTIONS_PATH": account_console.PORTFOLIO_RISK_ACTIONS_PATH,
                "PORTFOLIO_RISK_OUTBOX_PATH": account_console.PORTFOLIO_RISK_OUTBOX_PATH,
                "PORTFOLIO_RISK_OPERATIONS_STATUS_PATH": account_console.PORTFOLIO_RISK_OPERATIONS_STATUS_PATH,
                "PORTFOLIO_RISK_DIGEST_PATH": account_console.PORTFOLIO_RISK_DIGEST_PATH,
                "PORTFOLIO_RISK_OBSERVATION_PATH": account_console.PORTFOLIO_RISK_OBSERVATION_PATH,
            }
            account_console.RUNTIME = runtime
            account_console.CONTROL_TOWER_PATH = runtime / "broker_control_tower_latest.json"
            account_console.PORTFOLIO_RISK_ACTIONS_PATH = runtime / "portfolio_risk_actions.json"
            account_console.PORTFOLIO_RISK_OUTBOX_PATH = runtime / "portfolio_risk_outbox.json"
            account_console.PORTFOLIO_RISK_OPERATIONS_STATUS_PATH = runtime / "portfolio_risk_operations_status.json"
            account_console.PORTFOLIO_RISK_DIGEST_PATH = runtime / "portfolio_risk_digest_latest.json"
            account_console.PORTFOLIO_RISK_OBSERVATION_PATH = runtime / "portfolio_risk_observation.json"
            tower.write_control_tower(account_console.CONTROL_TOWER_PATH, self.tower_payload)
            for alias in ["primary"]:
                snapshot = tower.account_snapshot(
                    broker="IBKR", alias=alias, scope=alias,
                    capacity=self.tower_payload["accounts"][0]["capacity"],
                    generated_at=self.now.isoformat(),
                )
                tower.write_snapshot(runtime, snapshot)
            tower.write_control_tower(account_console.PORTFOLIO_RISK_OUTBOX_PATH, {
                "pending_count": 2, "sensitive_identifiers_excluded": True,
            })
            tower.write_control_tower(account_console.PORTFOLIO_RISK_OBSERVATION_PATH, {
                "status": "OBSERVING",
                "consecutive_clean_sessions": 2,
                "remaining_clean_sessions": 3,
                "target_sessions": 5,
            })
            try:
                risk_html = account_console.render_portfolio_risk_panel(
                    {"primary": {"alias": "primary"}}, {"account_alias": "primary"}
                )
                operations_html = account_console.render_portfolio_operations_panel()
            finally:
                for key, value in original_values.items():
                    setattr(account_console, key, value)

        self.assertIn("/portfolio-risk-action", risk_html)
        self.assertIn("Confirmar que lo revisé", risk_html)
        self.assertIn("Recordar en 60 min", risk_html)
        self.assertIn("Operación y mantenimiento", operations_html)
        self.assertIn("Outbox pendiente", operations_html)
        self.assertIn("Observación", operations_html)
        self.assertIn("2/5", operations_html)
        self.assertIn("Ejecutar mantenimiento ahora", operations_html)

    def test_console_routes_actions_outbox_and_operations(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "ibkr_account_profile.py").read_text()
        self.assertIn('path == "/portfolio-risk-outbox"', source)
        self.assertIn('path == "/portfolio-risk-operations"', source)
        self.assertIn('self.path == "/portfolio-risk-action"', source)
        self.assertIn('self.path == "/portfolio-risk-operations-run"', source)
        self.assertIn("known_alert_ids=known_alert_ids", source)


if __name__ == "__main__":
    unittest.main()
