import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import decision_outcome_intelligence as intelligence
from scripts import ibkr_account_profile as account_console
from scripts import run_daily_outcome_evaluation as daily_runner


class DecisionOutcomeIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.decisions = [
            {
                "decision_id": "D1", "ticker": "AAPL", "strategy": "NAKED_PUT",
                "final_state": "ENTRY_READY", "decision": "ENTRY_READY",
                "action": "Revisar entrada", "recorded_at": "2026-07-01T10:00:00+00:00",
            },
            {
                "decision_id": "D2", "ticker": "MSFT", "strategy": "NAKED_PUT",
                "signal_id": "S2",
                "final_state": "MANUAL_REVIEW", "decision": "MANUAL_REVIEW",
                "action": "Esperar confirmación", "recorded_at": "2026-07-02T10:00:00+00:00",
            },
            {
                "decision_id": "D3", "ticker": "TLT", "strategy": "UNKNOWN",
                "final_state": "NO_DATA", "decision": "NO_DATA",
                "recorded_at": "2026-07-03T10:00:00+00:00",
            },
        ]
        self.outcomes = [
            {
                "outcome_id": "O1", "decision_id": "D1", "ticker": "AAPL",
                "strategy": "NAKED_PUT", "outcome": "WIN", "pnl_r": 1.0,
                "mfe_r": 1.2, "mae_r": -0.2, "market_regime": "BULLISH_LOW_VOL",
                "recorded_at": "2026-07-05T10:00:00+00:00",
                "selected_contract": {"expiration": "20260821", "strike": 200, "right": "P"},
                "candidate_source": "IBKR", "confirmation_source": "TRADINGVIEW",
            },
            {
                "outcome_id": "O2", "signal_id": "S2", "ticker": "MSFT",
                "strategy": "NAKED_PUT", "outcome": "PENDING",
                "recorded_at": "2026-07-05T11:00:00+00:00",
            }
        ]

    def test_builds_traceability_and_evidence_progress(self):
        payload = intelligence.build_intelligence(
            self.decisions, self.outcomes, generated_at="2026-07-06T00:00:00+00:00"
        )

        self.assertEqual(payload["decision_count"], 3)
        self.assertEqual(payload["actionable_decision_count"], 2)
        self.assertEqual(payload["linked_actionable_outcome_count"], 2)
        self.assertEqual(payload["actionable_outcome_coverage_pct"], 100.0)
        self.assertEqual(payload["status"], "BUILDING_EVIDENCE")
        self.assertFalse(payload["automatic_parameter_changes_authorized"])
        self.assertEqual(payload["recent_decisions"][0]["ticker"], "MSFT")
        self.assertEqual(payload["recent_decisions"][0]["outcome"], "PENDING")
        self.assertEqual(payload["recent_decisions"][1]["outcome"], "WIN")

    def test_console_renders_decision_outcome_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_decisions = account_console.DECISION_JOURNAL_PATH
            original_outcomes = account_console.OUTCOME_JOURNAL_PATH
            account_console.DECISION_JOURNAL_PATH = Path(tmp) / "decisions.json"
            account_console.OUTCOME_JOURNAL_PATH = Path(tmp) / "outcomes.json"
            account_console.DECISION_JOURNAL_PATH.write_text(json.dumps(self.decisions))
            account_console.OUTCOME_JOURNAL_PATH.write_text(json.dumps(self.outcomes))
            try:
                rendered = account_console.render_decision_outcome_panel()
            finally:
                account_console.DECISION_JOURNAL_PATH = original_decisions
                account_console.OUTCOME_JOURNAL_PATH = original_outcomes

        self.assertIn("Historial de decisiones y resultados", rendered)
        self.assertIn("Cobertura accionable", rendered)
        self.assertIn("100.0%", rendered)
        self.assertIn("NAKED_PUT", rendered)
        self.assertIn("no cambia parámetros automáticamente", rendered)
        self.assertIn("Seguimiento automático", rendered)
        self.assertIn("Actualizar seguimiento ahora", rendered)

    def test_history_summary_explains_when_sample_is_not_ready(self):
        payload = intelligence.build_intelligence(
            self.decisions, self.outcomes, generated_at="2026-07-06T00:00:00+00:00"
        )
        effectiveness = {"resolved_entry_alert_count": 1, "verified_precision_pct": 100.0}
        with patch.object(account_console, "load_decision_outcome_intelligence", return_value=payload), patch.object(
            account_console, "load_alert_effectiveness", return_value=effectiveness
        ):
            rendered = account_console.render_history_learning_summary()

        self.assertIn("Todavía no conviene cambiar parámetros", rendered)
        self.assertIn("Faltan 30 resultados", rendered)
        self.assertIn("Todavía no hay resultados completos por estrategia", rendered)
        self.assertIn("Precisión verificable", rendered)

    def test_history_summary_marks_review_ready_without_automatic_changes(self):
        payload = {
            "parameter_review_ready": True,
            "decision_count": 42,
            "complete_closed_outcomes": 30,
            "minimum_complete_outcomes": 30,
            "actionable_outcome_coverage_pct": 95.0,
            "strategies": [{
                "strategy": "FUTURES_FAST",
                "complete_closed_outcomes": 30,
                "win_rate": 60.0,
                "expectancy_r": 0.25,
                "parameter_review_ready": True,
            }],
        }
        effectiveness = {"resolved_entry_alert_count": 30, "verified_precision_pct": 60.0}
        with patch.object(account_console, "load_decision_outcome_intelligence", return_value=payload), patch.object(
            account_console, "load_alert_effectiveness", return_value=effectiveness
        ):
            rendered = account_console.render_history_learning_summary()

        self.assertIn("Ya existe evidencia suficiente para revisar parámetros", rendered)
        self.assertIn("LISTO PARA REVISIÓN", rendered)
        self.assertIn("Muestra suficiente para revisión manual", rendered)

    def test_remote_outcomes_sync_is_sanitized_and_atomic(self):
        remote = {
            "outcomes": [{
                "outcome_id": "O1", "decision_id": "D1", "ticker": "AAPL",
                "outcome": "WIN", "account_id": "SENSITIVE", "nested": {"api_token": "SECRET", "pnl_r": 1.0},
            }],
            "not_order_instruction": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "outcomes.json"
            with patch.object(daily_runner, "request_json", return_value=(200, remote)):
                result = daily_runner.sync_local_outcomes("https://example.test", "token", 5, target)
            saved = json.loads(target.read_text())

        self.assertEqual(result["status"], "SYNCED")
        self.assertEqual(result["written_count"], 1)
        self.assertNotIn("account_id", saved[0])
        self.assertNotIn("api_token", saved[0]["nested"])
        self.assertEqual(saved[0]["nested"]["pnl_r"], 1.0)
        self.assertFalse(result["execution_authorized"])

    def test_sync_refuses_payload_without_no_order_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "outcomes.json"
            with patch.object(daily_runner, "request_json", return_value=(200, {"outcomes": [{}]})):
                result = daily_runner.sync_local_outcomes("https://example.test", "token", 5, target)

        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(target.exists())

    def test_remote_decisions_sync_uses_protected_read_payload(self):
        remote = {
            "decisions": [{"decision_id": "D1", "ticker": "AAPL", "account_number": "SECRET"}],
            "not_order_instruction": True,
            "execution_authorized": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "decisions.json"
            with patch.object(daily_runner, "request_json", return_value=(200, remote)) as request:
                result = daily_runner.sync_local_decisions("https://example.test", "token", 5, target)
            saved = json.loads(target.read_text())

        self.assertEqual(result["status"], "SYNCED")
        self.assertEqual(result["remote_decision_count"], 1)
        self.assertNotIn("account_number", saved[0])
        self.assertIn("/v32_decisions?limit=1000", request.call_args.args[0])

    def test_contract_and_entry_time_link_legacy_decision_without_shared_id(self):
        decisions = [{
            "decision_id": "LEGACY-D1", "ticker": "SPY", "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY", "recorded_at": "2026-06-22T13:55:52+00:00",
            "selected_contract": {"expiration": "20260731", "strike": 675.0},
        }]
        outcomes = [{
            "signal_id": "SIG-SPY-675", "ticker": "SPY", "strategy": "NAKED_PUT",
            "outcome": "PENDING", "entry_ready_at": "2026-06-22T13:55:52+00:00",
            "selected_contract": {"expiration": "20260731", "strike": 675.0},
        }]

        payload = intelligence.build_intelligence(decisions, outcomes)

        self.assertEqual(payload["linked_actionable_outcome_count"], 1)
        self.assertEqual(payload["actionable_outcome_coverage_pct"], 100.0)
        self.assertEqual(payload["recent_decisions"][0]["outcome"], "PENDING")


if __name__ == "__main__":
    unittest.main()
