import json
import tempfile
import unittest
from pathlib import Path

import decision_outcome_intelligence as intelligence
from scripts import ibkr_account_profile as account_console


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
            }
        ]

    def test_builds_traceability_and_evidence_progress(self):
        payload = intelligence.build_intelligence(
            self.decisions, self.outcomes, generated_at="2026-07-06T00:00:00+00:00"
        )

        self.assertEqual(payload["decision_count"], 3)
        self.assertEqual(payload["actionable_decision_count"], 2)
        self.assertEqual(payload["linked_actionable_outcome_count"], 1)
        self.assertEqual(payload["actionable_outcome_coverage_pct"], 50.0)
        self.assertEqual(payload["status"], "BUILDING_EVIDENCE")
        self.assertFalse(payload["automatic_parameter_changes_authorized"])
        self.assertEqual(payload["recent_decisions"][0]["ticker"], "MSFT")
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
        self.assertIn("50.0%", rendered)
        self.assertIn("NAKED_PUT", rendered)
        self.assertIn("no cambia parámetros automáticamente", rendered)


if __name__ == "__main__":
    unittest.main()
