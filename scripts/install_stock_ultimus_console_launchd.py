#!/usr/bin/env python3
"""Install a localhost Stock Ultimus Console launchd job.

The job serves scripts/ibkr_account_profile.py on 127.0.0.1. Secrets stay in
Keychain/env and are never embedded into plist files.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = Path("/private/tmp")
PYTHON = os.getenv("STOCK_ULTIMUS_CONSOLE_PYTHON", "/usr/bin/python3")
LABEL = "com.stockultimus.local-console"
OPENER_LABEL = "com.stockultimus.local-console-opener"
DEFAULT_PORT = 8765


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the Stock Ultimus localhost console launchd job.")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--install-opener-fallback", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--open", action="store_true", help="Open the local console URL after install/status.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def console_url(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}"


def plist_path() -> Path:
    return LAUNCH_AGENTS / f"{LABEL}.plist"


def opener_plist_path() -> Path:
    return LAUNCH_AGENTS / f"{OPENER_LABEL}.plist"


def plist_payload(port: int) -> dict[str, Any]:
    command = "cd {root} && exec {python} {script} serve --host 127.0.0.1 --port {port}".format(
        root=shlex.quote(str(ROOT)),
        python=shlex.quote(PYTHON),
        script=shlex.quote(str(ROOT / "scripts" / "ibkr_account_profile.py")),
        port=int(port),
    )
    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/bin/zsh",
            "-lc",
            command,
        ],
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(LOG_DIR / f"{LABEL}.out"),
        "StandardErrorPath": str(LOG_DIR / f"{LABEL}.err"),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
        },
    }


def opener_plist_payload() -> dict[str, Any]:
    command_file = ROOT / "Stock Ultimus Console.command"
    check_and_open = (
        "/usr/sbin/lsof -nP -iTCP:{port} -sTCP:LISTEN >/dev/null "
        "|| /usr/bin/open {command_file}"
    ).format(
        port=DEFAULT_PORT,
        command_file=shlex.quote(str(command_file)),
    )
    return {
        "Label": OPENER_LABEL,
        "ProgramArguments": [
            "/bin/zsh",
            "-lc",
            check_and_open,
        ],
        "RunAtLoad": True,
        "StartInterval": 60,
        "StandardOutPath": str(LOG_DIR / f"{OPENER_LABEL}.out"),
        "StandardErrorPath": str(LOG_DIR / f"{OPENER_LABEL}.err"),
    }


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


def open_console(port: int) -> dict[str, Any]:
    proc = subprocess.run(["open", console_url(port)], capture_output=True, text=True, check=False, timeout=10)
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "url": console_url(port),
        "stdout_tail": (proc.stdout or "")[-500:],
        "stderr_tail": (proc.stderr or "")[-500:],
    }


def install(port: int, dry_run: bool) -> dict[str, Any]:
    path = plist_path()
    payload = plist_payload(port)
    result: dict[str, Any] = {
        "action": "install",
        "dry_run": dry_run,
        "label": LABEL,
        "path": str(path),
        "url": console_url(port),
    }
    if dry_run:
        result["plist"] = payload
        return result
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    launchctl(["launchctl", "bootout", user_domain(), str(path)])
    result["bootstrap"] = launchctl(["launchctl", "bootstrap", user_domain(), str(path)])
    result["enable"] = launchctl(["launchctl", "enable", f"{user_domain()}/{LABEL}"])
    result["kickstart"] = launchctl(["launchctl", "kickstart", "-k", f"{user_domain()}/{LABEL}"])
    return result


def install_opener_fallback(dry_run: bool) -> dict[str, Any]:
    path = opener_plist_path()
    payload = opener_plist_payload()
    result: dict[str, Any] = {
        "action": "install_opener_fallback",
        "dry_run": dry_run,
        "label": OPENER_LABEL,
        "path": str(path),
        "url": console_url(DEFAULT_PORT),
        "note": "Watchdog: opens Stock Ultimus Console.command when localhost console is down and background launchd is blocked by macOS privacy/TCC.",
    }
    if dry_run:
        result["plist"] = payload
        return result
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    launchctl(["launchctl", "bootout", user_domain(), str(path)])
    result["bootstrap"] = launchctl(["launchctl", "bootstrap", user_domain(), str(path)])
    result["enable"] = launchctl(["launchctl", "enable", f"{user_domain()}/{OPENER_LABEL}"])
    result["kickstart"] = launchctl(["launchctl", "kickstart", "-k", f"{user_domain()}/{OPENER_LABEL}"])
    return result


def uninstall(dry_run: bool) -> dict[str, Any]:
    path = plist_path()
    result: dict[str, Any] = {
        "action": "uninstall",
        "dry_run": dry_run,
        "label": LABEL,
        "path": str(path),
    }
    if dry_run:
        return result
    result["bootout"] = launchctl(["launchctl", "bootout", user_domain(), str(path)])
    result["opener_bootout"] = launchctl(["launchctl", "bootout", user_domain(), str(opener_plist_path())])
    try:
        path.unlink()
        result["removed"] = True
    except FileNotFoundError:
        result["removed"] = False
    try:
        opener_plist_path().unlink()
        result["opener_removed"] = True
    except FileNotFoundError:
        result["opener_removed"] = False
    return result


def status(port: int) -> dict[str, Any]:
    path = plist_path()
    return {
        "action": "status",
        "dry_run": False,
        "label": LABEL,
        "path": str(path),
        "opener_label": OPENER_LABEL,
        "opener_path": str(opener_plist_path()),
        "installed": path.exists(),
        "opener_installed": opener_plist_path().exists(),
        "url": console_url(port),
        "print": launchctl(["launchctl", "print", f"{user_domain()}/{LABEL}"]),
        "opener_print": launchctl(["launchctl", "print", f"{user_domain()}/{OPENER_LABEL}"]),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.install:
        result = install(args.port, args.dry_run)
    elif args.install_opener_fallback:
        result = install_opener_fallback(args.dry_run)
    elif args.uninstall:
        result = uninstall(args.dry_run)
    else:
        result = status(args.port)
    if args.open and not args.dry_run:
        result["open"] = open_console(args.port)
    result.update(
        {
            "engine": "STOCK_ULTIMUS_LOCAL_CONSOLE_LAUNCHD_INSTALLER",
            "secrets_printed": False,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
