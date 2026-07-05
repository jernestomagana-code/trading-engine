import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import operational_evidence_gate


def decision(decision_id="DEC-1"):
    return {
        "decision_id": decision_id,
        "ticker": "QQQ",
        "strategy": "NAKED_PUT",
        "final_state": "ENTRY_READY",
        "candidate_source": "IBKR_OPTION_CHAIN",
        "confirmation_source": "TRADINGVIEW_ALERT",
        "signal_source": "TRADINGVIEW_ALERT",
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
    }


def complete_outcome(index):
    return {
        "outcome_id": f"OUT-{index}",
        "decision_id": "DEC-1",
        "ticker": "QQQ",
        "strategy": "NAKED_PUT",
        "outcome": "WIN" if index % 2 else "LOSS",
        "pnl_r": 0.4 if index % 2 else -0.2,
        "mfe_r": 0.6,
        "mae_r": -0.25,
        "market_regime": "BULLISH_LOW_VOL",
        "candidate_source": "IBKR_OPTION_CHAIN",
        "confirmation_source": "TRADINGVIEW_ALERT",
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
    }


def write_base_runtime(runtime: Path, outcomes=None, tv=True, ibkr_gap="COVERAGE_REVIEWABLE"):
    runtime.joinpath("v32_decision_journal.json").write_text(json.dumps([decision()]))
    runtime.joinpath("v32_outcomes_journal.json").write_text(json.dumps(outcomes or []))
    if tv:
        runtime.joinpath("v32_signal_events.json").write_text(
            json.dumps(
                [
                    {
                        "event_id": "TV-1",
                        "received_at": "2026-07-04T00:00:00+00:00",
                        "ticker": "QQQ",
                        "candidate_source": "TRADINGVIEW_ALERT",
                        "confirmation_source": "TRADINGVIEW_ALERT",
                    }
                ]
            )
        )
    runtime.joinpath("v32_ibkr_chain_coverage.json").write_text(
        json.dumps(
            {
                "primary_gap": ibkr_gap,
                "option_row_count": 1,
                "chain_event_count": 1,
                "missing_execution_field_counts": {},
            }
        )
    )


class OperationalEvidenceGateTests(unittest.TestCase):
    def test_empty_runtime_blocks_foundation(self):
        with TemporaryDirectory() as tmp:
            payload = operational_evidence_gate.build_operational_evidence_gate(
                Path(tmp),
                generated_at="2026-07-04T00:00:00+00:00",
                include_recovery_preview=False,
            )

            self.assertEqual(payload["state"], "FOUNDATION_BLOCKED")
            self.assertFalse(payload["capabilities"]["can_collect_signals"]["allowed"])
            self.assertFalse(payload["execution_authorized"])

    def test_source_without_tv_or_reviewable_ibkr_is_evidence_collection_only(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            write_base_runtime(runtime, tv=False, ibkr_gap="INCOMPLETE_OPTION_MARKET_DATA")

            payload = operational_evidence_gate.build_operational_evidence_gate(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                include_recovery_preview=False,
            )

            self.assertEqual(payload["state"], "EVIDENCE_COLLECTION_ONLY")
            self.assertTrue(payload["capabilities"]["can_collect_signals"]["allowed"])
            self.assertFalse(payload["capabilities"]["can_create_entry_ready"]["allowed"])
            self.assertIn("NO_TRADINGVIEW_LEDGER_EVENTS", payload["blocked_reasons"])
            self.assertIn("IBKR_CHAIN_COVERAGE_NOT_REVIEWABLE", payload["blocked_reasons"])

    def test_reviewable_tv_and_ibkr_with_outcome_sample_allows_outcome_collection_only(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            write_base_runtime(runtime, outcomes=[complete_outcome(1)], tv=True)

            payload = operational_evidence_gate.build_operational_evidence_gate(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                include_recovery_preview=False,
            )

            self.assertEqual(payload["state"], "OUTCOME_COLLECTION_READY")
            self.assertTrue(payload["capabilities"]["can_create_entry_ready"]["allowed"])
            self.assertTrue(payload["capabilities"]["can_evaluate_outcomes"]["allowed"])
            self.assertFalse(payload["capabilities"]["can_review_parameters"]["allowed"])
            self.assertFalse(payload["capabilities"]["can_execute_orders"]["allowed"])

    def test_thirty_complete_outcomes_allow_human_parameter_review_only(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            write_base_runtime(runtime, outcomes=[complete_outcome(index) for index in range(30)], tv=True)

            payload = operational_evidence_gate.build_operational_evidence_gate(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                include_recovery_preview=False,
            )

            self.assertEqual(payload["state"], "PARAMETER_REVIEW_READY")
            self.assertTrue(payload["capabilities"]["can_review_parameters"]["allowed"])
            self.assertFalse(payload["capabilities"]["can_change_production_rules"]["allowed"])
            self.assertFalse(payload["capabilities"]["can_execute_orders"]["allowed"])


if __name__ == "__main__":
    unittest.main()
