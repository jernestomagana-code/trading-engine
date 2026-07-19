import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import canslim_free_engine


ROOT = Path(__file__).resolve().parents[1]


def companyfacts_fixture():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-07-01", "end": "2026-06-30", "val": 130},
                            {"fy": 2025, "fp": "Q2", "form": "10-Q", "filed": "2025-07-01", "end": "2025-06-30", "val": 100},
                            {"fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-15", "end": "2025-12-31", "val": 520},
                            {"fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-15", "end": "2024-12-31", "val": 400},
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-07-01", "end": "2026-06-30", "val": 26},
                            {"fy": 2025, "fp": "Q2", "form": "10-Q", "filed": "2025-07-01", "end": "2025-06-30", "val": 20},
                            {"fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-15", "end": "2025-12-31", "val": 104},
                            {"fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-15", "end": "2024-12-31", "val": 80},
                        ]
                    }
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {"fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-07-01", "end": "2026-06-30", "val": 1.30},
                            {"fy": 2025, "fp": "Q2", "form": "10-Q", "filed": "2025-07-01", "end": "2025-06-30", "val": 1.00},
                            {"fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-15", "end": "2025-12-31", "val": 5.20},
                            {"fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-15", "end": "2024-12-31", "val": 4.00},
                        ]
                    }
                },
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-07-01", "end": "2026-06-30", "val": 100000000}
                        ]
                    }
                }
            },
        }
    }


def bars(start=100.0, step=1.0, count=80):
    return [
        {
            "timestamp": f"2026-05-{(index % 28) + 1:02d}",
            "close": start + index * step,
            "volume": 1000000 + index,
        }
        for index in range(count)
    ]


class CanslimFreeEngineTests(unittest.TestCase):
    def test_scores_companyfacts_and_runtime_relative_strength(self):
        runtime_data = {
            "bars.json": {
                "historical_bars": {
                    "ACME": bars(step=2.0),
                    "SPY": bars(step=0.3),
                    "QQQ": bars(step=0.4),
                }
            }
        }
        payload = canslim_free_engine.build_payload(
            universe=["ACME"],
            companyfacts_by_ticker={"ACME": companyfacts_fixture()},
            runtime_data=runtime_data,
        )

        row = payload["candidates"][0]
        self.assertEqual(row["ticker"], "ACME")
        self.assertTrue(row["canslim_passes"])
        self.assertGreaterEqual(row["canslim_score"], 70)
        self.assertEqual(row["source"], "CANSLIM_FREE_ENGINE")
        self.assertFalse(row["execution_authorized"])
        self.assertTrue(row["not_order_instruction"])

    def test_script_uses_local_sec_cache_without_paid_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            cache = root / "sec"
            runtime.mkdir()
            cache.mkdir()
            (runtime / "bars.json").write_text(json.dumps({
                "historical_bars": {
                    "ACME": bars(step=2.0),
                    "SPY": bars(step=0.3),
                    "QQQ": bars(step=0.4),
                }
            }))
            (cache / "company_tickers.json").write_text(json.dumps({
                "0": {"ticker": "ACME", "cik_str": 123}
            }))
            (cache / "ACME_0000000123.json").write_text(json.dumps(companyfacts_fixture()))
            output = runtime / "canslim_candidates_latest.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_canslim_free_candidates.py"),
                    "--runtime-dir",
                    str(runtime),
                    "--sec-cache-dir",
                    str(cache),
                    "--output",
                    str(output),
                    "--universe",
                    "ACME",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            summary = json.loads(result.stdout)
            payload = json.loads(output.read_text())

        self.assertEqual(summary["status"], "OK")
        self.assertTrue(summary["free_data_only"])
        self.assertEqual(payload["pass_count"], 1)
        self.assertEqual(payload["candidates"][0]["ticker"], "ACME")
        self.assertEqual(payload["network_health"]["status"], "OK")

    def test_network_errors_are_tracked_until_recurrent_then_reset_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "canslim_network_error_state.json"
            universe = ["ACME", "QQQ"]
            errors = {
                "ACME": "<urlopen error [Errno 8] nodename nor servname provided>",
                "QQQ": "NON_COMPANY_SYMBOL_SKIPPED",
            }

            for index in range(canslim_free_engine.RECURRENT_ERROR_THRESHOLD):
                state = canslim_free_engine.update_error_state(
                    universe=universe,
                    successful_tickers=set(),
                    errors=errors,
                    path=state_path,
                    generated_at=f"2026-07-16T00:00:0{index}+00:00",
                )

            acme = state["tickers"]["ACME"]
            qqq = state["tickers"]["QQQ"]
            self.assertEqual(acme["status"], "RECURRENT_ERROR")
            self.assertEqual(acme["last_error_kind"], "NETWORK")
            self.assertEqual(qqq["status"], "SKIPPED_NON_COMPANY_SYMBOL")
            self.assertEqual(qqq["consecutive_failures"], 0)

            health = canslim_free_engine.summarize_network_health(
                universe=universe,
                errors=errors,
                error_state=state,
            )
            self.assertEqual(health["status"], "ACTION_REQUIRED")
            self.assertEqual(health["recurrent_tickers"], ["ACME"])
            self.assertEqual(health["skipped_non_company_symbols"], ["QQQ"])

            state = canslim_free_engine.update_error_state(
                universe=["ACME"],
                successful_tickers={"ACME"},
                errors={},
                path=state_path,
                generated_at="2026-07-16T00:01:00+00:00",
            )
            self.assertEqual(state["tickers"]["ACME"]["status"], "OK")
            self.assertEqual(state["tickers"]["ACME"]["consecutive_failures"], 0)

    def test_payload_exposes_degraded_canslim_network_health(self):
        state = {
            "version": 1,
            "tickers": {
                "ACME": {
                    "status": "TRANSIENT_ERROR",
                    "consecutive_failures": 1,
                    "last_error_kind": "NETWORK",
                    "last_error": "timed out",
                }
            },
        }

        payload = canslim_free_engine.build_payload(
            universe=["ACME"],
            companyfacts_by_ticker={},
            runtime_data={},
            errors={"ACME": "timed out"},
            error_state=state,
        )

        self.assertEqual(payload["network_health"]["status"], "DEGRADED")
        self.assertEqual(payload["network_health"]["transient_tickers"], ["ACME"])
        self.assertFalse(payload["execution_authorized"])
        self.assertTrue(payload["not_order_instruction"])


if __name__ == "__main__":
    unittest.main()
