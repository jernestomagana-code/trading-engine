import unittest
from pathlib import Path

import premium_strategy_research as research
import strategy_registry


ROOT = Path(__file__).resolve().parents[1]


class PremiumStrategyResearchTests(unittest.TestCase):
    def setUp(self):
        self.config = research.load_config(ROOT / "config" / "premium_strategy_research_v1.json")

    def test_parameter_grids_cover_agreed_hypotheses(self):
        long_grid = research.parameter_grid("SPY_RSP_LONG_DATED_PUTWRITE", self.config)
        self.assertEqual({row["dte"] for row in long_grid}, {120, 150, 180})
        self.assertEqual({row["delta"] for row in long_grid}, {0.10, 0.12, 0.14, 0.15, 0.20})
        earnings_grid = research.parameter_grid("CANSLIM_EARNINGS_VOLATILITY_HARVEST", self.config)
        self.assertNotIn("SHORT_STRANGLE", {row["structure"] for row in earnings_grid})

    def test_earnings_candidate_never_becomes_entry_ready(self):
        result = research.earnings_candidate_gate({
            "ticker": "TEST", "structure": "CASH_SECURED_PUT", "earnings_confirmed": True,
            "canslim_pass": True, "canslim_coverage_pct": 92, "iv_percentile": 82,
            "iv_rank": 65, "event_move_ratio": 1.30, "iv_to_realized_ratio": 1.25,
            "bid_ask_spread_pct": 4, "open_interest": 1200,
            "stress_loss_pct_of_account": 1.5,
        }, self.config)
        self.assertEqual(result["state"], "RESEARCH_CANDIDATE")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["maximum_state"], "PAPER_ELIGIBLE")

    def test_unconfirmed_event_and_uncovered_structure_are_blocked(self):
        result = research.earnings_candidate_gate({
            "structure": "SHORT_STRANGLE", "canslim_pass": True, "canslim_coverage_pct": 100,
            "iv_percentile": 90, "iv_rank": 80, "event_move_ratio": 1.4,
            "iv_to_realized_ratio": 1.4, "bid_ask_spread_pct": 3,
            "open_interest": 2000, "stress_loss_pct_of_account": 1,
        }, self.config)
        self.assertEqual(result["state"], "RESEARCH_BLOCKED")
        self.assertIn("EARNINGS_DATE_UNCONFIRMED", result["blockers"])
        self.assertIn("UNDEFINED_OR_UNCOVERED_RISK_NOT_ALLOWED", result["blockers"])

    def test_long_dated_candidate_is_research_only(self):
        result = research.long_dated_candidate_gate({
            "ticker": "SPY", "dte": 150, "delta": 0.14, "iv_percentile": 70,
            "iv_to_realized_ratio": 1.3, "iv_minus_realized_points": 5,
            "bid_ask_spread_pct": 2, "open_interest": 5000,
            "cash_secured_or_stress_margin": True, "cycle_capacity_pct": 20,
            "aggregate_spy_rsp_exposure_pct": 30,
        }, self.config)
        self.assertEqual(result["state"], "RESEARCH_CANDIDATE")
        self.assertFalse(result["execution_authorized"])

    def test_small_winning_backtest_is_not_sufficient(self):
        trades = [{"date": f"2026-01-{day:02d}", "pnl": 100, "regime": "BULL"} for day in range(1, 9)]
        result = research.evaluate_backtest_sample(
            trades, "SPY_RSP_LONG_DATED_PUTWRITE", starting_capital=40_000, config=self.config
        )
        self.assertEqual(result["state"], "RESEARCH_BLOCKED")
        self.assertIn("INSUFFICIENT_CLOSED_TRADES", result["blockers"])
        self.assertIn("STRESS_HISTORY_INCOMPLETE", result["blockers"])

    def test_complete_robust_sample_can_reach_paper_eligible(self):
        stress_periods = ["2008", "2011", "2015_2016", "2018", "2020", "2022"]
        regimes = ["BULL", "BEAR", "HIGH_VOL"]
        trades = []
        for index in range(42):
            trades.append({
                "date": f"{2008 + index % 15}-06-15",
                "pnl": -50 if index % 7 == 0 else 120,
                "regime": regimes[index % len(regimes)],
                "stress_period": stress_periods[index % len(stress_periods)],
                "out_of_sample": index < 16,
            })
        result = research.evaluate_backtest_sample(
            trades, "SPY_RSP_LONG_DATED_PUTWRITE", starting_capital=40_000, config=self.config
        )
        self.assertEqual(result["state"], "PAPER_ELIGIBLE")
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["execution_authorized"])

    def test_registry_blocks_new_strategies_from_execution(self):
        registry = strategy_registry.load_registry(ROOT / "config" / "strategy_registry_v1.json")
        for strategy in ("EARNINGS_IV_CRUSH", "LONG_DATED_PUTWRITE"):
            overlay = strategy_registry.recommendation_overlay(
                {"strategy": strategy, "final_state": "ENTRY_READY"}, registry
            )
            self.assertTrue(overlay["research_only"])
            self.assertIn("RESEARCH_ONLY", overlay["strategy_blockers"])
            self.assertFalse(overlay["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
