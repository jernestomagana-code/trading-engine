import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import evidence_quality
import source_attribution


class EvidenceQualityTests(unittest.TestCase):
    def test_complete_entry_ready_evidence_scores_above_threshold(self):
        decision = source_attribution.apply_source_attribution({
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
            "selected_contract": {
                "strike": 700,
                "expiration": "20260821",
                "dte": 48,
                "bid": 1.2,
                "ask": 1.35,
                "spread_pct": 11.76,
                "delta": -0.18,
                "local_symbol": "QQQ  260821P00700000",
                "data_quality": "FULL_WITH_GREEKS",
            },
            "technical": {"confirmed": True, "source": "TECHNICAL_SNAPSHOT", "score": 82},
        })

        report = evidence_quality.evidence_quality_report(decision)

        self.assertGreaterEqual(report["score"], evidence_quality.ENTRY_READY_MIN_EVIDENCE_SCORE)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["execution_authorized"])

    def test_low_quality_evidence_selects_wait_options_gate(self):
        decision = source_attribution.apply_source_attribution({
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
            "selected_contract": {
                "strike": 700,
                "expiration": "20260821",
                "dte": 48,
                "bid": None,
                "ask": None,
                "spread_pct": 45.0,
                "delta": None,
                "option_discard_reasons": ["NO_BID_ASK", "NO_GREEKS", "SPREAD_TOO_WIDE"],
            },
            "technical": {"confirmed": True, "source": "TECHNICAL_SNAPSHOT", "score": 82},
        })

        report = evidence_quality.evidence_quality_report(decision)

        self.assertLess(report["score"], evidence_quality.ENTRY_READY_MIN_EVIDENCE_SCORE)
        self.assertIn("NO_BID_ASK", report["blockers"])
        self.assertEqual(evidence_quality.evidence_quality_wait_state(report), "WAIT_OPTIONS_DATA")


if __name__ == "__main__":
    unittest.main()
