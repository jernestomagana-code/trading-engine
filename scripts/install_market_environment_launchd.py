#!/usr/bin/env python3
"""Install local launchd jobs for Stock Ultimus market environment checks.

Secrets stay in Keychain/env and are never embedded in plist files.
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
    "auth-preflight": {
        "label": "com.stockultimus.environment-auth-preflight",
        "program": "scripts/run_environment_auth_check.py",
        "args": [],
        "calendar": [
            {"Weekday": day, "Hour": 7, "Minute": 0}
            for day in range(1, 6)
        ],
        "description": "Checks read/ingest/Pushover auth before the market workflow.",
    },
    "daily-snapshot-refresh": {
        "label": "com.stockultimus.daily-snapshot-refresh",
        "program": "scripts/daily_open_checklist.py",
        "args": ["--refresh", "--publish"],
        "calendar": [
            {"Weekday": day, "Hour": hour, "Minute": minute}
            for day in range(1, 6)
            for hour, minute in [(8, 35), (9, 5), (9, 35)]
        ],
        "description": "Builds CANSLIM, refreshes IBKR, publishes V31 snapshot, and validates V32 after market open.",
    },
    "market-open-readiness": {
        "label": "com.stockultimus.market-open-readiness",
        "program": "scripts/run_market_open_readiness.py",
        "args": ["--market-closed-ok"],
        "calendar": [
            {"Weekday": day, "Hour": 7, "Minute": 20}
            for day in range(1, 6)
        ],
        "description": "Builds the market-open go/no-go and checklist.",
    },
    "post-open-monitor": {
        "label": "com.stockultimus.post-open-monitor",
        "program": "scripts/run_post_open_monitor.py",
        "args": ["--watch", "--cycles", "18", "--interval-seconds", "300"],
        "calendar": [
            {"Weekday": day, "Hour": 8, "Minute": 35}
            for day in range(1, 6)
        ],
        "description": "Runs a 90-minute post-open monitor window.",
    },
    "environment-alerts": {
        "label": "com.stockultimus.environment-alerts",
        "program": "scripts/run_environment_alerts.py",
        "args": ["--notify-watch", "--pushover"],
        "calendar": [
            {"Weekday": day, "Hour": hour, "Minute": minute}
            for day in range(1, 6)
            for hour, minute in [(8, 40), (9, 10), (9, 40)]
        ],
        "description": "Sends environment Pushover alerts when monitor state needs attention.",
    },
    "security-audit": {
        "label": "com.stockultimus.security-audit",
        "program": "scripts/run_security_audit.py",
        "args": ["--pushover"],
        "calendar": [
            {"Weekday": day, "Hour": 7, "Minute": 10}
            for day in range(1, 6)
        ],
        "description": "Runs local information-security checks and notifies only on ACTION findings.",
    },
    "dependency-audit": {
        "label": "com.stockultimus.dependency-audit",
        "program": "scripts/run_dependency_audit.py",
        "args": ["--pushover"],
        "calendar": [
            {"Weekday": 5, "Hour": 7, "Minute": 30}
        ],
        "description": "Runs weekly dependency vulnerability audit and notifies only on vulnerable packages.",
    },
    "local-dashboard": {
        "label": "com.stockultimus.local-environment-dashboard",
        "program": "scripts/build_local_environment_dashboard.py",
        "args": [],
        "start_interval": 600,
        "description": "Refreshes the local static environment dashboard every 10 minutes.",
    },
    "executive-report-daily": {
        "label": "com.stockultimus.executive-report-daily",
        "program": "scripts/build_executive_report.py",
        "args": ["--period", "daily"],
        "calendar": [
            {"Weekday": day, "Hour": 17, "Minute": 45}
            for day in range(1, 6)
        ],
        "description": "Builds the sanitized daily executive report after portfolio-risk digest.",
    },
    "executive-report-weekly": {
        "label": "com.stockultimus.executive-report-weekly",
        "program": "scripts/build_executive_report.py",
        "args": ["--period", "weekly"],
        "calendar": {"Weekday": 5, "Hour": 18, "Minute": 0},
        "description": "Builds the sanitized weekly executive report every Friday.",
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install Stock Ultimus environment launchd jobs.")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jobs", default="auth-preflight,daily-snapshot-refresh,market-open-readiness,post-open-monitor,environment-alerts,security-audit,dependency-audit,local-dashboard")
    return parser


def selected_jobs(names: str) -> dict[str, dict[str, Any]]:
    wanted = [item.strip() for item in names.split(",") if item.strip()]
    return {name: JOBS[name] for name in wanted if name in JOBS}


def plist_path(job: dict[str, Any]) -> Path:
    return LAUNCH_AGENTS / f"{job['label']}.plist"


def plist_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "Label": job["label"],
        "ProgramArguments": [PYTHON, str(RUNNER_PATH), job["label"].replace("com.stockultimus.", "")],
        "WorkingDirectory": str(RUNNER_DIR),
        "StandardOutPath": str(LOG_DIR / f"{job['label']}.out"),
        "StandardErrorPath": str(LOG_DIR / f"{job['label']}.err"),
        "RunAtLoad": False,
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "STOCK_ULTIMUS_CONSOLE_URL": "http://127.0.0.1:8765",
        },
    }
    if "calendar" in job:
        calendar = job["calendar"]
        payload["StartCalendarInterval"] = (
            [dict(item) for item in calendar]
            if isinstance(calendar, list)
            else dict(calendar)
        )
    if "start_interval" in job:
        payload["StartInterval"] = int(job["start_interval"])
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
        "command": command,
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-1000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
    }


def install(jobs: dict[str, dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    runner = install_runner(dry_run)
    results = []
    for name, job in jobs.items():
        path = plist_path(job)
        payload = plist_payload(job)
        result: dict[str, Any] = {
            "job": name,
            "label": job["label"],
            "path": str(path),
            "description": job["description"],
        }
        if dry_run:
            result["plist"] = payload
        else:
            LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                plistlib.dump(payload, handle, sort_keys=True)
            launchctl(["launchctl", "bootout", user_domain(), str(path)])
            result["bootstrap"] = launchctl(["launchctl", "bootstrap", user_domain(), str(path)])
            result["enable"] = launchctl(["launchctl", "enable", f"{user_domain()}/{job['label']}"])
        results.append(result)
    return {"action": "install", "dry_run": dry_run, "runner": runner, "results": results}


def uninstall(jobs: dict[str, dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    results = []
    for name, job in jobs.items():
        path = plist_path(job)
        result: dict[str, Any] = {"job": name, "label": job["label"], "path": str(path)}
        if not dry_run:
            result["bootout"] = launchctl(["launchctl", "bootout", user_domain(), str(path)])
            try:
                path.unlink()
                result["removed"] = True
            except FileNotFoundError:
                result["removed"] = False
        results.append(result)
    return {"action": "uninstall", "dry_run": dry_run, "results": results}


def status(jobs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    results = []
    for name, job in jobs.items():
        path = plist_path(job)
        results.append(
            {
                "job": name,
                "label": job["label"],
                "path": str(path),
                "installed": path.exists(),
                "print": launchctl(["launchctl", "print", f"{user_domain()}/{job['label']}"]),
            }
        )
    return {"action": "status", "dry_run": False, "results": results}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    jobs = selected_jobs(args.jobs)
    if not jobs:
        print("No valid jobs selected.", file=sys.stderr)
        return 2
    if args.install:
        result = install(jobs, args.dry_run)
    elif args.uninstall:
        result = uninstall(jobs, args.dry_run)
    else:
        result = status(jobs)
    result.update(
        {
            "engine": "STOCK_ULTIMUS_MARKET_ENVIRONMENT_LAUNCHD_INSTALLER",
            "secrets_printed": False,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
