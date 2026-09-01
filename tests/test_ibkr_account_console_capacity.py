import importlib.util
import concurrent.futures
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


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
    def test_control_tower_fresh_account_overrides_stale_single_account_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            active_path = runtime / "ibkr_account_active_profile.json"
            tower_path = runtime / "broker_control_tower_latest.json"
            health_path = runtime / "ibkr_bridge_health_latest.json"
            session_path = runtime / "stock_ultimus_console_bridge_latest.json"
            web_result_path = runtime / "ibkr_account_profile_web_last_result.json"
            capacity_path = runtime / "ibkr_account_capacity_latest.json"
            active_path.write_text(json.dumps({"account_alias": "remanente", "account_scope": "remanente"}))
            tower_path.write_text(json.dumps({
                "generated_at": "2026-07-21T14:22:24+00:00",
                "accounts": [{
                    "account_alias": "remanente",
                    "account_scope": "remanente",
                    "refresh_status": "READY",
                    "generated_at": "2026-07-21T14:22:07+00:00",
                    "capacity": {"available_funds": 15731.34, "buying_power": 63591.84},
                }],
            }))
            health_path.write_text(json.dumps({
                "status": "CONNECTED",
                "connected": True,
                "account_alias": "retiro",
                "account_scope": "retiro",
                "generated_at": "2026-07-21T14:07:16+00:00",
            }))
            session_path.write_text(json.dumps({"runs": []}))
            web_result_path.write_text(json.dumps({
                "alias": "remanente",
                "account_scope": "remanente",
                "returncode": 0,
                "remote_verification_ok": True,
                "generated_at": "2026-07-21T14:23:44+00:00",
            }))
            capacity_path.write_text(json.dumps({
                "available": True,
                "account_alias": "remanente",
                "account_scope": "remanente",
                "available_capacity": 15.76,
                "generated_at": "2026-07-20T16:00:42+00:00",
            }))
            patches = [
                patch.object(account_console, "RUNTIME", runtime),
                patch.object(account_console, "ACTIVE_PATH", active_path),
                patch.object(account_console, "CONTROL_TOWER_PATH", tower_path),
                patch.object(account_console, "IBKR_BRIDGE_HEALTH_PATH", health_path),
                patch.object(account_console, "CONSOLE_BRIDGE_SESSION_PATH", session_path),
                patch.object(account_console, "WEB_LAST_RESULT_PATH", web_result_path),
                patch.object(account_console, "ACCOUNT_CAPACITY_PATH", capacity_path),
            ]
            for item in patches:
                item.start()
            try:
                active = account_console.active_profile()
                connection = account_console.latest_ibkr_connection_status(active)
                capacity = account_console.console_account_capacity({"data": {}}, {"available": True})
            finally:
                for item in reversed(patches):
                    item.stop()

        self.assertTrue(connection["available"])
        self.assertEqual(connection["status"], "CONNECTED_CONTROL_TOWER")
        self.assertEqual(connection["source"], "BROKER_CONTROL_TOWER")
        self.assertTrue(connection["published"])
        self.assertEqual(capacity["available_capacity"], 15731.34)
        self.assertEqual(capacity["capacity_source"], "control_tower_available_funds")

    def test_daily_open_timeout_is_recovered_by_newer_ready_tower_and_report_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            tower_path = runtime / "broker_control_tower_latest.json"
            tower_path.write_text(json.dumps({
                "generated_at": "2026-07-21T14:22:24+00:00",
                "accounts": [
                    {"refresh_status": "READY"},
                    {"refresh_status": "READY"},
                    {"refresh_status": "READY"},
                ],
            }))
            report = {
                "generated_at": "2026-07-21T14:03:13+00:00",
                "status": "ACTION_REQUIRED",
                "refresh_step": {"ok": False, "error": "TIMEOUT_AFTER_240_SECONDS"},
                "capacity_refresh_step": {"ok": True},
                "rsp_refresh_step": {"ok": True},
                "publish_step": {"ok": True},
                "checks": {
                    "foundation_health": {"status": "FAIL"},
                    "intraday_futures_reconciliation": {"ok": True},
                },
            }
            with patch.object(account_console, "CONTROL_TOWER_PATH", tower_path):
                recovered = account_console.daily_open_recovered_by_newer_state(report)
                effective = account_console.effective_daily_open_status(report)

        self.assertTrue(recovered)
        self.assertEqual(effective, "EVIDENCE_COLLECTION_ONLY")

    def test_daily_open_timeout_is_not_recovered_when_futures_reconciliation_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tower_path = Path(tmp) / "broker_control_tower_latest.json"
            tower_path.write_text(json.dumps({
                "generated_at": "2026-07-21T14:22:24+00:00",
                "accounts": [{"refresh_status": "READY"}],
            }))
            report = {
                "generated_at": "2026-07-21T14:03:13+00:00",
                "capacity_refresh_step": {"ok": True},
                "rsp_refresh_step": {"ok": True},
                "publish_step": {"ok": True},
                "checks": {"intraday_futures_reconciliation": {"ok": False}},
            }
            with patch.object(account_console, "CONTROL_TOWER_PATH", tower_path):
                self.assertFalse(account_console.daily_open_recovered_by_newer_state(report))

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
                {"ticker": "MSFT", "severity": "ACTION", "operator_status": "PAPER_TRACKED"},
                {"ticker": "AAPL", "severity": "ACTION", "operator_status": "IBKR_APPLIED"},
            ]
        }

        counts = account_console.operator_alert_counts(data)

        self.assertEqual(counts["open"], 1)
        self.assertEqual(counts["action"], 1)
        self.assertEqual(counts["watch"], 0)
        self.assertEqual(counts["risk"], 0)
        self.assertEqual(counts["closed"], 4)

    def test_console_health_surfaces_green_and_running_process(self):
        active = {"account_scope": "primary", "account_alias": "primary"}
        snapshot = {"available": True, "account_scope": "primary", "account_alias": "primary"}
        operator_payload = {
            "ok": True,
            "token_present": True,
            "data": {
                "account_context": {"account_scope": "primary", "account_alias": "primary"},
                "account_capacity": {"available_capacity": 50000, "capacity_source": "available_funds"},
            },
        }

        with account_console.WEB_JOBS_LOCK:
            account_console.WEB_JOBS.clear()
        with patch.object(account_console, "latest_ibkr_connection_status", return_value={
            "available": True,
            "connected": True,
            "account_matches": True,
            "status": "CONNECTED",
            "published": True,
        }):
            health = account_console.console_health(active, snapshot, operator_payload)
            rendered = account_console.render_console_health(active, snapshot, operator_payload)

        self.assertEqual(health["level"], "green")
        self.assertIn("health-green", rendered)
        self.assertIn("signal-dot", rendered)
        self.assertIn("sin procesos activos", rendered)

        try:
            with account_console.WEB_JOBS_LOCK:
                account_console.WEB_JOBS["job-test"] = {
                    "job_id": "job-test",
                    "label": "Refresh IBKR",
                    "alias": "primary",
                    "status": "RUNNING",
                    "started_at": account_console.now_iso(),
                }
            with patch.object(account_console, "latest_ibkr_connection_status", return_value={
                "available": True,
                "connected": True,
                "account_matches": True,
                "status": "CONNECTED",
                "published": True,
            }):
                running_health = account_console.console_health(active, snapshot, operator_payload)
                process_panel = account_console.render_active_process_panel()

            self.assertEqual(running_health["level"], "amber")
            self.assertIn("PROCESS_RUNNING", running_health["warnings"])
            self.assertIn("process-panel", process_panel)
            self.assertIn("La consola esta trabajando", process_panel)
            self.assertIn("RUNNING/DONE", process_panel)
        finally:
            with account_console.WEB_JOBS_LOCK:
                account_console.WEB_JOBS.clear()

    def test_post_open_monitor_runs_in_background_without_blocking_console(self):
        active = {"account_scope": "primary", "account_alias": "primary"}
        snapshot = {"available": True, "account_scope": "primary", "account_alias": "primary"}
        operator_payload = {
            "ok": True,
            "cached": False,
            "stale_cache": False,
            "token_present": True,
            "data": {
                "account_context": {"account_scope": "primary", "account_alias": "primary"},
                "account_capacity": {"available_capacity": 50000, "capacity_source": "available_funds"},
            },
        }
        try:
            with account_console.WEB_JOBS_LOCK:
                account_console.WEB_JOBS["monitor-test"] = {
                    "job_id": "monitor-test",
                    "label": "Post-open monitor",
                    "alias": "primary",
                    "status": "RUNNING",
                    "started_at": account_console.now_iso(),
                }
            with patch.object(account_console, "latest_ibkr_connection_status", return_value={
                "available": True,
                "connected": True,
                "account_matches": True,
                "status": "CONNECTED",
                "published": True,
            }):
                health = account_console.console_health(active, snapshot, operator_payload)
                process_panel = account_console.render_active_process_panel()

            self.assertNotIn("PROCESS_RUNNING", health["warnings"])
            self.assertIn("BACKGROUND_MONITOR_RUNNING", health["info"])
            self.assertEqual(health["blocking_jobs"], [])
            self.assertIn("Monitoreo automático activo", process_panel)
            self.assertIn("no bloquea la consola", process_panel)
        finally:
            with account_console.WEB_JOBS_LOCK:
                account_console.WEB_JOBS.clear()

    def test_console_health_keeps_fresh_remote_cache_green(self):
        active = {"account_scope": "primary", "account_alias": "primary"}
        snapshot = {"available": True, "account_scope": "primary", "account_alias": "primary"}
        operator_payload = {
            "ok": True,
            "cached": True,
            "stale_cache": False,
            "token_present": True,
            "cache_age_label": "45s ago",
            "data": {
                "account_context": {"account_scope": "primary", "account_alias": "primary"},
                "account_capacity": {"available_capacity": 50000, "capacity_source": "available_funds"},
            },
        }

        with patch.object(account_console, "latest_ibkr_connection_status", return_value={
            "available": True,
            "connected": True,
            "account_matches": True,
            "status": "CONNECTED",
            "published": True,
        }):
            health = account_console.console_health(active, snapshot, operator_payload)
            rendered = account_console.render_console_health(active, snapshot, operator_payload)

        self.assertEqual(health["level"], "green")
        self.assertEqual(health["warnings"], [])
        self.assertIn("REMOTE_CACHE_FRESH", health["info"])
        self.assertIn("health-green", rendered)

    def test_console_health_keeps_local_core_green_when_remote_cache_context_is_stale(self):
        active = {"account_scope": "remanente", "account_alias": "remanente"}
        snapshot = {"available": True, "account_scope": "", "account_alias": "", "generated_at": "2026-07-13T19:00:00+00:00"}
        operator_payload = {
            "ok": True,
            "cached": True,
            "stale_cache": True,
            "token_present": True,
            "cache_age_label": "33m ago",
            "data": {
                "account_context": {"account_scope": "unknown", "account_alias": "unknown"},
                "account_capacity": {"available_capacity": 20570.57, "capacity_source": "available_funds"},
            },
        }

        with patch.object(account_console, "latest_ibkr_connection_status", return_value={
            "available": True,
            "connected": True,
            "account_matches": True,
            "status": "CONNECTED",
            "published": True,
        }):
            health = account_console.console_health(active, snapshot, operator_payload)
            rendered = account_console.render_console_health(active, snapshot, operator_payload)

        self.assertEqual(health["level"], "green")
        self.assertTrue(health["local_core_ready"])
        self.assertNotIn("GPT_CONTEXT_REFRESH_REQUIRED", health["warnings"])
        self.assertNotIn("REMOTE_CACHE_STALE", health["warnings"])
        self.assertIn("REMOTE_CACHE_STALE_LOCAL_CORE_READY", health["info"])
        self.assertIn("IBKR conectado", rendered)
        self.assertIn("Producción guardada", rendered)

    def test_console_header_separates_connected_from_stale_risk_data(self):
        active = {"account_scope": "retiro", "account_alias": "retiro"}
        with tempfile.TemporaryDirectory() as tmp:
            risk_path = Path(tmp) / "portfolio_risk_latest.json"
            risk_path.write_text(json.dumps({
                "status": "ACTION_REQUIRED",
                "accounts": [{"account_alias": "retiro", "refresh_status": "STALE"}],
                "alerts": [{
                    "account_alias": "retiro",
                    "severity": "HIGH",
                    "title": "Revisar cuenta retiro",
                }],
            }))
            with patch.object(account_console, "PORTFOLIO_RISK_PATH", risk_path):
                state = account_console.console_header_operational_state(active)

        self.assertTrue(state["available"])
        self.assertFalse(state["data_current"])
        self.assertEqual(state["data_label"], "por actualizar")
        self.assertTrue(state["risk_review"])
        self.assertEqual(state["risk_label"], "revisar")

    def test_selected_vs_published_infers_local_account_when_remote_omits_account_fields(self):
        active = {"account_scope": "remanente", "account_alias": "remanente"}
        snapshot = {"available": True, "account_scope": "", "account_alias": ""}
        operator_payload = {"ok": True, "data": {"status": "WAIT_MARKET"}}

        comparison = account_console.selected_vs_published(active, snapshot, operator_payload)
        html = account_console.render_console_context(active, snapshot, operator_payload)

        self.assertEqual(comparison["status"], "LOCAL_CONTEXT_INFERRED")
        self.assertEqual(comparison["display_alias"], "remanente")
        self.assertFalse(comparison["needs_refresh"])
        self.assertIn("remoto sin campo cuenta", html)
        self.assertIn("remanente", html)

    def test_console_actions_uses_inferred_local_account_when_remote_omits_account_fields(self):
        active = {"account_scope": "remanente", "account_alias": "remanente"}
        snapshot = {"available": True, "account_scope": "", "account_alias": ""}
        operator_payload = {"ok": True, "data": {"status": "WAIT_MARKET", "active_alerts": []}}

        html = account_console.render_console_actions(active, snapshot, operator_payload)

        self.assertIn("cuenta=remanente", html)
        self.assertNotIn("cuenta=unknown", html)

    def test_console_v31_payloads_fetches_active_positions_endpoint(self):
        seen = []

        def fake_fetch(path, prefer_cache=False, timeout=account_console.REMOTE_READ_TIMEOUT_SECONDS):
            seen.append(path)
            return {"ok": True, "data": {}}

        with patch.object(account_console, "fetch_remote_json", side_effect=fake_fetch):
            payloads = account_console.console_v31_payloads(prefer_cache=True)

        self.assertIn("active_positions", payloads)
        self.assertIn("/v31_active_position_management", seen)

    def test_console_renders_active_position_management_panel(self):
        snapshot = {
            "available": True,
            "path": "runtime/v28_master_snapshot.json",
            "data": {
                "generated_at": account_console.now_iso(),
                "account_context": {
                    "available": True,
                    "available_funds": 100000,
                    "generated_at": account_console.now_iso(),
                },
                "positions": [
                    {
                        "ticker": "QQQ",
                        "sec_type": "OPT",
                        "right": "P",
                        "strike": 650,
                        "position_size": -1,
                        "entry_credit": 4.0,
                        "option_mark": 1.5,
                        "dte": 12,
                        "delta": -0.12,
                    }
                ],
                "technical_snapshot": {
                    "QQQ": {
                        "ticker": "QQQ",
                        "trend": "BULLISH",
                        "price": 670,
                        "support_level": 640,
                        "gamma_wall": 675,
                    }
                },
            },
        }

        with patch.object(account_console, "console_runtime_position_context", return_value=snapshot["data"]):
            payload = account_console.console_active_position_management(snapshot, {})
            html = account_console.render_active_positions_panel(snapshot, {}, {"account_alias": "primary"})

        self.assertEqual(payload["positions_found"], 1)
        self.assertEqual(payload["positions"][0]["management_action"], "REVIEW_CLOSE_OR_BUY_BACK")
        self.assertIn("Posiciones activas", html)
        self.assertIn("Actualizar cuentas y posiciones IBKR", html)
        self.assertIn("REVIEW_CLOSE_OR_BUY_BACK", html)
        self.assertIn("Revisé cierre", html)
        self.assertIn("Editar tesis y datos de entrada", html)
        self.assertIn('action="/position-context"', html)
        self.assertIn("Riesgo inmediato", html)
        self.assertIn("Seguimiento", html)
        self.assertIn("Ver gestión", html)
        self.assertIn("Ver datos, tesis y registrar gestión", html)
        self.assertIn("Recomendación del motor", html)
        self.assertIn("Ver otras", html)
        self.assertIn("Comprar para cerrar", html)
        self.assertIn("Rolar put en tiempo o strike", html)

    def test_console_renders_manual_gamma_panel(self):
        html = account_console.render_gamma_context_panel()

        self.assertIn("Contexto técnico complementario", html)
        self.assertIn('action="/gamma-context"', html)
        self.assertIn("call_wall", html)
        self.assertIn("gamma_blob", html)

    def test_position_action_queue_prioritizes_decisions_and_keeps_hold_explicit(self):
        urgent = account_console.position_action_queue_metadata({
            "management_action": "REVIEW_ASSIGNMENT_RISK",
            "exit_state": "RISK_REVIEW",
            "dte": 3,
            "reasons": ["Underlying is below the short-put strike; assignment risk needs review."],
            "technical": {"support": 210, "resistance": 225},
        })
        maintain = account_console.position_action_queue_metadata({
            "management_action": "NO_ACTION_RECOMMENDED",
            "exit_state": "MONITOR",
            "reasons": ["Covered call has no deterministic exit trigger; monitor."],
            "technical": {"support": 210},
        })
        completed = account_console.position_action_queue_metadata({
            "management_action": "REVIEW_ROLL",
            "exit_state": "MONITOR",
        }, acknowledged=True)
        expired = account_console.position_action_queue_metadata({
            "management_action": "NO_POSITION",
            "exit_state": "POSITION_EXPIRED",
            "dte": -2,
            "blockers": ["POSITION_EXPIRED"],
        })

        self.assertEqual(urgent["key"], "act")
        self.assertEqual(urgent["checkpoint"], "Antes del vencimiento · 3 DTE")
        self.assertEqual(maintain["key"], "maintain")
        self.assertIn("no tiene un disparador", maintain["why_now"])
        self.assertEqual(completed["key"], "completed")
        self.assertEqual(expired["key"], "data")
        self.assertEqual(expired["label"], "Conciliar con IBKR")
        self.assertNotIn("-2 DTE", expired["checkpoint"])

    def test_console_renders_long_stock_scenario_comparison(self):
        item = {
            "management_alternatives": {
                "recommendation": {
                    "alternative_id": "COLLAR",
                    "label": "Construir collar",
                    "status": "READY_FOR_MANUAL_REVIEW",
                    "confidence": "MEDIUM",
                    "reason": "Ganó la comparación de cinco escenarios.",
                    "contracts": 3,
                    "coverage_pct": 30.0,
                    "contract": {"right": "C", "strike": 65, "expiration": "20260828", "bid": 4.60, "bid_per_contract": 460},
                    "put_contract": {"right": "P", "strike": 62, "expiration": "20260828", "ask": 1.01, "ask_per_contract": 101},
                },
                "alternatives": [
                    {"alternative_id": "COLLAR", "label": "Construir collar", "status": "READY_FOR_MANUAL_REVIEW", "is_primary_management_path": True},
                    {"alternative_id": "REDUCE_25", "label": "Reducir 25%", "status": "READY_FOR_MANUAL_REVIEW"},
                ],
                "strategy_comparison": {
                    "available": True,
                    "shares": 1000,
                    "profile_leaders": {
                        "balanced": {"variant_id": "COLLAR_3", "alternative_id": "COLLAR", "label": "Collar parcial", "contracts": 3, "contract": {"strike": 65, "expiration": "20260828"}, "put_contract": {"strike": 62, "expiration": "20260828"}, "worst_case_pnl": -5375, "flat_pnl": 626},
                        "capital_protection": {"variant_id": "REDUCE_25", "label": "Reducir 25%", "worst_case_pnl": -5062, "flat_pnl": 0},
                    },
                    "variants": [
                        {"alternative_id": "COLLAR", "label": "Collar parcial", "contracts": 3, "contract": {"strike": 65, "expiration": "20260828"}, "put_contract": {"strike": 62, "expiration": "20260828"}, "support_pnl": -1089, "flat_pnl": 626, "resistance_pnl": 8263, "worst_case_pnl": -5375},
                        {"alternative_id": "REDUCE_25", "label": "Reducir 25%", "support_pnl": -1800, "flat_pnl": 0, "resistance_pnl": 8220, "worst_case_pnl": -5062},
                    ],
                },
            },
        }

        html = account_console.render_position_alternatives(item)

        self.assertIn("Mejor balance", html)
        self.assertIn("Mayor protección", html)
        self.assertIn("Ver comparación numérica y supuestos", html)
        self.assertIn("3 contratos · 300 acciones · 30.0%", html)
        self.assertIn("C 65 · vence 28 ago 2026", html)
        self.assertIn("P 62 · vence 28 ago 2026", html)
        self.assertIn("Crédito neto estimado: $3.59 por acción cubierta · $1,077.00 total", html)
        self.assertIn("700 acciones permanecen sin esta estructura", html)
        self.assertIn("C65 / P62 · 28 ago 2026 · 3 contrato(s)", html)

        position_card = account_console.render_position_management_card({
            **item,
            "position_id": "NFLX|STK|0|||",
            "ticker": "NFLX",
            "strategy": "LONG_STOCK",
            "sec_type": "STK",
            "position_size": 1000,
            "management_action": "REVIEW_RISK",
            "exit_state": "RISK_REVIEW",
        })
        self.assertIn("Marcar revisión completada", position_card)
        self.assertIn('name="management_fingerprint"', position_card)
        self.assertNotIn("strike 0.0", position_card)

        refresh_card = account_console.render_position_management_card({
            "position_id": "MSFT|OPT|P|335|20261016|",
            "ticker": "MSFT",
            "strategy": "CASH_SECURED_PUT",
            "sec_type": "OPT",
            "position_size": -1,
            "management_action": "REFRESH_DATA",
            "exit_state": "MONITOR",
            "management_alternatives": {"alternatives": []},
        })
        self.assertIn("requiere datos, no sólo confirmación", refresh_card)
        self.assertIn('href="#position-refresh"', refresh_card)

    def test_console_groups_fully_covered_stock_and_short_call_as_one_structure(self):
        structure = {
            "state": "FULLY_COVERED_CALL",
            "shares": 1000,
            "short_call_contracts": 10,
            "covered_contracts": 10,
            "coverage_pct": 100.0,
            "new_covered_call_capacity_contracts": 0,
            "short_call_legs": [{"contracts": 10, "strike": 76, "expiration": "20260731"}],
        }
        stock = {
            "position_id": "NFLX|STK|0|||",
            "ticker": "NFLX",
            "strategy": "LONG_STOCK",
            "sec_type": "STK",
            "position_size": 1000,
            "management_action": "NO_ACTION_RECOMMENDED",
            "exit_state": "MONITOR",
            "position_structure": structure,
            "management_alternatives": {
                "recommendation": {"alternative_id": "HOLD_MONITOR", "label": "Mantener y monitorear", "status": "READY_FOR_MANUAL_REVIEW"},
                "alternatives": [{"alternative_id": "HOLD_MONITOR", "label": "Mantener y monitorear", "status": "READY_FOR_MANUAL_REVIEW"}],
            },
        }
        call = {
            "position_id": "NFLX|OPT|C|76|20260731|",
            "ticker": "NFLX",
            "strategy": "COVERED_CALL",
            "sec_type": "OPT",
            "right": "C",
            "position_size": -10,
            "strike": 76,
            "expiration": "20260731",
            "management_action": "NO_ACTION_RECOMMENDED",
            "exit_state": "MONITOR",
            "position_structure": structure,
            "management_alternatives": {
                "recommendation": {"alternative_id": "HOLD_MONITOR", "label": "Mantener y monitorear", "status": "READY_FOR_MANUAL_REVIEW"},
                "alternatives": [{"alternative_id": "HOLD_MONITOR", "label": "Mantener y monitorear", "status": "READY_FOR_MANUAL_REVIEW"}],
            },
        }
        payload = {
            "positions": [stock, call],
            "positions_found": 2,
            "positions_requiring_review": 0,
            "risk_review_count": 0,
            "manual_review_required": False,
            "freshness": {"status": "OK"},
            "portfolio_risk": {"status": "OK"},
        }

        html = account_console.render_active_positions_panel({}, {}, {"account_alias": "remanente"}, payload)

        self.assertEqual(html.count('class="alert-card position-card"'), 1)
        self.assertIn("Covered call completo reconocido", html)
        self.assertIn("1000 acciones + 10 calls vendidas", html)
        self.assertIn("10 call(s) C76", html)
        self.assertIn("Capacidad para calls nuevas: 0 contrato(s)", html)
        self.assertIn("Ver gestión de las acciones vinculadas", html)
        self.assertIn("1</strong><small>2 instrumentos", html)

    def test_console_renders_quantitative_covered_call_expiry_comparison(self):
        item = {
            "management_alternatives": {
                "recommendation": {
                    "alternative_id": "HOLD_MONITOR",
                    "label": "Mantener y monitorear",
                    "status": "READY_FOR_MANUAL_REVIEW",
                    "confidence": "HIGH",
                    "reason": "La call permanece al menos 2% OTM.",
                },
                "alternatives": [
                    {"alternative_id": "HOLD_MONITOR", "label": "Mantener y monitorear", "status": "READY_FOR_MANUAL_REVIEW"},
                    {"alternative_id": "BUY_BACK_CALL", "label": "Comprar call para cerrar", "status": "READY_FOR_MANUAL_REVIEW"},
                    {"alternative_id": "ROLL_CALL", "label": "Rolar call", "status": "WAIT_OPTION_CHAIN"},
                ],
                "covered_call_expiry_comparison": {
                    "available": True,
                    "near_expiration": True,
                    "recommended_alternative_id": "HOLD_MONITOR",
                    "recommendation_reason": "La call permanece al menos 2% OTM y su delta no supera 0.25.",
                    "current_contract": {
                        "strike": 76,
                        "dte": 3,
                        "mark": 0.2958,
                        "entry_credit": 0.1031,
                        "distance_to_strike_pct": 3.64,
                        "abs_delta": 0.19,
                    },
                    "variants": [
                        {
                            "alternative_id": "HOLD_MONITOR",
                            "label": "Mantener hasta nueva señal",
                            "remaining_premium_if_worthless_total": 295.8,
                            "distance_to_strike_dollars": 2.67,
                            "distance_to_strike_pct": 3.64,
                            "abs_delta": 0.19,
                        },
                        {
                            "alternative_id": "BUY_BACK_CALL",
                            "label": "Recomprar ahora",
                            "close_cost_total": 295.8,
                            "estimated_premium_pnl_total": -192.7,
                            "premium_capture_pct": -186.91,
                        },
                        {
                            "alternative_id": "ROLL_CALL",
                            "label": "Rolar",
                            "available": False,
                            "reason": "No hay una call posterior líquida al mismo o mayor strike con datos suficientes.",
                        },
                    ],
                },
            },
        }

        html = account_console.render_position_alternatives(item)

        self.assertIn("Decisión próxima al vencimiento", html)
        self.assertIn("Actual: C76 · mark $0.30 · entrada $0.10 · distancia 3.64% · delta 0.19", html)
        self.assertIn("Prima todavía en juego: $295.80", html)
        self.assertIn("Costo estimado de cierre: $295.80", html)
        self.assertIn("P/L de prima estimado: $-192.70", html)
        self.assertIn("No hay una call posterior líquida", html)
        self.assertIn("RECOMENDADA", html)

    def test_latest_master_snapshot_prefers_fresh_decision_desk_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_runtime = account_console.RUNTIME
            account_console.RUNTIME = Path(tmp)
            old = account_console.RUNTIME / "v25_master_snapshot.json"
            fresh = account_console.RUNTIME / "decision_desk_snapshot.json"
            old.write_text(json.dumps({
                "generated_at": "2026-06-11T00:00:00+00:00",
                "options_rows": [{"ticker": "OLD"}],
            }))
            fresh.write_text(json.dumps({
                "generated_at": "2026-07-13T19:00:51+00:00",
                "health": {"snapshot_available": True, "rows_captured": 16},
                "top": [{"ticker": "QQQ"}, {"ticker": "NVDA"}],
            }))
            try:
                snapshot = account_console.latest_master_snapshot()
            finally:
                account_console.RUNTIME = original_runtime

        self.assertTrue(snapshot["available"])
        self.assertTrue(snapshot["path"].endswith("decision_desk_snapshot.json"))
        self.assertEqual(snapshot["rows_found"], 2)

    def test_console_capacity_prefers_newer_remote_over_stale_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_runtime = account_console.RUNTIME
            original_capacity_path = account_console.ACCOUNT_CAPACITY_PATH
            original_active_path = account_console.ACTIVE_PATH
            account_console.RUNTIME = Path(tmp)
            account_console.ACCOUNT_CAPACITY_PATH = Path(tmp) / "ibkr_account_capacity_latest.json"
            account_console.ACTIVE_PATH = Path(tmp) / "ibkr_account_active_profile.json"
            account_console.ACTIVE_PATH.write_text(json.dumps({
                "account_scope": "primary",
                "account_alias": "primary",
            }))
            account_console.ACCOUNT_CAPACITY_PATH.write_text(json.dumps({
                "available": True,
                "account_scope": "primary",
                "account_alias": "primary",
                "available_capacity": 1000,
                "capacity_source": "local_old",
                "generated_at": "2026-07-10T00:00:00+00:00",
            }))
            try:
                capacity = account_console.console_account_capacity(
                    {
                        "data": {
                            "account_scope": "primary",
                            "account_capacity": {
                                "available": True,
                                "account_scope": "primary",
                                "account_alias": "primary",
                                "available_capacity": 5000,
                                "capacity_source": "remote_new",
                                "generated_at": "2026-07-13T19:00:00+00:00",
                            },
                        }
                    },
                    {"available": True},
                )
            finally:
                account_console.RUNTIME = original_runtime
                account_console.ACCOUNT_CAPACITY_PATH = original_capacity_path
                account_console.ACTIVE_PATH = original_active_path

        self.assertEqual(capacity["available_capacity"], 5000)
        self.assertEqual(capacity["capacity_source"], "remote_new")

    def test_console_capacity_falls_back_to_active_account_when_remote_account_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_runtime = account_console.RUNTIME
            original_capacity_path = account_console.ACCOUNT_CAPACITY_PATH
            original_active_path = account_console.ACTIVE_PATH
            account_console.RUNTIME = Path(tmp)
            account_console.ACCOUNT_CAPACITY_PATH = Path(tmp) / "ibkr_account_capacity_latest.json"
            account_console.ACTIVE_PATH = Path(tmp) / "ibkr_account_active_profile.json"
            account_console.ACTIVE_PATH.write_text(json.dumps({
                "account_scope": "remanente",
                "account_alias": "remanente",
            }))
            account_console.ACCOUNT_CAPACITY_PATH.write_text(json.dumps({
                "available": True,
                "available_capacity": 1000,
                "capacity_source": "local",
            }))
            try:
                capacity = account_console.console_account_capacity(
                    {
                        "ok": True,
                        "data": {
                            "account_scope": "unknown",
                            "account_capacity": {"available_capacity": 5000, "capacity_source": "remote"},
                        },
                    },
                    {"available": True},
                )
            finally:
                account_console.RUNTIME = original_runtime
                account_console.ACCOUNT_CAPACITY_PATH = original_capacity_path
                account_console.ACTIVE_PATH = original_active_path

        self.assertEqual(capacity["account_alias"], "remanente")
        self.assertEqual(capacity["account_scope"], "remanente")

    def test_profile_cards_promote_fast_account_publish_and_deep_refresh(self):
        profiles = {"remanente": {"alias": "remanente", "account_scope": "remanente"}}
        html = account_console.render_profile_cards(profiles, {"account_alias": "remanente"})

        self.assertIn('action="/select-refresh"', html)
        self.assertIn("Alinear cuenta rapido", html)
        self.assertIn('action="/bridge-deep"', html)
        self.assertIn("Refresh profundo opciones", html)
        self.assertIn("Avanzado", html)
        self.assertIn("Solo usar cuenta", html)

    def test_profile_cards_tolerate_missing_macos_keychain_command(self):
        profiles = {"remanente": {"alias": "remanente", "account_scope": "remanente"}}
        with patch.object(account_console.subprocess, "run", side_effect=FileNotFoundError("security")):
            html = account_console.render_profile_cards(profiles, {"account_alias": "remanente"})

        self.assertIn("Falta Keychain", html)
        self.assertIn("Alinear cuenta rapido", html)

    def test_render_alert_card_shows_status_badge_and_friendly_actions(self):
        alert = {
            "alert_id": "alert-1",
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "state": "ENTRY_READY",
            "severity": "ACTION",
            "operator_status": "NEW",
            "setup_validity_pct": 92,
            "canslim_score": 78,
            "selected_contract": {
                "strike": 650,
                "dte": 42,
                "delta": -0.18,
                "bid": 4.2,
                "iv": 0.32,
                "volatility_context": {"premium_state": "RICH", "iv": 0.32},
            },
        }

        html = account_console.render_alert_card(alert, account_capacity={"available_capacity": 100000})

        self.assertIn("status-new", html)
        self.assertIn("<em>NEW</em>", html)
        self.assertIn(">Visto</button>", html)
        self.assertIn(">Revisando</button>", html)
        self.assertIn(">Watch</button>", html)
        self.assertIn(">Paper</button>", html)
        self.assertIn(">IBKR aplicada</button>", html)
        self.assertIn(">No aplicada</button>", html)
        self.assertIn(">Missed</button>", html)
        self.assertIn("Guardando revision en produccion", html)
        self.assertIn("Vigencia:", html)
        self.assertIn("Backtesting:", html)
        self.assertIn("why-line", html)
        self.assertIn("alert-checklist", html)
        self.assertIn("Score", html)
        self.assertIn("CANSLIM", html)
        self.assertIn("IV 32%", html)
        self.assertIn("prima RICH", html)
        self.assertIn("Volatilidad", html)

    def test_operator_alerts_hide_wait_and_no_data_from_operable_lane(self):
        operator_payload = {
            "ok": True,
            "data": {
                "active_alerts": [
                    {
                        "alert_id": "wait-1",
                        "ticker": "MSFT",
                        "strategy": "NAKED_PUT",
                        "state": "WAIT_TECHNICAL",
                        "severity": "WATCH",
                        "setup_validity_pct": 99,
                        "operator_status": "NEW",
                    },
                    {
                        "alert_id": "entry-1",
                        "ticker": "QQQ",
                        "strategy": "NAKED_PUT",
                        "state": "ENTRY_READY",
                        "severity": "ACTION",
                        "manual_review_ready": True,
                        "setup_validity_pct": 92,
                        "operator_status": "NEW",
                        "selected_contract": {
                            "strike": 520,
                            "expiration": "20260821",
                            "dte": 39,
                            "delta": -0.2,
                            "bid": 4.1,
                        },
                    },
                ],
                "next_actions": [],
            },
        }

        html = account_console.render_operator_alerts(operator_payload)

        self.assertIn("Alertas Operables", html)
        self.assertIn("1 operable(s)", html)
        self.assertIn("1 diagnostico(s) ocultos", html)
        self.assertIn("<strong>QQQ</strong>", html)
        self.assertNotIn("<strong>MSFT</strong><em>NEW</em>", html)
        self.assertIn("MSFT | WAIT_TECHNICAL", html)

    def test_next_level_console_panels_render_daily_control_surfaces(self):
        active = {"account_scope": "primary", "account_alias": "primary"}
        snapshot = {"available": True, "account_scope": "primary", "account_alias": "primary", "generated_at": account_console.now_iso()}
        operator_payload = {
            "ok": True,
            "token_present": True,
            "data": {
                "status": "WAIT_MARKET",
                "account_context": {"account_scope": "primary", "account_alias": "primary"},
                "account_capacity": {"available_capacity": 50000, "capacity_source": "available_funds"},
                "active_alerts": [
                    {
                        "alert_id": "alert-1",
                        "ticker": "MNQ",
                        "strategy": "INTRADAY_INDEX_FUTURES",
                        "state": "WAIT_MARKET",
                        "severity": "WATCH",
                        "operator_status": "NEW",
                    }
                ],
            },
        }
        reports = {
            "tradingview": {
                "_runtime_available": True,
                "status": "WAITING_FOR_REAL_TRADINGVIEW_EVENTS",
                "total_received_required_event_count": 0,
                "total_required_logical_event_count": 16,
                "real_e2e_confirmed": False,
                "generated_at": account_console.now_iso(),
            },
            "readiness": {
                "_runtime_available": True,
                "status": "WAITING_TV",
                "next_required_action": "Esperar payloads reales de TradingView.",
                "generated_at": account_console.now_iso(),
            },
            "notify": {
                "_runtime_available": True,
                "status": "OK",
                "classification": {"notify_reason": "WAIT_MARKET_SUPPRESSED"},
                "checked_at": account_console.now_iso(),
            },
            "edge": {
                "_runtime_available": True,
                "overall_status": "NEEDS_REVIEW",
                "overall_edge_score": 75.67,
                "recommended_sequence": ["Confirmar eventos reales TradingView."],
                "generated_at": account_console.now_iso(),
            },
            "daily_open": {
                "_runtime_available": True,
                "status": "WAIT_MARKET",
                "generated_at": account_console.now_iso(),
            },
        }

        today = account_console.render_today_panel(active, snapshot, operator_payload, reports)
        modules = account_console.render_module_health(active, snapshot, operator_payload, reports)
        market = account_console.render_market_mode_panel(operator_payload, reports)
        diagnostic = account_console.render_diagnostic_panel(active, reports)

        self.assertIn("Modo Hoy", today)
        self.assertIn("Esperando mercado", today)
        self.assertIn("Semaforo por modulo", modules)
        self.assertIn("TradingView", modules)
        self.assertIn("Modo mercado abierto", market)
        self.assertIn("Futuros vivos", market)
        self.assertIn("Diagnostico completo", diagnostic)
        self.assertIn("Revisar sistema", diagnostic)

    def test_command_center_summarizes_daily_work_in_five_questions(self):
        html = account_console.render_command_center(
            {"account_scope": "primary", "account_alias": "primary"},
            {"available": True, "generated_at": account_console.now_iso()},
            {"ok": True, "data": {"status": "WAIT_MARKET", "active_alerts": []}},
            {"daily_open": {"status": "OK", "generated_at": account_console.now_iso(), "coberturas_rsp": {"ok": True}}},
            {"positions": [], "positions_found": 2, "positions_requiring_review": 1},
            {"alerts": [{"severity": "HIGH", "title": "Concentración elevada", "recommended_action": "Revisar exposición antes de abrir otra posición."}], "alert_counts": {"critical": 0, "high": 1, "watch": 1}},
            {"ibkr": {"chain_has_rsp": True}, "blockers": [], "candidate_count": 2},
        )
        self.assertIn("Riesgo de cartera", html)
        self.assertIn("Oportunidades nuevas", html)
        self.assertIn("Posiciones abiertas", html)
        self.assertIn("Estado operativo", html)
        self.assertIn("Apertura y mercado", html)
        self.assertIn("1 requieren revisión", html)
        self.assertIn("Por qué importa ahora", html)
        self.assertIn("Recomendación", html)
        self.assertIn("Si no la atiendes", html)
        self.assertIn("Revisar exposición antes de abrir otra posición.", html)
        self.assertIn("Antes de abrir posición", html)
        self.assertIn("Próxima revisión", html)
        self.assertIn("Cierre diario", html)
        self.assertIn("Riesgos altos/críticos abiertos", html)
        self.assertIn("Próxima apertura estimada", html)

    def test_daily_task_timing_distinguishes_now_before_entry_and_wait(self):
        now = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
        urgent = account_console.daily_task_timing({"level": "critical", "area": "Riesgo", "when": "Resolver ahora"}, now)
        before_entry = account_console.daily_task_timing({"level": "high", "area": "Riesgo", "when": "Revisar hoy"}, now)
        waiting = account_console.daily_task_timing({"level": "watch", "area": "Sistema", "when": "Esperar"}, now)
        self.assertEqual(urgent["timing_label"], "Actuar ahora")
        self.assertIn("08:15 CDMX", urgent["next_review_label"])
        self.assertEqual(before_entry["timing_label"], "Antes de abrir posición")
        self.assertEqual(before_entry["next_review_label"], "Antes de la próxima entrada")
        self.assertEqual(waiting["timing_label"], "Esperar")
        self.assertIn("CDMX", waiting["next_review_label"])

    def test_daily_close_summarizes_reviewed_postponed_risk_and_resume(self):
        now = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp, patch.object(account_console, "DAILY_TASK_JOURNAL_PATH", Path(tmp) / "daily_tasks.json"):
            account_console.write_json_file(account_console.DAILY_TASK_JOURNAL_PATH, {
                "tasks": {
                    "TASK-done": {"state": "DONE", "updated_at": "2026-09-03T13:00:00+00:00", "title": "Revisada"},
                    "TASK-later": {"state": "POSTPONED", "updated_at": "2026-09-03T13:30:00+00:00", "postponed_until": "2026-09-03T15:00:00+00:00", "title": "Retomar RSP"},
                }
            })
            summary = account_console.daily_close_summary(
                {"visible": [{"title": "Revisar concentración"}]},
                {"alerts": [{"severity": "HIGH", "lifecycle_status": "OPEN"}]},
                now,
            )
        self.assertEqual(summary["reviewed_today"], 1)
        self.assertEqual(summary["postponed_active"], 1)
        self.assertEqual(summary["open_risk_count"], 1)
        self.assertEqual(summary["resume_title"], "Revisar concentración")
        self.assertEqual(summary["status"], "RIESGO ABIERTO")
        self.assertIn("CDMX", summary["next_open"])

    def test_daily_task_journal_reviews_postpones_and_reopens_changed_work(self):
        item = {"level": "high", "area": "Riesgo", "title": "Revisar concentración", "detail": "Concentración 80%", "href": "#riesgo", "when": "Revisar hoy"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(account_console, "DAILY_TASK_JOURNAL_PATH", Path(tmp) / "daily_tasks.json"):
            initial = account_console.daily_task_view([item])
            task = initial["visible"][0]
            account_console.record_daily_task_action(task["task_id"], task["task_fingerprint"], "REVIEW", task["title"])
            reviewing = account_console.daily_task_view([item])
            self.assertEqual(reviewing["visible"][0]["task_state"], "REVIEWING")

            account_console.record_daily_task_action(task["task_id"], task["task_fingerprint"], "POSTPONE", task["title"])
            postponed = account_console.daily_task_view([item])
            self.assertEqual(postponed["visible"], [])
            self.assertEqual(postponed["postponed_count"], 1)

            changed = {**item, "detail": "Concentración aumentó a 90%"}
            reopened = account_console.daily_task_view([changed])
            self.assertEqual(reopened["visible"][0]["task_state"], "NEW")
            self.assertEqual(reopened["postponed_count"], 0)

            changed_task = reopened["visible"][0]
            account_console.record_daily_task_action(changed_task["task_id"], changed_task["task_fingerprint"], "DONE", changed_task["title"])
            attended = account_console.daily_task_view([changed])
            self.assertEqual(attended["visible"], [])
            self.assertEqual(attended["attended_count"], 1)

    def test_unified_local_console_renders_v31_manual_review_surfaces(self):
        payloads = {
            "executive": {
                "ok": True,
                "data": {
                    "status": "READY_FOR_DECISION_REVIEW",
                    "operational_readiness": "READY_FOR_DECISION_REVIEW",
                    "answer_to_user": "Motor corrio: hay setups para revision manual.",
                    "summary": {"entry_ready": 1, "risk_blocked": 1, "wait_options_data": 0, "wait_technical": 0},
                    "blocked_cause_groups": [
                        {"cause": "broker_capacity", "count": 1, "tickers": ["MSFT"], "examples": [{"reason": "faltante=11500"}]},
                    ],
                },
            },
            "rankings": {
                "ok": True,
                "data": {
                    "top_recommendations": [
                        {
                            "ticker": "QQQ",
                            "strategy": "NAKED_PUT",
                            "final_state": "ENTRY_READY",
                            "manual_review_ready": True,
                            "selected_contract": {
                                "strike": 650,
                                "expiration": "20260821",
                                "dte": 46,
                                "bid": 5.99,
                                "ask": 6.05,
                                "mid": 6.02,
                                "delta": -0.14,
                                "spread_pct": 1.0,
                            },
                        }
                    ],
                    "blocked_or_waiting": [
                        {
                            "ticker": "MSFT",
                            "strategy": "NAKED_PUT",
                            "final_state": "RISK_BLOCKED",
                            "primary_block_reason": "Broker check: faltante=11500",
                            "selected_contract": {"strike": 365},
                        }
                    ],
                },
            },
            "reviews": {"ok": True, "data": {"recent_reviews": []}},
            "learning": {"ok": True, "data": {"by_manual_status": {"WATCHLIST": 2}, "evaluated_count": 2}},
            "performance": {"ok": True, "data": {"summary": {"evaluated_signal_count": 2}}},
        }

        executive_html = account_console.render_v31_executive_panel(payloads)
        manual_html = account_console.render_v31_manual_review_panel(payloads)
        learning_html = account_console.render_v31_learning_panel(payloads)

        self.assertIn("Estado Ejecutivo V31", executive_html)
        self.assertIn("broker_capacity", executive_html)
        self.assertIn("Revision Manual V31", manual_html)
        self.assertIn("APPROVED_FOR_MANUAL_TRADE", manual_html)
        self.assertIn("/manual-review-event", manual_html)
        self.assertIn("No accionables descartadas del inbox", manual_html)
        self.assertIn("Broker check: faltante=11500", manual_html)
        self.assertNotIn('<input name="ticker" value="MSFT"', manual_html)
        self.assertIn("Learning y Performance", learning_html)

    def test_local_question_answer_uses_v31_payload_without_inventing(self):
        payloads = {
            "executive": {
                "ok": True,
                "data": {
                    "answer_to_user": "Motor corrio: sin ENTRY_READY.",
                    "blocked_cause_groups": [{"cause": "options_data", "count": 2, "tickers": ["TLT"]}],
                },
            },
            "rankings": {
                "ok": True,
                "data": {
                    "top_recommendations": [],
                    "blocked_or_waiting": [
                        {
                            "ticker": "MSFT",
                            "strategy": "NAKED_PUT",
                            "final_state": "RISK_BLOCKED",
                            "primary_block_reason": "Delta fuera de rango",
                            "selected_contract": {"strike": 365, "expiration": "20260821"},
                        }
                    ],
                },
            },
        }

        answer = account_console.local_question_answer("por que esta bloqueado MSFT", payloads)

        self.assertIn("MSFT", answer)
        self.assertIn("RISK_BLOCKED", answer)
        self.assertIn("Delta fuera de rango", answer)
        self.assertIn("No autoriza ordenes", answer)

    def test_remote_cache_keeps_multiple_console_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_path = account_console.REMOTE_CACHE_PATH
            account_console.REMOTE_CACHE_PATH = Path(tmp) / "remote_cache.json"
            try:
                account_console.write_remote_cache(
                    "/gpt_v31_executive_status?limit=8",
                    {"ok": True, "token_present": True, "url": "https://example.test/a", "data": {"status": "OK"}},
                )
                account_console.write_remote_cache(
                    "/gpt_v31_daily_rankings",
                    {"ok": True, "token_present": True, "url": "https://example.test/b", "data": {"top_recommendations": []}},
                )

                executive = account_console.read_remote_cache("/gpt_v31_executive_status?limit=8")
                rankings = account_console.read_remote_cache("/gpt_v31_daily_rankings")

                self.assertEqual(executive["data"]["status"], "OK")
                self.assertEqual(rankings["data"]["top_recommendations"], [])
                self.assertTrue(executive["cached"])
                self.assertTrue(rankings["cached"])
            finally:
                account_console.REMOTE_CACHE_PATH = original_path

    def test_remote_cache_concurrent_writes_remain_valid_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_path = account_console.REMOTE_CACHE_PATH
            account_console.REMOTE_CACHE_PATH = Path(tmp) / "remote_cache.json"
            try:
                def write(index):
                    account_console.write_remote_cache(
                        f"/endpoint/{index}",
                        {"ok": True, "token_present": True, "url": "https://example.test", "data": {"index": index}},
                    )

                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    list(executor.map(write, range(24)))
                payload = json.loads(account_console.REMOTE_CACHE_PATH.read_text())
                self.assertEqual(len(payload["entries"]), 24)
            finally:
                account_console.REMOTE_CACHE_PATH = original_path

    def test_cache_first_render_returns_stale_cache_without_network_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_path = account_console.REMOTE_CACHE_PATH
            account_console.REMOTE_CACHE_PATH = Path(tmp) / "remote_cache.json"
            account_console.REMOTE_CACHE_PATH.write_text(json.dumps({
                "cache_version": "stock_ultimus_console_remote_cache_v2",
                "cached_at": "2026-01-01T00:00:00+00:00",
                "entries": {
                    "/slow-endpoint": {
                        "cached_at": "2026-01-01T00:00:00+00:00",
                        "result": {
                            "ok": True,
                            "error": "",
                            "token_present": True,
                            "url": "https://example.test/slow-endpoint",
                            "data": {"status": "CACHED"},
                        },
                    }
                },
            }))
            try:
                with patch.object(account_console.urllib.request, "urlopen", side_effect=AssertionError("network called")):
                    result = account_console.fetch_remote_json("/slow-endpoint", prefer_cache=True)

                self.assertEqual(result["data"]["status"], "CACHED")
                self.assertTrue(result["stale_cache"])
                self.assertEqual(result["live_error"], "CACHE_FIRST_CONSOLE_RENDER")
            finally:
                account_console.REMOTE_CACHE_PATH = original_path

    def test_stale_remote_positions_do_not_resurrect_closed_local_position(self):
        snapshot = {"available": True, "data": {"positions": []}}
        remote = {
            "active_positions": {
                "ok": True,
                "cached": True,
                "stale_cache": True,
                "data": {
                    "position_management_version": "active_position_management_v7",
                    "generated_at": "2026-08-03T14:57:46+00:00",
                    "positions_found": 1,
                    "positions": [{"ticker": "RSP", "position_id": "OLD-RSP-CALL"}],
                },
            }
        }
        with patch.object(account_console, "console_runtime_position_context", return_value={"positions": []}):
            payload = account_console.console_active_position_management(snapshot, remote)

        self.assertNotEqual(payload.get("source"), "remote_v31_active_position_management")
        self.assertEqual(payload.get("stale_remote_position_count_ignored"), 1)
        self.assertEqual(payload.get("position_data_warning"), "STALE_REMOTE_POSITIONS_IGNORED_REFRESH_IBKR")

    def test_failed_current_broker_refresh_suppresses_historical_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tower_path = Path(tmp) / "broker_control_tower_latest.json"
            alerts_path = Path(tmp) / "active_position_state_alerts.json"
            tower_path.write_text(json.dumps({
                "generated_at": account_console.now_iso(),
                "status": "WAIT_ACCOUNT_REFRESH",
                "accounts": [
                    {"account_alias": "remanente", "refresh_status": "BROKER_REFRESH_FAILED"},
                    {"account_alias": "retiro", "refresh_status": "BROKER_REFRESH_FAILED"},
                    {"account_alias": "marginal", "refresh_status": "BROKER_REFRESH_FAILED"},
                ],
            }))
            historical_context = {
                "generated_at": "2026-08-07T18:00:00+00:00",
                "positions": [{
                    "ticker": "MNQ",
                    "sec_type": "FUT",
                    "position_size": 1,
                    "account_alias": "remanente",
                }],
            }
            snapshot = {
                "available": True,
                "data": historical_context,
            }
            with (
                patch.object(account_console, "CONTROL_TOWER_PATH", tower_path),
                patch.object(account_console, "POSITION_STATE_ALERTS_PATH", alerts_path),
                patch.object(account_console, "console_runtime_position_context", return_value=historical_context),
            ):
                payload = account_console.console_active_position_management(snapshot, {})

        self.assertEqual(payload.get("status"), "WAIT_ACCOUNT_REFRESH")
        self.assertEqual(payload.get("positions_found"), 0)
        self.assertEqual(payload.get("positions"), [])
        self.assertEqual(payload.get("historical_positions_suppressed"), 1)
        self.assertEqual(payload.get("position_data_warning"), "BROKER_REFRESH_FAILED_POSITIONS_UNCONFIRMED")
        self.assertTrue(payload.get("state_change_alerts", {}).get("update_skipped"))
        self.assertEqual(payload.get("portfolio_risk", {}).get("status"), "UNCONFIRMED")
        html = account_console.render_active_positions_panel(
            snapshot,
            {},
            {"account_alias": "remanente"},
            payload=payload,
        )
        self.assertIn("Posiciones sin confirmar", html)
        self.assertIn("Historial de estados en pausa", html)
        self.assertNotIn("Hay posiciones que requieren revisión manual", html)
        self.assertNotIn("Cambios de estado detectados", html)

    def test_console_last_action_status_distinguishes_partial_bridge_refresh(self):
        result = {
            "returncode": 1,
            "partial_refresh_ok": True,
            "operator_status": "PARTIAL_REFRESH_OK",
            "stdout_tail": "BRIDGE_TIMEOUT",
        }

        self.assertIn("PARCIAL", account_console.console_last_action_status(result))
        self.assertIn("contexto fallback", account_console.console_last_action_summary(result))

        legacy_result = {
            "returncode": 1,
            "stdout_tail": "status: BRIDGE_TIMEOUT\n--- account context fallback ---\nstatus: FALLBACK_PUBLISHED\nok: True\n",
        }

        self.assertIn("PARCIAL", account_console.console_last_action_status(legacy_result))

    def test_notification_test_panel_exposes_preview_and_safe_test_actions(self):
        html = account_console.render_notification_test_panel()

        self.assertIn("Prueba de notificaciones", html)
        self.assertIn('action="/notification-preview"', html)
        self.assertIn('action="/notification-test-email"', html)
        self.assertIn('action="/notification-test-push"', html)
        self.assertIn('action="/macos-notification-test"', html)
        self.assertIn('action="/macos-notification-toggle"', html)
        self.assertIn("riesgos HIGH/CRITICAL", html)
        self.assertIn("No autoriza ordenes", html)

    def test_remote_chris_ia_futures_feed_is_counted_and_promotes_fresh_entry(self):
        received_at = datetime.now(timezone.utc).isoformat()
        operator = {"ok": True, "data": {"active_alerts": []}}
        payloads = {
            "signal_events": {"ok": True, "data": {"events": [
                {
                    "event_id": "TV-CHRIS-ENTRY",
                    "accepted_for_engine": True,
                    "ticker": "USTEC.F",
                    "strategy_context": "CHRIS_IA_REVERSAL_PRO",
                    "event": "ENTRY",
                    "event_code": "CHRIS_IA_USTECF_SHORT_ENTRY_15",
                    "breakout_direction": "SHORT",
                    "score": 92,
                    "received_at": received_at,
                },
                {
                    "event_id": "TV-NATIVE-SNAPSHOT",
                    "accepted_for_engine": True,
                    "ticker": "MNQ1!",
                    "strategy_context": "INTRADAY_INDEX_FUTURES",
                    "event": "SESSION_SNAPSHOT",
                    "received_at": received_at,
                },
            ]}},
            "futures_daily": {"ok": True, "data": {"summary": {"total_events": 0}}},
        }

        merged = account_console.merge_remote_futures_into_operator(operator, payloads)
        intraday = merged["data"]["intraday_futures"]
        alerts = merged["data"]["active_alerts"]

        self.assertEqual(intraday["daily_summary"]["received"], 2)
        self.assertEqual(intraday["daily_summary"]["accepted"], 2)
        self.assertEqual(intraday["daily_summary"]["entry"], 1)
        self.assertEqual(intraday["daily_summary"]["snapshot"], 1)
        self.assertTrue(intraday["daily_summary"]["pipeline_mismatch"])
        self.assertEqual(intraday["status"], "PIPELINE_MISMATCH")
        self.assertEqual(alerts[0]["state"], "MANUAL_REVIEW")
        self.assertTrue(account_console.is_intraday_futures_alert(alerts[0]))

    def test_expired_futures_entry_remains_visible_as_compact_daily_reference(self):
        received_at = datetime.now(timezone.utc).isoformat()
        operator = {"ok": True, "data": {"active_alerts": []}}
        payloads = {
            "signal_events": {"ok": True, "data": {"events": [{
                "event_id": "TV-US500-ENTRY",
                "accepted_for_engine": True,
                "ticker": "US500F",
                "strategy_context": "CHRIS_IA_REVERSAL_PRO",
                "event": "ENTRY",
                "event_code": "CHRIS_IA_US500F_SHORT_ENTRY_15",
                "received_at": received_at,
            }]}},
            "futures_daily": {"ok": True, "data": {
                "summary": {"total_events": 1},
                "latest_events": [{
                    "ticker": "US500F",
                    "event": "ENTRY",
                    "event_code": "CHRIS_IA_US500F_SHORT_ENTRY_15",
                    "direction": "SHORT",
                    "entry_price": 7533.7,
                    "stop_price": 7542.59,
                    "tp1_price": 7524.81,
                    "tp2_price": 7515.93,
                    "reference_levels_provisional": True,
                    "received_at": received_at,
                }],
            }},
        }

        merged = account_console.merge_remote_futures_into_operator(operator, payloads)
        latest = merged["data"]["intraday_futures"]["daily_summary"]["latest_signal"]
        html = account_console.render_intraday_futures_alerts([], merged)

        self.assertEqual(latest["ticker"], "US500F")
        self.assertEqual(latest["tp2_price"], 7515.93)
        self.assertIn("US500F · SHORT", html)
        self.assertIn("Stop y targets estimados por ATR", html)

    def test_ready_control_tower_empty_positions_remove_closed_snapshot_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            active_path = runtime / "ibkr_account_active_profile.json"
            active_path.write_text(json.dumps({"account_alias": "remanente", "account_scope": "remanente"}))
            (runtime / "unrelated_newer_status.json").write_text(json.dumps({"generated_at": "2026-07-22T01:00:00+00:00"}))
            (runtime / "broker_control_tower_latest.json").write_text(json.dumps({
                "generated_at": "2026-07-22T00:05:20+00:00",
                "accounts": [{
                    "account_alias": "remanente",
                    "refresh_status": "READY",
                    "generated_at": "2026-07-22T00:05:05+00:00",
                    "positions": [],
                }],
                "consolidated_positions": [],
            }))
            snapshot = {"data": {
                "generated_at": "2026-07-21T19:53:00+00:00",
                "positions": [{"ticker": "MNQ", "sec_type": "FUT", "position_size": -1}],
            }}
            with patch.object(account_console, "RUNTIME", runtime), patch.object(
                account_console, "ACTIVE_PATH", active_path
            ):
                context = account_console.console_runtime_position_context(snapshot)

        self.assertEqual(context["positions"], [])
        self.assertEqual(context["generated_at"], "2026-07-22T00:05:05+00:00")
        self.assertEqual(context["position_data_source"], "BROKER_CONTROL_TOWER")

    def test_ready_control_tower_exposes_positions_from_every_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            active_path = runtime / "ibkr_account_active_profile.json"
            active_path.write_text(json.dumps({"account_alias": "remanente", "account_scope": "remanente"}))
            (runtime / "broker_control_tower_latest.json").write_text(json.dumps({
                "status": "READY",
                "generated_at": "2026-08-08T15:16:05+00:00",
                "accounts": [
                    {
                        "account_alias": "remanente",
                        "account_scope": "remanente",
                        "refresh_status": "READY",
                        "generated_at": "2026-08-08T15:15:59+00:00",
                        "positions": [{"ticker": "MNQ", "security_type": "FUT", "quantity": -1}],
                    },
                    {
                        "account_alias": "retiro",
                        "account_scope": "retiro",
                        "refresh_status": "READY",
                        "generated_at": "2026-08-08T15:16:04+00:00",
                        "positions": [{"ticker": "MES", "security_type": "FUT", "quantity": 1}],
                    },
                ],
            }))
            with patch.object(account_console, "RUNTIME", runtime), patch.object(
                account_console, "ACTIVE_PATH", active_path
            ):
                context = account_console.console_runtime_position_context({"data": {"positions": []}})

        self.assertEqual({row["ticker"] for row in context["positions"]}, {"MNQ", "MES"})
        self.assertEqual({row["account_alias"] for row in context["positions"]}, {"remanente", "retiro"})
        self.assertEqual(context["position_data_scope"], "ALL_READY_ACCOUNTS")


if __name__ == "__main__":
    unittest.main()
