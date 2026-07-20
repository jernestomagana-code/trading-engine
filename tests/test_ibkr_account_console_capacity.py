import importlib.util
import json
import sys
import tempfile
import unittest
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
        self.assertIn("IBKR OK", rendered)
        self.assertIn("Producción guardada", rendered)

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

        payload = account_console.console_active_position_management(snapshot, {})
        html = account_console.render_active_positions_panel(snapshot, {}, {"account_alias": "primary"})

        self.assertEqual(payload["positions_found"], 1)
        self.assertEqual(payload["positions"][0]["management_action"], "REVIEW_CLOSE_OR_BUY_BACK")
        self.assertIn("Posiciones activas", html)
        self.assertIn("Refresh posiciones IBKR", html)
        self.assertIn("REVIEW_CLOSE_OR_BUY_BACK", html)
        self.assertIn("Revisé cierre", html)
        self.assertIn("Editar tesis y datos de entrada", html)
        self.assertIn('action="/position-context"', html)
        self.assertIn("Riesgo inmediato", html)
        self.assertIn("Seguimiento", html)
        self.assertIn("Ver detalles y registrar gestión", html)
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

    def test_console_renders_long_stock_scenario_comparison(self):
        item = {
            "management_alternatives": {
                "recommendation": {
                    "alternative_id": "COVERED_CALL_PARTIAL",
                    "label": "Covered call parcial",
                    "status": "READY_FOR_MANUAL_REVIEW",
                    "confidence": "MEDIUM",
                    "reason": "Ganó la comparación de cinco escenarios.",
                    "contracts": 3,
                    "coverage_pct": 30.0,
                    "contract": {"right": "C", "strike": 65, "expiration": "20260828", "premium_per_contract": 475},
                },
                "alternatives": [
                    {"alternative_id": "COVERED_CALL_PARTIAL", "label": "Covered call parcial", "status": "READY_FOR_MANUAL_REVIEW", "is_primary_management_path": True},
                    {"alternative_id": "REDUCE_25", "label": "Reducir 25%", "status": "READY_FOR_MANUAL_REVIEW"},
                ],
                "strategy_comparison": {
                    "available": True,
                    "profile_leaders": {
                        "balanced": {"variant_id": "COVERED_CALL_PARTIAL_3", "label": "Covered call parcial", "worst_case_pnl": -5375, "flat_pnl": 626},
                        "capital_protection": {"variant_id": "REDUCE_25", "label": "Reducir 25%", "worst_case_pnl": -5062, "flat_pnl": 0},
                    },
                    "variants": [
                        {"alternative_id": "COVERED_CALL_PARTIAL", "label": "Covered call parcial", "contracts": 3, "support_pnl": -1089, "flat_pnl": 626, "resistance_pnl": 8263, "worst_case_pnl": -5375},
                        {"alternative_id": "REDUCE_25", "label": "Reducir 25%", "support_pnl": -1800, "flat_pnl": 0, "resistance_pnl": 8220, "worst_case_pnl": -5062},
                    ],
                },
            },
        }

        html = account_console.render_position_alternatives(item)

        self.assertIn("Mejor balance", html)
        self.assertIn("Mayor protección", html)
        self.assertIn("Ver comparación numérica y supuestos", html)
        self.assertIn("3 contrato(s) · 30.0% de la posición", html)

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
        self.assertIn("No autoriza ordenes", html)


if __name__ == "__main__":
    unittest.main()
