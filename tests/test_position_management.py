import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import position_management
import position_management_journal
import position_context_store
import gamma_context_store
import position_state_alerts
import strategy_exit_playbook


class PositionManagementTests(unittest.TestCase):
    def setUp(self):
        self.playbook = strategy_exit_playbook.load_exit_playbook(
            ROOT / "config" / "strategy_exit_playbook_v1.json"
        )

    def snapshot(self, positions, technical):
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "account_context": {
                "available": True,
                "available_funds": 100000,
                "net_liquidation": 150000,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "positions": positions,
            "technical_snapshot": technical,
        }

    def test_short_put_profit_capture_triggers_take_profit_review(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {
                        "ticker": "QQQ",
                        "sec_type": "OPT",
                        "right": "P",
                        "strike": 650,
                        "expiration": "20260731",
                        "position_size": -1,
                        "entry_credit": 4.0,
                        "option_mark": 1.6,
                        "dte": 13,
                        "delta": -0.12,
                    }
                ],
                {
                    "QQQ": {
                        "ticker": "QQQ",
                        "trend": "BULLISH",
                        "price": 670,
                        "support_level": 640,
                        "gamma_wall": 675,
                    }
                },
            ),
            playbook=self.playbook,
        )

        item = payload["positions"][0]

        self.assertEqual(item["strategy"], "CASH_SECURED_PUT")
        self.assertEqual(item["exit_state"], "TAKE_PROFIT_REVIEW")
        self.assertEqual(item["management_action"], "REVIEW_CLOSE_OR_BUY_BACK")
        self.assertEqual(item["premium_capture_pct"], 60.0)
        self.assertEqual(item["thesis"]["status"], "INFERRED")
        self.assertTrue(item["scenario_analysis"]["available"])
        self.assertEqual(payload["battle_plan"]["top_step"]["ticker"], "QQQ")
        self.assertEqual(payload["portfolio_risk"]["short_put_notional"], 65000.0)
        self.assertTrue(item["manual_review_required"])
        self.assertFalse(item["execution_authorized"])
        self.assertTrue(item["not_order_instruction"])

    def test_short_put_below_strike_triggers_assignment_review(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {
                        "ticker": "MSFT",
                        "sec_type": "OPT",
                        "right": "P",
                        "strike": 420,
                        "position_size": -1,
                        "entry_credit": 5.0,
                        "option_mark": 6.2,
                        "dte": 9,
                        "delta": -0.45,
                    }
                ],
                {
                    "MSFT": {
                        "ticker": "MSFT",
                        "trend": "NEUTRAL",
                        "price": 415,
                        "support_level": 400,
                        "gamma_context": {"zero_gamma": 418},
                    }
                },
            ),
            playbook=self.playbook,
        )

        item = payload["positions"][0]

        self.assertEqual(item["exit_state"], "ASSIGNMENT_REVIEW")
        self.assertEqual(item["management_action"], "REVIEW_ASSIGNMENT")
        self.assertIn("SHORT_PUT_UNDERLYING_BELOW_STRIKE", item["blockers"])
        self.assertEqual(payload["status"], "RISK_REVIEW")

    def test_short_put_near_expiration_and_strike_triggers_pin_risk_review(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {
                        "ticker": "MSFT",
                        "sec_type": "OPT",
                        "right": "P",
                        "strike": 420,
                        "position_size": -1,
                        "entry_credit": 5.0,
                        "option_mark": 2.2,
                        "dte": 2,
                        "delta": -0.32,
                    }
                ],
                {
                    "MSFT": {
                        "ticker": "MSFT",
                        "trend": "NEUTRAL",
                        "price": 419.5,
                        "support_level": 400,
                    }
                },
            ),
            playbook=self.playbook,
        )

        item = payload["positions"][0]
        self.assertEqual(item["exit_state"], "ASSIGNMENT_REVIEW")
        self.assertIn("PIN_RISK_NEAR_EXPIRATION", item["blockers"])

    def test_covered_call_itm_into_ex_dividend_window_triggers_early_assignment_review(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {"ticker": "AAPL", "sec_type": "STK", "position_size": 100},
                    {
                        "ticker": "AAPL",
                        "sec_type": "OPT",
                        "right": "C",
                        "strike": 210,
                        "position_size": -1,
                        "entry_credit": 3.0,
                        "option_mark": 2.4,
                        "dte": 5,
                        "delta": 0.58,
                    }
                ],
                {
                    "AAPL": {
                        "ticker": "AAPL",
                        "trend": "NEUTRAL",
                        "price": 212,
                        "resistance_level": 215,
                        "ex_dividend_soon": True,
                    }
                },
            ),
            playbook=self.playbook,
        )

        option_item = [item for item in payload["positions"] if item["strategy"] == "COVERED_CALL"][0]
        self.assertEqual(option_item["exit_state"], "ASSIGNMENT_REVIEW")
        self.assertIn("EARLY_ASSIGNMENT_RISK", option_item["blockers"])

    def test_uncovered_short_call_is_risk_review(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {
                        "ticker": "TSLA",
                        "sec_type": "OPT",
                        "right": "C",
                        "strike": 450,
                        "position_size": -1,
                        "entry_credit": 7.0,
                        "option_mark": 9.0,
                        "dte": 21,
                        "delta": 0.55,
                    }
                ],
                {
                    "TSLA": {
                        "ticker": "TSLA",
                        "trend": "BULLISH",
                        "price": 455,
                        "resistance_level": 460,
                        "gamma_wall": 450,
                    }
                },
            ),
            playbook=self.playbook,
        )

        item = payload["positions"][0]

        self.assertEqual(item["strategy"], "SHORT_CALL_UNCOVERED_REVIEW")
        alternatives = {row["alternative_id"]: row for row in item["management_alternatives"]["alternatives"]}
        self.assertEqual(alternatives["HOLD_MONITOR"]["status"], "RISK_BLOCKED")
        self.assertFalse(alternatives["HOLD_MONITOR"]["is_primary_management_path"])
        self.assertEqual(item["exit_state"], "RISK_REVIEW")
        self.assertEqual(item["management_action"], "REVIEW_RISK")
        self.assertIn("UNCOVERED_SHORT_CALL", item["blockers"])

    def test_no_trigger_with_complete_context_recommends_no_action(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {
                        "ticker": "AAPL",
                        "sec_type": "OPT",
                        "right": "P",
                        "strike": 180,
                        "position_size": -1,
                        "entry_credit": 3.0,
                        "option_mark": 2.4,
                        "dte": 28,
                        "delta": -0.15,
                    }
                ],
                {
                    "AAPL": {
                        "ticker": "AAPL",
                        "trend": "BULLISH",
                        "price": 192,
                        "support_level": 176,
                        "gamma_wall": 190,
                    }
                },
            ),
            playbook=self.playbook,
        )

        item = payload["positions"][0]

        self.assertEqual(item["exit_state"], "MONITOR")
        self.assertEqual(item["management_action"], "NO_ACTION_RECOMMENDED")
        self.assertFalse(item["manual_review_required"])
        self.assertEqual(payload["status"], "MONITOR")

    def test_long_stock_exposes_generic_management_alternatives_with_contracts(self):
        snapshot = self.snapshot(
            [{"ticker": "NFLX", "sec_type": "STK", "position_size": 1000, "avg_cost": 106.58, "market_price": 120}],
            {"NFLX": {"ticker": "NFLX", "trend": "NEUTRAL", "price": 120, "support_level": 112}},
        )
        snapshot["active_position_option_chains"] = {
            "store_version": "active_position_option_chain_store_v1",
            "by_ticker": {
                "NFLX": {
                    "option_rows": [
                        {"ticker": "NFLX", "right": "C", "strike": 125, "expiration": "20260828", "dte": 39, "bid": 2.9, "ask": 3.1, "mid": 3.0, "spread_pct": 6.67, "delta": 0.3},
                        {"ticker": "NFLX", "right": "P", "strike": 110, "expiration": "20260828", "dte": 39, "bid": 1.9, "ask": 2.1, "mid": 2.0, "spread_pct": 10.0, "delta": -0.2},
                    ]
                }
            },
        }

        payload = position_management.build_active_position_management(snapshot, playbook=self.playbook)
        item = payload["positions"][0]
        alternatives = {row["alternative_id"]: row for row in item["management_alternatives"]["alternatives"]}

        self.assertEqual(item["exit_overlay"]["strategy_id"], "LONG_STOCK")
        self.assertNotIn("EXIT_PLAYBOOK_NOT_REGISTERED", item["exit_overlay"]["exit_blockers"])
        self.assertIn(alternatives["COVERED_CALL_PARTIAL"]["contracts"], [2, 3])
        self.assertEqual(alternatives["COVERED_CALL_PARTIAL"]["contract_choices"], [2, 3])
        self.assertEqual(alternatives["COVERED_CALL_FULL"]["contracts"], 10)
        self.assertEqual(alternatives["COVERED_CALL_FULL"]["contract_candidates"][0]["strike"], 125)
        self.assertEqual(alternatives["PROTECTIVE_PUT"]["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertIn("COLLAR", alternatives)
        comparison = item["management_alternatives"]["strategy_comparison"]
        self.assertTrue(comparison["available"])
        self.assertEqual(len(comparison["scenarios"]), 5)
        self.assertIn("balanced", comparison["profile_leaders"])
        self.assertEqual(
            item["management_alternatives"]["recommendation"]["alternative_id"],
            comparison["profile_leaders"]["balanced"]["alternative_id"],
        )
        self.assertGreaterEqual(payload["option_alternatives_summary"]["total_alternatives"], 8)

    def test_bearish_stock_with_intact_support_uses_scenario_winner(self):
        snapshot = self.snapshot(
            [{"ticker": "NFLX", "sec_type": "STK", "position_size": 1000, "market_price": 67.48}],
            {"NFLX": {"ticker": "NFLX", "trend": "BEARISH", "price": 67.48, "support_level": 65.08, "resistance_level": 78.44, "indicators": {"atr_14": 2.82, "rsi_14": 35.4}}},
        )
        snapshot["active_position_option_chains"] = {
            "by_ticker": {"NFLX": {"option_rows": [
                {"ticker": "NFLX", "right": "C", "strike": 65, "expiration": "20260828", "dte": 39, "bid": 4.1, "ask": 4.25, "mid": 4.175, "spread_pct": 3.6, "delta": 0.62},
                {"ticker": "NFLX", "right": "C", "strike": 71, "expiration": "20260828", "dte": 39, "bid": 1.82, "ask": 1.89, "mid": 1.855, "spread_pct": 3.77, "delta": 0.36},
                {"ticker": "NFLX", "right": "P", "strike": 60, "expiration": "20260828", "dte": 39, "bid": 0.7, "ask": 0.78, "mid": 0.74, "spread_pct": 10.8, "delta": -0.15},
            ]}},
        }

        payload = position_management.build_active_position_management(snapshot, playbook=self.playbook)
        management = payload["positions"][0]["management_alternatives"]
        balanced = management["strategy_comparison"]["profile_leaders"]["balanced"]

        self.assertEqual(management["recommendation"]["alternative_id"], balanced["alternative_id"])
        self.assertEqual(payload["positions"][0]["management_action"], "REVIEW_RISK")
        self.assertIn(management["strategy_comparison"]["profile_leaders"]["income_recovery"]["contracts"], [2, 3])
        self.assertLessEqual(management["strategy_comparison"]["scenarios"][0]["price"], 67.48 * 0.80)
        self.assertIn("cinco escenarios", management["recommendation"]["reason"])
        if management["recommendation"]["alternative_id"] == "COLLAR":
            self.assertIsInstance(management["recommendation"]["put_contract"], dict)
            self.assertIn("put de protección", management["recommendation"]["reason"])

    def test_extreme_concentration_overrides_scenario_comparison(self):
        snapshot = self.snapshot(
            [{"ticker": "NFLX", "sec_type": "STK", "position_size": 1000, "market_value": 100000, "market_price": 100}],
            {"NFLX": {"ticker": "NFLX", "price": 100, "trend": "BEARISH", "support_level": 90}},
        )

        payload = position_management.build_active_position_management(snapshot, playbook=self.playbook)
        recommendation = payload["positions"][0]["management_alternatives"]["recommendation"]

        self.assertEqual(recommendation["alternative_id"], "REDUCE_25")
        self.assertEqual(recommendation["confidence"], "HIGH")
        self.assertIn("concentración", recommendation["reason"])

    def test_option_market_price_is_never_used_as_underlying_price(self):
        snapshot = self.snapshot(
                [{"ticker": "MSFT", "sec_type": "OPT", "right": "P", "position_size": -1, "strike": 400, "market_price": 8.95, "option_mark": 8.95, "dte": 20}],
                {},
            )
        snapshot["runtime_data"] = {
            "option_rows.json": {
                "option_rows": [{"ticker": "MSFT", "sec_type": "OPT", "right": "P", "strike": 400, "price": 8.95, "market_price": 8.95}],
            }
        }
        payload = position_management.build_active_position_management(
            snapshot,
            playbook=self.playbook,
        )
        item = payload["positions"][0]

        self.assertIsNone(item["underlying_price"])
        self.assertNotEqual(item["management_action"], "REVIEW_ASSIGNMENT")
        self.assertEqual(item["management_alternatives"]["recommendation"]["alternative_id"], "HOLD_MONITOR")
        self.assertEqual(item["management_alternatives"]["recommendation"]["confidence"], "LOW")

    def test_bearish_long_stock_prioritizes_partial_risk_reduction(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [{"ticker": "NFLX", "sec_type": "STK", "position_size": 1000, "market_price": 67}],
                {"NFLX": {"ticker": "NFLX", "price": 67, "trend": "BEARISH", "support_level": 70}},
            ),
            playbook=self.playbook,
        )

        recommendation = payload["positions"][0]["management_alternatives"]["recommendation"]
        self.assertEqual(recommendation["alternative_id"], "REDUCE_25")
        self.assertEqual(recommendation["confidence"], "HIGH")

    def test_missing_gamma_alone_does_not_force_stock_data_refresh(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [{"ticker": "TLT", "sec_type": "STK", "position_size": 50, "market_price": 84}],
                {"TLT": {"ticker": "TLT", "price": 84, "trend": "NEUTRAL_TO_BEARISH", "support_level": 83, "resistance_level": 88}},
            ),
            playbook=self.playbook,
        )
        item = payload["positions"][0]

        self.assertIn("GAMMA_CONTEXT_MISSING", item["warnings"])
        self.assertEqual(item["management_action"], "NO_ACTION_RECOMMENDED")
        self.assertEqual(item["confidence"], "MEDIUM")
        self.assertIsNone(item["management_alternatives"]["strategy_comparison"]["profile_leaders"]["income_recovery"])

    def test_oversold_stock_prioritizes_hold_over_new_covered_call(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [{"ticker": "TLT", "sec_type": "STK", "position_size": 700, "market_price": 84}],
                {"TLT": {"ticker": "TLT", "price": 84, "trend": "NEUTRAL_TO_BEARISH", "support_level": 83, "resistance_level": 88, "indicators": {"rsi_14": 22}}},
            ),
            playbook=self.playbook,
        )
        recommendation = payload["positions"][0]["management_alternatives"]["recommendation"]

        self.assertEqual(recommendation["alternative_id"], "HOLD_MONITOR")
        self.assertEqual(recommendation["confidence"], "MEDIUM")
        self.assertIn("sobrevendido", recommendation["reason"])

    def test_durable_position_chain_supplies_underlying_price_after_empty_technical_refresh(self):
        snapshot = self.snapshot(
            [{"ticker": "NFLX", "sec_type": "STK", "position_size": 1000, "avg_cost": 106.58}],
            {"NFLX": {"ticker": "NFLX", "trend": "NEUTRAL", "price": None}},
        )
        snapshot["runtime_data"] = {
            "active_position_option_chains_latest.json": {
                "store_version": "active_position_option_chain_store_v1",
                "by_ticker": {
                    "NFLX": {
                        "last_successful_at": "2026-07-20T18:17:30+00:00",
                        "chain_event": {"ticker": "NFLX", "stock_price": 67.415},
                        "option_rows": [
                            {"ticker": "NFLX", "right": "C", "strike": 71, "bid": 1.82, "ask": 1.89, "mid": 1.855, "spread_pct": 3.77},
                        ],
                    }
                },
            }
        }

        payload = position_management.build_active_position_management(snapshot, playbook=self.playbook)
        item = payload["positions"][0]
        alternatives = {row["alternative_id"]: row for row in item["management_alternatives"]["alternatives"]}

        self.assertEqual(item["technical"]["price"], 67.415)
        self.assertTrue(item["management_alternatives"]["underlying_price_available"])
        self.assertEqual(alternatives["REDUCE_25"]["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertEqual(alternatives["COVERED_CALL_FULL"]["contract_candidates"][0]["moneyness"], "OTM")

    def test_covered_call_and_short_put_expose_strategy_specific_paths(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {"ticker": "AAPL", "sec_type": "STK", "position_size": 100, "market_price": 200},
                    {"ticker": "AAPL", "sec_type": "OPT", "right": "C", "position_size": -1, "strike": 205, "option_mark": 2, "entry_credit": 3, "dte": 10},
                    {"ticker": "MSFT", "sec_type": "OPT", "right": "P", "position_size": -1, "strike": 400, "option_mark": 2, "entry_credit": 3, "dte": 10},
                ],
                {
                    "AAPL": {"ticker": "AAPL", "price": 202, "trend": "NEUTRAL"},
                    "MSFT": {"ticker": "MSFT", "price": 410, "trend": "NEUTRAL"},
                },
            ),
            playbook=self.playbook,
        )
        by_strategy = {item["strategy"]: item for item in payload["positions"] if item["strategy"] != "LONG_STOCK"}
        call_ids = {row["alternative_id"] for row in by_strategy["COVERED_CALL"]["management_alternatives"]["alternatives"]}
        put_ids = {row["alternative_id"] for row in by_strategy["CASH_SECURED_PUT"]["management_alternatives"]["alternatives"]}

        self.assertIn("ROLL_CALL", call_ids)
        self.assertIn("ACCEPT_CALLED_AWAY", call_ids)
        self.assertIn("ROLL_PUT", put_ids)
        self.assertIn("ACCEPT_ASSIGNMENT", put_ids)

    def test_fully_covered_stock_never_recommends_uncovering_share_reduction(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {"ticker": "RSP", "sec_type": "STK", "position_size": 100, "market_price": 213, "portfolio_weight_pct": 100},
                    {"ticker": "RSP", "sec_type": "OPT", "right": "C", "position_size": -1, "strike": 215, "option_mark": 1.2, "entry_credit": 1.5, "dte": 11},
                ],
                {"RSP": {"ticker": "RSP", "price": 213, "trend": "NEUTRAL", "support_level": 210, "resistance_level": 215}},
            ),
            playbook=self.playbook,
        )
        stock = next(item for item in payload["positions"] if item["sec_type"] == "STK")
        call = next(item for item in payload["positions"] if item["sec_type"] == "OPT")
        alternatives = {item["alternative_id"]: item for item in stock["management_alternatives"]["alternatives"]}

        self.assertEqual(payload["position_management_version"], "active_position_management_v7")
        self.assertEqual(stock["position_structure"]["state"], "FULLY_COVERED_CALL")
        self.assertEqual(stock["position_structure"]["coverage_pct"], 100.0)
        self.assertEqual(stock["position_structure"]["new_covered_call_capacity_contracts"], 0)
        self.assertEqual(call["strategy"], "COVERED_CALL")
        self.assertIn("one covered-call structure", stock["reasons"][0])
        self.assertEqual(stock["management_alternatives"]["recommendation"]["alternative_id"], "HOLD_MONITOR")
        self.assertEqual(alternatives["REDUCE_25"]["status"], "RISK_BLOCKED_COVERAGE")
        self.assertEqual(alternatives["EXIT_FULL"]["status"], "RISK_BLOCKED_COVERAGE")

    def test_aggregate_short_calls_cannot_each_reuse_the_same_shares(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {"ticker": "NFLX", "sec_type": "STK", "position_size": 100, "market_price": 75},
                    {"ticker": "NFLX", "sec_type": "OPT", "right": "C", "position_size": -1, "strike": 76, "option_mark": 1, "entry_credit": 1.5, "dte": 3},
                    {"ticker": "NFLX", "sec_type": "OPT", "right": "C", "position_size": -1, "strike": 80, "option_mark": 0.5, "entry_credit": 1, "dte": 10},
                ],
                {"NFLX": {"ticker": "NFLX", "price": 75, "trend": "NEUTRAL"}},
            ),
            playbook=self.playbook,
        )

        calls = [item for item in payload["positions"] if item["sec_type"] == "OPT"]
        self.assertEqual({item["strategy"] for item in calls}, {"SHORT_CALL_UNCOVERED_REVIEW"})
        self.assertEqual(calls[0]["position_structure"]["excess_short_call_contracts"], 1)
        self.assertIn("UNCOVERED_SHORT_CALLS_PRESENT", payload["portfolio_risk"]["risk_flags"])

    def test_ibkr_option_average_cost_is_converted_from_contract_to_per_share(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {"ticker": "NFLX", "sec_type": "STK", "position_size": 1000, "market_price": 73.33},
                    {
                        "ticker": "NFLX",
                        "sec_type": "OPT",
                        "right": "C",
                        "position_size": -10,
                        "strike": 76,
                        "expiration": "20260731",
                        "average_cost": 10.3132,
                        "market_price": 0.2958,
                        "multiplier": "100",
                        "dte": 3,
                        "delta": 0.19,
                    },
                ],
                {"NFLX": {"ticker": "NFLX", "price": 73.33, "trend": "NEUTRAL"}},
            ),
            playbook=self.playbook,
        )

        call = next(item for item in payload["positions"] if item["sec_type"] == "OPT")
        self.assertAlmostEqual(call["entry_credit"], 0.1031, places=4)
        self.assertLess(call["premium_capture_pct"], 0)
        self.assertNotEqual(call["management_action"], "REVIEW_CLOSE_OR_BUY_BACK")

    def test_near_expiry_otm_covered_call_quantitatively_prefers_hold(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {"ticker": "NFLX", "sec_type": "STK", "position_size": 1000, "market_price": 73.33},
                    {
                        "ticker": "NFLX",
                        "sec_type": "OPT",
                        "right": "C",
                        "position_size": -10,
                        "strike": 76,
                        "expiration": "20260731",
                        "average_cost": 10.3132,
                        "market_price": 0.2958,
                        "multiplier": "100",
                        "dte": 3,
                        "delta": 0.19,
                    },
                ],
                {"NFLX": {"ticker": "NFLX", "price": 73.33, "trend": "NEUTRAL"}},
            ),
            playbook=self.playbook,
        )

        call = next(item for item in payload["positions"] if item["sec_type"] == "OPT")
        management = call["management_alternatives"]
        comparison = management["covered_call_expiry_comparison"]

        self.assertTrue(comparison["available"])
        self.assertTrue(comparison["near_expiration"])
        self.assertEqual(comparison["recommended_alternative_id"], "HOLD_MONITOR")
        self.assertEqual(management["recommendation"]["alternative_id"], "HOLD_MONITOR")
        self.assertEqual(management["recommendation"]["confidence"], "HIGH")
        self.assertAlmostEqual(comparison["current_contract"]["distance_to_strike_pct"], 3.64, places=2)
        self.assertAlmostEqual(comparison["variants"][1]["close_cost_total"], 295.8, places=2)
        self.assertEqual(call["management_action"], "NO_ACTION_RECOMMENDED")

    def test_near_expiry_bullish_covered_call_prefers_non_debit_roll_up(self):
        snapshot = self.snapshot(
            [
                {"ticker": "AAPL", "sec_type": "STK", "position_size": 100, "market_price": 204},
                {
                    "ticker": "AAPL",
                    "sec_type": "OPT",
                    "right": "C",
                    "position_size": -1,
                    "strike": 205,
                    "expiration": "20260731",
                    "entry_credit": 0.5,
                    "market_price": 1.0,
                    "dte": 3,
                    "delta": 0.34,
                },
            ],
            {"AAPL": {"ticker": "AAPL", "price": 204, "trend": "BULLISH"}},
        )
        snapshot["active_position_option_chains"] = {
            "by_ticker": {"AAPL": {"option_rows": [
                {
                    "ticker": "AAPL",
                    "right": "C",
                    "strike": 210,
                    "expiration": "20260828",
                    "dte": 31,
                    "bid": 1.25,
                    "ask": 1.35,
                    "mid": 1.30,
                    "delta": 0.25,
                    "spread_pct": 7.69,
                },
                {
                    "ticker": "AAPL",
                    "right": "C",
                    "strike": 202.5,
                    "expiration": "20260828",
                    "dte": 31,
                    "bid": 4.5,
                    "ask": 4.7,
                    "mid": 4.6,
                    "delta": 0.6,
                    "spread_pct": 4.35,
                },
            ]}},
        }

        payload = position_management.build_active_position_management(snapshot, playbook=self.playbook)
        call = next(item for item in payload["positions"] if item["sec_type"] == "OPT")
        comparison = call["management_alternatives"]["covered_call_expiry_comparison"]

        self.assertEqual(comparison["recommended_alternative_id"], "ROLL_CALL")
        self.assertEqual(comparison["best_roll"]["contract"]["strike"], 210)
        self.assertEqual(comparison["best_roll"]["net_credit_total"], 25.0)
        self.assertEqual(call["management_alternatives"]["recommendation"]["alternative_id"], "ROLL_CALL")
        self.assertEqual(call["management_action"], "REVIEW_ROLL")

    def test_identical_position_copies_are_deduplicated(self):
        row = {"ticker": "RSP", "sec_type": "STK", "position_size": 100, "market_price": 213}
        payload = position_management.build_active_position_management(
            self.snapshot([row, dict(row)], {"RSP": {"ticker": "RSP", "price": 213, "trend": "NEUTRAL"}}),
            playbook=self.playbook,
        )

        self.assertEqual(payload["positions_found"], 1)

    def test_position_management_journal_records_manual_review_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            saved = position_management_journal.record_event(
                {
                    "position_id": "QQQ|OPT|P|650",
                    "ticker": "QQQ",
                    "strategy": "CASH_SECURED_PUT",
                    "recommended_action": "REVIEW_CLOSE_OR_BUY_BACK",
                    "recommended_state": "TAKE_PROFIT_REVIEW",
                    "operator_action": "MANUAL_CLOSE_REVIEWED",
                    "operator_reason": "Reviewed buyback in TWS manually.",
                },
                path=path,
            )
            summary = position_management_journal.summary(path)

        self.assertEqual(saved["journal_version"], "position_management_journal_v1")
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["by_operator_action"]["MANUAL_CLOSE_REVIEWED"], 1)
        self.assertFalse(summary["execution_authorized"])

    def test_completed_review_stays_acknowledged_until_recommendation_changes(self):
        position = {
            "position_id": "NFLX|STK|0|||",
            "ticker": "NFLX",
            "strategy": "LONG_STOCK",
            "position_size": 1000,
            "management_action": "REVIEW_RISK",
            "exit_state": "RISK_REVIEW",
            "management_alternatives": {
                "recommendation": {
                    "alternative_id": "COLLAR",
                    "contracts": 3,
                    "contract": {"strike": 65, "expiration": "20260828"},
                    "put_contract": {"strike": 62, "expiration": "20260828"},
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            position_management_journal.record_event(
                {
                    "position_id": position["position_id"],
                    "ticker": "NFLX",
                    "strategy": "LONG_STOCK",
                    "recommended_action": "REVIEW_RISK",
                    "recommended_state": "RISK_REVIEW",
                    "management_fingerprint": position_management_journal.management_fingerprint(position),
                    "operator_action": "REVIEW_COMPLETED",
                },
                path=path,
            )
            acknowledged = position_management_journal.acknowledged_position_reviews({"positions": [position]}, path=path)
            changed = {**position, "management_alternatives": {"recommendation": {**position["management_alternatives"]["recommendation"], "contract": {"strike": 68, "expiration": "20260828"}}}}
            changed_acknowledgements = position_management_journal.acknowledged_position_reviews({"positions": [changed]}, path=path)

        self.assertIn(position["position_id"], acknowledged)
        self.assertNotIn(position["position_id"], changed_acknowledgements)

    def test_refresh_data_cannot_be_dismissed_as_reviewed(self):
        position = {
            "position_id": "MSFT|OPT|P|335|20261016|",
            "ticker": "MSFT",
            "strategy": "CASH_SECURED_PUT",
            "management_action": "REFRESH_DATA",
            "exit_state": "MONITOR",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            position_management_journal.record_event(
                {
                    "position_id": position["position_id"],
                    "ticker": "MSFT",
                    "strategy": "CASH_SECURED_PUT",
                    "recommended_action": "REFRESH_DATA",
                    "recommended_state": "MONITOR",
                    "management_fingerprint": position_management_journal.management_fingerprint(position),
                    "operator_action": "REVIEW_COMPLETED",
                },
                path=path,
            )
            acknowledged = position_management_journal.acknowledged_position_reviews({"positions": [position]}, path=path)

        self.assertEqual(acknowledged, {})

    def test_saved_position_context_enriches_thesis_and_entry_credit(self):
        payload = position_management.build_active_position_management(
            {
                **self.snapshot(
                    [
                        {
                            "ticker": "QQQ",
                            "sec_type": "OPT",
                            "right": "P",
                            "strike": 650,
                            "position_size": -1,
                            "option_mark": 1.5,
                            "dte": 12,
                            "delta": -0.12,
                        }
                    ],
                    {
                        "QQQ": {
                            "ticker": "QQQ",
                            "trend": "BULLISH",
                            "price": 670,
                            "support_level": 640,
                            "gamma_wall": 675,
                        }
                    },
                ),
                "active_position_contexts": {
                    "context_store_version": "position_context_store_v1",
                    "contexts": [
                        {
                            "ticker": "QQQ",
                            "strategy": "CASH_SECURED_PUT",
                            "thesis": {
                                "text": "Support hold thesis",
                                "invalidation_level": 640,
                            },
                            "entry": {
                                "entry_credit": 4.0,
                                "entry_date": "2026-07-01",
                            },
                        }
                    ],
                },
            },
            playbook=self.playbook,
        )
        item = payload["positions"][0]

        self.assertEqual(item["entry_credit"], 4.0)
        self.assertEqual(item["thesis"]["status"], "AVAILABLE")
        self.assertEqual(item["thesis"]["text"], "Support hold thesis")
        self.assertEqual(item["premium_capture_pct"], 62.5)
        self.assertEqual(payload["position_context_summary"]["contexts_applied"], 1)

    def test_position_context_store_upserts_and_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contexts.json"
            position_context_store.upsert_context(
                {
                    "ticker": "AAPL",
                    "strategy": "CASH_SECURED_PUT",
                    "thesis_text": "Support thesis",
                    "entry_credit": 3.25,
                },
                path=path,
            )
            payload = position_context_store.load_contexts(path)
            found = position_context_store.find_context(
                {"ticker": "AAPL", "strategy": "CASH_SECURED_PUT"},
                payload["contexts"],
            )

        self.assertIsNotNone(found)
        self.assertEqual(found["thesis"]["text"], "Support thesis")
        self.assertEqual(found["entry"]["entry_credit"], 3.25)

    def test_manual_gamma_context_feeds_position_technical_context(self):
        payload = position_management.build_active_position_management(
            {
                **self.snapshot(
                    [
                        {
                            "ticker": "QQQ",
                            "sec_type": "OPT",
                            "right": "P",
                            "strike": 650,
                            "position_size": -1,
                            "entry_credit": 4.0,
                            "option_mark": 2.0,
                            "dte": 20,
                        }
                    ],
                    {"QQQ": {"ticker": "QQQ", "trend": "BULLISH", "price": 670, "support_level": 640}},
                ),
                "gamma_contexts": {
                    "gamma_context_store_version": "gamma_context_store_v1",
                    "contexts": [{"ticker": "QQQ", "gamma_wall": 675, "call_wall": 680, "put_wall": 640}],
                },
            },
            playbook=self.playbook,
        )

        technical = payload["positions"][0]["technical"]

        self.assertTrue(technical["gamma_available"])
        self.assertEqual(technical["gamma"]["gamma_wall"], 675)
        self.assertEqual(technical["gamma"]["call_wall"], 680)

    def test_generic_manual_json_context_feeds_price_and_levels(self):
        payload = position_management.build_active_position_management(
            {
                **self.snapshot(
                    [{"ticker": "NFLX", "sec_type": "STK", "position_size": 100}],
                    {},
                ),
                "gamma_contexts": {
                    "contexts": [{"ticker": "NFLX", "spot": 67.4, "support_levels": [62, 65], "resistance_levels": [70, 73], "call_wall": 72}],
                },
            },
            playbook=self.playbook,
        )
        technical = payload["positions"][0]["technical"]

        self.assertEqual(technical["price"], 67.4)
        self.assertEqual(technical["support"], 65)
        self.assertEqual(technical["resistance"], 70)

    def test_open_futures_position_requires_explicit_risk_review(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [{
                    "ticker": "MNQ",
                    "sec_type": "FUT",
                    "expiration": "20260918",
                    "position_size": -1,
                    "market_value": -58666,
                }],
                {"MNQ": {"ticker": "MNQ", "trend": "NEUTRAL", "price": 29300}},
            ),
            playbook=self.playbook,
        )

        position = payload["positions"][0]
        self.assertEqual(position["strategy"], "FUTURES_POSITION")
        self.assertEqual(position["management_action"], "REVIEW_RISK")
        self.assertIn("FUTURES_RISK_PLAN_REVIEW_REQUIRED", position["blockers"])
        self.assertTrue(position["manual_review_required"])
        self.assertFalse(position["execution_authorized"])

    def test_calendar_futures_legs_create_one_economic_review(self):
        payload = position_management.build_active_position_management(
            self.snapshot(
                [
                    {"ticker": "MNQ", "sec_type": "FUT", "expiration": "20260918", "position_size": -1, "market_price": 30000},
                    {"ticker": "MNQ", "sec_type": "FUT", "expiration": "20261218", "position_size": 1, "market_price": 30100},
                ],
                {"MNQ": {"ticker": "MNQ", "trend": "NEUTRAL", "price": 30000}},
            ),
            playbook=self.playbook,
        )

        primary = next(item for item in payload["positions"] if item["futures_structure"]["primary_position_id"] == item["position_id"])
        linked = next(item for item in payload["positions"] if item is not primary)

        self.assertEqual(primary["futures_structure"]["structure_type"], "CALENDAR_SPREAD")
        self.assertEqual(primary["futures_structure"]["net_contracts"], 0)
        self.assertTrue(primary["manual_review_required"])
        self.assertEqual(linked["exit_state"], "LINKED_STRUCTURE_LEG")
        self.assertFalse(linked["manual_review_required"])
        self.assertEqual(payload["positions_requiring_review"], 1)

    def test_gamma_context_store_upserts_manual_gamma(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gamma.json"
            gamma_context_store.upsert_context({"ticker": "SPY", "spot": 675, "support_levels": [650, 660], "resistance_levels": [690, 700], "call_wall": 700, "put_wall": 650}, path=path)
            summary = gamma_context_store.summary(path)

        self.assertEqual(summary["context_count"], 1)
        self.assertIn("SPY", summary["tickers"])
        self.assertEqual(summary["latest_context"]["support_levels"], [650.0, 660.0])

    def test_position_state_alerts_detect_management_action_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "states.json"
            first = {
                "positions": [
                    {"position_id": "QQQ", "ticker": "QQQ", "strategy": "CASH_SECURED_PUT", "exit_state": "MONITOR", "management_action": "NO_ACTION_RECOMMENDED"}
                ]
            }
            second = {
                "positions": [
                    {"position_id": "QQQ", "ticker": "QQQ", "strategy": "CASH_SECURED_PUT", "exit_state": "TAKE_PROFIT_REVIEW", "management_action": "REVIEW_CLOSE_OR_BUY_BACK"}
                ]
            }
            position_state_alerts.update_from_management(first, path)
            updated = position_state_alerts.update_from_management(second, path)

        self.assertEqual(len(updated["latest_alerts"]), 1)
        self.assertEqual(updated["latest_alerts"][0]["ticker"], "QQQ")
        self.assertEqual(updated["latest_alerts"][0]["to_management_action"], "REVIEW_CLOSE_OR_BUY_BACK")

    def test_journal_evaluation_matches_current_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            position_management_journal.record_event(
                {
                    "position_id": "QQQ",
                    "ticker": "QQQ",
                    "strategy": "CASH_SECURED_PUT",
                    "recommended_action": "NO_ACTION_RECOMMENDED",
                    "recommended_state": "MONITOR",
                    "operator_action": "NO_ACTION_TAKEN",
                },
                path=path,
            )
            evaluation = position_management_journal.evaluate_against_management(
                {
                    "positions": [
                        {"position_id": "QQQ", "ticker": "QQQ", "exit_state": "TAKE_PROFIT_REVIEW", "management_action": "REVIEW_CLOSE_OR_BUY_BACK", "manual_review_required": True}
                    ]
                },
                path=path,
            )

        self.assertEqual(evaluation["evaluated_event_count"], 1)
        self.assertEqual(evaluation["pending_followup_count"], 1)


if __name__ == "__main__":
    unittest.main()
