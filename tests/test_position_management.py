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
        self.assertEqual(alternatives["COVERED_CALL_PARTIAL"]["contracts"], 5)
        self.assertEqual(alternatives["COVERED_CALL_FULL"]["contracts"], 10)
        self.assertEqual(alternatives["COVERED_CALL_FULL"]["contract_candidates"][0]["strike"], 125)
        self.assertEqual(alternatives["PROTECTIVE_PUT"]["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertIn("COLLAR", alternatives)
        self.assertGreaterEqual(payload["option_alternatives_summary"]["total_alternatives"], 8)

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

    def test_gamma_context_store_upserts_manual_gamma(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gamma.json"
            gamma_context_store.upsert_context({"ticker": "SPY", "call_wall": 700, "put_wall": 650}, path=path)
            summary = gamma_context_store.summary(path)

        self.assertEqual(summary["context_count"], 1)
        self.assertIn("SPY", summary["tickers"])

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
