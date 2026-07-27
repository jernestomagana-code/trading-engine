import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import operational_evidence_gate
import tradingview_alert_coverage
import tradingview_operational_health
import tradingview_signal_ledger


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
        ledger = runtime / "v32_signal_events.json"
        coverage = tradingview_alert_coverage.load_coverage()
        for alert in tradingview_alert_coverage.alerts(coverage):
            payload = tradingview_operational_health.concrete_payload_for_event_code(
                alert["event_code"]
            )
            tradingview_signal_ledger.append_signal_event(
                payload,
                raw_text=json.dumps(payload),
                endpoint="/technical_snapshot",
                path=ledger,
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


def append_options_underlying_events(runtime: Path):
    ledger = runtime / "v32_signal_events.json"
    coverage_path = ROOT / "config" / "tradingview_options_underlying_alert_coverage_v1.json"
    coverage = tradingview_alert_coverage.load_coverage(coverage_path)
    for alert in tradingview_alert_coverage.alerts(coverage):
        payload = tradingview_operational_health.concrete_payload_for_event_code(
            alert["event_code"],
            coverage_path=coverage_path,
        )
        tradingview_signal_ledger.append_signal_event(
            payload,
            raw_text=json.dumps(payload),
            endpoint="/technical_snapshot",
            path=ledger,
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
            self.assertFalse(payload["capabilities"]["can_create_options_entry_ready"]["allowed"])
            self.assertTrue(payload["capabilities"]["can_evaluate_outcomes"]["allowed"])
            self.assertFalse(payload["capabilities"]["can_review_parameters"]["allowed"])
            self.assertFalse(payload["capabilities"]["can_execute_orders"]["allowed"])

    def test_options_entry_ready_requires_underlying_tv_alerts(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            write_base_runtime(runtime, outcomes=[complete_outcome(1)], tv=True)
            blocked = operational_evidence_gate.build_operational_evidence_gate(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                include_recovery_preview=False,
            )

            append_options_underlying_events(runtime)
            allowed = operational_evidence_gate.build_operational_evidence_gate(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
                include_recovery_preview=False,
            )

            self.assertFalse(blocked["capabilities"]["can_create_options_entry_ready"]["allowed"])
            self.assertIn(
                "MISSING_OPTIONS_UNDERLYING_CONFIRMATION_COVERAGE",
                blocked["capabilities"]["can_create_options_entry_ready"]["blockers"],
            )
            self.assertFalse(blocked["evidence_summary"]["tradingview_bundle_real_e2e_confirmed"])
            self.assertTrue(allowed["capabilities"]["can_create_options_entry_ready"]["allowed"])
            self.assertTrue(allowed["evidence_summary"]["tradingview_bundle_real_e2e_confirmed"])
            self.assertEqual(allowed["evidence_summary"]["tradingview_bundle_total_production_active_alert_count"], 7)
            self.assertEqual(allowed["evidence_summary"]["tradingview_bundle_total_required_logical_event_count"], 20)
            self.assertEqual(allowed["evidence_summary"]["tradingview_bundle_total_expected_alert_count"], 24)

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
