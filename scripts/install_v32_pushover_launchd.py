#!/usr/bin/env python3
"""Install local launchd jobs for Stock Ultimus V32 Pushover automation.

The jobs call scripts/v32_pushover_automation.py. Secrets stay in Keychain and
are never embedded into plist files.
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

JOBS = {
    "monitor": {
        "label": "com.stockultimus.v32-pushover-monitor",
        "args": ["--mode", "monitor"],
        "start_interval": 300,
        "description": "Runs every 5 minutes; wrapper only notifies inside US market window and actionable conditions.",
    },
    "post-close": {
        "label": "com.stockultimus.v32-pushover-postclose",
        "args": ["--mode", "post-close"],
        "start_interval": 900,
        "description": "Runs every 15 minutes; wrapper only evaluates once in the post-close window.",
    },
    "preflight": {
        "label": "com.stockultimus.v32-pushover-preflight",
        "args": ["--mode", "preflight"],
        "calendar": {"Hour": 7, "Minute": 10},
        "description": "Daily local channel check before the US market window.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install/uninstall Stock Ultimus Pushover launchd jobs.")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--jobs", default="monitor,post-close,preflight")
    return parser.parse_args()


def selected_jobs(names: str) -> dict[str, dict[str, Any]]:
    wanted = [item.strip() for item in names.split(",") if item.strip()]
    return {name: JOBS[name] for name in wanted if name in JOBS}


def plist_path(job: dict[str, Any]) -> Path:
    return LAUNCH_AGENTS / f"{job['label']}.plist"


def plist_payload(job: dict[str, Any]) -> dict[str, Any]:
    args = [
        PYTHON,
        str(ROOT / "scripts" / "v32_pushover_automation.py"),
        *job["args"],
    ]
    payload: dict[str, Any] = {
        "Label": job["label"],
        "ProgramArguments": args,
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(LOG_DIR / f"{job['label']}.out"),
        "StandardErrorPath": str(LOG_DIR / f"{job['label']}.err"),
        "RunAtLoad": False,
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
        },
    }
    if "start_interval" in job:
        payload["StartInterval"] = int(job["start_interval"])
    if "calendar" in job:
        payload["StartCalendarInterval"] = dict(job["calendar"])
    return payload


def launchctl(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    return {
        "command": command,
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-1000:],
        "stderr_tail": (proc.stderr or "")[-1000:],
    }


def user_domain() -> str:
    return f"gui/{os.getuid()}"


def install(jobs: dict[str, dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    results = []
    for name, job in jobs.items():
        path = plist_path(job)
        payload = plist_payload(job)
        item: dict[str, Any] = {"job": name, "label": job["label"], "path": str(path), "description": job["description"]}
        if not dry_run:
            LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                plistlib.dump(payload, handle, sort_keys=True)
            launchctl(["launchctl", "bootout", user_domain(), str(path)])
            item["bootstrap"] = launchctl(["launchctl", "bootstrap", user_domain(), str(path)])
            item["enable"] = launchctl(["launchctl", "enable", f"{user_domain()}/{job['label']}"])
        else:
            item["plist"] = payload
        results.append(item)
    return {"action": "install", "dry_run": dry_run, "results": results}


def uninstall(jobs: dict[str, dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    results = []
    for name, job in jobs.items():
        path = plist_path(job)
        item: dict[str, Any] = {"job": name, "label": job["label"], "path": str(path)}
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
    results = []
    for name, job in jobs.items():
        path = plist_path(job)
        item = {
            "job": name,
            "label": job["label"],
            "path": str(path),
            "installed": path.exists(),
            "print": launchctl(["launchctl", "print", f"{user_domain()}/{job['label']}"]),
        }
        results.append(item)
    return {"action": "status", "dry_run": False, "results": results}


def main() -> int:
    args = parse_args()
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
    result.update({
        "engine": "V32_PUSHOVER_LAUNCHD_INSTALLER",
        "secrets_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    })
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
