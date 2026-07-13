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

    def test_profile_cards_promote_one_click_account_refresh(self):
        profiles = {"remanente": {"alias": "remanente", "account_scope": "remanente"}}
        html = account_console.render_profile_cards(profiles, {"account_alias": "remanente"})

        self.assertIn('action="/select-refresh"', html)
        self.assertIn("Alinear cuenta + Refresh IBKR", html)
        self.assertIn("Avanzado", html)
        self.assertIn("Solo usar cuenta", html)

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


if __name__ == "__main__":
    unittest.main()
