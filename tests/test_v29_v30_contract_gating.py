import unittest
import importlib.util
import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
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

        def middleware(self, *args, **kwargs):
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

    class JSONResponse(dict):
        def __init__(self, content=None, status_code=200, *args, **kwargs):
            super().__init__(content or {})
            self.status_code = status_code

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
    responses.JSONResponse = JSONResponse
    pydantic.BaseModel = BaseModel
    pydantic.Field = Field
    requests.get = lambda *args, **kwargs: None
    requests.post = lambda *args, **kwargs: None

    sys.modules.setdefault("fastapi", fastapi)
    sys.modules.setdefault("fastapi.responses", responses)
    sys.modules.setdefault("pydantic", pydantic)
    sys.modules.setdefault("requests", requests)


_install_import_stubs()


def _load_main_module():
    app_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    root = app_path.parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("trading_engine_main_for_contract_tests", app_path)
    if spec is None:
        raise RuntimeError("unable to load app/main.py")
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


main = _load_main_module()


class _FakeRequest:
    def __init__(self, headers=None, cookies=None):
        self.headers = headers or {}
        self.cookies = cookies or {}


class _FakeUrl:
    def __init__(self, path, query=""):
        self.path = path
        self.query = query


class _FakeBrowserRequest:
    def __init__(self, path, query="", method="GET"):
        self.method = method
        self.url = _FakeUrl(path, query)


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
    def test_request_read_token_accepts_gpt_action_api_key_header(self):
        request = _FakeRequest(headers={"X-Api-Key": "read-token-test"})

        self.assertEqual(main._request_read_token(request), "read-token-test")

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

    def test_strategy_context_selection_preserves_canslim(self):
        contexts = {
            "NAKED_PUT": {
                "ticker": "QQQ",
                "strategy_context": "NAKED_PUT",
                "trend": "bullish",
                "score": 82,
                "received_at": "2026-06-17T20:00:00+00:00",
            },
            "COVERED_CALL": {
                "ticker": "QQQ",
                "strategy_context": "COVERED_CALL",
                "trend": "neutral",
                "score": 74,
                "received_at": "2026-06-17T20:01:00+00:00",
            },
            "CANSLIM_FILTER": {
                "ticker": "QQQ",
                "strategy_context": "CANSLIM_FILTER",
                "score": 42,
                "canslim": {"passes": False, "score": 42, "rating": "FAIL"},
                "received_at": "2026-06-17T20:02:00+00:00",
            },
        }
        merged = main._strategy_signal_merge_contexts("QQQ", contexts)
        technical = {"QQQ": merged}

        naked_put = main._v29_technical_state("QQQ", technical, "NAKED_PUT")
        covered_call = main._v29_technical_state("QQQ", technical, "COVERED_CALL")

        self.assertEqual(naked_put["score"], 82)
        self.assertEqual(naked_put["strategy_context"], "NAKED_PUT")
        self.assertEqual(covered_call["score"], 74)
        self.assertEqual(covered_call["strategy_context"], "COVERED_CALL")
        self.assertFalse(naked_put["raw"]["canslim"]["passes"])

    def test_strategy_context_sanitizer_excludes_sensitive_account_fields(self):
        sanitized = main._strategy_signal_sanitize_snapshot({
            "ticker": "QQQ",
            "strategy_context": "NAKED_PUT",
            "trend": "bullish",
            "score": 80,
            "account_id": "SHOULD_NOT_PERSIST",
            "balance": 123456,
            "token": "SHOULD_NOT_PERSIST",
        })

        self.assertEqual(sanitized["ticker"], "QQQ")
        self.assertNotIn("account_id", sanitized)
        self.assertNotIn("balance", sanitized)
        self.assertNotIn("token", sanitized)

    def test_canslim_failure_blocks_complete_entry(self):
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
        master = _master_snapshot([complete_row])
        master["technical"]["QQQ"]["canslim"] = {"passes": False, "score": 42}

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            decision = main._v29_decide_ticker("QQQ")

        self.assertEqual(decision["final_state"], "RISK_BLOCKED")
        self.assertEqual(decision["main_blocker"], "CANSLIM_BLOCKED")
        self.assertFalse(decision["manual_review_ready"])
        self.assertFalse(decision["can_operate"])

    def test_wait_options_priority_is_preserved_when_canslim_fails(self):
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
        master = _master_snapshot([incomplete_row])
        master["technical"]["QQQ"]["canslim"] = {"passes": False, "score": 42}

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            decision = main._v29_decide_ticker("QQQ")

        self.assertEqual(decision["final_state"], "WAIT_OPTIONS_DATA")
        self.assertEqual(decision["main_blocker"], "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY")
        self.assertFalse(decision["manual_review_ready"])


