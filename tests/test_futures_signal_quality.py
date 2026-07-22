import unittest
from unittest.mock import patch

from test_v29_v30_contract_gating import main


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

    def test_watch_only_entry_does_not_generate_urgent_mobile_push(self):
        payload = main.apply_intraday_futures_signal_quality_gate(
            self.weak_countertrend_short()
        )
        with patch.object(main, "send_pushover_message") as send:
            result = main._v32_intraday_futures_immediate_notify_payload(payload)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "COUNTERTREND_CONFIRMATION_INSUFFICIENT")
        self.assertFalse(result["would_notify"])
        send.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
