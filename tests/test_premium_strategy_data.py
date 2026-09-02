import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import premium_strategy_data as data
from scripts import daily_open_checklist


class PremiumStrategyDataTests(unittest.TestCase):
    def test_volatility_metrics_are_derived_from_history(self):
        stats = data.volatility_statistics([0.10, 0.20, 0.30, 0.40], 0.30)
        self.assertEqual(stats["iv_rank"], 66.67)
        self.assertEqual(stats["iv_percentile"], 75.0)
        self.assertIsNotNone(data.annualized_realized_volatility([100, 101, 99, 103]))
        self.assertEqual(data.event_move_ratio(6, [3, 4, 5]), 1.5)

    def test_observation_store_validates_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.jsonl"
            record = {
                "ticker": "SPY", "observed_at": "2026-09-02T15:00:00Z",
                "expiration": "20270130", "dte": 150, "right": "P", "strike": 650,
                "bid": 5, "ask": 5.2, "delta": -0.14, "iv": 0.22,
                "underlying_price": 760, "source": "TEST",
            }
            first = data.append_observations(path, [record], "option_observation")
            second = data.append_observations(path, [record], "option_observation")
            self.assertEqual(first["accepted"], 1)
            self.assertEqual(second["accepted"], 0)
            saved = json.loads(path.read_text().strip())
            self.assertFalse(saved["execution_authorized"])

    def test_readiness_reports_specific_missing_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime / "canslim_candidates_latest.json").write_text(json.dumps({
                "candidates": [{"ticker": "AAPL", "canslim_passes": True, "canslim_component_coverage_pct": 100}]
            }))
            report = data.build_readiness(runtime, generated_at="2026-09-02T00:00:00Z")
            earnings = report["strategies"]["CANSLIM_EARNINGS_VOLATILITY_HARVEST"]
            long_dated = report["strategies"]["SPY_RSP_LONG_DATED_PUTWRITE"]
            self.assertNotIn("CANSLIM_FULL_COVERAGE", earnings["missing"])
            self.assertIn("CONFIRMED_EARNINGS_CALENDAR", earnings["missing"])
            self.assertIn("SPY_RSP_120_150_180_DTE_OBSERVATIONS", long_dated["missing"])
            self.assertIn("LIQUID_LONG_DATED_GRID_INCOMPLETE", long_dated["missing"])
            self.assertFalse(report["execution_authorized"])

    def test_confirmed_earnings_record_requires_confirmation(self):
        record = {"ticker": "AAPL", "earnings_date": "2026-10-20", "event_timing": "AMC", "confirmed": False, "source": "TEST", "observed_at": "2026-09-02T00:00:00Z"}
        self.assertIn("confirmed_true", data.validate_record(record, "earnings_event"))

    def test_capture_preserves_only_complete_live_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            payload = {"by_ticker": {"SPY": {"option_rows": [
                {"strategy": "NAKED_PUT", "expiration": "20270130", "dte": 150,
                 "strike": 650, "bid": 5, "ask": 5.2, "delta": -0.14, "iv": 0.22,
                 "underlying_price": 760, "market_data_source": "IBKR_TEST"},
                {"strategy": "NAKED_PUT", "expiration": "20270130", "dte": 150,
                 "strike": 640, "bid": None, "ask": None, "delta": None, "iv": None,
                 "underlying_price": 760},
            ]}}}
            (runtime / "active_position_option_chains_latest.json").write_text(json.dumps(payload))
            result = data.capture_runtime_observations(runtime, "2026-09-02T15:00:00Z")
            self.assertEqual(result["available_live_rows"], 2)
            self.assertEqual(result["usable_option_rows"], 1)
            self.assertEqual(result["options"]["accepted"], 1)
            self.assertEqual(result["underlyings"]["accepted"], 1)

    def test_daily_open_research_capture_is_explicitly_non_blocking(self):
        with mock.patch.object(daily_open_checklist, "RUNTIME", Path("/missing/runtime")), mock.patch.object(
            daily_open_checklist.premium_strategy_data, "capture_runtime_observations", side_effect=RuntimeError("test")
        ):
            result = daily_open_checklist.capture_premium_research_data()
        self.assertFalse(result["ok"])
        self.assertTrue(result["non_blocking"])
        self.assertFalse(result["execution_authorized"])

    def test_daily_open_ibkr_research_collector_is_non_blocking(self):
        args = type("Args", (), {"skip_premium_research": False, "ibkr_host": "127.0.0.1", "ibkr_port": 7496, "premium_research_timeout": 150})()
        with mock.patch.object(daily_open_checklist, "run_command", return_value={"ok": False, "error": "WSH_UNAVAILABLE"}):
            result = daily_open_checklist.collect_premium_research_ibkr(args)
        self.assertFalse(result["ok"])
        self.assertTrue(result["non_blocking"])
        self.assertFalse(result["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
