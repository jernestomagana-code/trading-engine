import importlib.util
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class MacNotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime_patch = mock.patch.dict(os.environ, {"STOCK_ULTIMUS_RUNTIME_DIR": self.tmp.name})
        self.runtime_patch.start()
        self.module = load_module("mac_notifications_test", ROOT / "scripts" / "run_macos_notifications.py")

    def tearDown(self):
        self.runtime_patch.stop()
        self.tmp.cleanup()

    def test_only_accepted_entry_becomes_popup(self):
        base = {"event_id": "a", "accepted_for_engine": True, "final_state": "ENTRY_READY", "ticker": "MNQ", "direction": "LONG", "entry_price": 100, "stop_price": 95, "tp1_price": 105}
        result = self.module.entry_event(base)
        self.assertEqual(result["category"], "ENTRY")
        self.assertIn("entrada 100", result["message"])
        self.assertIsNone(self.module.entry_event({**base, "event_id": "b", "accepted_for_engine": False}))
        self.assertIsNone(self.module.entry_event({**base, "event_id": "c", "final_state": "WATCH"}))
        self.assertIsNone(self.module.entry_event({**base, "event_id": "d", "alert_priority": "SILENT"}))

    def test_prime_and_dedup_prevent_historical_popup(self):
        item = {"id": "entry-1", "category": "ENTRY", "title": "x", "subtitle": "x", "message": "x"}
        with mock.patch.object(self.module, "collect_local", return_value=[]), mock.patch.object(self.module, "read_token", return_value="token"), mock.patch.object(self.module, "collect_remote", return_value=[item]), mock.patch.object(self.module, "display") as display:
            first = self.module.run(prime=True)
            second = self.module.run()
        self.assertTrue(first["primed"])
        self.assertEqual(second["new_notification_count"], 0)
        display.assert_not_called()

    def test_new_high_risk_notifies_once(self):
        self.module.save_json(self.module.RISK_PATH, {"alerts": [{"alert_id": "risk-1", "severity": "HIGH", "lifecycle_status": "OPEN", "title": "Riesgo", "recommended_action": "Revisar"}]})
        with mock.patch.object(self.module, "read_token", return_value=""), mock.patch.object(self.module, "display") as display:
            result = self.module.run()
            again = self.module.run()
        self.assertEqual(result["new_notification_count"], 1)
        self.assertEqual(again["new_notification_count"], 0)
        self.assertEqual(display.call_count, 1)

    def test_installer_plist_is_interactive_and_frequent(self):
        installer = load_module("mac_notifications_installer_test", ROOT / "scripts" / "install_macos_notifications_launchd.py")
        payload = installer.payload()
        self.assertEqual(payload["StartInterval"], 15)
        self.assertEqual(payload["ProcessType"], "Interactive")
        self.assertTrue(payload["RunAtLoad"])


if __name__ == "__main__":
    unittest.main()
