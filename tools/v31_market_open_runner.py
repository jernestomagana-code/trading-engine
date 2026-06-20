#!/usr/bin/env python3
"""Run the Stock Ultimus V31 market-open validation sequence.

This is an orchestration wrapper for the first live-market validation window:
1) read-only IBKR option quote probe,
2) read-only bridge publish through the V31 operational check,
3) one JSON report with pass/fail status.

It never places orders and never prints secrets. Tokens are read from Keychain
and passed only through environment variables to child processes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_READ_TOKEN_SERVICE = "stock-ultimus-read-access"
DEFAULT_INGEST_TOKEN_SERVICE = "stock-ultimus-snapshot-ingest"


@dataclass
class StepResult:
    name: str
    ok: bool
    command: list[str]
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    skipped: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "skipped": self.skipped,
            "detail": self.detail,
        }


def tail(text: str, limit: int = 4000) -> str:
    text = text or ""
    return text[-limit:]


def keychain_secret(service: str, account: str | None = None) -> str:
    cmd = ["security", "find-generic-password"]
    if account:
        cmd.extend(["-a", account])
    cmd.extend(["-s", service, "-w"])
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()


def quote_probe_command(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        "tools/ibkr_option_quote_probe.py",
        "--ticker",
        args.ticker,
        "--right",
        args.right,
        "--target-dte",
        str(args.target_dte),
        "--otm-pct",
        str(args.otm_pct),
        "--port",
        str(args.ibkr_port),
        "--market-data-types",
        args.market_data_types,
        "--underlying-wait",
        str(args.underlying_wait),
        "--stream-wait",
        str(args.stream_wait),
        "--snapshot-wait",
        str(args.snapshot_wait),
        "--timeout",
        str(args.ibkr_timeout),
    ]


def operational_check_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        "tools/v31_operational_check.py",
        "--ticker",
        args.ticker,
        "--remote-url",
        args.remote_url,
        "--min-rows",
        str(args.min_rows),
        "--ibkr-port",
        str(args.ibkr_port),
        "--market-data-type",
        str(args.bridge_market_data_type),
        "--historical-timeout",
        str(args.historical_timeout),
        "--stock-wait",
        str(args.stock_wait),
        "--option-wait",
        str(args.option_wait),
        "--option-second-wait",
        str(args.option_second_wait),
        "--bridge-timeout",
        str(args.bridge_timeout),
        "--timeout",
        str(args.http_timeout),
    ]
    if not args.skip_bridge:
        cmd.append("--run-bridge")
    if not args.allow_closed_market:
        cmd.append("--require-open-data")
    return cmd


def run_step(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    dry_run: bool = False,
    skipped: bool = False,
    detail: str = "",
) -> StepResult:
    if skipped:
        return StepResult(name=name, ok=True, command=command, skipped=True, detail=detail)
    if dry_run:
        return StepResult(name=name, ok=True, command=command, skipped=True, detail="dry_run")
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return StepResult(
        name=name,
        ok=proc.returncode == 0,
        command=command,
        exit_code=proc.returncode,
        stdout_tail=tail(proc.stdout),
        stderr_tail=tail(proc.stderr),
    )


def build_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    if args.dry_run:
        return env

    if not env.get("READ_ACCESS_TOKEN"):
        env["READ_ACCESS_TOKEN"] = keychain_secret(args.read_token_service, args.keychain_account or None)
    if not env.get("TRADING_ENGINE_INGEST_TOKEN"):
        env["TRADING_ENGINE_INGEST_TOKEN"] = keychain_secret(args.ingest_token_service, args.keychain_account or None)
    return env


def run_market_open_validation(args: argparse.Namespace, repo_root: Path) -> dict[str, Any]:
    env = build_env(args)
    steps: list[StepResult] = []

    probe = run_step(
        "ibkr_option_quote_probe",
        quote_probe_command(args),
        cwd=repo_root,
        env=env,
        timeout=args.probe_timeout,
        dry_run=args.dry_run,
        skipped=args.skip_probe,
        detail="skip_probe" if args.skip_probe else "",
    )
    steps.append(probe)

    if probe.ok or args.continue_on_probe_failure:
        steps.append(
            run_step(
                "v31_operational_check",
                operational_check_command(args),
                cwd=repo_root,
                env=env,
                timeout=args.operational_timeout,
                dry_run=args.dry_run,
            )
        )

    ok = all(step.ok for step in steps)
    return {
        "engine": "V31_MARKET_OPEN_RUNNER",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ticker": args.ticker,
        "remote_url": args.remote_url,
        "dry_run": bool(args.dry_run),
        "allow_closed_market": bool(args.allow_closed_market),
        "skip_probe": bool(args.skip_probe),
        "skip_bridge": bool(args.skip_bridge),
        "continue_on_probe_failure": bool(args.continue_on_probe_failure),
        "steps": [step.as_dict() for step in steps],
        "ok": ok,
        "not_order_instruction": True,
        "secrets_printed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the V31 market-open validation sequence.")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--remote-url", default="https://trading-engine-p097.onrender.com")
    parser.add_argument("--right", choices=["P", "C", "p", "c"], default="P")
    parser.add_argument("--target-dte", type=int, default=45)
    parser.add_argument("--otm-pct", type=float, default=0.10)
    parser.add_argument("--ibkr-port", default="7496")
    parser.add_argument("--market-data-types", default="1,2,3,4")
    parser.add_argument("--bridge-market-data-type", default="1")
    parser.add_argument("--min-rows", type=int, default=1)
    parser.add_argument("--underlying-wait", type=float, default=6)
    parser.add_argument("--stream-wait", type=float, default=12)
    parser.add_argument("--snapshot-wait", type=float, default=4)
    parser.add_argument("--ibkr-timeout", type=float, default=10)
    parser.add_argument("--historical-timeout", default="4")
    parser.add_argument("--stock-wait", default="3")
    parser.add_argument("--option-wait", default="12")
    parser.add_argument("--option-second-wait", default="8")
    parser.add_argument("--http-timeout", default="20")
    parser.add_argument("--probe-timeout", type=int, default=180)
    parser.add_argument("--bridge-timeout", default="240")
    parser.add_argument("--operational-timeout", type=int, default=360)
    parser.add_argument("--read-token-service", default=DEFAULT_READ_TOKEN_SERVICE)
    parser.add_argument("--ingest-token-service", default=DEFAULT_INGEST_TOKEN_SERVICE)
    parser.add_argument("--keychain-account", default="")
    parser.add_argument("--skip-probe", action="store_true")
    parser.add_argument("--skip-bridge", action="store_true")
    parser.add_argument("--allow-closed-market", action="store_true")
    parser.add_argument("--continue-on-probe-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.ticker = args.ticker.upper()
    repo_root = Path(__file__).resolve().parents[1]
    result = run_market_open_validation(args, repo_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
