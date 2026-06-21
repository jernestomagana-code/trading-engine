#!/usr/bin/env python3
"""Guard V32 strategy performance evidence endpoint."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def install_import_stubs():
    fastapi = types.ModuleType("fastapi")
    responses = types.ModuleType("fastapi.responses")
    pydantic = types.ModuleType("pydantic")

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

    sys.modules.setdefault("fastapi", fastapi)
    sys.modules.setdefault("fastapi.responses", responses)
    sys.modules.setdefault("pydantic", pydantic)


def load_app_module():
    sys.dont_write_bytecode = True
    install_import_stubs()
    app_path = ROOT / "app" / "main.py"
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_strategy_performance_guard", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")

    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def require(condition, message):
    if not condition:
        raise AssertionError(message)


async def maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value


async def main_async() -> int:
    app = load_app_module()

    decisions = [
        {
            "decision_id": "DEC-1",
            "ticker": "AAPL",
            "strategy": "CASH_SECURED_PUT",
            "final_state": "ENTRY_READY",
            "outcome_status": "OPEN",
        },
        {
            "decision_id": "DEC-2",
            "ticker": "MSFT",
            "strategy": "COVERED_CALL",
            "final_state": "WAIT_OPTIONS_DATA",
            "outcome_status": "OPEN",
        },
    ]
    outcomes = [
        {
            "outcome_id": "OUT-1",
            "ticker": "AAPL",
            "strategy": "CASH_SECURED_PUT",
            "outcome": "WIN",
            "pnl": 150,
            "pnl_r": 1.5,
            "mfe_r": 2.1,
            "mae_r": -0.4,
            "recorded_at": "2026-06-21T10:00:00+00:00",
        },
        {
            "outcome_id": "OUT-2",
            "ticker": "AAPL",
            "strategy": "CASH_SECURED_PUT",
            "outcome": "LOSS",
            "pnl": -50,
            "pnl_r": -0.5,
            "mfe_r": 0.4,
            "mae_r": -1.0,
            "recorded_at": "2026-06-21T11:00:00+00:00",
        },
    ]

    app._strategy_performance_decisions = lambda limit=1000: decisions
    app._strategy_performance_outcomes = lambda limit=1000: outcomes
    app._durable_storage_summary = lambda: {
        "status": "READY",
        "sensitive_values_excluded": True,
        "not_order_instruction": True,
    }

    payload = await maybe_await(app.v32_strategy_performance(limit=100))
    require(payload.get("engine") == "V32_STRATEGY_PERFORMANCE", f"unexpected engine: {payload}")
    require(payload.get("strategy_performance_version") == "strategy_performance_v1", f"unexpected version: {payload}")
    require(payload.get("not_order_instruction") is True, f"missing no-order guard: {payload}")
    require(payload.get("execution_authorized") is False, f"execution authorized unexpectedly: {payload}")

    csp = next(
        (item for item in payload.get("strategies", []) if item.get("strategy") == "CASH_SECURED_PUT"),
        None,
    )
    require(csp is not None, f"CASH_SECURED_PUT row missing: {payload}")
    require(csp.get("decision_count") == 1, f"decision count mismatch: {csp}")
    require(csp.get("entry_ready_decisions") == 1, f"entry ready count mismatch: {csp}")
    require(csp.get("closed_outcomes") == 2, f"closed outcomes mismatch: {csp}")
    require(csp.get("wins") == 1 and csp.get("losses") == 1, f"win/loss mismatch: {csp}")
    require(csp.get("win_rate") == 50.0, f"win rate mismatch: {csp}")
    require(csp.get("net_pnl_r") == 1.0, f"net pnl_r mismatch: {csp}")
    require(csp.get("avg_mfe_r") == 1.25, f"avg mfe_r mismatch: {csp}")
    require(csp.get("avg_mae_r") == -0.7, f"avg mae_r mismatch: {csp}")
    require(csp.get("sample_size_warning") is True, f"sample warning missing: {csp}")

    print("Validated V32 strategy performance evidence endpoint.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
