#!/usr/bin/env python3
"""Install the Stock Ultimus native macOS notification monitor."""

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
LABEL = "com.stockultimus.macos-notifications"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
SCRIPT = ROOT / "scripts" / "run_macos_notifications.py"
RUNNER_DIR = Path.home() / "Library" / "Application Support" / "Stock Ultimus" / "Launchd"
RUNNER = RUNNER_DIR / "stock_ultimus_macos_notifications.py"
SHARED_RUNTIME = Path.home() / "Library" / "Application Support" / "Stock Ultimus" / "Runtime"


def domain() -> str:
    return f"gui/{os.getuid()}"


def launchctl(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout_tail": (proc.stdout or "")[-800:], "stderr_tail": (proc.stderr or "")[-800:]}


def payload() -> dict[str, Any]:
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(RUNNER)],
        "WorkingDirectory": str(RUNNER_DIR),
        "StartInterval": 15,
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "StandardOutPath": "/private/tmp/com.stockultimus.macos-notifications.out",
        "StandardErrorPath": "/private/tmp/com.stockultimus.macos-notifications.err",
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "STOCK_ULTIMUS_PROJECT_ROOT": str(ROOT),
            "STOCK_ULTIMUS_RUNTIME_DIR": str(SHARED_RUNTIME),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result: dict[str, Any] = {"engine": "MACOS_NOTIFICATIONS_LAUNCHD_INSTALLER", "label": LABEL, "plist": str(PLIST)}
    if args.dry_run:
        result.update({"action": "dry-run", "payload": payload()})
    elif args.uninstall:
        result.update({"action": "uninstall", "bootout": launchctl(["launchctl", "bootout", domain(), str(PLIST)])})
        try:
            PLIST.unlink()
            result["removed"] = True
        except FileNotFoundError:
            result["removed"] = False
    elif args.install:
        subprocess.run([sys.executable, str(SCRIPT), "--prime"], capture_output=True, text=True, timeout=30, check=False)
        RUNNER_DIR.mkdir(parents=True, exist_ok=True)
        RUNNER.write_text(SCRIPT.read_text())
        RUNNER.chmod(0o755)
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        with PLIST.open("wb") as handle:
            plistlib.dump(payload(), handle, sort_keys=True)
        launchctl(["launchctl", "bootout", domain(), str(PLIST)])
        result.update({"action": "install", "bootstrap": launchctl(["launchctl", "bootstrap", domain(), str(PLIST)]), "enable": launchctl(["launchctl", "enable", f"{domain()}/{LABEL}"])})
    else:
        result.update({"action": "status", "installed": PLIST.exists(), "launchd": launchctl(["launchctl", "print", f"{domain()}/{LABEL}"])})
    result.update({"execution_authorized": False, "not_order_instruction": True})
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
