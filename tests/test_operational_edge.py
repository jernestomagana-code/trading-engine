import json
import tempfile
import unittest
from pathlib import Path

import operational_edge


class OperationalEdgeTests(unittest.TestCase):
    def write_json(self, runtime: Path, name: str, payload):
        runtime.joinpath(name).write_text(json.dumps(payload))

    def test_operational_edge_builds_all_seven_capabilities_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self.write_json(runtime, "tradingview_alert_bundle_health.json", {
                "coverage_valid": True,
                "real_e2e_confirmed": False,
                "status": "WAITING_FOR_REAL_TRADINGVIEW_EVENTS",
                "total_production_active_alert_count": 5,
                "total_required_logical_event_count": 16,
                "total_received_required_event_count": 0,
                "blockers": ["intraday_index_futures:NO_REAL_TRADINGVIEW_EVENT"],
                "execution_authorized": False,
                "not_order_instruction": True,
            })
            self.write_json(runtime, "v32_decision_journal.json", [
                {
                    "decision_id": "d1",
                    "recorded_at": "2026-07-10T14:30:00+00:00",
                    "ticker": "AAPL",
                    "strategy": "NAKED_PUT",
                    "final_state": "ENTRY_READY",
                    "ready_for_manual_review": True,
                    "conviction_score": 86,
                    "candidate_source": "LOCAL_SCANNER",
                    "confirmation_source": "TRADINGVIEW_ALERT",
                    "selected_contract": {
                        "expiration": "20260821",
                        "strike": 185,
                        "dte": 42,
                        "delta": -0.18,
                        "spread_pct": 2.0,
                    },
                    "execution_authorized": False,
                    "not_order_instruction": True,
                },
                {
                    "decision_id": "d2",
                    "recorded_at": "2026-07-10T14:31:00+00:00",
                    "ticker": "TSLA",
                    "strategy": "NAKED_PUT",
                    "final_state": "WAIT_OPTIONS_DATA",
                    "conviction_score": 95,
                    "main_blocker": "WAIT_OPTIONS_DATA",
                    "blockers": ["WAIT_OPTIONS_DATA"],
                    "execution_authorized": False,
                    "not_order_instruction": True,
                },
            ])
            self.write_json(runtime, "v32_outcomes_journal.json", [
                {
                    "outcome_id": "o1",
                    "decision_id": "d1",
                    "ticker": "AAPL",
                    "strategy": "NAKED_PUT",
                    "outcome": "WIN",
                    "pnl_r": 0.6,
                    "mfe_r": 1.1,
                    "mae_r": -0.3,
                    "market_regime": "BULL",
                    "candidate_source": "LOCAL_SCANNER",
                    "confirmation_source": "TRADINGVIEW_ALERT",
                    "selected_contract": {"delta": -0.18, "dte": 42, "spread_pct": 2.0, "iv": 0.3},
                    "execution_authorized": False,
                    "not_order_instruction": True,
                }
            ])
            self.write_json(runtime, "v32_ibkr_chain_coverage.json", {
                "primary_gap": "COVERAGE_REVIEWABLE",
                "option_rows": [
                    {
                        "ticker": "AAPL",
                        "strategy": "NAKED_PUT",
                        "expiration": "20260821",
                        "strike": 185,
                        "dte": 42,
                        "delta": -0.18,
                        "bid": 2.0,
                        "ask": 2.04,
                        "mid": 2.02,
                        "spread_pct": 1.98,
                        "iv": 0.3,
                        "volume": 500,
                        "open_interest": 2000,
                        "data_quality": "FULL_WITH_GREEKS",
                        "decision": "ENTRY_READY",
                    }
                ],
                "option_symbol_plan": {
                    "enabled": True,
                    "candidate_count": 8,
                    "selected_count": 4,
                    "selected_symbols": ["AAPL"],
                    "max_symbols_per_run": 6,
                    "max_total_option_contracts_per_run": 60,
                    "canslim_candidate_count": 1,
                },
                "execution_authorized": False,
                "not_order_instruction": True,
            })
            self.write_json(runtime, "canslim_candidates_latest.json", {
                "free_data_only": True,
                "candidates": [
                    {"ticker": "AAPL", "canslim_score": 88, "canslim_passes": True, "canslim_rating": "LEADER"}
                ],
                "execution_authorized": False,
                "not_order_instruction": True,
            })
            self.write_json(runtime, "alert_opportunity_deep_audit_latest.json", {
                "summary": {"decision_count": 2, "entry_ready_count": 1, "closed_outcome_count": 1},
                "execution_authorized": False,
                "not_order_instruction": True,
            })

            payload = operational_edge.build_operational_edge_report(runtime, generated_at="2026-07-11T00:00:00+00:00")

        self.assertEqual(payload["engine"], "V32_OPERATIONAL_EDGE")
        self.assertEqual(len(payload["capabilities"]), 7)
        self.assertIn("market_confirmation", payload["capabilities"])
        self.assertIn("score_calibration", payload["capabilities"])
        self.assertIn("institutional_ranking", payload["capabilities"])
        self.assertIn("option_optimizer", payload["capabilities"])
        self.assertIn("canslim_confidence", payload["capabilities"])
        self.assertIn("control_panel", payload["capabilities"])
        self.assertIn("post_mortem", payload["capabilities"])
        self.assertFalse(payload["execution_authorized"])
        self.assertTrue(payload["not_order_instruction"])
        self.assertEqual(payload["summary"]["best_opportunities"][0]["ticker"], "AAPL")
        self.assertEqual(payload["summary"]["best_contracts"][0]["ticker"], "AAPL")
        self.assertEqual(payload["capabilities"]["market_confirmation"]["status"], "WAIT_LIVE_CONFIRMATION")

    def test_waiting_candidates_do_not_outrank_entry_ready_on_raw_score_alone(self):
        entry = {"ticker": "AAPL", "strategy": "NAKED_PUT", "final_state": "ENTRY_READY", "conviction_score": 70}
        waiting = {
            "ticker": "TSLA",
            "strategy": "NAKED_PUT",
            "final_state": "WAIT_OPTIONS_DATA",
            "conviction_score": 500,
            "blockers": ["WAIT_OPTIONS_DATA"],
        }

        ranking = operational_edge.build_institutional_ranking([waiting, entry], top_limit=2)

        self.assertEqual(ranking["top_opportunities"][0]["ticker"], "AAPL")
        self.assertLess(
            ranking["top_opportunities"][1]["institutional_score"],
            ranking["top_opportunities"][0]["institutional_score"],
        )


if __name__ == "__main__":
    unittest.main()
