#!/usr/bin/env python3
"""Smoke test V29 FastAPI endpoint handlers with controlled runtime snapshots."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
V29_MASTER_SNAPSHOT = RUNTIME_DIR / "v28_master_snapshot.json"
REQUIRED_OPTION = {
    "strike": 180.0,
    "expiration": "2026-07-17",
    "dte": 39,
    "bid": 1.2,
    "ask": 1.35,
    "mid": 1.275,
    "spread": 0.15,
    "spread_pct": 11.76,
    "delta": -0.28,
}


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_smoke", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")

    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def option_row(**overrides):
    row = {
        "ticker": "AAPL",
        "strategy": "NAKED_PUT",
        "decision": "ENTRY",
        "score": 90,
        "price": 185.0,
        "data_quality": "FULL_WITH_GREEKS",
        "risk": {"passes": True},
        **REQUIRED_OPTION,
    }
    row.update(overrides)
    return row


def master_snapshot(row, *, technical_score=85, market_open=True, options_expected=True):
    return {
        "source": "V29_ENDPOINT_SMOKE_TEST",
        "generated_at": "2026-06-11T00:00:00+00:00",
        "options_rows": [row],
        "technical_snapshot": {
            "AAPL": {
                "ticker": "AAPL",
                "trend": "BULLISH",
                "score": technical_score,
                "technical_score": technical_score,
            }
        },
        "market": {
            "is_regular_market_open": market_open,
            "options_bidask_expected": options_expected,
            "label": "SMOKE_TEST",
        },
    }


async def call_endpoint(handler, ticker="AAPL"):
    result = handler(ticker)
    if hasattr(result, "__await__"):
        return await result
    return result


def assert_routes(app_module):
    paths = {getattr(route, "path", None) for route in app_module.app.routes}
    required = {
        "/v29_trade_decision/{ticker}",
        "/gpt_v29_trade_decision/{ticker}",
        "/v29_dashboard",
        "/v29_dashboard/{ticker}",
    }
    missing = sorted(required - paths)
    if missing:
        raise AssertionError(f"missing FastAPI routes: {missing}")


def assert_contract_fields(gpt_result):
    contract = gpt_result.get("best_contract") or {}
    missing = [field for field in REQUIRED_OPTION if contract.get(field) is None]
    if missing:
        raise AssertionError(f"GPT endpoint missing contract fields: {missing}")


async def run_case(app_module, name, snapshot, expected_state, expected_blocker=None):
    V29_MASTER_SNAPSHOT.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    trade = await call_endpoint(app_module.v29_trade_decision)
    gpt = await call_endpoint(app_module.gpt_v29_trade_decision)

    if trade.get("final_state") != expected_state:
        raise AssertionError(f"{name}: trade endpoint expected {expected_state}, got {trade.get('final_state')}")
    if gpt.get("final_state") != expected_state:
        raise AssertionError(f"{name}: GPT endpoint expected {expected_state}, got {gpt.get('final_state')}")
    if trade.get("decision") != gpt.get("decision"):
        raise AssertionError(f"{name}: trade/GPT decision mismatch")
    if trade.get("can_operate") != gpt.get("can_operate"):
        raise AssertionError(f"{name}: trade/GPT can_operate mismatch")
    if expected_blocker is not None and gpt.get("main_blocker") != expected_blocker:
        raise AssertionError(f"{name}: expected blocker {expected_blocker}, got {gpt.get('main_blocker')}")
    if expected_state != "ENTRY_READY" and gpt.get("can_operate") is True:
        raise AssertionError(f"{name}: can_operate must be false for {expected_state}")
    if expected_state == "ENTRY_READY":
        assert_contract_fields(gpt)


async def smoke() -> None:
    app_module = load_app_module()
    assert_routes(app_module)

    cases = [
        ("entry_ready", master_snapshot(option_row()), "ENTRY_READY", None),
        (
            "wait_options_priority",
            master_snapshot(option_row(delta=None), market_open=False, options_expected=False),
            "WAIT_OPTIONS_DATA",
            "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY",
        ),
        (
            "risk_blocked",
            master_snapshot(option_row(risk={"passes": False, "blocker": "RISK_RULE_FAILED"})),
            "RISK_BLOCKED",
            "RISK_RULE_FAILED",
        ),
        (
            "manual_review_blocked",
            master_snapshot(option_row(manual_review_required=True)),
            "MANUAL_REVIEW_BLOCKED",
            "MANUAL_REVIEW_REQUIRED",
        ),
    ]

    for name, snapshot, expected_state, expected_blocker in cases:
        await run_case(app_module, name, snapshot, expected_state, expected_blocker)

    dashboard = app_module.v29_dashboard_ticker("AAPL")
    if hasattr(dashboard, "__await__"):
        dashboard = await dashboard
    body = getattr(dashboard, "body", dashboard)
    if isinstance(body, bytes):
        rendered = body.decode("utf-8", errors="replace")
    else:
        rendered = str(body)
    if "AAPL" not in rendered:
        raise AssertionError("dashboard ticker endpoint did not render AAPL")


def main() -> int:
    backup = V29_MASTER_SNAPSHOT.read_text() if V29_MASTER_SNAPSHOT.exists() else None
    try:
        RUNTIME_DIR.mkdir(exist_ok=True)
        asyncio.run(smoke())
    except Exception as exc:
        print(f"V29 endpoint smoke failed: {exc}")
        return 1
    finally:
        if backup is None:
            try:
                V29_MASTER_SNAPSHOT.unlink()
            except FileNotFoundError:
                pass
        else:
            V29_MASTER_SNAPSHOT.write_text(backup)

    print("V29 endpoint smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
