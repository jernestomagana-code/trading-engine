#!/usr/bin/env python3
"""Local V32 Pushover automation wrapper.

Modes:
- monitor: run the actionable-alert notifier during the market window.
- post-close: run post-close outcome evaluation once per US trading date and
  send a Pushover summary only when there is something to review.
- preflight: verify the local Pushover channel and write a status artifact.

This script never places orders, never authorizes execution, and never prints
tokens. It is designed for launchd.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
DEFAULT_OUT = RUNTIME / "v32_pushover_automation_latest.json"
POST_CLOSE_STATE = RUNTIME / "v32_pushover_post_close_state.json"
NY_TZ = ZoneInfo("America/New_York")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local V32 Pushover automation safely.")
    parser.add_argument("--mode", choices=["monitor", "post-close", "preflight"], required=True)
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", "https://trading-engine-p097.onrender.com"))
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_PUSHOVER_AUTOMATION_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "45")))
    parser.add_argument("--limit", type=int, default=int(os.getenv("STOCK_ULTIMUS_OPERATOR_ALERT_LIMIT", "12")))
    parser.add_argument("--force", action="store_true", help="Bypass time/dedupe gates for a deliberate smoke test.")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ny() -> datetime:
    return now_utc().astimezone(NY_TZ)


def ny_market_date() -> str:
    return now_ny().date().isoformat()


def in_weekday_window(start: time, end: time) -> bool:
    current = now_ny()
    if current.weekday() >= 5:
        return False
    current_time = current.time().replace(tzinfo=None)
    return start <= current_time <= end


def market_monitor_window() -> bool:
    return in_weekday_window(time(9, 25), time(16, 10))


def post_close_window() -> bool:
    return in_weekday_window(time(16, 10), time(18, 30))


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def tail(text: str, limit: int = 2500) -> str:
    return (text or "")[-limit:]


def run_command(command: list[str], timeout: int) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
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
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": None,
            "command": command,
            "error": f"TIMEOUT_AFTER_{timeout}_SECONDS",
            "stdout_tail": tail(exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""),
            "stderr_tail": tail(exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""),
        }
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "command": command,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
    }


def parse_stdout_json(step: dict[str, Any]) -> dict[str, Any]:
    raw = step.get("stdout_tail") or ""
    start = raw.find("{")
    if start < 0:
        return {}
    try:
        return json.loads(raw[start:])
    except Exception:
        return {}


def send_pushover_summary(message: str, timeout: int) -> dict[str, Any]:
    from scripts import v32_operator_notify as notify

    report = {
        "engine": "V32_PUSHOVER_AUTOMATION",
        "operator_status": "POST_CLOSE_REVIEW",
        "classification": {
            "should_notify": True,
            "notify_reason": "POST_CLOSE_REVIEW",
            "actionable_count": 0,
            "actionable_alerts": [],
        },
        "custom_message": message,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    return notify.send_pushover_notification(
        report,
        notify.first_keychain_password(notify.PUSHOVER_USER_KEYCHAIN_SERVICES),
        notify.first_keychain_password(notify.PUSHOVER_API_TOKEN_KEYCHAIN_SERVICES),
        timeout,
    )


def run_monitor(args: argparse.Namespace) -> dict[str, Any]:
    allowed = args.force or market_monitor_window()
    if not allowed:
        return {
            "status": "SKIPPED",
            "reason": "OUTSIDE_MARKET_MONITOR_WINDOW",
            "ny_time": now_ny().isoformat(),
            "notification_sent": False,
        }
    command = [
        sys.executable,
        "scripts/v32_operator_notify.py",
        "--base-url",
        args.base_url,
        "--timeout",
        str(args.timeout),
        "--limit",
        str(args.limit),
        "--pushover",
    ]
    step = run_command(command, timeout=max(60, args.timeout + 20))
    payload = parse_stdout_json(step)
    return {
        "status": "OK" if step.get("ok") else "ACTION_REQUIRED",
        "reason": payload.get("classification", {}).get("notify_reason"),
        "notification_sent": bool(payload.get("notification_sent")),
        "operator_status": payload.get("operator_status"),
        "operator_readiness": payload.get("operator_readiness"),
        "step": step,
    }


def post_close_already_ran() -> bool:
    state = load_json(POST_CLOSE_STATE)
    return state.get("market_date") == ny_market_date() and state.get("status") == "OK"


def mark_post_close(status: str) -> None:
    save_json(POST_CLOSE_STATE, {"market_date": ny_market_date(), "status": status, "updated_at": now_utc().isoformat()})


def outcome_review_counts(payload: dict[str, Any]) -> dict[str, int]:
    counts = {"evaluated": 0, "not_evaluated": 0, "saved": 0}
    for item in payload.get("evaluations") or []:
        if not isinstance(item, dict):
            continue
        counts["evaluated"] += int(item.get("evaluated_count") or 0)
        counts["not_evaluated"] += int(item.get("not_evaluated_count") or 0)
        counts["saved"] += int(item.get("saved_count") or 0)
    return counts


def run_post_close(args: argparse.Namespace) -> dict[str, Any]:
    if not (args.force or post_close_window()):
        return {
            "status": "SKIPPED",
            "reason": "OUTSIDE_POST_CLOSE_WINDOW",
            "ny_time": now_ny().isoformat(),
            "notification_sent": False,
        }
    if not args.force and post_close_already_ran():
        return {
            "status": "SKIPPED",
            "reason": "POST_CLOSE_ALREADY_RAN_FOR_MARKET_DATE",
            "market_date": ny_market_date(),
            "notification_sent": False,
        }
    command = [
        sys.executable,
        "scripts/run_daily_outcome_evaluation.py",
        "--base-url",
        args.base_url,
        "--timeout",
        str(args.timeout),
    ]
    step = run_command(command, timeout=max(180, args.timeout * 8))
    payload = parse_stdout_json(step)
    counts = outcome_review_counts(payload)
    should_notify = (not step.get("ok")) or counts["evaluated"] or counts["not_evaluated"]
    notification_result = None
    if should_notify:
        message = (
            "Post-cierre Stock Ultimus: "
            f"evaluated={counts['evaluated']}, not_evaluated={counts['not_evaluated']}, saved={counts['saved']}. "
            "Revisar backtesting/outcomes. No orden autorizada."
        )
        notification_result = send_pushover_summary(message, args.timeout)
    if step.get("ok"):
        mark_post_close("OK")
    return {
        "status": "OK" if step.get("ok") else "ACTION_REQUIRED",
        "reason": "POST_CLOSE_OUTCOME_EVALUATION",
        "market_date": ny_market_date(),
        "counts": counts,
        "notification_sent": bool((notification_result or {}).get("sent")),
        "notification_result": notification_result,
        "step": step,
    }


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    command = [sys.executable, "scripts/setup_pushover_channel.py", "--no-write"]
    step = run_command(command, timeout=max(45, args.timeout))
    payload = parse_stdout_json(step)
    return {
        "status": "OK" if payload.get("ready") is True else "ACTION_REQUIRED",
        "reason": "PUSHOVER_CHANNEL_PREFLIGHT",
        "ready": bool(payload.get("ready")),
        "step": step,
    }


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    if args.mode == "monitor":
        mode_result = run_monitor(args)
    elif args.mode == "post-close":
        mode_result = run_post_close(args)
    else:
        mode_result = run_preflight(args)
    return {
        "engine": "V32_PUSHOVER_AUTOMATION",
        "automation_version": "v32_pushover_automation_v1",
        "mode": args.mode,
        "checked_at": now_utc().isoformat(),
        "ny_time": now_ny().isoformat(),
        "base_url": args.base_url.rstrip("/"),
        "mode_result": mode_result,
        "status": mode_result.get("status"),
        "secrets_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def main() -> int:
    args = parse_args()
    result = build_result(args)
    if not args.no_write:
        save_json(Path(args.json_out), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"OK", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
