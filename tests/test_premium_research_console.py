import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import ibkr_account_profile as console


class PremiumResearchConsoleTests(unittest.TestCase):
    def test_history_panel_explains_wsh_and_never_presents_entry(self):
        payload = {
            "summary": {
                "canslim_full_coverage": 10, "confirmed_earnings_events": 0,
                "prospective_option_observations": 69, "liquid_long_dated_grid_cells": 1,
                "expired_option_backfill_rows": 0,
                "earnings_calendar_blocker": "WSH_SUBSCRIPTION_OR_METADATA_UNAVAILABLE",
            },
            "strategies": {
                "CANSLIM_EARNINGS_VOLATILITY_HARVEST": {"data_state": "DATA_COLLECTION_REQUIRED", "missing": ["CONFIRMED_EARNINGS_CALENDAR"]},
                "SPY_RSP_LONG_DATED_PUTWRITE": {"data_state": "DATA_COLLECTION_REQUIRED", "next_action": "Acumular historia."},
            },
        }
        with mock.patch.object(console, "load_json_file", return_value=payload):
            html = console.render_premium_strategy_research_summary()
        self.assertIn("Enchilada Pro", html)
        self.assertIn("1/6", html)
        self.assertIn("RESEARCH ONLY", html)
        self.assertNotIn("ENTRY_READY", html)


if __name__ == "__main__":
    unittest.main()
