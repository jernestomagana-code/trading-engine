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


if __name__ == "__main__":
    unittest.main()
