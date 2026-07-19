import unittest
from unittest.mock import patch

import alert_effectiveness
from scripts import ibkr_account_profile as account_console


class AlertEffectivenessTests(unittest.TestCase):
    def setUp(self):
        self.decisions = [
            {"decision_id": "D1", "ticker": "AAPL", "strategy": "NAKED_PUT", "final_state": "ENTRY_READY", "recorded_at": "2026-07-01T10:00:00+00:00"},
            {"decision_id": "D2", "ticker": "MSFT", "strategy": "NAKED_PUT", "final_state": "ENTRY_READY", "recorded_at": "2026-07-01T10:05:00+00:00"},
            {"decision_id": "D3", "ticker": "TSLA", "strategy": "NAKED_PUT", "final_state": "RISK_BLOCKED", "recorded_at": "2026-07-01T10:10:00+00:00"},
            {"decision_id": "D4", "ticker": "NVDA", "strategy": "NAKED_PUT", "final_state": "RISK_BLOCKED", "recorded_at": "2026-07-01T10:15:00+00:00"},
        ]
        self.outcomes = [
            {"decision_id": "D1", "ticker": "AAPL", "strategy": "NAKED_PUT", "outcome": "WIN", "recorded_at": "2026-07-02T10:00:00+00:00"},
            {"decision_id": "D2", "ticker": "MSFT", "strategy": "NAKED_PUT", "outcome": "LOSS", "recorded_at": "2026-07-02T10:00:00+00:00"},
            {"decision_id": "D3", "ticker": "TSLA", "strategy": "NAKED_PUT", "outcome": "LOSS", "recorded_at": "2026-07-02T10:00:00+00:00"},
            {"decision_id": "D4", "ticker": "NVDA", "strategy": "NAKED_PUT", "outcome": "WIN", "recorded_at": "2026-07-02T10:00:00+00:00"},
        ]

    def test_computes_only_verified_effectiveness(self):
        payload = alert_effectiveness.build_effectiveness(self.decisions, self.outcomes)

        self.assertEqual(payload["entry_alert_count"], 2)
        self.assertEqual(payload["resolved_entry_alert_count"], 2)
        self.assertEqual(payload["useful_alert_count"], 1)
        self.assertEqual(payload["false_positive_count"], 1)
        self.assertEqual(payload["verified_precision_pct"], 50.0)
        self.assertEqual(payload["missed_opportunity_count"], 1)
        self.assertEqual(payload["correct_risk_block_count"], 1)
        self.assertFalse(payload["automatic_rule_changes_authorized"])

    def test_unresolved_alerts_do_not_look_like_zero_false_positives(self):
        payload = alert_effectiveness.build_effectiveness(self.decisions[:1], [])
        with patch.object(account_console, "load_alert_effectiveness", return_value=payload):
            rendered = account_console.render_alert_effectiveness_panel()

        self.assertEqual(payload["status"], "WAITING_FOR_OUTCOMES")
        self.assertIsNone(payload["verified_precision_pct"])
        self.assertIn("Efectividad del alertamiento", rendered)
        self.assertIn("Falsas alarmas</span><strong>Sin muestra", rendered)
        self.assertIn("Ninguna métrica cambia reglas automáticamente", rendered)


if __name__ == "__main__":
    unittest.main()
