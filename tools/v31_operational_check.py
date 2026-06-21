#!/usr/bin/env python3
"""
Run a focused V31 operational readiness check.

Default mode is cloud-only and never connects to IBKR. Use --run-bridge to run
one local ibkr_bridge.py cycle with a reduced watchlist and then validate V31.
This script does not place orders; it only calls the existing read-only bridge
entrypoint and Render status/decision endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_REMOTE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_LOG_PATH = "/private/tmp/stock_ultimus_v31_operational_check.log"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def read_headers(token: str | None = None) -> dict[str, str]:
    if not token:
        return {}
    return {"X-Stock-Ultimus-Read-Token": token}


def fetch_json(url: str, timeout: int = 20, token: str | None = None) -> tuple[bool, int | None, Any]:
    req = request.Request(url, headers=read_headers(token))
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, resp.status, json.loads(body)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body
        return False, exc.code, parsed
    except Exception as exc:
        return False, None, {"error": str(exc)}


def post_json(url: str, payload: dict[str, Any], timeout: int = 20) -> tuple[bool, int | None, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return True, resp.status, json.loads(text)
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = text
        return False, exc.code, parsed
    except Exception as exc:
        return False, None, {"error": str(exc)}


def safe_get(data: Any, *path: str, default: Any = None) -> Any:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def pipeline_ready_for_open_data(pipeline: dict[str, Any], min_rows: int) -> bool:
    rows_found = int(safe_get(pipeline, "rows_found", default=0) or 0)
    return safe_get(pipeline, "status") == "OK" and rows_found >= min_rows


def wait_for_pipeline_after_bridge(
    base: str,
    token: str | None,
    *,
    request_timeout: int,
    wait_seconds: int,
    poll_interval: int,
    min_rows: int,
) -> dict[str, Any]:
    if wait_seconds <= 0:
        return {
            "waited": False,
            "ok": False,
            "attempts": 0,
            "detail": "post-bridge wait disabled",
        }

    deadline = time.monotonic() + wait_seconds
    attempts = 0
    last_status = None
    last_rows = None
    last_payload: Any = None
    while True:
        attempts += 1
        ok, status_code, payload = fetch_json(
            f"{base}/v31_data_pipeline_status",
            timeout=request_timeout,
            token=token,
        )
        last_payload = payload
        if isinstance(payload, dict):
            last_status = safe_get(payload, "status")
            last_rows = safe_get(payload, "rows_found", default=0)
            if ok and pipeline_ready_for_open_data(payload, min_rows):
                return {
                    "waited": True,
                    "ok": True,
                    "attempts": attempts,
                    "status": last_status,
                    "rows_found": last_rows,
                }
        else:
            last_status = f"HTTP_{status_code}"

        if time.monotonic() >= deadline:
            return {
                "waited": True,
                "ok": False,
                "attempts": attempts,
                "status": last_status,
                "rows_found": last_rows,
                "last_payload": last_payload if isinstance(last_payload, dict) else str(last_payload)[:200],
                "detail": f"pipeline did not reach OK with rows >= {min_rows} within {wait_seconds}s",
            }
        time.sleep(max(1, poll_interval))


def evaluate_cloud(
    health: dict[str, Any],
    unauth_status_code: int | None,
    read_auth: dict[str, Any],
    readiness: dict[str, Any],
    pipeline: dict[str, Any],
    decision: dict[str, Any],
    daily_recommendations: dict[str, Any],
    strategy_performance: dict[str, Any],
    require_open_data: bool,
    min_rows: int,
) -> list[Check]:
    rows_found = int(safe_get(pipeline, "rows_found", default=0) or 0)
    final_state = str(safe_get(decision, "final_state", default=""))
    not_order = bool(safe_get(decision, "not_order_instruction", default=False))
    can_operate = bool(safe_get(decision, "can_operate", default=False))
    market_holiday = bool(safe_get(health, "market_clock", "market_holiday", default=False))

    checks = [
        Check("health_ok", safe_get(health, "status") == "ok", str(safe_get(health, "status"))),
        Check(
            "read_auth_required",
            safe_get(read_auth, "required") is True,
            str(safe_get(read_auth, "required")),
        ),
        Check(
            "production_readiness_ready",
            safe_get(readiness, "status") == "READY",
            str(safe_get(readiness, "status")),
        ),
        Check(
            "critical_read_endpoints_protected",
            safe_get(readiness, "read_auth", "critical_endpoints_protected") is True,
            str(safe_get(readiness, "read_auth", "critical_endpoints_protected")),
        ),
        Check(
            "outcome_tracking_available",
            safe_get(readiness, "outcome_tracking", "version") == "v31_entry_ready_signal_outcome_v1",
            str(safe_get(readiness, "outcome_tracking", "version")),
        ),
        Check(
            "risk_profile_loaded",
            safe_get(readiness, "risk_profile", "profile_version") == "v31_risk_profile_v1",
            str(safe_get(readiness, "risk_profile", "profile_version")),
        ),
        Check(
            "analysis_only",
            safe_get(health, "operating_mode") == "ANALYSIS_ONLY",
            str(safe_get(health, "operating_mode")),
        ),
        Check(
            "snapshot_ingest_auth_required",
            safe_get(health, "snapshot_ingest_token_required") is True,
            str(safe_get(health, "snapshot_ingest_token_required")),
        ),
        Check("unauth_v31_ingest_rejected", unauth_status_code == 401, str(unauth_status_code)),
        Check(
            "pipeline_status_known",
            safe_get(pipeline, "status") in {"OK", "NO_MASTER_SNAPSHOT"},
            str(safe_get(pipeline, "status")),
        ),
        Check(
            "daily_recommendations_ok",
            safe_get(daily_recommendations, "status") == "OK"
            and safe_get(daily_recommendations, "not_order_instruction") is True,
            f"status={safe_get(daily_recommendations, 'status')} not_order={safe_get(daily_recommendations, 'not_order_instruction')}",
        ),
        Check(
            "strategy_performance_ok",
            safe_get(strategy_performance, "engine") == "V32_STRATEGY_PERFORMANCE"
            and safe_get(strategy_performance, "strategy_performance_version") == "strategy_performance_v1",
            (
                f"engine={safe_get(strategy_performance, 'engine')} "
                f"version={safe_get(strategy_performance, 'strategy_performance_version')}"
            ),
        ),
        Check(
            "strategy_performance_no_order",
            safe_get(strategy_performance, "not_order_instruction") is True
            and safe_get(strategy_performance, "execution_authorized") is False,
            (
                f"not_order={safe_get(strategy_performance, 'not_order_instruction')} "
                f"execution_authorized={safe_get(strategy_performance, 'execution_authorized')}"
            ),
        ),
        Check(
            "strategy_performance_summary",
            isinstance(safe_get(strategy_performance, "summary", default={}), dict)
            and safe_get(strategy_performance, "summary", "strategy_count", default=0) is not None,
            f"summary={safe_get(strategy_performance, 'summary', default={})}",
        ),
        Check("decision_support_only", not_order and not can_operate, f"not_order={not_order} can_operate={can_operate}"),
    ]

    if require_open_data:
        checks.append(Check("pipeline_status_ok", safe_get(pipeline, "status") == "OK", str(safe_get(pipeline, "status"))))
        checks.append(Check("market_not_holiday", not market_holiday, f"market_holiday={market_holiday}"))
        checks.append(Check("rows_found_minimum", rows_found >= min_rows, f"rows_found={rows_found} min={min_rows}"))
        checks.append(Check("decision_not_no_data", final_state not in ["", "NO_DATA"], f"final_state={final_state}"))

    return checks


def run_bridge_once(args: argparse.Namespace, repo_root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "IBKR_PORT": str(args.ibkr_port),
            "IBKR_MARKET_DATA_TYPE": str(args.market_data_type),
            "IBKR_WATCHLIST": args.ticker,
            "IBKR_OPTION_SYMBOLS": args.ticker,
            "IBKR_HISTORICAL_DATA_TIMEOUT_SECONDS": str(args.historical_timeout),
            "IBKR_STOCK_MARKET_DATA_WAIT_SECONDS": str(args.stock_wait),
            "IBKR_OPTION_MARKET_DATA_WAIT_SECONDS": str(args.option_wait),
            "IBKR_OPTION_SECOND_PASS_WAIT_SECONDS": str(args.option_second_wait),
            "PYTHONUNBUFFERED": "1",
        }
    )

    if not env.get("TRADING_ENGINE_INGEST_TOKEN"):
        return {
            "ok": False,
            "exit_code": None,
            "log_path": args.log_path,
            "detail": "TRADING_ENGINE_INGEST_TOKEN is required for --run-bridge.",
        }

    log_path = Path(args.log_path)
    with log_path.open("w") as log:
        proc = subprocess.run(
            [sys.executable, "ibkr_bridge.py", "--once"],
            cwd=str(repo_root),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=args.bridge_timeout,
            check=False,
        )

    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "log_path": str(log_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check V31 operational readiness.")
    parser.add_argument("--remote-url", default=DEFAULT_REMOTE_URL)
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--read-token", default=os.getenv("READ_ACCESS_TOKEN", ""))
    parser.add_argument("--run-bridge", action="store_true")
    parser.add_argument("--require-open-data", action="store_true")
    parser.add_argument("--min-rows", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--bridge-timeout", type=int, default=240)
    parser.add_argument("--post-bridge-wait-seconds", type=int, default=60)
    parser.add_argument("--post-bridge-poll-interval", type=int, default=5)
    parser.add_argument("--log-path", default=DEFAULT_LOG_PATH)
    parser.add_argument("--ibkr-port", default="7496")
    parser.add_argument("--market-data-type", default="1")
    parser.add_argument("--historical-timeout", default="4")
    parser.add_argument("--stock-wait", default="3")
    parser.add_argument("--option-wait", default="12")
    parser.add_argument("--option-second-wait", default="8")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    base = args.remote_url.rstrip("/")
    ticker = args.ticker.upper()
    read_token = args.read_token or None

    bridge_result = None
    pipeline_wait_result = None
    if args.run_bridge:
        try:
            bridge_result = run_bridge_once(args, repo_root)
        except subprocess.TimeoutExpired:
            bridge_result = {
                "ok": False,
                "exit_code": None,
                "log_path": args.log_path,
                "detail": f"Bridge timed out after {args.bridge_timeout}s.",
            }
        if bridge_result.get("ok") and args.require_open_data:
            pipeline_wait_result = wait_for_pipeline_after_bridge(
                base,
                read_token,
                request_timeout=args.timeout,
                wait_seconds=args.post_bridge_wait_seconds,
                poll_interval=args.post_bridge_poll_interval,
                min_rows=args.min_rows,
            )

    _, _, health = fetch_json(f"{base}/health", timeout=args.timeout)
    _, unauth_status_code, _ = post_json(f"{base}/v31_ingest_snapshot", {}, timeout=args.timeout)
    _, _, read_auth = fetch_json(f"{base}/read_auth_status", timeout=args.timeout, token=read_token)
    _, _, readiness = fetch_json(f"{base}/v31_production_readiness", timeout=args.timeout, token=read_token)
    _, _, pipeline = fetch_json(f"{base}/v31_data_pipeline_status", timeout=args.timeout, token=read_token)
    _, _, decision = fetch_json(f"{base}/v31_decision/{ticker}", timeout=args.timeout, token=read_token)
    _, _, daily_recommendations = fetch_json(f"{base}/v31_daily_recommendations", timeout=args.timeout, token=read_token)
    _, _, strategy_performance = fetch_json(f"{base}/v32_strategy_performance", timeout=args.timeout, token=read_token)

    checks = evaluate_cloud(
        health if isinstance(health, dict) else {},
        unauth_status_code,
        read_auth if isinstance(read_auth, dict) else {},
        readiness if isinstance(readiness, dict) else {},
        pipeline if isinstance(pipeline, dict) else {},
        decision if isinstance(decision, dict) else {},
        daily_recommendations if isinstance(daily_recommendations, dict) else {},
        strategy_performance if isinstance(strategy_performance, dict) else {},
        require_open_data=args.require_open_data,
        min_rows=args.min_rows,
    )

    if bridge_result is not None:
        checks.insert(0, Check("bridge_once_completed", bool(bridge_result.get("ok")), str(bridge_result)))
        if args.require_open_data:
            checks.insert(
                1,
                Check(
                    "post_bridge_pipeline_ready",
                    bool((pipeline_wait_result or {}).get("ok")),
                    str(pipeline_wait_result),
                ),
            )

    result = {
        "engine": "V31_OPERATIONAL_CHECK",
        "ticker": ticker,
        "remote_url": base,
        "bridge_result": bridge_result,
        "post_bridge_pipeline_wait": pipeline_wait_result,
        "read_auth": {
            "required": safe_get(read_auth, "required"),
            "read_access_token_configured": safe_get(read_auth, "read_access_token_configured"),
        },
        "production_readiness": {
            "status": safe_get(readiness, "status"),
            "durable_storage": safe_get(readiness, "durable_storage", default={}),
        },
        "pipeline": {
            "status": safe_get(pipeline, "status"),
            "rows_found": safe_get(pipeline, "rows_found"),
            "technical_count": safe_get(pipeline, "technical_count"),
            "master_source": safe_get(pipeline, "master_source"),
        },
        "decision": {
            "final_state": safe_get(decision, "final_state"),
            "main_blocker": safe_get(decision, "main_blocker"),
            "required_missing_fields": safe_get(decision, "required_missing_fields", default=[]),
            "can_operate": safe_get(decision, "can_operate"),
            "not_order_instruction": safe_get(decision, "not_order_instruction"),
        },
        "daily_recommendations": {
            "status": safe_get(daily_recommendations, "status"),
            "recommendation_version": safe_get(daily_recommendations, "recommendation_version"),
            "summary": safe_get(daily_recommendations, "summary", default={}),
        },
        "strategy_performance": {
            "engine": safe_get(strategy_performance, "engine"),
            "strategy_performance_version": safe_get(strategy_performance, "strategy_performance_version"),
            "summary": safe_get(strategy_performance, "summary", default={}),
            "execution_authorized": safe_get(strategy_performance, "execution_authorized"),
            "not_order_instruction": safe_get(strategy_performance, "not_order_instruction"),
        },
        "market_clock": safe_get(health, "market_clock", default={}),
        "checks": [check.as_dict() for check in checks],
        "ok": all(check.ok for check in checks),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
