import unittest

from test_v29_v30_contract_gating import main


class FuturesOutcomeFirstTouchTests(unittest.TestCase):
    def test_long_path_records_target_before_stop_and_time(self):
        event = {
            "received_at": "2026-08-13T14:30:00+00:00",
            "price": 100.0,
            "direction": "LONG",
            "stop_price": 99.0,
            "stop_points": 1.0,
            "tp1_price": 101.0,
            "tp2_price": 102.0,
        }
        points = [
            {"received_at": "2026-08-13T14:31:00+00:00", "price": 100.4},
            {"received_at": "2026-08-13T14:33:00+00:00", "price": 101.1},
            {"received_at": "2026-08-13T14:35:00+00:00", "price": 98.8},
        ]

        result = main.calculate_intraday_futures_window_outcome(event, points, 15)

        self.assertEqual(result["first_touch"], "TARGET_1")
        self.assertEqual(result["minutes_to_first_touch"], 3.0)
        self.assertEqual(result["hypothetical_result_r"], 1.0)
        self.assertEqual(result["classification"], "GOOD_SIGNAL")
        self.assertEqual(result["mfe_r"], 1.1)
        self.assertEqual(result["mae_r"], 1.2)

    def test_short_path_records_stop_before_target(self):
        event = {
            "received_at": "2026-08-13T14:30:00+00:00",
            "price": 100.0,
            "direction": "SHORT",
            "stop_price": 101.0,
            "stop_points": 1.0,
            "tp1_price": 99.0,
            "tp2_price": 98.0,
        }
        points = [
            {"received_at": "2026-08-13T14:32:00+00:00", "price": 101.2},
            {"received_at": "2026-08-13T14:36:00+00:00", "price": 98.0},
        ]

        result = main.calculate_intraday_futures_window_outcome(event, points, 15)

        self.assertEqual(result["first_touch"], "STOP")
        self.assertEqual(result["hypothetical_result_r"], -1.0)
        self.assertEqual(result["classification"], "FALSE_POSITIVE")


if __name__ == "__main__":
    unittest.main()
