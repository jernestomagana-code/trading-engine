import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import broker_control_tower as tower
import portfolio_risk_engine as risk
import portfolio_risk_store as store
from scripts import ibkr_account_profile as account_console


class PortfolioRiskEngineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc)

    def account_snapshot(self, alias="primary", capacity=None, positions=None, generated_at=None):
        return tower.account_snapshot(
            broker="IBKR",
            alias=alias,
            scope=alias,
            capacity=capacity or {
                "net_liquidation": 100000,
                "available_funds": 40000,
                "excess_liquidity": 50000,
                "maintenance_margin_required": 20000,
                "initial_margin_required": 25000,
                "gross_position_value": 100000,
                "total_cash_value": 10000,
                "buying_power": 160000,
            },
            positions=positions or [],
            generated_at=(generated_at or self.now).isoformat(),
        )

    def payload(self, snapshots):
        registry = tower.build_registry({alias: {"alias": alias} for alias in snapshots})
        return tower.consolidate(registry, snapshots, reference=self.now)

    def test_healthy_account_is_ready_without_alerts(self):
        evaluation = risk.evaluate(self.payload({"primary": self.account_snapshot()}), reference=self.now)

        self.assertEqual(evaluation["status"], "READY")
        self.assertEqual(evaluation["decision_support"], "CLEAR")
        self.assertEqual(evaluation["risk_score"], 0)
        self.assertEqual(evaluation["alerts"], [])

    def test_margin_and_liquidity_breaches_are_explainable_and_critical(self):
        snapshot = self.account_snapshot(capacity={
            "net_liquidation": 100000,
            "available_funds": 4000,
            "excess_liquidity": 9000,
            "maintenance_margin_required": 90000,
            "initial_margin_required": 92000,
            "gross_position_value": 450000,
            "total_cash_value": -200000,
            "buying_power": 10000,
        })

        evaluation = risk.evaluate(self.payload({"primary": snapshot}), reference=self.now)
        rules = {alert["rule"]: alert for alert in evaluation["alerts"]}

        self.assertEqual(evaluation["status"], "BLOCKED")
        self.assertEqual(rules["EXCESS_LIQUIDITY_LOW"]["severity"], "CRITICAL")
        self.assertEqual(rules["AVAILABLE_FUNDS_LOW"]["value"], 0.04)
        self.assertEqual(rules["MAINTENANCE_MARGIN_HIGH"]["threshold"], 0.85)
        self.assertEqual(rules["LEVERAGE_HIGH"]["metric"], "leverage")
        self.assertFalse(rules["LEVERAGE_HIGH"]["automatic_action_authorized"])

    def test_age_is_recomputed_and_old_ready_snapshot_fails_closed(self):
        old = self.account_snapshot(generated_at=self.now - timedelta(minutes=30))
        payload = self.payload({"primary": old})
        payload["status"] = "READY"
        payload["accounts"][0]["refresh_status"] = "READY"
        payload["accounts"][0]["snapshot_age_minutes"] = 0

        evaluation = risk.evaluate(payload, reference=self.now)

        self.assertEqual(evaluation["status"], "BLOCKED")
        self.assertEqual(evaluation["accounts"][0]["refresh_status"], "STALE")
        self.assertIn("ACCOUNT_DATA_NOT_READY", {item["rule"] for item in evaluation["alerts"]})

    def test_unpaired_short_options_are_flagged(self):
        snapshot = self.account_snapshot(positions=[{
            "ticker": "SPY", "security_type": "OPT", "quantity": -1,
            "expiration": "20261218", "strike": 500, "right": "P",
        }])

        evaluation = risk.evaluate(self.payload({"primary": snapshot}), reference=self.now)
        alert = next(item for item in evaluation["alerts"] if item["rule"] == "SHORT_OPTION_EXPOSURE")

        self.assertEqual(alert["severity"], "WATCH")
        self.assertEqual(alert["metric"], "unconfirmed_short_option_contracts")
        self.assertEqual(alert["value"], 1.0)
        self.assertIn("sin cobertura estructural", alert["title"].lower())

    def test_fully_covered_calls_do_not_trigger_short_option_exposure(self):
        snapshot = self.account_snapshot(positions=[
            {"ticker": "NFLX", "security_type": "STK", "quantity": 1000},
            {
                "ticker": "NFLX", "security_type": "OPT", "quantity": -10,
                "expiration": "20260821", "strike": 78, "right": "C", "multiplier": "100",
            },
        ])

        evaluation = risk.evaluate(self.payload({"primary": snapshot}), reference=self.now)
        rules = {item["rule"] for item in evaluation["alerts"]}
        metrics = evaluation["accounts"][0]["metrics"]

        self.assertNotIn("SHORT_OPTION_EXPOSURE", rules)
        self.assertEqual(metrics["short_option_contracts"], 10.0)
        self.assertEqual(metrics["covered_short_call_contracts"], 10.0)
        self.assertEqual(metrics["unconfirmed_short_option_contracts"], 0.0)

    def test_vertical_spread_pairs_short_option_risk(self):
        snapshot = self.account_snapshot(positions=[
            {"ticker": "SPY", "security_type": "OPT", "quantity": -2, "expiration": "20261218", "strike": 500, "right": "P"},
            {"ticker": "SPY", "security_type": "OPT", "quantity": 2, "expiration": "20261218", "strike": 490, "right": "P"},
        ])

        evaluation = risk.evaluate(self.payload({"primary": snapshot}), reference=self.now)
        metrics = evaluation["accounts"][0]["metrics"]

        self.assertNotIn("SHORT_OPTION_EXPOSURE", {item["rule"] for item in evaluation["alerts"]})
        self.assertEqual(metrics["defined_risk_short_option_contracts"], 2.0)
        self.assertEqual(metrics["unconfirmed_short_option_contracts"], 0.0)

    def test_multi_account_nav_concentration_is_detected(self):
        large = self.account_snapshot("large", capacity={
            "net_liquidation": 90000, "available_funds": 40000, "excess_liquidity": 50000,
            "maintenance_margin_required": 10000, "initial_margin_required": 12000,
            "gross_position_value": 80000, "total_cash_value": 10000, "buying_power": 160000,
        })
        small = self.account_snapshot("small", capacity={
            "net_liquidation": 10000, "available_funds": 5000, "excess_liquidity": 7000,
            "maintenance_margin_required": 1000, "initial_margin_required": 1200,
            "gross_position_value": 5000, "total_cash_value": 5000, "buying_power": 20000,
        })

        evaluation = risk.evaluate(self.payload({"large": large, "small": small}), reference=self.now)
        alert = next(item for item in evaluation["alerts"] if item["rule"] == "ACCOUNT_NAV_CONCENTRATION")

        self.assertEqual(alert["account_alias"], "large")
        self.assertEqual(alert["severity"], "HIGH")
        self.assertEqual(alert["value"], 0.9)

    def test_account_override_can_make_a_limit_stricter(self):
        policy = risk.load_policy()
        policy["account_overrides"] = {
            "primary": {"thresholds": {"leverage": {"watch_above": 0.9}}}
        }

        evaluation = risk.evaluate(self.payload({"primary": self.account_snapshot()}), policy, reference=self.now)

        alert = next(item for item in evaluation["alerts"] if item["rule"] == "LEVERAGE_HIGH")
        self.assertEqual(alert["severity"], "WATCH")
        self.assertEqual(alert["threshold"], 0.9)

    def test_invalid_policy_and_missing_metrics_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("not-json")
            policy = risk.load_policy(path)
        incomplete = self.account_snapshot(capacity={"net_liquidation": 1000})

        evaluation = risk.evaluate(self.payload({"primary": incomplete}), policy, reference=self.now)
        rules = {item["rule"] for item in evaluation["alerts"]}

        self.assertEqual(evaluation["status"], "BLOCKED")
        self.assertIn("RISK_POLICY_INVALID", rules)
        self.assertIn("RISK_METRICS_MISSING", rules)

    def test_alert_ids_are_stable(self):
        payload = self.payload({"primary": self.account_snapshot(positions=[{
            "ticker": "QQQ", "security_type": "OPT", "quantity": -1,
        }])})

        first = risk.evaluate(payload, reference=self.now)
        second = risk.evaluate(payload, reference=self.now + timedelta(minutes=1))

        self.assertEqual(first["alerts"][0]["alert_id"], second["alerts"][0]["alert_id"])

    def test_persistence_tracks_open_and_resolved_transitions(self):
        watch_payload = self.payload({"primary": self.account_snapshot(positions=[{
            "ticker": "QQQ", "security_type": "OPT", "quantity": -1,
        }])})
        open_evaluation = risk.evaluate(watch_payload, reference=self.now)
        healthy_evaluation = risk.evaluate(
            self.payload({"primary": self.account_snapshot()}),
            reference=self.now + timedelta(minutes=1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            first = store.persist_evaluation(runtime, open_evaluation)
            repeated = store.persist_evaluation(runtime, open_evaluation)
            resolved = store.persist_evaluation(runtime, healthy_evaluation)
            history = json.loads((runtime / store.HISTORY_FILENAME).read_text())
            latest = json.loads((runtime / store.LATEST_FILENAME).read_text())

        self.assertEqual(first["opened_count"], 1)
        self.assertEqual(repeated["new_event_count"], 0)
        self.assertEqual(resolved["resolved_count"], 1)
        self.assertEqual([item["transition"] for item in history["events"]], ["OPENED", "RESOLVED"])
        self.assertEqual(latest["status"], "READY")

    def test_scripts_preserve_decision_support_only_guardrails(self):
        root = Path(__file__).resolve().parents[1]
        sources = "\n".join([
            (root / "scripts" / "evaluate_portfolio_risk.py").read_text(),
            (root / "scripts" / "refresh_multi_account_control_tower.py").read_text(),
        ])
        self.assertNotIn("placeOrder", sources)
        self.assertIn('"automatic_liquidation_authorized": False', sources)
        self.assertIn('"execution_authorized": False', sources)

    def test_console_renders_risk_alerts_and_safe_refresh(self):
        snapshot = self.account_snapshot(positions=[{
            "ticker": "SPY", "security_type": "OPT", "quantity": -1,
        }])
        payload = self.payload({"primary": snapshot})
        with tempfile.TemporaryDirectory() as tmp:
            original_runtime = account_console.RUNTIME
            original_tower_path = account_console.CONTROL_TOWER_PATH
            account_console.RUNTIME = Path(tmp)
            account_console.CONTROL_TOWER_PATH = account_console.RUNTIME / "broker_control_tower_latest.json"
            tower.write_control_tower(account_console.CONTROL_TOWER_PATH, payload)
            tower.write_snapshot(account_console.RUNTIME, snapshot)
            try:
                rendered = account_console.render_portfolio_risk_panel(
                    {"primary": {"alias": "primary", "account_scope": "primary"}},
                    {"account_alias": "primary"},
                )
            finally:
                account_console.RUNTIME = original_runtime
                account_console.CONTROL_TOWER_PATH = original_tower_path

        self.assertIn("Riesgo de cartera", rendered)
        self.assertIn("Opciones cortas sin cobertura estructural confirmada", rendered)
        self.assertIn("Reevaluar riesgo", rendered)
        self.assertIn("no transmite ni ejecuta órdenes", rendered)

    def test_console_exposes_sanitized_risk_routes(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "ibkr_account_profile.py").read_text()
        self.assertIn('path == "/portfolio-risk"', source)
        self.assertIn('self.path == "/portfolio-risk-refresh"', source)
        self.assertIn("portfolio_risk_refresh_command", source)


if __name__ == "__main__":
    unittest.main()
