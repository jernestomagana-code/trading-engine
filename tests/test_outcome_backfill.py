import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import outcome_backfill


class OutcomeBackfillTests(unittest.TestCase):
    def test_backfill_repairs_outcome_from_matched_decision(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runtime.joinpath("v32_outcomes_journal.json").write_text(
                json.dumps(
                    [
                        {
                            "outcome_id": "OUT-1",
                            "decision_id": "DEC-1",
                            "ticker": "QQQ",
                            "strategy": "NAKED_PUT",
                            "outcome": "WIN",
                        }
                    ]
                )
            )
            runtime.joinpath("v32_decision_journal.json").write_text(
                json.dumps(
                    [
                        {
                            "decision_id": "DEC-1",
                            "ticker": "QQQ",
                            "strategy": "NAKED_PUT",
                            "final_state": "ENTRY_READY",
                            "technical": {"bias": "BULLISH", "score": 82},
                            "market": {"vix": 15.0},
                            "selected_contract": {
                                "strike": 450,
                                "expiration": "2026-08-21",
                                "dte": 42,
                                "bid": 1.0,
                                "ask": 1.1,
                                "mid": 1.05,
                                "spread_pct": 9.52,
                                "delta": -0.2,
                                "iv": 0.31,
                            },
                            "followups": [
                                {"pnl_r": 0.2},
                                {"pnl_r": -0.1},
                                {"pnl_r": 0.6},
                            ],
                        }
                    ]
                )
            )

            report = outcome_backfill.build_backfill_report(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                write=False,
            )

            self.assertEqual(report["changed_count"], 1)
            self.assertEqual(report["complete_after_count"], 1)
            self.assertEqual(report["field_update_counts"]["selected_contract"], 1)
            repair = report["repairs"][0]
            self.assertEqual(repair["matched_decision_id"], "DEC-1")
            self.assertEqual(repair["unresolved_fields"], [])

    def test_backfill_does_not_fabricate_missing_contract_iv(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runtime.joinpath("v32_outcomes_journal.json").write_text(
                json.dumps(
                    [
                        {
                            "outcome_id": "OUT-1",
                            "decision_id": "DEC-1",
                            "ticker": "AAPL",
                            "strategy": "NAKED_PUT",
                            "outcome": "WIN",
                        }
                    ]
                )
            )
            runtime.joinpath("v32_decision_journal.json").write_text(
                json.dumps(
                    [
                        {
                            "decision_id": "DEC-1",
                            "ticker": "AAPL",
                            "strategy": "NAKED_PUT",
                            "final_state": "ENTRY_READY",
                            "technical": {"bias": "BULLISH", "score": 85},
                            "selected_contract": {
                                "strike": 180,
                                "expiration": "2026-07-17",
                                "dte": 39,
                                "bid": 1.2,
                                "ask": 1.35,
                                "mid": 1.275,
                                "spread_pct": 11.76,
                                "delta": -0.28,
                                "iv": None,
                            },
                            "followups": [{"pnl_r": 1.0}],
                        }
                    ]
                )
            )

            report = outcome_backfill.build_backfill_report(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                write=False,
            )

            self.assertEqual(report["changed_count"], 1)
            self.assertEqual(report["complete_after_count"], 0)
            self.assertEqual(report["unresolved_field_counts"]["selected_contract.iv"], 1)
            repair = report["repairs"][0]
            self.assertIn("selected_contract.iv", repair["unresolved_fields"])
            self.assertFalse(report["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
