#!/usr/bin/env python3
"""Run the Stock Ultimus operating-day cycle.

This is the local "one command" wrapper for the human-in-the-loop workflow:

1) refresh the read-only IBKR snapshot through the daily radar helper,
2) check local foundation health,
3) read GPT-facing readiness/rankings,
4) evaluate pending paper outcomes and manual reviews,
5) check GPT Action health,
6) write one redacted operational report.

It never places orders, never authorizes execution, and never prints tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "runtime" / "operating_day_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Stock Ultimus operating-day workflow.")
    parser.add_argument("--public-base-url", default=os.getenv("PUBLIC_BASE_URL", "https://trading-engine-p097.onrender.com"))
    parser.add_argument("--preview", type=int, default=int(os.getenv("STOCK_ULTIMUS_PREVIEW_ROWS", "5")))
    parser.add_argument("--bridge-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_BRIDGE_TIMEOUT", "240")))
    parser.add_argument("--read-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "45")))
    parser.add_argument("--outcome-limit", type=int, default=int(os.getenv("STOCK_ULTIMUS_EVALUATION_LIMIT", "100")))
    parser.add_argument("--checkpoints", default=os.getenv("STOCK_ULTIMUS_EVALUATION_CHECKPOINTS", "EOD,PLUS_1D,PLUS_5D"))
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_OPERATING_DAY_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--skip-bridge", action="store_true", help="Only read/evaluate cloud state; do not touch IBKR.")
    parser.add_argument("--allow-partial", action="store_true", help="Continue if bridge refresh fails.")
    parser.add_argument("--skip-foundation-health", action="store_true", help="Skip the local foundation health gate.")
    parser.add_argument("--skip-outcomes", action="store_true", help="Skip outcome/manual-review evaluation.")
    parser.add_argument("--skip-gpt-health", action="store_true", help="Skip GPT Action health monitor.")
    parser.add_argument("--dry-run-outcomes", action="store_true", help="Preview outcome evaluation without persisting updates.")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tail(text: str, limit: int = 3500) -> str:
    return (text or "")[-limit:]


def run_step(name: str, command: list[str], timeout: int, env: dict[str, str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "name": name,
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "command": command,
            "stdout_tail": tail(proc.stdout),
            "stderr_tail": tail(proc.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "ok": False,
            "exit_code": None,
            "command": command,
            "stdout_tail": tail(exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""),
            "stderr_tail": tail(exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""),
            "error": f"TIMEOUT_AFTER_{timeout}_SECONDS",
        }


def command_daily_radar(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        "scripts/run_daily_radar.py",
        "--public-base-url",
        args.public_base_url,
        "--bridge-timeout",
        str(args.bridge_timeout),
        "--read-timeout",
        str(args.read_timeout),
        "--preview",
        str(args.preview),
    ]
    if args.skip_bridge:
        cmd.append("--skip-bridge")
    if args.allow_partial:
        cmd.append("--allow-partial")
    return cmd


def command_outcomes(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        "scripts/run_daily_outcome_evaluation.py",
        "--base-url",
        args.public_base_url,
        "--timeout",
        str(args.read_timeout),
        "--limit",
        str(args.outcome_limit),
        "--checkpoints",
        args.checkpoints,
    ]
    if args.dry_run_outcomes:
        cmd.append("--dry-run")
    return cmd


def command_gpt_health(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        "scripts/monitor_gpt_action_health.py",
        "--base-url",
        args.public_base_url,
        "--timeout",
        str(args.read_timeout),
    ]


def command_foundation_health() -> list[str]:
    return [
        sys.executable,
        "scripts/run_foundation_health_check.py",
        "--json-only",
        "--no-write",
        "--strict",
    ]


def classify_next_action(steps: list[dict[str, Any]]) -> str:
    failed = [step for step in steps if not step.get("ok")]
    if not failed:
        return "Abrir /v31_manual_review_inbox y revisar solo si hay ENTRY_READY; no es instruccion de operar."
    first = failed[0]
    if first.get("name") == "daily_radar_refresh":
        return "Revisar TWS/IB Gateway/API y runtime/ibkr_bridge_health_latest.json; luego reintentar el ciclo."
    if first.get("name") == "foundation_health":
        return "Resolver Foundation Health antes de depender del motor; revisar runtime/foundation_health_latest.json."
    if first.get("name") == "outcome_evaluation":
        return "Revisar endpoint de outcomes y token READ_ACCESS_TOKEN; el snapshot puede seguir siendo util."
    if first.get("name") == "gpt_action_health":
        return "Revisar Action del GPT oficial y sincronizar READ_ACCESS_TOKEN si hay 401."
    return "Revisar el primer paso fallido antes de tomar decisiones manuales."


def run(args: argparse.Namespace) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    steps: list[dict[str, Any]] = []

    daily = run_step(
        "daily_radar_refresh",
        command_daily_radar(args),
        timeout=max(args.bridge_timeout + 90, args.read_timeout + 30),
        env=env,
    )
    steps.append(daily)

    should_continue = daily["ok"] or args.allow_partial or args.skip_bridge
    if should_continue and not args.skip_foundation_health:
        foundation = run_step(
            "foundation_health",
            command_foundation_health(),
            timeout=60,
            env=env,
        )
        steps.append(foundation)
        should_continue = foundation["ok"] or args.allow_partial
    if should_continue and not args.skip_outcomes:
        steps.append(
            run_step(
                "outcome_evaluation",
                command_outcomes(args),
                timeout=max(120, args.read_timeout * 8),
                env=env,
            )
        )
    if should_continue and not args.skip_gpt_health:
        steps.append(
            run_step(
                "gpt_action_health",
                command_gpt_health(args),
                timeout=max(90, args.read_timeout * 4),
                env=env,
            )
        )

    ok = all(step.get("ok") for step in steps)
    return {
        "engine": "STOCK_ULTIMUS_OPERATING_DAY_RUNNER",
        "run_version": "operating_day_v1",
        "generated_at": now_iso(),
        "public_base_url": args.public_base_url,
        "ok": ok,
        "status": "PASS" if ok else "ACTION_REQUIRED",
        "steps": steps,
        "next_required_action": classify_next_action(steps),
        "manual_review_inbox": args.public_base_url.rstrip("/") + "/v31_manual_review_inbox",
        "manual_review_console": args.public_base_url.rstrip("/") + "/v31_manual_review_console",
        "manual_review_history": args.public_base_url.rstrip("/") + "/v31_manual_reviews_dashboard",
        "learning": args.public_base_url.rstrip("/") + "/v31_manual_review_learning",
        "learning_dashboard": args.public_base_url.rstrip("/") + "/v31_manual_review_learning_dashboard",
        "outcome_tracking": args.public_base_url.rstrip("/") + "/v31_outcome_tracking_status",
        "uses_ingest_token": not args.skip_bridge,
        "touches_ibkr": not args.skip_bridge,
        "sends_email": False,
        "secrets_printed": False,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def main() -> int:
    args = parse_args()
    result = run(args)
    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
