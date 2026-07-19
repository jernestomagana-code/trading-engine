import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import broker_control_tower as tower
import portfolio_factor_engine as factors
from scripts import ibkr_account_profile as account_console


def closes(start=100.0, count=50, pattern=(0.01, -0.005, 0.008, -0.002)):
    values = [start]
    for index in range(count - 1):
        values.append(values[-1] * (1 + pattern[index % len(pattern)]))
    return values


class PortfolioFactorEngineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)
        self.policy_path = Path(__file__).resolve().parents[1] / "config" / "portfolio_factor_policy.json"
        self.policy = factors.load_policy(self.policy_path)

    def snapshot(self, alias, positions, nav=100000):
        return tower.account_snapshot(
            broker="IBKR", alias=alias, scope=alias,
            capacity={
                "net_liquidation": nav, "available_funds": nav * 0.4,
                "excess_liquidity": nav * 0.5, "maintenance_margin_required": nav * 0.2,
                "gross_position_value": sum(abs(item.get("market_value") or 0) for item in positions),
            },
            positions=positions, generated_at=self.now.isoformat(),
        )

    def payload(self, snapshots):
        registry = tower.build_registry({alias: {"alias": alias} for alias in snapshots})
        return tower.consolidate(registry, snapshots, reference=self.now)

    def test_factor_history_and_correlations_are_explainable(self):
        series = closes()
        payload = self.payload({
            "growth": self.snapshot("growth", [
                {"ticker": "NFLX", "security_type": "STK", "quantity": 100, "market_value": 50000, "historical_closes": series},
                {"ticker": "MSFT", "security_type": "STK", "quantity": 100, "market_value": 40000, "historical_closes": series},
            ])
        })

        result = factors.evaluate(payload, self.policy, reference=self.now)
        style = next(group for group in result["factor_groups"] if group["group"] == "style")

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["history_coverage_ratio"], 1.0)
        self.assertEqual(result["correlations"][0]["correlation"], 1.0)
        self.assertEqual(result["high_correlation_pair_count"], 1)
        self.assertEqual(style["factors"][0]["label"], "GROWTH")
        self.assertEqual(style["factors"][0]["gross_share"], 1.0)
        self.assertGreater(result["historical_risk"]["observation_count"], 30)
        self.assertFalse(result["execution_authorized"])

    def test_option_greeks_are_aggregated_with_delta_equivalent_exposure(self):
        series = closes(start=400)
        payload = self.payload({
            "options": self.snapshot("options", [{
                "ticker": "MSFT", "security_type": "OPT", "right": "P", "quantity": -1,
                "multiplier": "100", "market_value": -1000, "historical_closes": series,
                "delta": -0.20, "gamma": 0.01, "theta": -1.5, "vega": 0.8, "iv": 0.25,
            }])
        })

        result = factors.evaluate(payload, self.policy, reference=self.now)

        self.assertEqual(result["greeks_coverage_ratio"], 1.0)
        self.assertEqual(result["option_greeks"]["delta_contracts"], 20.0)
        self.assertGreater(result["option_greeks"]["dollar_delta"], 0)
        self.assertEqual(result["option_greeks"]["theta_daily"], 150.0)
        self.assertEqual(result["positions"][0]["exposure_basis"], "DELTA_EQUIVALENT")

    def test_missing_history_and_greeks_degrade_to_partial(self):
        payload = self.payload({
            "primary": self.snapshot("primary", [{
                "ticker": "MSFT", "security_type": "OPT", "right": "P", "quantity": -1,
                "average_cost": 1000, "historical_closes": [400, 401],
            }])
        })

        result = factors.evaluate(payload, self.policy, reference=self.now)

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["history_coverage_ratio"], 0.0)
        self.assertEqual(result["greeks_coverage_ratio"], 0.0)
        self.assertIn("LOW_HISTORY_COVERAGE", result["warnings"])
        self.assertIn("LOW_OPTION_GREEKS_COVERAGE", result["warnings"])

    def test_snapshot_sanitizes_history_and_greeks(self):
        snapshot = self.snapshot("primary", [{
            "ticker": "MSFT", "security_type": "OPT", "quantity": -1,
            "delta": -0.2, "gamma": 0.01, "theta": -1, "vega": 0.5, "iv": 0.3,
            "historical_closes": [100, "bad", 101],
        }])
        position = snapshot["positions"][0]

        self.assertEqual(position["delta"], -0.2)
        self.assertEqual(position["implied_volatility"], 0.3)
        self.assertEqual(position["historical_closes"], [100.0, 101.0])
        self.assertNotIn("account_id", position)

    def test_console_renders_advanced_intelligence_and_safe_routes(self):
        series = closes()
        snapshot = self.snapshot("primary", [
            {"ticker": "NFLX", "security_type": "STK", "quantity": 100, "market_value": 50000, "historical_closes": series},
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
                rendered = account_console.render_portfolio_factor_panel(
                    {"primary": {"alias": "primary"}}, {"account_alias": "primary"}
                )
            finally:
                account_console.RUNTIME = original_runtime
                account_console.CONTROL_TOWER_PATH = original_tower

        self.assertIn("Inteligencia avanzada de cartera", rendered)
        self.assertIn("Historia cubierta", rendered)
        self.assertIn("Greeks agregados", rendered)
        self.assertIn("Recalcular inteligencia", rendered)
        source = (Path(__file__).resolve().parents[1] / "scripts" / "ibkr_account_profile.py").read_text()
        self.assertIn('path == "/portfolio-factors"', source)
        self.assertIn('self.path == "/portfolio-factor-refresh"', source)

    def test_adapter_routes_factor_market_data_without_order_methods(self):
        source = (Path(__file__).resolve().parents[1] / "brokers" / "ibkr_readonly.py").read_text()

        self.assertIn('Stock(ticker, "SMART"', source)
        self.assertIn('quote_contract.exchange = "SMART"', source)
        self.assertNotIn("placeOrder", source)


if __name__ == "__main__":
    unittest.main()
