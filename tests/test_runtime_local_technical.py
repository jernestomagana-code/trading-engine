import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import runtime_local_technical
from tools import publish_v31_snapshot_from_runtime as publisher


def bullish_bars(count=60):
    price = 100.0
    rows = []
    for index in range(count):
        price += 0.3
        rows.append({
            "timestamp": f"2026-06-{(index % 28) + 1:02d}",
            "open": price - 0.2,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1_000_000 + index,
        })
    return rows


class RuntimeLocalTechnicalTests(unittest.TestCase):
    def test_extracts_local_bars_from_runtime_shapes(self):
        runtime_data = {
            "market.json": {
                "prices": {
                    "QQQ": {
                        "ticker": "QQQ",
                        "historical_bars": bullish_bars(),
                    }
                }
            },
            "nested.json": {
                "local_bars": {
                    "SPY": bullish_bars(),
                }
            },
        }

        bars = runtime_local_technical.extract_local_bar_sets(runtime_data)

        self.assertIn("QQQ", bars)
        self.assertIn("SPY", bars)
        self.assertGreaterEqual(len(bars["QQQ"]), 60)

    def test_ignores_internal_runtime_keys_as_tickers(self):
        runtime_data = {
            "diagnostic.json": {
                "historical_bars": {
                    "TOP": bullish_bars(),
                    "CANSLIM": bullish_bars(),
                    "NAKED_PUT": bullish_bars(),
                    "PLTR": bullish_bars(),
                }
            }
        }

        bars = runtime_local_technical.extract_local_bar_sets(runtime_data)

        self.assertIn("PLTR", bars)
        self.assertNotIn("TOP", bars)
        self.assertNotIn("CANSLIM", bars)
        self.assertNotIn("NAKED_PUT", bars)

    def test_builds_local_technical_only_for_missing_ticker(self):
        runtime_data = {
            "sample.json": {
                "historical_bars": {
                    "QQQ": bullish_bars(),
                    "SPY": bullish_bars(),
                }
            }
        }
        existing = {
            "QQQ": {
                "ticker": "QQQ",
                "source": "TRADINGVIEW_ALERT",
                "trend": "BEARISH",
                "score": 10,
            }
        }

        merged = runtime_local_technical.merge_local_technical_snapshot(
            existing,
            runtime_data,
            options_rows=[
                {"ticker": "QQQ", "strategy": "NAKED_PUT"},
                {"ticker": "SPY", "strategy": "NAKED_PUT"},
            ],
        )

        self.assertEqual(merged["QQQ"]["source"], "TRADINGVIEW_ALERT")
        self.assertIn("SPY", merged)
        self.assertEqual(merged["SPY"]["source"], "LOCAL_TECHNICAL_ENGINE")
        self.assertIsNotNone(merged["SPY"]["support"])
        self.assertIsNotNone(merged["SPY"]["resistance"])
        self.assertLess(merged["SPY"]["support"], merged["SPY"]["price"])
        self.assertIn("NAKED_PUT", merged["SPY"]["by_strategy_context"])
        self.assertFalse(merged["SPY"]["execution_authorized"])
        self.assertTrue(merged["SPY"]["not_order_instruction"])

    def test_runtime_publisher_includes_local_technical_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "sample.json").write_text(json.dumps({
                "options_rows": [
                    {
                        "ticker": "SPY",
                        "strategy": "NAKED_PUT",
                        "decision": "RADAR",
                        "strike": 500,
                    }
                ],
                "historical_bars": {
                    "SPY": bullish_bars(),
                },
            }))

            payload = publisher.build_payload(runtime)

        self.assertIn("SPY", payload["technical_snapshot"])
        self.assertEqual(payload["technical_snapshot"]["SPY"]["source"], "LOCAL_TECHNICAL_ENGINE")
        self.assertFalse(payload["technical_snapshot"]["SPY"]["execution_authorized"])
        self.assertTrue(payload["not_order_instruction"])

    def test_runtime_publisher_script_runs_with_local_technical_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "sample.json").write_text(json.dumps({
                "options_rows": [{"ticker": "SPY", "strategy": "NAKED_PUT", "decision": "RADAR"}],
                "historical_bars": {"SPY": bullish_bars()},
            }))
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "tools" / "publish_v31_snapshot_from_runtime.py"),
                    "--runtime-dir",
                    str(runtime),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["technical_count"], 1)
        self.assertIn("SPY", payload["tickers_detected"])
        self.assertTrue(payload["not_order_instruction"])


if __name__ == "__main__":
    unittest.main()
