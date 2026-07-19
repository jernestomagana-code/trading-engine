#!/usr/bin/env python3
"""Install secret-free launchd jobs for local portfolio-risk operations.

The background jobs use an Application Support runner and call the localhost
console, avoiding macOS privacy/TCC denial for projects stored in Documents.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = Path("/private/tmp")
PYTHON = sys.executable
RUNNER_DIR = Path.home() / "Library" / "Application Support" / "Stock Ultimus" / "Launchd"
RUNNER_PATH = RUNNER_DIR / "stock_ultimus_launchd_console_runner.py"
RUNNER_SOURCE = ROOT / "scripts" / "stock_ultimus_launchd_console_runner.py"
JOBS = {
    "monitor": {
        "label": "com.stockultimus.portfolio-risk-monitor",
        "args": ["--mode", "monitor", "--refresh-broker"],
        "start_interval": 300,
        "description": "Refreshes and evaluates broker risk every five minutes inside the configured window.",
    },
    "digest": {
        "label": "com.stockultimus.portfolio-risk-digest",
        "args": ["--mode", "digest"],
        "calendar": [
            {"Weekday": day, "Hour": 17, "Minute": 35}
            for day in range(1, 6)
        ],
        "description": "Builds the daily local risk digest after the monitoring window.",
    },
    "preflight": {
        "label": "com.stockultimus.portfolio-risk-preflight",
        "args": ["--mode", "preflight"],
        "calendar": [
            {"Weekday": day, "Hour": 7, "Minute": 0}
            for day in range(1, 6)
        ],
        "description": "Checks policy, snapshots, lifecycle, and outbox before monitoring starts.",
    },
}


def selected_jobs(value: str) -> dict[str, dict[str, Any]]:
    names = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return {name: JOBS[name] for name in names if name in JOBS}


def plist_path(job: dict[str, Any]) -> Path:
    return LAUNCH_AGENTS / f"{job['label']}.plist"


def plist_payload(job: dict[str, Any], enable_local_notifications: bool = False) -> dict[str, Any]:
    arguments = [PYTHON, str(RUNNER_PATH), job["label"].replace("com.stockultimus.", "")]
    if enable_local_notifications and job.get("label") == JOBS["monitor"]["label"]:
        arguments.append("--local-notify")
    payload: dict[str, Any] = {
        "Label": job["label"],
        "ProgramArguments": arguments,
        "WorkingDirectory": str(RUNNER_DIR),
        "StandardOutPath": str(LOG_DIR / f"{job['label']}.out"),
        "StandardErrorPath": str(LOG_DIR / f"{job['label']}.err"),
        "RunAtLoad": False,
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "STOCK_ULTIMUS_CONSOLE_URL": "http://127.0.0.1:8765",
        },
    }
    if job.get("start_interval"):
        payload["StartInterval"] = int(job["start_interval"])
    if job.get("calendar"):
        calendar = job["calendar"]
        payload["StartCalendarInterval"] = (
            [dict(item) for item in calendar]
            if isinstance(calendar, list)
            else dict(calendar)
        )
    return payload


def install_runner(dry_run: bool) -> dict[str, Any]:
    result = {
        "runner_path": str(RUNNER_PATH),
        "source": str(RUNNER_SOURCE),
        "installed": False,
    }
    if dry_run:
        return result
    RUNNER_DIR.mkdir(parents=True, exist_ok=True)
    RUNNER_PATH.write_text(RUNNER_SOURCE.read_text())
    RUNNER_PATH.chmod(0o755)
    result["installed"] = True
    return result


def user_domain() -> str:
    return f"gui/{os.getuid()}"


def launchctl(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-800:],
        "stderr_tail": (proc.stderr or "")[-800:],
    }


def install(jobs: dict[str, dict[str, Any]], dry_run: bool, enable_local_notifications: bool) -> dict[str, Any]:
    runner = install_runner(dry_run)
    results = []
    for name, job in jobs.items():
        path = plist_path(job)
        payload = plist_payload(job, enable_local_notifications)
        item: dict[str, Any] = {"job": name, "path": str(path), "description": job["description"], "plist": payload}
        if not dry_run:
            LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                plistlib.dump(payload, handle, sort_keys=True)
            launchctl(["launchctl", "bootout", user_domain(), str(path)])
            item["bootstrap"] = launchctl(["launchctl", "bootstrap", user_domain(), str(path)])
            item["enable"] = launchctl(["launchctl", "enable", f"{user_domain()}/{job['label']}"])
        results.append(item)
    return {"action": "install", "dry_run": dry_run, "runner": runner, "results": results}


def uninstall(jobs: dict[str, dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    results = []
    for name, job in jobs.items():
        path = plist_path(job)
        item: dict[str, Any] = {"job": name, "path": str(path)}
        if not dry_run:
            item["bootout"] = launchctl(["launchctl", "bootout", user_domain(), str(path)])
            try:
                path.unlink()
                item["removed"] = True
            except FileNotFoundError:
                item["removed"] = False
        results.append(item)
    return {"action": "uninstall", "dry_run": dry_run, "results": results}


def status(jobs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "action": "status",
        "dry_run": False,
        "results": [{
            "job": name,
            "path": str(plist_path(job)),
            "installed": plist_path(job).exists(),
            "launchd": launchctl(["launchctl", "print", f"{user_domain()}/{job['label']}"]),
        } for name, job in jobs.items()],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jobs", default="monitor,digest,preflight")
    parser.add_argument("--enable-local-notifications", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    jobs = selected_jobs(args.jobs)
    if not jobs:
        print("No valid jobs selected.", file=sys.stderr)
        return 2
    if args.install:
        result = install(jobs, args.dry_run, args.enable_local_notifications)
    elif args.uninstall:
        result = uninstall(jobs, args.dry_run)
    else:
        result = status(jobs)
    result.update({
        "engine": "STOCK_ULTIMUS_PORTFOLIO_RISK_LAUNCHD_V1",
        "local_notifications_enabled": bool(args.enable_local_notifications),
        "external_notifications_enabled": False,
        "secrets_printed": False,
        "execution_authorized": False,
        "automatic_liquidation_authorized": False,
        "not_order_instruction": True,
    })
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
