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
    return {
        "ok": result.returncode == 0,
        "status": "BRIDGE_OK" if result.returncode == 0 else "BRIDGE_FAILED",
        "returncode": result.returncode,
        "started_at": started_at,
        "finished_at": now_iso(),
        "published": "V31 SNAPSHOT PUBLISHED" in output or "REMOTE INGEST: True" in output,
        "tail": tail,
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
    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for index in range(max(1, args.max_runs)):
        print(f"Run {index + 1}/{args.max_runs}: refreshing IBKR snapshot...")
        run = run_bridge(args, ingest_token)
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
    session["ok"] = all(bool(run.get("ok")) for run in session["runs"])
    out_path.write_text(json.dumps(session, indent=2, sort_keys=True))
    return 0 if session["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
