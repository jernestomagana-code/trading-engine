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
    def test_unified_opportunity_center_prioritizes_ready_before_forming_and_waiting(self):
        operator = {
            "ok": True,
            "data": {
                "active_alerts": [
                    {
                        "ticker": "MNQ1!",
                        "strategy": "INTRADAY_INDEX_FUTURES",
                        "state": "ENTRY_READY",
                        "severity": "ACTION",
                        "entry_price": 20100,
                        "confirmation_quality_score": 88,
                    },
                    {
                        "ticker": "NVDA",
                        "state": "WAIT_TECHNICAL",
                        "severity": "WATCH",
                        "main_blocker": "WAIT_TECHNICAL",
                    },
                ]
            },
        }
        candidates = {
            "generated_at": "2026-08-29T12:00:00+00:00",
            "candidates": [
                {"ticker": "NVDA", "canslim_passes": True, "canslim_score": 86},
                {"ticker": "MSFT", "canslim_passes": False, "canslim_score": 40},
            ],
        }
        rsp = {
            "strategy_recommendation": {"status": "WAIT_NO_ELIGIBLE_STRUCTURE"},
            "blockers": ["RSP_NO_RECOMMENDATION_ELIGIBLE_CANDIDATES"],
            "ibkr": {"chain_has_rsp": True, "chain_is_fresh": True},
        }

        items = console.build_unified_opportunity_items(operator, rsp, candidates)

        self.assertEqual(items[0]["type"], "futures")
        self.assertEqual(items[0]["state"], "ready")
        self.assertEqual({item["type"] for item in items}, {"futures", "canslim", "rsp"})
        self.assertEqual(next(item for item in items if item["type"] == "rsp")["state"], "waiting")

    def test_unified_opportunity_center_exposes_filters_and_common_decision_fields(self):
        operator = {"ok": True, "data": {"active_alerts": []}}
        rsp = {"strategy_recommendation": {"status": "WAIT_DATA"}, "blockers": ["RSP_FRESH_CHAIN_MISSING"]}

        html = console.render_unified_opportunity_center(operator, rsp)

        self.assertIn('id="opportunity-center"', html)
        self.assertIn('data-opportunity-filter="all"', html)
        self.assertIn('data-opportunity-filter="canslim"', html)
        self.assertIn('data-opportunity-filter="futures"', html)
        self.assertIn('data-opportunity-filter="rsp"', html)
        self.assertIn("Entradas listas", html)
        self.assertIn("Preparándose", html)
        self.assertIn("Falta / bloqueo", html)

    def test_rsp_fresh_evaluated_wait_is_not_a_refresh_pending_item(self):
        rsp = {
            "blockers": ["RSP_NO_RECOMMENDATION_ELIGIBLE_CANDIDATES"],
            "candidate_count": 0,
            "ibkr": {"chain_has_rsp": True, "chain_is_fresh": True},
            "strategy_recommendation": {"status": "WAIT_NO_ELIGIBLE_STRUCTURE"},
        }

        self.assertTrue(console.rsp_current_wait_without_opportunity(rsp))
        pending = console.build_unified_pending_items({}, {"positions": []}, {"alerts": []}, rsp)
        self.assertFalse(any(item.get("area") == "RSP" for item in pending))

    def test_rsp_missing_fresh_chain_remains_a_pending_item(self):
        rsp = {
            "blockers": ["RSP_FRESH_CHAIN_MISSING"],
            "candidate_count": 0,
            "ibkr": {"chain_has_rsp": False, "chain_is_fresh": False},
            "strategy_recommendation": {"status": "WAIT_DATA"},
        }

        self.assertFalse(console.rsp_current_wait_without_opportunity(rsp))
        pending = console.build_unified_pending_items({}, {"positions": []}, {"alerts": []}, rsp)
        self.assertTrue(any(item.get("title") == "Coberturas RSP necesita actualización" for item in pending))

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

    def test_opener_prefers_permanent_service_before_repair_launcher(self):
        command = " ".join(installer.opener_plist_payload()["ProgramArguments"])

        self.assertIn("launchctl kickstart", command)
        self.assertIn(installer.LABEL, command)
        self.assertIn("Stock Ultimus Console.command", command)

    def test_console_exposes_compact_operator_navigation(self):
        source = CONSOLE_SOURCE.read_text()

        self.assertIn('class="operator-nav"', source)
        for view in ("hoy", "cartera", "oportunidades", "historial", "configuracion"):
            self.assertIn(f'data-console-view-link="{view}"', source)
            self.assertIn(f'data-console-view="{view}"', source)
        self.assertIn('id="analisis" class="panel operator-workspace" open', source)
        self.assertIn('id="cartera" class="operator-subsection"', source)
        self.assertIn('id="resultados" class="operator-subsection" open', source)
        self.assertIn('id="herramientas" class="panel operator-workspace" open', source)
        self.assertIn('href="/guide">Ayuda</a>', source)
        self.assertIn('class="panel command-center command-{level}"', source)
        self.assertIn('Tus tres prioridades', source)
        self.assertIn('id="position-search"', source)
        self.assertIn('data-position-card', source)
        self.assertIn('"Ultima apertura"', source)
        self.assertIn('"RSP OK"', source)
        self.assertIn("Ver {len(secondary_alerts)} alertas adicionales", source)
        self.assertIn('id="canslim-radar"', source)
        self.assertIn("De preselección C/A/L/M a decisión final", source)
        self.assertIn("1 · Universo", source)
        self.assertIn("5 · Entrada lista", source)
        self.assertIn("la lista se ordena por cercanía a una decisión", source)
        self.assertIn("Actividad de futuros recibida hoy", source)
        self.assertIn('<details id="alertas" class="panel operator-workspace secondary-workspace" open>', source)
        risk_index = source.index('<div id="riesgo">{portfolio_risk}</div>')
        positions_index = source.index('<div id="posiciones">{active_positions}</div>')
        rsp_index = source.index("            {coberturas}\n", positions_index)
        tools_index = source.index('<details id="herramientas" class="panel operator-workspace" open>')
        self.assertLess(risk_index, positions_index)
        self.assertLess(positions_index, rsp_index)
        self.assertNotIn("{coberturas}", source[tools_index:source.index("</details>", tools_index)])

    def test_futures_history_explains_mobile_filter_and_quarantine(self):
        operator = {
            "ok": True,
            "data": {
                "intraday_futures": {
                    "daily_summary": {
                        "entry": 1,
                        "watch": 0,
                        "snapshot": 0,
                        "received": 2,
                        "accepted": 1,
                        "quarantined": 1,
                        "processed_total": 1,
                        "latest_signal": {
                            "event": "ENTRY",
                            "ticker": "USTEC.F",
                            "direction": "LONG",
                            "entry_price": 28486.13,
                            "stop_price": 28435.92,
                            "tp1_price": 28536.34,
                            "tp2_price": 28586.55,
                            "signal_actionability": "WATCH_ONLY",
                            "confirmation_gate_status": "INSUFFICIENT",
                            "confirmation_reasons": ["MOMENTUM"],
                            "confirmation_conflicts": ["COUNTERTREND", "MACD", "RSI"],
                            "decision_explanation": "Confirmación insuficiente; mantener en vigilancia.",
                        },
                        "latest_quarantined": {
                            "ticker": "MES1!",
                            "event": "ENTRY",
                            "price": 7569,
                            "missing_fields": ["session_state", "premarket_high"],
                        },
                        "recent_events": [{
                            "ticker": "MES1!",
                            "event": "ENTRY",
                            "price": 7569,
                            "received_at": "2026-08-03T13:47:00+00:00",
                            "accepted": False,
                            "missing_fields": ["session_state", "premarket_high"],
                        }],
                    }
                }
            },
        }

        html = console.render_intraday_futures_alerts([], operator)

        self.assertIn("Celular: no enviado; no alcanzó ENTRY_READY", html)
        self.assertIn("Actividad de futuros recibida hoy (1)", html)
        self.assertIn("Última señal en cuarentena", html)
        self.assertIn("session_state", html)

    def test_canslim_context_is_visible_in_final_alerts(self):
        operator = {"ok": True, "data": {"active_alerts": [], "diagnostic_alerts": [{"ticker": "NVDA"}]}}
        candidates = {"candidates": [{
            "ticker": "NVDA",
            "canslim_score": 91,
            "canslim_rating": "LEADER",
            "canslim_passes": True,
        }]}

        from unittest.mock import patch
        with patch.object(console, "load_json_file", return_value=candidates):
            merged = console.merge_local_canslim_context(operator)

        alert = merged["data"]["diagnostic_alerts"][0]
        self.assertEqual(alert["canslim_score"], 91)
        self.assertTrue(alert["canslim_passes"])
        self.assertEqual(alert["canslim_rating"], "LEADER")

    def test_canslim_funnel_ranks_actionability_before_raw_score(self):
        candidates = {"generated_at": "2026-08-29T15:00:00+00:00", "candidates": [
            {
                "ticker": "HIGH",
                "canslim_passes": True,
                "canslim_score": 100,
                "canslim_component_coverage_pct": 50,
                "canslim_missing_components": ["L", "M"],
                "canslim": {"components": {"C_quarterly_growth": 100, "A_annual_growth": 100, "L_relative_strength": None, "M_market": None}},
            },
            {
                "ticker": "READY",
                "canslim_passes": True,
                "canslim_score": 72,
                "canslim_component_coverage_pct": 100,
                "canslim": {"components": {"C_quarterly_growth": 72, "A_annual_growth": 74, "L_relative_strength": 71, "M_market": 70}},
            },
        ]}
        decisions = {"by_ticker": [{"ticker": "READY", "best": {"strategy": "NAKED_PUT", "dte": 35, "strike": 90}}]}
        operator = {"data": {"active_alerts": [{"ticker": "READY", "state": "ENTRY_READY", "entry_price": 101}], "diagnostic_alerts": []}}

        rows = console.build_canslim_operational_rows(operator, candidates, decisions)

        self.assertEqual(rows[0]["ticker"], "READY")
        self.assertEqual(rows[0]["stage"], "Entrada lista")
        self.assertEqual(rows[1]["coverage_label"], "Parcial; falta L, M")
        self.assertEqual(rows[1]["relative_strength"], "Pendiente; L no disponible")

    def test_canslim_funnel_explains_each_operational_field(self):
        source = CONSOLE_SOURCE.read_text(encoding="utf-8")

        for label in ("Gatillo", "Fortaleza relativa", "Punto de compra / distancia", "Volumen vs promedio", "Estrategia propuesta", "Bloqueo principal", "Siguiente condición necesaria"):
            self.assertIn(label, source)
        self.assertIn('class="canslim-components"', source)
        self.assertIn("Pendiente; la fuente actual no lo entrega", source)

    def test_position_recommendations_use_full_width_responsive_layout(self):
        source = CONSOLE_SOURCE.read_text(encoding="utf-8")

        self.assertIn(".position-list {{ display:grid; gap:10px; }}", source)
        self.assertIn(".position-card-summary {{ cursor:pointer; list-style:none; display:grid;", source)
        self.assertIn(".position-structure-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr));", source)
        self.assertIn("@media (max-width:620px)", source)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", source)
        self.assertIn(".position-structure-grid,.position-profile-grid,.canslim-facts {{ grid-template-columns:minmax(0,1fr); }}", source)
        self.assertIn(".position-comparison-scroll {{ overflow-x:auto; max-width:100%;", source)
        self.assertEqual(console.friendly_operator_state("REVIEW_RISK"), "Revisar riesgo")
        self.assertEqual(console.friendly_operator_state("STALE"), "Desactualizados")
        self.assertEqual(
            console.friendly_operator_state("MANAGE_EXISTING_AND_WAIT_NEW_ENTRY_DATA"),
            "Gestionar la posición actual y esperar datos para una nueva entrada",
        )

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
        self.assertEqual(command[command.index("--bridge-timeout") + 1], "180")
        self.assertEqual(command[command.index("--rsp-bridge-timeout") + 1], "90")
        self.assertEqual(command[command.index("--control-tower-timeout") + 1], "90")
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
