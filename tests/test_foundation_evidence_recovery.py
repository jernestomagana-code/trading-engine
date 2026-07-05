import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import foundation_evidence_recovery
import outcome_backfill


def write_runtime(runtime: Path) -> None:
    runtime.joinpath("v32_decision_journal.json").write_text(
        json.dumps(
            [
                {
                    "decision_id": "DEC-1",
                    "ticker": "QQQ",
                    "strategy": "NAKED_PUT",
                    "final_state": "ENTRY_READY",
                    "technical": {"bias": "BULLISH", "score": 84},
                    "selected_contract": {
                        "ticker": "QQQ",
                        "strategy": "NAKED_PUT",
                        "strike": 450,
                        "expiration": "2026-08-21",
                        "dte": 42,
                        "bid": 1.0,
                        "ask": 1.1,
                        "mid": 1.05,
                        "spread_pct": 9.52,
                        "delta": -0.2,
                        "iv": 0.31,
                        "volume": 100,
                        "open_interest": 500,
                    },
                    "followups": [{"pnl_r": 0.3}],
                }
            ]
        )
    )
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


class FoundationEvidenceRecoveryTests(unittest.TestCase):
    def test_source_backfill_and_ibkr_recovery_use_saved_decision_evidence(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            write_runtime(runtime)

            source_report = foundation_evidence_recovery.backfill_decision_sources(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                write=False,
            )
            ibkr_report = foundation_evidence_recovery.recover_ibkr_diagnostics(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                write=False,
            )

            self.assertEqual(source_report["changed_count"], 1)
            self.assertEqual(source_report["field_update_counts"]["candidate_source"], 1)
            self.assertEqual(ibkr_report["option_row_count"], 1)
            self.assertEqual(ibkr_report["primary_gap"], "COVERAGE_REVIEWABLE")
            self.assertEqual(ibkr_report["diagnostic"]["option_rows"][0]["iv"], 0.31)
            self.assertFalse(ibkr_report["execution_authorized"])

    def test_full_recovery_writes_diagnostics_and_enables_outcome_completion_without_tv_fabrication(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            write_runtime(runtime)

            payload = foundation_evidence_recovery.recover_foundation_evidence(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                write=True,
            )
            outcomes = outcome_backfill.list_from_payload(
                outcome_backfill.read_json(runtime / "v32_outcomes_journal.json", []),
                ["outcomes", "rows", "items"],
            )

            self.assertTrue((runtime / "v32_ibkr_chain_coverage.json").exists())
            self.assertEqual(payload["outcome_backfill"]["complete_after_count"], 1)
            self.assertEqual(outcomes[0]["selected_contract"]["iv"], 0.31)
            self.assertEqual(payload["tradingview_ledger_replay"]["existing_event_count"], 0)
            self.assertIn("NO_TRADINGVIEW_LEDGER_EVENTS", payload["collection_readiness"]["blockers"])


if __name__ == "__main__":
    unittest.main()
