import json
import unittest
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import alert_opportunity_audit


class AlertOpportunityAuditTests(unittest.TestCase):
    def test_audit_surfaces_sources_blockers_and_sample_gap(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "v32_decision_journal.json").write_text(
                json.dumps(
                    [
                        {
                            "decision_id": "DEC-1",
                            "ticker": "QQQ",
                            "strategy": "NAKED_PUT",
                            "final_state": "ENTRY_READY",
                            "source": "LOCAL_TECHNICAL_ENGINE",
                        },
                        {
                            "decision_id": "DEC-2",
                            "ticker": "AAPL",
                            "strategy": "NAKED_PUT",
                            "final_state": "WAIT_OPTIONS_DATA",
                            "main_blocker": "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY",
                            "required_missing_fields": ["bid", "ask"],
                        },
                        {
                            "decision_id": "DEC-3",
                            "ticker": "MSFT",
                            "strategy": "COVERED_CALL",
                            "final_state": "WAIT_TECHNICAL",
                            "blockers": ["TECHNICAL_NOT_CONFIRMED"],
                            "confirmation_source": "TRADINGVIEW_ALERT",
                        },
                    ]
                )
            )
            (runtime / "v32_outcomes_journal.json").write_text(
                json.dumps(
                    [
                        {
                            "outcome_id": "OUT-1",
                            "decision_id": "DEC-1",
                            "ticker": "QQQ",
                            "strategy": "NAKED_PUT",
                            "outcome": "WIN",
                            "pnl_r": 0.7,
                        }
                    ]
                )
            )

            payload = alert_opportunity_audit.build_alert_opportunity_audit(
                runtime,
                generated_at="2026-06-28T00:00:00+00:00",
            )

            self.assertEqual(payload["audit_version"], "alert_opportunity_deep_audit_v1")
            self.assertEqual(payload["summary"]["decision_count"], 3)
            self.assertEqual(payload["summary"]["entry_ready_count"], 1)
            self.assertEqual(payload["summary"]["state_counts"]["WAIT_OPTIONS_DATA"], 1)
            self.assertEqual(payload["summary"]["source_counts"]["TRADINGVIEW_ALERT"], 1)
            self.assertEqual(payload["summary"]["source_counts"]["UNKNOWN"], 1)
            self.assertEqual(payload["data_quality"]["primary_gap"], "INSUFFICIENT_OUTCOME_SAMPLE")
            self.assertFalse(payload["execution_authorized"])

            missed = payload["missed_opportunity_review"]
            self.assertEqual(len(missed), 2)
            wait_options = next(row for row in missed if row["final_state"] == "WAIT_OPTIONS_DATA")
            self.assertIn("option-chain", wait_options["audit_question"])

            coverage = {row["strategy"]: row for row in payload["strategy_coverage"]}
            self.assertEqual(coverage["NAKED_PUT"]["entry_ready_count"], 1)
            self.assertEqual(coverage["NAKED_PUT"]["closed_outcomes"], 1)
            self.assertTrue(coverage["NAKED_PUT"]["sample_size_warning"])

    def test_audit_dedupes_repeated_same_day_contract_decisions(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            repeated = {
                "ticker": "AAPL",
                "strategy": "NAKED_PUT",
                "final_state": "ENTRY_READY",
                "selected_contract": {
                    "strike": 180,
                    "expiration": "2026-07-17",
                    "dte": 39,
                    "bid": 1.2,
                    "ask": 1.35,
                    "mid": 1.275,
                    "spread_pct": 11.76,
                    "delta": -0.28,
                },
            }
            (runtime / "v32_decision_journal.json").write_text(
                json.dumps(
                    [
                        {**repeated, "decision_id": "DEC-OLD", "recorded_at": "2026-06-19T19:16:00+00:00"},
                        {**repeated, "decision_id": "DEC-NEW", "recorded_at": "2026-06-19T19:20:00+00:00"},
                    ]
                )
            )

            payload = alert_opportunity_audit.build_alert_opportunity_audit(
                runtime,
                generated_at="2026-06-28T00:00:00+00:00",
            )

            self.assertEqual(payload["summary"]["decision_count"], 1)
            self.assertEqual(payload["summary"]["entry_ready_count"], 1)


if __name__ == "__main__":
    unittest.main()
