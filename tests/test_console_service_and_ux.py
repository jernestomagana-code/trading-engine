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
        self.assertIn("tools", installer.SERVICE_COPY_DIRS)

    def test_opener_prefers_permanent_service_before_terminal_fallback(self):
        command = " ".join(installer.opener_plist_payload()["ProgramArguments"])

        self.assertIn("launchctl kickstart", command)
        self.assertIn(installer.LABEL, command)
        self.assertIn("Stock Ultimus Console.command", command)

    def test_console_exposes_compact_operator_navigation(self):
        source = CONSOLE_SOURCE.read_text()

        self.assertIn('class="operator-nav"', source)
        self.assertIn('href="#hoy"', source)
        self.assertIn('href="#pendientes">Pendientes</a>', source)
        self.assertIn('href="#coberturas-rsp">RSP</a>', source)
        self.assertIn('id="analisis" class="panel operator-workspace"', source)
        self.assertIn('id="cartera" class="operator-subsection"', source)
        self.assertIn('id="resultados" class="operator-subsection"', source)
        self.assertIn('id="herramientas" class="panel operator-workspace"', source)
        self.assertIn('href="/guide">Ayuda</a>', source)
        self.assertIn('class="panel command-center command-{level}"', source)
        self.assertIn('"Ultima apertura"', source)
        self.assertIn('"RSP OK"', source)
        self.assertIn("Ver {len(secondary_alerts)} alertas adicionales", source)
        risk_index = source.index('<div id="riesgo">{portfolio_risk}</div>')
        positions_index = source.index('<div id="posiciones">{active_positions}</div>')
        rsp_index = source.index("          {coberturas}\n", positions_index)
        tools_index = source.index('<details id="herramientas" class="panel operator-workspace">')
        self.assertLess(risk_index, positions_index)
        self.assertLess(positions_index, rsp_index)
        self.assertNotIn("{coberturas}", source[tools_index:source.index("</details>", tools_index)])

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

    def test_daily_open_includes_rsp_and_resilient_timeouts(self):
        command = console.daily_open_command()

        self.assertIn("--rsp-bridge-timeout", command)
        self.assertEqual(command[command.index("--bridge-timeout") + 1], "240")
        self.assertEqual(command[command.index("--rsp-bridge-timeout") + 1], "120")
        self.assertEqual(command[command.index("--capacity-timeout") + 1], "20")
        self.assertEqual(command[command.index("--read-timeout") + 1], "30")
        self.assertGreaterEqual(console.CONSOLE_DAILY_OPEN_TIMEOUT_SECONDS, 600)

    def test_rsp_has_a_dedicated_retirement_account(self):
        source = CONSOLE_SOURCE.read_text(encoding="utf-8")
        guide = OPERATOR_GUIDE.read_text(encoding="utf-8")

        self.assertEqual(console.CONSOLE_COBERTURAS_RSP_ACCOUNT_ALIAS, "retiro")
        self.assertIn('selected_alias = CONSOLE_COBERTURAS_RSP_ACCOUNT_ALIAS', source)
        self.assertIn('if "--coberturas-rsp-weekly" not in command:', source)
        self.assertIn("Cuenta RSP", source)
        self.assertIn("RSP → retiro", guide)

    def test_completed_opening_with_only_foundation_gap_is_presented_as_evidence_collection(self):
        report = {
            "status": "ACTION_REQUIRED",
            "refresh_step": {"ok": True},
            "capacity_refresh_step": {"ok": True},
            "rsp_refresh_step": {"ok": True},
            "coberturas_rsp": {"ok": True},
            "publish_step": {"ok": True},
            "checks": {
                "production_auth": {"ok": True},
                "v32_operator_today": {"ok": True},
                "foundation_health": {"status": "FAIL"},
            },
        }

        self.assertEqual(console.effective_daily_open_status(report), "EVIDENCE_COLLECTION_ONLY")


if __name__ == "__main__":
    unittest.main()
