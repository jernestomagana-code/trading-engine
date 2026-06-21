import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import market_regime_detector


class MarketRegimeDetectorTests(unittest.TestCase):
    def test_explicit_regime_is_preserved(self):
        detected = market_regime_detector.detect_market_regime(
            {"market_regime": "HIGH_VOL_EVENT_RISK"},
            {"SPY": {"trend": "BULLISH", "score": 90}},
        )

        self.assertEqual(detected["market_regime"], "HIGH_VOL_EVENT_RISK")
        self.assertEqual(detected["confidence"], "EXPLICIT")
        self.assertTrue(detected["not_order_instruction"])

    def test_high_vix_derives_event_risk_regime(self):
        detected = market_regime_detector.detect_market_regime(
            {"vix": 28.5},
            {"SPY": {"trend": "BULLISH", "score": 80}},
        )

        self.assertEqual(detected["market_regime"], "HIGH_VOL_EVENT_RISK")
        self.assertIn("vix=28.5", detected["evidence"])

    def test_bullish_technical_low_vol_derives_bullish_low_vol(self):
        detected = market_regime_detector.detect_market_regime(
            {"vix": 16.2},
            {"QQQ": {"trend": "BULLISH", "score": 82}},
        )

        self.assertEqual(detected["market_regime"], "BULLISH_LOW_VOL")
        self.assertIn("bullish_votes=1", detected["evidence"])

    def test_bearish_technical_derives_correction_regime(self):
        detected = market_regime_detector.detect_market_regime(
            {"vix": 21},
            {"SPY": {"trend": "BEARISH", "score": 30}},
        )

        self.assertEqual(detected["market_regime"], "BEARISH_OR_CORRECTION")
        self.assertIn("bearish_votes=1", detected["evidence"])

    def test_intraday_technical_with_adx_derives_intraday_trend(self):
        detected = market_regime_detector.detect_market_regime(
            {"adx": 24},
            {"ES": {"trend": "BULLISH", "strategy_context": "INTRADAY", "score": 72}},
        )

        self.assertEqual(detected["market_regime"], "INTRADAY_TREND")
        self.assertIn("intraday_votes=1", detected["evidence"])

    def test_unknown_when_evidence_is_insufficient(self):
        detected = market_regime_detector.detect_market_regime({}, {})

        self.assertEqual(detected["market_regime"], "UNKNOWN")
        self.assertEqual(detected["confidence"], "INSUFFICIENT_DATA")
        self.assertEqual(detected["detector_version"], "market_regime_detector_v1")


if __name__ == "__main__":
    unittest.main()
