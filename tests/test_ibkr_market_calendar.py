import unittest
import ast
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ibkr_bridge.py"


def load_calendar_helpers():
    tree = ast.parse(BRIDGE.read_text(), filename=str(BRIDGE))
    wanted = {
        "_observed_fixed_market_holiday",
        "_nth_weekday_date",
        "_last_weekday_date",
        "_easter_date",
        "_us_market_holiday_dates",
        "ibkr_market_is_us_holiday",
        "ibkr_market_is_open_for_options",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "datetime": datetime,
        "timedelta": __import__("datetime").timedelta,
        "ZoneInfo": ZoneInfo,
    }
    exec(compile(module, str(BRIDGE), "exec"), namespace)
    return namespace


class IbkrMarketCalendarTests(unittest.TestCase):
    def test_juneteenth_2026_is_not_regular_options_session(self):
        helpers = load_calendar_helpers()
        juneteenth = datetime(2026, 6, 19, 10, 30, tzinfo=ZoneInfo("America/New_York"))

        self.assertTrue(helpers["ibkr_market_is_us_holiday"](juneteenth))
        self.assertFalse(helpers["ibkr_market_is_open_for_options"](juneteenth))

    def test_regular_weekday_during_session_is_open(self):
        helpers = load_calendar_helpers()
        regular_day = datetime(2026, 6, 22, 10, 30, tzinfo=ZoneInfo("America/New_York"))

        self.assertFalse(helpers["ibkr_market_is_us_holiday"](regular_day))
        self.assertTrue(helpers["ibkr_market_is_open_for_options"](regular_day))


if __name__ == "__main__":
    unittest.main()
