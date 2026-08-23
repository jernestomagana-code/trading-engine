import unittest
from pathlib import Path
from unittest.mock import patch

from test_v29_v30_contract_gating import main
from scripts import v32_operator_notify


class FuturesMobileAlertTests(unittest.TestCase):
    def chris_entry(self):
        return {
            "strategy_context": "CHRIS_IA_REVERSAL_PRO",
            "ticker": "US500F",
            "timeframe": "15m",
            "event": "ENTRY",
            "event_code": "CHRIS_IA_US500F_SHORT_ENTRY_15",
            "breakout_direction": "SHORT",
            "price": 7533.7,
            "atr_pct": 0.117949,
            "score": 100,
            "final_state": "MANUAL_REVIEW",
            "main_blocker": "RISK_ENGINE_NEEDS_REVIEW",
            "not_order_instruction": True,
        }

    def test_missing_levels_receive_transparent_atr_reference_plan(self):
        result = main.apply_intraday_futures_reference_levels(self.chris_entry())

        self.assertEqual(result["entry_price"], 7533.7)
        self.assertEqual(result["stop_price"], 7542.59)
        self.assertEqual(result["tp1_price"], 7524.81)
        self.assertEqual(result["tp2_price"], 7515.93)
        self.assertEqual(result["tp1_rr_ratio"], 1.0)
        self.assertEqual(result["tp2_rr_ratio"], 2.0)
        self.assertTrue(result["reference_levels_provisional"])
        self.assertEqual(result["reference_level_source"], "ATR_1R_2R")

    def test_durable_ledger_projection_also_recovers_reference_levels(self):
        signal = {
            **self.chris_entry(),
            "event_id": "TV-mobile-durable-1",
            "accepted_for_engine": True,
            "received_at": "2026-07-22T14:30:07+00:00",
            "raw_payload": self.chris_entry(),
        }
        with patch.object(main, "supabase_fetch_table_rows", return_value=[]), patch.object(
            main, "load_intraday_futures_alert_events_from_file", return_value=[]
        ), patch.object(main, "_v32_load_tradingview_signal_events", return_value=[signal]):
            events = main.load_intraday_futures_alert_events(limit=100)

        self.assertEqual(events[0]["stop_price"], 7542.59)
        self.assertEqual(events[0]["tp1_price"], 7524.81)
        self.assertEqual(events[0]["tp2_price"], 7515.93)
        self.assertTrue(events[0]["reference_levels_provisional"])

    def test_immediate_mobile_message_is_compact_and_action_oriented(self):
        payload = main.apply_intraday_futures_reference_levels(self.chris_entry())
        message = main._v32_intraday_futures_immediate_message(payload, "ENTRY_TRIGGER")

        self.assertIn("US500F SHORT", message)
        self.assertIn("Disparo: 7,533.70", message)
        self.assertIn("Stop: 7,542.59", message)
        self.assertIn("Target 1: 7,524.81", message)
        self.assertIn("Target 2: 7,515.93", message)
        self.assertIn("revisar ahora; aún no ejecutar", message)
        self.assertIn("Niveles estimados por ATR", message)
        self.assertNotIn("RISK_ENGINE_NEEDS_REVIEW", message)
        self.assertNotIn("MANUAL_REVIEW", message)

    def test_immediate_push_runs_before_secondary_storage(self):
        calls = []
        with patch.object(
            main,
            "_v32_intraday_futures_immediate_notify_payload",
            side_effect=lambda payload: calls.append("notify") or {"status": "sent", "pushover_sent": True},
        ), patch.object(
            main,
            "save_intraday_futures_alert_event",
            side_effect=lambda payload: calls.append("event_storage") or {"saved": True},
        ), patch.object(
            main,
            "save_intraday_futures_price_point",
            side_effect=lambda payload: calls.append("price_storage") or {"saved": True},
        ), patch.object(
            main,
            "_durable_supabase_persist",
            side_effect=lambda kind, payload: calls.append("mobile_telemetry") or {"saved": True},
        ):
            result = main._v32_process_intraday_futures_alert(self.chris_entry(), notify=True)

        self.assertEqual(calls, ["notify", "mobile_telemetry", "event_storage", "price_storage"])
        self.assertTrue(result["immediate_notify"]["pushover_sent"])
        self.assertTrue(result["mobile_telemetry_storage"]["saved"])

    def test_missing_source_timestamp_is_disclosed_without_suppressing_entry(self):
        with patch.object(main, "_v29_load_json_file", return_value={}), patch.object(
            main, "_v32_save_intraday_futures_immediate_state", return_value=True
        ), patch.object(main, "send_pushover_message", return_value={"pushover_sent": True}):
            result = main._v32_intraday_futures_immediate_notify_payload(self.chris_entry())

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["signal_timestamp_source"], "received_at")
        self.assertEqual(result["signal_timestamp_status"], "RECEIVED_AT_FALLBACK")

    def test_immediate_entry_push_uses_high_priority_and_distinct_sound(self):
        payload = main.apply_intraday_futures_reference_levels(self.chris_entry())
        with patch.object(main, "_v29_load_json_file", return_value={}), patch.object(
            main, "_v32_save_intraday_futures_immediate_state", return_value=True
        ), patch.object(main, "send_pushover_message", return_value={"pushover_sent": True}) as send:
            result = main._v32_intraday_futures_immediate_notify_payload(payload)

        self.assertEqual(result["status"], "sent")
        _, _, kwargs = send.mock_calls[0]
        self.assertEqual(kwargs["priority"], 1)
        self.assertEqual(kwargs["sound"], "cashregister")
        self.assertEqual(kwargs["notification_kind"], "ENTRY")

    def test_local_classifier_recognizes_explicit_entry_event_only(self):
        payload = main.apply_intraday_futures_reference_levels(self.chris_entry())
        operator = {
            "active_alerts": [{
                **payload,
                "alert_id": "IFEV-TV-mobile-1",
                "strategy": "INTRADAY_INDEX_FUTURES",
                "severity": "WATCH",
                "state": "MANUAL_REVIEW",
                "manual_review_ready": True,
            }]
        }
        classification = v32_operator_notify.classify(operator)
        self.assertTrue(classification["should_notify"])
        self.assertEqual(classification["actionable_count"], 1)
        self.assertEqual(classification["actionable_alerts"][0]["event"], "ENTRY")

    def test_risk_invalidation_is_kept_out_of_mobile(self):
        payload = {
            **self.chris_entry(),
            "event": "RISK_INVALIDATION",
            "event_code": "MES_RISK_INVALIDATION_5M",
        }
        with patch.object(main, "send_pushover_message") as send:
            result = main._v32_intraday_futures_immediate_notify_payload(payload)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "RISK_SUPPRESSED_BY_MOBILE_ENTRY_POLICY")
        send.assert_not_called()

    def test_prepare_is_recorded_as_low_priority_without_entry_push(self):
        payload = {
            **self.chris_entry(),
            "event": "WATCH",
            "event_code": "CHRIS_IA_US500F_SHORT_WATCH_15",
            "alert_priority": "LOW",
            "signal_actionability": "WATCH_ONLY",
        }
        with patch.object(main, "send_pushover_message") as send:
            result = main._v32_intraday_futures_immediate_notify_payload(payload)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "PREPARE_RECORDED_LOW_PRIORITY_NO_MOBILE_PUSH")
        self.assertFalse(result["would_notify"])
        send.assert_not_called()

    def test_central_pushover_gate_rejects_non_entry_kind(self):
        with patch.object(main.requests, "post") as post:
            result = main.send_pushover_message("Riesgo", "Revisar", notification_kind="RISK")

        self.assertFalse(result["pushover_sent"])
        self.assertEqual(result["reason"], "MOBILE_ENTRY_ONLY_POLICY")
        post.assert_not_called()

    def test_chris_ia_pine_exposes_prepare_then_confirmed_entry_alerts(self):
        pine = (Path(__file__).resolve().parents[1] / "pine" / "chris_ia_reversal_engine_pro.pine").read_text()

        self.assertIn('input.bool(true, "Alertar ENTRY confirmado"', pine)
        self.assertIn('input.bool(true, "Alertar PREPARE/WATCH"', pine)
        self.assertIn('alertcondition(longConfirmed, "Chris IA PRO LONG ENTRY"', pine)
        self.assertIn('alertcondition(shortConfirmed, "Chris IA PRO SHORT ENTRY"', pine)
        self.assertIn('alertcondition(longWatch, "Chris IA PRO LONG PREPARE"', pine)
        self.assertIn('alertcondition(shortWatch, "Chris IA PRO SHORT PREPARE"', pine)
        self.assertNotIn('alertcondition(longRebound, "Chris IA PRO LONG REBOTE"', pine)
        self.assertNotIn('alertcondition(shortRebound, "Chris IA PRO SHORT REBOTE"', pine)
        self.assertIn('alert(f_chris_payload("LONG", "WATCH"', pine)
        self.assertIn('alert(f_chris_payload("SHORT", "WATCH"', pine)
        self.assertIn('alert(f_chris_payload("LONG", "WATCH_CANCELED"', pine)
        self.assertIn("alert_priority", pine)
        self.assertIn("trigger_price", pine)
        self.assertIn("missing_confirmations", pine)
        self.assertNotIn('alert(f_chris_payload("LONG", "REBOTE"', pine)
        self.assertNotIn('alert(f_chris_payload("SHORT", "REBOTE"', pine)
        self.assertNotIn('f_row(1, "ACTUAL"', pine)
        for phrase in (
            "ACCIÓN AHORA", "GRÁFICO ", "SEÑAL ", "CONFIRMA ",
            "TENDENCIA ", "PRÓXIMO GATILLO", "SIGUIENTE PASO",
            "ALERTA = EVIDENCIA",
        ):
            self.assertIn(f'"{phrase}', pine)


if __name__ == "__main__":
    unittest.main()
