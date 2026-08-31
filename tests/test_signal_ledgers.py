import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ibkr_diagnostics
import tradingview_alert_coverage
import tradingview_operational_health
import tradingview_payload_contract
import tradingview_signal_ledger


class SignalLedgerTests(unittest.TestCase):
    def test_active_tradingview_alerts_expose_renewal_window(self):
        coverage = tradingview_alert_coverage.load_coverage(
            ROOT / "config" / "tradingview_alert_coverage_v1.json"
        )

        status = tradingview_alert_coverage.production_alert_expiry_status(
            coverage, as_of="2026-10-12"
        )

        self.assertEqual(status["status"], "RENEW_SOON")
        self.assertTrue(status["renewal_required"])
        self.assertEqual(status["alerts"][0]["expires_on"], "2026-10-23")

    def test_absolute_runtime_ledger_uses_neighbor_remote_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            cache = runtime / "stock_ultimus_console_remote_cache.json"
            cache.write_text(json.dumps({
                "entries": {
                    "/v32_signal_events?limit=1000": {
                        "result": {"data": {"events": [{"event_id": "REMOTE-ABS", "ticker": "MES"}]}}
                    }
                }
            }))

            events = tradingview_signal_ledger.load_signal_events(runtime / "v32_signal_events.json")

        self.assertEqual(events[0]["event_id"], "REMOTE-ABS")

    def test_default_ledger_falls_back_to_console_remote_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            ledger = runtime / "v32_signal_events.json"
            cache = runtime / "stock_ultimus_console_remote_cache.json"
            cache.write_text(json.dumps({
                "entries": {
                    "/v32_signal_events?limit=1000": {
                        "result": {
                            "data": {
                                "events": [{"event_id": "REMOTE-1", "ticker": "MNQ"}],
                            },
                        },
                    },
                },
            }))
            with patch.object(tradingview_signal_ledger, "DEFAULT_LEDGER_PATH", ledger), patch.object(
                tradingview_signal_ledger,
                "DEFAULT_REMOTE_CACHE_PATH",
                cache,
            ):
                events = tradingview_signal_ledger.load_signal_events()

        self.assertEqual(events[0]["event_id"], "REMOTE-1")

    def test_tradingview_alert_coverage_generates_valid_minimum_messages(self):
        coverage = tradingview_alert_coverage.load_coverage()
        validation = tradingview_alert_coverage.validate_coverage(coverage)
        required_records = tradingview_alert_coverage.setup_records(coverage, required_only=True)
        all_records = tradingview_alert_coverage.setup_records(coverage)
        first = tradingview_alert_coverage.alert_by_code(coverage, "MNQ_ORB_BREAKOUT_LONG_5M")
        message = tradingview_alert_coverage.payload_for_alert(first)
        payload_validation = tradingview_payload_contract.validate_payload(message)

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["production_active_alert_count"], 2)
        self.assertEqual(validation["logical_event_count"], 20)
        self.assertEqual(validation["required_logical_event_count"], 10)
        self.assertEqual(validation["required_alert_count"], 10)
        self.assertEqual(validation["health_alert_count"], 2)
        self.assertEqual(len(required_records), 10)
        self.assertEqual(len(all_records), 20)
        self.assertEqual(message["event_code"], "MNQ_ORB_BREAKOUT_LONG_5M")
        self.assertTrue(payload_validation["valid"])

    def test_options_underlying_alert_coverage_generates_valid_messages(self):
        coverage_path = ROOT / "config" / "tradingview_options_underlying_alert_coverage_v1.json"
        coverage = tradingview_alert_coverage.load_coverage(coverage_path)
        validation = tradingview_alert_coverage.validate_coverage(coverage)
        required_records = tradingview_alert_coverage.setup_records(coverage, required_only=True)
        all_records = tradingview_alert_coverage.setup_records(coverage)
        first = tradingview_alert_coverage.alert_by_code(coverage, "QQQ_TECH_CONFIRM_LONG_15M")
        message = tradingview_alert_coverage.payload_for_alert(first)
        payload_validation = tradingview_payload_contract.validate_payload(message)

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["production_active_alert_count"], 3)
        self.assertEqual(validation["logical_event_count"], 9)
        self.assertEqual(validation["required_logical_event_count"], 6)
        self.assertEqual(validation["required_alert_count"], 6)
        self.assertEqual(validation["health_alert_count"], 2)
        self.assertEqual(len(required_records), 6)
        self.assertEqual(len(all_records), 9)
        self.assertEqual(message["strategy_context"], "OPTIONS_UNDERLYING_CONFIRMATION")
        self.assertEqual(message["event_code"], "QQQ_TECH_CONFIRM_LONG_15M")
        self.assertIn("rsi", message)
        self.assertTrue(payload_validation["valid"])
        self.assertIn("rsi", payload_validation["placeholder_fields"])

    def test_options_underlying_ledger_accepts_intraday_vix_risk_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            coverage_path = ROOT / "config" / "tradingview_options_underlying_alert_coverage_v1.json"
            payload = tradingview_operational_health.concrete_payload_for_event_code(
                "VIX_RISK_ELEVATED_15M",
                coverage_path=coverage_path,
            )
            payload.update(
                {
                    "ticker": "SPY",
                    "timeframe": "15",
                    "price": 755.0,
                    "source": "TRADINGVIEW",
                }
            )

            result = tradingview_signal_ledger.append_signal_event(
                payload,
                raw_text=json.dumps(payload),
                endpoint="/technical_snapshot",
                path=path,
            )
            events = tradingview_signal_ledger.load_signal_events(path)

        self.assertEqual(result["status"], "RECEIVED")
        self.assertTrue(result["accepted_for_engine"])
        self.assertEqual(events[0]["strategy_context"], "OPTIONS_UNDERLYING_CONFIRMATION")
        self.assertEqual(events[0]["event_code"], "VIX_RISK_ELEVATED_15M")
        self.assertEqual(events[0]["alert_contract_status"], "ACCEPTED")

    def test_chris_ia_alert_coverage_and_ledger_accept_structured_reversal_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            coverage_path = ROOT / "config" / "tradingview_chris_ia_alert_coverage_v1.json"
            coverage = tradingview_alert_coverage.load_coverage(coverage_path)
            validation = tradingview_alert_coverage.validate_coverage(coverage)
            payload = tradingview_operational_health.concrete_payload_for_event_code(
                "CHRIS_IA_USTECF_LONG_ENTRY_15",
                coverage_path=coverage_path,
            )
            payload_validation = tradingview_payload_contract.validate_payload(payload)

            result = tradingview_signal_ledger.append_signal_event(
                payload,
                raw_text=json.dumps(payload),
                endpoint="/technical_snapshot",
                path=path,
            )
            events = tradingview_signal_ledger.load_signal_events(path)

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["production_active_alert_count"], 0)
        self.assertEqual(validation["required_logical_event_count"], 4)
        self.assertTrue(payload_validation["valid"])
        self.assertEqual(payload_validation["base_required_fields"], ["ticker", "timeframe", "strategy_context", "price"])
        self.assertEqual(result["status"], "RECEIVED")
        self.assertTrue(result["accepted_for_engine"])
        self.assertEqual(events[0]["strategy_context"], "CHRIS_IA_REVERSAL_PRO")
        self.assertEqual(events[0]["event_code"], "CHRIS_IA_USTECF_LONG_ENTRY_15")
        self.assertEqual(events[0]["breakout_direction"], "LONG")
        self.assertEqual(events[0]["score"], 82.0)
        self.assertEqual(events[0]["macd_z"], -1.25)
        self.assertEqual(events[0]["missing_context_fields"], [])

    def test_tradingview_payload_contract_validates_sample_and_missing_fields(self):
        valid = tradingview_payload_contract.validate_payload(
            tradingview_payload_contract.sample_payload()
        )
        invalid = tradingview_payload_contract.validate_payload({"ticker": "MNQ1!"})
        template = tradingview_payload_contract.validate_payload(
            tradingview_payload_contract.tradingview_placeholder_template()
        )

        self.assertTrue(valid["valid"])
        self.assertEqual(valid["context_completeness_pct"], 100.0)
        self.assertFalse(invalid["valid"])
        self.assertIn("vwap", invalid["missing_fields"])
        self.assertTrue(template["valid"])
        self.assertIn("price", template["placeholder_fields"])

    def test_tradingview_ledger_records_and_dedupes_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            payload = tradingview_operational_health.concrete_payload_for_event_code(
                "MNQ_ORB_BREAKOUT_LONG_5M"
            )

            first = tradingview_signal_ledger.append_signal_event(payload, raw_text=json.dumps(payload), endpoint="/technical_snapshot", path=path)
            second = tradingview_signal_ledger.append_signal_event(payload, raw_text=json.dumps(payload), endpoint="/technical_snapshot", path=path)
            events = tradingview_signal_ledger.load_signal_events(path)

        self.assertEqual(first["status"], "RECEIVED")
        self.assertEqual(second["status"], "DUPLICATE")
        self.assertEqual(len(events), 1)
        self.assertTrue(first["accepted_for_engine"])
        self.assertEqual(events[0]["candidate_source"], "TRADINGVIEW_ALERT")
        self.assertEqual(events[0]["payload_contract_version"], "tradingview_signal_payload_v2_1_compact_options")
        self.assertEqual(events[0]["alert_contract_status"], "ACCEPTED")
        self.assertEqual(events[0]["event_code"], "MNQ_ORB_BREAKOUT_LONG_5M")
        self.assertTrue(events[0]["payload_validation"]["valid"])
        self.assertEqual(events[0]["adx"], 22.0)
        self.assertEqual(events[0]["logical_stop"], 98.75)
        self.assertEqual(events[0]["missing_context_fields"], [])
        self.assertFalse(events[0]["execution_authorized"])

    def test_tradingview_ledger_accepts_options_underlying_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            coverage_path = ROOT / "config" / "tradingview_options_underlying_alert_coverage_v1.json"
            payload = tradingview_operational_health.concrete_payload_for_event_code(
                "QQQ_TECH_CONFIRM_LONG_15M",
                coverage_path=coverage_path,
            )

            result = tradingview_signal_ledger.append_signal_event(
                payload,
                raw_text=json.dumps(payload),
                endpoint="/technical_snapshot",
                path=path,
            )
            events = tradingview_signal_ledger.load_signal_events(path)

        self.assertEqual(result["status"], "RECEIVED")
        self.assertTrue(result["accepted_for_engine"])
        self.assertEqual(events[0]["strategy_context"], "OPTIONS_UNDERLYING_CONFIRMATION")
        self.assertEqual(events[0]["event_code"], "QQQ_TECH_CONFIRM_LONG_15M")
        self.assertEqual(events[0]["rsi"], 55.0)
        self.assertEqual(events[0]["market_regime"], "RISK_ON")
        self.assertEqual(events[0]["missing_context_fields"], [])

    def test_options_underlying_compact_payload_is_accepted_without_execution_context(self):
        payload = {
            "source": "TRADINGVIEW",
            "strategy_context": "OPTIONS_UNDERLYING_CONFIRMATION",
            "event": "TECH_CONFIRM",
            "event_code": "QQQ_TECH_CONFIRM_SHORT_15M",
            "ticker": "QQQ",
            "timeframe": "15",
            "breakout_direction": "SHORT",
            "price": 714.79,
            "logical_stop": 716.19,
            "logical_target": 711.99,
            "adx": 37.52,
            "atr": 1.40,
            "rsi": 44.68,
            "volume_relative": 0.57,
            "vwap": 714.61,
            "underlying_signal": "TECH_CONFIRM_SHORT",
            "volatility_state": "NORMAL",
            "action": "ALERT_ONLY",
            "execution_authorized": False,
            "not_order_instruction": True,
        }

        validation = tradingview_payload_contract.validate_payload(payload, allow_placeholders=False)
        event = tradingview_signal_ledger.normalize_signal_event(
            payload,
            raw_text=json.dumps(payload),
            endpoint="/technical_snapshot",
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["missing_fields"], [])
        self.assertNotIn("session_state", validation["required_fields"])
        self.assertTrue(event["accepted_for_engine"])
        self.assertEqual(event["missing_context_fields"], [])
        self.assertEqual(event["alert_contract_status"], "ACCEPTED")

    def test_tradingview_ledger_quarantines_legacy_payload_without_event_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            status_path = Path(tmp) / "webhook_status.json"
            payload = dict(tradingview_payload_contract.sample_payload())
            payload.pop("event_code", None)

            result = tradingview_signal_ledger.append_signal_event(
                payload,
                raw_text=json.dumps(payload),
                endpoint="/technical_snapshot",
                path=path,
                status_path=status_path,
            )
            events = tradingview_signal_ledger.load_signal_events(path)
            status = tradingview_signal_ledger.load_webhook_status(status_path)

        self.assertEqual(result["status"], "QUARANTINED")
        self.assertFalse(result["accepted_for_engine"])
        self.assertIn("MISSING_EVENT_CODE", result["quarantine_reasons"])
        self.assertEqual(events[0]["alert_contract_status"], "QUARANTINED")
        self.assertEqual(events[0]["delivery_status"], "QUARANTINED")
        self.assertEqual(status["webhook_attempt_count"], 1)
        self.assertEqual(status["quarantined_count"], 1)
        self.assertEqual(status["last_webhook"]["status"], "QUARANTINED")
        self.assertEqual(status["last_webhook"]["event_id"], result["event_id"])

    def test_tradingview_operational_health_tracks_real_event_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            ledger_path = runtime / "v32_signal_events.json"
            payload = tradingview_operational_health.concrete_payload_for_event_code(
                "MNQ_ORB_BREAKOUT_LONG_5M"
            )
            tradingview_signal_ledger.append_signal_event(
                payload,
                raw_text=json.dumps(payload),
                endpoint="/technical_snapshot",
                path=ledger_path,
            )

            health = tradingview_operational_health.build_alert_health(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
            )
            e2e = tradingview_operational_health.build_e2e_readiness(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
                allow_local_replay_validation=True,
            )
            audit = tradingview_operational_health.build_production_audit(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
            )

        self.assertTrue(health["coverage_valid"])
        self.assertEqual(health["production_active_alert_count"], 2)
        self.assertEqual(health["required_logical_event_count"], 10)
        self.assertEqual(health["required_alert_count"], 10)
        self.assertEqual(health["health_alert_count"], 2)
        self.assertEqual(health["received_health_event_count"], 0)
        self.assertFalse(health["required_real_events_required"])
        self.assertEqual(
            health["missing_health_event_codes"],
            ["MNQ_SESSION_SNAPSHOT_5M", "MES_SESSION_SNAPSHOT_5M"],
        )
        self.assertEqual(health["missing_required_event_codes"], [])
        self.assertIn("MES_VWAP_REJECT_SHORT_5M", health["missing_opportunistic_event_codes"])
        self.assertFalse(e2e["real_e2e_confirmed"])
        self.assertEqual(e2e["local_replay_validation"]["candidate_source"], "TRADINGVIEW_ALERT")
        self.assertTrue(audit["checks"]["no_nq_es_expansion"])
        self.assertTrue(audit["checks"]["only_mnq_mes_in_scope"])
        self.assertNotIn("required_real_events_observed", audit["open_items"])

    def test_tradingview_operational_health_requires_some_real_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            health = tradingview_operational_health.build_alert_health(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
            )

        self.assertEqual(health["status"], "DEGRADED")
        self.assertIn("NO_REAL_TRADINGVIEW_EVENT", health["blockers"])
        self.assertEqual(health["visible_health"]["tv"], "TV_MISSING")

    def test_historical_quarantine_does_not_degrade_current_health_forever(self):
        old_payload = tradingview_operational_health.concrete_payload_for_event_code(
            "MNQ_SESSION_SNAPSHOT_5M"
        )
        old_payload["event_code"] = "RETIRED_UNKNOWN_EVENT"
        old_event = tradingview_signal_ledger.normalize_signal_event(
            old_payload,
            raw_text=json.dumps(old_payload),
            endpoint="/technical_snapshot",
            received_at="2026-07-05T10:00:00+00:00",
        )
        current_events = []
        for code in ("MNQ_SESSION_SNAPSHOT_5M", "MES_SESSION_SNAPSHOT_5M"):
            payload = tradingview_operational_health.concrete_payload_for_event_code(code)
            current_events.append(tradingview_signal_ledger.normalize_signal_event(
                payload,
                raw_text=json.dumps(payload),
                endpoint="/technical_snapshot",
                received_at="2026-07-05T14:00:00+00:00",
            ))

        health = tradingview_operational_health.build_alert_health(
            Path("runtime"),
            generated_at="2026-07-05T14:00:00+00:00",
            events_override=[old_event, *current_events],
        )

        self.assertEqual(health["quarantine_event_count"], 0)
        self.assertEqual(health["historical_quarantine_event_count"], 1)
        self.assertNotIn("UNKNOWN_OR_QUARANTINED_TRADINGVIEW_PAYLOADS", health["blockers"])

    def test_options_underlying_e2e_local_replay_uses_options_coverage_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            coverage_path = ROOT / "config" / "tradingview_options_underlying_alert_coverage_v1.json"
            e2e = tradingview_operational_health.build_e2e_readiness(
                Path(tmp),
                coverage_path=coverage_path,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
                allow_local_replay_validation=True,
            )

        self.assertFalse(e2e["real_e2e_confirmed"])
        self.assertEqual(e2e["local_replay_validation"]["event_code"], "QQQ_TECH_CONFIRM_LONG_15M")
        self.assertTrue(e2e["local_replay_validation"]["payload_valid"])
        self.assertIn("SPY/QQQ/VIX", e2e["next_real_trigger"])

    def test_tradingview_bundle_health_tracks_all_three_production_coverages(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            ledger_path = runtime / "v32_signal_events.json"
            futures_coverage = tradingview_alert_coverage.load_coverage()
            options_coverage_path = ROOT / "config" / "tradingview_options_underlying_alert_coverage_v1.json"
            options_coverage = tradingview_alert_coverage.load_coverage(options_coverage_path)
            chris_coverage_path = ROOT / "config" / "tradingview_chris_ia_alert_coverage_v1.json"
            chris_coverage = tradingview_alert_coverage.load_coverage(chris_coverage_path)
            for alert in tradingview_alert_coverage.alerts(futures_coverage):
                payload = tradingview_operational_health.concrete_payload_for_event_code(alert["event_code"])
                tradingview_signal_ledger.append_signal_event(
                    payload,
                    raw_text=json.dumps(payload),
                    endpoint="/technical_snapshot",
                    path=ledger_path,
                )
            for alert in tradingview_alert_coverage.alerts(options_coverage):
                payload = tradingview_operational_health.concrete_payload_for_event_code(
                    alert["event_code"],
                    coverage_path=options_coverage_path,
                )
                tradingview_signal_ledger.append_signal_event(
                    payload,
                    raw_text=json.dumps(payload),
                    endpoint="/technical_snapshot",
                    path=ledger_path,
                )
            for alert in tradingview_alert_coverage.alerts(chris_coverage):
                payload = tradingview_operational_health.concrete_payload_for_event_code(
                    alert["event_code"],
                    coverage_path=chris_coverage_path,
                )
                tradingview_signal_ledger.append_signal_event(
                    payload,
                    raw_text=json.dumps(payload),
                    endpoint="/technical_snapshot",
                    path=ledger_path,
                )

            bundle = tradingview_operational_health.build_alert_bundle_health(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
                allow_local_replay_validation=True,
            )

        self.assertEqual(bundle["bundle_health_version"], "tradingview_alert_bundle_health_v1")
        self.assertTrue(bundle["coverage_valid"])
        self.assertTrue(bundle["real_e2e_confirmed"])
        self.assertEqual(bundle["coverage_count"], 3)
        self.assertEqual(bundle["readiness_coverage_count"], 2)
        self.assertEqual(bundle["supplemental_coverage_count"], 1)
        self.assertTrue(bundle["supplemental_real_e2e_confirmed"])
        self.assertEqual(bundle["total_production_active_alert_count"], 5)
        self.assertEqual(bundle["total_required_logical_event_count"], 20)
        self.assertEqual(bundle["total_expected_alert_count"], 24)
        self.assertEqual(bundle["total_required_alert_count"], 20)
        self.assertEqual(bundle["total_health_alert_count"], 4)
        self.assertEqual(bundle["total_received_required_event_count"], 20)
        self.assertEqual(bundle["total_received_health_event_count"], 4)
        self.assertEqual(bundle["missing_required_event_codes_by_coverage"], {})
        self.assertEqual(bundle["total_quarantine_event_count"], 0)

    def test_ibkr_diagnostic_summarizes_missing_option_fields(self):
        diagnostic = ibkr_diagnostics.build_cycle_diagnostic(
            symbols=["QQQ"],
            chain_events=[{"ticker": "QQQ", "status": "CHAIN_SELECTED"}],
            option_rows=[
                {
                    "ticker": "QQQ",
                    "strategy": "NAKED_PUT",
                    "underlying_price": 712.5,
                    "bid": 1.0,
                    "ask": None,
                    "mid": 1.05,
                    "strike": 700,
                    "expiration": "20260821",
                    "dte": 48,
                    "delta": -0.18,
                    "iv": 0.27,
                    "data_quality": "PRICE_WITH_GREEKS_NO_BIDASK",
                }
            ],
        )

        self.assertEqual(diagnostic["diagnostic_version"], "ibkr_chain_coverage_v2")
        self.assertEqual(diagnostic["primary_gap"], "INCOMPLETE_OPTION_MARKET_DATA")
        self.assertEqual(diagnostic["missing_execution_field_counts"]["ask"], 1)
        self.assertEqual(diagnostic["option_rows"][0]["iv"], 0.27)
        self.assertEqual(diagnostic["option_rows"][0]["delta"], -0.18)
        self.assertEqual(diagnostic["option_rows"][0]["underlying_price"], 712.5)
        self.assertEqual(diagnostic["discard_reason_counts"]["NO_BID_ASK"], 1)
        self.assertEqual(diagnostic["discard_reason_counts"]["PRICE_WITH_GREEKS_NO_BIDASK"], 1)
        self.assertEqual(diagnostic["discarded_contract_count"], 1)
        self.assertFalse(diagnostic["execution_authorized"])

    def test_position_chain_store_preserves_last_nonempty_ticker_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "position_chains.json"
            first = ibkr_diagnostics.build_cycle_diagnostic(
                symbols=["NFLX"],
                chain_events=[{"ticker": "NFLX", "status": "CHAIN_SELECTED"}],
                option_rows=[{
                    "ticker": "NFLX", "strategy": "COVERED_CALL", "bid": 2.9, "ask": 3.1,
                    "mid": 3.0, "spread_pct": 6.67, "strike": 125, "expiration": "20260828",
                    "dte": 39, "delta": 0.3, "iv": 0.25,
                }],
            )
            ibkr_diagnostics.merge_position_chain_store(first, path)
            empty = ibkr_diagnostics.build_cycle_diagnostic(symbols=["NFLX"], chain_events=[], option_rows=[])
            preserved = ibkr_diagnostics.merge_position_chain_store(empty, path)

        self.assertEqual(preserved["by_ticker"]["NFLX"]["option_row_count"], 1)
        self.assertEqual(preserved["by_ticker"]["NFLX"]["data_status"], "STALE_PRESERVED_AFTER_EMPTY_SCAN")
        self.assertEqual(preserved["by_ticker"]["NFLX"]["option_rows"][0]["strike"], 125)


if __name__ == "__main__":
    unittest.main()
