import unittest

import alpha_vantage_earnings as calendar


class AlphaVantageEarningsTests(unittest.TestCase):
    def test_csv_is_filtered_and_keeps_estimated_confidence(self):
        raw = "symbol,name,reportDate,fiscalDateEnding,estimate,currency\nAAPL,Apple,2026-10-29,2026-09-30,1.5,USD\nIBM,IBM,2026-10-20,2026-09-30,2.0,USD\n"
        rows = calendar.parse_calendar_csv(raw, ["AAPL"], "2026-09-02T00:00:00Z")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "AAPL")
        self.assertFalse(rows[0]["confirmed"])
        self.assertEqual(rows[0]["confidence"], "ESTIMATED")


if __name__ == "__main__":
    unittest.main()
