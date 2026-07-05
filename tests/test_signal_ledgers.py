import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ibkr_diagnostics
import tradingview_alert_coverage
import tradingview_payload_contract
import tradingview_signal_ledger


class SignalLedgerTests(unittest.TestCase):
    def test_tradingview_alert_coverage_generates_valid_minimum_messages(self):
        coverage = tradingview_alert_coverage.load_coverage()
        validation = tradingview_alert_coverage.validate_coverage(coverage)
        required_records = tradingview_alert_coverage.setup_records(coverage, required_only=True)
        all_records = tradingview_alert_coverage.setup_records(coverage)
        first = tradingview_alert_coverage.alert_by_code(coverage, "MNQ_ORB_BREAKOUT_LONG_5M")
        message = tradingview_alert_coverage.payload_for_alert(first)
        payload_validation = tradingview_payload_contract.validate_payload(message)

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["required_alert_count"], 10)
        self.assertEqual(validation["health_alert_count"], 2)
        self.assertEqual(len(required_records), 10)
        self.assertEqual(len(all_records), 12)
        self.assertEqual(message["event_code"], "MNQ_ORB_BREAKOUT_LONG_5M")
        self.assertTrue(payload_validation["valid"])

    def test_tradingview_payload_contract_validates_sample_and_missing_fields(self):
        valid = tradingview_payload_contract.validate_payload(
            tradingview_payload_contract.sample_payload()
        )
        invalid = tradingview_payload_contract.validate_payload({"ticker": "MNQ1!"})
        template = tradingview_payload_contract.validate_payload(
            tradingview_payload_contract.tradingview_placeholder_template()
        )

        self.assertTrue(valid["valid"])
        self.assertEqual(valid["context_completeness_pct"], 100.0)
        self.assertFalse(invalid["valid"])
        self.assertIn("vwap", invalid["missing_fields"])
        self.assertTrue(template["valid"])
        self.assertIn("price", template["placeholder_fields"])

    def test_tradingview_ledger_records_and_dedupes_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            payload = {
                "ticker": "MNQ",
                "timeframe": "5",
                "strategy_context": "INTRADAY_INDEX_FUTURES",
                "price": 23000.25,
                "session_state": "OPENING_RANGE",
                "vwap": 22980.0,
                "opening_range_high": 23010.0,
                "opening_range_low": 22920.0,
                "breakout_direction": "LONG",
                "adx": 24.5,
                "atr": 52.0,
                "volume_relative": 1.8,
                "premarket_high": 23040.0,
                "premarket_low": 22880.0,
                "logical_stop": 22950.0,
                "logical_target": 23120.0,
                "invalidation": "VWAP_LOST",
                "major_event_window": "NONE",
                "risk_daily_status": "OK",
                "portfolio_status": "OK",
            }

            first = tradingview_signal_ledger.append_signal_event(payload, raw_text=json.dumps(payload), endpoint="/technical_snapshot", path=path)
            second = tradingview_signal_ledger.append_signal_event(payload, raw_text=json.dumps(payload), endpoint="/technical_snapshot", path=path)
            events = tradingview_signal_ledger.load_signal_events(path)

        self.assertEqual(first["status"], "RECORDED")
        self.assertEqual(second["status"], "DUPLICATE")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["candidate_source"], "TRADINGVIEW_ALERT")
        self.assertEqual(events[0]["payload_contract_version"], "tradingview_signal_payload_v2")
        self.assertTrue(events[0]["payload_validation"]["valid"])
        self.assertEqual(events[0]["adx"], 24.5)
        self.assertEqual(events[0]["logical_stop"], 22950.0)
        self.assertEqual(events[0]["missing_context_fields"], [])
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
                    "iv": 0.27,
                    "data_quality": "PRICE_WITH_GREEKS_NO_BIDASK",
                }
            ],
        )

        self.assertEqual(diagnostic["diagnostic_version"], "ibkr_chain_coverage_v2")
        self.assertEqual(diagnostic["primary_gap"], "INCOMPLETE_OPTION_MARKET_DATA")
        self.assertEqual(diagnostic["missing_execution_field_counts"]["ask"], 1)
        self.assertEqual(diagnostic["option_rows"][0]["iv"], 0.27)
        self.assertEqual(diagnostic["option_rows"][0]["delta"], -0.18)
        self.assertEqual(diagnostic["discard_reason_counts"]["NO_BID_ASK"], 1)
        self.assertEqual(diagnostic["discard_reason_counts"]["PRICE_WITH_GREEKS_NO_BIDASK"], 1)
        self.assertEqual(diagnostic["discarded_contract_count"], 1)
        self.assertFalse(diagnostic["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
