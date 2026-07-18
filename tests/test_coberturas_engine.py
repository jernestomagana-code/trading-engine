import json
import tempfile
import unittest
from pathlib import Path

import coberturas_engine as ce


class CoberturasEngineTests(unittest.TestCase):
    def test_write_manual_context_preserves_guardrails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.json"
            context = ce.write_manual_context(
                {
                    "spot": "213.5",
                    "position_mode": "NO_SHARES",
                    "support_levels": "208.85, 208.01",
                    "resistance_levels": "215,217.5",
                    "expected_move_low": "211.28",
                    "expected_move_high": "214.72",
                    "call_wall": "215",
                    "put_wall": "202.5",
                    "gamma_bias": "positive",
                },
                path=path,
            )
            self.assertEqual(context["ticker"], "RSP")
            self.assertFalse(context["execution_authorized"])
            self.assertTrue(context["not_order_instruction"])
            self.assertEqual(context["support_levels"], [208.01, 208.85])

    def test_gamma_blob_populates_manual_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.json"
            context = ce.write_manual_context(
                {
                    "gamma_blob": (
                        "RSP spot: 213.50\n"
                        "Soportes: 210, 208.85, 208.01\n"
                        "Resistencias: 215, 217.5\n"
                        "Expected move bajo: 211.28\n"
                        "Expected move alto: 214.72\n"
                        "Call wall: 215\n"
                        "Put wall: 202.5\n"
                        "Gamma positivo"
                    ),
                    "position_mode": "NO_SHARES",
                },
                path=path,
            )
            self.assertEqual(context["spot"], 213.5)
            self.assertEqual(context["support_levels"], [208.01, 208.85, 210.0])
            self.assertEqual(context["resistance_levels"], [215.0, 217.5])
            self.assertEqual(context["expected_move_low"], 211.28)
            self.assertEqual(context["expected_move_high"], 214.72)
            self.assertEqual(context["call_wall"], 215.0)
            self.assertEqual(context["put_wall"], 202.5)
            self.assertEqual(context["gamma_bias"], "POSITIVO")
            self.assertIn("RSP spot", context["gamma_blob"])

    def test_recommendation_waits_when_rsp_chain_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({"spot": "213", "position_mode": "NO_SHARES"})
                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original
            self.assertEqual(payload["ticker"], "RSP")
            self.assertEqual(payload["mode"], "SELL_PUT")
            self.assertEqual(payload["decision"], "WAIT_DATA")
            self.assertIn("RSP_OPTION_CHAIN_MISSING", payload["blockers"])
            self.assertFalse(payload["execution_authorized"])

    def test_recommendation_ranks_rsp_put_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context(
                    {
                        "spot": "213",
                        "position_mode": "NO_SHARES",
                        "support_levels": "210,208",
                        "expected_move_low": "211",
                        "put_wall": "202.5",
                    }
                )
                (runtime / "v32_ibkr_chain_coverage.json").write_text(
                    '{"option_rows":[{"ticker":"RSP","strategy":"NAKED_PUT","expiration":"20260724","dte":9,"strike":210,"delta":-0.18,"bid":0.95,"ask":1.05,"open_interest":500}],"chain_by_ticker":{"RSP":{}},"not_order_instruction":true}',
                    encoding="utf-8",
                )
                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original
            self.assertEqual(payload["decision"], "REVIEW_SELL_PUT_CANDIDATES")
            self.assertEqual(payload["candidate_count"], 1)
            self.assertEqual(payload["top_candidates"][0]["premium_100"], 100.0)
            self.assertFalse(payload["top_candidates"][0]["execution_authorized"])

    def test_recommendation_compares_sell_put_and_buy_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({"spot": "214", "position_mode": "NO_SHARES", "call_wall": "220"})
                (runtime / "v32_ibkr_chain_coverage.json").write_text(
                    json.dumps({
                        "option_rows": [
                            {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260724", "dte": 8, "strike": 205, "delta": -0.2, "bid": 0.9, "ask": 1.1},
                            {"ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260724", "dte": 8, "strike": 220, "delta": 0.22, "bid": 0.8, "ask": 1.0},
                        ],
                        "chain_by_ticker": {"RSP": {}},
                        "not_order_instruction": True,
                    }),
                    encoding="utf-8",
                )
                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original
            self.assertTrue(payload["decision"].startswith("RECOMMEND_"))
            self.assertEqual(payload["put_candidate_count"], 1)
            self.assertEqual(payload["call_candidate_count"], 1)
            self.assertTrue(payload["strategy_scenarios"]["sell_put"]["available"])
            self.assertTrue(payload["strategy_scenarios"]["buy_100_sell_call"]["available"])
            self.assertEqual(payload["strategy_scenarios"]["buy_100_sell_call"]["shares"], 100)
            self.assertFalse(payload["strategy_scenarios"]["buy_100_sell_call"]["execution_authorized"])


    def test_recommendation_uses_ibkr_margin_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({"spot": "214", "position_mode": "NO_SHARES"})
                (runtime / "ibkr_account_capacity_latest.json").write_text(
                    json.dumps({"available_funds": 25000, "available": True}),
                    encoding="utf-8",
                )
                (runtime / "v32_ibkr_chain_coverage.json").write_text(
                    json.dumps({
                        "option_rows": [
                            {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260724", "dte": 8, "strike": 205, "delta": -0.2, "bid": 0.9, "ask": 1.1},
                            {"ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260724", "dte": 8, "strike": 220, "delta": 0.22, "bid": 0.8, "ask": 1.0},
                        ],
                        "chain_by_ticker": {"RSP": {}},
                        "not_order_instruction": True,
                    }),
                    encoding="utf-8",
                )
                (runtime / "coberturas_rsp_margin_preview_latest.json").write_text(
                    json.dumps({
                        "status": "MARGIN_PREVIEW_READY",
                        "previews": [
                            {"strategy": "SELL_PUT", "status": "MARGIN_PREVIEW_READY", "init_margin_change": 4000},
                            {"strategy": "BUY_100_SELL_CALL", "status": "MARGIN_PREVIEW_READY", "init_margin_change": 11000},
                        ],
                        "execution_authorized": False,
                        "not_order_instruction": True,
                    }),
                    encoding="utf-8",
                )
                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original
            self.assertTrue(payload["decision"].startswith("RECOMMEND_"))
            self.assertEqual(payload["strategy_recommendation"]["recommended_strategy"], "BUY_100_SELL_CALL")
            self.assertEqual(payload["strategy_scenarios"]["sell_put"]["ibkr_initial_margin_required"], 4000)
            self.assertEqual(payload["strategy_scenarios"]["sell_put"]["decision_capital_source"], "IBKR_WHAT_IF_MARGIN")
            self.assertFalse(payload["strategy_recommendation"]["execution_authorized"])


    def test_gamma_json_blob_is_used_in_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({
                    "position_mode": "NO_SHARES",
                    "gamma_blob": json.dumps({
                        "spot": 214,
                        "technical_levels": {
                            "supports": [210, {"low": 207, "high": 209}],
                            "resistances": [{"low": 219, "high": 221}],
                        },
                        "expected_move": {
                            "low": {"2026-07-24": 211},
                            "high": {"2026-07-24": 216},
                        },
                        "gamma_context": {"call_wall": 220, "put_wall": 205, "bias": "positivo"},
                    }),
                })
                (runtime / "ibkr_account_capacity_latest.json").write_text(
                    json.dumps({"available_funds": 25000, "buying_power": 80000, "available": True}),
                    encoding="utf-8",
                )
                (runtime / "v32_ibkr_chain_coverage.json").write_text(
                    json.dumps({
                        "option_rows": [
                            {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260724", "dte": 8, "strike": 205, "delta": -0.2, "bid": 0.9, "ask": 1.1},
                            {"ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260724", "dte": 8, "strike": 220, "delta": 0.22, "bid": 0.8, "ask": 1.0},
                        ],
                        "chain_by_ticker": {"RSP": {}},
                        "not_order_instruction": True,
                    }),
                    encoding="utf-8",
                )
                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original
            self.assertEqual(payload["manual_context"]["support_levels"], [208.0, 210.0])
            self.assertEqual(payload["manual_context"]["expected_move_high"], 216)
            self.assertTrue(payload["strategy_scenarios"]["buy_100_sell_call"]["success_probability"]["available"])
            self.assertEqual(payload["strategy_scenarios"]["buy_100_sell_call"]["gamma_alignment"]["status"], "SUPPORTIVE")
            self.assertIn("margin_decision_sensitivity", payload["strategy_recommendation"])


    def test_margin_preview_is_not_reported_as_open_position(self):
        runtime_data = {
            "coberturas_rsp_margin_preview_latest.json": {
                "previews": [{
                    "ticker": "RSP",
                    "strategy": "SELL_PUT",
                    "quantity": 1,
                    "what_if": True,
                    "status": "MARGIN_PREVIEW_PARTIAL",
                }]
            },
            "ibkr_account_capacity_latest.json": {"available": True},
        }
        position = ce.extract_position_state(runtime_data, {"position_mode": "AUTO"})
        self.assertEqual(position["state"], "NO_SHARES")
        self.assertEqual(position["open_rsp_options"], [])

    def test_known_but_insufficient_capacity_is_not_called_missing_capital(self):
        scenarios = {
            "sell_put": {
                "available": True,
                "decision_capital_required": 21000,
                "decision_return_on_capital_pct": 0.29,
                "can_afford_by_available_funds": False,
                "can_afford_by_buying_power": False,
            },
            "buy_100_sell_call": {
                "available": True,
                "decision_capital_required": 21480,
                "decision_return_on_capital_pct": 1.26,
                "can_afford_by_available_funds": False,
                "can_afford_by_buying_power": False,
            },
        }
        recommendation = ce.build_strategy_recommendation(scenarios, [])
        self.assertEqual(recommendation["status"], "WAIT_ACCOUNT_CAPACITY")
        self.assertEqual(recommendation["blockers"], ["INSUFFICIENT_ACCOUNT_CAPACITY"])
        self.assertIn("capital conservador si esta calculado", recommendation["reason"])
        self.assertNotIn("CAPITAL_DATA_MISSING", json.dumps(recommendation))


if __name__ == "__main__":
    unittest.main()
