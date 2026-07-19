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
import shutil
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
APPLICATION_SUPPORT = Path.home() / "Library" / "Application Support" / "Stock Ultimus"
SERVICE_ROOT = APPLICATION_SUPPORT / "ConsoleService"
SERVICE_RUNTIME = APPLICATION_SUPPORT / "Runtime"
RUNTIME_MIGRATION_BACKUPS = APPLICATION_SUPPORT / "MigrationBackups"
LOG_DIR = Path("/private/tmp")
PYTHON = os.getenv("STOCK_ULTIMUS_CONSOLE_PYTHON", "/usr/bin/python3")
LABEL = "com.stockultimus.local-console"
OPENER_LABEL = "com.stockultimus.local-console-opener"
DEFAULT_PORT = 8765
SERVICE_COPY_DIRS = ("scripts", "config", "brokers", "docs")


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


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def prepare_service_bundle(dry_run: bool = False) -> dict[str, Any]:
    """Install code outside Documents and share one canonical runtime directory.

    macOS may deny a background LaunchAgent access to Documents even when the
    same Python command works from Terminal.  The service copy avoids that TCC
    boundary.  The workspace runtime becomes a symlink so manual tools and the
    background console continue reading and writing the exact same data.
    """

    project_runtime = ROOT / "runtime"
    result: dict[str, Any] = {
        "service_root": str(SERVICE_ROOT),
        "service_runtime": str(SERVICE_RUNTIME),
        "project_runtime": str(project_runtime),
        "runtime_shared": project_runtime.is_symlink() and project_runtime.resolve() == SERVICE_RUNTIME.resolve(),
    }
    if dry_run:
        result["planned"] = True
        return result

    APPLICATION_SUPPORT.mkdir(parents=True, exist_ok=True)
    SERVICE_ROOT.mkdir(parents=True, exist_ok=True)
    for source in ROOT.glob("*.py"):
        shutil.copy2(source, SERVICE_ROOT / source.name)
    for directory in SERVICE_COPY_DIRS:
        _copy_tree(ROOT / directory, SERVICE_ROOT / directory)

    if project_runtime.is_symlink():
        if project_runtime.resolve() != SERVICE_RUNTIME.resolve():
            raise RuntimeError(f"runtime symlink points to an unexpected location: {project_runtime.resolve()}")
        SERVICE_RUNTIME.mkdir(parents=True, exist_ok=True)
    elif project_runtime.exists():
        if SERVICE_RUNTIME.exists():
            _copy_tree(project_runtime, SERVICE_RUNTIME)
            RUNTIME_MIGRATION_BACKUPS.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = RUNTIME_MIGRATION_BACKUPS / f"runtime-{stamp}"
            shutil.move(str(project_runtime), str(backup))
            result["runtime_backup"] = str(backup)
        else:
            shutil.move(str(project_runtime), str(SERVICE_RUNTIME))
        project_runtime.symlink_to(SERVICE_RUNTIME, target_is_directory=True)
    else:
        SERVICE_RUNTIME.mkdir(parents=True, exist_ok=True)
        project_runtime.symlink_to(SERVICE_RUNTIME, target_is_directory=True)

    service_runtime_link = SERVICE_ROOT / "runtime"
    if service_runtime_link.is_symlink() and service_runtime_link.resolve() != SERVICE_RUNTIME.resolve():
        service_runtime_link.unlink()
    elif service_runtime_link.exists() and not service_runtime_link.is_symlink():
        raise RuntimeError(f"service runtime path is not a symlink: {service_runtime_link}")
    if not service_runtime_link.exists():
        service_runtime_link.symlink_to(SERVICE_RUNTIME, target_is_directory=True)

    result.update(
        {
            "planned": False,
            "runtime_shared": project_runtime.is_symlink() and project_runtime.resolve() == SERVICE_RUNTIME.resolve(),
            "copied_root_python_files": len(list(ROOT.glob("*.py"))),
        }
    )
    return result


def plist_payload(port: int) -> dict[str, Any]:
    command = "cd {root} && exec {python} {script} serve --host 127.0.0.1 --port {port}".format(
        root=shlex.quote(str(SERVICE_ROOT)),
        python=shlex.quote(PYTHON),
        script=shlex.quote(str(SERVICE_ROOT / "scripts" / "ibkr_account_profile.py")),
        port=int(port),
    )
    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/bin/zsh",
            "-lc",
            command,
        ],
        "WorkingDirectory": str(SERVICE_ROOT),
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
        "|| ( /usr/bin/launchctl kickstart -k {domain}/{label} >/dev/null 2>&1; "
        "for attempt in 1 2 3 4 5 6 7 8 9 10; do "
        "/usr/sbin/lsof -nP -iTCP:{port} -sTCP:LISTEN >/dev/null && exit 0; "
        "/bin/sleep 1; done; /usr/bin/open {command_file} )"
    ).format(
        port=DEFAULT_PORT,
        domain=user_domain(),
        label=LABEL,
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
        result["service_bundle"] = prepare_service_bundle(dry_run=True)
        return result
    result["service_bundle"] = prepare_service_bundle()
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
    listener = launchctl(
        ["/usr/sbin/lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN"]
    )
    health = {"ok": listener["ok"], "port_listening": listener["ok"]}
    return {
        "action": "status",
        "dry_run": False,
        "label": LABEL,
        "path": str(path),
        "opener_label": OPENER_LABEL,
        "opener_path": str(opener_plist_path()),
        "installed": path.exists(),
        "opener_installed": opener_plist_path().exists(),
        "service_bundle_installed": (SERVICE_ROOT / "scripts" / "ibkr_account_profile.py").exists(),
        "runtime_shared": (ROOT / "runtime").is_symlink()
        and (ROOT / "runtime").resolve() == SERVICE_RUNTIME.resolve(),
        "health": health,
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
    if args.install and not args.dry_run:
        result["ok"] = bool(
            result.get("service_bundle", {}).get("runtime_shared")
            and result.get("bootstrap", {}).get("ok")
            and result.get("enable", {}).get("ok")
            and result.get("kickstart", {}).get("ok")
        )
    elif args.install_opener_fallback and not args.dry_run:
        result["ok"] = bool(
            result.get("bootstrap", {}).get("ok")
            and result.get("enable", {}).get("ok")
            and result.get("kickstart", {}).get("ok")
        )
    elif not (args.install or args.install_opener_fallback or args.uninstall):
        result["ok"] = bool(result.get("print", {}).get("ok") and result.get("health", {}).get("ok"))
    result.update(
        {
            "engine": "STOCK_ULTIMUS_LOCAL_CONSOLE_LAUNCHD_INSTALLER",
            "secrets_printed": False,
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
