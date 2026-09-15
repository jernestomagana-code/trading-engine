from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import install_stock_ultimus_console_launchd as installer
from scripts import ibkr_account_profile as console


ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SOURCE = ROOT / "scripts" / "ibkr_account_profile.py"
OPERATOR_GUIDE = ROOT / "docs" / "guia-consola-stock-ultimus.md"


class ConsoleServiceAndUxTests(unittest.TestCase):
    def test_automatic_cycle_distinguishes_installed_from_confirmed(self):
        now = datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc)
        report = {"generated_at": "2026-09-04T16:35:00+00:00", "status": "READY"}
        cycle = console.build_automation_cycle_status(
            report, installed=True, now=now,
            last_attempt_at=datetime(2026, 9, 4, 16, 35, tzinfo=timezone.utc),
            last_attempt_ok=True,
        )
        self.assertEqual(cycle["state"], "ready")
        self.assertEqual(cycle["label"], "Automatización confirmada")
        self.assertIn("11:35 CDMX", cycle["next_run"])

    def test_automatic_cycle_surfaces_attempt_without_new_report(self):
        cycle = console.build_automation_cycle_status(
            {"generated_at": "2026-09-04T14:35:00+00:00", "status": "READY"},
            installed=True,
            now=datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc),
            last_attempt_at=datetime(2026, 9, 4, 16, 36, tzinfo=timezone.utc),
            last_attempt_ok=False,
        )
        self.assertEqual(cycle["state"], "review")
        self.assertIn("no existe un reporte posterior", cycle["detail"])

    def test_automatic_cycle_panel_explains_attempt_is_not_confirmation(self):
        with patch.object(console, "build_automation_cycle_status", return_value={
            "state": "scheduled", "label": "Automatización activa", "detail": "Programada.",
            "installed": True, "last_report": "hace 1 h", "last_status": "READY",
            "last_attempt": "hace 1 h", "last_attempt_status": "Completado", "next_run": "lun 07 sep · 07:35 CDMX",
            "schedule": "Días hábiles",
        }):
            html = console.render_automation_cycle_panel()
        self.assertIn('id="automatic-cycle"', html)
        self.assertIn("el reporte sigue siendo la evidencia principal", html)
        self.assertIn("Próxima ejecución", html)

    def test_daily_routine_is_short_ordered_and_safety_explicit(self):
        html = console.render_daily_operator_routine()
        self.assertIn('id="daily-routine"', html)
        steps = ["1. Leer Hoy", "2. Proteger la cartera", "3. Evaluar oportunidades", "4. Cerrar y aprender"]
        self.assertTrue(all(step in html for step in steps))
        self.assertEqual(sorted(html.index(step) for step in steps), [html.index(step) for step in steps])
        self.assertIn("nunca envía una orden", html)

    def test_trade_casefile_keeps_ticker_only_evidence_unlinked(self):
        decisions = [{"ticker": "NFLX", "strategy": "COVERED_CALL", "final_state": "MANAGE", "recorded_at": "2026-09-05T10:00:00+00:00"}]
        with patch.object(console, "json_rows", side_effect=[decisions, []]), patch.object(console, "load_operator_events", return_value=[]):
            rows = console.build_trade_casefiles({"positions": [{"ticker": "NFLX", "management_action": "HOLD"}]})
        self.assertEqual(rows[0]["phase"], "open")
        self.assertFalse(rows[0]["linked"])
        self.assertEqual(rows[0]["execution"], "Detectada automáticamente por posición")

    def test_usage_telemetry_is_local_minimal_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(console, "CONSOLE_USAGE_PATH", Path(tmp) / "usage.json"):
            result = console.record_console_usage("VIEW_CHANGE", "oportunidades")
            rejected = console.record_console_usage("ORDER", "oportunidades")
            payload = json.loads((Path(tmp) / "usage.json").read_text())
        self.assertTrue(result["ok"])
        self.assertFalse(rejected["ok"])
        self.assertEqual(set(payload["events"][0]), {"event", "view", "recorded_at", "session_date", "session_id"})

    def test_focus_mode_and_experience_validation_are_exposed(self):
        source = CONSOLE_SOURCE.read_text() + (ROOT / "scripts" / "console_ui.js").read_text()
        self.assertIn("data-focus-mode", source)
        self.assertIn("stockUltimusFocusMode", source)
        self.assertIn('fetch("/usage-event"', source)
        with patch.object(console, "load_json_file", return_value={"events": [], "session_dates": []}):
            html = console.render_usage_validation_panel()
        self.assertIn("0 sesiones registradas", html)
        self.assertIn("No guarda cuentas, posiciones, precios ni órdenes", html)

    def test_activity_view_leads_with_learning_conclusion_before_expired_signals(self):
        source = CONSOLE_SOURCE.read_text() + (ROOT / "scripts" / "console_ui.js").read_text()
        history = source.index('{history_learning_summary}', source.index('id="view-historial"'))
        futures = source.index('{futures_activity}', source.index('id="view-historial"'))
        self.assertLess(history, futures)

    def test_remote_refresh_prioritizes_live_futures_evidence(self):
        endpoints = {
            "operator": "/operator",
            "executive": "/executive",
            "rankings": "/rankings",
            "signal_events": "/signals",
            "futures_daily": "/futures",
            "webhook_status": "/webhook",
            "learning": "/learning",
        }

        phases = console.remote_refresh_phases(endpoints)

        self.assertEqual(
            [key for key, _ in phases[0]],
            ["operator", "signal_events", "futures_daily", "webhook_status"],
        )
        self.assertEqual(
            {key for key, _ in phases[1]},
            {"executive", "rankings", "learning"},
        )

    def test_remote_console_uses_bounded_history_windows(self):
        endpoints = console.remote_console_endpoints()
        self.assertEqual(endpoints["signal_events"], "/v32_signal_events?limit=100")
        self.assertEqual(endpoints["reviews"], "/v31_manual_reviews?limit=100")
        self.assertEqual(endpoints["performance"], "/v32_strategy_performance?limit=200")

    def test_unified_opportunity_center_prioritizes_ready_before_forming_and_waiting(self):
        operator = {
            "ok": True,
            "data": {
                "active_alerts": [
                    {
                        "ticker": "MNQ1!",
                        "received_at": console.now_iso(),
                        "strategy": "INTRADAY_INDEX_FUTURES",
                        "state": "ENTRY_READY",
                        "severity": "ACTION",
                        "entry_price": 20100,
                        "direction": "LONG", "current_price": 20100, "max_entry_price": 20105,
                        "quote_symbol": "MNQ1!", "quote_timestamp": console.now_iso(),
                        "stop_loss": 20070,
                        "target_1": 20130,
                        "target_2": 20160,
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

        items = console.build_unified_opportunity_items(
            operator, rsp, candidates, risk_payload={"alerts": []},
            account_capacity={"available_capacity": 50000, "capacity_source": "available_funds"},
            premium_payload={},
        )

        self.assertEqual(items[0]["type"], "futures")
        self.assertEqual(items[0]["state"], "ready")
        self.assertEqual(items[0]["invalidation"], "Stop 20070")
        self.assertEqual(items[0]["target"], "TP1 20130 · TP2 20160")
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
        self.assertIn('data-opportunity-filter="earnings"', html)
        self.assertIn('data-opportunity-filter="long_put"', html)
        self.assertIn("Entradas listas", html)
        self.assertIn("Preparándose", html)
        self.assertIn("Qué hacer ahora", html)
        self.assertIn("Entrada / nivel", html)
        self.assertIn("Invalida / riesgo", html)
        self.assertIn("Objetivo", html)
        self.assertIn("Falta / bloqueo", html)
        self.assertIn("Capital / margen requerido", html)
        self.assertIn("Capacidad disponible", html)
        self.assertIn("Capacidad después", html)
        self.assertIn("Impacto de riesgo", html)
        self.assertNotIn("Simulador pendiente", html)

    def test_expired_futures_never_return_to_live_opportunities(self):
        operator = {"ok": True, "data": {"active_alerts": [{
            "ticker": "MNQ1!", "strategy": "INTRADAY_INDEX_FUTURES", "state": "ENTRY_READY",
            "received_at": "2020-01-01T14:00:00+00:00", "entry_price": 20000,
            "stop_loss": 19980, "target_1": 20030,
        }], "intraday_futures": {"daily_summary": {"latest_signal": {
            "ticker": "MES1!", "state": "ENTRY_READY", "received_at": "2020-01-01T14:00:00+00:00"
        }}}}}
        items = console.build_unified_opportunity_items(
            operator, {"strategy_recommendation": {"status": "WAIT_DATA"}},
            {"candidates": []}, risk_payload={"alerts": []},
            account_capacity={"available_capacity": 25000},
        )
        self.assertFalse(any(item["type"] == "futures" for item in items))

    def test_unified_opportunity_financial_projection_blocks_insufficient_capacity(self):
        operator = {"ok": True, "data": {"active_alerts": [{
            "ticker": "NVDA",
            "state": "ENTRY_READY",
            "severity": "ACTION",
            "strategy": "CASH_SECURED_PUT",
            "selected_contract": {"strike": 200, "bid": 1.0},
        }]}}
        candidates = {"candidates": [{"ticker": "NVDA", "canslim_passes": True, "canslim_score": 88}]}

        items = console.build_unified_opportunity_items(
            operator,
            {"strategy_recommendation": {"status": "WAIT_DATA"}},
            candidates,
            risk_payload={"alerts": []},
            account_capacity={"available_capacity": 7000, "capacity_source": "available_funds"},
        )
        nvda = next(item for item in items if item["type"] == "canslim" and item["ticker"] == "NVDA")

        self.assertEqual(nvda["capital_required"], 19900)
        self.assertEqual(nvda["state"], "blocked")
        self.assertEqual(nvda["state_label"], "Bloqueada por capacidad")
        self.assertIn("insuficiente", nvda["capacity_after_label"])

    def test_unified_opportunity_global_data_risk_downgrades_ready_entry(self):
        operator = {"ok": True, "data": {"active_alerts": [{
            "ticker": "MNQ1!", "strategy": "INTRADAY_INDEX_FUTURES", "state": "ENTRY_READY",
            "severity": "ACTION", "entry_price": 20000, "stop_loss": 19980,
            "direction": "LONG", "current_price": 20000, "max_entry_price": 20005,
            "tp1_price": 20030, "quote_symbol": "MNQ1!", "quote_timestamp": console.now_iso(),
            "received_at": console.now_iso(),
        }]}}

        items = console.build_unified_opportunity_items(
            operator,
            {"strategy_recommendation": {"status": "WAIT_DATA"}},
            {"candidates": []},
            risk_payload={"alerts": [{"severity": "HIGH", "rule": "ACCOUNT_DATA_NOT_READY"}]},
            account_capacity={"available_capacity": 25000},
        )
        future = next(item for item in items if item["type"] == "futures")

        self.assertEqual(future["state"], "blocked")
        self.assertEqual(future["state_label"], "Bloqueada por riesgo")
        self.assertIn("Bloqueo global activo", future["risk_impact"])

    def test_opportunity_simulator_renders_real_unit_inputs_without_order_action(self):
        item = {
            "type": "canslim", "type_label": "CANSLIM", "ticker": "NVDA",
            "state": "ready", "state_label": "Entrada lista", "rank": 0,
            "quality": 90, "metric_label": "Score", "freshness": "ahora",
            "recommendation": "Revisar", "action": "Validar ticket", "trigger": "200",
            "invalidation": "190", "target": "220", "blocker": "Ninguno",
            "capital_label": "$5,000.00", "available_capacity_label": "$20,000.00",
            "capacity_after_label": "$15,000.00 · proyección", "risk_impact": "Sin bloqueo",
            "simulator_available": True, "simulator_unit_label": "contrato", "simulator_max": 10,
            "simulator_capital": 5000, "simulator_capacity": 20000,
        }
        with patch.object(console, "build_unified_opportunity_items", return_value=[item]):
            html = console.render_unified_opportunity_center({}, {})

        self.assertIn("Simulador previo", html)
        self.assertIn('data-unit-capital="5000"', html)
        self.assertIn('data-capacity="20000"', html)
        self.assertIn("Cantidad de contratos", html)
        self.assertIn("Referencia; no reserva fondos ni envía una orden.", html)
        self.assertNotIn("placeOrder", html)

    def test_position_recommendation_link_requires_more_than_ticker_when_contract_exists(self):
        position = {
            "ticker": "NVDA", "strategy": "CASH_SECURED_PUT", "sec_type": "OPT",
            "strike": 200, "expiration": "20261016", "right": "P",
        }
        exact_operator = {"data": {"active_alerts": [{
            "ticker": "NVDA", "strategy": "CASH_SECURED_PUT", "alert_id": "entry-1",
            "selected_contract": {"strike": 200, "expiration": "20261016", "right": "P"},
            "entry_price": 2.5, "stop_loss": 188, "target_1": 1.25,
        }]}}
        ticker_only_operator = {"data": {"active_alerts": [{"ticker": "NVDA", "alert_id": "other"}]}}

        exact = console.position_recommendation_match(position, exact_operator, {})
        ticker_only = console.position_recommendation_match(position, ticker_only_operator, {})

        self.assertEqual(exact["status"], "LINKED")
        self.assertEqual(exact["confidence"], "ALTA")
        self.assertEqual(exact["recommendation_id"], "entry-1")
        self.assertEqual(exact["invalidation"], 188)
        self.assertEqual(ticker_only["status"], "CANDIDATE_ONLY")

    def test_position_card_shows_automatic_post_entry_followup_plan(self):
        position = {
            "position_id": "NVDA-P200", "ticker": "NVDA", "strategy": "CASH_SECURED_PUT",
            "sec_type": "OPT", "position_size": -1, "strike": 200, "dte": 30,
            "average_cost": 2.4, "management_action": "NO_ACTION_RECOMMENDED", "exit_state": "MONITOR",
            "technical": {"support": 188, "resistance": 220}, "management_alternatives": {"alternatives": []},
        }
        match = {
            "status": "LINKED", "label": "Recomendación vinculada", "confidence": "ALTA",
            "source": "Stock Ultimus", "evidence": ["mismo ticker", "mismo strike"],
            "recommendation_id": "entry-1", "entry": 2.5, "invalidation": 188,
            "target_1": 1.25, "target_2": 0.5,
        }

        html = console.render_position_management_card(
            position, queue_meta={"key": "maintain", "label": "Mantener", "checkpoint": "Próxima apertura"},
            recommendation_match=match,
        )

        self.assertIn("Recomendación vinculada", html)
        self.assertIn("Entrada detectada en IBKR", html)
        self.assertIn("Entrada de la recomendación", html)
        self.assertIn("Invalidación / stop", html)
        self.assertIn("TP1 1.25 · TP2 0.5", html)
        self.assertIn("Próxima apertura", html)

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

    def test_today_queue_consolidates_repeated_data_risk_and_uses_position_priority(self):
        risk = {"alerts": [
            {"severity": "CRITICAL", "account_alias": "retiro", "title": "Datos no confiables en retiro"},
            {"severity": "CRITICAL", "account_alias": "retiro", "title": "NAV inválido en retiro"},
            {"severity": "CRITICAL", "account_alias": "remanente", "title": "Métricas de riesgo incompletas en remanente"},
        ]}
        positions = {"positions": [
            {"position_id": "A", "ticker": "NFLX", "management_action": "REVIEW_RISK", "exit_state": "RISK_REVIEW", "reasons": ["Review risk."]},
            {"position_id": "B", "ticker": "NFLX", "management_action": "REFRESH_DATA", "exit_state": "MONITOR"},
            {"position_id": "C", "ticker": "RSP", "management_action": "NO_ACTION_RECOMMENDED", "exit_state": "MONITOR"},
        ]}

        pending = console.build_unified_pending_items({}, positions, risk, {})

        risk_rows = [item for item in pending if item["area"] == "Riesgo"]
        position_rows = [item for item in pending if item["area"] == "Posiciones"]
        self.assertEqual(len(risk_rows), 1)
        self.assertIn("3 alertas relacionadas", risk_rows[0]["detail"])
        self.assertEqual(len(position_rows), 2)
        self.assertIn("NFLX", position_rows[0]["title"])
        self.assertEqual(position_rows[0]["when"], "Resolver ahora")

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
        source = CONSOLE_SOURCE.read_text() + (ROOT / "scripts" / "console_ui.js").read_text()

        self.assertIn('class="operator-nav"', source)
        for view in ("hoy", "decisiones", "seguimiento", "historial", "configuracion"):
            self.assertIn(f'data-console-view-link="{view}"', source)
            self.assertIn(f'data-console-view="{view}"', source)
        self.assertIn('legacyViews = {cartera: "decisiones", oportunidades: "decisiones"}', source)
        self.assertIn('Qué hacer con tu dinero ahora', source)
        self.assertIn('Qué estamos buscando', source)
        self.assertIn('id="analisis" class="panel operator-workspace"', source)
        self.assertIn('Detalle e informes técnicos', source)
        self.assertIn('{history_learning_summary}', source)
        self.assertIn('id="seguimiento-detalle" class="panel operator-workspace"', source)
        self.assertIn('id="analisis-cartera" class="operator-subsection"', source)
        self.assertIn('id="resultados" class="operator-subsection" open', source)
        self.assertIn('id="cuentas-config" class="panel operator-workspace" open', source)
        self.assertIn('id="herramientas" class="panel operator-workspace"', source)
        self.assertIn('Soporte y diagnóstico avanzado', source)
        self.assertIn('{configuration_overview}', source)
        self.assertIn('href="/guide">Ayuda</a>', source)
        self.assertIn('class="panel command-center command-{level}"', source)
        self.assertIn('Haz esto ahora', source)

        self.assertIn('id="position-search"', source)
        self.assertIn('data-position-card', source)
        self.assertIn('Primera decisión de cartera', source)
        self.assertIn('data-position-focus=', source)
        self.assertIn('Posiciones sin acción recomendada', source)
        self.assertIn('"Ultima apertura"', source)
        self.assertIn('"RSP OK"', source)
        self.assertIn("Ver {len(secondary_alerts)} alertas adicionales", source)
        self.assertIn('id="canslim-radar"', source)
        self.assertIn("De preselección C/A/L/M a decisión final", source)
        self.assertIn("1 · Universo", source)
        self.assertIn("5 · Entrada lista", source)
        self.assertIn("la lista se ordena por cercanía a una decisión", source)
        self.assertIn("Actividad reciente y señales caducadas", source)
        self.assertIn('<details id="alertas" class="operator-subsection">', source)
        risk_index = source.index('<details id="riesgo"')
        positions_index = source.index('<div id="posiciones">{active_positions}</div>')
        rsp_index = source.index("            {coberturas}\n", positions_index)
        tools_index = source.index('<details id="herramientas" class="panel operator-workspace">')
        self.assertLess(risk_index, positions_index)
        self.assertLess(positions_index, rsp_index)
        self.assertNotIn("{coberturas}", source[tools_index:source.index("</details>", tools_index)])

    def test_decision_entry_panel_excludes_forming_and_research_ideas(self):
        items = [
            {"state": "forming", "ticker": "WAIT", "research_only": False},
            {"state": "research", "ticker": "STUDY", "research_only": True},
        ]
        with patch.object(console, "build_unified_opportunity_items", return_value=items):
            rendered = console.render_actionable_entry_panel({}, {})
        self.assertIn("No hay una entrada nueva que decidir ahora", rendered)
        self.assertNotIn(">WAIT<", rendered)
        self.assertNotIn(">STUDY<", rendered)

    def test_decision_entry_panel_keeps_ready_and_blocked_entries(self):
        items = [
            {"state": "ready", "ticker": "READY", "type": "futures", "type_label": "Futuros", "state_label": "Lista", "action": "Evaluar", "trigger": "100", "invalidation": "95"},
            {"state": "blocked", "ticker": "BLOCK", "type": "rsp", "type_label": "RSP", "state_label": "Bloqueada", "action": "Resolver riesgo", "trigger": "10", "invalidation": "8"},
        ]
        with patch.object(console, "build_unified_opportunity_items", return_value=items):
            rendered = console.render_actionable_entry_panel({}, {})
        self.assertIn("READY · Lista", rendered)
        self.assertIn("BLOCK · Bloqueada", rendered)

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
                            "received_at": console.now_iso(),
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

        self.assertIn("Límite de entrada", html)
        self.assertIn("No calculada; no perseguir precio", html)
        self.assertIn("Actividad reciente y señales caducadas", html)
        self.assertIn("Última señal en cuarentena", html)
        self.assertIn("session_state", html)

    def test_futures_funnel_prioritizes_ready_and_explains_latency(self):
        daily = {"recent_events": [
            {"ticker": "MES1!", "event": "ENTRY", "accepted": True, "signal_actionability": "WATCH_ONLY", "confirmation_gate_status": "INSUFFICIENT", "price": 5000},
            {
                "ticker": "MNQ1!", "event": "ENTRY", "accepted": True, "final_state": "ENTRY_READY",
                "entry_price": 20000, "stop_price": 19980, "tp1_price": 20020, "tp2_price": 20040,
                "confirmation_quality_score": 80,
                "mobile_notification": {"pushover_sent": True, "signal_to_provider_ack_ms": 1250},
            },
        ]}

        rows = console.build_futures_operational_rows([], daily)

        self.assertEqual(rows[0]["ticker"], "MNQ1!")
        self.assertEqual(rows[0]["stage"], "Entrada lista")
        self.assertEqual(rows[0]["latency"]["label"], "1.2 s señal→celular")
        self.assertAlmostEqual(rows[0]["rr"], 1.0)
        self.assertEqual(rows[1]["stage"], "Vigilancia")

    def test_futures_latency_marks_stale_mobile_signal(self):
        event = {"mobile_notification": {"reason": "STALE_INTRADAY_ENTRY_SUPPRESSED", "signal_age_seconds_at_push": 130}}

        latency = console.futures_latency_summary(event)
        stage = console.futures_operational_stage({"event": "ENTRY", **event})

        self.assertTrue(latency["late"])
        self.assertEqual(stage[1], "Señal tardía")

    def test_native_fast_triggers_count_as_futures_entries(self):
        for event in ("ORB_BREAKOUT", "VWAP_RECLAIM", "VWAP_REJECT"):
            self.assertEqual(console.remote_futures_event_kind({"event": event}), "ENTRY")
        self.assertEqual(console.remote_futures_event_kind({"event_code": "MNQ_ORB_BREAKOUT_SHORT_5M"}), "ENTRY")

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
        self.assertIn("Entrada al confirmar 101", rows[0]["trigger"])
        self.assertIn("lectura preliminar", rows[1]["qualification"])
        self.assertEqual(rows[1]["missing_data"], "Falta L, M")
        self.assertIn("falta soporte", rows[0]["invalidation"])

    def test_canslim_funnel_explains_each_operational_field(self):
        source = CONSOLE_SOURCE.read_text(encoding="utf-8")

        for label in ("Por qué está en la lista", "Entrada esperada", "Invalidación", "Dato pendiente", "Gatillo", "Fortaleza relativa", "Punto de compra / distancia", "Volumen vs promedio", "Estrategia propuesta", "Bloqueo principal", "Siguiente condición necesaria"):
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
        self.assertIn(".position-structure-grid,.position-profile-grid,.canslim-facts,.futures-decision-grid {{ grid-template-columns:minmax(0,1fr); }}", source)
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

    def test_configuration_overview_distinguishes_setup_from_daily_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tower = root / "tower.json"
            auth = root / "auth.json"
            service = root / "console.plist"
            service.write_text("installed")
            tower.write_text(json.dumps({
                "status": "READY",
                "accounts": [{
                    "account_alias": "retiro", "configured": True,
                    "keychain_ready": True, "refresh_status": "READY",
                }],
            }))
            auth.write_text(json.dumps({"checks": {
                "read_token": {"ok": True}, "ingest_token": {"ok": True},
                "pushover_channel_configured": {"ok": True},
            }}))
            reports = {"tradingview": {
                "coverage_valid": True, "real_e2e_confirmed": False,
                "coverages": [
                    {"name": "intraday_index_futures", "production_active_alert_count": 2},
                    {"name": "options_underlying_confirmation", "production_active_alert_count": 3},
                ],
            }}
            with patch.object(console, "CONTROL_TOWER_PATH", tower), patch.object(
                console, "ENVIRONMENT_AUTH_PATH", auth
            ), patch.object(console, "CONSOLE_LAUNCH_AGENT_PATH", service):
                rendered = console.render_configuration_overview(
                    {"retiro": {}},
                    {"account_alias": "retiro", "account_scope": "retiro"},
                    {"account_alias": "retiro", "account_scope": "retiro"},
                    {"ok": True, "data": {"account_alias": "retiro", "account_scope": "retiro"}},
                    reports,
                )

        self.assertIn("¿Está lista esta instalación?", rendered)
        self.assertIn("6/6", rendered)
        self.assertIn("Instalación base lista", rendered)
        self.assertIn("PENDIENTE DE MERCADO ABIERTO", rendered)
        self.assertIn("TWS y conexión API", rendered)
        self.assertIn("Notificaciones móviles", rendered)
        self.assertIn("Probar sin enviar", rendered)
        self.assertIn('href="#view-hoy"', rendered)

    def test_configuration_overview_does_not_call_missing_setup_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"
            with patch.object(console, "CONTROL_TOWER_PATH", missing), patch.object(
                console, "ENVIRONMENT_AUTH_PATH", missing
            ), patch.object(console, "CONSOLE_LAUNCH_AGENT_PATH", root / "missing.plist"):
                rendered = console.render_configuration_overview({}, {}, {}, {"ok": False}, {"tradingview": {}})

        self.assertIn("0/6", rendered)
        self.assertIn("Instalación requiere atención", rendered)
        self.assertIn("REVISAR", rendered)


if __name__ == "__main__":
    unittest.main()
