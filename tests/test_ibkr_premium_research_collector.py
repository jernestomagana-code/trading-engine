import json
import unittest
from datetime import date
from types import SimpleNamespace

import ibkr_premium_research_collector as collector


class IbkrPremiumResearchCollectorTests(unittest.TestCase):
    def test_expirations_are_selected_nearest_each_target(self):
        result = collector.select_target_expirations(
            ["20260430", "20260529", "20260630"], today=date(2026, 1, 1)
        )
        self.assertEqual(set(result), {120, 150, 180})
        self.assertEqual(len(set(result.values())), 3)

    def test_delta_selection_targets_all_research_deltas(self):
        rows = [
            {"expiration": "20270101", "strike": strike, "right": "P", "delta": -delta}
            for strike, delta in [(600, .08), (610, .10), (620, .12), (630, .14), (640, .15), (650, .20)]
        ]
        selected = collector.choose_delta_contracts(rows)
        self.assertEqual([row["target_delta"] for row in selected], list(collector.TARGET_DELTAS))

    def test_normalize_complete_option_ticker(self):
        contract = SimpleNamespace(symbol="SPY", lastTradeDateOrContractMonth="20270130", right="P", strike=650)
        greeks = SimpleNamespace(impliedVol=.22, delta=-.14, undPrice=760)
        ticker = SimpleNamespace(contract=contract, bid=5, ask=5.2, modelGreeks=greeks, bidGreeks=None, askGreeks=None, lastGreeks=None, putOpenInterest=1000, putVolume=50)
        result = collector.normalize_option_ticker(ticker, 150, "2026-09-02T00:00:00Z")
        self.assertEqual(result["target_dte"], 150)
        self.assertEqual(result["source"], "IBKR_TWS_READONLY")
        self.assertAlmostEqual(result["spread_pct"], 3.92, places=2)

    def test_wsh_parser_extracts_earnings_without_account_data(self):
        raw = json.dumps({"events": [{"eventType": "Earnings Date", "eventDate": "20261020", "eventTime": "After Market Close"}]})
        result = collector.normalize_wsh_events(raw, "AAPL", "2026-09-02T00:00:00Z")
        self.assertEqual(result[0]["earnings_date"], "2026-10-20")
        self.assertEqual(result[0]["event_timing"], "AMC")
        self.assertTrue(result[0]["confirmed"])

    def test_exact_contract_resolution_uses_listed_strikes(self):
        chain = SimpleNamespace(multiplier="100", tradingClass="SPY", strikes=[600, 650])
        details = [SimpleNamespace(contract=SimpleNamespace(strike=value)) for value in (600, 620, 640, 660, 680, 700)]
        ib = SimpleNamespace(reqContractDetails=lambda template: details)
        contracts, mode = collector.contracts_for_expiration(ib, "SPY", "20270101", chain, 760, prefer_exact=True)
        self.assertEqual(mode, "EXACT_CONTRACT_DETAILS")
        self.assertTrue(contracts)


if __name__ == "__main__":
    unittest.main()
