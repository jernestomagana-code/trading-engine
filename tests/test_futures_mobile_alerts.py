import unittest
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
        ):
            result = main._v32_process_intraday_futures_alert(self.chris_entry(), notify=True)

        self.assertEqual(calls, ["notify", "event_storage", "price_storage"])
        self.assertTrue(result["immediate_notify"]["pushover_sent"])

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

    def test_local_fallback_uses_same_compact_futures_format(self):
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
        title, body = v32_operator_notify.notification_text({
            "operator_status": "READY_FOR_TRADING_DAY",
            "classification": classification,
        })

        self.assertEqual(title, "US500F SHORT · FUTUROS")
        self.assertIn("Disparo 7,533.70", body)
        self.assertIn("Stop 7,542.59", body)
        self.assertIn("T1 7,524.81", body)
        self.assertIn("T2 7,515.93", body)
        self.assertNotIn("MANUAL_REVIEW", body)
        self.assertNotIn("RISK_ENGINE_NEEDS_REVIEW", body)


if __name__ == "__main__":
    unittest.main()
