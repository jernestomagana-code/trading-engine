import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ibkr_diagnostics
import tradingview_signal_ledger


class SignalLedgerTests(unittest.TestCase):
    def test_tradingview_ledger_records_and_dedupes_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            payload = {
                "ticker": "MNQ",
                "timeframe": "5",
                "strategy_context": "INTRADAY_INDEX_FUTURES",
                "price": 23000.25,
                "vwap": 22980.0,
                "opening_range_high": 23010.0,
                "breakout_direction": "LONG",
            }

            first = tradingview_signal_ledger.append_signal_event(payload, raw_text=json.dumps(payload), endpoint="/technical_snapshot", path=path)
            second = tradingview_signal_ledger.append_signal_event(payload, raw_text=json.dumps(payload), endpoint="/technical_snapshot", path=path)
            events = tradingview_signal_ledger.load_signal_events(path)

        self.assertEqual(first["status"], "RECORDED")
        self.assertEqual(second["status"], "DUPLICATE")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["candidate_source"], "TRADINGVIEW_ALERT")
        self.assertFalse(events[0]["execution_authorized"])

    def test_ibkr_diagnostic_summarizes_missing_option_fields(self):
        diagnostic = ibkr_diagnostics.build_cycle_diagnostic(
            symbols=["QQQ"],
            chain_events=[{"ticker": "QQQ", "status": "CHAIN_SELECTED"}],
            option_rows=[
                {
                    "ticker": "QQQ",
                    "strategy": "NAKED_PUT",
                    "bid": 1.0,
                    "ask": None,
                    "mid": 1.05,
                    "strike": 700,
                    "expiration": "20260821",
                    "dte": 48,
                    "delta": -0.18,
                    "data_quality": "PRICE_WITH_GREEKS_NO_BIDASK",
                }
            ],
        )

        self.assertEqual(diagnostic["diagnostic_version"], "ibkr_chain_coverage_v1")
        self.assertEqual(diagnostic["primary_gap"], "INCOMPLETE_OPTION_MARKET_DATA")
        self.assertEqual(diagnostic["missing_execution_field_counts"]["ask"], 1)
        self.assertFalse(diagnostic["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
