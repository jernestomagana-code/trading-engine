import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import broker_control_tower as tower
import portfolio_whatif_engine as whatif
from scripts import ibkr_account_profile as account_console
from scripts import preview_portfolio_rebalance_whatif as runner


class PortfolioWhatIfEngineTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.policy = whatif.load_policy(root / "config" / "portfolio_whatif_policy.json")
        self.rebalance = {
            "preferred_simulation_id": "balanced_relief",
            "candidates": [{
                "candidate_id": "balanced_relief",
                "name": "Alivio combinado",
                "virtual_actions": [
                    {
                        "simulation_action": "VIRTUAL_REDUCTION", "account_alias": "primary",
                        "ticker": "NFLX", "quantity_before": 1000, "quantity_after": 800,
                        "virtual_only": True, "order_created": False,
                    },
                    {
                        "simulation_action": "VIRTUAL_OPTION_CLOSE", "account_alias": "primary",
                        "ticker": "MSFT", "expiration": "20261016", "strike": 335,
                        "right": "P", "quantity_before": -1, "quantity_after": 0,
                        "virtual_only": True, "order_created": False,
                    },
                ],
            }],
        }

    def test_requests_are_reduce_only_and_use_ibkr_whatif_submission_semantics(self):
        result = whatif.build_preview_requests(self.rebalance, self.policy)

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["request_count"], 2)
        self.assertEqual(result["requests"][0]["action"], "SELL")
        self.assertEqual(result["requests"][0]["quantity"], 200.0)
        self.assertEqual(result["requests"][1]["action"], "BUY")
        self.assertTrue(all(row["what_if"] for row in result["requests"]))
        self.assertTrue(all(row["transmit"] for row in result["requests"]))
        self.assertTrue(all(row["transmit_semantics"] == "SUBMIT_WHATIF_PREVIEW_TO_IBKR_NOT_LIVE_ORDER" for row in result["requests"]))
        self.assertTrue(all(row["reduce_only"] for row in result["requests"]))

    def test_increase_or_unproven_virtual_action_is_rejected(self):
        payload = json.loads(json.dumps(self.rebalance))
        payload["candidates"][0]["virtual_actions"][0]["quantity_after"] = 1200
        payload["candidates"][0]["virtual_actions"][1]["virtual_only"] = False

        result = whatif.build_preview_requests(payload, self.policy)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["request_count"], 0)
        self.assertEqual(result["rejected_count"], 2)

    def test_summary_aggregates_independent_margin_and_commission(self):
        request_build = whatif.build_preview_requests(self.rebalance, self.policy)
        previews = [
            {"status": "READY", "commission": 1.0, "init_margin_change": -100, "maintenance_margin_change": -80},
            {"status": "READY", "commission": 2.0, "init_margin_change": -200, "maintenance_margin_change": -150},
        ]

        result = whatif.summarize(
            request_build, previews, open_orders_before=2, open_orders_after=2,
            open_order_fingerprint_unchanged=True,
            reference=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["estimated_commission_total"], 3.0)
        self.assertEqual(result["independent_maintenance_margin_change_sum"], -230.0)
        self.assertEqual(result["orders_created"], 0)
        self.assertTrue(result["margin_changes_are_independent_not_portfolio_combined"])

    def test_open_order_change_is_a_safety_violation(self):
        request_build = whatif.build_preview_requests(self.rebalance, self.policy)

        result = whatif.summarize(
            request_build, [{"status": "READY"}], open_orders_before=1, open_orders_after=2,
            open_order_fingerprint_unchanged=False,
        )

        self.assertEqual(result["status"], "SAFETY_VIOLATION")
        self.assertIsNone(result["orders_created"])

    def test_timeout_only_result_explains_tws_precaution_confirmation(self):
        request_build = whatif.build_preview_requests(self.rebalance, self.policy)
        result = whatif.summarize(
            request_build,
            [
                {"status": "FAILED", "error": "TimeoutError"},
                {"status": "FAILED", "error": "TimeoutError"},
            ],
            open_orders_before=0,
            open_orders_after=0,
            open_order_fingerprint_unchanged=True,
        )

        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["operator_state"], "TWS_CONFIRMATION_REQUIRED")
        self.assertTrue(result["tws_precaution_confirmation_likely"])
        self.assertIn("precauciones", result["operator_message"])

    def test_runner_redacts_real_account_and_has_hard_guards(self):
        error = runner.safe_error(RuntimeError("failed for REAL_ACCOUNT"), ["REAL_ACCOUNT"])
        source = (Path(__file__).resolve().parents[1] / "scripts" / "preview_portfolio_rebalance_whatif.py").read_text()

        self.assertNotIn("REAL_ACCOUNT", error)
        self.assertIn("[ACCOUNT_ID_REDACTED]", error)
        self.assertIn("readonly=False", source)
        self.assertIn("whatIf=True", source)
        self.assertIn("transmit=True", source)
        self.assertIn("ib.whatIfOrder", source)
        self.assertIn("open_order_fingerprint", source)
        self.assertNotIn("ib.placeOrder", source)

    def test_console_renders_official_preview_and_safe_form(self):
        payload = whatif.summarize(
            whatif.build_preview_requests(self.rebalance, self.policy),
            [{
                "status": "READY", "ticker": "NFLX", "action": "SELL", "account_alias": "primary",
                "security_type": "STK", "quantity": 200, "init_margin_change": -1000,
                "maintenance_margin_change": -800, "commission": 1.25,
            }],
            open_orders_before=0, open_orders_after=0, open_order_fingerprint_unchanged=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            original_whatif = account_console.PORTFOLIO_WHATIF_PATH
            original_rebalance = account_console.PORTFOLIO_REBALANCE_PATH
            account_console.PORTFOLIO_WHATIF_PATH = Path(tmp) / "whatif.json"
            account_console.PORTFOLIO_REBALANCE_PATH = Path(tmp) / "rebalance.json"
            tower.write_control_tower(account_console.PORTFOLIO_WHATIF_PATH, payload)
            tower.write_control_tower(account_console.PORTFOLIO_REBALANCE_PATH, self.rebalance)
            try:
                rendered = account_console.render_portfolio_whatif_panel(
                    {"primary": {"alias": "primary"}}, {"account_alias": "primary"}
                )
            finally:
                account_console.PORTFOLIO_WHATIF_PATH = original_whatif
                account_console.PORTFOLIO_REBALANCE_PATH = original_rebalance

        self.assertIn("Validación oficial IBKR what-if", rendered)
        self.assertIn("Margen y comisiones sin transmitir órdenes", rendered)
        self.assertIn("whatIf=true y transmit=true solo para procesar el preview", rendered)
        self.assertIn("Validar margen y comisión", rendered)

    def test_console_renders_tws_confirmation_notice(self):
        payload = whatif.summarize(
            whatif.build_preview_requests(self.rebalance, self.policy),
            [{"status": "FAILED", "ticker": "NFLX", "error": "TimeoutError"}],
            open_orders_before=0,
            open_orders_after=0,
            open_order_fingerprint_unchanged=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            original_whatif = account_console.PORTFOLIO_WHATIF_PATH
            original_rebalance = account_console.PORTFOLIO_REBALANCE_PATH
            account_console.PORTFOLIO_WHATIF_PATH = Path(tmp) / "whatif.json"
            account_console.PORTFOLIO_REBALANCE_PATH = Path(tmp) / "rebalance.json"
            tower.write_control_tower(account_console.PORTFOLIO_WHATIF_PATH, payload)
            tower.write_control_tower(account_console.PORTFOLIO_REBALANCE_PATH, self.rebalance)
            try:
                rendered = account_console.render_portfolio_whatif_panel(
                    {"primary": {"alias": "primary"}}, {"account_alias": "primary"}
                )
            finally:
                account_console.PORTFOLIO_WHATIF_PATH = original_whatif
                account_console.PORTFOLIO_REBALANCE_PATH = original_rebalance

        self.assertIn("Acción requerida en TWS", rendered)
        self.assertIn("posibles órdenes reales futuras", rendered)


if __name__ == "__main__":
    unittest.main()
