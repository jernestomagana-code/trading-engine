#!/usr/bin/env python3
"""Manage local IBKR account profiles without printing account identifiers.

Real IBKR account identifiers are stored in macOS Keychain. Runtime payloads
only receive logical aliases/scopes such as "primary" or "income".
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
PROFILES_PATH = RUNTIME / "ibkr_account_profiles.local.json"
ACTIVE_PATH = RUNTIME / "ibkr_account_active_profile.json"
WEB_LAST_RESULT_PATH = RUNTIME / "ibkr_account_profile_web_last_result.json"
REMOTE_CACHE_PATH = RUNTIME / "stock_ultimus_console_remote_cache.json"
KEYCHAIN_SERVICE_PREFIX = "stock-ultimus-ibkr-account-"
READ_KEYCHAIN_SERVICES = ("stock-ultimus-read-access-token", "stock-ultimus-read-access")
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"
FAST_KEYCHAIN_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_KEYCHAIN_TIMEOUT_SECONDS", "2"))
REMOTE_READ_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_REMOTE_TIMEOUT_SECONDS", "2"))
REMOTE_CACHE_MAX_AGE_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_REMOTE_CACHE_MAX_AGE_SECONDS", "900"))
LOCAL_JOB_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_JOB_TIMEOUT_SECONDS", "90"))
CONSOLE_BRIDGE_TIMEOUT_SECONDS = int(float(os.getenv("STOCK_ULTIMUS_CONSOLE_BRIDGE_TIMEOUT_SECONDS", "75")))
CONSOLE_HISTORICAL_TIMEOUT_SECONDS = int(float(os.getenv("STOCK_ULTIMUS_CONSOLE_HISTORICAL_TIMEOUT_SECONDS", "4")))
CONSOLE_IBKR_CLIENT_ID = int(float(os.getenv("STOCK_ULTIMUS_CONSOLE_IBKR_CLIENT_ID", "73")))
CONSOLE_OPTION_SYMBOLS = os.getenv("STOCK_ULTIMUS_CONSOLE_OPTION_SYMBOLS", "QQQ,SPY,AAPL,NVDA,TSLA")
CONSOLE_MAX_OPTIONS_PER_SYMBOL = os.getenv("STOCK_ULTIMUS_CONSOLE_MAX_OPTIONS_PER_SYMBOL", "1")
CONSOLE_OPTION_MARKET_DATA_TYPES = os.getenv("STOCK_ULTIMUS_CONSOLE_OPTION_MARKET_DATA_TYPES", "1,2")
CONSOLE_OPTION_WAIT_SECONDS = os.getenv("STOCK_ULTIMUS_CONSOLE_OPTION_WAIT_SECONDS", "1")
CONSOLE_OPTION_SNAPSHOT_WAIT_SECONDS = os.getenv("STOCK_ULTIMUS_CONSOLE_OPTION_SNAPSHOT_WAIT_SECONDS", "1")
WEB_JOBS: dict[str, dict[str, Any]] = {}
WEB_JOBS_LOCK = threading.Lock()
UNKNOWN_CONTEXT_VALUES = {"", "UNKNOWN", "NONE", "NULL", "N/A"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_alias(value: str) -> str:
    alias = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in ["-", "_"])
    if not alias:
        raise SystemExit("Alias requerido. Ejemplo: primary, income, speculative.")
    return alias


def keychain_service(alias: str) -> str:
    return KEYCHAIN_SERVICE_PREFIX + normalize_alias(alias)


def keychain_account() -> str:
    return os.getenv("USER") or "stock-ultimus"


def save_keychain_value(service: str, value: str) -> None:
    if not value.strip():
        raise SystemExit("Account vacio; no se guardo nada.")
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-a",
            keychain_account(),
            "-s",
            service,
            "-w",
            value.strip(),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise SystemExit("No pude guardar el account en Keychain.")


def read_keychain_value(service: str, timeout: float = FAST_KEYCHAIN_TIMEOUT_SECONDS) -> str:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            keychain_account(),
            "-s",
            service,
            "-w",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_keychain_value_any_account(service: str, timeout: float = FAST_KEYCHAIN_TIMEOUT_SECONDS) -> str:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            service,
            "-w",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def load_profiles() -> dict[str, Any]:
    try:
        data = json.loads(PROFILES_PATH.read_text())
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        data["profiles"] = {}
    data.setdefault("profile_version", "ibkr_account_profiles_v1")
    data.setdefault("real_account_ids_stored_in_keychain", True)
    data.setdefault("secrets_printed", False)
    return data


def write_profiles(data: dict[str, Any]) -> None:
    RUNTIME.mkdir(exist_ok=True)
    PROFILES_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def profile_for(alias: str) -> dict[str, Any]:
    alias = normalize_alias(alias)
    data = load_profiles()
    profile = data.get("profiles", {}).get(alias)
    if not isinstance(profile, dict):
        raise SystemExit(f"Perfil '{alias}' no existe. Usa: setup {alias} --account ...")
    return profile


def active_profile() -> dict[str, Any]:
    try:
        data = json.loads(ACTIVE_PATH.read_text())
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def write_active_profile(profile: dict[str, Any]) -> None:
    RUNTIME.mkdir(exist_ok=True)
    active = {
        "active_profile_version": "ibkr_active_account_profile_v1",
        "selected_at": now_iso(),
        "account_scope": profile["account_scope"],
        "account_alias": profile["alias"],
        "selected_account_configured": True,
        "real_account_id_printed": False,
        "real_account_id_stored_in_keychain": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    ACTIVE_PATH.write_text(json.dumps(active, indent=2, sort_keys=True) + "\n")


def cmd_setup(args: argparse.Namespace) -> int:
    alias = normalize_alias(args.alias)
    scope = normalize_alias(args.scope or alias)
    service = keychain_service(alias)
    save_keychain_value(service, args.account)

    data = load_profiles()
    data["profiles"][alias] = {
        "alias": alias,
        "account_scope": scope,
        "keychain_service": service,
        "created_or_updated_at": now_iso(),
        "real_account_id_printed": False,
    }
    write_profiles(data)
    print(f"Perfil IBKR guardado: alias={alias} scope={scope} account_id_printed=false")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    data = load_profiles()
    profiles = data.get("profiles", {})
    if not profiles:
        print("No hay perfiles IBKR guardados.")
        return 0
    for alias in sorted(profiles):
        profile = profiles[alias]
        service = str(profile.get("keychain_service") or keychain_service(alias))
        print(
            "alias={alias} scope={scope} account_in_keychain={present}".format(
                alias=alias,
                scope=profile.get("account_scope") or alias,
                present=bool(read_keychain_value(service)),
            )
        )
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    profile = profile_for(args.alias)
    if not read_keychain_value(str(profile.get("keychain_service") or "")):
        raise SystemExit(f"Perfil '{args.alias}' existe, pero falta su account en Keychain.")
    write_active_profile(profile)
    print(f"Perfil activo: alias={profile['alias']} scope={profile['account_scope']} account_id_printed=false")
    return 0


def environment_for(profile: dict[str, Any]) -> dict[str, str]:
    service = str(profile.get("keychain_service") or "")
    account = read_keychain_value(service, timeout=10)
    if not account:
        raise SystemExit(f"Falta account en Keychain para alias '{profile.get('alias')}'.")
    env = os.environ.copy()
    env["STOCK_ULTIMUS_ACCOUNT_SCOPE"] = str(profile["account_scope"])
    env["IBKR_ACCOUNT_ALIAS"] = str(profile["alias"])
    env["IBKR_ACCOUNT_ID"] = account
    return env


def command_label(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def sanitize_output(text: str, env: dict[str, str] | None = None) -> str:
    clean = str(text or "")
    account = (env or {}).get("IBKR_ACCOUNT_ID") or ""
    if account:
        clean = clean.replace(account, "[REDACTED_IBKR_ACCOUNT]")
    return clean[-6000:]


def process_output_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def enrich_console_bridge_output(text: str) -> str:
    bridge_report = RUNTIME / "stock_ultimus_console_bridge_latest.json"
    if not bridge_report.exists():
        return text
    try:
        data = json.loads(bridge_report.read_text())
    except Exception:
        return text
    runs = data.get("runs") if isinstance(data.get("runs"), list) else []
    last = runs[-1] if runs and isinstance(runs[-1], dict) else {}
    if not last:
        return text
    details = [
        "\n--- bridge session detail ---",
        "status: {}".format(last.get("status") or "UNKNOWN"),
        "published: {}".format(last.get("published")),
        "timeout_seconds: {}".format(last.get("timeout_seconds") or data.get("bridge_timeout")),
    ]
    if last.get("tail"):
        details.extend(["tail:", str(last.get("tail"))])
    return (text + "\n" + "\n".join(details)).strip()


def run_with_profile(alias: str, command: list[str]) -> int:
    profile = profile_for(alias)
    write_active_profile(profile)
    env = environment_for(profile)
    print(
        "Ejecutando con perfil IBKR: alias={alias} scope={scope} account_id_printed=false".format(
            alias=profile["alias"],
            scope=profile["account_scope"],
        )
    )
    result = subprocess.run(command, cwd=str(ROOT), env=env, check=False)
    return int(result.returncode)


def run_with_profile_capture(alias: str, command: list[str]) -> dict[str, Any]:
    profile = profile_for(alias)
    write_active_profile(profile)
    env = environment_for(profile)
    if any(str(part).endswith("run_market_bridge_session.py") for part in command):
        env.setdefault("IBKR_OPTION_SYMBOLS", CONSOLE_OPTION_SYMBOLS)
        env.setdefault("IBKR_MAX_OPTIONS_PER_SYMBOL", CONSOLE_MAX_OPTIONS_PER_SYMBOL)
        env.setdefault("IBKR_OPTION_MARKET_DATA_TYPE_SEQUENCE", CONSOLE_OPTION_MARKET_DATA_TYPES)
        env.setdefault("IBKR_OPTION_MARKET_DATA_WAIT_SECONDS", CONSOLE_OPTION_WAIT_SECONDS)
        env.setdefault("IBKR_OPTION_SNAPSHOT_WAIT_SECONDS", CONSOLE_OPTION_SNAPSHOT_WAIT_SECONDS)
    timed_out = False
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=LOCAL_JOB_TIMEOUT_SECONDS,
        )
        returncode = int(result.returncode)
        stdout = enrich_console_bridge_output(result.stdout)
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = process_output_text(exc.stdout)
        stderr = process_output_text(exc.stderr) + f"\nTIMEOUT: comando detenido despues de {LOCAL_JOB_TIMEOUT_SECONDS:.0f}s. Revisa TWS/IBKR Gateway y vuelve a intentar."
    payload = {
        "result_version": "ibkr_account_profile_web_result_v1",
        "generated_at": now_iso(),
        "alias": profile["alias"],
        "account_scope": profile["account_scope"],
        "command": command_label(command),
        "returncode": returncode,
        "timed_out": timed_out,
        "timeout_seconds": LOCAL_JOB_TIMEOUT_SECONDS,
        "stdout_tail": sanitize_output(stdout, env),
        "stderr_tail": sanitize_output(stderr, env),
        "account_id_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    RUNTIME.mkdir(exist_ok=True)
    WEB_LAST_RESULT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def start_web_job(alias: str, command: list[str], label: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "job_version": "stock_ultimus_console_job_v1",
        "status": "RUNNING",
        "label": label,
        "alias": normalize_alias(alias),
        "command": command_label(command),
        "started_at": now_iso(),
        "finished_at": None,
        "result": None,
        "error": "",
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    with WEB_JOBS_LOCK:
        WEB_JOBS[job_id] = job

    def worker() -> None:
        try:
            result = run_with_profile_capture(alias, command)
            with WEB_JOBS_LOCK:
                WEB_JOBS[job_id] = {
                    **WEB_JOBS.get(job_id, job),
                    "status": "DONE" if int(result.get("returncode") or 0) == 0 else "ERROR",
                    "finished_at": now_iso(),
                    "result": result,
                    "error": "",
                }
        except Exception as exc:
            with WEB_JOBS_LOCK:
                WEB_JOBS[job_id] = {
                    **WEB_JOBS.get(job_id, job),
                    "status": "ERROR",
                    "finished_at": now_iso(),
                    "result": None,
                    "error": str(exc),
                }

    threading.Thread(target=worker, name=f"stock-ultimus-console-{job_id}", daemon=True).start()
    return job_id


def web_job(job_id: str) -> dict[str, Any]:
    with WEB_JOBS_LOCK:
        job = WEB_JOBS.get(str(job_id or ""))
        return dict(job) if isinstance(job, dict) else {}


def cmd_run(args: argparse.Namespace) -> int:
    if not args.command:
        raise SystemExit("Falta comando despues de --. Ejemplo: run primary -- python3 ibkr_bridge.py --once")
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    return run_with_profile(args.alias, command)


def console_bridge_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_market_bridge_session.py",
        "--max-runs",
        "1",
        "--bridge-timeout",
        str(max(30, min(CONSOLE_BRIDGE_TIMEOUT_SECONDS, int(LOCAL_JOB_TIMEOUT_SECONDS) - 10))),
        "--historical-data-timeout",
        str(CONSOLE_HISTORICAL_TIMEOUT_SECONDS),
        "--ibkr-client-id",
        str(CONSOLE_IBKR_CLIENT_ID),
        "--json-out",
        str(RUNTIME / "stock_ultimus_console_bridge_latest.json"),
    ]


def cmd_bridge(args: argparse.Namespace) -> int:
    return run_with_profile(args.alias, console_bridge_command())


def cmd_daily_open(args: argparse.Namespace) -> int:
    return run_with_profile(args.alias, [sys.executable, "scripts/daily_open_checklist.py", "--refresh"])


def html_escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def web_status_class(profile: dict[str, Any], active: dict[str, Any]) -> str:
    if profile.get("alias") == active.get("account_alias"):
        return "active"
    return ""


def web_last_result() -> dict[str, Any]:
    try:
        data = json.loads(WEB_LAST_RESULT_PATH.read_text())
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def read_access_token() -> str:
    token = (
        os.getenv("READ_ACCESS_TOKEN")
        or os.getenv("STOCK_ULTIMUS_READ_TOKEN")
        or os.getenv("STOCK_ULTIMUS_READ_ACCESS_TOKEN")
        or ""
    ).strip()
    if token:
        return token
    for service in READ_KEYCHAIN_SERVICES:
        token = read_keychain_value(service) or read_keychain_value_any_account(service)
        if token:
            return token
    return ""


def public_base_url() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or DEFAULT_PUBLIC_BASE_URL).rstrip("/")


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    RUNTIME.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def latest_master_snapshot() -> dict[str, Any]:
    candidates = []
    fixed_names = [
        "v31_master_snapshot.json",
        "v28_master_snapshot.json",
        "v26_master_snapshot.json",
        "v26_local_master_snapshot.json",
        "v25_master_snapshot.json",
    ]
    for name in fixed_names:
        path = RUNTIME / name
        if path.exists():
            candidates.append(path)
    if RUNTIME.exists():
        candidates.extend(path for path in RUNTIME.glob("*master_snapshot*.json") if path.is_file())
    unique = sorted({path.resolve(): path for path in candidates}.values(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not unique:
        return {
            "available": False,
            "path": "",
            "data": {},
            "account_scope": "",
            "account_alias": "",
            "generated_at": "",
            "rows_found": 0,
        }
    path = unique[0]
    data = load_json_file(path)
    rows = data.get("options_rows") if isinstance(data.get("options_rows"), list) else []
    broker_summary = data.get("broker_check_summary") if isinstance(data.get("broker_check_summary"), dict) else {}
    account_context = data.get("account_context") if isinstance(data.get("account_context"), dict) else {}
    scope = data.get("account_scope") or broker_summary.get("account_scope") or account_context.get("account_scope") or ""
    alias = data.get("account_alias") or broker_summary.get("account_alias") or account_context.get("account_alias") or scope
    return {
        "available": True,
        "path": str(path.relative_to(ROOT)),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "data": data,
        "account_scope": scope,
        "account_alias": alias,
        "generated_at": data.get("generated_at") or data.get("timestamp") or "",
        "rows_found": len(rows),
        "broker_summary": broker_summary,
        "real_account_id_excluded": True,
    }


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def age_label(value: Any) -> str:
    dt = parse_iso_datetime(value)
    if not dt:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if seconds < 90:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def cache_age_seconds(cached_at: Any) -> float | None:
    dt = parse_iso_datetime(cached_at)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def write_remote_cache(path: str, result: dict[str, Any]) -> None:
    if not result.get("ok"):
        return
    payload = {
        "cache_version": "stock_ultimus_console_remote_cache_v1",
        "cached_at": now_iso(),
        "path": path,
        "result": {
            "ok": True,
            "error": "",
            "token_present": bool(result.get("token_present")),
            "url": result.get("url"),
            "data": result.get("data") if isinstance(result.get("data"), dict) else {},
        },
        "secrets_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    write_json_file(REMOTE_CACHE_PATH, payload)


def read_remote_cache(path: str, live_error: str = "") -> dict[str, Any] | None:
    cache = load_json_file(REMOTE_CACHE_PATH)
    if cache.get("path") != path:
        return None
    age_seconds = cache_age_seconds(cache.get("cached_at"))
    if age_seconds is None or age_seconds > REMOTE_CACHE_MAX_AGE_SECONDS:
        return None
    result = cache.get("result") if isinstance(cache.get("result"), dict) else {}
    if not result.get("ok"):
        return None
    out = dict(result)
    out["cached"] = True
    out["cached_at"] = cache.get("cached_at")
    out["cache_age_label"] = age_label(cache.get("cached_at"))
    out["live_error"] = live_error
    return out


def fetch_remote_json(path: str, timeout: float = REMOTE_READ_TIMEOUT_SECONDS, prefer_cache: bool = False) -> dict[str, Any]:
    if prefer_cache:
        cached = read_remote_cache(path, live_error="LIVE_REFRESH_SKIPPED_DURING_LOCAL_JOB")
        if cached:
            return cached
    token = read_access_token()
    if not token:
        cached = read_remote_cache(path, live_error="MISSING_READ_ACCESS_TOKEN")
        return cached or {"ok": False, "error": "MISSING_READ_ACCESS_TOKEN", "token_present": False, "data": {}}
    url = public_base_url() + path
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Stock-Ultimus-Read-Token": token,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        result = {"ok": True, "error": "", "token_present": True, "url": url, "data": data if isinstance(data, dict) else {}}
        write_remote_cache(path, result)
        return result
    except urllib.error.HTTPError as exc:
        error_text = f"HTTP_{exc.code}"
        cached = read_remote_cache(path, live_error=error_text)
        return cached or {"ok": False, "error": error_text, "token_present": True, "url": url, "data": {}}
    except Exception as exc:
        error_text = str(exc)
        cached = read_remote_cache(path, live_error=error_text)
        return cached or {"ok": False, "error": error_text, "token_present": True, "url": url, "data": {}}


def post_remote_json(path: str, payload: dict[str, Any], timeout: float = 15) -> dict[str, Any]:
    token = read_access_token()
    if not token:
        return {"ok": False, "error": "MISSING_READ_ACCESS_TOKEN", "token_present": False, "data": {}}
    url = public_base_url() + path
    body = json.dumps(payload, default=str).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Stock-Ultimus-Read-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return {"ok": True, "error": "", "token_present": True, "url": url, "data": data if isinstance(data, dict) else {}}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP_{exc.code}", "token_present": True, "url": url, "text": text[:1000], "data": {}}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "token_present": True, "url": url, "data": {}}


def console_operator_payload(prefer_cache: bool = False) -> dict[str, Any]:
    return fetch_remote_json("/gpt_v32_operator_today?limit=12", prefer_cache=prefer_cache)


def published_context_value(value: Any) -> str:
    text = str(value or "").strip()
    if text.upper() in UNKNOWN_CONTEXT_VALUES:
        return ""
    return text


def selected_vs_published(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any]) -> dict[str, Any]:
    operator_data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    operator_context = operator_data.get("account_context") if isinstance(operator_data.get("account_context"), dict) else {}
    remote_ok = bool(operator_payload.get("ok"))
    selected_scope = active.get("account_scope") or ""
    selected_alias = active.get("account_alias") or ""
    published_scope = published_context_value(
        operator_data.get("account_scope")
        or operator_context.get("account_scope")
        or snapshot.get("account_scope")
        or ""
    )
    published_alias = published_context_value(
        operator_data.get("account_alias")
        or operator_context.get("account_alias")
        or snapshot.get("account_alias")
        or ""
    )
    matches = bool(selected_scope and published_scope and selected_scope == published_scope)
    missing_published_context = bool(remote_ok and selected_scope and not published_scope)
    return {
        "selected_scope": selected_scope,
        "selected_alias": selected_alias,
        "published_scope": published_scope,
        "published_alias": published_alias,
        "missing_published_context": missing_published_context,
        "remote_ok": remote_ok,
        "remote_error": operator_payload.get("error") or "",
        "cached": bool(operator_payload.get("cached")),
        "cache_age_label": operator_payload.get("cache_age_label") or "",
        "live_error": operator_payload.get("live_error") or "",
        "matches": matches,
        "needs_refresh": bool(missing_published_context or (remote_ok and selected_scope and published_scope and not matches)),
        "status": "MATCH" if matches else ("REMOTE_UNAVAILABLE" if not remote_ok else "REFRESH_REQUIRED"),
    }


def render_metric(title: str, value: Any, note: str = "") -> str:
    return """
    <article class="metric">
      <span>{title}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
    """.format(title=html_escape(title), value=html_escape(value), note=html_escape(note))


def render_console_context(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any]) -> str:
    comparison = selected_vs_published(active, snapshot, operator_payload)
    operator_data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    status = operator_data.get("status") or ("OK" if operator_payload.get("ok") else operator_payload.get("error") or "UNKNOWN")
    warning = ""
    if not comparison["remote_ok"]:
        warning = """
        <div class="warning">No pude verificar que cuenta ve GPT porque el endpoint remoto no respondio a tiempo. Recargar esta consola solo relee la pagina local; no publica cuenta. Para cambiar lo que ve GPT, el refresh IBKR debe terminar en DONE y publicar snapshot.</div>
        """
    elif comparison["needs_refresh"]:
        warning = """
        <div class="warning">GPT todavia no tiene publicada la cuenta seleccionada. Usa <strong>Usar + Refresh IBKR</strong> y espera DONE antes de pedir interpretacion de broker/account context.</div>
        """
    elif not comparison["published_scope"]:
        warning = """
        <div class="warning">No hay contexto publicado para GPT. Selecciona una cuenta y refresca el bridge.</div>
        """
    remote_status = "cached" if operator_payload.get("cached") else ("ok" if operator_payload.get("ok") else "timeout" if "timed out" in str(operator_payload.get("error") or "").lower() else "blocked")
    published_value = comparison["published_alias"] or ("unavailable" if not comparison["remote_ok"] else "pendiente")
    if comparison["missing_published_context"]:
        published_note = "sin cuenta publicada; GPT remoto aun no ve " + (comparison["selected_scope"] or "la seleccion local")
    elif comparison["cached"]:
        published_note = "cache=" + comparison["cache_age_label"] + (" | live_error=" + comparison["live_error"] if comparison["live_error"] else "")
    elif not comparison["remote_ok"]:
        published_note = "error=" + comparison["remote_error"]
    else:
        published_note = "scope=" + (comparison["published_scope"] or "pendiente")
    return """
    <section class="panel hero-panel">
      <div>
        <p class="eyebrow">Contexto activo</p>
        <h1>Stock Ultimus Console</h1>
        <p class="lede">Un solo cockpit para escoger cuenta, refrescar IBKR, revisar alertas y verificar que GPT este usando el contexto correcto.</p>
      </div>
      <div class="context-grid">
        {selected}
        {published}
        {snapshot}
        {operator}
      </div>
      {warning}
    </section>
    """.format(
        selected=render_metric(
            "Seleccion local",
            comparison["selected_alias"] or "none",
            "scope=" + (comparison["selected_scope"] or "none"),
        ),
        published=render_metric(
            "GPT ve",
            published_value,
            published_note,
        ),
        snapshot=render_metric(
            "Snapshot",
            "available" if snapshot.get("available") else "missing",
            (snapshot.get("path") or "no file") + " | " + age_label(snapshot.get("generated_at") or snapshot.get("mtime")),
        ),
        operator=render_metric(
            "V32 status",
            status,
            "remote=" + remote_status,
        ),
        warning=warning,
    )


def render_console_actions() -> str:
    base = public_base_url()
    return """
    <section class="panel">
      <h2>Perifericos y salidas</h2>
      <div class="tiles">
        <a class="tile" href="{base}/v32_operator_dashboard" target="_blank">V32 dashboard<span>Alertas y acciones guiadas</span></a>
        <a class="tile" href="{base}/gpt_v32_operator_today" target="_blank">GPT payload<span>Contexto exacto que lee el GPT</span></a>
        <a class="tile" href="{base}/v32_operator_daily_summary_email/preview" target="_blank">Email preview<span>Resumen antes de enviar</span></a>
        <a class="tile" href="{base}/v32_operator_tracking_status" target="_blank">Tracking<span>Eventos, outcomes y aprendizaje</span></a>
      </div>
      <p class="muted">Los links protegidos pueden pedir READ_ACCESS_TOKEN en el navegador. La consola local nunca imprime ese token.</p>
    </section>
    """.format(base=html_escape(base))


def render_operator_alerts(operator_payload: dict[str, Any]) -> str:
    if not operator_payload.get("ok"):
        return """
        <section class="panel">
          <h2>Alertas V32</h2>
          <p class="muted">No pude leer el endpoint protegido: {error}. Configura READ_ACCESS_TOKEN o revisa produccion.</p>
        </section>
        """.format(error=html_escape(operator_payload.get("error") or "unknown"))
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    alerts = data.get("active_alerts") if isinstance(data.get("active_alerts"), list) else []
    next_actions = data.get("next_actions") if isinstance(data.get("next_actions"), list) else []
    if not alerts:
        alert_html = '<p class="empty">Sin alertas activas en el payload V32 actual.</p>'
    else:
        alert_html = "".join(
            """
            <article class="alert-card severity-{severity}">
              <strong>{ticker}</strong>
              <span>{severity} | {state}</span>
              <small>blocker: {blocker} | status: {status}</small>
              <form method="post" action="/operator-event" class="alert-actions" data-busy="Registrando evento de operador">
                <input name="alert_id" value="{alert_id}" type="hidden">
                <input name="ticker" value="{ticker}" type="hidden">
                <input name="strategy" value="{strategy}" type="hidden">
                <input name="state" value="{state}" type="hidden">
                <label>Nota/razon opcional</label>
                <input name="reason" placeholder="Ej. revisar tamano, descartar por capital, mantener watch">
                <div class="actions">
                  <button name="action" value="ACK_ALERT">Ack</button>
                  <button name="action" value="MARK_REVIEWING">Review</button>
                  <button name="action" value="MARK_WATCHLIST">Watch</button>
                  <button name="action" value="REJECT_SETUP">Reject</button>
                  <button name="action" value="CLOSE_ALERT">Close</button>
                </div>
              </form>
            </article>
            """.format(
                alert_id=html_escape(alert.get("alert_id") or ""),
                ticker=html_escape(alert.get("ticker") or "UNKNOWN"),
                severity=html_escape(str(alert.get("severity") or "UNKNOWN").lower()),
                state=html_escape(alert.get("state") or "UNKNOWN"),
                strategy=html_escape(alert.get("strategy") or ""),
                blocker=html_escape(alert.get("main_blocker") or "NONE"),
                status=html_escape(alert.get("operator_status") or "UNKNOWN"),
            )
            for alert in alerts[:12]
        )
    action = next_actions[0] if next_actions else {}
    return """
    <section class="panel">
      <div class="section-head">
        <h2>Alertas V32</h2>
        <p>{next_action}</p>
      </div>
      <div class="alert-grid">{alerts}</div>
    </section>
    """.format(
        next_action=html_escape((action.get("label") or "Sin accion inmediata") + ". " + (action.get("detail") or "")),
        alerts=alert_html,
    )


def render_profile_cards(profiles: dict[str, Any], active: dict[str, Any]) -> str:
    profile_cards = []
    for alias in sorted(profiles):
        profile = profiles[alias]
        service = str(profile.get("keychain_service") or keychain_service(alias))
        keychain_ready = bool(read_keychain_value(service))
        status = "Lista" if keychain_ready else "Falta Keychain"
        profile_cards.append(
            """
            <article class="card {active}">
              <div>
                <h3>{alias}</h3>
                <p>scope: <strong>{scope}</strong></p>
                <p class="muted">{status}. ID real oculto.</p>
              </div>
              <div class="actions">
                <form method="post" action="/select" data-busy="Cambiando perfil activo"><input name="alias" value="{alias}" type="hidden"><button>Usar</button></form>
                <form method="post" action="/bridge" data-busy="Refresh IBKR en curso"><input name="alias" value="{alias}" type="hidden"><button>Usar + Refresh IBKR</button></form>
                <form method="post" action="/daily-open" data-busy="Daily open en curso"><input name="alias" value="{alias}" type="hidden"><button>Daily open</button></form>
              </div>
            </article>
            """.format(
                active=web_status_class(profile, active),
                alias=html_escape(alias),
                scope=html_escape(profile.get("account_scope") or alias),
                status=html_escape(status),
            )
        )
    if not profile_cards:
        profile_cards.append('<p class="empty">Todavia no hay perfiles. Crea uno abajo; el ID se guarda en Keychain y no se imprime.</p>')
    return "\n".join(profile_cards)


def render_job_panel(job_id: str = "") -> tuple[str, str]:
    job = web_job(job_id)
    if not job:
        return "", ""
    status = str(job.get("status") or "UNKNOWN")
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    result_html = ""
    if result:
        diagnostic = console_job_diagnostic(result)
        result_html = """
        {diagnostic}
        <p><strong>Resultado:</strong> returncode={returncode}</p>
        <pre>{stdout}{stderr}</pre>
        """.format(
            diagnostic=diagnostic,
            returncode=html_escape(result.get("returncode")),
            stdout=html_escape(result.get("stdout_tail") or ""),
            stderr=html_escape(("\nSTDERR:\n" + result.get("stderr_tail")) if result.get("stderr_tail") else ""),
        )
    elif job.get("error"):
        result_html = "<pre>{}</pre>".format(html_escape(job.get("error")))
    else:
        result_html = "<p class=\"muted\">El proceso esta corriendo en segundo plano. Esta pagina se actualiza sola.</p>"
    refresh_meta = (
        '<meta http-equiv="refresh" content="3;url=/console?job_id={}">'.format(html_escape(job.get("job_id")))
        if status == "RUNNING" else ""
    )
    panel = """
    <section class="panel job-panel status-{status_class}">
      <div class="section-head">
        <h2>Trabajo local</h2>
        <p><strong>{status}</strong> | {label}</p>
      </div>
      <ul class="job-facts">
        <li><span>Alias</span><strong>{alias}</strong></li>
        <li><span>Comando</span><strong>{command}</strong></li>
        <li><span>Inicio</span><strong>{started_at}</strong></li>
        <li><span>Fin</span><strong>{finished_at}</strong></li>
      </ul>
      {result_html}
      <p><a class="tile inline-link" href="/console">Volver a consola <span>No refresca IBKR ni cambia GPT</span></a></p>
    </section>
    """.format(
        status_class=html_escape(status.lower()),
        status=html_escape(status),
        label=html_escape(job.get("label") or ""),
        alias=html_escape(job.get("alias") or ""),
        command=html_escape(job.get("command") or ""),
        started_at=html_escape(job.get("started_at") or ""),
        finished_at=html_escape(job.get("finished_at") or "pendiente"),
        result_html=result_html,
    )
    return refresh_meta, panel


def console_job_diagnostic(result: dict[str, Any]) -> str:
    text = "\n".join([
        str(result.get("stdout_tail") or ""),
        str(result.get("stderr_tail") or ""),
    ])
    if "ERROR conectando IBKR" in text or "account updates" in text and "timed out" in text:
        return """
        <div class="warning">IBKR esta en puerto abierto, pero la API no esta aceptando/respondiendo a la sesion. No sigas presionando Refresh: reinicia TWS/IB Gateway o desconecta sesiones API viejas, espera que quede conectado, y vuelve a intentar.</div>
        """
    if "BRIDGE_TIMEOUT" in text:
        return """
        <div class="warning">El bridge no termino dentro del tiempo limite. Puede estar escaneando opciones lento o esperando respuesta de IBKR. Reintenta despues de estabilizar TWS/IB Gateway.</div>
        """
    if result.get("timed_out"):
        return """
        <div class="warning">La consola detuvo el proceso por timeout local. Revisa TWS/IB Gateway y vuelve a intentar.</div>
        """
    return ""


def render_web_page(message: str = "", result: dict[str, Any] | None = None, job_id: str = "") -> bytes:
    current_job = web_job(job_id)
    prefer_cache = str(current_job.get("status") or "").upper() == "RUNNING"
    data = load_profiles()
    profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    active = active_profile()
    snapshot = latest_master_snapshot()
    operator_payload = console_operator_payload(prefer_cache=prefer_cache)
    result = result or web_last_result()
    refresh_meta, job_panel = render_job_panel(job_id)

    output = ""
    if result:
        output = """
        <section class="panel">
          <h2>Ultima accion</h2>
          <p><strong>{command}</strong> | alias={alias} scope={scope} | returncode={returncode}</p>
          <pre>{stdout}{stderr}</pre>
        </section>
        """.format(
            command=html_escape(result.get("command") or "Sin comando"),
            alias=html_escape(result.get("alias") or ""),
            scope=html_escape(result.get("account_scope") or ""),
            returncode=html_escape(result.get("returncode")),
            stdout=html_escape(result.get("stdout_tail") or ""),
            stderr=html_escape(("\nSTDERR:\n" + result.get("stderr_tail")) if result.get("stderr_tail") else ""),
        )

    body = """
    <!doctype html>
    <html lang="es">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {refresh_meta}
        <title>Stock Ultimus Console</title>
        <style>
          :root {{ --ink:#172019; --muted:#5d675f; --paper:#f7f2e8; --card:#fffaf0; --accent:#1d6b4f; --line:#d9cdb7; --warn:#9f4b1b; --risk:#b42318; }}
          body {{ margin:0; font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif; color:var(--ink); background:radial-gradient(circle at top left,#e2f0dc,transparent 35%),linear-gradient(135deg,#f7f2e8,#eee2cc); }}
          main {{ max-width:1180px; margin:0 auto; padding:28px 18px 60px; }}
          h1 {{ font-size:clamp(2rem,5vw,4.4rem); line-height:.92; margin:0 0 12px; letter-spacing:-.05em; }}
          h2 {{ margin:0 0 12px; }}
          h3 {{ margin:0; }}
          .lede {{ color:var(--muted); max-width:720px; font-size:1.08rem; }}
          .notice,.panel,.card {{ border:1px solid var(--line); background:rgba(255,250,240,.82); border-radius:22px; box-shadow:0 18px 50px rgba(72,52,20,.08); }}
          .notice {{ padding:14px 18px; margin:22px 0; }}
          .hero-panel {{ display:grid; grid-template-columns:1.1fr .9fr; gap:24px; align-items:end; padding:28px; }}
          .eyebrow {{ text-transform:uppercase; letter-spacing:.16em; color:var(--accent); font-weight:800; font-size:.78rem; margin:0 0 12px; }}
          .context-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
          .metric {{ background:#fffdf6; border:1px solid var(--line); border-radius:18px; padding:14px; }}
          .metric span,.metric small {{ display:block; color:var(--muted); }}
          .metric strong {{ display:block; font-size:1.45rem; margin:4px 0; }}
          .warning {{ grid-column:1 / -1; background:#fff3df; color:var(--warn); border:1px solid #efc99d; border-radius:16px; padding:12px 14px; font-weight:700; }}
          .grid {{ display:grid; gap:14px; margin:22px 0; }}
          .card {{ display:flex; justify-content:space-between; gap:18px; padding:20px; align-items:center; }}
          .card.active {{ outline:3px solid rgba(29,107,79,.25); }}
          .card h3 {{ margin:0; font-size:1.5rem; }}
          .card p {{ margin:5px 0; }}
          .muted,.empty {{ color:var(--muted); }}
          .actions {{ display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; }}
          button {{ border:0; border-radius:999px; padding:10px 14px; background:var(--accent); color:white; font-weight:700; cursor:pointer; }}
          button:disabled {{ opacity:.62; cursor:wait; }}
          button.secondary {{ background:#6c5f45; }}
          .panel {{ padding:20px; margin-top:20px; }}
          .job-panel {{ border-color:#b88b2a; background:#fff8e7; }}
          .job-panel.status-done {{ border-color:#1d6b4f; background:#eef8ef; }}
          .job-panel.status-error {{ border-color:var(--risk); background:#fff1ef; }}
          .job-facts {{ list-style:none; padding:0; margin:12px 0; display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:8px; }}
          .job-facts li {{ border:1px solid var(--line); border-radius:14px; padding:10px; background:#fffdf6; }}
          .job-facts span,.job-facts strong {{ display:block; }}
          .job-facts span {{ color:var(--muted); font-size:.9rem; }}
          .job-facts strong {{ overflow-wrap:anywhere; }}
          .section-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:20px; }}
          .section-head p {{ margin:0; color:var(--muted); max-width:620px; }}
          .tiles,.alert-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
          .tile,.alert-card {{ border:1px solid var(--line); background:#fffdf6; border-radius:18px; padding:14px; text-decoration:none; color:var(--ink); }}
          .inline-link {{ display:inline-block; }}
          .tile {{ font-weight:800; }}
          .tile span,.alert-card span,.alert-card small {{ display:block; color:var(--muted); margin-top:6px; font-weight:400; }}
          .alert-card strong {{ font-size:1.35rem; }}
          .alert-actions {{ margin-top:12px; border-top:1px solid var(--line); padding-top:10px; }}
          .alert-actions label {{ font-size:.9rem; margin-top:0; color:var(--muted); }}
          .alert-actions input {{ width:100%; margin-bottom:10px; }}
          .alert-actions .actions {{ justify-content:flex-start; }}
          .alert-actions button {{ padding:8px 11px; font-size:.9rem; }}
          .severity-action {{ border-color:#d97706; }}
          .severity-risk {{ border-color:var(--risk); }}
          .severity-watch {{ border-color:#2563eb; }}
          label {{ display:block; margin:10px 0 4px; font-weight:700; }}
          input {{ width:min(520px,100%); border:1px solid var(--line); border-radius:12px; padding:11px 12px; font:inherit; background:white; box-sizing:border-box; }}
          pre {{ white-space:pre-wrap; overflow:auto; background:#162019; color:#f6f1df; border-radius:14px; padding:14px; max-height:360px; }}
          .busy-overlay[hidden] {{ display:none; }}
          .busy-overlay {{ position:fixed; inset:0; background:rgba(23,32,25,.62); display:grid; place-items:center; z-index:20; padding:20px; }}
          .busy-box {{ width:min(460px,100%); background:#fffaf0; border:1px solid var(--line); border-radius:18px; padding:20px; box-shadow:0 18px 50px rgba(0,0,0,.22); }}
          .busy-box strong,.busy-box span {{ display:block; }}
          .busy-box span {{ color:var(--muted); margin-top:8px; }}
          footer {{ margin-top:26px; color:var(--muted); font-size:.95rem; }}
          @media (max-width:820px) {{ .hero-panel {{ grid-template-columns:1fr; }} .context-grid {{ grid-template-columns:1fr; }} .card {{ align-items:flex-start; flex-direction:column; }} .actions {{ justify-content:flex-start; }} }}
        </style>
      </head>
      <body>
        <div id="busy-overlay" class="busy-overlay" hidden>
          <div class="busy-box">
            <strong>Trabajando...</strong>
            <span>La consola envio la accion. Espera el resultado o el panel de estado.</span>
          </div>
        </div>
        <main>
          {context}
          {message}
          {job_panel}
          <section class="panel">
            <div class="section-head">
              <h2>Cuentas</h2>
              <p>Escoge la cuenta que quieres revisar. Para que GPT cambie de contexto, usa <strong>Usar + Refresh IBKR</strong>.</p>
            </div>
          </section>
          <section class="grid">{profile_cards}</section>
          {alerts}
          {actions}
          <section class="panel">
            <h2>Crear o actualizar perfil</h2>
            <form method="post" action="/setup" autocomplete="off" data-busy="Guardando perfil local">
              <label>Alias amigable</label>
              <input name="alias" placeholder="primary" required>
              <label>Scope publicado</label>
              <input name="scope" placeholder="primary">
              <label>ID real IBKR</label>
              <input name="account" placeholder="Se guarda en Keychain; no se imprime" required>
              <p><button class="secondary">Guardar perfil local</button></p>
            </form>
          </section>
          {output}
          <footer>Decision support solamente. Esta pantalla no autoriza ordenes ni ejecuciones automaticas.</footer>
        </main>
        <script>
          (() => {{
            const overlay = document.getElementById("busy-overlay");
            if (!overlay) return;
            const title = overlay.querySelector("strong");
            const detail = overlay.querySelector("span");
            document.querySelectorAll("form").forEach((form) => {{
              form.addEventListener("submit", () => {{
                const label = form.dataset.busy || "Procesando accion local";
                title.textContent = label;
                detail.textContent = "Solicitud enviada. Si es Refresh IBKR, veras un panel RUNNING/DONE en unos segundos.";
                overlay.hidden = false;
                form.querySelectorAll("button").forEach((button) => {{
                  button.disabled = true;
                  button.textContent = "Trabajando...";
                }});
              }});
            }});
          }})();
        </script>
      </body>
    </html>
    """.format(
        context=render_console_context(active, snapshot, operator_payload),
        message=('<div class="notice">' + html_escape(message) + "</div>") if message else "",
        refresh_meta=refresh_meta,
        job_panel=job_panel,
        profile_cards=render_profile_cards(profiles, active),
        alerts=render_operator_alerts(operator_payload),
        actions=render_console_actions(),
        output=output,
    )
    return body.encode("utf-8")


class AccountProfileWebHandler(BaseHTTPRequestHandler):
    server_version = "StockUltimusIBKRProfile/1.0"

    def send_html(self, message: str = "", result: dict[str, Any] | None = None, status: int = 200, job_id: str = "") -> None:
        payload = render_web_page(message=message, result=result, job_id=job_id)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        if path == "/job-status":
            job_id = (params.get("id") or [""])[0]
            job = web_job(job_id)
            self.send_json(job or {"ok": False, "error": "JOB_NOT_FOUND", "job_id": job_id}, status=200 if job else 404)
            return
        if path not in ["/", "", "/console"]:
            self.send_html("Ruta no encontrada.", status=404)
            return
        self.send_html(job_id=(params.get("job_id") or [""])[0])

    def do_HEAD(self) -> None:
        path = self.path.split("?", 1)[0]
        status = 200 if path in ["/", "", "/console"] else 404
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
            params = parse_qs(self.rfile.read(length).decode("utf-8"))
            alias = (params.get("alias") or [""])[0]
            if self.path == "/setup":
                args = argparse.Namespace(
                    alias=alias,
                    scope=(params.get("scope") or [""])[0],
                    account=(params.get("account") or [""])[0],
                )
                cmd_setup(args)
                self.send_html(f"Perfil guardado: alias={normalize_alias(alias)} account_id_printed=false")
            elif self.path == "/select":
                args = argparse.Namespace(alias=alias)
                cmd_select(args)
                self.send_html(f"Perfil activo: alias={normalize_alias(alias)} account_id_printed=false")
            elif self.path == "/bridge":
                job_id = start_web_job(alias, console_bridge_command(), "Refresh IBKR")
                self.send_html("Refresh IBKR iniciado. La consola mostrara RUNNING hasta que termine.", job_id=job_id)
            elif self.path == "/daily-open":
                job_id = start_web_job(alias, [sys.executable, "scripts/daily_open_checklist.py", "--refresh"], "Daily open checklist")
                self.send_html("Daily open iniciado. La consola mostrara RUNNING hasta que termine.", job_id=job_id)
            elif self.path == "/operator-event":
                action = (params.get("action") or [""])[0]
                reason = (params.get("reason") or [""])[0].strip()
                if action in {"REJECT_SETUP", "APPROVE_MANUAL_REVIEW", "JOURNAL_NOTE"} and not reason:
                    self.send_html("Esta accion requiere nota/razon antes de registrarla.", status=400)
                    return
                payload = {
                    "action": action,
                    "alert_id": (params.get("alert_id") or [""])[0],
                    "ticker": (params.get("ticker") or [""])[0],
                    "strategy": (params.get("strategy") or [""])[0],
                    "state": (params.get("state") or [""])[0],
                    "reason": reason,
                    "actor": "stock_ultimus_console",
                    "source": "local_stock_ultimus_console",
                    "execution_authorized": False,
                    "not_order_instruction": True,
                }
                result = post_remote_json("/gpt_v32_operator_event", payload)
                message = (
                    "Evento registrado para seguimiento/backtesting. No autoriza ordenes."
                    if result.get("ok")
                    else f"No pude registrar evento: {result.get('error') or result.get('text') or 'unknown'}"
                )
                self.send_html(message, result={
                    "command": "POST /gpt_v32_operator_event",
                    "alias": active_profile().get("account_alias") or "",
                    "account_scope": active_profile().get("account_scope") or "",
                    "returncode": 0 if result.get("ok") else 1,
                    "stdout_tail": json.dumps(result.get("data") or result, indent=2, sort_keys=True)[:6000],
                    "stderr_tail": "",
                }, status=200 if result.get("ok") else 400)
            else:
                self.send_html("Ruta no encontrada.", status=404)
        except Exception as exc:
            self.send_html(f"No pude completar la accion: {exc}", status=400)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("ibkr-profile-web: " + (format % args) + "\n")


def cmd_serve(args: argparse.Namespace) -> int:
    host = args.host
    if host not in ["127.0.0.1", "localhost"]:
        raise SystemExit("Por seguridad, el selector web solo escucha en 127.0.0.1/localhost.")
    server = ThreadingHTTPServer((host, int(args.port)), AccountProfileWebHandler)
    print(f"Selector web local: http://{host}:{int(args.port)}")
    print("IDs reales permanecen en Keychain. Decision support only; no autoriza ordenes.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSelector web detenido.")
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Friendly local IBKR account profile selector.")
    sub = parser.add_subparsers(dest="command_name", required=True)

    setup = sub.add_parser("setup", help="Store or update an IBKR account profile in Keychain.")
    setup.add_argument("alias", help="Logical name, e.g. primary, income, speculative.")
    setup.add_argument("--scope", default="", help="Optional published account_scope; defaults to alias.")
    setup.add_argument("--account", required=True, help="Real IBKR account id. Stored in Keychain; never printed.")
    setup.set_defaults(func=cmd_setup)

    list_cmd = sub.add_parser("list", help="List saved aliases without printing account ids.")
    list_cmd.set_defaults(func=cmd_list)

    select = sub.add_parser("select", help="Mark an alias active for operator visibility.")
    select.add_argument("alias")
    select.set_defaults(func=cmd_select)

    run = sub.add_parser("run", help="Run any command under a selected IBKR account profile.")
    run.add_argument("alias")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(func=cmd_run)

    bridge = sub.add_parser("bridge", help="Run ibkr_bridge.py --once under the selected profile.")
    bridge.add_argument("alias")
    bridge.set_defaults(func=cmd_bridge)

    daily_open = sub.add_parser("daily-open", help="Run daily_open_checklist.py --refresh under the selected profile.")
    daily_open.add_argument("alias")
    daily_open.set_defaults(func=cmd_daily_open)

    serve = sub.add_parser("serve", help="Start a localhost-only web selector for saved IBKR account profiles.")
    serve.add_argument("--host", default="127.0.0.1", help="Must be 127.0.0.1 or localhost.")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=cmd_serve)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
