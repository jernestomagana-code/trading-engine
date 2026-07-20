#!/usr/bin/env python3
"""Run the IBKR bridge repeatedly during a market session.

This is an operator helper. It refreshes snapshots through ibkr_bridge.py and
can call the cloud monitor after each successful refresh. It never places
orders and never prints tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import coberturas_engine
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"
INGEST_KEYCHAIN_SERVICE = "stock-ultimus-snapshot-ingest"
READ_KEYCHAIN_SERVICE = "stock-ultimus-read-access-token"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def keychain_password(service: str) -> str | None:
    user = os.getenv("USER") or ""
    if not user:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", user, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def v31_publish_status(output: str) -> str:
    if (
        "V28.3 OFFICIAL V31 SNAPSHOT PUBLISHED | ok:True" in output
        or "V31 REMOTE MASTER SNAPSHOT PUBLISHED | ok:True" in output
        or "V31 SNAPSHOT PUBLISHED | ok:True" in output
    ):
        return "V31_PUBLISHED"
    if (
        "V28.3 OFFICIAL V31 SNAPSHOT ERROR" in output
        or "V28 REMOTE MASTER SNAPSHOT PUBLISH ERROR" in output
        or "V31 canonical publish call error" in output
    ):
        return "V31_PUBLISH_FAILED"
    return "V31_PUBLISH_NOT_CONFIRMED"


def post_json(url: str, token: str, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Accept": "application/json",
            "X-Stock-Ultimus-Read-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status_code": exc.code, "body": body[:500]}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def run_bridge(args: argparse.Namespace, ingest_token: str) -> dict[str, Any]:
    if not port_open(args.ibkr_host, args.ibkr_port):
        return {
            "ok": False,
            "status": "IBKR_PORT_CLOSED",
            "detail": f"{args.ibkr_host}:{args.ibkr_port} is not accepting connections.",
        }

    env = os.environ.copy()
    env["TRADING_ENGINE_INGEST_TOKEN"] = ingest_token
    env["IBKR_HOST"] = args.ibkr_host
    env["IBKR_PORT"] = str(args.ibkr_port)
    env["IBKR_CLIENT_ID"] = str(args.ibkr_client_id)
    env["IBKR_HISTORICAL_DATA_TIMEOUT_SECONDS"] = str(args.historical_data_timeout)
    env["PYTHONUNBUFFERED"] = "1"
    if args.fast:
        env["DAILY_RADAR_FAST"] = "1"
    if args.coberturas_rsp_weekly:
        env["COBERTURAS_RSP_WEEKLY"] = "1"
        env["IBKR_SKIP_CANONICAL_PUBLISH"] = "1"
        env.setdefault("IBKR_WATCHLIST", "RSP")
        env.setdefault("IBKR_OPTION_SYMBOLS", "RSP")
        env.setdefault("IBKR_MAX_OPTIONS_PER_SYMBOL", "4")
        env.setdefault("IBKR_MAX_OPTION_SYMBOLS_PER_RUN", "1")
        env.setdefault("IBKR_MAX_TOTAL_OPTION_CONTRACTS_PER_RUN", "4")
        env.setdefault("IBKR_TARGET_DTE_MIN", "7")
        env.setdefault("IBKR_TARGET_DTE_MAX", "14")
        env.setdefault("IBKR_TARGET_DTE_IDEAL", "8")
        env.setdefault("IBKR_DYNAMIC_OPTION_UNIVERSE_ENABLED", "0")
        env.setdefault("IBKR_INCLUDE_RUNTIME_TECHNICAL_OPTION_CANDIDATES", "0")

    cmd = [sys.executable, str(ROOT / "ibkr_bridge.py"), "--once"]
    started_at = now_iso()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=args.bridge_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial_stdout = exc.stdout or ""
        partial_stderr = exc.stderr or ""
        if isinstance(partial_stdout, bytes):
            partial_stdout = partial_stdout.decode("utf-8", errors="replace")
        if isinstance(partial_stderr, bytes):
            partial_stderr = partial_stderr.decode("utf-8", errors="replace")
        tail = "\n".join((partial_stdout + "\n" + partial_stderr).splitlines()[-40:])
        return {
            "ok": False,
            "status": "BRIDGE_TIMEOUT",
            "started_at": started_at,
            "timeout_seconds": args.bridge_timeout,
            "tail": tail,
        }

    output = result.stdout + "\n" + result.stderr
    tail = "\n".join(output.splitlines()[-30:])
    publish_status = v31_publish_status(output)
    local_ok = result.returncode == 0
    return {
        "ok": local_ok,
        "status": "BRIDGE_OK" if local_ok and publish_status == "V31_PUBLISHED" else ("BRIDGE_OK_PUBLISH_PENDING" if local_ok else "BRIDGE_FAILED"),
        "returncode": result.returncode,
        "started_at": started_at,
        "finished_at": now_iso(),
        "published": publish_status == "V31_PUBLISHED",
        "publish_status": publish_status,
        "tail": tail,
    }


def refresh_rsp_account_capacity(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "ibkr_account_profile.py"),
        "refresh-account-capacity",
        "--host",
        args.ibkr_host,
        "--port",
        str(args.ibkr_port),
        "--client-id",
        str(args.ibkr_client_id),
        "--timeout",
        "20",
        "--json-out",
        str(ROOT / "runtime" / "coberturas_rsp_account_capacity_latest.json"),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=35,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "RSP_ACCOUNT_CAPACITY_TIMEOUT"}
    return {
        "ok": result.returncode == 0,
        "status": "RSP_ACCOUNT_CAPACITY_READY" if result.returncode == 0 else "RSP_ACCOUNT_CAPACITY_FAILED",
        "exit_code": result.returncode,
        "output_tail": (result.stdout + "\n" + result.stderr)[-1200:],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Stock Ultimus bridge repeatedly during market.")
    parser.add_argument("--public-base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL))
    parser.add_argument("--ibkr-host", default=os.getenv("IBKR_HOST", "127.0.0.1"))
    parser.add_argument("--ibkr-port", type=int, default=int(os.getenv("IBKR_PORT", "7496")))
    parser.add_argument("--ibkr-client-id", type=int, default=int(os.getenv("IBKR_CLIENT_ID", "42")))
    parser.add_argument(
        "--historical-data-timeout",
        type=int,
        default=int(os.getenv("IBKR_HISTORICAL_DATA_TIMEOUT_SECONDS", "4")),
    )
    parser.add_argument("--interval-minutes", type=float, default=float(os.getenv("STOCK_ULTIMUS_BRIDGE_INTERVAL_MINUTES", "15")))
    parser.add_argument("--max-runs", type=int, default=int(os.getenv("STOCK_ULTIMUS_BRIDGE_MAX_RUNS", "1")))
    parser.add_argument("--bridge-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_BRIDGE_TIMEOUT", "420")))
    parser.add_argument("--read-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "30")))
    parser.add_argument("--fast", action="store_true", help="Use DAILY_RADAR_FAST=1. Enabled by default unless --full-scan is passed.")
    parser.add_argument("--full-scan", action="store_true", help="Disable fast mode and scan the full configured option depth.")
    parser.add_argument("--coberturas-rsp-weekly", action="store_true", help="Run an RSP-only 7-14 DTE options refresh for Coberturas.")
    parser.add_argument("--notify", action="store_true", help="Call /v31_monitor_notify after successful bridge runs.")
    parser.add_argument("--force-notify", action="store_true", help="Pass force=true when calling monitor notify.")
    parser.add_argument("--json-out", default=str(ROOT / "runtime" / "market_bridge_session_latest.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.fast = bool(args.fast or not args.full_scan)
    ingest_token = os.getenv("TRADING_ENGINE_INGEST_TOKEN") or keychain_password(INGEST_KEYCHAIN_SERVICE)
    read_token = os.getenv("READ_ACCESS_TOKEN") or keychain_password(READ_KEYCHAIN_SERVICE)
    if not ingest_token:
        print("Missing snapshot ingest token in env or Keychain.", file=sys.stderr)
        return 2
    if args.notify and not read_token:
        print("Missing read token for --notify.", file=sys.stderr)
        return 3

    session: dict[str, Any] = {
        "engine": "MARKET_BRIDGE_SESSION",
        "started_at": now_iso(),
        "ibkr_host": args.ibkr_host,
        "ibkr_port": args.ibkr_port,
        "ibkr_client_id": args.ibkr_client_id,
        "historical_data_timeout": args.historical_data_timeout,
        "fast_mode": args.fast,
        "interval_minutes": args.interval_minutes,
        "max_runs": args.max_runs,
        "runs": [],
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if args.coberturas_rsp_weekly:
        session["rsp_account_alias"] = os.getenv("IBKR_ACCOUNT_ALIAS") or os.getenv("STOCK_ULTIMUS_ACCOUNT_SCOPE") or "unknown"
        session["rsp_account_capacity"] = refresh_rsp_account_capacity(args)
    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for index in range(max(1, args.max_runs)):
        print(f"Run {index + 1}/{args.max_runs}: refreshing IBKR snapshot...")
        run = run_bridge(args, ingest_token)
        if args.coberturas_rsp_weekly and run.get("ok"):
            run["rsp_reconciliation"] = coberturas_engine.reconcile_broker_position(ROOT / "runtime")
        if args.notify and run.get("ok") and read_token:
            suffix = "?force=true" if args.force_notify else ""
            notify = post_json(args.public_base_url.rstrip("/") + "/v31_monitor_notify" + suffix, read_token, args.read_timeout)
            run["monitor_notify"] = {
                "status": notify.get("status"),
                "email_sent": notify.get("email_sent"),
                "notify_reason": notify.get("notify_reason"),
                "subject": notify.get("subject"),
                "not_order_instruction": notify.get("not_order_instruction"),
            }
        session["runs"].append(run)
        out_path.write_text(json.dumps(session, indent=2, sort_keys=True))
        print(json.dumps({k: run.get(k) for k in ["ok", "status", "published", "monitor_notify"]}, indent=2, sort_keys=True))
        if index < args.max_runs - 1:
            time.sleep(max(1.0, args.interval_minutes * 60.0))

    session["finished_at"] = now_iso()
    capacity_ok = not args.coberturas_rsp_weekly or bool((session.get("rsp_account_capacity") or {}).get("ok"))
    session["ok"] = all(bool(run.get("ok")) for run in session["runs"]) and capacity_ok
    out_path.write_text(json.dumps(session, indent=2, sort_keys=True))
    return 0 if session["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
