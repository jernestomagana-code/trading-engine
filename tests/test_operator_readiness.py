import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import operator_readiness
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


def complete_outcome(index=1):
    return {
        "outcome_id": f"OUT-{index}",
        "decision_id": "DEC-1",
        "ticker": "QQQ",
        "strategy": "NAKED_PUT",
        "outcome": "WIN",
        "pnl_r": 0.4,
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


def write_decision_runtime(runtime: Path, *, ibkr_gap="COVERAGE_REVIEWABLE", outcomes=None):
    runtime.joinpath("v32_decision_journal.json").write_text(json.dumps([decision()]))
    runtime.joinpath("v32_outcomes_journal.json").write_text(json.dumps(outcomes or []))
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


def append_all_tv_events(runtime: Path):
    ledger = runtime / "v32_signal_events.json"
    coverage_specs = [
        tradingview_alert_coverage.DEFAULT_COVERAGE_PATH,
        ROOT / "config" / "tradingview_options_underlying_alert_coverage_v1.json",
    ]
    for coverage_path in coverage_specs:
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


class OperatorReadinessTests(unittest.TestCase):
    def test_empty_runtime_is_foundation_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = operator_readiness.build_go_no_go(
                Path(tmp),
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
            )

        self.assertEqual(report["status"], "FOUNDATION_BLOCKED")
        self.assertFalse(report["ok"])
        self.assertFalse(report["execution_authorized"])

    def test_decision_runtime_without_real_tv_waits_for_tradingview(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            write_decision_runtime(runtime, outcomes=[complete_outcome()])
            report = operator_readiness.build_go_no_go(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
            )
            checklist = operator_readiness.build_market_open_checklist(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
            )

        self.assertEqual(report["status"], "WAITING_TV")
        self.assertEqual(report["tradingview_bundle"]["total_expected_alert_count"], 16)
        self.assertEqual(checklist["steps"][1]["status"], "WAIT_REAL_MARKET")

    def test_complete_runtime_is_ready_for_manual_review_and_monitor_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            write_decision_runtime(runtime, outcomes=[complete_outcome()])
            append_all_tv_events(runtime)
            report = operator_readiness.build_go_no_go(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
            )
            monitor = operator_readiness.build_post_open_monitor(
                runtime,
                generated_at="2026-07-05T14:00:00+00:00",
                market_closed_ok=True,
            )

        self.assertEqual(report["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertTrue(report["ok"])
        self.assertTrue(report["tradingview_bundle"]["real_e2e_confirmed"])
        self.assertEqual(monitor["alert_level"], "OK")


if __name__ == "__main__":
    unittest.main()
