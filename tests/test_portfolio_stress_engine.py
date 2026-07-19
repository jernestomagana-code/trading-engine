import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import broker_control_tower as tower
import portfolio_stress_engine as stress
from brokers.ibkr_readonly import IBKRReadOnlyAdapter
from scripts import ibkr_account_profile as account_console


class PortfolioStressEngineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)
        self.policy = stress.load_policy(Path(__file__).resolve().parents[1] / "config" / "portfolio_stress_policy.json")

    def payload(self, snapshots):
        registry = tower.build_registry({alias: {"alias": alias} for alias in snapshots})
        return tower.consolidate(registry, snapshots, reference=self.now)

    def snapshot(self, alias, nav, positions):
        return tower.account_snapshot(
            broker="IBKR", alias=alias, scope=alias,
            capacity={
                "net_liquidation": nav, "available_funds": nav * 0.4,
                "excess_liquidity": nav * 0.5, "maintenance_margin_required": nav * 0.2,
                "gross_position_value": sum(abs(item.get("market_value") or 0) for item in positions),
            },
            positions=positions, generated_at=self.now.isoformat(),
        )

    def test_multi_account_scenarios_identify_worst_account_and_concentration(self):
        payload = self.payload({
            "growth": self.snapshot("growth", 100000, [
                {"ticker": "QQQ", "security_type": "STK", "quantity": 100, "market_value": 50000},
            ]),
            "income": self.snapshot("income", 50000, [
                {"ticker": "SPY", "security_type": "STK", "quantity": 40, "market_value": 20000},
            ]),
        })

        result = stress.evaluate(payload, self.policy, reference=self.now)
        severe = next(item for item in result["scenarios"] if item["scenario_id"] == "severe_drawdown")

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["valuation_coverage_ratio"], 1.0)
        self.assertEqual(severe["estimated_pnl"], -14000.0)
        self.assertEqual(severe["most_exposed_account"], "growth")
        self.assertEqual(result["concentrations"][0]["ticker"], "QQQ")
        self.assertFalse(result["execution_authorized"])

    def test_options_are_stressed_by_right_and_side(self):
        payload = self.payload({
            "options": self.snapshot("options", 100000, [
                {"ticker": "SPY", "security_type": "OPT", "right": "P", "quantity": -2, "market_value": -2000},
                {"ticker": "QQQ", "security_type": "OPT", "right": "P", "quantity": 1, "market_value": 1000},
            ])
        })

        result = stress.evaluate(payload, self.policy, reference=self.now)
        severe = next(item for item in result["scenarios"] if item["scenario_id"] == "severe_drawdown")

        self.assertEqual(severe["estimated_pnl"], -1000.0)

    def test_average_cost_fallback_is_disclosed_as_partial_coverage(self):
        payload = self.payload({
            "primary": self.snapshot("primary", 100000, [
                {"ticker": "AAPL", "security_type": "STK", "quantity": 10, "average_cost": 200},
            ])
        })

        result = stress.evaluate(payload, self.policy, reference=self.now)

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["valuation_coverage_ratio"], 0.0)
        self.assertEqual(result["estimated_value"], 2000.0)
        self.assertIn("LOW_MARKET_VALUE_COVERAGE", result["warnings"])

    def test_portfolio_normalizer_keeps_market_data_but_redacts_account(self):
        contract = SimpleNamespace(
            symbol="SPY", localSymbol="SPY", secType="STK", currency="USD",
            strike=0, lastTradeDateOrContractMonth="", right="", multiplier="",
        )
        row = SimpleNamespace(
            account="REAL_ACCOUNT", contract=contract, position=5, averageCost=500,
            marketPrice=510, marketValue=2550, unrealizedPNL=50,
        )

        positions = IBKRReadOnlyAdapter._portfolio_positions([row], "REAL_ACCOUNT")
        encoded = json.dumps(positions)

        self.assertEqual(positions[0]["market_value"], 2550)
        self.assertEqual(positions[0]["unrealized_pl"], 50)
        self.assertNotIn("REAL_ACCOUNT", encoded)

    def test_console_renders_stress_scenarios_and_safe_route(self):
        snapshot = self.snapshot("primary", 100000, [
            {"ticker": "QQQ", "security_type": "STK", "quantity": 100, "market_value": 50000},
        ])
        payload = self.payload({"primary": snapshot})
        with tempfile.TemporaryDirectory() as tmp:
            original_runtime = account_console.RUNTIME
            original_tower = account_console.CONTROL_TOWER_PATH
            account_console.RUNTIME = Path(tmp)
            account_console.CONTROL_TOWER_PATH = account_console.RUNTIME / "tower.json"
            tower.write_control_tower(account_console.CONTROL_TOWER_PATH, payload)
            tower.write_snapshot(account_console.RUNTIME, snapshot)
            try:
                rendered = account_console.render_portfolio_stress_panel(
                    {"primary": {"alias": "primary"}}, {"account_alias": "primary"}
                )
            finally:
                account_console.RUNTIME = original_runtime
                account_console.CONTROL_TOWER_PATH = original_tower

        self.assertIn("Estrés y escenarios multicuenta", rendered)
        self.assertIn("Drawdown severo", rendered)
        self.assertIn("Recalcular escenarios", rendered)
        self.assertIn("Sin ejecución automática", rendered)
        source = (Path(__file__).resolve().parents[1] / "scripts" / "ibkr_account_profile.py").read_text()
        self.assertIn('path == "/portfolio-stress"', source)
        self.assertIn('self.path == "/portfolio-stress-refresh"', source)


if __name__ == "__main__":
    unittest.main()
