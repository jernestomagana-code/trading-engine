import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


account_console = load_module("ibkr_account_profile_for_test", ROOT / "scripts" / "ibkr_account_profile.py")
runtime_publisher = load_module("publish_v31_snapshot_for_test", ROOT / "tools" / "publish_v31_snapshot_from_runtime.py")


class IbkrAccountConsoleCapacityTests(unittest.TestCase):
    def test_publisher_merges_sanitized_capacity_without_account_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp)
            (runtime_dir / "ibkr_account_active_profile.json").write_text(json.dumps({
                "account_scope": "remanente",
                "account_alias": "remanente",
                "selected_at": "2026-07-11T03:13:00+00:00",
            }))
            (runtime_dir / "ibkr_account_capacity_latest.json").write_text(json.dumps({
                "account_scope": "remanente",
                "account_alias": "remanente",
                "available": True,
                "available_capacity": 20570.57,
                "available_funds": 20570.57,
                "buying_power": 82282.28,
                "currency": "USD",
                "source": "IBKR_ACCOUNT_SUMMARY_SANITIZED",
                "sensitive_identifiers_excluded": True,
            }))

            context = runtime_publisher.active_account_context(runtime_dir)

        self.assertEqual(context["account_context_version"], "local_runtime_account_context_with_capacity_v1")
        self.assertEqual(context["account_alias"], "remanente")
        self.assertEqual(context["available_capacity"], 20570.57)
        self.assertEqual(context["source"], "IBKR_ACCOUNT_SUMMARY_SANITIZED")
        self.assertTrue(context["real_account_id_excluded"])
        self.assertTrue(context["sensitive_identifiers_excluded"])
        self.assertFalse(context["execution_authorized"])
        self.assertTrue(context["not_order_instruction"])
        self.assertNotIn("account_id", context)

    def test_console_renders_option_economics_and_capacity(self):
        alert = {
            "ticker": "MSFT",
            "strategy": "NAKED_PUT",
            "state": "ENTRY_READY",
            "severity": "ACTION",
            "selected_contract": {
                "strike": 350,
                "dte": 42,
                "bid": 7.25,
                "mid": 7.45,
                "delta": -0.2234,
            },
        }
        capacity = {
            "available_capacity": 20570.57,
            "capacity_source": "available_funds",
        }

        economics = account_console.render_alert_economics(alert)
        capacity_line = account_console.render_alert_capacity(alert, capacity)

        self.assertIn("Capital req: $34,275.00", economics)
        self.assertIn("credito bruto: $725.00", economics)
        self.assertIn("prob. exito: 77.66%", economics)
        self.assertIn("retorno anualizado", economics)
        self.assertIn("sin capital suficiente", capacity_line)
        self.assertIn("faltante $13,704.43", capacity_line)

    def test_handled_operator_events_are_removed_from_first_review_queue(self):
        data = {
            "active_alerts": [
                {"ticker": "QQQ", "severity": "ACTION", "operator_status": "NEW"},
                {"ticker": "SPY", "severity": "WATCH", "operator_status": "WATCHLIST"},
                {"ticker": "TSLA", "severity": "RISK", "operator_status": "REJECTED"},
            ]
        }

        counts = account_console.operator_alert_counts(data)

        self.assertEqual(counts["open"], 1)
        self.assertEqual(counts["action"], 1)
        self.assertEqual(counts["watch"], 0)
        self.assertEqual(counts["risk"], 0)
        self.assertEqual(counts["closed"], 2)


if __name__ == "__main__":
    unittest.main()
