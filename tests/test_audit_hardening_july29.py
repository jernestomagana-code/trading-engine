from __future__ import annotations

import unittest
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import broker_control_tower
import broker_check
import coberturas_engine
import position_management
import portfolio_risk_engine
import tradingview_signal_ledger
from scripts import v32_pushover_automation
from test_v29_v30_contract_gating import main
from tools import publish_v31_snapshot_from_runtime


class AuditHardeningJuly29Tests(unittest.TestCase):
    def test_durable_snapshot_preserves_sanitized_positions_and_management(self):
        durable = main._v31_canonical_durable_payload({
            "source": "UNIT_TEST",
            "received_at": main._v29_now(),
            "options_rows": [],
            "technical_snapshot": {"NFLX": {"score": 80}},
            "account_context": {
                "account_alias": "remanente",
                "account_scope": "remanente",
                "real_account_id_excluded": True,
            },
            "positions": [{"ticker": "NFLX", "sec_type": "STK", "position_size": 100}],
            "active_position_management": {"positions_found": 1},
            "coberturas_rsp_chain_coverage": {
                "generated_at": main._v29_now(),
                "chain_by_ticker": {"RSP": {"option_rows": []}},
            },
            "coberturas_rsp_account_capacity": {
                "account_alias": "retiro",
                "available_funds": 7000,
            },
        })

        self.assertEqual(durable["positions"][0]["ticker"], "NFLX")
        self.assertEqual(durable["active_position_management"]["positions_found"], 1)
        self.assertEqual(durable["account_alias"], "remanente")
        self.assertIn("RSP", durable["coberturas_rsp_chain_coverage"]["chain_by_ticker"])
        self.assertEqual(durable["coberturas_rsp_account_capacity"]["account_alias"], "retiro")

    def test_post_close_recovery_window_remains_open_in_evening(self):
        evening = datetime(2026, 7, 29, 21, 30, tzinfo=v32_pushover_automation.NY_TZ)
        with patch.object(v32_pushover_automation, "now_ny", return_value=evening):
            self.assertTrue(v32_pushover_automation.post_close_window())

    def test_post_close_never_sends_mobile_notification(self):
        args = Namespace(
            force=True,
            base_url="https://example.invalid",
            timeout=2,
        )
        step = {
            "ok": True,
            "stdout_tail": '{"evaluations":[{"evaluated_count":2,"not_evaluated_count":1,"saved_count":2}]}',
            "stderr_tail": "",
        }
        with (
            patch.object(v32_pushover_automation, "run_command", return_value=step),
            patch.object(v32_pushover_automation, "mark_post_close"),
            patch.object(v32_pushover_automation, "send_pushover_summary") as send,
        ):
            result = v32_pushover_automation.run_post_close(args)

        self.assertEqual(result["mobile_policy"], "ENTRY_ONLY")
        self.assertFalse(result["notification_sent"])
        self.assertTrue(result["review_required"])
        send.assert_not_called()

    def test_signal_ledger_records_bar_to_server_latency(self):
        payload = {
            "source": "TRADINGVIEW",
            "action": "ALERT_ONLY",
            "strategy_context": "INTRADAY_INDEX_FUTURES",
            "ticker": "MNQ1!",
            "timeframe": "1m",
            "event": "VWAP_RECLAIM",
            "event_code": "MNQ_VWAP_RECLAIM_LONG_5M",
            "price": 100,
            "signal_bar_open_time_ms": 1_785_000_000_000,
            "signal_bar_close_time_ms": 1_785_000_060_000,
            "alert_emitted_time_ms": 1_785_000_060_500,
        }
        received = datetime.fromtimestamp(1_785_000_061, tz=timezone.utc).isoformat()

        event = tradingview_signal_ledger.normalize_signal_event(
            payload,
            received_at=received,
        )

        self.assertEqual(event["signal_bar_close_time_ms"], 1_785_000_060_000)
        self.assertEqual(event["server_receive_latency_ms"], 500.0)

    def test_mobile_suppresses_expired_intraday_entry(self):
        old_ms = int((datetime.now(timezone.utc) - timedelta(minutes=3)).timestamp() * 1000)
        payload = {
            "strategy_context": "INTRADAY_INDEX_FUTURES",
            "ticker": "MNQ1!",
            "timeframe": "1m",
            "event": "VWAP_RECLAIM",
            "event_code": "MNQ_VWAP_RECLAIM_LONG_5M",
            "direction": "LONG",
            "price": 100,
            "alert_emitted_time_ms": old_ms,
        }
        with patch.object(main, "send_pushover_message") as send:
            result = main._v32_intraday_futures_immediate_notify_payload(payload)

        self.assertEqual(result["reason"], "STALE_INTRADAY_ENTRY_SUPPRESSED")
        self.assertFalse(result["pushover_sent"])
        send.assert_not_called()

    def test_rsp_current_broker_spot_precedes_old_manual_spot(self):
        runtime_data = {
            "chain.json": {
                "ticker": "RSP",
                "underlying_price": 219.25,
            }
        }
        spot = coberturas_engine.extract_rsp_underlying_price(
            runtime_data,
            {"spot": 210.0},
        )
        self.assertEqual(spot, 219.25)

    def test_rsp_chain_recovers_from_durable_master(self):
        chain = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chain_by_ticker": {
                "RSP": {
                    "option_rows": [{
                        "ticker": "RSP",
                        "strategy": "COVERED_CALL",
                        "strike": 220,
                        "dte": 9,
                        "bid": 1.0,
                        "ask": 1.1,
                    }],
                },
            },
        }
        runtime_data = {
            "v28_master_snapshot.json": {
                "coberturas_rsp_chain_coverage": chain,
            },
        }

        self.assertEqual(
            coberturas_engine.extract_embedded_rsp_chain(runtime_data),
            chain,
        )
        rows = coberturas_engine.extract_option_rows(runtime_data)
        self.assertEqual(rows[0]["source_file"], "durable_master_snapshot")

    def test_rsp_capacity_prefers_configured_retiro_account(self):
        runtime_data = {
            "master.json": {
                "account_context": {
                    "account_alias": "remanente",
                    "available_funds": 50000,
                    "buying_power": 100000,
                },
                "coberturas_rsp_account_capacity": {
                    "account_alias": "retiro",
                    "available_funds": 7000,
                    "buying_power": 14000,
                },
            },
        }

        capacity = coberturas_engine.extract_account_capacity(runtime_data)

        self.assertEqual(capacity["account_alias"], "retiro")

    def test_weekday_after_close_staleness_is_watch_not_critical(self):
        reference = datetime(2026, 7, 29, 23, 35, tzinfo=timezone.utc)
        old = broker_control_tower.account_snapshot(
            broker="IBKR",
            alias="remanente",
            scope="remanente",
            capacity={
                "net_liquidation": 100000,
                "available_funds": 50000,
                "excess_liquidity": 50000,
                "maintenance_margin_required": 20000,
                "gross_position_value": 100000,
                "total_cash_value": 10000,
            },
            positions=[],
            generated_at=(reference - timedelta(hours=3)).isoformat(),
        )
        registry = broker_control_tower.build_registry({"remanente": {"alias": "remanente"}})
        tower = broker_control_tower.consolidate(registry, {"remanente": old}, reference=reference)
        tower["accounts"][0]["refresh_status"] = "STALE"

        evaluation = portfolio_risk_engine.evaluate(tower, reference=reference)
        alert = next(item for item in evaluation["alerts"] if item["rule"] == "ACCOUNT_DATA_NOT_READY")

        self.assertEqual(alert["severity"], "WATCH")
        self.assertIn("cierre", alert["recommended_action"])

    def test_same_ticker_in_two_accounts_remains_separate(self):
        positions = broker_check.extract_positions({
            "positions": [
                {
                    "account_alias": "remanente",
                    "ticker": "MSFT",
                    "security_type": "OPT",
                    "right": "P",
                    "strike": 335,
                    "expiration": "20261016",
                    "quantity": -1,
                },
                {
                    "account_alias": "retiro",
                    "ticker": "MSFT",
                    "security_type": "OPT",
                    "right": "P",
                    "strike": 345,
                    "expiration": "20261016",
                    "quantity": -1,
                },
            ],
        })
        groups = position_management._position_groups([
            position_management.normalize_position(row) for row in positions
        ])
        management = position_management.build_active_position_management({
            "positions": positions,
            "technical_snapshot": {
                "MSFT": {"ticker": "MSFT", "price": 400, "trend": "SIDEWAYS"},
            },
        })

        self.assertEqual(len(positions), 2)
        self.assertEqual(set(groups), {"REMANENTE|MSFT", "RETIRO|MSFT"})
        self.assertEqual(
            {row["account_alias"] for row in management["positions"]},
            {"remanente", "retiro"},
        )
        self.assertEqual(len({row["position_id"] for row in management["positions"]}), 2)

    def test_publisher_prefers_account_scoped_control_tower_positions(self):
        runtime_data = {
            "broker_control_tower_latest.json": {
                "accounts": [
                    {
                        "account_alias": "remanente",
                        "account_scope": "remanente",
                        "positions": [{"ticker": "NFLX", "security_type": "STK", "quantity": 100}],
                    },
                    {
                        "account_alias": "retiro",
                        "account_scope": "retiro",
                        "positions": [{"ticker": "RSP", "security_type": "STK", "quantity": 100}],
                    },
                ],
            },
        }

        positions = publish_v31_snapshot_from_runtime.account_scoped_positions(runtime_data)

        self.assertEqual(len(positions), 2)
        self.assertEqual({row["account_alias"] for row in positions}, {"remanente", "retiro"})


if __name__ == "__main__":
    unittest.main()