class V31CanonicalDecisionTests(unittest.TestCase):
    def test_cloud_market_calendar_treats_juneteenth_2026_as_closed(self):
        juneteenth = datetime(2026, 6, 19, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        regular_day = datetime(2026, 6, 22, 10, 30, tzinfo=ZoneInfo("America/New_York"))

        self.assertTrue(main.is_us_market_holiday(juneteenth))
        self.assertFalse(main.is_us_market_holiday(regular_day))

    def test_v20_market_hours_respects_us_market_holiday(self):
        juneteenth = datetime(2026, 6, 19, 10, 30, tzinfo=ZoneInfo("America/New_York"))

        with patch.object(main, "_v20_now_ny", return_value=juneteenth):
            status = main._v20_market_hours_status()

        self.assertEqual(status["status"], "MARKET_HOLIDAY_CLOSED")
        self.assertFalse(status["is_regular_market_open"])
        self.assertFalse(status["options_bidask_expected"])
        self.assertTrue(status["market_holiday"])

    def test_v31_market_state_forces_closed_when_snapshot_marks_holiday(self):
        master = {
            "data": {
                "market": {
                    "status": "REGULAR_OPTIONS_SESSION",
                    "is_regular_market_open": True,
                    "options_bidask_expected": True,
                    "market_holiday": True,
                    "label": "Mercado cerrado por feriado de EE.UU.",
                }
            }
        }

        market = main._v29_market_state(master)

        self.assertFalse(market["is_regular_market_open"])
        self.assertFalse(market["options_bidask_expected"])
        self.assertTrue(market["market_holiday"])

    def test_snapshot_ingest_requires_matching_configured_token(self):
        with patch.object(main, "REQUIRE_SNAPSHOT_INGEST_TOKEN", True), \
                patch.object(main, "SNAPSHOT_INGEST_TOKEN", "test-token"):
            with self.assertRaises(main.HTTPException) as rejected:
                main.verify_snapshot_ingest_token(None)
            self.assertEqual(rejected.exception.status_code, 401)
            self.assertIsNone(main.verify_snapshot_ingest_token("test-token"))

        with patch.object(main, "REQUIRE_SNAPSHOT_INGEST_TOKEN", True), \
                patch.object(main, "SNAPSHOT_INGEST_TOKEN", ""):
            with self.assertRaises(main.HTTPException) as unavailable:
                main.verify_snapshot_ingest_token("anything")
            self.assertEqual(unavailable.exception.status_code, 503)

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
        self.assertEqual(status["endpoints"]["daily_recommendations"], "/v31_daily_recommendations")
        self.assertEqual(status["endpoints"]["gpt_daily_recommendations"], "/gpt_v31_daily_recommendations")
        self.assertEqual(status["endpoints"]["gpt_daily_rankings"], "/gpt_v31_daily_rankings")
        self.assertEqual(status["endpoints"]["gpt_daily_answer"], "/gpt_v31_daily_answer")
        self.assertEqual(status["endpoints"]["gpt_daily_brief"], "/gpt_v31_daily_brief")
        self.assertEqual(status["endpoints"]["gpt_daily_plain"], "/gpt_v31_daily_plain")
        self.assertEqual(status["endpoints"]["gpt_daily_now"], "/gpt_v31_daily_now")
        self.assertEqual(status["endpoints"]["strategy_registry"], "/strategy_registry")
        self.assertEqual(status["endpoints"]["strategy_playbook"], "/strategy_playbook")
        self.assertEqual(status["endpoints"]["strategy_exit_playbook"], "/strategy_exit_playbook")
        self.assertEqual(status["endpoints"]["strategy_regime_policy"], "/strategy_regime_policy")
        self.assertEqual(status["endpoints"]["risk_profile"], "/v31_risk_profile")
        self.assertEqual(status["endpoints"]["operating_suite"], "/v31_operating_suite")
        self.assertEqual(status["endpoints"]["outcome_tracking"], "/v31_outcome_tracking_status")
        self.assertEqual(status["decisions"][0]["final_state"], "WAIT_OPTIONS_DATA")
        self.assertIn("risk_profile", status)
        self.assertIn("outcome_tracking", status)
        self.assertTrue(status["not_order_instruction"])

    def test_gpt_daily_rankings_endpoint_serves_recommendations_payload(self):
        payload = {
            "engine": "V31_DAILY_RECOMMENDATION_ENGINE",
            "recommendation_version": "test",
            "summary": {"total": 1, "manual_review_ready": 0},
            "items": [{"ticker": "QQQ", "final_state": "ENTRY_READY", "manual_review_ready": True}],
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_daily_recommendations_payload", return_value=payload), patch.object(
            main,
            "_record_audit_event",
        ) as audit:
            result = asyncio.run(main.gpt_v31_daily_rankings())

        self.assertEqual(result["engine"], payload["engine"])
        self.assertEqual(result["summary"]["total"], 1)
        self.assertEqual(result["top_recommendations"][0]["ticker"], "QQQ")
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0], "GPT_DAILY_RANKINGS_SERVED")

    def test_gpt_daily_answer_returns_safe_institutional_text(self):
        payload = {
            "engine": "V31_DAILY_RECOMMENDATION_ENGINE",
            "generated_at": "2026-06-24T16:00:00+00:00",
            "summary": {"total": 1, "manual_review_ready": 1, "entry_ready": 1},
            "data_readiness": {
                "status": "READY_FOR_DECISION_REVIEW",
                "operational_readiness": "READY_FOR_DECISION_REVIEW",
                "option_rows_found": 1,
                "technical_count": 1,
                "next_required_actions": ["Revisar manualmente."],
            },
            "items": [
                {
                    "ticker": "QQQ",
                    "strategy": "NAKED_PUT",
                    "final_state": "ENTRY_READY",
                    "manual_review_ready": True,
                    "conviction_score": 1200,
                    "selected_contract": {
                        "strike": 645,
                        "expiration": "20260731",
                        "dte": 37,
                        "bid": 6.1,
                        "ask": 6.2,
                        "delta": -0.14,
                    },
                }
            ],
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_daily_recommendations_payload", return_value=payload), patch.object(
            main,
            "_record_audit_event",
        ) as audit:
            result = asyncio.run(main.gpt_v31_daily_answer(limit=3))

        self.assertEqual(result["engine"], "SUPER_ENGINE_BOLSA_INSTITUTIONAL_ANSWER")
        self.assertIn("Oportunidades para revision manual", result["answer_text"])
        self.assertIn("QQQ", result["answer_text"])
        self.assertIn("no autoriza ordenes", result["answer_text"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0], "GPT_DAILY_ANSWER_SERVED")

    def test_gpt_daily_brief_returns_minimal_safe_display_text(self):
        answer_payload = {
            "generated_at": "2026-06-24T16:00:00+00:00",
            "answer_text": "Estado del motor: READY_FOR_DECISION_REVIEW / WAIT_MARKET_WINDOW\n\nNota: esto no autoriza ordenes.",
            "summary": {"total": 10, "entry_ready": 0, "manual_review_ready": 0},
            "data_readiness": {
                "status": "READY_FOR_DECISION_REVIEW",
                "operational_readiness": "WAIT_MARKET_WINDOW",
                "main_blocker": "WAIT_MARKET",
            },
            "execution_authorized": False,
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_gpt_institutional_answer_payload", return_value=answer_payload), patch.object(
            main,
            "_record_audit_event",
        ) as audit:
            result = asyncio.run(main.gpt_v31_daily_brief(limit=3))

        self.assertEqual(result["brief_version"], "super_engine_bolsa_daily_brief_v1")
        self.assertEqual(result["response_mode"], "copy_answer_to_user_exactly")
        self.assertIn(answer_payload["answer_text"], result["answer_to_user"])
        self.assertEqual(result["display_text"], result["answer_to_user"])
        self.assertTrue(result["answer_to_user"].startswith("Hoy no hay oportunidades accionables:"))
        self.assertIn("WAIT_MARKET_WINDOW", result["display_text"])
        self.assertIn("estado wait market window", result["display_text"].splitlines()[0])
        self.assertIn("no autoriza ordenes", result["display_text"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0], "GPT_DAILY_BRIEF_SERVED")

    def test_gpt_daily_plain_returns_ready_to_send_text(self):
        answer_payload = {
            "generated_at": "2026-06-24T16:00:00+00:00",
            "answer_text": "Estado del motor: READY_FOR_DECISION_REVIEW / WAIT_MARKET_WINDOW\n\nNota: esto no autoriza ordenes.",
            "summary": {"total": 10, "entry_ready": 0, "manual_review_ready": 0},
            "data_readiness": {
                "status": "READY_FOR_DECISION_REVIEW",
                "operational_readiness": "WAIT_MARKET_WINDOW",
                "main_blocker": "WAIT_MARKET",
            },
            "execution_authorized": False,
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_gpt_institutional_answer_payload", return_value=answer_payload), patch.object(
            main,
            "_record_audit_event",
        ) as audit:
            result = asyncio.run(main.gpt_v31_daily_plain(limit=3))

        body = getattr(result, "body", None)
        rendered = body.decode("utf-8") if body is not None else str(result)
        self.assertIn(answer_payload["answer_text"], rendered)
        self.assertTrue(rendered.startswith("Hoy no hay oportunidades accionables:"))
        self.assertIn("motor ready for decision review", rendered.splitlines()[0])
        self.assertIn("no autoriza ordenes", rendered.splitlines()[0])
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0], "GPT_DAILY_PLAIN_SERVED")

    def test_gpt_daily_now_returns_ready_to_send_text(self):
        answer_payload = {
            "generated_at": "2026-06-24T16:00:00+00:00",
            "answer_text": "Estado del motor: READY_FOR_DECISION_REVIEW / WAIT_MARKET_WINDOW\n\nNota: esto no autoriza ordenes.",
            "summary": {"total": 10, "entry_ready": 0, "manual_review_ready": 0},
            "data_readiness": {
                "status": "READY_FOR_DECISION_REVIEW",
                "operational_readiness": "WAIT_MARKET_WINDOW",
                "main_blocker": "WAIT_MARKET",
            },
            "execution_authorized": False,
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_gpt_institutional_answer_payload", return_value=answer_payload), patch.object(
            main,
            "_record_audit_event",
        ) as audit:
            result = asyncio.run(main.gpt_v31_daily_now(limit=3))

        rendered = result["answer_to_user"]
        self.assertEqual(result["response_mode"], "copy_answer_to_user_exactly")
        self.assertTrue(rendered.startswith("Hoy no hay oportunidades accionables:"))
        self.assertEqual(result["first_line"], rendered.splitlines()[0])
        self.assertIn("estado wait market window", rendered.splitlines()[0])
        self.assertNotIn("READY_FOR_DECISION_REVIEW", rendered.splitlines()[0])
        self.assertIn("no autoriza ordenes", rendered.splitlines()[0])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0], "GPT_DAILY_NOW_SERVED")

    def test_v31_blocker_cause_summary_groups_broker_capacity_detail(self):
        items = [
            {
                "ticker": "MSFT",
                "strategy": "NAKED_PUT",
                "final_state": "RISK_BLOCKED",
                "risk_status": "RISK_BLOCKED",
                "broker_check_blockers": ["BROKER_PUT_CAPACITY_INSUFFICIENT"],
                "broker_check_checks": [
                    {
                        "name": "PUT_CAPACITY_CHECK",
                        "status": "BLOCKED",
                        "value": 25000,
                        "required": 36500,
                        "shortfall": 11500,
                        "capacity_pct_required": 146.0,
                    }
                ],
            },
            {
                "ticker": "AAPL",
                "strategy": "NAKED_PUT",
                "final_state": "WAIT_OPTIONS_DATA",
                "main_blocker": "WAIT_OPTIONS_DATA",
            },
        ]

        groups = main._v31_blocker_cause_summary(items)

        self.assertEqual(groups[0]["bucket"], "broker_capacity")
        self.assertEqual(groups[0]["count"], 1)
        self.assertIn("MSFT", groups[0]["tickers"])
        self.assertIn("faltante=11500", groups[0]["examples"][0]["primary_block_reason"])
        self.assertEqual(groups[1]["bucket"], "options_data")
        self.assertEqual(groups[1]["count"], 1)

    def test_gpt_executive_status_exposes_compact_operational_answer(self):
        answer_payload = {
            "generated_at": "2026-07-06T14:00:00+00:00",
            "answer_text": "Estado del motor: READY_FOR_DECISION_REVIEW / READY.\n\nBloqueos principales:\n- broker_capacity: 1 setup. Ejemplos: MSFT.",
            "summary": {"total": 3, "entry_ready": 0, "manual_review_ready": 0, "risk_blocked": 1},
            "data_readiness": {
                "status": "READY_FOR_DECISION_REVIEW",
                "operational_readiness": "READY",
                "main_blocker": None,
            },
            "blocked_cause_groups": [{"bucket": "broker_capacity", "count": 1, "tickers": ["MSFT"]}],
            "execution_authorized": False,
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_gpt_institutional_answer_payload", return_value=answer_payload):
            result = main._v31_executive_status_payload(limit=3)

        self.assertEqual(result["response_mode"], "copy_answer_to_user_exactly")
        self.assertEqual(result["engine"], "V31_EXECUTIVE_STATUS")
        self.assertIn("Motor corrió: sin ENTRY_READY", result["first_line"])
        self.assertIn("broker_capacity=1 (MSFT)", result["first_line"])
        self.assertEqual(result["blocked_cause_groups"][0]["bucket"], "broker_capacity")
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])

    def test_v31_risk_profile_presets_are_selectable(self):
        conservative = main._v31_risk_profile("conservative")
        paper = main._v31_risk_profile("paper")

        self.assertEqual(conservative["preset"], "conservative")
        self.assertEqual(paper["preset"], "paper")
        self.assertLess(conservative["max_abs_spread"], paper["max_abs_spread"])
        self.assertIn("balanced", conservative["available_presets"])

    def test_v31_operating_suite_groups_product_surfaces(self):
        with patch.object(main, "_v31_command_center_payload", return_value={
            "status": "READY_FOR_DECISION_REVIEW",
            "operational_readiness": "READY_FOR_DECISION_REVIEW",
            "summary": {"entry_ready": 1},
            "top_recommendations": [{"ticker": "QQQ"}],
            "blocked_or_waiting": [],
        }), patch.object(main, "_v31_trading_day_readiness_payload", return_value={
            "status": "READY_FOR_MANUAL_REVIEW",
        }), patch.object(main, "_v31_manual_reviews_payload", return_value={
            "review_count": 2,
            "by_status": {"REVIEWING": 1, "REJECTED": 1},
        }), patch.object(main, "_v31_manual_review_learning_payload", return_value={
            "evaluated_count": 1,
            "needs_more_data": True,
            "avg_paper_pnl_r": 0.2,
            "by_learning_label": {"FAVORABLE_AFTER_REJECTION": 1},
        }), patch.object(main, "_durable_supabase_fetch", return_value=[]), patch.object(
            main,
            "load_outcomes_from_file",
            return_value=[],
        ):
            suite = main._v31_operating_suite_payload()

        self.assertEqual(suite["engine"], "V31_OPERATING_SUITE")
        self.assertIn("manual_review", suite)
        self.assertIn("outcome_tracking", suite)
        self.assertIn("learning", suite)
        self.assertIn("risk_profiles", suite)
        self.assertIn("third_party_installation", suite)
        self.assertFalse(suite["execution_authorized"])

    def test_v32_operator_today_guides_manual_review_without_execution(self):
        with patch.object(main, "_v31_command_center_payload", return_value={
            "status": "READY_FOR_DECISION_REVIEW",
            "operational_readiness": "READY_FOR_MANUAL_REVIEW",
            "account_context": {
                "account_scope": "primary",
                "account_alias": "primary",
                "available_funds": 70000,
                "excess_liquidity": 80000,
                "buying_power": 100000,
                "net_liquidation": 150000,
                "currency": "USD",
            },
            "account_scope": "primary",
            "account_alias": "primary",
            "summary": {"entry_ready": 1, "manual_review_ready": 1},
            "top_recommendations": [{
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "generated_at": "2026-07-08T13:45:00+00:00",
                "final_state": "ENTRY_READY",
                "manual_review_ready": True,
                "selected_contract": {
                    "strike": 645,
                    "expiration": "20260731",
                    "dte": 30,
                    "bid": 6.1,
                    "ask": 6.2,
                    "mid": 6.15,
                    "delta": -0.2,
                },
                "next_required_action": "Validar spread, liquidez y ticket broker.",
            }],
            "blocked_or_waiting": [],
        }), patch.object(main, "_v31_trading_day_readiness_payload", return_value={
            "status": "READY_FOR_MANUAL_REVIEW",
        }), patch.object(main, "_v31_manual_reviews_payload", return_value={
            "review_count": 0,
            "by_status": {},
            "allowed_statuses": ["REVIEWING", "WATCHLIST"],
        }), patch.object(main, "_v31_manual_review_learning_payload", return_value={
            "evaluated_count": 0,
            "unevaluated_count": 0,
            "needs_more_data": True,
            "avg_paper_pnl_r": None,
        }), patch.object(main, "_durable_supabase_fetch", return_value=[]), patch.object(
            main,
            "_v32_load_operator_events",
            return_value=[],
        ):
            payload = main._v32_operator_today_payload()

        self.assertEqual(payload["engine"], "V32_OPERATOR_ASSISTANT")
        self.assertEqual(payload["active_alerts"][0]["severity"], "ACTION")
        self.assertEqual(payload["active_alerts"][0]["alert_date"], "2026-07-08")
        self.assertEqual(payload["active_alerts"][0]["economics"]["capital_required"], 63890.0)
        self.assertEqual(payload["active_alerts"][0]["economics"]["capital_source"], "estimated_cash_secured_put")
        self.assertEqual(payload["active_alerts"][0]["economics"]["probability_success_pct"], 80.0)
        self.assertEqual(payload["active_alerts"][0]["economics"]["probability_source"], "delta_proxy")
        self.assertEqual(payload["account_capacity"]["available_capacity"], 70000.0)
        self.assertEqual(payload["account_capacity"]["capacity_source"], "available_funds")
        self.assertEqual(payload["active_alerts"][0]["account_capacity_check"]["status"], "WITHIN_AVAILABLE_CAPACITY")
        self.assertTrue(payload["active_alerts"][0]["account_capacity_check"]["within_available_capacity"])
        self.assertEqual(payload["active_alerts"][0]["account_capacity_check"]["capacity_pct_required"], 91.27)
        self.assertEqual(payload["active_alerts"][0]["account_capacity_check"]["warning"], "USES_HIGH_CAPACITY_PCT")
        self.assertEqual(payload["intraday_futures"]["status"], "NO_ACTIVE_INTRADAY_FUTURES_ALERTS")
        self.assertEqual(payload["next_actions"][0]["kind"], "MANUAL_REVIEW")
        self.assertIn("revisar", payload["answer_to_user"].lower())
        self.assertIn("MARK_WATCHLIST", payload["allowed_operator_actions"])
        self.assertFalse(payload["execution_authorized"])
        self.assertTrue(payload["not_order_instruction"])

    def test_v32_operator_event_maps_to_manual_review_journal(self):
        with patch.object(main, "_v31_record_manual_review", return_value={
            "status": "RECORDED",
            "review": {"review_id": "MR-1"},
        }) as record:
            event = main._v32_operator_event_payload({
                "action": "MARK_WATCHLIST",
                "ticker": "qqq",
                "reason": "Esperando mejor spread.",
                "actor": "unit_test",
            })

        self.assertEqual(event["action"], "MARK_WATCHLIST")
        self.assertEqual(event["ticker"], "QQQ")
        self.assertTrue(event["manual_review_recorded"])
        self.assertEqual(event["manual_review_status"], "WATCHLIST")
        self.assertEqual(event["manual_review_id"], "MR-1")
        self.assertFalse(event["execution_authorized"])
        self.assertTrue(event["not_order_instruction"])
        record.assert_called_once()
        self.assertEqual(record.call_args.args[0]["status"], "WATCHLIST")
        self.assertFalse(record.call_args.args[0]["execution_authorized"])

    def test_v32_operator_event_reject_requires_reason(self):
        with self.assertRaises(ValueError) as ctx:
            main._v32_operator_event_payload({
                "action": "REJECT_SETUP",
                "ticker": "QQQ",
            })

        self.assertIn("REASON_REQUIRED", str(ctx.exception))

    def test_v32_operator_daily_summary_and_tracking_are_read_only(self):
        with patch.object(main, "_v31_command_center_payload", return_value={
            "status": "READY_FOR_DECISION_REVIEW",
            "operational_readiness": "READY_FOR_MANUAL_REVIEW",
            "summary": {"entry_ready": 1, "manual_review_ready": 1},
            "top_recommendations": [{
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "final_state": "ENTRY_READY",
                "manual_review_ready": True,
                "selected_contract": {"strike": 645, "expiration": "20260731", "bid": 6.1, "ask": 6.2},
                "next_required_action": "Validar spread, liquidez y ticket broker.",
            }],
            "blocked_or_waiting": [],
        }), patch.object(main, "_v31_trading_day_readiness_payload", return_value={
            "status": "READY_FOR_MANUAL_REVIEW",
        }), patch.object(main, "_v31_manual_reviews_payload", return_value={
            "review_count": 0,
            "by_status": {},
            "allowed_statuses": ["REVIEWING", "WATCHLIST"],
        }), patch.object(main, "_v31_manual_review_learning_payload", return_value={
            "evaluated_count": 0,
            "unevaluated_count": 0,
            "needs_more_data": True,
            "avg_paper_pnl_r": None,
        }), patch.object(main, "_durable_supabase_fetch", return_value=[]), patch.object(
            main,
            "_v32_load_operator_events",
            return_value=[{
                "event_id": "OE-1",
                "alert_id": "ALERT-1",
                "action": "MARK_WATCHLIST",
                "operator_status": "WATCHLIST",
                "ticker": "QQQ",
            }],
        ):
            summary = main._v32_operator_daily_summary_payload()
            tracking = main._v32_operator_tracking_payload()

        self.assertEqual(summary["engine"], "V32_OPERATOR_DAILY_SUMMARY")
        self.assertEqual(summary["counts"]["action"], 1)
        self.assertIn("/v32_operator_tracking_status", summary["links"]["tracking"])
        self.assertFalse(summary["execution_authorized"])
        self.assertTrue(summary["not_order_instruction"])
        self.assertEqual(tracking["engine"], "V32_OPERATOR_TRACKING_STATUS")
        self.assertEqual(tracking["by_action"]["MARK_WATCHLIST"], 1)
        self.assertEqual(tracking["open_alert_count"], 1)
        self.assertFalse(tracking["execution_authorized"])
        self.assertTrue(tracking["not_order_instruction"])

    def test_v32_operator_daily_summary_marks_data_refresh_issue(self):
        with patch.object(main, "_v32_operator_today_payload", return_value={
            "status": "WAIT_MARKET",
            "active_alerts": [{
                "alert_id": "ALERT-NODATA-QQQ",
                "ticker": "QQQ",
                "severity": "INFO",
                "state": "NO_DATA",
                "main_blocker": "NO_OPTION_ROWS",
                "operator_status": "NEW",
            }],
            "next_actions": [{
                "kind": "DATA_REFRESH",
                "label": "Refrescar datos del motor",
                "detail": "Ejecutar ibkr_bridge.py y publicar snapshot fresco.",
            }],
            "account_context": {},
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_tracking_payload", return_value={
            "operator_event_count": 0,
            "open_alert_count": 0,
            "closed_alert_count": 0,
            "outcome_tracking": {"pending_entry_ready_signals": 0},
        }):
            summary = main._v32_operator_daily_summary_payload()

        self.assertEqual(summary["counts"]["action"], 0)
        self.assertEqual(summary["counts"]["no_data"], 1)
        self.assertTrue(summary["counts"]["data_refresh_required"])
        self.assertIn("esperando datos frescos", summary["summary_text"])
        self.assertFalse(summary["execution_authorized"])
        self.assertTrue(summary["not_order_instruction"])

    def test_v32_operator_daily_summary_email_preview_never_sends(self):
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "send_resend_email") as send_email:
            preview = main._v32_operator_daily_summary_email_payload(dry_run=True)

        self.assertEqual(preview["status"], "preview")
        self.assertFalse(preview["email_sent"])
        self.assertFalse(preview["execution_authorized"])
        self.assertTrue(preview["not_order_instruction"])
        send_email.assert_not_called()

    def test_v32_operator_pushover_preview_never_sends(self):
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "send_pushover_message") as send_push:
            preview = main._v32_operator_pushover_notify_payload(dry_run=True)

        self.assertEqual(preview["status"], "preview")
        self.assertFalse(preview["pushover_sent"])
        self.assertFalse(preview["execution_authorized"])
        self.assertTrue(preview["not_order_instruction"])
        send_push.assert_not_called()

    def test_v32_operator_pushover_skips_non_actionable_without_force(self):
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "send_pushover_message") as send_push:
            result = main._v32_operator_pushover_notify_payload(dry_run=False)

        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result["pushover_sent"])
        self.assertEqual(result["reason"], "NO_ACTIONABLE_V32_ALERTS")
        send_push.assert_not_called()

    def test_v32_operator_pushover_notifies_data_refresh_issue(self):
        summary = {
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Requiere atencion de datos.",
            "counts": {
                "action": 0,
                "risk": 0,
                "watch": 0,
                "info": 1,
                "no_data": 1,
                "active": 1,
                "data_refresh_required": True,
            },
            "active_alerts": [{
                "alert_id": "ALERT-NODATA-QQQ",
                "ticker": "QQQ",
                "severity": "INFO",
                "state": "NO_DATA",
                "main_blocker": "NO_OPTION_ROWS",
                "operator_status": "NEW",
            }],
            "next_actions": [{"kind": "DATA_REFRESH", "label": "Refrescar datos del motor"}],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value=summary), patch.object(
            main,
            "_v29_load_json_file",
            return_value={},
        ), patch.object(main, "send_pushover_message", return_value={
            "pushover_sent": True,
            "provider": "pushover",
            "status_code": 200,
        }) as send_push, patch.object(main, "_v32_save_pushover_dedupe_state", return_value=True) as save_state:
            result = main._v32_operator_pushover_notify_payload(dry_run=False)

        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["would_notify"])
        self.assertTrue(result["pushover_sent"])
        self.assertEqual(result["notify_reason"], "DATA_REFRESH_REQUIRED")
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        send_push.assert_called_once()
        save_state.assert_called_once()

    def test_v32_operator_pushover_force_sends_decision_support_only(self):
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [{"ticker": "QQQ", "severity": "WATCH", "state": "WAIT_MARKET", "operator_status": "NEW"}],
            "next_actions": [{"label": "Esperar mercado abierto"}],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "send_pushover_message", return_value={
            "pushover_sent": True,
            "provider": "pushover",
            "status_code": 200,
        }) as send_push:
            result = main._v32_operator_pushover_notify_payload(force=True, dry_run=False)

        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["pushover_sent"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        send_push.assert_called_once()

    def test_v32_operator_pushover_dedupes_repeated_action_alert(self):
        summary = {
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "READY_FOR_MANUAL_REVIEW",
            "summary_text": "Requiere atencion humana.",
            "counts": {"action": 1, "risk": 0, "watch": 0},
            "active_alerts": [{
                "alert_id": "ALERT-1",
                "ticker": "QQQ",
                "severity": "ACTION",
                "state": "ENTRY_READY",
                "operator_status": "NEW",
            }],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        signature = main._v32_operator_pushover_signature(summary)
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value=summary), patch.object(
            main,
            "_v29_load_json_file",
            return_value={"last_signature": signature, "last_sent_at": "2026-07-03T20:00:00+00:00", "last_status": "sent"},
        ), patch.object(main, "send_pushover_message") as send_push:
            result = main._v32_operator_pushover_notify_payload(dry_run=False)

        self.assertEqual(result["status"], "deduped")
        self.assertFalse(result["pushover_sent"])
        self.assertTrue(result["dedupe"]["deduped"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        send_push.assert_not_called()

    def test_v32_operator_pushover_records_dedupe_state_after_send(self):
        summary = {
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "READY_FOR_MANUAL_REVIEW",
            "summary_text": "Requiere atencion humana.",
            "counts": {"action": 1, "risk": 0, "watch": 0},
            "active_alerts": [{
                "alert_id": "ALERT-2",
                "ticker": "SPY",
                "severity": "ACTION",
                "state": "ENTRY_READY",
                "operator_status": "NEW",
            }],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value=summary), patch.object(
            main,
            "_v29_load_json_file",
            return_value={},
        ), patch.object(main, "send_pushover_message", return_value={
            "pushover_sent": True,
            "provider": "pushover",
            "status_code": 200,
        }) as send_push, patch.object(main, "_v32_save_pushover_dedupe_state", return_value=True) as save_state:
            result = main._v32_operator_pushover_notify_payload(dry_run=False)

        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["pushover_sent"])
        self.assertFalse(result["dedupe"]["deduped"])
        send_push.assert_called_once()
        save_state.assert_called_once()

    def test_v32_operator_nudge_preview_never_sends(self):
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_tracking_payload", return_value={
            "engine": "V32_OPERATOR_TRACKING_STATUS",
            "operator_event_count": 1,
            "open_alert_count": 1,
            "outcome_tracking": {"pending_entry_ready_signals": 0},
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "send_pushover_message") as send_push:
            preview = main._v32_operator_nudge_payload(slot="midday", dry_run=True)

        self.assertEqual(preview["engine"], "V32_OPERATOR_NUDGE")
        self.assertEqual(preview["status"], "preview")
        self.assertEqual(preview["slot"], "midday")
        self.assertTrue(preview["would_notify"])
        self.assertFalse(preview["pushover_sent"])
        self.assertIn("Abre el GPT", preview["message"])
        self.assertFalse(preview["execution_authorized"])
        self.assertTrue(preview["not_order_instruction"])
        send_push.assert_not_called()

    def test_v32_operator_nudge_sends_decision_support_push(self):
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [{"ticker": "QQQ", "severity": "WATCH", "state": "WAIT_MARKET", "operator_status": "NEW"}],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_tracking_payload", return_value={
            "engine": "V32_OPERATOR_TRACKING_STATUS",
            "operator_event_count": 1,
            "open_alert_count": 1,
            "outcome_tracking": {"pending_entry_ready_signals": 1},
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v29_load_json_file", return_value={}), patch.object(
            main,
            "send_pushover_message",
            return_value={"pushover_sent": True, "provider": "pushover", "status_code": 200},
        ) as send_push, patch.object(main, "_v32_save_operator_nudge_state", return_value=True) as save_state:
            result = main._v32_operator_nudge_payload(slot="post_close", dry_run=False)

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["slot"], "post_close")
        self.assertTrue(result["pushover_sent"])
        self.assertEqual(result["gpt_prompt"], "haz cierre operativo y backtesting pendiente")
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        send_push.assert_called_once()
        save_state.assert_called_once()

    def test_v32_operator_nudge_dedupes_repeated_slot(self):
        summary = {
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        tracking = {
            "engine": "V32_OPERATOR_TRACKING_STATUS",
            "operator_event_count": 1,
            "open_alert_count": 1,
            "outcome_tracking": {"pending_entry_ready_signals": 0},
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        signature = main._v32_operator_nudge_signature("open_check", summary, tracking)
        session_date = datetime.now(main.MARKET_TZ).date().isoformat()
        state = {"sent": {"{}:open_check".format(session_date): {"signature": signature, "sent_at": "2026-07-03T13:31:00+00:00", "status": "sent"}}}
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value=summary), patch.object(
            main,
            "_v32_operator_tracking_payload",
            return_value=tracking,
        ), patch.object(main, "_v29_load_json_file", return_value=state), patch.object(main, "send_pushover_message") as send_push:
            result = main._v32_operator_nudge_payload(slot="open_check", dry_run=False)

        self.assertEqual(result["status"], "deduped")
        self.assertTrue(result["dedupe"]["deduped"])
        self.assertFalse(result["pushover_sent"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        send_push.assert_not_called()

    def test_v32_operator_nudge_preflight_is_read_only_and_operational(self):
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_tracking_payload", return_value={
            "engine": "V32_OPERATOR_TRACKING_STATUS",
            "operator_event_count": 1,
            "open_alert_count": 1,
            "outcome_tracking": {"pending_entry_ready_signals": 1},
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "send_pushover_message") as send_push:
            result = main._v32_operator_nudge_preflight_payload()

        self.assertEqual(result["engine"], "V32_OPERATOR_NUDGE_PREFLIGHT")
        self.assertIn("GET /v32_operator_nudge_preflight", result["checks"]["gpt_action_endpoints"])
        self.assertEqual([item["slot"] for item in result["slot_previews"]], ["premarket", "open_check", "midday", "power_hour", "post_close"])
        self.assertGreaterEqual(len(result["first_business_day_checklist"]), 5)
        self.assertIn("MARK_WATCHLIST", [item["operator_action"] for item in result["response_playbook"]])
        self.assertFalse(result["auto_preview"]["pushover_sent"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        send_push.assert_not_called()

    def test_v32_actionable_signal_watch_sends_new_entry_ready_push(self):
        summary = {
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "READY",
            "counts": {"action": 1, "risk": 0, "watch": 0},
            "active_alerts": [{
                "alert_id": "ALERT-2026-07-06-NVDA-NAKED_PUT-ENTRY_READY",
                "ticker": "NVDA",
                "strategy": "NAKED_PUT",
                "severity": "ACTION",
                "state": "ENTRY_READY",
                "operator_status": "NEW",
                "manual_review_ready": True,
                "selected_contract": {"expiration": "2026-07-17", "strike": 140, "mid": 1.25},
            }],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value=summary), patch.object(
            main, "_v29_load_json_file", return_value={}
        ), patch.object(main, "_v32_save_actionable_signal_watch_state", return_value=True) as save_state, patch.object(
            main, "send_pushover_message", return_value={"pushover_sent": True, "provider": "pushover", "status_code": 200}
        ) as send_push:
            result = main._v32_actionable_signal_watch_payload()

        self.assertEqual(result["engine"], "V32_ACTIONABLE_SIGNAL_WATCH")
        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["would_notify"])
        self.assertEqual(result["new_candidate_count"], 1)
        self.assertTrue(result["pushover_sent"])
        self.assertIn("revisa NVDA", result["message"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        send_push.assert_called_once()
        save_state.assert_called_once()

    def test_v32_actionable_signal_watch_dedupes_same_signal(self):
        summary = {
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "READY",
            "counts": {"action": 1, "risk": 0, "watch": 0},
            "active_alerts": [{
                "alert_id": "ALERT-2026-07-06-NVDA-NAKED_PUT-ENTRY_READY",
                "ticker": "NVDA",
                "strategy": "NAKED_PUT",
                "severity": "ACTION",
                "state": "ENTRY_READY",
                "operator_status": "NEW",
                "manual_review_ready": True,
                "selected_contract": {"expiration": "2026-07-17", "strike": 140, "mid": 1.25},
            }],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
        signature = main._v32_actionable_signal_signature(summary["active_alerts"][0])
        today = main.datetime.now(main.MARKET_TZ).date().isoformat()
        key = f"{today}:ALERT-2026-07-06-NVDA-NAKED_PUT-ENTRY_READY"
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value=summary), patch.object(
            main, "_v29_load_json_file", return_value={"sent": {key: {"signature": signature, "sent_at": "2026-07-06T14:00:00Z"}}}
        ), patch.object(main, "send_pushover_message") as send_push:
            result = main._v32_actionable_signal_watch_payload()

        self.assertEqual(result["status"], "deduped")
        self.assertFalse(result["would_notify"])
        self.assertEqual(result["new_candidate_count"], 0)
        self.assertEqual(result["deduped_candidate_count"], 1)
        self.assertFalse(result["pushover_sent"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])
        send_push.assert_not_called()

    def test_v32_operator_daily_cycle_guides_notifications_and_backtesting(self):
        with patch.object(main, "_v32_operator_today_payload", return_value={
            "engine": "V32_OPERATOR_ASSISTANT",
            "status": "WAIT_MARKET",
            "active_alerts": [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "status": "WAIT_MARKET",
            "summary_text": "Sin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "active_alerts": [],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_tracking_payload", return_value={
            "engine": "V32_OPERATOR_TRACKING_STATUS",
            "operator_event_count": 2,
            "open_alert_count": 1,
            "outcome_tracking": {"pending_entry_ready_signals": 1},
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_pushover_notify_payload", return_value={
            "engine": "V32_OPERATOR_PUSHOVER_NOTIFY",
            "would_notify": False,
            "status": "preview",
            "dedupe": {"deduped": False},
            "pushover_sent": False,
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_nudge_payload", return_value={
            "engine": "V32_OPERATOR_NUDGE",
            "would_notify": True,
            "status": "preview",
            "slot": "midday",
            "question": "Quieres mantener, rechazar o anotar algo de la watchlist?",
            "pushover_sent": False,
            "execution_authorized": False,
            "not_order_instruction": True,
        }):
            result = main._v32_operator_daily_cycle_payload()

        self.assertEqual(result["engine"], "V32_OPERATOR_DAILY_CYCLE")
        self.assertIn("/v32_operator_pushover_notify/preview", result["routine"][2]["cloud_push_preview"])
        self.assertIn("/v32_operator_nudge/preview", result["routine"][3]["nudge_preview"])
        self.assertEqual(result["backtesting_follow_up"]["pending_entry_ready_signals"], 1)
        self.assertIn("/v31_evaluate_manual_reviews", result["routine"][4]["post_close_endpoint"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["not_order_instruction"])

    def test_v32_live_command_center_renders_summary_and_tracking(self):
        with patch.object(main, "_v32_operator_daily_summary_payload", return_value={
            "engine": "V32_OPERATOR_DAILY_SUMMARY",
            "generated_at": "2026-07-03T18:54:11+00:00",
            "status": "WAIT_MARKET",
            "summary_text": "Stock Ultimus V32 daily summary\nSin accion operativa inmediata.",
            "counts": {"action": 0, "risk": 0, "watch": 5},
            "next_actions": [{"priority": 1, "label": "Monitorear", "detail": "Esperar mercado abierto."}],
            "active_alerts": [{
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "severity": "WATCH",
                "state": "WAIT_MARKET",
                "main_blocker": "MARKET_CLOSED",
                "operator_status": "NEW",
            }],
            "execution_authorized": False,
            "not_order_instruction": True,
        }), patch.object(main, "_v32_operator_tracking_payload", return_value={
            "engine": "V32_OPERATOR_TRACKING_STATUS",
            "operator_event_count": 1,
            "open_alert_count": 1,
            "outcome_tracking": {"pending_entry_ready_signals": 0},
            "recent_events": [{"recorded_at": "2026-07-03T18:00:00+00:00", "ticker": "QQQ", "action": "MARK_WATCHLIST", "operator_status": "WATCHLIST"}],
            "execution_authorized": False,
            "not_order_instruction": True,
        }):
            html = main._v32_project_command_center_live_html()

        self.assertIn("Stock Ultimus Live Command Center", html)
        self.assertIn("WAIT_MARKET", html)
        self.assertIn("QQQ", html)
        self.assertIn("Daily Summary", html)
        self.assertIn("Tracking JSON", html)
        self.assertIn("/v32_project_command_center_static", html)

    def test_manual_review_inbox_renders_entry_ready_cards(self):
        decision = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
            "manual_review_ready": True,
            "technical_status": "CONFIRMED",
            "risk_status": "PASS",
            "explanation": "QQQ listo para revision manual.",
            "selected_contract": {
                "strike": 645,
                "expiration": "20260731",
                "dte": 37,
                "bid": 6.1,
                "ask": 6.2,
                "spread_pct": 0.8,
                "delta": -0.14,
            },
        }

        with patch.object(main, "_v31_manual_review_console_decisions", return_value=([decision], {"recent_reviews": []})):
            html = main._v31_manual_review_inbox_html()

        self.assertIn("Daily Review Inbox", html)
        self.assertIn("Inbox de revision manual", html)
        self.assertIn("Hay setups pendientes de revision humana", html)
        self.assertIn("Que hago ahora", html)
        self.assertIn("QQQ", html)
        self.assertIn("Approve manual", html)
        self.assertIn("/v31_manual_review_inbox/record", html)
        self.assertIn("no autoriza ejecución automática", html)
        self.assertIn("Pendientes", html)
        self.assertIn("scripts/run_daily_outcome_evaluation.py --dry-run", html)
        self.assertIn("/v32_strategy_performance_dashboard", html)
        self.assertIn("/v31_manual_reviews_dashboard", html)
        self.assertIn("/v31_manual_review_learning_dashboard", html)

    def test_command_center_html_renders_operator_friendly_summary(self):
        with patch.object(main, "_v31_command_center_payload", return_value={
            "status": "READY_FOR_DECISION_REVIEW",
            "operational_readiness": "READY_FOR_MANUAL_REVIEW",
            "generated_at": "2026-07-06T14:00:00+00:00",
            "summary": {
                "items": 2,
                "entry_ready": 1,
                "blocked_or_waiting": 1,
                "option_rows_found": 12,
                "snapshot": "unit-test-master.json",
                "decision_state_counts": {"ENTRY_READY": 1, "WAIT_OPTIONS_DATA": 1},
            },
            "top_recommendations": [{
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "final_state": "ENTRY_READY",
                "conviction_score": 1200,
                "main_blocker": "Manual review",
                "selected_contract": {
                    "strike": 645,
                    "expiration": "20260731",
                    "bid": 6.1,
                    "ask": 6.2,
                    "delta": -0.14,
                },
            }],
            "blocked_or_waiting": [{
                "ticker": "TSLA",
                "strategy": "NAKED_PUT",
                "final_state": "WAIT_OPTIONS_DATA",
                "main_blocker": "MISSING_DELTA",
                "required_missing_fields": ["delta"],
            }],
            "next_required_actions": ["Revisar QQQ manualmente."],
            "execution_authorized": False,
            "not_order_instruction": True,
        }):
            html = main._v31_command_center_html()

        self.assertIn("Hay setups listos para revision manual", html)
        self.assertIn("Siguiente paso", html)
        self.assertIn("Usar Inbox revision manual", html)
        self.assertIn("/v31_manual_review_inbox", html)
        self.assertIn("ENTRY_READY no autoriza ordenes", html)
        self.assertIn("Bloqueadas o en espera", html)

    def test_wait_options_inbox_renders_contract_alternatives(self):
        decision = {
            "ticker": "TSLA",
            "strategy": "NAKED_PUT",
            "final_state": "WAIT_OPTIONS_DATA",
            "manual_review_ready": False,
            "technical_status": "CONFIRMED",
            "risk_status": "BLOCKED",
            "explanation": "TSLA espera datos de opciones.",
            "selected_contract": {
                "strike": 335,
                "expiration": "20260807",
                "dte": 43,
                "bid": 6.45,
                "ask": 9.4,
                "spread_pct": 37.22,
                "delta": -0.2158,
            },
            "contract_alternatives": [
                {
                    "strike": 330,
                    "expiration": "20260807",
                    "dte": 43,
                    "bid": 5.8,
                    "ask": 6.05,
                    "spread": 0.25,
                    "spread_pct": 4.22,
                    "delta": -0.19,
                    "quality": "EXECUTABLE",
                }
            ],
        }

        with patch.object(main, "_v31_manual_review_console_decisions", return_value=([decision], {"recent_reviews": []})):
            html = main._v31_manual_review_inbox_html(show_all=True)

        self.assertIn("Alternativas de contrato", html)
        self.assertIn("330", html)
        self.assertIn("No cambian el estado ni autorizan operar", html)

    def test_manual_review_dashboards_render_learning_and_history(self):
        with patch.object(main, "_v31_manual_reviews_payload", return_value={
            "review_count": 1,
            "by_status": {"APPROVED_FOR_MANUAL_TRADE": 1},
            "recent_reviews": [
                {
                    "ticker": "QQQ",
                    "strategy": "NAKED_PUT",
                    "status": "APPROVED_FOR_MANUAL_TRADE",
                    "reviewed_at": "2026-06-25T16:00:00+00:00",
                    "reason": "Validado manualmente.",
                    "decision": {"selected_contract": {"strike": 300, "expiration": "20260717", "bid": 1.2, "ask": 1.35, "spread_pct": 11.76, "delta": -0.2}},
                    "latest_manual_review_evaluation": {"checkpoint": "EOD"},
                    "current_paper_pnl_r": 0.1,
                    "manual_review_learning_label": "APPROVED_WORKED",
                }
            ],
        }):
            history_html = main._v31_manual_reviews_dashboard_html(limit=10)

        self.assertIn("Manual Review History", history_html)
        self.assertIn("APPROVED_FOR_MANUAL_TRADE", history_html)
        self.assertIn("QQQ", history_html)

        with patch.object(main, "_v31_manual_review_learning_payload", return_value={
            "review_count": 1,
            "evaluated_count": 1,
            "unevaluated_count": 0,
            "avg_paper_pnl_r": 0.1,
            "needs_more_data": True,
            "strategy_summary": [{"group": "NAKED_PUT", "review_count": 1, "evaluated_count": 1, "favorable_count": 1, "adverse_count": 0, "avg_paper_pnl_r": 0.1, "avg_mfe_r": 0.2, "avg_mae_r": -0.1}],
            "ticker_summary": [{"group": "QQQ", "review_count": 1, "evaluated_count": 1, "favorable_count": 1, "adverse_count": 0, "avg_paper_pnl_r": 0.1, "avg_mfe_r": 0.2, "avg_mae_r": -0.1}],
            "best_reviews": [{"ticker": "QQQ", "strategy": "NAKED_PUT", "manual_status": "APPROVED_FOR_MANUAL_TRADE", "learning_label": "APPROVED_WORKED", "current_paper_pnl_r": 0.1, "mfe_r": 0.2, "mae_r": -0.1, "checkpoint": "EOD"}],
            "worst_reviews": [],
        }):
            learning_html = main._v31_manual_review_learning_dashboard_html(limit=10)

        self.assertIn("Manual Review Learning", learning_html)
        self.assertIn("NAKED_PUT", learning_html)
        self.assertIn("APPROVED_WORKED", learning_html)

    def test_v32_strategy_performance_dashboard_is_manual_review_only(self):
        with patch.object(main, "_v32_strategy_performance_payload", return_value={
            "generated_at": "2026-06-24T16:00:00+00:00",
            "summary": {
                "strategy_count": 1,
                "decision_count": 2,
                "outcome_count": 3,
                "closed_outcomes": 2,
                "strategy_regime_group_count": 1,
            },
            "strategies": [
                {
                    "strategy": "CASH_SECURED_PUT",
                    "closed_outcomes": 2,
                    "wins": 1,
                    "losses": 1,
                    "win_rate": 50.0,
                    "expectancy_r": 0.1,
                    "avg_mfe_r": 0.6,
                    "avg_mae_r": -0.3,
                    "evidence_level": "INSUFFICIENT_SAMPLE",
                    "parameter_review_ready": False,
                }
            ],
            "strategy_regime_performance": [
                {
                    "group": "CASH_SECURED_PUT::BULLISH_LOW_VOL",
                    "closed_outcomes": 2,
                    "win_rate": 50.0,
                    "expectancy_r": 0.1,
                    "avg_mfe_r": 0.6,
                    "avg_mae_r": -0.3,
                    "evidence_level": "INSUFFICIENT_SAMPLE",
                }
            ],
        }):
            html = main._v32_strategy_performance_dashboard_html(limit=100)

        self.assertIn("V32 Strategy Performance", html)
        self.assertIn("CASH_SECURED_PUT", html)
        self.assertIn("No autoriza", html)

    def test_premarket_page_renders_operator_friendly_state_before_json(self):
        with patch.object(main, "get_intraday_futures_premarket_context", return_value={
            "found": False,
            "context": {},
        }):
            html = main.intraday_futures_premarket_page_html(mode="base", session_date="2026-06-30")

        self.assertIn("Estado", html)
        self.assertIn("Pendiente", html)
        self.assertIn("Lectura operativa", html)
        self.assertIn("Falta cargar el contexto operativo de sesion", html)
        self.assertIn("Siguiente paso", html)
        self.assertIn("Guardar Base defensiva", html)
        self.assertIn("Seleccionar contexto de sesion", html)
        self.assertIn("Inbox revision manual", html)
        self.assertIn("Command Center", html)
        self.assertIn("Ver payload tecnico", html)
        self.assertIn("No autorizadas", html)
        self.assertIn("Necesita revision", html)
        self.assertIn("Aun no hay contexto operativo guardado", html)
        self.assertIn("Todo se carga aqui, sin salir de la consola", html)

    def test_v31_daily_payload_exposes_data_readiness_for_gpt(self):
        with patch.object(main, "_v29_discover_master_snapshot", return_value={
            "path": None,
            "data": {},
            "rows": [],
            "technical": {},
            "score": 0,
        }):
            payload = main._v31_daily_recommendations_payload(["QQQ"])

        self.assertEqual(payload["data_readiness"]["diagnostic_version"], "v31_data_readiness_diagnostic_v1")
        self.assertEqual(payload["data_readiness"]["status"], "NO_DATA")
        self.assertIn("NO_OPTION_ROWS", payload["data_readiness"]["blockers"])
        self.assertEqual(payload["answer_guidance"]["guidance_version"], "super_engine_bolsa_daily_answer_v1")
        self.assertFalse(payload["answer_guidance"]["execution_authorized"])
        self.assertTrue(payload["answer_guidance"]["not_order_instruction"])

    def test_v31_daily_recommendations_preserve_wait_options_priority(self):
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
            payload = main._v31_daily_recommendations_payload(["QQQ"])

        self.assertEqual(payload["engine"], "V31_DAILY_RECOMMENDATION_ENGINE")
        self.assertEqual(payload["items"][0]["final_state"], "WAIT_OPTIONS_DATA")
        self.assertEqual(payload["items"][0]["recommendation_action"], "WAIT_FOR_EXECUTABLE_OPTION_DATA")
        self.assertIn("delta", payload["items"][0]["required_missing_fields"])
        self.assertFalse(payload["items"][0]["can_operate"])
        self.assertTrue(payload["items"][0]["not_order_instruction"])
        self.assertEqual(payload["strategy_playbook"]["registry_version"], "strategy_registry_v1")
        self.assertIn("CASH_SECURED_PUT", payload["strategy_playbook"]["active_manual_review"])
        self.assertEqual(payload["strategy_exit_playbook"]["exit_playbook_version"], "strategy_exit_playbook_v1")
        self.assertIn("COVERED_CALL", payload["strategy_exit_playbook"]["active_exit_strategies"])
        self.assertEqual(payload["strategy_regime_policy"]["regime_policy_version"], "strategy_regime_policy_v1")
        self.assertIn("HIGH_VOL_EVENT_RISK", payload["strategy_regime_policy"]["market_regimes"])
        self.assertTrue(payload["strategy_regime_policy"]["parameter_matrix_available"])
        self.assertEqual(payload["market"]["market_regime"], "BULLISH_LOW_VOL")
        self.assertEqual(payload["market"]["regime_detection"]["detector_version"], "market_regime_detector_v1")
        overlay = payload["items"][0]["strategy_overlay"]
        self.assertEqual(overlay["strategy_id"], "CASH_SECURED_PUT")
        self.assertIn("WAIT_OPTIONS_DATA", overlay["strategy_blockers"])
        self.assertTrue(overlay["not_order_instruction"])
        self.assertFalse(overlay["execution_authorized"])
        regime_overlay = payload["items"][0]["regime_overlay"]
        self.assertEqual(regime_overlay["regime_policy_version"], "strategy_regime_policy_v1")
        self.assertEqual(regime_overlay["strategy_id"], "CASH_SECURED_PUT")
        self.assertEqual(regime_overlay["market_regime"], "BULLISH_LOW_VOL")
        self.assertEqual(regime_overlay["parameter_guidance_state"], "GUIDANCE_AVAILABLE")
        self.assertEqual(regime_overlay["strategy_parameters"]["preferred_abs_delta_max"], 0.2)
        parameter_review = payload["items"][0]["parameter_review"]
        self.assertEqual(parameter_review["status"], "WAIT_OPTIONS_DATA")
        self.assertIn("WAIT_OPTIONS_DATA", parameter_review["blockers"])
        self.assertIn("delta", parameter_review["missing_fields"])
        self.assertIn(regime_overlay["regime_state"], {"REGIME_ALIGNED", "REGIME_CAUTION", "REGIME_BLOCKED", "REGIME_UNSPECIFIED"})
        self.assertTrue(regime_overlay["not_order_instruction"])
        self.assertFalse(regime_overlay["execution_authorized"])

    def test_v31_daily_recommendations_apply_explicit_regime_overlay(self):
        row = {
            "ticker": "SPY",
            "strategy": "INTRADAY_INDEX_FUTURES",
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
        master = _master_snapshot([row])
        master["data"]["market"]["market_regime"] = "HIGH_VOL_EVENT_RISK"

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            payload = main._v31_daily_recommendations_payload(["SPY"])

        overlay = payload["items"][0]["regime_overlay"]
        self.assertEqual(overlay["market_regime"], "HIGH_VOL_EVENT_RISK")
        self.assertEqual(overlay["strategy_id"], "INTRADAY_INDEX_FUTURES")
        self.assertEqual(overlay["regime_state"], "REGIME_BLOCKED")
        self.assertEqual(payload["items"][0]["parameter_review"]["status"], "BLOCKED_BY_REGIME")
        self.assertFalse(overlay["execution_authorized"])

    def test_v31_daily_recommendations_pass_parameter_review_when_aligned(self):
        row = {
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
        master = _master_snapshot([row])
        master["technical"]["QQQ"]["canslim"] = {"passes": True, "score": 78}

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            payload = main._v31_daily_recommendations_payload(["QQQ"])

        review = payload["items"][0]["parameter_review"]
        self.assertEqual(review["status"], "PASS")
        self.assertEqual(review["blockers"], [])
        self.assertTrue(review["not_order_instruction"])
        self.assertFalse(review["execution_authorized"])

    def test_v31_finalizer_enforces_decision_support_only_contract(self):
        decision = {
            "final_state": "ENTRY_READY",
            "decision": "ENTRY_READY",
            "manual_review_ready": False,
            "can_operate": True,
            "warnings": [],
            "blockers": ["STALE_BLOCKER"],
            "selected_contract": {
                "strike": 710,
                "can_operate": True,
                "manual_review_ready": False,
            },
            "source_decision": {"can_operate": True},
        }

        finalized = main._v31_finalize_decision_support_contract(decision)

        self.assertEqual(finalized["final_state"], "ENTRY_READY")
        self.assertTrue(finalized["manual_review_ready"])
        self.assertFalse(finalized["can_operate"])
        self.assertTrue(finalized["not_order_instruction"])
        self.assertEqual(finalized["blockers"], [])
        self.assertIsNone(finalized["main_blocker"])
        self.assertFalse(finalized["selected_contract"]["can_operate"])
        self.assertTrue(finalized["selected_contract"]["manual_review_ready"])
        self.assertFalse(finalized["source_decision"]["can_operate"])
        self.assertIn("NOT_AN_ORDER_INSTRUCTION", finalized["warnings"])

    def test_v31_entry_ready_requires_auditable_source_evidence(self):
        decision = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
            "decision": "ENTRY_READY",
            "manual_review_ready": True,
            "selected_contract": {
                "strike": 710,
                "expiration": "20260717",
                "dte": 33,
                "bid": 1.20,
                "ask": 1.35,
                "delta": -0.20,
            },
        }
        decision = main.shared_source_attribution.apply_source_attribution(decision)

        gated = main._v31_apply_entry_evidence_gate(decision)

        self.assertEqual(gated["final_state"], "WAIT_TECHNICAL")
        self.assertEqual(gated["main_blocker"], "WAIT_TECHNICAL")
        self.assertIn("ENTRY_EVIDENCE_GATE_FAILED", gated["blockers"])
        self.assertIn("MISSING_CONFIRMATION_SOURCE", gated["blockers"])
        self.assertFalse(gated["manual_review_ready"])
        self.assertFalse(gated["selected_contract"]["manual_review_ready"])
        self.assertEqual(gated["entry_evidence_gate"]["status"], "BLOCKED")

    def test_v31_risk_profile_blocks_entry_ready_without_weakening_wait_options(self):
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
            "delta": -0.50,
        }
        incomplete_row = {
            **complete_row,
            "delta": None,
        }

        with patch.dict(main.os.environ, {"V31_MAX_ABS_DELTA": "0.30"}), patch.object(
            main,
            "_v29_discover_master_snapshot",
            return_value=_master_snapshot([complete_row]),
        ):
            blocked = main._v31_canonical_decision("QQQ")

        self.assertEqual(blocked["final_state"], "RISK_BLOCKED")
        self.assertEqual(blocked["main_blocker"], "RISK_BLOCKED")
        self.assertEqual(blocked["risk_blocker"], "RISK_PROFILE_DELTA_TOO_HIGH")
        self.assertIn("RISK_PROFILE_DELTA_TOO_HIGH", blocked["blockers"])
        self.assertEqual(blocked["risk_profile"]["primary_blocker"], "RISK_PROFILE_DELTA_TOO_HIGH")
        self.assertEqual(blocked["risk_profile"]["blocked_checks"][0]["field"], "selected_contract.abs_delta")
        self.assertEqual(blocked["risk_profile"]["blocked_checks"][0]["value"], 0.5)
        self.assertEqual(blocked["risk_profile"]["blocked_checks"][0]["limit"], 0.3)
        self.assertIn("RISK_PROFILE_DELTA_TOO_HIGH", blocked["explanation"])
        self.assertFalse(blocked["manual_review_ready"])
        self.assertFalse(blocked["can_operate"])

        with patch.dict(main.os.environ, {"V31_MAX_ABS_DELTA": "0.30"}), patch.object(
            main,
            "_v29_discover_master_snapshot",
            return_value=_master_snapshot([incomplete_row]),
        ):
            wait_options = main._v31_canonical_decision("QQQ")

        self.assertEqual(wait_options["final_state"], "WAIT_OPTIONS_DATA")
        self.assertEqual(wait_options["main_blocker"], "WAIT_OPTIONS_DATA")
        self.assertIn("WAIT_OPTIONS_DATA", wait_options["blockers"])
        self.assertNotIn("risk_blocker", wait_options)
        self.assertFalse(wait_options["manual_review_ready"])
        self.assertFalse(wait_options["can_operate"])

    def test_v31_balanced_profile_is_not_looser_than_strategy_specific_put_guard(self):
        complete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 710,
            "expiration": "20260717",
            "dte": 26,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": -0.20,
        }

        with patch.object(
            main,
            "_v29_discover_master_snapshot",
            return_value=_master_snapshot([complete_row]),
        ):
            blocked = main._v31_canonical_decision("QQQ")

        self.assertEqual(blocked["final_state"], "RISK_BLOCKED")
        self.assertEqual(blocked["risk_blocker"], "RISK_PROFILE_DTE_TOO_LOW")
        self.assertEqual(blocked["risk_profile"]["primary_blocker"], "RISK_PROFILE_DTE_TOO_LOW")
        self.assertFalse(blocked["manual_review_ready"])

    def test_v31_broker_check_blocks_entry_ready_when_account_context_conflicts(self):
        complete_row = {
            "ticker": "TSLA",
            "strategy": "COVERED_CALL",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 440,
            "expiration": "20260717",
            "dte": 33,
            "bid": 13.20,
            "ask": 13.35,
            "mid": 13.275,
            "spread": 0.15,
            "spread_pct": 1.13,
            "delta": 0.20,
        }
        master = _master_snapshot([complete_row])
        master["technical"] = {
            "TSLA": {
                "ticker": "TSLA",
                "trend": "BULLISH",
                "score": 80,
            }
        }
        master["data"]["broker_checks"] = [
            {
                "broker_check_version": "broker_check_v1",
                "ticker": "TSLA",
                "strategy": "COVERED_CALL",
                "status": "BLOCKED",
                "ok_for_manual_review": False,
                "blockers": ["BROKER_COVERED_CALL_SHARES_INSUFFICIENT"],
                "warnings": [],
                "execution_authorized": False,
                "not_order_instruction": True,
            }
        ]

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            decision = main._v31_canonical_decision("TSLA")

        self.assertEqual(decision["final_state"], "RISK_BLOCKED")
        self.assertEqual(decision["main_blocker"], "RISK_BLOCKED")
        self.assertEqual(decision["risk_blocker"], "BROKER_CHECK_BLOCKED")
        self.assertIn("BROKER_CHECK_BLOCKED", decision["blockers"])
        self.assertIn("BROKER_COVERED_CALL_SHARES_INSUFFICIENT", decision["blockers"])
        self.assertEqual(decision["broker_check"]["status"], "BLOCKED")
        self.assertFalse(decision["manual_review_ready"])
        self.assertFalse(decision["can_operate"])

    def test_v31_event_assignment_gate_blocks_covered_call_ex_dividend(self):
        complete_row = {
            "ticker": "TSLA",
            "strategy": "COVERED_CALL",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 440,
            "expiration": "20260717",
            "dte": 33,
            "bid": 13.20,
            "ask": 13.35,
            "mid": 13.275,
            "spread": 0.15,
            "spread_pct": 1.13,
            "delta": 0.20,
        }
        master = _master_snapshot([complete_row])
        master["technical"] = {
            "TSLA": {
                "ticker": "TSLA",
                "trend": "BULLISH",
                "score": 80,
                "by_strategy_context": {
                    "COVERED_CALL": {
                        "trend": "BULLISH",
                        "score": 80,
                        "ex_dividend_soon": True,
                        "assignment_acceptable": True,
                    }
                },
            }
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            decision = main._v31_canonical_decision("TSLA")
            payload = main._v31_daily_recommendations_payload(["TSLA"])

        self.assertEqual(decision["final_state"], "RISK_BLOCKED")
        self.assertEqual(decision["risk_blocker"], "EX_DIVIDEND_WITHIN_WINDOW")
        self.assertIn("EX_DIVIDEND_WITHIN_WINDOW", decision["blockers"])
        self.assertTrue(decision["market"]["ex_dividend_soon"])
        self.assertEqual(payload["items"][0]["parameter_review"]["status"], "REVIEW_REQUIRED")
        self.assertIn("AVOID_IF_EX_DIVIDEND_WITHIN_WINDOW", payload["items"][0]["parameter_review"]["blockers"])

    def test_v31_event_assignment_gate_blocks_put_when_assignment_unacceptable(self):
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
        master = _master_snapshot([complete_row])
        master["technical"]["QQQ"]["by_strategy_context"] = {
            "NAKED_PUT": {
                "trend": "BULLISH",
                "score": 80,
                "assignment_acceptable": False,
            }
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            decision = main._v31_canonical_decision("QQQ")
            payload = main._v31_daily_recommendations_payload(["QQQ"])

        self.assertEqual(decision["final_state"], "RISK_BLOCKED")
        self.assertEqual(decision["risk_blocker"], "ASSIGNMENT_UNACCEPTABLE")
        self.assertIn("ASSIGNMENT_UNACCEPTABLE", decision["blockers"])
        self.assertEqual(decision["market"]["assignment_acceptable"], False)
        self.assertEqual(payload["items"][0]["parameter_review"]["status"], "REVIEW_REQUIRED")
        self.assertIn("AVOID_IF_ASSIGNMENT_UNACCEPTABLE", payload["items"][0]["parameter_review"]["blockers"])

    def test_v31_stale_broker_check_blocks_entry_ready(self):
        complete_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "decision": "ENTRY_READY",
            "score": 90,
            "strike": 300,
            "expiration": "20260717",
            "dte": 33,
            "bid": 1.20,
            "ask": 1.35,
            "mid": 1.275,
            "spread": 0.15,
            "spread_pct": 11.76,
            "delta": -0.20,
        }
        master = _master_snapshot([complete_row])
        old = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        master["data"]["broker_checks"] = [
            {
                "broker_check_version": "broker_check_v1",
                "generated_at": old,
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "status": "OK",
                "ok_for_manual_review": True,
                "blockers": [],
                "warnings": [],
                "execution_authorized": False,
                "not_order_instruction": True,
            }
        ]

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            decision = main._v31_canonical_decision("QQQ")

        self.assertEqual(decision["final_state"], "RISK_BLOCKED")
        self.assertEqual(decision["risk_blocker"], "BROKER_CHECK_STALE")
        self.assertIn("BROKER_CHECK_STALE", decision["blockers"])
        self.assertEqual(decision["broker_check"]["freshness"]["status"], "STALE")
        self.assertFalse(decision["manual_review_ready"])

    def test_v31_manual_approval_rejects_blocked_broker_check(self):
        decision = {
            "ticker": "TSLA",
            "strategy": "COVERED_CALL",
            "final_state": "ENTRY_READY",
            "manual_review_ready": True,
            "broker_check": {
                "status": "BLOCKED",
                "blockers": ["BROKER_COVERED_CALL_SHARES_INSUFFICIENT"],
                "warnings": [],
                "execution_authorized": False,
                "not_order_instruction": True,
            },
            "selected_contract": {
                "strike": 440,
                "expiration": "20260717",
                "dte": 33,
                "bid": 13.20,
                "ask": 13.35,
                "mid": 13.275,
                "spread": 0.15,
                "spread_pct": 1.13,
                "delta": 0.34,
            },
        }

        with self.assertRaisesRegex(ValueError, "APPROVAL_REQUIRES_BROKER_CHECK_NOT_BLOCKED"):
            main._v31_manual_review_payload({
                "ticker": "TSLA",
                "status": "APPROVED_FOR_MANUAL_TRADE",
                "decision": decision,
            })

    def test_v31_manual_approval_requires_strict_fresh_complete_checks(self):
        fresh = datetime.now(timezone.utc).isoformat()
        decision = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
            "technical_status": "CONFIRMED",
            "risk_status": "PASS",
            "manual_review_ready": True,
            "broker_check": {
                "generated_at": fresh,
                "status": "OK",
                "blockers": [],
                "warnings": [],
                "execution_authorized": False,
                "not_order_instruction": True,
            },
            "selected_contract": {
                "strike": 300,
                "expiration": "20260717",
                "dte": 33,
                "bid": 1.20,
                "ask": 1.35,
                "mid": 1.275,
                "spread": 0.15,
                "spread_pct": 11.76,
                "delta": -0.20,
            },
        }

        approved = main._v31_manual_review_payload({
            "ticker": "QQQ",
            "status": "APPROVED_FOR_MANUAL_TRADE",
            "reason": "Validé contrato, liquidez, riesgo y ticket manual en TWS.",
            "decision": decision,
        })

        self.assertEqual(approved["status"], "APPROVED_FOR_MANUAL_TRADE")
        self.assertFalse(approved["execution_authorized"])
        self.assertTrue(approved["not_order_instruction"])

        with self.assertRaisesRegex(ValueError, "APPROVAL_REQUIRES_REVIEW_REASON"):
            main._v31_manual_review_payload({
                "ticker": "QQQ",
                "status": "APPROVED_FOR_MANUAL_TRADE",
                "reason": "",
                "decision": decision,
            })

    def test_v31_manual_approval_rejects_unknown_or_stale_broker_check(self):
        base = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
            "technical_status": "CONFIRMED",
            "risk_status": "PASS",
            "manual_review_ready": True,
            "selected_contract": {
                "strike": 300,
                "expiration": "20260717",
                "dte": 33,
                "bid": 1.20,
                "ask": 1.35,
                "mid": 1.275,
                "spread": 0.15,
                "spread_pct": 11.76,
                "delta": -0.20,
            },
        }
        unknown = {**base, "broker_check": {"status": "UNKNOWN"}}
        stale = {
            **base,
            "broker_check": {
                "status": "OK",
                "generated_at": (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat(),
            },
        }

        with self.assertRaisesRegex(ValueError, "APPROVAL_REQUIRES_BROKER_CHECK_AVAILABLE"):
            main._v31_manual_review_payload({
                "ticker": "QQQ",
                "status": "APPROVED_FOR_MANUAL_TRADE",
                "reason": "Validado",
                "decision": unknown,
            })
        approved_unknown_with_manual_override = main._v31_manual_review_payload({
            "ticker": "QQQ",
            "status": "APPROVED_FOR_MANUAL_TRADE",
            "reason": "Validé manualmente contrato, liquidez, spread, eventos, riesgo de cuenta y ticket en TWS.",
            "decision": unknown,
            "manual_broker_validation_override": True,
        })
        self.assertEqual(approved_unknown_with_manual_override["status"], "APPROVED_FOR_MANUAL_TRADE")
        self.assertTrue(approved_unknown_with_manual_override["manual_broker_validation_override"])
        self.assertFalse(approved_unknown_with_manual_override["execution_authorized"])
        self.assertTrue(approved_unknown_with_manual_override["not_order_instruction"])
        with self.assertRaisesRegex(ValueError, "APPROVAL_REQUIRES_FRESH_BROKER_CHECK"):
            main._v31_manual_review_payload({
                "ticker": "QQQ",
                "status": "APPROVED_FOR_MANUAL_TRADE",
                "reason": "Validado",
                "decision": stale,
            })

    def test_v31_entry_ready_signal_tracking_creates_pending_paper_outcome(self):
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
        master = _master_snapshot([complete_row])
        master["technical"]["QQQ"]["canslim"] = {"passes": True, "score": 78}

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            decision = main._v31_canonical_decision("QQQ")

        with patch.object(main, "_journal_outcome", return_value={"saved": True, "status": "SAVED"}) as journal:
            tracking = main._v31_track_entry_ready_signal(decision, source="unit_test")

        self.assertEqual(tracking["status"], "TRACKED")
        self.assertTrue(tracking["enabled"])
        self.assertEqual(tracking["outcome"]["outcome"], "PENDING")
        self.assertTrue(tracking["outcome"]["paper_outcome"])
        self.assertEqual(tracking["outcome"]["final_state"], "ENTRY_READY")
        self.assertEqual(tracking["outcome"]["market_regime"], "BULLISH_LOW_VOL")
        self.assertEqual(tracking["outcome"]["regime_overlay"]["market_regime"], "BULLISH_LOW_VOL")
        self.assertEqual(tracking["outcome"]["parameter_review_status"], "PASS")
        self.assertEqual(tracking["outcome"]["parameter_review"]["status"], "PASS")
        self.assertEqual(tracking["outcome"]["parameter_review_blockers"], [])
        self.assertEqual(tracking["outcome"]["exit_regime_guidance_state"], "GUIDANCE_AVAILABLE")
        self.assertEqual(tracking["outcome"]["exit_regime_guidance"]["market_regime"], "BULLISH_LOW_VOL")
        self.assertEqual(
            tracking["outcome"]["exit_regime_guidance"]["regime_exit_adjustment"]["risk_action"],
            "MONITOR_SUPPORT_AND_EVENT_RISK",
        )
        self.assertEqual(tracking["outcome"]["measurement_plan"]["exit_guidance_state"], "GUIDANCE_AVAILABLE")
        self.assertEqual(tracking["outcome"]["measurement_plan"]["exit_risk_action"], "MONITOR_SUPPORT_AND_EVENT_RISK")
        self.assertIn("SIG-", tracking["signal_id"])
        self.assertTrue(tracking["not_order_instruction"])
        journal.assert_called_once()

    def test_v31_non_entry_signal_tracking_is_skipped(self):
        tracking = main._v31_track_entry_ready_signal({
            "final_state": "WAIT_OPTIONS_DATA",
            "ticker": "QQQ",
            "not_order_instruction": True,
        })

        self.assertEqual(tracking["status"], "NOT_ENTRY_READY")
        self.assertFalse(tracking["enabled"])

    def test_v31_outcome_tracking_status_reports_pending_entry_ready_signals(self):
        rows = [
            {
                "outcome_tracking_version": "v31_entry_ready_signal_outcome_v1",
                "outcome": "PENDING",
                "ticker": "QQQ",
                "market_regime": "BULLISH_LOW_VOL",
                "parameter_review_status": "PASS",
                "not_order_instruction": True,
            },
            {
                "outcome_tracking_version": "other",
                "outcome": "PENDING",
            },
        ]

        with patch.object(main, "_durable_supabase_fetch", return_value=rows):
            status = asyncio.run(main.v31_outcome_tracking_status())

        self.assertEqual(status["engine"], "V31_OUTCOME_TRACKING_STATUS")
        self.assertEqual(status["tracked_entry_ready_signals"], 1)
        self.assertEqual(status["pending_entry_ready_signals"], 1)
        self.assertEqual(status["by_market_regime"], {"BULLISH_LOW_VOL": 1})
        self.assertEqual(status["by_parameter_review_status"], {"PASS": 1})
        self.assertTrue(status["not_order_instruction"])

    def test_v31_auto_evaluates_pending_outcome_from_current_snapshot(self):
        pending = {
            "outcome_tracking_version": "v31_entry_ready_signal_outcome_v1",
            "outcome": "PENDING",
            "outcome_id": "SIG-2026-06-22-QQQ-NAKED_PUT-20260717-710",
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "paper_outcome": True,
            "selected_contract": {
                "strike": 710,
                "expiration": "20260717",
                "mid": 1.25,
                "spread_pct": 11.76,
                "delta": -0.20,
            },
            "not_order_instruction": True,
        }
        current_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "strike": 710,
            "expiration": "20260717",
            "bid": 0.70,
            "ask": 0.80,
            "mid": 0.75,
            "spread_pct": 13.33,
            "delta": -0.12,
            "underlying_price": 725.0,
        }
        master = _master_snapshot([current_row])

        result = main._v31_evaluate_pending_outcome(pending, master, checkpoint="PLUS_1D")

        self.assertEqual(result["status"], "EVALUATED")
        outcome = result["outcome"]
        self.assertEqual(outcome["outcome"], "PENDING")
        self.assertEqual(outcome["outcome_engine_version"], "v31_pending_outcome_auto_eval_v1")
        self.assertEqual(outcome["current_paper_pnl_r"], 0.4)
        self.assertEqual(outcome["mfe_r"], 0.4)
        self.assertEqual(outcome["mae_r"], 0.0)
        self.assertEqual(outcome["latest_auto_evaluation"]["checkpoint"], "PLUS_1D")
        self.assertTrue(outcome["not_order_instruction"])
        self.assertFalse(outcome["execution_authorized"])

    def test_v31_auto_evaluate_pending_outcomes_persists_evaluated_paper_updates(self):
        pending = {
            "outcome_tracking_version": "v31_entry_ready_signal_outcome_v1",
            "outcome": "PENDING",
            "outcome_id": "SIG-2026-06-22-QQQ-NAKED_PUT-20260717-710",
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "paper_outcome": True,
            "selected_contract": {
                "strike": 710,
                "expiration": "20260717",
                "mid": 1.25,
                "delta": -0.20,
            },
            "not_order_instruction": True,
        }
        current_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "strike": 710,
            "expiration": "20260717",
            "bid": 0.70,
            "ask": 0.80,
            "mid": 0.75,
            "spread_pct": 13.33,
            "delta": -0.12,
        }
        master = _master_snapshot([current_row])

        with patch.object(main, "_durable_supabase_fetch", return_value=[pending]), \
                patch.object(main, "_v29_discover_master_snapshot", return_value=master), \
                patch.object(main, "_journal_outcome", return_value={"saved": True, "status": "SAVED"}) as journal:
            payload = main._v31_auto_evaluate_pending_outcomes(limit=10, checkpoint="EOD", dry_run=False)

        self.assertEqual(payload["engine"], "V31_PENDING_OUTCOME_AUTO_EVALUATION")
        self.assertEqual(payload["evaluated_count"], 1)
        self.assertEqual(payload["saved_count"], 1)
        self.assertTrue(payload["not_order_instruction"])
        self.assertFalse(payload["execution_authorized"])
        journal.assert_called_once()

        with patch.object(main, "_durable_supabase_fetch", return_value=[pending]), \
                patch.object(main, "_v29_discover_master_snapshot", return_value=master), \
                patch.object(main, "_journal_outcome") as dry_journal:
            dry_payload = main._v31_auto_evaluate_pending_outcomes(limit=10, checkpoint="EOD", dry_run=True)

        self.assertEqual(dry_payload["evaluated_count"], 1)
        self.assertEqual(dry_payload["saved_count"], 0)
        dry_journal.assert_not_called()

    def test_v31_production_readiness_blocks_without_read_token(self):
        with patch.object(main, "REQUIRE_READ_AUTH", True), patch.object(
            main,
            "READ_ACCESS_TOKEN",
            "",
        ), patch.object(main, "ADMIN_DEBUG_TOKEN", ""), patch.object(
            main,
            "SNAPSHOT_INGEST_TOKEN",
            "configured",
        ), patch.object(main, "REQUIRE_SNAPSHOT_INGEST_TOKEN", True), patch.object(
            main,
            "OPERATING_MODE",
            "ANALYSIS_ONLY",
        ):
            readiness = main._v31_production_readiness_payload()

        self.assertEqual(readiness["status"], "BLOCKED")
        blocker_names = {item["name"] for item in readiness["blockers"]}
        self.assertIn("read_auth_token_configured", blocker_names)
        self.assertTrue(readiness["read_auth"]["required"])
        self.assertTrue(readiness["read_auth"]["critical_endpoints_protected"])
        self.assertTrue(readiness["not_order_instruction"])

    def test_v31_production_readiness_ready_with_required_auth_and_token(self):
        with patch.object(main, "REQUIRE_READ_AUTH", True), patch.object(
            main,
            "READ_ACCESS_TOKEN",
            "read-token",
        ), patch.object(main, "ADMIN_DEBUG_TOKEN", ""), patch.object(
            main,
            "SNAPSHOT_INGEST_TOKEN",
            "ingest-token",
        ), patch.object(main, "REQUIRE_SNAPSHOT_INGEST_TOKEN", True), patch.object(
            main,
            "OPERATING_MODE",
            "ANALYSIS_ONLY",
        ):
            readiness = main._v31_production_readiness_payload()

        self.assertEqual(readiness["status"], "READY")
        self.assertEqual(readiness["production_readiness_version"], "v31_production_readiness_v2")
        self.assertTrue(readiness["snapshot_ingest_auth"]["required"])
        self.assertTrue(readiness["snapshot_ingest_auth"]["token_configured"])
        self.assertTrue(readiness["read_auth"]["critical_endpoints_protected"])
        self.assertEqual(readiness["risk_profile"]["profile_version"], "v31_risk_profile_v1")
        self.assertEqual(readiness["outcome_tracking"]["version"], "v31_entry_ready_signal_outcome_v1")
        self.assertEqual(readiness["outcome_tracking"]["auto_evaluation_version"], "v31_pending_outcome_auto_eval_v1")
        self.assertEqual(readiness["outcome_tracking"]["auto_evaluation_endpoint"], "/v31_evaluate_pending_outcomes")
        self.assertTrue(readiness["token_rotation"]["required_for_hygiene"])

    def test_read_auth_browser_endpoint_redirects_to_login(self):
        request = _FakeBrowserRequest("/v31_manual_review_inbox")

        response = main._read_auth_login_redirect(request)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.url, "/read_auth_login?next=%2Fv31_manual_review_inbox")

    def test_read_auth_gpt_endpoint_does_not_redirect_to_login(self):
        request = _FakeBrowserRequest("/gpt_v31_daily_answer")

        response = main._read_auth_login_redirect(request)

        self.assertIsNone(response)

    def test_v31_ingest_endpoints_keep_snapshot_auth_separate_from_read_auth(self):
        with patch.object(main, "REQUIRE_READ_AUTH", True):
            self.assertFalse(main._path_requires_read_auth("/v31_ingest_snapshot"))
            self.assertFalse(main._path_requires_read_auth("/v28_ingest_snapshot"))
            self.assertFalse(main._path_requires_read_auth("/decision_desk/ingest"))
            self.assertTrue(main._path_requires_read_auth("/v31_decision/SPY"))
            self.assertTrue(main._path_requires_read_auth("/v31_production_readiness"))
            self.assertTrue(main._path_requires_read_auth("/v31_manual_review_learning"))
            self.assertTrue(main._path_requires_read_auth("/v31_trading_day_readiness"))

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
            "account_context": {"net_liquidation": 123456, "buying_power": 50000},
            "positions": [{"ticker": "TLT", "size": 700}],
        })

        self.assertEqual(durable["source"], "UNIT_TEST")
        self.assertTrue(durable["not_order_instruction"])
        self.assertNotIn("account_id", durable)
        self.assertNotIn("account_context", durable)
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
        self.assertEqual(status["freshness"]["status"], "MISSING")
        self.assertTrue(status["not_order_instruction"])

    def test_v31_trading_day_readiness_flags_entry_ready_with_fresh_snapshot(self):
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
        master = _master_snapshot([complete_row])
        master["data"]["received_at"] = main._v29_now()

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master), \
                patch.object(main, "_v31_production_readiness_payload", return_value={"status": "READY", "blockers": [], "not_order_instruction": True}):
            readiness = main._v31_trading_day_readiness_payload(max_open_snapshot_age_minutes=10)

        self.assertEqual(readiness["engine"], "V31_TRADING_DAY_READINESS")
        self.assertEqual(readiness["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertEqual(readiness["freshness"]["status"], "FRESH")
        self.assertEqual(readiness["pipeline"]["status"], "OK")
        self.assertEqual(readiness["summary"]["entry_ready_count"], 1)
        self.assertEqual(readiness["monitor"]["entry_ready_tickers"], ["QQQ"])
        self.assertFalse(readiness["execution_authorized"])
        self.assertTrue(readiness["not_order_instruction"])

    def test_v31_system_status_sanitizes_operational_flags_from_technical_raw(self):
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
        master = _master_snapshot([complete_row])
        master["technical"]["QQQ"]["can_operate"] = True
        master["technical"]["QQQ"]["execution_authorized"] = True
        master["technical"]["QQQ"]["by_strategy_context"] = {
            "NAKED_PUT": {
                "score": 90,
                "trend": "BULLISH",
                "can_trade": True,
            },
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master):
            status = main._v31_system_status_payload(tickers=["QQQ"])

        raw = status["decisions"][0]["technical"]["raw"]
        self.assertNotIn("can_operate", raw)
        self.assertNotIn("execution_authorized", raw)
        self.assertNotIn("can_trade", raw["by_strategy_context"]["NAKED_PUT"])
        self.assertEqual(raw["operational_fields_removed"], ["can_operate", "can_trade", "execution_authorized"])
        self.assertEqual(raw["by_strategy_context"]["NAKED_PUT"]["operational_fields_removed"], ["can_trade"])
        self.assertFalse(status["decisions"][0]["can_operate"])
        self.assertTrue(status["not_order_instruction"])

    def test_v31_trading_day_readiness_blocks_stale_snapshot_during_market(self):
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
        master = _master_snapshot([complete_row])
        master["data"]["received_at"] = "2026-01-01T00:00:00+00:00"

        with patch.object(main, "_v29_discover_master_snapshot", return_value=master), \
                patch.object(main, "_v31_production_readiness_payload", return_value={"status": "READY", "blockers": [], "not_order_instruction": True}):
            readiness = main._v31_trading_day_readiness_payload(max_open_snapshot_age_minutes=10)

        self.assertEqual(readiness["status"], "ACTION_REQUIRED")
        self.assertEqual(readiness["freshness"]["status"], "STALE")
        self.assertIn("STALE_SNAPSHOT", readiness["blockers"])
        self.assertFalse(readiness["execution_authorized"])
        self.assertTrue(readiness["not_order_instruction"])

    def test_v31_trading_day_readiness_waits_pipeline_when_snapshot_missing(self):
        empty_master = {
            "path": None,
            "data": {},
            "rows": [],
            "technical": {},
            "score": 0,
        }

        with patch.object(main, "_v29_discover_master_snapshot", return_value=empty_master), \
                patch.object(main, "_v31_production_readiness_payload", return_value={"status": "READY", "blockers": [], "not_order_instruction": True}):
            readiness = main._v31_trading_day_readiness_payload()

        self.assertEqual(readiness["status"], "WAIT_PIPELINE")
        self.assertEqual(readiness["freshness"]["status"], "MISSING")
        self.assertIn("SNAPSHOT_MISSING", readiness["warnings"])
        self.assertIn("PIPELINE_NOT_READY", readiness["warnings"])
        self.assertFalse(readiness["execution_authorized"])
        self.assertTrue(readiness["not_order_instruction"])

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
        self.assertEqual(monitor["entry_ready_decisions"][0]["contract"]["strike"], 710)
        self.assertEqual(monitor["entry_ready_decisions"][0]["contract"]["bid"], 1.20)
        self.assertEqual(monitor["entry_ready_decisions"][0]["contract"]["ask"], 1.35)
        self.assertEqual(monitor["entry_ready_decisions"][0]["contract"]["delta"], -0.20)
        self.assertFalse(monitor["entry_ready_decisions"][0]["can_operate"])
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
        self.assertIn("dedupe", preview)
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
            "entry_ready_decisions": [
                {
                    "ticker": "QQQ",
                    "strategy": "NAKED_PUT",
                    "final_state": "ENTRY_READY",
                    "main_blocker": None,
                    "manual_review_ready": True,
                    "can_operate": False,
                    "technical_status": "CONFIRMED",
                    "risk_status": "PASS",
                    "construction_status": "CONTRACT_SELECTED",
                    "contract": {
                        "strike": 710,
                        "expiration": "20260717",
                        "dte": 33,
                        "bid": 1.20,
                        "ask": 1.35,
                        "mid": 1.275,
                        "spread": 0.15,
                        "spread_pct": 11.76,
                        "delta": -0.20,
                    },
                    "not_order_instruction": True,
                }
            ],
            "risk_blocked_tickers": [],
            "risk_blocked_decisions": [],
            "wait_options_tickers": [],
            "wait_options_decisions": [],
            "message": "Hay setups ENTRY_READY para revision manual.",
            "next_required_action": "Revisar consola.",
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_monitor_status_payload", return_value=monitor):
            with patch.object(main, "_v31_load_monitor_notify_state", return_value={}):
                with patch.object(main, "_v31_save_monitor_notify_state", return_value=True):
                    with patch.object(main, "send_resend_email", return_value={"email_sent": True, "provider": "test"}) as send_email:
                        result = main._v31_monitor_notify_payload(to_email="test@example.com")

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["notify_reason"], "ACTION_REQUIRED")
        self.assertTrue(result["email_sent"])
        sent_args = send_email.call_args.args
        self.assertIn("strike=710", sent_args[2])
        self.assertIn("bid/ask=1.2/1.35", sent_args[2])
        self.assertIn("delta=-0.2", sent_args[2])
        self.assertIn("/v31_manual_review", sent_args[2])
        self.assertIn("APPROVED_FOR_MANUAL_TRADE", sent_args[2])
        self.assertIn("execution_authorized=false", sent_args[2])
        self.assertIn("/v31_decision/QQQ", sent_args[3])
        self.assertIn("/v31_manual_review", sent_args[3])
        self.assertIn("710", sent_args[3])
        self.assertIn("1.35", sent_args[3])
        self.assertIn("-0.2", sent_args[3])
        self.assertTrue(result["not_order_instruction"])
        send_email.assert_called_once()

    def test_v31_monitor_notify_sends_warning_blocker_summary(self):
        monitor = {
            "engine": "V31_PIPELINE_MONITOR",
            "generated_at": "2026-06-12T00:00:00+00:00",
            "alert_level": "WARNING",
            "pipeline_status": "OK",
            "market_context": "REGULAR_MARKET_HOURS",
            "master_snapshot_available": True,
            "master_source": "runtime/v28_master_snapshot.json",
            "rows_found": 1,
            "technical_count": 1,
            "manual_review_ready_count": 0,
            "entry_ready_tickers": [],
            "entry_ready_decisions": [],
            "risk_blocked_tickers": ["MSFT"],
            "risk_blocked_decisions": [
                {
                    "ticker": "MSFT",
                    "strategy": "NAKED_PUT",
                    "final_state": "RISK_BLOCKED",
                    "main_blocker": "RISK_BLOCKED",
                    "primary_block_reason": "RISK_PROFILE_SPREAD_TOO_WIDE: spread actual=0.4 requiere <= 0.35",
                    "manual_review_ready": False,
                    "can_operate": False,
                    "technical_status": "CONFIRMED",
                    "risk_status": "RISK_BLOCKED",
                    "construction_status": "CONTRACT_SELECTED",
                    "contract": {
                        "strike": 415,
                        "expiration": "20260717",
                        "dte": 35,
                        "bid": 1.45,
                        "ask": 1.62,
                        "mid": 1.535,
                        "spread": 0.17,
                        "spread_pct": 11.07,
                        "delta": -0.24,
                    },
                    "not_order_instruction": True,
                }
            ],
            "wait_options_tickers": [],
            "wait_options_decisions": [],
            "blocked_cause_groups": [
                {
                    "cause": "broker_capacity",
                    "bucket": "broker_capacity",
                    "label": "Capacidad broker / buying power",
                    "count": 1,
                    "tickers": ["MSFT"],
                    "examples": [
                        {
                            "ticker": "MSFT",
                            "strategy": "NAKED_PUT",
                            "primary_block_reason": "Broker check: PUT_CAPACITY_CHECK actual=25000 requiere=36500 faltante=11500 capacidad_requerida=146.0%",
                        }
                    ],
                }
            ],
            "message": "Hay setups bloqueados por riesgo.",
            "next_required_action": "Validar blockers.",
            "not_order_instruction": True,
        }

        with patch.object(main, "_v31_monitor_status_payload", return_value=monitor):
            with patch.object(main, "_v31_load_monitor_notify_state", return_value={}):
                with patch.object(main, "_v31_save_monitor_notify_state", return_value=True):
                    with patch.object(main, "send_resend_email", return_value={"email_sent": True}) as send_email:
                        result = main._v31_monitor_notify_payload()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["notify_reason"], "BLOCKED_OR_WAITING_SUMMARY")
        sent_args = send_email.call_args.args
        self.assertIn("razon=RISK_PROFILE_SPREAD_TOO_WIDE", sent_args[2])
        self.assertIn("Bloqueos por causa:", sent_args[2])
        self.assertIn("broker_capacity", sent_args[2])
        self.assertIn("Razon principal", sent_args[3])
        self.assertIn("Bloqueos por causa", sent_args[3])
        self.assertIn("Broker check: PUT_CAPACITY_CHECK", sent_args[3])
        self.assertIn("execution_authorized=false", sent_args[2])
        self.assertTrue(result["not_order_instruction"])

    def test_v31_monitor_notify_dedupes_recent_actionable_alert(self):
        monitor = {
            "engine": "V31_PIPELINE_MONITOR",
            "generated_at": "2026-06-22T14:00:00+00:00",
            "alert_level": "ACTION_REQUIRED",
            "pipeline_status": "OK",
            "market_context": "REGULAR_MARKET_HOURS",
            "master_snapshot_available": True,
            "manual_review_ready_count": 1,
            "entry_ready_tickers": ["SPY"],
            "risk_blocked_tickers": [],
            "wait_options_tickers": [],
            "message": "Hay setups ENTRY_READY para revision manual.",
            "next_required_action": "Revisar consola.",
            "not_order_instruction": True,
        }
        alert_key = "ACTION_REQUIRED|OK|SPY|||"
        state = {
            alert_key: {
                "sent_at": main._v29_now(),
                "notify_reason": "ACTION_REQUIRED",
                "status": "sent",
            }
        }

        with patch.object(main, "_v31_monitor_status_payload", return_value=monitor):
            with patch.object(main, "_v31_load_monitor_notify_state", return_value=state):
                with patch.object(main, "send_resend_email") as send_email:
                    result = main._v31_monitor_notify_payload()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "DEDUPED_RECENT_ALERT")
        self.assertFalse(result["email_sent"])
        self.assertTrue(result["dedupe"]["deduped"])
        send_email.assert_not_called()

    def test_v31_monitor_notify_force_bypasses_dedupe(self):
        monitor = {
            "engine": "V31_PIPELINE_MONITOR",
            "generated_at": "2026-06-22T14:00:00+00:00",
            "alert_level": "ACTION_REQUIRED",
            "pipeline_status": "OK",
            "market_context": "REGULAR_MARKET_HOURS",
            "master_snapshot_available": True,
            "manual_review_ready_count": 1,
            "entry_ready_tickers": ["SPY"],
            "risk_blocked_tickers": [],
            "wait_options_tickers": [],
            "message": "Hay setups ENTRY_READY para revision manual.",
            "next_required_action": "Revisar consola.",
            "not_order_instruction": True,
        }
        alert_key = "ACTION_REQUIRED|OK|SPY|||"
        state = {alert_key: {"sent_at": main._v29_now()}}

        with patch.object(main, "_v31_monitor_status_payload", return_value=monitor):
            with patch.object(main, "_v31_load_monitor_notify_state", return_value=state):
                with patch.object(main, "_v31_save_monitor_notify_state", return_value=True):
                    with patch.object(main, "send_resend_email", return_value={"email_sent": True}) as send_email:
                        result = main._v31_monitor_notify_payload(force=True)

        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["email_sent"])
        self.assertFalse(result["dedupe"]["deduped"])
        send_email.assert_called_once()

    def test_v31_manual_review_records_human_decision_without_authorizing_execution(self):
        decision = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "ENTRY_READY",
            "decision_version": "V31",
            "ruleset_version": "V31",
            "snapshot_version": "V31",
            "generated_at": "2026-06-22T14:00:00+00:00",
            "manual_review_ready": True,
            "technical_status": "CONFIRMED",
            "risk_status": "PASS",
            "main_blocker": None,
            "blockers": [],
            "selected_contract": {
                "strike": 710,
                "expiration": "20260717",
                "dte": 33,
                "bid": 1.20,
                "ask": 1.35,
                "mid": 1.275,
                "spread": 0.15,
                "spread_pct": 11.76,
                "delta": -0.20,
            },
        }

        with patch.object(main, "_v31_load_manual_reviews", return_value=[]):
            with patch.object(main, "_v31_save_manual_reviews", return_value=True) as save_reviews:
                with patch.object(main, "_journal_outcome", return_value={"saved": True}) as journal:
                    with patch.object(main, "_record_audit_event", return_value={"event_id": "AUD-1"}) as audit:
                        result = main._v31_record_manual_review({
                            "ticker": "QQQ",
                            "status": "REJECTED",
                            "reason": "Earnings too close; passing manually.",
                            "actor": "ernesto",
                            "decision": decision,
                        })

        review = result["review"]
        self.assertEqual(result["engine"], "V31_MANUAL_REVIEW_JOURNAL")
        self.assertEqual(result["status"], "RECORDED")
        self.assertEqual(review["status"], "REJECTED")
        self.assertEqual(review["outcome"], "REJECTED")
        self.assertEqual(review["ticker"], "QQQ")
        self.assertEqual(review["decision"]["selected_contract"]["strike"], 710)
        self.assertFalse(review["can_operate"])
        self.assertFalse(review["execution_authorized"])
        self.assertTrue(review["not_order_instruction"])
        self.assertEqual(review["outcome_tracking_version"], "v31_manual_review_journal_v1")
        save_reviews.assert_called_once()
        journal.assert_called_once()
        audit.assert_called_once()

    def test_v31_manual_review_prevents_approval_when_not_entry_ready(self):
        decision = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "final_state": "WAIT_OPTIONS_DATA",
            "manual_review_ready": False,
            "main_blocker": "WAIT_OPTIONS_DATA",
            "blockers": ["OPTIONS_FIELDS_MISSING"],
            "selected_contract": {},
        }

        with self.assertRaises(ValueError) as ctx:
            main._v31_manual_review_payload({
                "ticker": "QQQ",
                "status": "APPROVED_FOR_MANUAL_TRADE",
                "reason": "Trying to approve incomplete option data.",
                "decision": decision,
            })

        self.assertEqual(str(ctx.exception), "APPROVAL_REQUIRES_ENTRY_READY")

    def test_v31_manual_review_summary_limits_and_counts_reviews(self):
        reviews = [
            {"outcome_tracking_version": "v31_manual_review_journal_v1", "review_id": "MR-1", "signal_id": "SIG-1", "status": "REVIEWING", "ticker": "QQQ"},
            {"outcome_tracking_version": "v31_manual_review_journal_v1", "review_id": "MR-2", "signal_id": "SIG-1", "status": "WATCHLIST", "ticker": "QQQ"},
            {"outcome_tracking_version": "v31_manual_review_journal_v1", "review_id": "MR-3", "signal_id": "SIG-2", "status": "REJECTED", "ticker": "SPY"},
        ]

        with patch.object(main, "_v31_load_manual_reviews", return_value=reviews):
            payload = main._v31_manual_reviews_payload(limit=2)

        self.assertEqual(payload["engine"], "V31_MANUAL_REVIEW_JOURNAL")
        self.assertEqual(payload["review_count"], 3)
        self.assertEqual(payload["by_status"]["WATCHLIST"], 1)
        self.assertEqual(payload["by_status"]["REJECTED"], 1)
        self.assertEqual(len(payload["recent_reviews"]), 2)
        self.assertEqual(payload["latest_by_signal"]["SIG-1"]["status"], "WATCHLIST")
        self.assertTrue(payload["not_order_instruction"])
        self.assertFalse(payload["execution_authorized"])

    def test_v31_manual_reviews_payload_reads_durable_reviews_after_runtime_reset(self):
        durable_review = {
            "outcome_tracking_version": "v31_manual_review_journal_v1",
            "review_id": "MR-DURABLE-1",
            "signal_id": "SIG-DURABLE-1",
            "status": "REVIEWING",
            "ticker": "SPY",
            "not_order_instruction": True,
            "execution_authorized": False,
        }

        with patch.object(main, "_durable_supabase_fetch", return_value=[durable_review]), \
                patch.object(main, "_v31_load_manual_reviews", return_value=[]):
            payload = main._v31_manual_reviews_payload(limit=10)

        self.assertEqual(payload["review_count"], 1)
        self.assertEqual(payload["by_status"], {"REVIEWING": 1})
        self.assertEqual(payload["recent_reviews"][0]["review_id"], "MR-DURABLE-1")
        self.assertEqual(payload["sources"]["durable_count"], 1)
        self.assertEqual(payload["sources"]["local_count"], 0)
        self.assertTrue(payload["sources"]["durable_available"])
        self.assertTrue(payload["not_order_instruction"])
        self.assertFalse(payload["execution_authorized"])

    def test_v31_evaluates_manual_review_against_current_snapshot(self):
        review = {
            "outcome_tracking_version": "v31_manual_review_journal_v1",
            "review_id": "MR-SIG-1",
            "outcome_id": "SIG-1-MANUAL-REVIEW",
            "signal_id": "SIG-1",
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "status": "WATCHLIST",
            "outcome": "WATCHLIST",
            "decision": {
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "selected_contract": {
                    "strike": 710,
                    "expiration": "20260717",
                    "mid": 1.25,
                    "delta": -0.20,
                },
            },
            "not_order_instruction": True,
            "execution_authorized": False,
        }
        current_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "strike": 710,
            "expiration": "20260717",
            "bid": 0.70,
            "ask": 0.80,
            "mid": 0.75,
            "spread_pct": 13.33,
            "delta": -0.12,
            "underlying_price": 725.0,
        }

        result = main._v31_evaluate_manual_review(review, _master_snapshot([current_row]), checkpoint="PLUS_1D")

        self.assertEqual(result["status"], "EVALUATED")
        evaluated = result["review"]
        self.assertEqual(evaluated["status"], "WATCHLIST")
        self.assertEqual(evaluated["outcome"], "WATCHLIST")
        self.assertEqual(evaluated["current_paper_pnl_r"], 0.4)
        self.assertEqual(evaluated["manual_review_learning_label"], "WATCHLIST_WORKED")
        self.assertEqual(evaluated["latest_manual_review_evaluation"]["checkpoint"], "PLUS_1D")
        self.assertFalse(evaluated["execution_authorized"])
        self.assertTrue(evaluated["not_order_instruction"])

    def test_v31_auto_evaluate_manual_reviews_persists_learning_without_authorizing_execution(self):
        review = {
            "outcome_tracking_version": "v31_manual_review_journal_v1",
            "review_id": "MR-SIG-2",
            "outcome_id": "SIG-2-MANUAL-REVIEW",
            "signal_id": "SIG-2",
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "status": "REJECTED",
            "outcome": "REJECTED",
            "decision": {
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "selected_contract": {
                    "strike": 710,
                    "expiration": "20260717",
                    "mid": 1.25,
                },
            },
            "not_order_instruction": True,
            "execution_authorized": False,
        }
        current_row = {
            "ticker": "QQQ",
            "strategy": "NAKED_PUT",
            "strike": 710,
            "expiration": "20260717",
            "bid": 1.70,
            "ask": 1.80,
            "mid": 1.75,
        }

        with patch.object(main, "_v31_load_manual_reviews", return_value=[review]), \
                patch.object(main, "_v29_discover_master_snapshot", return_value=_master_snapshot([current_row])), \
                patch.object(main, "_v31_save_manual_reviews", return_value=True) as save_reviews, \
                patch.object(main, "_journal_outcome", return_value={"saved": True, "status": "SAVED"}) as journal:
            payload = main._v31_auto_evaluate_manual_reviews(limit=10, checkpoint="EOD", dry_run=False)

        self.assertEqual(payload["engine"], "V31_MANUAL_REVIEW_AUTO_EVALUATION")
        self.assertEqual(payload["evaluated_count"], 1)
        self.assertEqual(payload["saved_count"], 1)
        result_review = payload["results"][0]["review"]
        self.assertEqual(result_review["status"], "REJECTED")
        self.assertEqual(result_review["manual_review_learning_label"], "RISK_AVOIDED")
        self.assertFalse(result_review["execution_authorized"])
        self.assertTrue(result_review["not_order_instruction"])
        save_reviews.assert_called_once()
        journal.assert_called_once()

    def test_v31_manual_review_learning_summarizes_evaluated_reviews(self):
        reviews = [
            {
                "outcome_tracking_version": "v31_manual_review_journal_v1",
                "review_id": "MR-1",
                "signal_id": "SIG-1",
                "ticker": "QQQ",
                "strategy": "NAKED_PUT",
                "status": "WATCHLIST",
                "outcome": "WATCHLIST",
                "manual_review_learning_label": "WATCHLIST_WORKED",
                "manual_review_auto_evaluation_status": "EVALUATED",
                "current_paper_pnl_r": 0.4,
                "mfe_r": 0.4,
                "mae_r": 0.0,
                "evaluated_at": "2026-06-22T20:00:00+00:00",
                "latest_manual_review_evaluation": {
                    "checkpoint": "PLUS_1D",
                    "entry_mid": 1.25,
                    "current_mid": 0.75,
                },
                "decision": {
                    "selected_contract": {
                        "strike": 710,
                        "expiration": "20260717",
                        "delta": -0.20,
                    }
                },
                "not_order_instruction": True,
                "execution_authorized": False,
            },
            {
                "outcome_tracking_version": "v31_manual_review_journal_v1",
                "review_id": "MR-2",
                "signal_id": "SIG-2",
                "ticker": "SPY",
                "strategy": "NAKED_PUT",
                "status": "REJECTED",
                "outcome": "REJECTED",
                "manual_review_learning_label": "RISK_AVOIDED",
                "manual_review_auto_evaluation_status": "EVALUATED",
                "current_paper_pnl_r": -0.2,
                "mfe_r": 0.0,
                "mae_r": -0.2,
                "latest_manual_review_evaluation": {
                    "checkpoint": "EOD",
                    "entry_mid": 1.50,
                    "current_mid": 1.80,
                },
                "not_order_instruction": True,
                "execution_authorized": False,
            },
            {
                "outcome_tracking_version": "v31_manual_review_journal_v1",
                "review_id": "MR-3",
                "signal_id": "SIG-3",
                "ticker": "IWM",
                "strategy": "NAKED_PUT",
                "status": "REVIEWING",
                "outcome": "REVIEWING",
                "not_order_instruction": True,
                "execution_authorized": False,
            },
        ]

        with patch.object(main, "_v31_load_manual_reviews_with_durable", return_value=(reviews, {"durable_count": 3, "local_count": 0, "durable_available": True})):
            payload = main._v31_manual_review_learning_payload(limit=10)

        self.assertEqual(payload["engine"], "V31_MANUAL_REVIEW_LEARNING")
        self.assertEqual(payload["review_count"], 3)
        self.assertEqual(payload["evaluated_count"], 2)
        self.assertEqual(payload["unevaluated_count"], 1)
        self.assertEqual(payload["by_manual_status"], {"REJECTED": 1, "WATCHLIST": 1})
        self.assertEqual(payload["by_learning_label"], {"RISK_AVOIDED": 1, "WATCHLIST_WORKED": 1})
        self.assertEqual(payload["by_ticker"], {"QQQ": 1, "SPY": 1})
        self.assertEqual(payload["by_strategy"], {"NAKED_PUT": 2})
        self.assertEqual(payload["avg_paper_pnl_r"], 0.1)
        self.assertEqual(payload["avg_mfe_r"], 0.2)
        self.assertEqual(payload["avg_mae_r"], -0.1)
        self.assertEqual(payload["best_reviews"][0]["ticker"], "QQQ")
        self.assertEqual(payload["worst_reviews"][0]["ticker"], "SPY")
        self.assertTrue(payload["needs_more_data"])
        self.assertFalse(payload["execution_authorized"])
        self.assertTrue(payload["not_order_instruction"])

    def test_v31_learning_notify_preview_includes_executive_summary_without_sending(self):
        learning = {
            "engine": "V31_MANUAL_REVIEW_LEARNING",
            "review_count": 2,
            "evaluated_count": 2,
            "unevaluated_count": 0,
            "needs_more_data": True,
            "avg_paper_pnl_r": 0.1,
            "avg_mfe_r": 0.2,
            "avg_mae_r": -0.1,
            "by_manual_status": {"WATCHLIST": 1, "REJECTED": 1},
            "by_learning_label": {"WATCHLIST_WORKED": 1, "RISK_AVOIDED": 1},
            "by_strategy": {"NAKED_PUT": 2},
            "by_ticker": {"QQQ": 1, "SPY": 1},
            "best_reviews": [{"ticker": "QQQ", "strategy": "NAKED_PUT", "manual_status": "WATCHLIST", "learning_label": "WATCHLIST_WORKED", "current_paper_pnl_r": 0.4}],
            "worst_reviews": [{"ticker": "SPY", "strategy": "NAKED_PUT", "manual_status": "REJECTED", "learning_label": "RISK_AVOIDED", "current_paper_pnl_r": -0.2}],
            "not_order_instruction": True,
            "execution_authorized": False,
        }

        with patch.object(main, "_v31_manual_review_learning_payload", return_value=learning), \
                patch.object(main, "send_resend_email") as send_email:
            preview = main._v31_learning_notify_payload(dry_run=True)

        self.assertEqual(preview["engine"], "V31_WEEKLY_LEARNING_EMAIL")
        self.assertEqual(preview["status"], "preview")
        self.assertFalse(preview["email_sent"])
        self.assertIn("Weekly Learning", preview["subject"])
        self.assertIn("WATCHLIST_WORKED", preview["text"])
        self.assertIn("RISK_AVOIDED", preview["html"])
        self.assertFalse(preview["execution_authorized"])
        self.assertTrue(preview["not_order_instruction"])
        send_email.assert_not_called()

    def test_v31_learning_notify_sends_and_dedupes_weekly_email(self):
        learning = {
            "engine": "V31_MANUAL_REVIEW_LEARNING",
            "review_count": 1,
            "evaluated_count": 1,
            "unevaluated_count": 0,
            "needs_more_data": True,
            "avg_paper_pnl_r": 0.0,
            "avg_mfe_r": 0.0,
            "avg_mae_r": 0.0,
            "by_manual_status": {"REVIEWING": 1},
            "by_learning_label": {"REVIEWING_ADVERSE": 1},
            "by_strategy": {"NAKED_PUT": 1},
            "by_ticker": {"SPY": 1},
            "best_reviews": [],
            "worst_reviews": [],
            "not_order_instruction": True,
            "execution_authorized": False,
        }

        with patch.object(main, "_v31_manual_review_learning_payload", return_value=learning), \
                patch.object(main, "_v31_load_learning_notify_state", return_value={}), \
                patch.object(main, "_v31_save_learning_notify_state", return_value=True), \
                patch.object(main, "send_resend_email", return_value={"email_sent": True}) as send_email:
            sent = main._v31_learning_notify_payload(to_email="test@example.com")

        self.assertEqual(sent["status"], "sent")
        self.assertTrue(sent["email_sent"])
        self.assertFalse(sent["dedupe"]["deduped"])
        self.assertFalse(sent["execution_authorized"])
        self.assertTrue(sent["not_order_instruction"])
        send_email.assert_called_once()

        week_key = main._v31_learning_week_key()
        with patch.object(main, "_v31_manual_review_learning_payload", return_value=learning), \
                patch.object(main, "_v31_load_learning_notify_state", return_value={week_key: {"sent_at": main._v29_now()}}), \
                patch.object(main, "send_resend_email") as deduped_email:
            deduped = main._v31_learning_notify_payload()

        self.assertEqual(deduped["status"], "skipped")
        self.assertEqual(deduped["reason"], "DEDUPED_WEEKLY_LEARNING_EMAIL")
        self.assertTrue(deduped["dedupe"]["deduped"])
        deduped_email.assert_not_called()


if __name__ == "__main__":
    unittest.main()
