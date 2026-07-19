from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts import install_stock_ultimus_console_launchd as installer
from scripts import ibkr_account_profile as console


ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SOURCE = ROOT / "scripts" / "ibkr_account_profile.py"
OPERATOR_GUIDE = ROOT / "docs" / "guia-consola-stock-ultimus.md"


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
        self.assertIn("docs", installer.SERVICE_COPY_DIRS)

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
        self.assertIn('href="/guide">Guía</a>', source)
        self.assertIn("Ver {len(secondary_alerts)} alertas adicionales", source)

    def test_operator_guide_is_canonical_and_covers_navigation(self):
        source = CONSOLE_SOURCE.read_text(encoding="utf-8")
        guide = OPERATOR_GUIDE.read_text(encoding="utf-8")
        nav_match = re.search(r'<nav class="operator-nav".*?</nav>', source, re.DOTALL)

        self.assertIsNotNone(nav_match)
        self.assertGreater(len(guide), 10000)
        self.assertIn("no compra, vende, abre, cierra ni modifica órdenes automáticamente", guide)
        for label in re.findall(r">([^<>]+)</a>", nav_match.group(0)):
            self.assertIn(label, guide, f"La guía oficial no explica la sección {label}")

    def test_operator_guide_renders_as_readable_html(self):
        payload = console.render_operator_guide_page().decode("utf-8")

        self.assertIn("Guía de uso de Stock Ultimus Console", payload)
        self.assertIn('href="/console"', payload)
        self.assertIn("<table>", payload)
        self.assertIn("<ol>", payload)
        self.assertNotIn("# Guía de uso", payload)


if __name__ == "__main__":
    unittest.main()
