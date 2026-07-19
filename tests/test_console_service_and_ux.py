from __future__ import annotations

import unittest
from pathlib import Path

from scripts import install_stock_ultimus_console_launchd as installer


ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SOURCE = ROOT / "scripts" / "ibkr_account_profile.py"


class ConsoleServiceAndUxTests(unittest.TestCase):
    def test_launch_agent_runs_from_application_support(self):
        payload = installer.plist_payload(8765)
        command = " ".join(payload["ProgramArguments"])

        self.assertEqual(payload["WorkingDirectory"], str(installer.SERVICE_ROOT))
        self.assertIn(str(installer.SERVICE_ROOT), command)
        self.assertNotIn(str(ROOT / "scripts" / "ibkr_account_profile.py"), command)
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])

    def test_service_bundle_dry_run_does_not_mutate_runtime(self):
        result = installer.prepare_service_bundle(dry_run=True)

        self.assertTrue(result["planned"])
        self.assertEqual(result["service_root"], str(installer.SERVICE_ROOT))
        self.assertEqual(result["service_runtime"], str(installer.SERVICE_RUNTIME))

    def test_opener_prefers_permanent_service_before_terminal_fallback(self):
        command = " ".join(installer.opener_plist_payload()["ProgramArguments"])

        self.assertIn("launchctl kickstart", command)
        self.assertIn(installer.LABEL, command)
        self.assertIn("Stock Ultimus Console.command", command)

    def test_console_exposes_compact_operator_navigation(self):
        source = CONSOLE_SOURCE.read_text()

        self.assertIn('class="operator-nav"', source)
        self.assertIn('href="#hoy"', source)
        self.assertIn('id="cartera" class="panel operator-workspace"', source)
        self.assertIn('id="resultados" class="panel operator-workspace"', source)
        self.assertIn('id="herramientas" class="panel operator-workspace"', source)
        self.assertIn("Ver {len(secondary_alerts)} alertas adicionales", source)


if __name__ == "__main__":
    unittest.main()
