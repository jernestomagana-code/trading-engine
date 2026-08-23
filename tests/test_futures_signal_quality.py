import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from test_v29_v30_contract_gating import main
from scripts import ibkr_account_profile


class FuturesSignalQualityTests(unittest.TestCase):
    def weak_countertrend_short(self):
        return {
            "strategy_context": "CHRIS_IA_REVERSAL_PRO",
            "ticker": "US500F",
            "timeframe": "15m",
            "event": "ENTRY",
            "event_code": "CHRIS_IA_US500F_SHORT_ENTRY_15",
            "direction": "SHORT",
            "price": 7533.7,
            "score": 100,
            "trend_state": "ALCISTA+",
            "mtf_long_votes": 2,
            "mtf_short_votes": 1,
            "macd_z": 1.012596,
            "rsi": 54.329256,
            "stoch_k": 78.594455,
            "stoch_d": 87.469318,
            "counter_trend": False,
            "not_order_instruction": True,
        }

    def test_pine_classifies_opposite_mtf_majority_as_rebound_not_confirmed_entry(self):
        pine = (Path(__file__).resolve().parents[1] / "pine" / "chris_ia_reversal_engine_pro.pine").read_text()

        self.assertIn("mtfLongVotes <= mtfShortVotes", pine)
        self.assertIn("mtfShortVotes <= mtfLongVotes", pine)
        self.assertIn("shortRebound = shortEntry and counterTrendShort", pine)
        self.assertNotIn('alert(f_chris_payload("SHORT", "REBOTE"', pine)
        self.assertIn('f_chris_payload("SHORT", "ENTRY"', pine)
        self.assertIn('text="CT BLOQ L"', pine)
        self.assertIn('text="CT BLOQ S"', pine)
        self.assertIn('longRebound or shortRebound ? color.new(color.orange', pine)

    def test_today_short_is_reclassified_as_weak_countertrend_watch(self):
        result = main.apply_intraday_futures_signal_quality_gate(
            self.weak_countertrend_short()
        )

        self.assertTrue(result["counter_trend"])
        self.assertFalse(result["source_counter_trend"])
        self.assertEqual(result["signal_actionability"], "WATCH_ONLY")
        self.assertEqual(result["confirmation_gate_status"], "INSUFFICIENT")
        self.assertEqual(result["confirmation_quality_score"], 20)
        self.assertEqual(result["confirmation_reasons"], ["CRUCE_ESTOCASTICO_BAJISTA"])
        self.assertEqual(
            result["confirmation_conflicts"],
            ["TENDENCIA_ALCISTA", "MAYORIA_MTF_LONG", "MACD_POSITIVO", "RSI_SOBRE_50"],
        )
        self.assertEqual(result["main_blocker"], "COUNTERTREND_CONFIRMATION_INSUFFICIENT")
        self.assertIn("1 de 3", result["decision_explanation"])

    def test_aligned_short_passes_quality_gate(self):
        payload = {
            **self.weak_countertrend_short(),
            "trend_state": "BAJISTA",
            "mtf_long_votes": 0,
            "mtf_short_votes": 3,
            "macd_z": -1.2,
            "rsi": 44,
            "counter_trend": True,
        }
        result = main.apply_intraday_futures_signal_quality_gate(payload)

        self.assertFalse(result["counter_trend"])
        self.assertEqual(result["signal_actionability"], "ACTIONABLE_CANDIDATE")
        self.assertEqual(result["confirmation_gate_status"], "PASSED")
        self.assertEqual(result["confirmation_quality_score"], 100)
        self.assertEqual(result["confirmation_conflicts"], [])

    def test_core_continuous_contract_keeps_direction_and_instrument_family(self):
        payload = main.normalize_technical_snapshot_payload({
            "source": "TRADINGVIEW",
            "action": "ALERT_ONLY",
            "strategy_context": "INTRADAY_INDEX_FUTURES",
            "ticker": "MES1!",
            "timeframe": "1m",
            "event": "ORB_BREAKOUT",
            "event_code": "MES_ORB_BREAKOUT_LONG_5M",
            "direction": "NONE",
            "breakout_direction": "LONG",
            "price": 7800.0,
            "logical_stop": 7795.0,
            "logical_target": 7810.0,
            "nlv": 50000.0,
            "portfolio_status": "CLEAR",
            "portfolio_engine_result": "CLEAR",
        })

        self.assertEqual(payload["direction"], "LONG")
        with patch.object(main, "get_intraday_futures_premarket_context", return_value={
            "found": True,
            "context": {
                "decision_max_state": "ENTRY_READY",
                "macro_status": "CLEAR",
                "volatility_status": "NORMAL",
                "risk_daily_status": "CLEAR",
                "portfolio_status": "CLEAR",
                "reference_alignment": "ALIGNED",
            },
        }):
            result = main.build_intraday_futures_construction(payload)

        self.assertEqual(result["direction"], "LONG")
        self.assertEqual(result["construction"]["direction"], "LONG")
        self.assertEqual(result["construction"]["instrument_family"], "S&P 500")
        self.assertEqual(result["target_instrument"], "MES")

    def test_core_signal_quality_matches_the_four_checks_shown_in_pine(self):
        payload = {
            "strategy_context": "INTRADAY_INDEX_FUTURES",
            "ticker": "MES1!",
            "event": "ORB_BREAKOUT",
            "event_code": "MES_ORB_BREAKOUT_LONG_5M",
            "breakout_direction": "LONG",
            "price": 7801.0,
            "vwap": 7799.0,
            "adx": 24.0,
            "volume_relative": 1.35,
            "plus_di": 28.0,
            "minus_di": 17.0,
        }

        result = main.apply_intraday_futures_signal_quality_gate(payload)

        self.assertEqual(result["signal_actionability"], "ACTIONABLE_CANDIDATE")
        self.assertEqual(result["confirmation_gate_status"], "PASSED")
        self.assertEqual(result["confirmation_quality_score"], 100)
        self.assertEqual(
            result["confirmation_reasons"],
            ["ADX_OK", "RVOL_OK", "VWAP_ALINEADO", "DMI_ALINEADO"],
        )
        self.assertEqual(result["confirmation_conflicts"], [])

    def test_core_dmi_conflict_lowers_quality_without_relaxing_baseline_gate(self):
        result = main.apply_intraday_futures_signal_quality_gate({
            "strategy_context": "INTRADAY_INDEX_FUTURES",
            "ticker": "MNQ1!",
            "event": "VWAP_RECLAIM",
            "event_code": "MNQ_VWAP_RECLAIM_LONG_5M",
            "breakout_direction": "LONG",
            "price": 30010.0,
            "vwap": 30000.0,
            "adx": 21.0,
            "volume_relative": 1.2,
            "plus_di": 14.0,
            "minus_di": 22.0,
        })

        self.assertEqual(result["signal_actionability"], "ACTIONABLE_CANDIDATE")
        self.assertEqual(result["confirmation_quality_score"], 75)
        self.assertEqual(result["confirmation_conflicts"], ["DMI_CONTRARIO"])

    def test_core_baseline_failure_stays_watch_only(self):
        result = main.apply_intraday_futures_signal_quality_gate({
            "strategy_context": "INTRADAY_INDEX_FUTURES",
            "ticker": "MES1!",
            "event": "ORB_BREAKOUT",
            "event_code": "MES_ORB_BREAKOUT_SHORT_5M",
            "breakout_direction": "SHORT",
            "price": 7790.0,
            "vwap": 7795.0,
            "adx": 16.0,
            "volume_relative": 1.3,
            "plus_di": 15.0,
            "minus_di": 25.0,
        })

        self.assertEqual(result["signal_actionability"], "WATCH_ONLY")
        self.assertEqual(result["main_blocker"], "CORE_TECHNICAL_CONFIRMATION_INSUFFICIENT")
        self.assertIn("ADX_BAJO_O_NO_DISPONIBLE", result["confirmation_conflicts"])

    def test_prepare_is_watch_only_and_never_promoted_to_entry(self):
        payload = {
            "strategy_context": "INTRADAY_INDEX_FUTURES",
            "ticker": "MES1!",
            "event": "PREPARE",
            "event_code": "MES_PREPARE_LONG_1M",
            "breakout_direction": "LONG",
            "price": 7800.0,
            "trigger_price": 7801.0,
            "alert_priority": "LOW",
            "not_order_instruction": True,
        }
        result = main.build_intraday_futures_construction(payload)
        event = main.build_intraday_futures_alert_event(result)

        self.assertTrue(main.intraday_futures_is_setup_wait_event(result["event_code"], result["event"]))
        self.assertEqual(result["signal_actionability"], "WATCH_ONLY")
        self.assertNotEqual(result["final_state"], "ENTRY_READY")
        self.assertEqual(event["evaluation_status"], "PENDING_OUTCOME")
        self.assertEqual(event["trigger_price"], 7801.0)

    def test_fast_and_chris_same_direction_receive_consensus_a(self):
        chris = {
            "event_id": "TV-CHRIS-1",
            "strategy_context": "CHRIS_IA_REVERSAL_PRO",
            "ticker": "US500F",
            "event": "ENTRY",
            "event_code": "CHRIS_IA_US500F_LONG_ENTRY_15",
            "breakout_direction": "LONG",
            "received_at": "2026-08-13T14:35:00+00:00",
        }
        fast = {
            "strategy_context": "INTRADAY_INDEX_FUTURES",
            "ticker": "MES1!",
            "event": "ORB_BREAKOUT",
            "event_code": "MES_ORB_BREAKOUT_LONG_5M",
            "breakout_direction": "LONG",
            "received_at": "2026-08-13T14:40:00+00:00",
        }

        result = main.apply_intraday_futures_strategy_consensus(fast, [chris])

        self.assertEqual(result["consensus_grade"], "A")
        self.assertEqual(result["consensus_status"], "CONFIRMED_BY_FAST_AND_CHRIS")
        self.assertEqual(result["consensus_sources"], ["CHRIS", "FAST"])

    def test_watch_only_entry_is_suppressed_from_mobile(self):
        payload = main.apply_intraday_futures_signal_quality_gate(
            self.weak_countertrend_short()
        )
        with patch.object(main, "_v29_load_json_file", return_value={}), patch.object(
            main, "_v32_save_intraday_futures_immediate_state", return_value=True
        ), patch.object(main, "send_pushover_message", return_value={"pushover_sent": True}) as send:
            result = main._v32_intraday_futures_immediate_notify_payload(payload)

        self.assertEqual(result["status"], "skipped")
        self.assertIsNone(result["trigger_kind"])
        self.assertFalse(result["would_notify"])
        self.assertEqual(result["reason"], "WATCH_ONLY_SUPPRESSED_BY_MOBILE_ENTRY_POLICY")
        send.assert_not_called()

    def test_rebound_keeps_radar_alert_and_receives_provisional_levels(self):
        payload = {
            **self.weak_countertrend_short(),
            "event": "REBOTE",
            "event_code": "CHRIS_IA_US500F_SHORT_REBOTE_15",
            "breakout_direction": "SHORT",
            "atr_pct": 0.117949,
        }
        result = main.apply_intraday_futures_reference_levels(payload)
        result = main.apply_intraday_futures_signal_quality_gate(result)

        self.assertEqual(result["signal_actionability"], "WATCH_ONLY")
        self.assertEqual(result["stop_price"], 7542.59)
        self.assertEqual(result["tp1_price"], 7524.81)
        self.assertEqual(result["tp2_price"], 7515.93)

    def test_historical_processed_event_is_reclassified_from_durable_ledger(self):
        old_event = main.build_intraday_futures_alert_event({
            **self.weak_countertrend_short(),
            "source_event_id": "TV-quality-history-1",
            "received_at": "2026-07-22T14:30:07+00:00",
            "final_state": "MANUAL_REVIEW",
            "decision": {"final_state": "MANUAL_REVIEW"},
        })
        signal = {
            **self.weak_countertrend_short(),
            "event_id": "TV-quality-history-1",
            "received_at": "2026-07-22T14:30:07+00:00",
            "accepted_for_engine": True,
            "raw_payload": self.weak_countertrend_short(),
        }
        with patch.object(main, "supabase_fetch_table_rows", return_value=[]), patch.object(
            main, "load_intraday_futures_alert_events_from_file", return_value=[old_event]
        ), patch.object(main, "_v32_load_tradingview_signal_events", return_value=[signal]):
            events = main.load_intraday_futures_alert_events(limit=100)

        self.assertEqual(events[0]["signal_actionability"], "WATCH_ONLY")
        self.assertEqual(events[0]["confirmation_quality_score"], 20)
        self.assertEqual(events[0]["main_blocker"], "COUNTERTREND_CONFIRMATION_INSUFFICIENT")

    def test_actionable_message_exposes_confirmation_balance(self):
        payload = {
            **self.weak_countertrend_short(),
            "trend_state": "BAJISTA",
            "mtf_long_votes": 0,
            "mtf_short_votes": 3,
            "macd_z": -1.2,
            "rsi": 44,
        }
        result = main.apply_intraday_futures_signal_quality_gate(payload)
        message = main._v32_intraday_futures_immediate_message(result, "ENTRY_TRIGGER")

        self.assertIn("Confirmación: 5 a favor · 0 conflicto(s)", message)

    def test_console_fallback_uses_processed_quality_instead_of_raw_action(self):
        received_at = datetime.now(timezone.utc).isoformat()
        raw = self.weak_countertrend_short()
        operator = {"ok": True, "data": {"active_alerts": [], "intraday_futures": {}}}
        payloads = {
            "signal_events": {"data": {"events": [{
                **raw,
                "event_id": "TV-console-quality-1",
                "received_at": received_at,
                "accepted_for_engine": True,
                "raw_payload": raw,
            }]}},
            "futures_daily": {"data": {
                "summary": {"total_events": 1},
                "latest_events": [{
                    "source_event_id": "TV-console-quality-1",
                    "received_at": received_at,
                    "ticker": "US500F",
                    "event": "ENTRY",
                    "event_code": "CHRIS_IA_US500F_SHORT_ENTRY_15",
                    "direction": "SHORT",
                    "entry_price": 7533.7,
                    "stop_price": 7542.59,
                    "tp1_price": 7524.81,
                    "tp2_price": 7515.93,
                    "rr_ratio": 2,
                    "reference_levels_provisional": True,
                    "signal_actionability": "WATCH_ONLY",
                    "confirmation_gate_status": "INSUFFICIENT",
                    "confirmation_quality_score": 20,
                    "confirmation_reasons": ["CRUCE_ESTOCASTICO_BAJISTA"],
                    "confirmation_conflicts": [
                        "TENDENCIA_ALCISTA", "MAYORIA_MTF_LONG", "MACD_POSITIVO", "RSI_SOBRE_50"
                    ],
                    "main_blocker": "COUNTERTREND_CONFIRMATION_INSUFFICIENT",
                    "decision_explanation": "Mantener en WATCH por confirmación insuficiente.",
                    "signal_trigger_explanation": "Disparó por cruce estocástico bajista.",
                    "signal_quality_explanation": "Una confirmación a favor y cuatro conflictos.",
                }],
            }},
        }

        result = ibkr_account_profile.merge_remote_futures_into_operator(operator, payloads)
        alert = result["data"]["active_alerts"][0]

        self.assertEqual(alert["severity"], "WATCH")
        self.assertFalse(alert["manual_review_ready"])
        self.assertEqual(alert["stop_price"], 7542.59)
        self.assertEqual(alert["confirmation_gate_status"], "INSUFFICIENT")
        self.assertEqual(len(alert["confirmation_conflicts"]), 4)
        self.assertEqual(ibkr_account_profile.alert_quality_score(alert), 20)
        self.assertIn("cruce estocástico", ibkr_account_profile.alert_reason_plain(alert))


if __name__ == "__main__":
    unittest.main()
