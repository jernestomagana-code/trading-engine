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


def master_snapshot(row, *, technical_score=85, market_open=True, options_expected=True, technical_overrides=None):
    technical = {
        "ticker": "AAPL",
        "trend": "BULLISH",
        "score": technical_score,
        "technical_score": technical_score,
    }
    if technical_overrides:
        technical.update(technical_overrides)

    return {
        "source": "V29_ENDPOINT_SMOKE_TEST",
        "generated_at": "2026-06-11T00:00:00+00:00",
        "options_rows": [row],
        "technical_snapshot": {
            "AAPL": technical
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
        "/v31_system_status",
        "/v31_ingest_snapshot",
        "/v31_trade_decision/{ticker}",
        "/gpt_v31_trade_decision/{ticker}",
        "/strategy_signal_contract",
        "/strategy_signal_template",
        "/v30_monitor_status",
        "/v30_monitor_notify/preview",
        "/v30_monitor_notify",
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
    v31 = await call_endpoint(app_module.v31_trade_decision)
    gpt_v31 = await call_endpoint(app_module.gpt_v31_trade_decision)

    if trade.get("final_state") != expected_state:
        raise AssertionError(f"{name}: trade endpoint expected {expected_state}, got {trade.get('final_state')}")
    if gpt.get("final_state") != expected_state:
        raise AssertionError(f"{name}: GPT endpoint expected {expected_state}, got {gpt.get('final_state')}")
    expected_v31_state = {
        "WAIT_MARKET_OPEN": "WAIT_MARKET",
        "MANUAL_REVIEW_BLOCKED": "MANUAL_REVIEW",
        "RADAR": "MANUAL_REVIEW",
    }.get(expected_state, expected_state)
    if v31.get("final_state") != expected_v31_state:
        raise AssertionError(f"{name}: V31 endpoint expected {expected_v31_state}, got {v31.get('final_state')}")
    if gpt_v31.get("final_state") != expected_v31_state:
        raise AssertionError(f"{name}: GPT V31 endpoint expected {expected_v31_state}, got {gpt_v31.get('final_state')}")
    if gpt_v31.get("not_order_instruction") is not True or gpt_v31.get("execution_authorized") is not False:
        raise AssertionError(f"{name}: GPT V31 must preserve no-order guardrails")
    if trade.get("decision") != gpt.get("decision"):
        raise AssertionError(f"{name}: trade/GPT decision mismatch")
    if trade.get("can_operate") != gpt.get("can_operate"):
        raise AssertionError(f"{name}: trade/GPT can_operate mismatch")
    if expected_blocker is not None and gpt.get("main_blocker") != expected_blocker:
        raise AssertionError(f"{name}: expected blocker {expected_blocker}, got {gpt.get('main_blocker')}")
    if expected_blocker is not None and gpt_v31.get("main_blocker") != expected_blocker:
        raise AssertionError(f"{name}: expected V31 blocker {expected_blocker}, got {gpt_v31.get('main_blocker')}")
    if expected_state != "ENTRY_READY" and gpt.get("can_operate") is True:
        raise AssertionError(f"{name}: can_operate must be false for {expected_state}")
    if expected_state == "ENTRY_READY":
        assert_contract_fields(gpt)
        contract = gpt_v31.get("selected_contract") or {}
        missing = [field for field in REQUIRED_OPTION if contract.get(field) is None]
        if missing:
            raise AssertionError(f"GPT V31 endpoint missing contract fields: {missing}")


async def smoke() -> None:
    app_module = load_app_module()
    assert_routes(app_module)

    app_module.SNAPSHOT_INGEST_TOKEN = "local-smoke-test-token"
    try:
        await app_module.v31_ingest_snapshot(master_snapshot(option_row()), None, None, None)
        raise AssertionError("V31 ingest accepted a request without its configured token")
    except Exception as exc:
        if getattr(exc, "status_code", None) != 401:
            raise

    ingest = await app_module.v31_ingest_snapshot(
        master_snapshot(option_row()),
        "local-smoke-test-token",
        None,
        None,
    )
    if ingest.get("engine") != "V31_CANONICAL_SNAPSHOT_INGEST":
        raise AssertionError(f"unexpected V31 ingest response: {ingest}")

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
            "event_risk_blocked",
            master_snapshot(option_row(), technical_overrides={"event_risk": True}),
            "RISK_BLOCKED",
            "EVENT_RISK_ACTIVE",
        ),
        (
            "liquidity_blocked",
            master_snapshot(option_row(volume=10, open_interest=400)),
            "RISK_BLOCKED",
            "LOW_OPTION_VOLUME",
        ),
        (
            "canslim_blocked",
            master_snapshot(option_row(), technical_overrides={"canslim": {"passes": False, "score": 42}}),
            "RISK_BLOCKED",
            "CANSLIM_BLOCKED",
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

    monitor = await app_module.v30_monitor_status()
    if monitor.get("not_order_instruction") is not True:
        raise AssertionError("monitor must preserve not_order_instruction")

    v31_status = await app_module.v31_system_status()
    if v31_status.get("decision_version") != "v31.0":
        raise AssertionError("V31 status must expose decision version")
    if v31_status.get("not_order_instruction") is not True:
        raise AssertionError("V31 status must preserve not_order_instruction")

    signal_contract = await app_module.strategy_signal_contract()
    if signal_contract.get("contract_version") != "strategy_signal_contract_v1":
        raise AssertionError("strategy signal contract version mismatch")
    if "CANSLIM_FILTER" not in signal_contract.get("strategy_contexts", []):
        raise AssertionError("strategy signal contract must include CANSLIM_FILTER")
    if signal_contract.get("not_order_instruction") is not True:
        raise AssertionError("strategy signal contract must preserve not_order_instruction")

    signal_template = await app_module.strategy_signal_template("AAPL", "NAKED_PUT")
    template_payload = signal_template.get("alert_payload_template") or {}
    if template_payload.get("ticker") != "AAPL" or template_payload.get("strategy_context") != "NAKED_PUT":
        raise AssertionError("strategy signal template did not preserve ticker/context")
    if "canslim" not in template_payload:
        raise AssertionError("strategy signal template should include optional CANSLIM shape")

    preview = await app_module.v30_monitor_notify_preview()
    if preview.get("status") != "preview":
        raise AssertionError("monitor preview did not return preview status")
    if preview.get("email_sent") is True:
        raise AssertionError("monitor preview must not send email")

    original_send = app_module._v30_send_resend_email
    try:
        app_module._v30_send_resend_email = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("non-actionable monitor notification attempted to send email")
        )
        original_status = app_module._v30_monitor_status_payload
        app_module._v30_monitor_status_payload = lambda: {
            "engine": "V30_PASSIVE_PIPELINE_MONITOR",
            "generated_at": "2026-06-11T00:00:00+00:00",
            "alert_level": "INFO",
            "summary": {"entry_ready": 0},
            "message": "informational only",
            "not_order_instruction": True,
        }
        skipped = app_module._v30_monitor_notify_payload()
        if skipped.get("status") != "skipped":
            raise AssertionError("non-actionable monitor notification should be skipped")
    finally:
        app_module._v30_send_resend_email = original_send
        app_module._v30_monitor_status_payload = original_status

    sent_calls = []
    try:
        app_module._v30_send_resend_email = lambda *args, **kwargs: sent_calls.append(args) or {
            "email_sent": True,
            "provider": "test",
        }
        app_module._v30_monitor_status_payload = lambda: {
            "engine": "V30_PASSIVE_PIPELINE_MONITOR",
            "generated_at": "2026-06-11T00:00:00+00:00",
            "alert_level": "ACTION_REQUIRED",
            "summary": {"entry_ready": 1},
            "entry_ready_tickers": ["AAPL"],
            "risk_blocked_tickers": [],
            "wait_options_tickers": [],
            "message": "actionable",
            "next_required_action": "manual review",
            "market_context": "REGULAR_MARKET_HOURS",
            "master_snapshot_available": True,
            "master_source": "test",
            "rows_found": 1,
            "technical_count": 1,
            "not_order_instruction": True,
        }
        sent = app_module._v30_monitor_notify_payload()
        if sent.get("status") != "sent" or sent.get("email_sent") is not True:
            raise AssertionError("actionable monitor notification should send email")
        if not sent_calls:
            raise AssertionError("actionable monitor notification did not call email helper")
    finally:
        app_module._v30_send_resend_email = original_send
        app_module._v30_monitor_status_payload = original_status


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
