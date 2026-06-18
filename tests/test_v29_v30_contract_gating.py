import unittest
import sys
import types
from unittest.mock import patch


def _install_import_stubs():
    fastapi = types.ModuleType("fastapi")
    responses = types.ModuleType("fastapi.responses")
    pydantic = types.ModuleType("pydantic")
    requests = types.ModuleType("requests")

    class FastAPI:
        def __init__(self, *args, **kwargs):
            self.router = types.SimpleNamespace(routes=[])

        def get(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def on_event(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def add_api_route(self, *args, **kwargs):
            self.router.routes.append(types.SimpleNamespace(path=args[0] if args else None))

    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    class HTMLResponse(str):
        pass

    class BaseModel:
        pass

    def Field(default=None, **kwargs):
        return default

    def Header(default=None, **kwargs):
        return default

    fastapi.FastAPI = FastAPI
    fastapi.Request = object
    fastapi.Header = Header
    fastapi.HTTPException = HTTPException
    responses.HTMLResponse = HTMLResponse
    pydantic.BaseModel = BaseModel
    pydantic.Field = Field
    requests.get = lambda *args, **kwargs: None
    requests.post = lambda *args, **kwargs: None

    sys.modules.setdefault("fastapi", fastapi)
    sys.modules.setdefault("fastapi.responses", responses)
    sys.modules.setdefault("pydantic", pydantic)
    sys.modules.setdefault("requests", requests)


_install_import_stubs()

from app import main


def _master_snapshot(rows):
    return {
        "path": "unit-test-master.json",
        "rows": rows,
        "technical": {
            "QQQ": {
                "ticker": "QQQ",
                "trend": "BULLISH",
                "score": 80,
            }
        },
        "data": {
            "market": {
                "is_regular_market_open": True,
                "options_bidask_expected": True,
                "label": "REGULAR_OPTIONS_SESSION",
            }
        },
    }


class V29V30ContractGatingTests(unittest.TestCase):
    def test_confirmed_technical_with_incomplete_option_data_waits_for_options(self):
        incomplete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": None,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=_master_snapshot([incomplete_row])):
            decision = main._v29_decide_ticker("QQQ")

        self.assertEqual(decision["final_state"], "WAIT_OPTIONS_DATA")
        self.assertFalse(decision["can_operate"])
        self.assertFalse(decision["manual_review_ready"])
        self.assertIn("delta", decision["best_row_quality"]["missing"])
        self.assertIn("delta", decision["required_missing_fields"])
        self.assertEqual(decision["selected_contract"]["delta"], None)
        self.assertFalse(decision["selected_contract"]["manual_review_ready"])

    def test_complete_option_data_can_only_become_manual_review_ready(self):
        complete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": -0.20,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=_master_snapshot([complete_row])):
            decision = main._v29_decide_ticker("QQQ")

        self.assertEqual(decision["final_state"], "ENTRY_READY")
        self.assertFalse(decision["can_operate"])
        self.assertTrue(decision["manual_review_ready"])
        self.assertTrue(decision["not_order_instruction"])
        self.assertEqual(decision["best_row_quality"]["missing"], [])
        self.assertEqual(decision["required_missing_fields"], [])
        self.assertEqual(decision["selected_contract"]["strike"], 710)
        self.assertEqual(decision["selected_contract"]["delta"], -0.20)
        self.assertTrue(decision["selected_contract"]["manual_review_ready"])
        self.assertFalse(decision["selected_contract"]["can_operate"])


class V31CanonicalDecisionTests(unittest.TestCase):
    def test_v31_incomplete_option_data_uses_wait_options_blocker(self):
        incomplete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": None,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=_master_snapshot([incomplete_row])):
            decision = main._v31_canonical_decision("QQQ")

        self.assertEqual(decision["engine"], "V31_CANONICAL_DECISION_ENGINE")
        self.assertEqual(decision["decision_version"], "v31_canonical_decision_engine")
        self.assertEqual(decision["final_state"], "WAIT_OPTIONS_DATA")
        self.assertEqual(decision["main_blocker"], "WAIT_OPTIONS_DATA")
        self.assertIn("WAIT_OPTIONS_DATA", decision["blockers"])
        self.assertIn("MISSING_DELTA", decision["blockers"])
        self.assertIn("delta", decision["required_missing_fields"])
        self.assertEqual(decision["construction_status"], "WAIT_OPTIONS_DATA")
        self.assertEqual(decision["risk_status"], "NOT_EVALUATED")
        self.assertEqual(decision["portfolio_status"], "NOT_EVALUATED")
        self.assertFalse(decision["manual_review_ready"])
        self.assertFalse(decision["can_operate"])
        self.assertTrue(decision["not_order_instruction"])

    def test_v31_complete_option_data_is_manual_review_only_entry_ready(self):
        complete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": -0.20,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=_master_snapshot([complete_row])):
            decision = main._v31_canonical_decision("QQQ")

        self.assertEqual(decision["final_state"], "ENTRY_READY")
        self.assertEqual(decision["blockers"], [])
        self.assertIsNone(decision["main_blocker"])
        self.assertTrue(decision["manual_review_ready"])
        self.assertFalse(decision["can_operate"])
        self.assertTrue(decision["not_order_instruction"])
        self.assertEqual(decision["risk_status"], "PASS")
        self.assertEqual(decision["portfolio_status"], "PASS")
        self.assertEqual(decision["technical_status"], "CONFIRMED")
        self.assertEqual(decision["construction_status"], "CONTRACT_SELECTED")
        self.assertEqual(decision["selected_contract"]["delta"], -0.20)

    def test_v31_normalizes_wait_market_open_to_wait_market(self):
        complete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": -0.20,
        }
        market_closed = _master_snapshot([complete_row])
        market_closed["data"]["market"] = {
            "is_regular_market_open": False,
            "options_bidask_expected": False,
            "label": "CLOSED",
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=market_closed):
            decision = main._v31_canonical_decision("QQQ")

        self.assertEqual(decision["source_decision"]["final_state"], "WAIT_MARKET_OPEN")
        self.assertEqual(decision["final_state"], "WAIT_MARKET")
        self.assertEqual(decision["main_blocker"], "WAIT_MARKET")
        self.assertIn("WAIT_MARKET", decision["blockers"])
        self.assertFalse(decision["manual_review_ready"])
        self.assertFalse(decision["can_operate"])

    def test_v31_system_status_uses_canonical_summary_and_endpoints(self):
        incomplete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": None,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=_master_snapshot([incomplete_row])):
            status = main._v31_system_status_payload(["QQQ"])

        self.assertEqual(status["engine"], "V31_CANONICAL_DECISION_ENGINE")
        self.assertEqual(status["canonical_source"], "V31")
        self.assertEqual(status["legacy_source"], "V29_FINAL_DECISION_QUALITY_ENGINE")
        self.assertEqual(status["summary"]["wait_options_data"], 1)
        self.assertEqual(status["summary"]["manual_review_ready"], 0)
        self.assertEqual(status["summary"]["can_operate"], 0)
        self.assertEqual(status["endpoints"]["ingest"], "/v31_ingest_snapshot")
        self.assertEqual(status["endpoints"]["pipeline_status"], "/v31_data_pipeline_status")
        self.assertEqual(status["endpoints"]["gpt_trade_decision_example"], "/gpt_v31_trade_decision/QQQ")
        self.assertEqual(status["decisions"][0]["final_state"], "WAIT_OPTIONS_DATA")
        self.assertTrue(status["not_order_instruction"])

    def test_v31_dashboard_points_to_canonical_routes(self):
        complete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": -0.20,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=_master_snapshot([complete_row])):
            html = main._v31_dashboard_html(["QQQ"])

        self.assertIn("V31 Canonical Decision Engine", html)
        self.assertIn("/v31_system_status", html)
        self.assertIn("/gpt_v31_trade_decision/QQQ", html)
        self.assertIn("/v31_decision/QQQ", html)
        self.assertIn("Can Operate", html)
        self.assertIn("ENTRY_READY", html)

    def test_v31_ingest_snapshot_reuses_master_storage_contract(self):
        saved = {
            "rows_found": 1,
            "technical_available": True,
            "tickers_detected": ["QQQ"],
            "received_at": "2026-06-14T00:00:00+00:00",
            "source": "UNIT_TEST",
        }

        with patch.object(main, "_v28_write_master", return_value=saved), patch.object(
            main,
            "_v31_persist_durable_snapshot",
            return_value={"saved": True, "status": "SAVED"},
        ):
            result = main._v31_ingest_snapshot_payload({
                "source": "UNIT_TEST",
                "options_rows": [],
                "technical_snapshot": {},
            })

        self.assertEqual(result["engine"], "V31_CANONICAL_SNAPSHOT_INGEST")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["rows_found"], 1)
        self.assertTrue(result["technical_available"])
        self.assertEqual(result["tickers_detected"], ["QQQ"])
        self.assertEqual(result["v31_status"], "/v31_system_status")
        self.assertEqual(result["v31_pipeline_status"], "/v31_data_pipeline_status")
        self.assertTrue(result["durable_storage"]["saved"])
        self.assertTrue(result["not_order_instruction"])

    def test_v31_durable_payload_excludes_unapproved_account_context(self):
        durable = main._v31_canonical_durable_payload({
            "source": "UNIT_TEST",
            "options_rows": [{"ticker": "QQQ", "strike": 700}],
            "technical_snapshot": {"QQQ": {"score": 80}},
            "market": {"is_regular_market_open": True},
            "account_id": "SENSITIVE",
            "positions": [{"ticker": "TLT", "size": 700}],
        })

        self.assertEqual(durable["source"], "UNIT_TEST")
        self.assertTrue(durable["not_order_instruction"])
        self.assertNotIn("account_id", durable)
        self.assertNotIn("positions", durable)

    def test_v31_persist_uses_singleton_supabase_row(self):
        snapshot = {
            "source": "UNIT_TEST",
            "generated_at": main._v29_now(),
            "received_at": main._v29_now(),
            "options_rows": [{"ticker": "QQQ", "strike": 700}],
            "technical_snapshot": {"QQQ": {"score": 80}},
            "market": {"is_regular_market_open": False},
            "account_id": "SENSITIVE",
        }

        with patch.object(
            main,
            "supabase_upsert_row",
            return_value={"enabled": True, "saved": True, "status_code": 201},
        ) as upsert:
            result = main._v31_persist_durable_snapshot(snapshot)

        table, row, conflict_key = upsert.call_args.args
        self.assertEqual(table, "stock_ultimus_v31_snapshots")
        self.assertEqual(row["snapshot_id"], "canonical")
        self.assertEqual(conflict_key, "snapshot_id")
        self.assertNotIn("account_id", row["snapshot"])
        self.assertTrue(row["not_order_instruction"])
        self.assertTrue(result["saved"])

    def test_v31_restore_fresh_durable_snapshot_writes_runtime_master(self):
        snapshot = {
            "source": "SUPABASE_TEST",
            "generated_at": main._v29_now(),
            "received_at": main._v29_now(),
            "options_rows": [{"ticker": "QQQ", "strike": 700}],
            "technical_snapshot": {"QQQ": {"score": 80}},
            "market": {"is_regular_market_open": False},
        }
        saved = {
            **snapshot,
            "rows_found": 1,
            "technical_available": True,
            "received_at": main._v29_now(),
        }

        with patch.object(main, "supabase_enabled", return_value=True), patch.object(
            main,
            "supabase_fetch_single_row",
            return_value={"snapshot": snapshot, "updated_at": main._v29_now()},
        ), patch.object(main, "_v28_write_master", return_value=saved) as write_master:
            result = main._v31_restore_durable_snapshot(force=True)

        self.assertTrue(result["restored"])
        self.assertEqual(result["status"], "RESTORED")
        self.assertEqual(result["rows_found"], 1)
        write_master.assert_called_once()

    def test_v31_restore_rejects_stale_durable_snapshot(self):
        snapshot = {
            "source": "SUPABASE_TEST",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "received_at": "2026-01-01T00:00:00+00:00",
            "options_rows": [{"ticker": "QQQ", "strike": 700}],
            "technical_snapshot": {"QQQ": {"score": 80}},
        }

        with patch.object(main, "supabase_enabled", return_value=True), patch.object(
            main,
            "supabase_fetch_single_row",
            return_value={"snapshot": snapshot, "updated_at": "2026-01-01T00:00:00+00:00"},
        ), patch.object(main, "_v28_write_master") as write_master:
            result = main._v31_restore_durable_snapshot(force=True)

        self.assertFalse(result["restored"])
        self.assertEqual(result["status"], "STALE")
        write_master.assert_not_called()

    def test_v31_pipeline_status_explains_missing_master_snapshot(self):
        empty_master = {
            "path": None,
            "data": {},
            "rows": [],
            "technical": {},
            "score": 0,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=empty_master):
            status = main._v31_data_pipeline_status_payload()

        self.assertEqual(status["engine"], "V31_DATA_PIPELINE_STATUS")
        self.assertEqual(status["status"], "NO_MASTER_SNAPSHOT")
        self.assertEqual(status["canonical_ingest"], "/v31_ingest_snapshot")
        self.assertEqual(status["legacy_ingest_supported"], "/v28_ingest_snapshot")
        self.assertFalse(status["master_snapshot_available"])
        self.assertIn("ibkr_bridge.py", status["next_required_action"])
        self.assertTrue(status["not_order_instruction"])

    def test_v31_monitor_reports_info_when_pipeline_missing_outside_market(self):
        empty_master = {
            "path": None,
            "data": {},
            "rows": [],
            "technical": {},
            "score": 0,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=empty_master):
            monitor = main._v31_monitor_status_payload()

        self.assertEqual(monitor["engine"], "V31_PIPELINE_MONITOR")
        self.assertEqual(monitor["alert_level"], "INFO")
        self.assertEqual(monitor["pipeline_status"], "NO_MASTER_SNAPSHOT")
        self.assertEqual(monitor["market_context"], "OUTSIDE_MARKET_HOURS_OR_UNKNOWN")
        self.assertFalse(monitor["notification_sent"])
        self.assertTrue(monitor["not_order_instruction"])

    def test_v31_monitor_flags_entry_ready_for_manual_review(self):
        complete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": -0.20,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=_master_snapshot([complete_row])):
            monitor = main._v31_monitor_status_payload()

        self.assertEqual(monitor["alert_level"], "ACTION_REQUIRED")
        self.assertEqual(monitor["pipeline_status"], "OK")
        self.assertEqual(monitor["manual_review_ready_count"], 1)
        self.assertEqual(monitor["entry_ready_tickers"], ["QQQ"])
        self.assertIn("revision manual", monitor["message"])
        self.assertFalse(monitor["notification_sent"])
        self.assertTrue(monitor["not_order_instruction"])

    def test_v31_monitor_flags_missing_pipeline_during_market(self):
        empty_open_master = {
            "path": None,
            "data": {
                "market": {
                    "is_regular_market_open": True,
                    "options_bidask_expected": True,
                    "label": "REGULAR_OPTIONS_SESSION",
                }
            },
            "rows": [],
            "technical": {},
            "score": 0,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=empty_open_master):
            monitor = main._v31_monitor_status_payload()

        self.assertEqual(monitor["alert_level"], "ACTION_REQUIRED")
        self.assertEqual(monitor["pipeline_status"], "NO_MASTER_SNAPSHOT")
        self.assertEqual(monitor["market_context"], "REGULAR_MARKET_HOURS")
        self.assertIn("bridge", monitor["message"])
        self.assertFalse(monitor["notification_sent"])
        self.assertTrue(monitor["not_order_instruction"])

    def test_v31_monitor_notify_preview_never_sends_email(self):
        with patch.object(main, "send_resend_email") as send_email:
            preview = main._v31_monitor_notify_payload(dry_run=True)

        self.assertEqual(preview["engine"], "V31_PIPELINE_MONITOR_EMAIL")
        self.assertEqual(preview["status"], "preview")
        self.assertFalse(preview["email_sent"])
        self.assertIn("Stock Ultimus V31 Monitor", preview["subject"])
        self.assertTrue(preview["not_order_instruction"])
        send_email.assert_not_called()

    def test_v31_monitor_notify_skips_non_actionable_status(self):
        monitor = {
            "engine": "V31_PIPELINE_MONITOR",
            "generated_at": "2026-06-12T00:00:00+00:00",
            "alert_level": "INFO",
            "pipeline_status": "NO_MASTER_SNAPSHOT",
            "market_context": "OUTSIDE_MARKET_HOURS_OR_UNKNOWN",
            "master_snapshot_available": False,
            "manual_review_ready_count": 0,
            "entry_ready_tickers": [],
            "risk_blocked_tickers": [],
            "wait_options_tickers": [],
            "message": "Informativo",
            "next_required_action": "No hacer nada.",
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_monitor_status_payload", return_value=monitor):
            with patch.object(main, "send_resend_email") as send_email:
                result = main._v31_monitor_notify_payload()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["notify_reason"], "NO_ACTIONABLE_ALERT")
        self.assertFalse(result["email_sent"])
        self.assertTrue(result["not_order_instruction"])
        send_email.assert_not_called()

    def test_v31_monitor_notify_sends_actionable_status(self):
        monitor = {
            "engine": "V31_PIPELINE_MONITOR",
            "generated_at": "2026-06-12T00:00:00+00:00",
            "alert_level": "ACTION_REQUIRED",
            "pipeline_status": "OK",
            "market_context": "REGULAR_MARKET_HOURS",
            "master_snapshot_available": True,
            "master_source": "runtime/v28_master_snapshot.json",
            "rows_found": 1,
            "technical_count": 1,
            "manual_review_ready_count": 1,
            "entry_ready_tickers": ["QQQ"],
            "risk_blocked_tickers": [],
            "wait_options_tickers": [],
            "message": "Hay setups ENTRY_READY para revision manual.",
            "next_required_action": "Abrir dashboard.",
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_monitor_status_payload", return_value=monitor):
            with patch.object(main, "send_resend_email", return_value={"email_sent": True, "provider": "test"}) as send_email:
                result = main._v31_monitor_notify_payload(to_email="test@example.com")

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["notify_reason"], "ACTION_REQUIRED")
        self.assertTrue(result["email_sent"])
        self.assertTrue(result["not_order_instruction"])
        send_email.assert_called_once()


if __name__ == "__main__":
    unittest.main()
