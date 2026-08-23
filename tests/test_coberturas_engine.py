import json
import tempfile
import unittest
from pathlib import Path

import coberturas_engine as ce


class CoberturasEngineTests(unittest.TestCase):
    def test_generic_wait_context_penalizes_but_does_not_veto_valid_entry(self):
        row = {
            "ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260821",
            "strike": 225, "bid": 1.0, "ask": 1.1, "spread_pct": 9.52,
            "coberturas_score": 80,
        }
        context = {"gamma_blob": json.dumps({
            "possible_mode": "esperar",
            "technical_levels": {"resistances": [225]},
            "gamma_context": {"bias": "positivo"},
        })}

        qualified, rejected = ce.annotate_profit_eligibility(
            [row], "BUY_100_SELL_CALL", 220, context
        )

        self.assertEqual(len(qualified), 1)
        self.assertEqual(rejected, [])
        self.assertIn("MARKET_CONTEXT_CAUTION", qualified[0]["eligibility_soft_cautions"])
        self.assertEqual(qualified[0]["coberturas_score"], 72)

    def test_explicit_market_risk_remains_a_hard_veto(self):
        row = {
            "ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260821",
            "strike": 225, "bid": 1.0, "ask": 1.1, "spread_pct": 9.52,
        }
        context = {"gamma_blob": json.dumps({
            "possible_mode": "esperar",
            "risk_warnings": ["RIESGO DE EVENTO activo: no operar"],
            "technical_levels": {"resistances": [225]},
        })}

        qualified, rejected = ce.annotate_profit_eligibility(
            [row], "BUY_100_SELL_CALL", 220, context
        )

        self.assertEqual(qualified, [])
        self.assertIn("MARKET_RISK_HARD_BLOCK", rejected[0]["eligibility_gate_failures"])

    def test_one_noncritical_failure_creates_near_candidate(self):
        row = {
            "ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260821",
            "strike": 220, "bid": 2.1, "ask": 2.3, "spread_pct": 9.09,
        }

        qualified, rejected = ce.annotate_profit_eligibility(
            [row], "BUY_100_SELL_CALL", 221.06, {"resistance_levels": [222.5]}
        )

        self.assertEqual(qualified, [])
        self.assertTrue(rejected[0]["near_candidate"])
        self.assertEqual(rejected[0]["eligibility_gate_failures"], ["STRIKE_NOT_ALIGNED_WITH_LEVELS"])

    def test_wide_spread_call_cannot_become_recommendation_from_stock_appreciation(self):
        rows = [{
            "ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260821",
            "strike": 225, "bid": 0.05, "ask": 0.30, "spread_pct": 142.86,
            "discarded_for_manual_review": True,
        }]
        context = {
            "resistance_levels": [222.5, 225], "gamma_bias": "POSITIVO",
            "expected_move_high": 222.03, "call_wall": 222.5,
        }

        qualified, rejected = ce.annotate_profit_eligibility(
            rows, "BUY_100_SELL_CALL", 220.72, context
        )

        self.assertEqual(qualified, [])
        self.assertEqual(rejected[0]["executable_premium_estimate"], 5.0)
        self.assertEqual(rejected[0]["theoretical_mid_premium"], 17.5)
        self.assertEqual(rejected[0]["max_profit_estimate"], 433.0)
        self.assertIn("EXECUTION_QUALITY_FAILED", rejected[0]["eligibility_gate_failures"])
        self.assertIn("EXECUTABLE_PREMIUM_BELOW_MINIMUM", rejected[0]["eligibility_gate_failures"])

    def test_expiration_specific_gamma_levels_are_resolved(self):
        context = {
            "gamma_blob": json.dumps({
                "technical_levels": {"trend": "alcista", "supports": [220], "resistances": [222.5, 225]},
                "gamma_context": {
                    "bias": "positivo",
                    "call_wall": {"2026-08-14": 220, "2026-08-21": 222.5},
                    "put_wall": {"2026-08-14": 207.5, "2026-08-21": 210},
                },
                "expected_move": {
                    "2026-08-21": {"low": 219.57, "high": 222.03},
                },
            })
        }

        resolved = ce.context_for_expiration(context, "20260821")

        self.assertEqual(resolved["call_wall"], 222.5)
        self.assertEqual(resolved["put_wall"], 210)
        self.assertEqual(resolved["expected_move_high"], 222.03)
        self.assertEqual(resolved["technical_trend"], "ALCISTA")

    def test_minimum_profit_filter_rejects_low_profit_options(self):
        rows = [
            {"strike": 210, "expiration": "20260821", "bid": 0.75, "ask": 0.85, "spread_pct": 12.5},
            {"strike": 207.5, "expiration": "20260821", "bid": 1.10, "ask": 1.20, "spread_pct": 8.7},
        ]

        qualified, rejected = ce.annotate_profit_eligibility(
            rows, "SELL_PUT", 212, {"support_levels": [210]}
        )

        self.assertEqual(len(qualified), 1)
        self.assertEqual(qualified[0]["max_profit_estimate"], 110)
        self.assertTrue(qualified[0]["meets_minimum_max_profit"])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["max_profit_estimate"], 75)
        self.assertIn("MAX_PROFIT_BELOW_MINIMUM", rejected[0]["coberturas_blockers"])

    def test_minimum_profit_filter_uses_total_buy_write_profit(self):
        rows = [
            {"strike": 210, "expiration": "20260821", "bid": 2.50, "ask": 2.70, "spread_pct": 7.7},
            {"strike": 213, "expiration": "20260821", "bid": 1.00, "ask": 1.10, "spread_pct": 9.5},
        ]

        qualified, rejected = ce.annotate_profit_eligibility(
            rows, "BUY_100_SELL_CALL", 212, {"resistance_levels": [210]}
        )

        self.assertEqual(len(qualified), 1)
        self.assertEqual(qualified[0]["max_profit_estimate"], 200)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["max_profit_estimate"], 50)

    def test_itm_buy_write_includes_stock_loss_below_entry_in_max_profit(self):
        scenario = ce.build_buy_write_scenario(
            {"strike": 210, "expiration": "20260731", "dte": 11, "premium_100": 400, "delta": 0.7},
            213,
        )

        self.assertEqual(scenario["moneyness"], "ITM")
        self.assertEqual(scenario["max_profit_if_called"], 100)
        self.assertEqual(scenario["breakeven"], 209)

    def test_covered_call_profiles_consider_itm_and_otm_candidates(self):
        rows = [
            {"strike": 210, "expiration": "20260731", "dte": 11, "premium_100": 500, "delta": 0.72, "spread_pct": 8, "coberturas_score": 60},
            {"strike": 216, "expiration": "20260731", "dte": 11, "premium_100": 100, "delta": 0.28, "spread_pct": 8, "coberturas_score": 90},
        ]

        ranked, methodology = ce.rank_covered_call_candidates(rows, 213)

        self.assertEqual({row["covered_call_evaluation"]["moneyness"] for row in ranked}, {"ITM", "OTM"})
        self.assertTrue(methodology["itm_allowed"])
        self.assertEqual(methodology["candidate_count"], 2)
        self.assertEqual(methodology["profile_winners"]["INCOME_DEFENSIVE"]["moneyness"], "ITM")
        self.assertEqual(methodology["profile_winners"]["UPSIDE_RETENTION"]["moneyness"], "OTM")
        self.assertTrue(methodology["profile_winners"]["INCOME_DEFENSIVE"]["execution_ready_for_review"])
        self.assertEqual(methodology["selection_status"], "READY_FOR_MANUAL_REVIEW")
    def test_dedicated_rsp_positions_detect_covered_call_without_duplicates(self):
        runtime_data = {
            ce.RSP_POSITIONS_PATH: {
                "account_alias": "retiro",
                "positions": [
                    {"ticker": "RSP", "sec_type": "STK", "position_size": 100, "avg_cost": 213.29},
                    {"ticker": "RSP", "sec_type": "OPT", "right": "C", "position_size": -1, "strike": 215, "expiration": "20260731"},
                ],
            },
            "broker_control_tower_latest.json": {
                "positions": [{"ticker": "RSP", "security_type": "STK", "quantity": 100}],
            },
        }

        position = ce.extract_position_state(runtime_data, {"position_mode": "AUTO"})

        self.assertEqual(position["state"], "COVERED_CALL_OPEN")
        self.assertEqual(position["shares"], 100)
        self.assertEqual(position["short_call_count"], 1)

    def test_broker_reconciliation_creates_one_automatic_open_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            journal = runtime / "journal.json"
            state = runtime / "sync.json"
            (runtime / ce.RSP_POSITIONS_PATH).write_text(json.dumps({
                "account_alias": "retiro",
                "positions": [
                    {"ticker": "RSP", "sec_type": "STK", "position_size": 100, "avg_cost": 213.29},
                    {"ticker": "RSP", "sec_type": "OPT", "right": "C", "position_size": -1, "strike": 215, "expiration": "20260731"},
                ],
            }), encoding="utf-8")
            (runtime / ce.RSP_CHAIN_PATH).write_text(json.dumps({
                "option_rows": [{"ticker": "RSP", "strategy": "COVERED_CALL", "right": "C", "strike": 215, "expiration": "20260731"}],
            }), encoding="utf-8")

            first = ce.reconcile_broker_position(runtime, journal, state)
            second = ce.reconcile_broker_position(runtime, journal, state)
            entries = json.loads(journal.read_text())

        self.assertEqual(first["action"], "OPEN_POSITION_RECORDED")
        self.assertEqual(second["action"], "NO_CHANGE")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["strategy"], "BUY_100_SELL_CALL")
        self.assertTrue(entries[0]["matched_motor_candidate"])
        self.assertEqual(entries[0]["source"], "IBKR_AUTO_RECONCILIATION")

    def test_broker_reconciliation_detects_close_without_manual_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            journal = runtime / "journal.json"
            state = runtime / "sync.json"
            positions_path = runtime / ce.RSP_POSITIONS_PATH
            positions_path.write_text(json.dumps({
                "account_alias": "retiro",
                "positions": [
                    {"ticker": "RSP", "sec_type": "STK", "position_size": 100},
                    {"ticker": "RSP", "sec_type": "OPT", "right": "C", "position_size": -1, "strike": 215, "expiration": "20260731"},
                ],
            }), encoding="utf-8")
            ce.reconcile_broker_position(runtime, journal, state)
            positions_path.write_text(json.dumps({"account_alias": "retiro", "positions": []}), encoding="utf-8")

            closed = ce.reconcile_broker_position(runtime, journal, state)
            entries = json.loads(journal.read_text())

        self.assertEqual(closed["action"], "CLOSE_DETECTED")
        self.assertEqual(entries[0]["status"], "CLOSED_DETECTED")
        self.assertEqual(closed["journal"]["pending_outcome_count"], 1)
    def test_rsp_capacity_prefers_dedicated_retirement_account_file(self):
        self.assertEqual(ce.RSP_ACCOUNT_ALIAS, "retiro")
        self.assertEqual(ce.RSP_CAPACITY_PATH, "coberturas_rsp_account_capacity_latest.json")

    def test_fresh_control_tower_retirement_capacity_overrides_old_rsp_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original_context = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({"spot": "213", "position_mode": "AUTO", "support_levels": "207.5", "resistance_levels": "215"})
                (runtime / ce.RSP_POSITIONS_PATH).write_text(json.dumps({
                    "account_alias": "retiro", "positions": [],
                }))
                (runtime / ce.RSP_CAPACITY_PATH).write_text(json.dumps({
                    "available": True,
                    "account_alias": "retiro",
                    "available_funds": 8000,
                    "buying_power": 8000,
                    "generated_at": "2026-08-07T18:00:00+00:00",
                }))
                (runtime / "broker_control_tower_latest.json").write_text(json.dumps({
                    "status": "READY",
                    "accounts": [{
                        "account_alias": "retiro",
                        "account_scope": "retiro",
                        "refresh_status": "READY",
                        "generated_at": "2026-08-08T15:16:04+00:00",
                        "capacity": {"available_funds": 6000, "buying_power": 20000},
                    }],
                }))
                (runtime / ce.RSP_CHAIN_PATH).write_text(json.dumps({
                    "generated_at": ce.now_iso(),
                    "chain_by_ticker": {"RSP": {}},
                    "option_rows": [
                        {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260821", "dte": 11, "strike": 207.5, "delta": -0.2, "bid": 1.0, "ask": 1.1},
                        {"ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260821", "dte": 11, "strike": 215, "delta": 0.3, "bid": 1.0, "ask": 1.1},
                    ],
                }))

                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original_context

        self.assertEqual(payload["ibkr"]["available_funds"], 6000)
        self.assertEqual(payload["ibkr"]["capacity_source"], "BROKER_CONTROL_TOWER_RSP_ACCOUNT")
        self.assertFalse(payload["new_entry_lane"]["can_review_new_entry"])
        self.assertEqual(payload["strategy_recommendation"]["status"], "WAIT_ACCOUNT_CAPACITY")

    def test_open_rsp_cycle_is_managed_while_another_entry_is_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original_context = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({"spot": "213", "position_mode": "AUTO", "support_levels": "207.5", "resistance_levels": "215"})
                (runtime / ce.RSP_POSITIONS_PATH).write_text(json.dumps({
                    "account_alias": "retiro",
                    "positions": [
                        {"ticker": "RSP", "sec_type": "STK", "position_size": 100, "market_price": 213},
                        {"ticker": "RSP", "sec_type": "OPT", "right": "C", "position_size": -1, "strike": 215, "expiration": "20260731"},
                    ],
                }), encoding="utf-8")
                (runtime / ce.RSP_CAPACITY_PATH).write_text(json.dumps({
                    "available": True,
                    "account_alias": "retiro",
                    "available_funds": 25000,
                    "buying_power": 25000,
                }), encoding="utf-8")
                (runtime / ce.RSP_CHAIN_PATH).write_text(json.dumps({
                    "generated_at": ce.now_iso(),
                    "chain_by_ticker": {"RSP": {}},
                    "option_rows": [
                        {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260731", "dte": 11, "strike": 207.5, "delta": -0.2, "bid": 1.0, "ask": 1.1},
                        {"ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260731", "dte": 11, "strike": 215, "delta": 0.3, "bid": 1.0, "ask": 1.1},
                    ],
                }), encoding="utf-8")

                payload = ce.build_recommendation(runtime)
                (runtime / ce.RSP_CAPACITY_PATH).write_text(json.dumps({
                    "available": True,
                    "account_alias": "retiro",
                    "available_funds": 1000,
                    "buying_power": 1000,
                }), encoding="utf-8")
                capacity_limited = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original_context

        self.assertEqual(payload["mode"], "MANAGE_OPEN_POSITION")
        self.assertEqual(payload["decision"], "MANAGE_EXISTING_AND_REVIEW_NEW_ENTRY")
        self.assertTrue(payload["strategy_recommendation"]["status"].startswith("RECOMMEND_"))
        self.assertEqual(payload["candidate_count"], 2)
        self.assertNotIn("OPEN_RSP_OPTION_REQUIRES_MANAGEMENT", payload["blockers"])
        self.assertTrue(payload["new_entry_lane"]["evaluated_independently_from_management"])
        self.assertEqual(payload["new_entry_lane"]["cycle_capacity"]["active_cycles"], 1)
        self.assertEqual(payload["new_entry_lane"]["cycle_capacity"]["remaining_risk_slots"], 2)
        self.assertEqual(capacity_limited["decision"], "MANAGE_EXISTING_AND_WAIT_NEW_ENTRY_CAPACITY")
        self.assertFalse(capacity_limited["new_entry_lane"]["can_review_new_entry"])
        self.assertIn(capacity_limited["new_entry_lane"]["conditional_strategy"], {"SELL_PUT", "BUY_100_SELL_CALL"})
        self.assertEqual(capacity_limited["new_entry_lane"]["strategy_role"], "CONDITIONAL_PREFERENCE")

    def test_configured_margin_estimate_is_separate_from_nominal_exposure(self):
        scenarios = {
            "sell_put": {
                "available": True,
                "cash_secured_notional": 21000,
                "max_profit": 100,
            }
        }
        updated = ce.apply_margin_previews(
            scenarios,
            {"status": "MARGIN_PREVIEW_INCOMPLETE", "previews": []},
            {"available_funds": 8000, "buying_power": 8000},
        )
        sell_put = updated["sell_put"]
        self.assertEqual(sell_put["nominal_exposure"], 21000)
        self.assertEqual(sell_put["decision_capital_required"], 7000)
        self.assertEqual(sell_put["estimated_margin_required"], 7000)
        self.assertEqual(sell_put["decision_capital_source"], "CONFIGURED_MARGIN_ESTIMATE")
        self.assertTrue(sell_put["can_afford_by_available_funds"])

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
                    '{"option_rows":[{"ticker":"RSP","strategy":"NAKED_PUT","expiration":"20260724","dte":9,"strike":210,"delta":-0.18,"bid":1.00,"ask":1.05,"open_interest":500}],"chain_by_ticker":{"RSP":{}},"not_order_instruction":true}',
                    encoding="utf-8",
                )
                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original
            self.assertEqual(payload["decision"], "REVIEW_SELL_PUT_CANDIDATES")
            self.assertEqual(payload["candidate_count"], 1)
            self.assertEqual(payload["top_candidates"][0]["executable_premium_estimate"], 100.0)
            self.assertFalse(payload["top_candidates"][0]["execution_authorized"])

    def test_recommendation_never_presents_out_of_window_row_as_current_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({"spot": "213", "position_mode": "NO_SHARES", "support_levels": "210"})
                (runtime / "v32_ibkr_chain_coverage.json").write_text(
                    json.dumps({
                        "option_rows": [
                            {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260828", "dte": 40, "strike": 195, "delta": -0.09, "bid": 0.45, "ask": 0.51},
                        ],
                        "chain_by_ticker": {"RSP": {}},
                        "not_order_instruction": True,
                    }),
                    encoding="utf-8",
                )
                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original
            self.assertEqual(payload["decision"], "WAIT_DATA")
            self.assertEqual(payload["candidate_count"], 0)
            self.assertEqual(payload["top_candidates"], [])
            self.assertEqual(payload["diagnostic_candidate_count"], 1)
            self.assertIn("RSP_7_14_DTE_CANDIDATES_MISSING", payload["blockers"])

    def test_dedicated_rsp_chain_survives_newer_empty_general_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({"spot": "213", "position_mode": "NO_SHARES", "support_levels": "210"})
                (runtime / ce.RSP_CHAIN_PATH).write_text(json.dumps({
                    "generated_at": ce.now_iso(),
                    "option_rows": [
                        {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260731", "dte": 11, "strike": 210, "delta": -0.18, "bid": 1.0, "ask": 1.05},
                    ],
                    "chain_by_ticker": {"RSP": {}},
                }), encoding="utf-8")
                (runtime / "v32_ibkr_chain_coverage.json").write_text(json.dumps({
                    "generated_at": ce.now_iso(),
                    "option_rows": [],
                    "chain_by_ticker": {},
                }), encoding="utf-8")
                payload = ce.build_recommendation(runtime)
            finally:
                ce.MANUAL_CONTEXT_PATH = original
            self.assertTrue(payload["ibkr"]["chain_has_rsp"])
            self.assertEqual(payload["ibkr"]["chain_coverage_source"], ce.RSP_CHAIN_PATH)
            self.assertEqual(payload["candidate_count"], 1)

    def test_recommendation_compares_sell_put_and_buy_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original = ce.MANUAL_CONTEXT_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            try:
                ce.write_manual_context({"spot": "214", "position_mode": "NO_SHARES", "support_levels": "205", "call_wall": "220"})
                (runtime / "v32_ibkr_chain_coverage.json").write_text(
                    json.dumps({
                        "option_rows": [
                            {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260724", "dte": 8, "strike": 205, "delta": -0.2, "bid": 1.0, "ask": 1.1},
                            {"ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260724", "dte": 8, "strike": 220, "delta": 0.22, "bid": 1.0, "ask": 1.1},
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
                ce.write_manual_context({"spot": "214", "position_mode": "NO_SHARES", "support_levels": "205", "resistance_levels": "220"})
                (runtime / "ibkr_account_capacity_latest.json").write_text(
                    json.dumps({"available_funds": 25000, "available": True}),
                    encoding="utf-8",
                )
                (runtime / "v32_ibkr_chain_coverage.json").write_text(
                    json.dumps({
                        "option_rows": [
                            {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260724", "dte": 8, "strike": 205, "delta": -0.2, "bid": 1.0, "ask": 1.1},
                            {"ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260724", "dte": 8, "strike": 220, "delta": 0.22, "bid": 1.0, "ask": 1.1},
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
                            {"ticker": "RSP", "strategy": "NAKED_PUT", "expiration": "20260724", "dte": 8, "strike": 205, "delta": -0.2, "bid": 1.0, "ask": 1.1},
                            {"ticker": "RSP", "strategy": "COVERED_CALL", "expiration": "20260724", "dte": 8, "strike": 220, "delta": 0.22, "bid": 1.0, "ask": 1.1},
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

    def test_operating_plan_includes_management_ev_and_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            runtime.mkdir()
            original_context = ce.MANUAL_CONTEXT_PATH
            original_journal = ce.JOURNAL_PATH
            ce.MANUAL_CONTEXT_PATH = runtime / "coberturas_rsp_manual_context.json"
            ce.JOURNAL_PATH = runtime / "coberturas_rsp_journal.json"
            try:
                ce.write_manual_context({
                    "spot": "214",
                    "position_mode": "NO_SHARES",
                    "support_levels": "210,208",
                    "resistance_levels": "220",
                    "expected_move_low": "211",
                    "expected_move_high": "216",
                    "call_wall": "220",
                    "gamma_bias": "positivo",
                })
                (runtime / "ibkr_account_capacity_latest.json").write_text(
                    json.dumps({"available_funds": 25000, "buying_power": 80000, "available": True}),
                    encoding="utf-8",
                )
                (runtime / "coberturas_rsp_journal.json").write_text(
                    json.dumps([
                        {"strategy": "SELL_PUT", "status": "CLOSED", "realized_pnl": 60},
                        {"strategy": "BUY_100_SELL_CALL", "status": "CLOSED", "realized_pnl": -25},
                    ]),
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
                ce.MANUAL_CONTEXT_PATH = original_context
                ce.JOURNAL_PATH = original_journal
            self.assertIn("position_manager", payload)
            self.assertIn("exit_rules", payload)
            self.assertIn("strategy_operating_plan", payload)
            self.assertIn("learning_journal", payload)
            self.assertIn("expected_value", payload["strategy_scenarios"]["sell_put"])
            self.assertIn("composite_success_probability", payload["strategy_scenarios"]["buy_100_sell_call"])
            self.assertEqual(payload["learning_journal"]["closed_count"], 2)
            self.assertFalse(payload["strategy_operating_plan"]["execution_authorized"])

    def test_margin_preview_is_not_reported_as_open_position(self):
        runtime_data = {
            "coberturas_rsp_margin_preview_latest.json": {
                "previews": [
                    {
                        "ticker": "RSP",
                        "strategy": "SELL_PUT",
                        "quantity": 1,
                        "what_if": True,
                        "status": "MARGIN_PREVIEW_PARTIAL",
                    }
                ]
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
        self.assertIn("margen requerido esta estimado", recommendation["reason"])
        self.assertNotIn("CAPITAL_DATA_MISSING", json.dumps(recommendation))

    def test_capacity_is_recovered_from_canonical_snapshot(self):
        runtime_data = {
            "v28_master_snapshot.json": {
                "data": {
                    "account_context": {
                        "available": True,
                        "available_funds": 15.76,
                        "buying_power": 15.76,
                        "net_liquidation": 15.76,
                        "sensitive_identifiers_excluded": True,
                    }
                }
            }
        }
        capacity = ce.extract_account_capacity(runtime_data)
        self.assertEqual(capacity["available_funds"], 15.76)
        self.assertEqual(capacity["buying_power"], 15.76)
        self.assertTrue(capacity["sensitive_identifiers_excluded"])

    def test_manual_context_is_recovered_from_canonical_snapshot(self):
        runtime_data = {
            "v28_master_snapshot.json": {
                "data": {
                    "coberturas_rsp_manual_context": {
                        "context_version": "coberturas_rsp_manual_context_v1",
                        "ticker": "RSP",
                        "spot": 215.15,
                        "support_levels": [214.4],
                        "not_order_instruction": True,
                    }
                }
            }
        }
        context = ce.extract_manual_context(runtime_data)
        self.assertTrue(context["available"])
        self.assertEqual(context["spot"], 215.15)
        self.assertEqual(context["support_levels"], [214.4])


if __name__ == "__main__":
    unittest.main()
