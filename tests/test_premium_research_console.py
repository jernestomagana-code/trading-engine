import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import ibkr_account_profile as console


class PremiumResearchConsoleTests(unittest.TestCase):
    def test_research_strategies_are_visible_but_never_operable(self):
        payload = {
            "generated_at": "2026-09-04T12:00:00+00:00",
            "summary": {
                "scheduled_earnings_events": 2,
                "prospective_option_observations": 20,
                "liquid_long_dated_grid_cells": 3,
                "expired_option_backfill_rows": 4,
            },
            "strategies": {
                "CANSLIM_EARNINGS_VOLATILITY_HARVEST": {"data_state": "PAPER_ELIGIBLE", "next_action": "Continuar muestra."},
                "SPY_RSP_LONG_DATED_PUTWRITE": {"data_state": "PAPER_ELIGIBLE", "next_action": "Continuar muestra."},
            },
        }
        items = console.build_unified_opportunity_items(
            {"ok": True, "data": {"active_alerts": []}},
            {"strategy_recommendation": {"status": "WAIT_DATA"}},
            candidates_payload={}, risk_payload={"alerts": []},
            account_capacity={"available_capacity": 50000}, premium_payload=payload,
        )
        research = [item for item in items if item["type"] in {"earnings", "long_put"}]
        self.assertEqual({item["type"] for item in research}, {"earnings", "long_put"})
        self.assertTrue(all(item["state"] == "research" for item in research))
        self.assertTrue(all(item["operability"] == "RESEARCH_ONLY" for item in research))
        self.assertTrue(all(item["simulator_available"] is False for item in research))

    def test_history_panel_explains_free_calendar_and_never_presents_entry(self):
        payload = {
            "summary": {
                "canslim_full_coverage": 10, "confirmed_earnings_events": 0,
                "prospective_option_observations": 69, "liquid_long_dated_grid_cells": 1,
                "expired_option_backfill_rows": 0,
                "scheduled_earnings_events": 0, "earnings_calendar_configured": False,
            },
            "strategies": {
                "CANSLIM_EARNINGS_VOLATILITY_HARVEST": {"data_state": "DATA_COLLECTION_REQUIRED", "missing": ["EARNINGS_CALENDAR"]},
                "SPY_RSP_LONG_DATED_PUTWRITE": {"data_state": "DATA_COLLECTION_REQUIRED", "next_action": "Acumular historia."},
            },
        }
        with mock.patch.object(console, "load_json_file", return_value=payload):
            html = console.render_premium_strategy_research_summary()
        self.assertIn("clave gratuita de Alpha Vantage", html)
        self.assertIn("WSH es opcional", html)
        self.assertIn("1/6", html)
        self.assertIn("RESEARCH ONLY", html)
        self.assertNotIn("ENTRY_READY", html)


if __name__ == "__main__":
    unittest.main()
