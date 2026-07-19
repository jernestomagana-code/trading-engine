import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import broker_control_tower as tower
import portfolio_factor_engine as factors
import portfolio_rebalance_engine as rebalance
import portfolio_stress_engine as stress
from scripts import ibkr_account_profile as account_console


def closes(start=100.0, count=50):
    values = [start]
    pattern = (0.01, -0.006, 0.008, -0.003)
    for index in range(count - 1):
        values.append(values[-1] * (1 + pattern[index % len(pattern)]))
    return values


class PortfolioRebalanceEngineTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.now = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)
        self.policy = rebalance.load_policy(root / "config" / "portfolio_rebalance_policy.json")
        self.stress_policy = stress.load_policy(root / "config" / "portfolio_stress_policy.json")
        self.factor_policy = factors.load_policy(root / "config" / "portfolio_factor_policy.json")

    def snapshot(self, alias, positions, nav=100000, excess=40000):
        return tower.account_snapshot(
            broker="IBKR", alias=alias, scope=alias,
            capacity={
                "net_liquidation": nav, "available_funds": excess,
                "excess_liquidity": excess, "maintenance_margin_required": nav * 0.3,
                "initial_margin_required": nav * 0.35,
                "gross_position_value": sum(abs(item.get("market_value") or 0) for item in positions),
                "total_cash_value": nav - sum(abs(item.get("market_value") or 0) for item in positions),
            },
            positions=positions, generated_at=self.now.isoformat(),
        )

    def payload(self, snapshots):
        registry = tower.build_registry({alias: {"alias": alias} for alias in snapshots})
        return tower.consolidate(registry, snapshots, reference=self.now)

    def evaluate(self, payload, **kwargs):
        return rebalance.evaluate(payload, self.policy, self.stress_policy, self.factor_policy, reference=self.now, **kwargs)

    def test_concentration_candidate_reduces_share_with_turnover_cap(self):
        history = closes()
        payload = self.payload({"primary": self.snapshot("primary", [
            {"ticker": "NFLX", "security_type": "STK", "quantity": 1000, "market_value": 80000, "historical_closes": history},
            {"ticker": "TLT", "security_type": "STK", "quantity": 200, "market_value": 20000, "historical_closes": history},
        ])})
        original = copy.deepcopy(payload)

        result = self.evaluate(payload)
        candidate = next(item for item in result["candidates"] if item["candidate_id"] == "concentration_relief")

        self.assertEqual(result["status"], "READY")
        self.assertLess(candidate["metrics"]["top_ticker_share"], result["baseline"]["top_ticker_share"])
        self.assertLessEqual(candidate["turnover_nav_ratio"], 0.25)
        self.assertTrue(candidate["constraints"]["all_satisfied"])
        self.assertTrue(candidate["virtual_actions"][0]["virtual_only"])
        self.assertFalse(candidate["execution_authorized"])
        self.assertEqual(payload, original)

    def test_custom_ticker_reduction_is_virtual_and_parameterized(self):
        history = closes()
        payload = self.payload({"primary": self.snapshot("primary", [
            {"ticker": "NFLX", "security_type": "STK", "quantity": 100, "market_value": 50000, "historical_closes": history},
            {"ticker": "TLT", "security_type": "STK", "quantity": 500, "market_value": 50000, "historical_closes": history},
        ])})

        result = self.evaluate(payload, custom_ticker="NFLX", custom_reduction_pct=10)
        custom = next(item for item in result["candidates"] if item["candidate_id"] == "custom_reduction")

        self.assertEqual(custom["turnover_dollars"], 5000.0)
        self.assertEqual(custom["virtual_actions"][0]["quantity_after"], 90.0)
        self.assertEqual(result["orders_created"], 0)

    def test_option_delta_candidate_closes_whole_virtual_contract(self):
        history = closes(start=100)
        payload = self.payload({"options": self.snapshot("options", [{
            "ticker": "MSFT", "security_type": "OPT", "right": "P", "quantity": -1,
            "multiplier": "100", "market_value": -1000, "historical_closes": history,
            "delta": -0.30, "gamma": 0.01, "theta": -1, "vega": 0.5,
        }], nav=10000, excess=5000)})

        result = self.evaluate(payload)
        candidate = next(item for item in result["candidates"] if item["candidate_id"] == "option_sensitivity_relief")

        self.assertEqual(candidate["virtual_actions"][0]["quantity_after"], 0.0)
        self.assertEqual(candidate["metrics"]["option_dollar_delta"], 0.0)
        self.assertFalse(candidate["virtual_actions"][0]["order_created"])

    def test_liquidity_candidate_improves_low_buffer(self):
        history = closes()
        payload = self.payload({"margin": self.snapshot("margin", [
            {"ticker": "NFLX", "security_type": "STK", "quantity": 1000, "market_value": 80000, "historical_closes": history},
        ], nav=100000, excess=10000)})

        result = self.evaluate(payload)
        candidate = next(item for item in result["candidates"] if item["candidate_id"] == "liquidity_buffer")

        self.assertGreater(
            candidate["metrics"]["minimum_excess_liquidity_ratio"],
            result["baseline"]["minimum_excess_liquidity_ratio"],
        )

    def test_console_renders_simulator_and_custom_safe_action(self):
        history = closes()
        snapshot = self.snapshot("primary", [
            {"ticker": "NFLX", "security_type": "STK", "quantity": 1000, "market_value": 80000, "historical_closes": history},
            {"ticker": "TLT", "security_type": "STK", "quantity": 200, "market_value": 20000, "historical_closes": history},
        ])
        payload = self.payload({"primary": snapshot})
        with tempfile.TemporaryDirectory() as tmp:
            original_runtime = account_console.RUNTIME
            original_tower = account_console.CONTROL_TOWER_PATH
            original_rebalance = account_console.PORTFOLIO_REBALANCE_PATH
            account_console.RUNTIME = Path(tmp)
            account_console.CONTROL_TOWER_PATH = account_console.RUNTIME / "tower.json"
            account_console.PORTFOLIO_REBALANCE_PATH = account_console.RUNTIME / "rebalance.json"
            tower.write_control_tower(account_console.CONTROL_TOWER_PATH, payload)
            tower.write_snapshot(account_console.RUNTIME, snapshot)
            try:
                rendered = account_console.render_portfolio_rebalance_panel(
                    {"primary": {"alias": "primary"}}, {"account_alias": "primary"}
                )
            finally:
                account_console.RUNTIME = original_runtime
                account_console.CONTROL_TOWER_PATH = original_tower
                account_console.PORTFOLIO_REBALANCE_PATH = original_rebalance

        self.assertIn("Simulador de rebalanceo", rendered)
        self.assertIn("Reducir concentración", rendered)
        self.assertIn("Simular solamente", rendered)
        self.assertIn("Órdenes creadas: 0", rendered)
        source = (Path(__file__).resolve().parents[1] / "scripts" / "ibkr_account_profile.py").read_text()
        self.assertIn('path == "/portfolio-rebalance"', source)
        self.assertIn('self.path == "/portfolio-rebalance-simulate"', source)
        self.assertNotIn("placeOrder", (Path(__file__).resolve().parents[1] / "portfolio_rebalance_engine.py").read_text())


if __name__ == "__main__":
    unittest.main()
