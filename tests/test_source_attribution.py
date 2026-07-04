import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import source_attribution


class SourceAttributionTests(unittest.TestCase):
    def test_ibkr_option_and_tradingview_technical_are_attributed(self):
        decision = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
            "generated_at": "2026-07-04T15:00:00+00:00",
            "selected_contract": {
                "strike": 700,
                "expiration": "20260821",
                "dte": 48,
                "bid": 1.2,
                "ask": 1.35,
                "delta": -0.18,
                "local_symbol": "QQQ  260821P00700000",
            },
            "technical": {
                "source": "TECHNICAL_SNAPSHOT",
                "trend": "BULLISH",
                "score": 78,
            },
            "master_source": "runtime/v28_master_snapshot.json",
        }

        enriched = source_attribution.apply_source_attribution(decision)

        self.assertEqual(enriched["candidate_source"], "IBKR_OPTION_CHAIN")
        self.assertEqual(enriched["confirmation_source"], "TRADINGVIEW_ALERT")
        self.assertEqual(enriched["source_confidence"], "HIGH")
        self.assertTrue(enriched["signal_id"].startswith("SIG-2026-07-04-QQQ-NAKED_PUT-ENTRY_READY"))
        self.assertFalse(enriched["execution_authorized"])
        self.assertTrue(enriched["not_order_instruction"])

    def test_missing_data_is_explicit_not_unknown(self):
        enriched = source_attribution.apply_source_attribution({
            "ticker": "MSFT",
            "strategy": "UNKNOWN",
            "final_state": "NO_DATA",
            "generated_at": "2026-07-04T15:00:00+00:00",
        })

        self.assertEqual(enriched["candidate_source"], source_attribution.NO_CANDIDATE_SOURCE)
        self.assertEqual(enriched["confirmation_source"], source_attribution.NO_CONFIRMATION_SOURCE)
        self.assertFalse(enriched["source_attribution"]["unknown_source"])


if __name__ == "__main__":
    unittest.main()
