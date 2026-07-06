import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import foundation_health


class FoundationHealthTests(unittest.TestCase):
    def test_foundation_health_goes_ok_when_all_evidence_is_present(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            runtime.joinpath("v32_decision_journal.json").write_text(
                json.dumps(
                    [
                        {
                            "decision_id": "DEC-1",
                            "ticker": "QQQ",
                            "strategy": "NAKED_PUT",
                            "final_state": "ENTRY_READY",
                            "candidate_source": "IBKR_OPTION_CHAIN",
                            "confirmation_source": "TRADINGVIEW_ALERT",
                            "signal_source": "TRADINGVIEW_ALERT",
                        }
                    ]
                )
            )
            runtime.joinpath("v32_outcomes_journal.json").write_text(
                json.dumps(
                    [
                        {
                            "outcome_id": f"OUT-{index}",
                            "ticker": "QQQ",
                            "strategy": "NAKED_PUT",
                            "outcome": "WIN" if index % 2 else "LOSS",
                            "pnl_r": 0.2 if index % 2 else -0.1,
                            "mfe_r": 0.5 if index % 2 else 0.1,
                            "mae_r": -0.15 if index % 2 else -0.4,
                            "market_regime": "BULLISH_LOW_VOL",
                            "candidate_source": "IBKR_OPTION_CHAIN",
                            "confirmation_source": "TRADINGVIEW_ALERT",
                            "selected_contract": {
                                "delta": -0.2,
                                "dte": 42,
                                "spread_pct": 7.0,
                                "iv": 0.32,
                            },
                        }
                        for index in range(30)
                    ]
                )
            )
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
                        "primary_gap": "COVERAGE_REVIEWABLE",
                        "option_row_count": 8,
                        "chain_event_count": 2,
                        "missing_execution_field_counts": {},
                    }
                )
            )

            payload = foundation_health.build_foundation_health(
                runtime,
                generated_at="2026-07-04T00:00:00+00:00",
            )

            self.assertEqual(payload["foundation_health_version"], "foundation_health_v1")
            self.assertEqual(payload["status"], "OK")
            checks = {item["name"]: item for item in payload["checks"]}
            self.assertEqual(checks["source_attribution_coverage"]["status"], "OK")
            self.assertEqual(checks["tradingview_signal_ledger"]["metrics"]["event_count"], 1)
            self.assertEqual(checks["outcome_sample"]["metrics"]["complete_closed_outcomes"], 30)
            self.assertEqual(payload["parameter_review_summary"]["candidate_count"], 1)
            self.assertEqual(payload["parameter_review_summary"]["guard_allowed_count"], 1)
            self.assertFalse(payload["execution_authorized"])

    def test_foundation_health_waits_when_runtime_is_empty(self):
        with TemporaryDirectory() as tmp:
            payload = foundation_health.build_foundation_health(
                Path(tmp),
                generated_at="2026-07-04T00:00:00+00:00",
            )

            self.assertEqual(payload["status"], "WAITING_FOR_DATA")
            self.assertTrue(payload["priorities"])
            self.assertTrue(payload["manual_review_required"])
            self.assertTrue(payload["not_order_instruction"])


if __name__ == "__main__":
    unittest.main()
