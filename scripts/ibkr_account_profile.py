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
OPERATOR_EVENTS_PATH = RUNTIME / "v32_operator_events.json"
ACCOUNT_CAPACITY_PATH = RUNTIME / "ibkr_account_capacity_latest.json"
TRADINGVIEW_BUNDLE_HEALTH_PATH = RUNTIME / "tradingview_alert_bundle_health.json"
MARKET_OPEN_READINESS_PATH = RUNTIME / "market_open_readiness_latest.json"
POST_OPEN_MONITOR_PATH = RUNTIME / "post_open_monitor_latest.json"
OPERATOR_NOTIFY_PATH = RUNTIME / "v32_operator_notify_latest.json"
OPERATIONAL_EDGE_PATH = RUNTIME / "v32_operational_edge_latest.json"
DAILY_OPEN_CHECKLIST_PATH = RUNTIME / "daily_open_checklist_latest.json"
KEYCHAIN_SERVICE_PREFIX = "stock-ultimus-ibkr-account-"
READ_KEYCHAIN_SERVICES = ("stock-ultimus-read-access-token", "stock-ultimus-read-access")
SNAPSHOT_INGEST_KEYCHAIN_SERVICES = ("stock-ultimus-snapshot-ingest", "stock-ultimus-snapshot-ingest-token")
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"
FAST_KEYCHAIN_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_KEYCHAIN_TIMEOUT_SECONDS", "2"))
REMOTE_READ_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_REMOTE_TIMEOUT_SECONDS", "5"))
REMOTE_VERIFY_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_REMOTE_VERIFY_TIMEOUT_SECONDS", "20"))
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
CLOSED_OPERATOR_STATUSES = {
    "REJECTED",
    "EXPIRED",
    "CLOSED",
    "APPROVED_FOR_MANUAL_REVIEW",
    "APPROVED_FOR_MANUAL_TRADE",
}
HANDLED_OPERATOR_STATUSES = CLOSED_OPERATOR_STATUSES | {
    "ACKNOWLEDGED",
    "REVIEWING",
    "WATCHLIST",
    "NOTE_RECORDED",
}
OPERATOR_STATUS_BY_ACTION = {
    "ACK_ALERT": "ACKNOWLEDGED",
    "MARK_REVIEWING": "REVIEWING",
    "MARK_WATCHLIST": "WATCHLIST",
    "REJECT_SETUP": "REJECTED",
    "APPROVE_MANUAL_REVIEW": "APPROVED_FOR_MANUAL_REVIEW",
    "MARK_EXPIRED": "EXPIRED",
    "CLOSE_ALERT": "CLOSED",
    "JOURNAL_NOTE": "NOTE_RECORDED",
}


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
            returncode = int(result.get("returncode") or 0)
            if returncode == 0:
                verification = fetch_remote_json(
                    "/gpt_v32_operator_today?limit=12",
                    timeout=REMOTE_VERIFY_TIMEOUT_SECONDS,
                    prefer_cache=False,
                )
                verification_data = verification.get("data") if isinstance(verification.get("data"), dict) else {}
                result["remote_verification_ok"] = bool(verification.get("ok"))
                result["remote_verification_status"] = (
                    verification_data.get("status")
                    or verification.get("error")
                    or "UNKNOWN"
                )
                result["remote_verification_account"] = (
                    verification_data.get("account_alias")
                    or verification_data.get("account_scope")
                    or "unknown"
                )
                result["remote_verification_counts"] = operator_alert_counts(verification_data)
                WEB_LAST_RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            elif is_console_bridge_command(command):
                fallback = publish_account_context_fallback()
                result["account_context_fallback"] = fallback
                result["stdout_tail"] = (
                    str(result.get("stdout_tail") or "")
                    + "\n\n--- account context fallback ---\n"
                    + "status: {status}\nok: {ok}\nreturncode: {returncode}\n".format(
                        status=fallback.get("status"),
                        ok=fallback.get("ok"),
                        returncode=fallback.get("returncode"),
                    )
                    + str(fallback.get("stdout_tail") or "")
                )[-6000:]
                if fallback.get("stderr_tail"):
                    result["stderr_tail"] = (
                        str(result.get("stderr_tail") or "")
                        + "\nFALLBACK STDERR:\n"
                        + str(fallback.get("stderr_tail") or "")
                    )[-6000:]
                WEB_LAST_RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            with WEB_JOBS_LOCK:
                WEB_JOBS[job_id] = {
                    **WEB_JOBS.get(job_id, job),
                    "status": "DONE" if returncode == 0 else "ERROR",
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


def account_publish_command() -> list[str]:
    return [
        sys.executable,
        "scripts/ibkr_account_profile.py",
        "publish-context",
    ]


def account_capacity_command() -> list[str]:
    return [
        sys.executable,
        "scripts/ibkr_account_profile.py",
        "refresh-account-capacity",
        "--publish",
    ]


def console_diagnostic_command() -> list[str]:
    return [
        sys.executable,
        "scripts/daily_open_checklist.py",
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


def snapshot_ingest_token() -> str:
    token = (
        os.getenv("TRADING_ENGINE_INGEST_TOKEN")
        or os.getenv("SNAPSHOT_INGEST_TOKEN")
        or os.getenv("STOCK_ULTIMUS_SNAPSHOT_INGEST_TOKEN")
        or ""
    ).strip()
    if token:
        return token
    for service in SNAPSHOT_INGEST_KEYCHAIN_SERVICES:
        token = read_keychain_value(service) or read_keychain_value_any_account(service)
        if token:
            return token
    return ""


def is_console_bridge_command(command: list[str]) -> bool:
    return any(str(part).endswith("run_market_bridge_session.py") for part in command)


def publish_account_context_fallback() -> dict[str, Any]:
    token = snapshot_ingest_token()
    if not token:
        return {
            "ok": False,
            "status": "MISSING_SNAPSHOT_INGEST_TOKEN",
            "detail": "No pude publicar fallback de cuenta porque falta el token de ingest.",
        }
    env = os.environ.copy()
    env["TRADING_ENGINE_INGEST_TOKEN"] = token
    result = subprocess.run(
        [
            sys.executable,
            "tools/publish_v31_snapshot_from_runtime.py",
            "--publish",
            "--allow-stale",
            "--timeout",
            "30",
        ],
        cwd=str(ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=40,
    )
    stdout = sanitize_output(result.stdout, {})
    stderr = sanitize_output(result.stderr, {})
    return {
        "ok": result.returncode == 0,
        "status": "FALLBACK_PUBLISHED" if result.returncode == 0 else "FALLBACK_FAILED",
        "returncode": int(result.returncode),
        "stdout_tail": stdout[-1800:],
        "stderr_tail": stderr[-1000:],
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def cmd_publish_context(_: argparse.Namespace) -> int:
    result = publish_account_context_fallback()
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "ok": result.get("ok"),
                "returncode": result.get("returncode"),
                "not_order_instruction": True,
                "execution_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.get("ok") else 1


def account_summary_capacity(host: str, port: int, client_id: int, timeout: float = 12.0) -> dict[str, Any]:
    try:
        from ib_insync import IB
    except Exception as exc:
        return {
            "ok": False,
            "status": "IB_INSYNC_IMPORT_FAILED",
            "error": str(exc)[:200],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    active = active_profile()
    selected = os.getenv("IBKR_ACCOUNT_ID", "").strip()
    fields = {
        "NetLiquidation": "net_liquidation",
        "BuyingPower": "buying_power",
        "AvailableFunds": "available_funds",
        "ExcessLiquidity": "excess_liquidity",
        "TotalCashValue": "total_cash_value",
        "InitMarginReq": "initial_margin_required",
        "MaintMarginReq": "maintenance_margin_required",
        "GrossPositionValue": "gross_position_value",
        "Cushion": "cushion",
    }
    context = {
        "account_context_version": "local_console_account_capacity_v1",
        "source": "IBKR_ACCOUNT_SUMMARY_SANITIZED",
        "generated_at": now_iso(),
        "account_scope": active.get("account_scope") or os.getenv("STOCK_ULTIMUS_ACCOUNT_SCOPE") or "unknown",
        "account_alias": active.get("account_alias") or os.getenv("IBKR_ACCOUNT_ALIAS") or "unknown",
        "available": False,
        "currency": None,
        "net_liquidation": None,
        "buying_power": None,
        "available_funds": None,
        "excess_liquidity": None,
        "total_cash_value": None,
        "initial_margin_required": None,
        "maintenance_margin_required": None,
        "gross_position_value": None,
        "cushion": None,
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    ib = IB()
    try:
        ib.connect(host, int(port), clientId=int(client_id), readonly=True, timeout=timeout)
        try:
            summary = ib.accountSummary(account=selected) if selected else ib.accountSummary()
        except TypeError:
            summary = ib.accountSummary()
    except Exception as exc:
        context.update({
            "ok": False,
            "status": "ACCOUNT_SUMMARY_FAILED",
            "error": str(exc)[:240],
        })
        return context
    finally:
        try:
            if ib.isConnected():
                ib.disconnect()
        except Exception:
            pass

    preferred: list[tuple[str, Any, str]] = []
    fallback: list[tuple[str, Any, str]] = []
    for item in summary or []:
        if selected and str(getattr(item, "account", "") or "").strip() not in ["", selected]:
            continue
        mapped = fields.get(getattr(item, "tag", None))
        if not mapped:
            continue
        currency = str(getattr(item, "currency", "") or "").upper()
        row = (mapped, getattr(item, "value", None), currency)
        if currency in ["BASE", "USD", ""]:
            preferred.append(row)
        else:
            fallback.append(row)

    for mapped, value, currency in preferred + fallback:
        if context.get(mapped) is not None:
            continue
        parsed = console_float_or_none(value)
        if parsed is None:
            continue
        context[mapped] = round(parsed, 4)
        if not context.get("currency") and currency:
            context["currency"] = currency

    context["available_capacity"] = (
        context.get("available_funds")
        if context.get("available_funds") is not None
        else context.get("excess_liquidity")
        if context.get("excess_liquidity") is not None
        else context.get("buying_power")
    )
    context["available"] = any(
        context.get(key) is not None
        for key in ["net_liquidation", "buying_power", "available_funds", "excess_liquidity", "total_cash_value"]
    )
    context["ok"] = bool(context["available"])
    context["status"] = "ACCOUNT_CAPACITY_READY" if context["available"] else "ACCOUNT_SUMMARY_EMPTY"
    return context


def cmd_refresh_account_capacity(args: argparse.Namespace) -> int:
    context = account_summary_capacity(args.host, args.port, args.client_id, timeout=args.timeout)
    RUNTIME.mkdir(exist_ok=True)
    ACCOUNT_CAPACITY_PATH.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n")
    result = {
        "account_capacity": context,
        "capacity_file": str(ACCOUNT_CAPACITY_PATH.relative_to(ROOT)),
        "publish_result": None,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if args.publish and context.get("ok"):
        result["publish_result"] = publish_account_context_fallback()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if context.get("ok") else 1


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


def load_operator_events() -> list[dict[str, Any]]:
    try:
        data = json.loads(OPERATOR_EVENTS_PATH.read_text())
    except Exception:
        data = []
    return data if isinstance(data, list) else []


def save_operator_events(events: list[dict[str, Any]]) -> None:
    RUNTIME.mkdir(exist_ok=True)
    OPERATOR_EVENTS_PATH.write_text(json.dumps((events or [])[-10000:], indent=2, sort_keys=True) + "\n")


def local_operator_alert_id(payload: dict[str, Any]) -> str:
    alert_id = str(payload.get("alert_id") or "").strip()
    if alert_id:
        return alert_id
    ticker = str(payload.get("ticker") or "UNKNOWN").strip().upper() or "UNKNOWN"
    strategy = str(payload.get("strategy") or "UNKNOWN").strip().upper() or "UNKNOWN"
    state = str(payload.get("state") or "UNKNOWN").strip().upper() or "UNKNOWN"
    return f"ALERT-{datetime.now(timezone.utc).date().isoformat()}-{ticker}-{strategy}-{state}"


def record_local_operator_event(payload: dict[str, Any], remote_result: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    remote_result = remote_result if isinstance(remote_result, dict) else {}
    data = remote_result.get("data") if isinstance(remote_result.get("data"), dict) else {}
    remote_event = data.get("event") if isinstance(data.get("event"), dict) else {}
    action = str(remote_event.get("action") or payload.get("action") or "").upper()
    event = {
        "event_id": remote_event.get("event_id") or remote_event.get("id") or f"LOCAL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "id": remote_event.get("id") or remote_event.get("event_id") or f"LOCAL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "operator_event_version": remote_event.get("operator_event_version") or "local_console_operator_event_v1",
        "recorded_at": remote_event.get("recorded_at") or now_iso(),
        "alert_id": remote_event.get("alert_id") or local_operator_alert_id(payload),
        "ticker": remote_event.get("ticker") or str(payload.get("ticker") or "").upper() or None,
        "strategy": remote_event.get("strategy") or payload.get("strategy"),
        "action": action,
        "operator_status": remote_event.get("operator_status") or OPERATOR_STATUS_BY_ACTION.get(action, action or "UNKNOWN"),
        "reason": remote_event.get("reason") or payload.get("reason") or "",
        "actor": remote_event.get("actor") or payload.get("actor") or "stock_ultimus_console",
        "source": remote_event.get("source") or "local_stock_ultimus_console",
        "remote_recorded": bool(remote_result.get("ok")),
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    events = load_operator_events()
    if not any(item.get("event_id") == event["event_id"] for item in events if isinstance(item, dict)):
        events.append(event)
        save_operator_events(events)
    return event


def apply_local_operator_events(operator_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(operator_payload, dict):
        return operator_payload
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    alerts = data.get("active_alerts") if isinstance(data.get("active_alerts"), list) else []
    if not alerts:
        return operator_payload
    latest: dict[str, dict[str, Any]] = {}
    for event in load_operator_events():
        if not isinstance(event, dict):
            continue
        alert_id = str(event.get("alert_id") or "")
        if alert_id:
            latest[alert_id] = event
    if not latest:
        return operator_payload
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        event = latest.get(str(alert.get("alert_id") or ""))
        if not event:
            continue
        alert["operator_status"] = event.get("operator_status") or alert.get("operator_status")
        alert["last_operator_action"] = event.get("action") or alert.get("last_operator_action")
        alert["last_operator_reason"] = event.get("reason") or alert.get("last_operator_reason")
        alert["local_operator_event_applied"] = True
    data["local_operator_event_count"] = len(latest)
    return operator_payload


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
        "account_context": account_context,
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


def duration_label(started_at: Any, finished_at: Any = None) -> str:
    start = parse_iso_datetime(started_at)
    if not start:
        return "unknown"
    end = parse_iso_datetime(finished_at) or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    seconds = max(0, int((end - start).total_seconds()))
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    return f"{minutes // 60}h"


def active_web_jobs() -> list[dict[str, Any]]:
    with WEB_JOBS_LOCK:
        jobs = [
            dict(job)
            for job in WEB_JOBS.values()
            if isinstance(job, dict) and str(job.get("status") or "").upper() == "RUNNING"
        ]
    return sorted(jobs, key=lambda item: str(item.get("started_at") or ""), reverse=True)


def runtime_json_report(path: Path) -> dict[str, Any]:
    data = load_json_file(path)
    if not isinstance(data, dict):
        data = {}
    data["_runtime_path"] = str(path.relative_to(ROOT)) if path.exists() else str(path)
    data["_runtime_available"] = bool(path.exists())
    if path.exists():
        try:
            data["_runtime_mtime"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except Exception:
            data["_runtime_mtime"] = ""
    return data


def report_generated_at(report: dict[str, Any]) -> Any:
    return report.get("generated_at") or report.get("checked_at") or report.get("_runtime_mtime")


def report_age_text(report: dict[str, Any]) -> str:
    if not report.get("_runtime_available"):
        return "sin reporte"
    return age_label(report_generated_at(report))


def status_level(status: Any, ok: bool | None = None) -> str:
    text = str(status or "").upper()
    if ok is True or text in {"OK", "READY", "READY_FOR_MANUAL_REVIEW", "MATCH", "CONNECTED", "CONTRACT_RANKING_AVAILABLE", "RANKING_AVAILABLE"}:
        return "green"
    if ok is False or text in {"ERROR", "FAIL", "FAILED", "BLOCKED", "NO_DATA", "ACTION_REQUIRED", "PRODUCTION_UNREACHABLE", "REMOTE_UNAVAILABLE"}:
        return "red"
    if any(marker in text for marker in ["WAIT", "WATCH", "PARTIAL", "BUILDING", "NEEDS_REVIEW", "DEGRADED", "PENDING"]):
        return "amber"
    return "neutral"


def is_us_market_session_now() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    minute = now.hour * 60 + now.minute
    return (13 * 60 + 30) <= minute <= (20 * 60)


def console_reports() -> dict[str, dict[str, Any]]:
    return {
        "tradingview": runtime_json_report(TRADINGVIEW_BUNDLE_HEALTH_PATH),
        "readiness": runtime_json_report(MARKET_OPEN_READINESS_PATH),
        "post_open": runtime_json_report(POST_OPEN_MONITOR_PATH),
        "notify": runtime_json_report(OPERATOR_NOTIFY_PATH),
        "edge": runtime_json_report(OPERATIONAL_EDGE_PATH),
        "daily_open": runtime_json_report(DAILY_OPEN_CHECKLIST_PATH),
        "events": runtime_json_report(OPERATOR_EVENTS_PATH),
        "capacity": runtime_json_report(ACCOUNT_CAPACITY_PATH),
    }


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


def read_remote_cache(path: str, live_error: str = "", allow_stale: bool = False) -> dict[str, Any] | None:
    cache = load_json_file(REMOTE_CACHE_PATH)
    if cache.get("path") != path:
        return None
    age_seconds = cache_age_seconds(cache.get("cached_at"))
    if age_seconds is None:
        return None
    if not allow_stale and age_seconds > REMOTE_CACHE_MAX_AGE_SECONDS:
        return None
    result = cache.get("result") if isinstance(cache.get("result"), dict) else {}
    if not result.get("ok"):
        return None
    out = dict(result)
    out["cached"] = True
    out["stale_cache"] = bool(age_seconds > REMOTE_CACHE_MAX_AGE_SECONDS)
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
        cached = read_remote_cache(path, live_error="MISSING_READ_ACCESS_TOKEN", allow_stale=True)
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
        cached = read_remote_cache(path, live_error=error_text, allow_stale=True)
        return cached or {"ok": False, "error": error_text, "token_present": True, "url": url, "data": {}}
    except Exception as exc:
        error_text = str(exc)
        cached = read_remote_cache(path, live_error=error_text, allow_stale=True)
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
    return apply_local_operator_events(fetch_remote_json("/gpt_v32_operator_today?limit=12", prefer_cache=prefer_cache))


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


def console_health(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any]) -> dict[str, Any]:
    comparison = selected_vs_published(active, snapshot, operator_payload)
    running = active_web_jobs()
    token_present = bool(operator_payload.get("token_present") or read_access_token())
    remote_ok = bool(operator_payload.get("ok"))
    cached = bool(operator_payload.get("cached"))
    capacity = console_account_capacity(operator_payload, snapshot)
    blockers = []
    warnings = []
    if not token_present:
        blockers.append("READ_TOKEN_MISSING")
    if not remote_ok:
        blockers.append("PRODUCTION_UNREACHABLE")
    if comparison.get("needs_refresh"):
        warnings.append("GPT_CONTEXT_REFRESH_REQUIRED")
    if cached:
        warnings.append("USING_REMOTE_CACHE")
    if not snapshot.get("available"):
        warnings.append("SNAPSHOT_MISSING")
    if not capacity.get("available"):
        warnings.append("IBKR_CAPACITY_NOT_REFRESHED")
    if running:
        warnings.append("PROCESS_RUNNING")

    if blockers:
        level = "red"
        label = "Atencion"
        detail = "No todo esta conectado. Revisa token/produccion antes de operar la consola."
    elif running:
        level = "amber"
        label = "Pensando"
        detail = "Hay un proceso corriendo. Espera DONE antes de volver a refrescar."
    elif warnings:
        level = "amber"
        label = "Parcial"
        detail = "Consola utilizable, con datos que pueden requerir refresh."
    else:
        level = "green"
        label = "Conectado"
        detail = "Produccion, cuenta, snapshot y capacidad estan alineados para revision manual."

    return {
        "level": level,
        "label": label,
        "detail": detail,
        "blockers": blockers,
        "warnings": warnings,
        "running_jobs": running,
        "remote_ok": remote_ok,
        "cached": cached,
        "token_present": token_present,
        "context_status": comparison.get("status"),
        "snapshot_available": bool(snapshot.get("available")),
        "capacity_available": bool(capacity.get("available")),
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def render_console_health(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any]) -> str:
    health = console_health(active, snapshot, operator_payload)
    running = health.get("running_jobs") or []
    running_text = "sin procesos activos"
    if running:
        job = running[0]
        running_text = "{label} | {elapsed} | {status}".format(
            label=job.get("label") or "Proceso local",
            elapsed=duration_label(job.get("started_at")),
            status=job.get("status") or "RUNNING",
        )
    details = []
    details.extend(health.get("blockers") or [])
    details.extend(health.get("warnings") or [])
    detail_text = ", ".join(details) if details else "sin bloqueos visibles"
    return """
    <section class="control-strip health-{level}">
      <div class="signal">
        <span class="signal-dot"></span>
        <div>
          <strong>{label}</strong>
          <small>{detail}</small>
        </div>
      </div>
      <div class="control-facts">
        <span>Produccion: {production}</span>
        <span>Contexto GPT: {context}</span>
        <span>Snapshot: {snapshot}</span>
        <span>Capacidad: {capacity}</span>
      </div>
      <div class="thinking-now">
        <strong>{running_text}</strong>
        <small>{detail_text}</small>
      </div>
    </section>
    """.format(
        level=html_escape(health.get("level")),
        label=html_escape(health.get("label")),
        detail=html_escape(health.get("detail")),
        production="OK" if health.get("remote_ok") else "NO",
        context=html_escape(health.get("context_status")),
        snapshot="OK" if health.get("snapshot_available") else "NO",
        capacity="OK" if health.get("capacity_available") else "NO",
        running_text=html_escape(running_text),
        detail_text=html_escape(detail_text),
    )


def render_active_process_panel() -> str:
    jobs = active_web_jobs()
    if not jobs:
        return ""
    rows = []
    for job in jobs[:3]:
        rows.append("""
        <a class="process-row" href="/console?job_id={job_id}">
          <span class="process-pulse"></span>
          <strong>{label}</strong>
          <small>alias={alias} | corriendo hace {elapsed} | abre detalle RUNNING/DONE</small>
        </a>
        """.format(
            job_id=html_escape(job.get("job_id") or ""),
            label=html_escape(job.get("label") or "Proceso local"),
            alias=html_escape(job.get("alias") or ""),
            elapsed=html_escape(duration_label(job.get("started_at"))),
        ))
    return """
    <section class="panel process-panel">
      <div class="section-head">
        <h2>La consola esta trabajando</h2>
        <p>No presiones Refresh de nuevo hasta que el proceso termine. Puedes abrir el detalle para ver RUNNING/DONE.</p>
      </div>
      <div class="process-list">{rows}</div>
    </section>
    """.format(rows="".join(rows))


def first_pending_alert(operator_payload: dict[str, Any]) -> dict[str, Any]:
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    alerts = data.get("active_alerts") if isinstance(data.get("active_alerts"), list) else []
    for severity in ["RISK", "ACTION", "WATCH"]:
        for alert in alerts:
            if isinstance(alert, dict) and not is_handled_alert(alert) and str(alert.get("severity") or "").upper() == severity:
                return alert
    for alert in alerts:
        if isinstance(alert, dict) and not is_handled_alert(alert):
            return alert
    return {}


def console_today_summary(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    counts = operator_alert_counts(data)
    health = console_health(active, snapshot, operator_payload)
    first_alert = first_pending_alert(operator_payload)
    readiness = reports.get("readiness") or {}
    notify = reports.get("notify") or {}
    edge = reports.get("edge") or {}
    tradingview = reports.get("tradingview") or {}
    next_actions = data.get("next_actions") if isinstance(data.get("next_actions"), list) else []
    next_action = next_actions[0] if next_actions else {}

    if health.get("level") == "red":
        mode = "Bloqueado"
        action = "Resolver conexion/token/produccion antes de operar."
    elif active_web_jobs():
        mode = "Procesando"
        action = "Esperar DONE; no lanzar otro refresh mientras corre el proceso."
    elif counts["risk"]:
        mode = "Riesgo"
        action = "Revisar alertas RISK y registrar rechazo/cierre si aplica."
    elif counts["action"]:
        mode = "Revision"
        action = "Revisar alertas ACTION con checklist, contrato y capacidad."
    elif str(data.get("status") or "").upper() == "WAIT_MARKET":
        mode = "Esperando mercado"
        action = "Mantener monitoreo; no convertir WAIT_MARKET en entrada."
    elif not is_us_market_session_now():
        mode = "Fuera de mercado"
        action = "Preparar diagnostico y esperar eventos reales en sesion."
    else:
        mode = "Monitoreo"
        action = next_action.get("label") or "Actualizar estado y revisar si hay nuevas alertas."

    recommended_sequence = edge.get("recommended_sequence") if isinstance(edge.get("recommended_sequence"), list) else []
    waiting = readiness.get("next_required_action") or (recommended_sequence[0] if recommended_sequence else "") or "Sin bloqueo principal visible."
    last_alert = "Sin alerta pendiente"
    if first_alert:
        last_alert = "{ticker} | {severity} | {state}".format(
            ticker=first_alert.get("ticker") or "UNKNOWN",
            severity=first_alert.get("severity") or "UNKNOWN",
            state=first_alert.get("state") or "UNKNOWN",
        )

    return {
        "mode": mode,
        "action": action,
        "waiting": waiting,
        "last_alert": last_alert,
        "market_session": "abierta" if is_us_market_session_now() else "cerrada",
        "operator_status": data.get("status") or ("OK" if operator_payload.get("ok") else operator_payload.get("error") or "UNKNOWN"),
        "edge_score": edge.get("overall_edge_score"),
        "notify_reason": (notify.get("classification") if isinstance(notify.get("classification"), dict) else {}).get("notify_reason") or notify.get("status") or "N/D",
        "tv_status": tradingview.get("status") or "N/D",
        "counts": counts,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def render_today_panel(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]]) -> str:
    today = console_today_summary(active, snapshot, operator_payload, reports)
    counts = today["counts"]
    edge_score = today.get("edge_score")
    edge_text = compact_percent(edge_score) if edge_score is not None else "N/D"
    return """
    <section class="panel today-panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Modo Hoy</p>
          <h2>{mode}</h2>
        </div>
        <p>{action}</p>
      </div>
      <div class="today-grid">
        {status}
        {waiting}
        {alert}
        {market}
      </div>
    </section>
    """.format(
        mode=html_escape(today["mode"]),
        action=html_escape(today["action"]),
        status=render_metric("Estado operador", today["operator_status"], "pendientes={open} | risk={risk} | action={action}".format(**counts)),
        waiting=render_metric("Esta esperando", today["waiting"], "TradingView=" + str(today.get("tv_status"))),
        alert=render_metric("Ultima alerta viva", today["last_alert"], "notify=" + str(today.get("notify_reason"))),
        market=render_metric("Mercado", today["market_session"], "edge=" + edge_text),
    )


def module_health_items(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    comparison = selected_vs_published(active, snapshot, operator_payload)
    capacity = console_account_capacity(operator_payload, snapshot)
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    counts = operator_alert_counts(data)
    tradingview = reports.get("tradingview") or {}
    readiness = reports.get("readiness") or {}
    notify = reports.get("notify") or {}
    edge = reports.get("edge") or {}
    return [
        {
            "name": "TWS/IBKR",
            "level": status_level("OK" if snapshot.get("available") else "WAITING"),
            "status": "snapshot OK" if snapshot.get("available") else "sin snapshot",
            "detail": age_label(snapshot.get("generated_at") or snapshot.get("mtime")),
        },
        {
            "name": "TradingView",
            "level": status_level(tradingview.get("status"), ok=bool(tradingview.get("real_e2e_confirmed")) if tradingview.get("_runtime_available") else None),
            "status": tradingview.get("status") or "sin reporte",
            "detail": "recibidos {}/{}".format(tradingview.get("total_received_required_event_count", 0), tradingview.get("total_required_logical_event_count", tradingview.get("total_required_alert_count", 0))),
        },
        {
            "name": "Produccion",
            "level": status_level("OK" if operator_payload.get("ok") else "ERROR"),
            "status": "OK" if operator_payload.get("ok") else operator_payload.get("error") or "NO",
            "detail": "cache " + (operator_payload.get("cache_age_label") or "live"),
        },
        {
            "name": "GPT Action",
            "level": status_level(comparison.get("status")),
            "status": comparison.get("status"),
            "detail": "local={} | GPT={}".format(comparison.get("selected_alias") or "none", comparison.get("published_alias") or "none"),
        },
        {
            "name": "Notificaciones",
            "level": status_level("OK" if notify.get("status") == "OK" else notify.get("status")),
            "status": (notify.get("classification") if isinstance(notify.get("classification"), dict) else {}).get("notify_reason") or notify.get("status") or "sin reporte",
            "detail": report_age_text(notify),
        },
        {
            "name": "Capacidad",
            "level": status_level("OK" if capacity.get("available") else "WAITING"),
            "status": "OK" if capacity.get("available") else "pendiente",
            "detail": compact_money(capacity.get("available_capacity")) + " | " + str(capacity.get("capacity_source") or "N/D"),
        },
        {
            "name": "Alertas",
            "level": "red" if counts["risk"] else ("amber" if counts["action"] or counts["watch"] else "green"),
            "status": "{open} abiertas".format(**counts),
            "detail": "{risk} risk | {action} action | {closed} atendidas".format(**counts),
        },
        {
            "name": "Operational Edge",
            "level": status_level(edge.get("overall_status")),
            "status": edge.get("overall_status") or readiness.get("status") or "sin reporte",
            "detail": "score=" + (compact_percent(edge.get("overall_edge_score")) if edge.get("overall_edge_score") is not None else "N/D"),
        },
    ]


def render_module_health(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]]) -> str:
    cards = []
    for item in module_health_items(active, snapshot, operator_payload, reports):
        cards.append("""
        <article class="module-card module-{level}">
          <span class="module-dot"></span>
          <div>
            <strong>{name}</strong>
            <span>{status}</span>
            <small>{detail}</small>
          </div>
        </article>
        """.format(
            level=html_escape(item.get("level") or "neutral"),
            name=html_escape(item.get("name") or ""),
            status=html_escape(item.get("status") or ""),
            detail=html_escape(item.get("detail") or ""),
        ))
    return """
    <section class="panel">
      <div class="section-head">
        <h2>Semaforo por modulo</h2>
        <p>Lectura rapida de los sistemas que importan antes de revisar alertas.</p>
      </div>
      <div class="module-grid">{cards}</div>
    </section>
    """.format(cards="".join(cards))


def append_timeline_event(events: list[dict[str, Any]], when: Any, title: str, detail: str, level: str = "neutral") -> None:
    dt = parse_iso_datetime(when)
    events.append({
        "when": when or "",
        "dt": dt,
        "title": title,
        "detail": detail,
        "level": level,
    })


def console_timeline(snapshot: dict[str, Any], operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if snapshot.get("available"):
        append_timeline_event(events, snapshot.get("generated_at") or snapshot.get("mtime"), "Snapshot maestro", "Contexto local disponible", "green")
    for job in active_web_jobs():
        append_timeline_event(events, job.get("started_at"), "Proceso corriendo", "{} | {}".format(job.get("label") or "Proceso local", job.get("status") or "RUNNING"), "amber")
    for event in load_operator_events()[-5:]:
        append_timeline_event(events, event.get("recorded_at"), "Alerta marcada", "{} {} -> {}".format(event.get("ticker") or "", event.get("action") or "", event.get("operator_status") or ""), "green")
    notify = reports.get("notify") or {}
    if notify.get("_runtime_available"):
        append_timeline_event(events, report_generated_at(notify), "Notificador", "{} | sent={}".format((notify.get("classification") if isinstance(notify.get("classification"), dict) else {}).get("notify_reason") or notify.get("status"), notify.get("notification_sent")), status_level(notify.get("status")))
    tradingview = reports.get("tradingview") or {}
    if tradingview.get("_runtime_available"):
        append_timeline_event(events, report_generated_at(tradingview), "TradingView health", "{} | {}/{} recibidos".format(tradingview.get("status"), tradingview.get("total_received_required_event_count", 0), tradingview.get("total_required_logical_event_count", tradingview.get("total_required_alert_count", 0))), status_level(tradingview.get("status")))
    readiness = reports.get("readiness") or {}
    if readiness.get("_runtime_available"):
        append_timeline_event(events, report_generated_at(readiness), "Readiness", readiness.get("next_required_action") or readiness.get("status") or "sin detalle", status_level(readiness.get("status"), ok=readiness.get("ok") is True))
    if operator_payload.get("cached_at"):
        append_timeline_event(events, operator_payload.get("cached_at"), "Estado GPT cacheado", operator_payload.get("cache_age_label") or "cache local", "amber")
    return sorted(events, key=lambda item: item.get("dt") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:8]


def render_timeline(snapshot: dict[str, Any], operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]]) -> str:
    events = console_timeline(snapshot, operator_payload, reports)
    if not events:
        rows = '<p class="empty">Sin eventos locales recientes.</p>'
    else:
        rows = "".join("""
        <li class="timeline-{level}">
          <span></span>
          <div><strong>{title}</strong><small>{age} · {detail}</small></div>
        </li>
        """.format(
            level=html_escape(event.get("level") or "neutral"),
            title=html_escape(event.get("title") or ""),
            age=html_escape(age_label(event.get("when"))),
            detail=html_escape(event.get("detail") or ""),
        ) for event in events)
    return """
    <section class="panel">
      <div class="section-head">
        <h2>Timeline operativo</h2>
        <p>Lo ultimo que la consola sabe de procesos, alertas, TradingView y notificaciones.</p>
      </div>
      <ol class="timeline">{rows}</ol>
    </section>
    """.format(rows=rows)


def render_market_mode_panel(operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]]) -> str:
    tradingview = reports.get("tradingview") or {}
    notify = reports.get("notify") or {}
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    alerts = data.get("active_alerts") if isinstance(data.get("active_alerts"), list) else []
    futures_alerts = [
        alert for alert in alerts
        if isinstance(alert, dict) and (
            str(alert.get("strategy") or "").upper() == "INTRADAY_INDEX_FUTURES"
            or str(alert.get("ticker") or "").upper() in {"MNQ", "MNQ1!", "NQ", "MES", "MES1!", "ES"}
        )
    ]
    session = "Mercado abierto" if is_us_market_session_now() else "Mercado cerrado"
    detail = "Durante mercado abierto, los futuros intradia deben llegar por TradingView -> /technical_snapshot -> notify inmediato."
    return """
    <section class="panel market-panel">
      <div class="section-head">
        <h2>Modo mercado abierto</h2>
        <p>{detail}</p>
      </div>
      <div class="tiles">
        <div class="tile">{session}<span>La consola separa espera normal de alertas vivas.</span></div>
        <div class="tile">Futuros vivos<span>{futures_count} alerta(s) intradia en payload actual.</span></div>
        <div class="tile">TradingView real<span>{received}/{required} eventos requeridos recibidos.</span></div>
        <div class="tile">Notify<span>{notify_reason}</span></div>
      </div>
    </section>
    """.format(
        detail=html_escape(detail),
        session=html_escape(session),
        futures_count=html_escape(len(futures_alerts)),
        received=html_escape(tradingview.get("total_received_required_event_count", 0)),
        required=html_escape(tradingview.get("total_required_logical_event_count", tradingview.get("total_required_alert_count", 0))),
        notify_reason=html_escape((notify.get("classification") if isinstance(notify.get("classification"), dict) else {}).get("notify_reason") or notify.get("status") or "sin reporte"),
    )


def render_diagnostic_panel(active: dict[str, Any], reports: dict[str, dict[str, Any]]) -> str:
    alias = active.get("account_alias") or ""
    daily = reports.get("daily_open") or {}
    edge = reports.get("edge") or {}
    disabled = "" if alias else " disabled"
    note = "Usa este boton cuando quieras una revision completa sin salir de la consola."
    if not alias:
        note = "Selecciona una cuenta antes de correr diagnostico local."
    return """
    <section class="panel diagnostic-panel">
      <div class="section-head">
        <h2>Diagnostico completo</h2>
        <p>{note}</p>
      </div>
      <div class="tiles">
        <div class="tile">Ultimo checklist<span>{daily_status} · {daily_age}</span></div>
        <div class="tile">Operational Edge<span>{edge_status} · score {edge_score}</span></div>
      </div>
      <form method="post" action="/diagnostic" class="hero-actions" data-busy="Diagnosticando sistema" data-busy-detail="Revisando tokens, runtime, produccion, evidencia y alertas. No ejecuta ordenes.">
        <input name="alias" value="{alias}" type="hidden">
        <button{disabled}>Revisar sistema</button>
        <span>Corre el checklist seguro y deja resultado RUNNING/DONE aqui mismo.</span>
      </form>
    </section>
    """.format(
        note=html_escape(note),
        daily_status=html_escape(daily.get("status") or daily.get("classification") or "sin reporte"),
        daily_age=html_escape(report_age_text(daily)),
        edge_status=html_escape(edge.get("overall_status") or "sin reporte"),
        edge_score=html_escape(compact_percent(edge.get("overall_edge_score")) if edge.get("overall_edge_score") is not None else "N/D"),
        alias=html_escape(alias),
        disabled=disabled,
    )


def render_console_context(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any]) -> str:
    comparison = selected_vs_published(active, snapshot, operator_payload)
    operator_data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    status = operator_data.get("status") or ("OK" if operator_payload.get("ok") else operator_payload.get("error") or "UNKNOWN")
    warning = ""
    if not comparison["remote_ok"]:
        warning = """
        <div class="warning">No pude verificar que cuenta ve GPT porque produccion no respondio a tiempo. <strong>Actualizar estado</strong> solo relee GPT/alertas; <strong>Usar cuenta</strong> publica la cuenta seleccionada para GPT; <strong>Refresh IBKR</strong> trae datos frescos del broker.</div>
        """
    elif comparison["needs_refresh"]:
        warning = """
        <div class="warning">La seleccion local no coincide con lo que GPT ve. Usa <strong>Usar cuenta</strong> y espera DONE en el trabajo local; usa <strong>Refresh IBKR</strong> solo si necesitas datos nuevos del broker/opciones.</div>
        """
    elif not comparison["published_scope"]:
        warning = """
        <div class="warning">No hay contexto publicado para GPT. Selecciona una cuenta con <strong>Usar cuenta</strong>; no necesitas tocar IBKR para publicar el contexto.</div>
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
      <form method="post" action="/refresh-remote" class="hero-actions" data-busy="Actualizando estado remoto" data-busy-detail="Leyendo GPT/alertas desde produccion. No cambia cuenta ni conecta con IBKR.">
        <button>Actualizar estado</button>
        <span>Relee lo que produccion ya tiene publicado. No cambia cuenta ni refresca IBKR.</span>
      </form>
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


def render_console_actions(operator_payload: dict[str, Any] | None = None) -> str:
    operator_payload = operator_payload if isinstance(operator_payload, dict) else {}
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    counts = operator_alert_counts(data)
    intraday = data.get("intraday_futures") if isinstance(data.get("intraday_futures"), dict) else {}
    alerts = data.get("active_alerts") if isinstance(data.get("active_alerts"), list) else []
    intraday_count = sum(
        1 for alert in alerts
        if str((alert or {}).get("strategy") or "").upper() == "INTRADAY_INDEX_FUTURES"
        or str((alert or {}).get("ticker") or "").upper() in {"MNQ", "NQ", "MES", "ES"}
    )
    intraday_message = intraday.get("message")
    if not intraday_message:
        intraday_message = (
            "Hay alertas intradia de futuros en el payload actual."
            if intraday_count
            else "Sin alertas intradia de futuros en el payload actual; solo validar monitoreo y datos."
        )
    next_actions = data.get("next_actions") if isinstance(data.get("next_actions"), list) else []
    next_action = next_actions[0] if next_actions else {}
    account = data.get("account_alias") or data.get("account_scope") or "pendiente"
    status = data.get("status") or ("OK" if operator_payload.get("ok") else operator_payload.get("error") or "UNKNOWN")
    return """
    <section class="panel">
      <h2>Administracion desde esta consola</h2>
      <div class="tiles">
        <div class="tile">Alertas y acciones<span>{open} pendientes: {risk} riesgo, {watch} watch, {action} action. Usa los botones de cada tarjeta aqui mismo.</span></div>
        <div class="tile">Contexto GPT activo<span>status={status} | cuenta={account}. Actualiza con el boton de arriba; no necesitas abrir otro dashboard.</span></div>
        <div class="tile">Siguiente paso<span>{next_label}</span></div>
        <div class="tile">Futuros intradia<span>{intraday_message}</span></div>
        <div class="tile">Historial local visible<span>{closed} alerta(s) cerrada(s) o revisada(s) quedan debajo de Alertas V32.</span></div>
      </div>
      <p class="muted">No hace falta salir de esta consola para administrar cuenta, refrescar IBKR, revisar alertas o registrar decisiones. Rutas de diagnostico protegidas, no requeridas para operar desde consola: /gpt_v32_operator_today · /v32_operator_dashboard · /v32_operator_daily_summary_email/preview · /v32_operator_tracking_status.</p>
    </section>
    """.format(
        open=html_escape(counts["open"]),
        risk=html_escape(counts["risk"]),
        watch=html_escape(counts["watch"]),
        action=html_escape(counts["action"]),
        closed=html_escape(counts["closed"]),
        status=html_escape(status),
        account=html_escape(account),
        next_label=html_escape(next_action.get("label") or "Sin accion inmediata; mantener monitoreo desde la consola."),
        intraday_message=html_escape(intraday_message),
    )


def compact_contract_value(value: Any, suffix: str = "") -> str:
    if value in [None, "", "None"]:
        return "-"
    try:
        number = float(value)
        text = ("{:.4f}".format(number)).rstrip("0").rstrip(".")
    except Exception:
        text = str(value)
    return text + suffix


def compact_money(value: Any) -> str:
    try:
        number = float(value)
        return "${:,.2f}".format(number)
    except Exception:
        return "N/D"


def compact_percent(value: Any) -> str:
    try:
        number = float(value)
        return "{:.2f}%".format(number)
    except Exception:
        return "N/D"


def console_float_or_none(value: Any) -> float | None:
    try:
        if value in [None, "", "None", "null", "NULL"]:
            return None
        return float(value)
    except Exception:
        return None


def console_account_capacity(operator_payload: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    capacity = data.get("account_capacity") if isinstance(data.get("account_capacity"), dict) else {}
    context = data.get("account_context") if isinstance(data.get("account_context"), dict) else {}
    if not context:
        context = snapshot.get("account_context") if isinstance(snapshot.get("account_context"), dict) else {}
    local_capacity = load_json_file(ACCOUNT_CAPACITY_PATH)
    if isinstance(local_capacity, dict) and local_capacity.get("available"):
        active = active_profile()
        local_alias = local_capacity.get("account_alias")
        local_scope = local_capacity.get("account_scope")
        if not active or local_alias == active.get("account_alias") or local_scope == active.get("account_scope"):
            capacity = {**capacity, **local_capacity}
            context = {**context, **local_capacity}
    available_funds = console_float_or_none(capacity.get("available_funds", context.get("available_funds")))
    excess_liquidity = console_float_or_none(capacity.get("excess_liquidity", context.get("excess_liquidity")))
    buying_power = console_float_or_none(capacity.get("buying_power", context.get("buying_power")))
    available_capacity = console_float_or_none(capacity.get("available_capacity", context.get("available_capacity")))
    source = capacity.get("capacity_source") or "available_capacity"
    if available_capacity is None:
        if available_funds is not None:
            available_capacity = available_funds
            source = "available_funds"
        elif excess_liquidity is not None:
            available_capacity = excess_liquidity
            source = "excess_liquidity"
        elif buying_power is not None:
            available_capacity = buying_power
            source = "buying_power"
        else:
            source = "N/D"
    return {
        "available": available_capacity is not None,
        "available_capacity": available_capacity,
        "capacity_source": source,
        "currency": capacity.get("currency") or context.get("currency") or "USD",
        "net_liquidation": console_float_or_none(capacity.get("net_liquidation", context.get("net_liquidation"))),
        "buying_power": buying_power,
        "available_funds": available_funds,
        "excess_liquidity": excess_liquidity,
        "initial_margin_required": console_float_or_none(capacity.get("initial_margin_required", context.get("initial_margin_required"))),
        "maintenance_margin_required": console_float_or_none(capacity.get("maintenance_margin_required", context.get("maintenance_margin_required"))),
        "generated_at": capacity.get("generated_at") or context.get("generated_at") or snapshot.get("generated_at"),
        "account_alias": data.get("account_alias") or context.get("account_alias") or snapshot.get("account_alias"),
        "account_scope": data.get("account_scope") or context.get("account_scope") or snapshot.get("account_scope"),
        "sensitive_identifiers_excluded": True,
    }


def render_account_capacity_panel(operator_payload: dict[str, Any], snapshot: dict[str, Any]) -> str:
    capacity = console_account_capacity(operator_payload, snapshot)
    if not capacity.get("available"):
        note = "No hay capacidad de cuenta disponible todavia. Usa Refresh IBKR para traer AccountSummary de la cuenta seleccionada."
    else:
        note = "Comparacion informativa; el ticket final/margen se valida en IBKR antes de cualquier decision manual."
    return """
    <section class="panel">
      <div class="section-head">
        <h2>Capacidad IBKR</h2>
        <p>{note}</p>
      </div>
      <div class="capacity-grid">
        {usable}
        {available_funds}
        {excess}
        {buying_power}
        {net_liq}
        {margin}
      </div>
    </section>
    """.format(
        note=html_escape(note),
        usable=render_metric(
            "Capacidad usable",
            compact_money(capacity.get("available_capacity")),
            "fuente=" + str(capacity.get("capacity_source") or "N/D") + " | cuenta=" + str(capacity.get("account_alias") or capacity.get("account_scope") or "N/D"),
        ),
        available_funds=render_metric("AvailableFunds", compact_money(capacity.get("available_funds")), capacity.get("currency") or "USD"),
        excess=render_metric("ExcessLiquidity", compact_money(capacity.get("excess_liquidity")), capacity.get("currency") or "USD"),
        buying_power=render_metric("BuyingPower", compact_money(capacity.get("buying_power")), capacity.get("currency") or "USD"),
        net_liq=render_metric("NetLiquidation", compact_money(capacity.get("net_liquidation")), capacity.get("currency") or "USD"),
        margin=render_metric(
            "Margen usado",
            compact_money(capacity.get("initial_margin_required")),
            "maint=" + compact_money(capacity.get("maintenance_margin_required")) + " | " + age_label(capacity.get("generated_at")),
        ),
    )


def alert_date_label(alert: dict[str, Any]) -> str:
    value = alert.get("alert_date") or alert.get("alert_created_at") or alert.get("received_at") or alert.get("generated_at")
    if not value:
        alert_id = str(alert.get("alert_id") or "")
        parts = alert_id.split("-")
        if len(parts) >= 4 and parts[0] == "ALERT":
            value = "-".join(parts[1:4])
    if not value:
        return "Fecha alerta: N/D"
    text = str(value)
    return "Fecha alerta: " + (text[:10] if len(text) >= 10 else text)


def render_alert_contract(alert: dict[str, Any]) -> str:
    contract = alert.get("selected_contract") if isinstance(alert.get("selected_contract"), dict) else {}
    strike = contract.get("strike") or alert.get("strike")
    expiration = contract.get("expiration") or alert.get("expiration") or alert.get("expiry")
    dte = contract.get("dte") or alert.get("dte")
    bid = contract.get("bid")
    ask = contract.get("ask")
    mid = contract.get("mid") or alert.get("price")
    spread = contract.get("spread_pct")
    delta = contract.get("delta")
    has_contract = any(value not in [None, "", "None"] for value in [strike, expiration, dte, bid, ask, mid, spread, delta])
    if not has_contract:
        return "Contrato: pendiente de datos"
    return (
        "Contrato: strike {strike} | exp {expiration} | DTE {dte} | bid/ask {bid}/{ask} | mid {mid} | spread {spread} | delta {delta}"
    ).format(
        strike=compact_contract_value(strike),
        expiration=compact_contract_value(expiration),
        dte=compact_contract_value(dte),
        bid=compact_contract_value(bid),
        ask=compact_contract_value(ask),
        mid=compact_contract_value(mid),
        spread=compact_contract_value(spread, "%"),
        delta=compact_contract_value(delta),
    )


def render_alert_economics(alert: dict[str, Any]) -> str:
    economics = alert.get("economics") if isinstance(alert.get("economics"), dict) else {}
    contract = alert.get("selected_contract") if isinstance(alert.get("selected_contract"), dict) else {}
    capital = economics.get("capital_required", contract.get("capital_required"))
    credit = economics.get("gross_credit", contract.get("gross_credit"))
    probability = economics.get("probability_success_pct", contract.get("probability_success_pct"))
    annualized = economics.get(
        "annualized_return_on_capital_pct",
        contract.get("annualized_return_on_capital_pct"),
    )
    capital_source = economics.get("capital_source") or "N/D"
    probability_source = economics.get("probability_source") or "N/D"

    strategy = str(alert.get("strategy") or contract.get("strategy") or "").upper()
    strike = console_float_or_none(contract.get("strike") or alert.get("strike"))
    dte = console_float_or_none(contract.get("dte") or alert.get("dte"))
    delta = console_float_or_none(contract.get("delta") or alert.get("delta"))
    bid = console_float_or_none(contract.get("bid"))
    mid = console_float_or_none(contract.get("mid") or alert.get("price"))
    option_credit = bid if bid is not None else mid

    if credit is None and option_credit is not None:
        credit = option_credit * 100.0
    if capital is None and strike is not None and option_credit is not None and strategy in {
        "NAKED_PUT",
        "CASH_SECURED_PUT",
        "SHORT_PUT",
        "PUT_SELL",
    }:
        capital = max((strike * 100.0) - (option_credit * 100.0), 0.0)
        capital_source = "estimated_cash_secured_put"
    if probability is None and delta is not None and abs(delta) <= 1 and strategy in {
        "NAKED_PUT",
        "CASH_SECURED_PUT",
        "SHORT_PUT",
        "PUT_SELL",
        "COVERED_CALL",
        "SHORT_CALL_COVERED",
    }:
        probability = max(0.0, min((1.0 - abs(delta)) * 100.0, 100.0))
        probability_source = "delta_proxy"
    if annualized is None and credit is not None and capital not in [None, 0] and dte not in [None, 0]:
        annualized = ((float(credit) / float(capital)) * 100.0) * (365.0 / float(dte))

    if capital is None and credit is None and probability is None and annualized is None:
        return "Capital req: N/D | credito bruto: N/D | prob. exito: N/D | retorno anualizado: N/D | faltan contrato IBKR completo y/o delta"

    return (
        "Capital req: {capital} ({capital_source}) | credito bruto: {credit} | "
        "prob. exito: {probability} ({probability_source}) | retorno anualizado: {annualized}"
    ).format(
        capital=compact_money(capital),
        capital_source=html_escape(capital_source),
        credit=compact_money(credit),
        probability=compact_percent(probability),
        probability_source=html_escape(probability_source),
        annualized=compact_percent(annualized),
    )


def console_alert_capital_required(alert: dict[str, Any]) -> float | None:
    economics = alert.get("economics") if isinstance(alert.get("economics"), dict) else {}
    contract = alert.get("selected_contract") if isinstance(alert.get("selected_contract"), dict) else {}
    capital = console_float_or_none(economics.get("capital_required", contract.get("capital_required")))
    if capital is not None:
        return capital
    strategy = str(alert.get("strategy") or contract.get("strategy") or "").upper()
    strike = console_float_or_none(contract.get("strike") or alert.get("strike"))
    bid = console_float_or_none(contract.get("bid"))
    mid = console_float_or_none(contract.get("mid") or alert.get("price"))
    credit = bid if bid is not None else mid
    if strike is not None and credit is not None and strategy in {
        "NAKED_PUT",
        "CASH_SECURED_PUT",
        "SHORT_PUT",
        "PUT_SELL",
    }:
        return max((strike * 100.0) - (credit * 100.0), 0.0)
    spread_width = console_float_or_none(contract.get("spread_width") or alert.get("spread_width"))
    if spread_width is not None and credit is not None:
        return max((spread_width * 100.0) - (credit * 100.0), 0.0)
    underlying_price = console_float_or_none(contract.get("underlying_price") or alert.get("underlying_price"))
    if strategy in {"COVERED_CALL", "SHORT_CALL_COVERED"} and underlying_price is not None:
        return max(underlying_price * 100.0, 0.0)
    return None


def render_alert_capacity(alert: dict[str, Any], account_capacity: dict[str, Any]) -> str:
    check = alert.get("account_capacity_check") if isinstance(alert.get("account_capacity_check"), dict) else {}
    capital = console_float_or_none(check.get("capital_required"))
    if capital is None:
        capital = console_alert_capital_required(alert)
    available = console_float_or_none(check.get("available_capacity"))
    if available is None:
        available = console_float_or_none(account_capacity.get("available_capacity"))
    source = check.get("capacity_source") or account_capacity.get("capacity_source") or "N/D"
    if capital is None:
        return "Cuenta: capacidad {available} ({source}) | alerta no evaluable: falta capital requerido".format(
            available=compact_money(available),
            source=html_escape(source),
        )
    if available is None:
        return "Cuenta: capital requerido {capital} | capacidad disponible N/D; usa Refresh IBKR para validar margen".format(
            capital=compact_money(capital),
        )
    pct = (capital / available) * 100.0 if available > 0 else None
    shortfall = max(capital - available, 0.0)
    status = "dentro de margen disponible" if shortfall <= 0 else "sin capital suficiente"
    warning = ""
    if shortfall <= 0 and pct is not None and pct > 25.0:
        warning = " | consume >25% de la capacidad"
    return (
        "Cuenta: {status} | requerido {capital} vs disponible {available} ({source}) | "
        "uso {pct} | faltante {shortfall}{warning}"
    ).format(
        status=status,
        capital=compact_money(capital),
        available=compact_money(available),
        source=html_escape(source),
        pct=compact_percent(pct),
        shortfall=compact_money(shortfall),
        warning=warning,
    )


def alert_review_guidance(alert: dict[str, Any]) -> str:
    state = str(alert.get("state") or "").upper()
    severity = str(alert.get("severity") or "").upper()
    blocker = str(alert.get("main_blocker") or "").upper()
    if severity == "RISK" or state == "RISK_BLOCKED":
        return "Revision: no aprobar. Documentar el bloqueo de riesgo o rechazar el setup."
    if state == "WAIT_TECHNICAL" or blocker == "WAIT_TECHNICAL":
        return "Revision: mantener en watch hasta que llegue confirmacion tecnica."
    if state == "WAIT_OPTIONS_DATA" or blocker == "WAIT_OPTIONS_DATA":
        return "Revision: mantener en watch; faltan datos completos/confiables de opciones."
    if state == "ENTRY_READY":
        return "Revision: revisar manualmente contrato, riesgo, portfolio y contexto antes de cualquier decision."
    return "Revision: ack si ya fue visto, watch si sigue vivo, reject si no cumple."


def alert_reason_plain(alert: dict[str, Any]) -> str:
    state = str(alert.get("state") or "").upper()
    blocker = str(alert.get("main_blocker") or "").upper()
    missing = alert.get("required_missing_fields") if isinstance(alert.get("required_missing_fields"), list) else []
    if state == "ENTRY_READY":
        return "Cumple lo suficiente para revision manual: aun falta confirmar orden/ticket en IBKR."
    if state == "WAIT_MARKET":
        return "La estructura puede existir, pero la ventana/condicion de mercado aun no autoriza revision accionable."
    if state == "WAIT_TECHNICAL" or blocker == "WAIT_TECHNICAL":
        return "Falta confirmacion tecnica real; mantener en watch hasta recibir evidencia."
    if state == "WAIT_OPTIONS_DATA" or blocker == "WAIT_OPTIONS_DATA":
        return "Faltan datos completos de opciones, spread, delta, DTE o calidad de contrato."
    if state == "RISK_BLOCKED" or str(alert.get("severity") or "").upper() == "RISK":
        return "Bloqueada por riesgo; revisar causa y normalmente rechazar/cerrar."
    if missing:
        return "Faltan campos: " + ", ".join(str(item) for item in missing[:4])
    return "No hay razon accionable completa; usar la guia de revision y registrar estado."


def alert_checklist_items(alert: dict[str, Any], account_capacity: dict[str, Any]) -> list[tuple[str, bool, str]]:
    contract = alert.get("selected_contract") if isinstance(alert.get("selected_contract"), dict) else {}
    state = str(alert.get("state") or "").upper()
    blocker = str(alert.get("main_blocker") or "").upper()
    severity = str(alert.get("severity") or "").upper()
    capital = console_alert_capital_required(alert)
    available = console_float_or_none(account_capacity.get("available_capacity"))
    technical_ok = state in {"ENTRY_READY", "WAIT_MARKET"} and blocker not in {"WAIT_TECHNICAL", "TECHNICAL_NOT_CONFIRMED"}
    options_ok = all(contract.get(field) not in [None, "", "None"] for field in ["strike", "dte", "delta"]) and (
        contract.get("bid") not in [None, "", "None"] or contract.get("mid") not in [None, "", "None"]
    )
    capacity_ok = capital is not None and available is not None and capital <= available
    canslim_value = alert.get("canslim_score") or alert.get("canslim_confidence")
    canslim_ok = canslim_value not in [None, "", "None"]
    risk_ok = severity != "RISK" and state != "RISK_BLOCKED" and not str(alert.get("risk_blocker") or "")
    score_ok = any(alert.get(field) not in [None, "", "None"] for field in ["setup_validity_pct", "conviction_score", "ranking_score", "raw_score"])
    return [
        ("Score", score_ok, "score/conviccion visible" if score_ok else "falta score visible"),
        ("Tecnico", technical_ok, "confirmado o esperando mercado" if technical_ok else "falta confirmacion tecnica"),
        ("Opciones", options_ok, "strike/DTE/delta presentes" if options_ok else "contrato incompleto"),
        ("Capacidad", capacity_ok, "capital dentro de cuenta" if capacity_ok else "requiere validar capital"),
        ("CANSLIM", canslim_ok, "contexto dinamico presente" if canslim_ok else "sin dato CANSLIM en alerta"),
        ("Riesgo", risk_ok, "sin bloqueo de riesgo" if risk_ok else "bloqueo/riesgo activo"),
    ]


def render_alert_checklist(alert: dict[str, Any], account_capacity: dict[str, Any]) -> str:
    items = []
    for label, ok, note in alert_checklist_items(alert, account_capacity):
        items.append("""
        <li class="{klass}"><span></span><strong>{label}</strong><small>{note}</small></li>
        """.format(
            klass="check-ok" if ok else "check-wait",
            label=html_escape(label),
            note=html_escape(note),
        ))
    return '<ul class="alert-checklist">{}</ul>'.format("".join(items))


def operator_status(alert: dict[str, Any]) -> str:
    return str(alert.get("operator_status") or "NEW").upper()


def is_closed_alert(alert: dict[str, Any]) -> bool:
    return operator_status(alert) in CLOSED_OPERATOR_STATUSES


def is_handled_alert(alert: dict[str, Any]) -> bool:
    return operator_status(alert) in HANDLED_OPERATOR_STATUSES


def operator_alert_counts(data: dict[str, Any]) -> dict[str, int]:
    alerts = data.get("active_alerts") if isinstance(data.get("active_alerts"), list) else []
    pending_alerts = [alert for alert in alerts if isinstance(alert, dict) and not is_handled_alert(alert)]
    handled_alerts = [alert for alert in alerts if isinstance(alert, dict) and is_handled_alert(alert)]
    return {
        "open": len(pending_alerts),
        "risk": sum(1 for alert in pending_alerts if str(alert.get("severity") or "").upper() == "RISK"),
        "watch": sum(1 for alert in pending_alerts if str(alert.get("severity") or "").upper() == "WATCH"),
        "action": sum(1 for alert in pending_alerts if str(alert.get("severity") or "").upper() == "ACTION"),
        "closed": len(handled_alerts),
    }


def operator_state_message(data: dict[str, Any]) -> str:
    counts = operator_alert_counts(data)
    account = data.get("account_alias") or data.get("account_scope") or "unknown"
    return (
        "Estado actualizado desde produccion: {status} | GPT ve cuenta={account} | "
        "pendientes={open} ({risk} riesgo, {watch} watch, {action} action) | cerradas={closed}."
    ).format(
        status=data.get("status") or "OK",
        account=account,
        open=counts["open"],
        risk=counts["risk"],
        watch=counts["watch"],
        action=counts["action"],
        closed=counts["closed"],
    )


def render_alert_card(alert: dict[str, Any], readonly: bool = False, account_capacity: dict[str, Any] | None = None) -> str:
    account_capacity = account_capacity if isinstance(account_capacity, dict) else {}
    status = operator_status(alert)
    actions_html = ""
    if not readonly:
        actions_html = """
              <form method="post" action="/operator-event" class="alert-actions" data-busy="Registrando evento de operador" data-busy-detail="Guardando revision en produccion y releyendo alertas actualizadas.">
                <input name="alert_id" value="{alert_id}" type="hidden">
                <input name="ticker" value="{ticker}" type="hidden">
                <input name="strategy" value="{strategy}" type="hidden">
                <input name="state" value="{state}" type="hidden">
                <label>Nota/razon</label>
                <input name="reason" placeholder="Ej. revisar tamano, descartar por capital, mantener watch">
                <small>Opcional para Ack/Review/Watch/Close. Requerida para Reject y Journal.</small>
                <div class="actions">
                  <button name="action" value="ACK_ALERT">Visto</button>
                  <button name="action" value="MARK_REVIEWING">Revisando</button>
                  <button name="action" value="MARK_WATCHLIST">Watch</button>
                  <button name="action" value="REJECT_SETUP">Rechazar</button>
                  <button name="action" value="CLOSE_ALERT">Cerrar</button>
                </div>
              </form>
        """.format(
            alert_id=html_escape(alert.get("alert_id") or ""),
            ticker=html_escape(alert.get("ticker") or "UNKNOWN"),
            strategy=html_escape(alert.get("strategy") or ""),
            state=html_escape(alert.get("state") or "UNKNOWN"),
        )
    return """
            <article class="alert-card severity-{severity} status-{status_class}{closed_class}">
              <div class="alert-title"><strong>{ticker}</strong><em>{status}</em></div>
              <span>{date_label}</span>
              <span>{strategy} | {severity_label} | {state}</span>
              <div class="contract-line">{contract}</div>
              <div class="economics-line">{economics}</div>
              <div class="capacity-line">{capacity}</div>
              <div class="why-line">{why}</div>
              {checklist}
              <div class="review-line">{guidance}</div>
              <small>blocker: {blocker} | status: {status}</small>
              {actions}
            </article>
            """.format(
        severity=html_escape(str(alert.get("severity") or "UNKNOWN").lower()),
        status_class=html_escape(status.lower().replace("_", "-")),
        closed_class=" closed-alert" if readonly else "",
        ticker=html_escape(alert.get("ticker") or "UNKNOWN"),
        status=html_escape(status),
        date_label=html_escape(alert_date_label(alert)),
        severity_label=html_escape(alert.get("severity") or "UNKNOWN"),
        state=html_escape(alert.get("state") or "UNKNOWN"),
        strategy=html_escape(alert.get("strategy") or ""),
        contract=html_escape(render_alert_contract(alert)),
        economics=render_alert_economics(alert),
        capacity=render_alert_capacity(alert, account_capacity),
        why=html_escape(alert_reason_plain(alert)),
        checklist=render_alert_checklist(alert, account_capacity),
        guidance=html_escape(alert_review_guidance(alert)),
        blocker=html_escape(alert.get("main_blocker") or "NONE"),
        actions=actions_html,
    )


def render_operator_alerts(operator_payload: dict[str, Any], snapshot: dict[str, Any] | None = None) -> str:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
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
    account_capacity = console_account_capacity(operator_payload, snapshot)
    pending_alerts = [alert for alert in alerts if not is_handled_alert(alert)]
    handled_alerts = [alert for alert in alerts if is_handled_alert(alert)]
    if not pending_alerts:
        alert_html = '<p class="empty">Sin alertas pendientes de primera revision en el payload V32 actual.</p>'
    else:
        alert_html = "".join(render_alert_card(alert, account_capacity=account_capacity) for alert in pending_alerts[:12])
    closed_html = ""
    if handled_alerts:
        closed_html = """
        <details class="reviewed-alerts">
          <summary>{count} alerta(s) ya revisada(s), en seguimiento o cerrada(s)</summary>
          <div class="alert-grid">{alerts}</div>
        </details>
        """.format(
            count=html_escape(len(handled_alerts)),
            alerts="".join(render_alert_card(alert, readonly=True, account_capacity=account_capacity) for alert in handled_alerts[:12]),
        )
    action = next_actions[0] if next_actions else {}
    local_counts = {
        "action": sum(1 for alert in pending_alerts if str(alert.get("severity") or "").upper() == "ACTION"),
        "risk": sum(1 for alert in pending_alerts if str(alert.get("severity") or "").upper() == "RISK"),
        "watch": sum(1 for alert in pending_alerts if str(alert.get("severity") or "").upper() == "WATCH"),
        "closed": len(handled_alerts),
    }
    next_action = (
        "Pendientes de primera revision: {risk} riesgo, {watch} watch, {action} action. Ya atendidas: {closed}. Siguiente: {label}."
    ).format(
        risk=local_counts["risk"],
        watch=local_counts["watch"],
        action=local_counts["action"],
        closed=local_counts["closed"],
        label=action.get("label") or "Sin accion inmediata",
    )
    return """
    <section class="panel">
      <div class="section-head">
        <h2>Alertas V32</h2>
        <p>{next_action}</p>
      </div>
      <div class="alert-grid">{alerts}</div>
      {closed_alerts}
    </section>
    """.format(
        next_action=html_escape(next_action),
        alerts=alert_html,
        closed_alerts=closed_html,
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
                <p class="muted">Usar cuenta publica este scope para GPT; Refresh IBKR solo si necesitas datos frescos del broker.</p>
              </div>
              <div class="actions">
                <form method="post" action="/select" data-busy="Publicando cuenta para GPT" data-busy-detail="La cuenta se selecciona localmente y se abre un trabajo RUNNING/DONE para verificar produccion."><input name="alias" value="{alias}" type="hidden"><button>Usar cuenta</button></form>
                <form method="post" action="/account-capacity" data-busy="Leyendo capacidad IBKR" data-busy-detail="Lee solo AccountSummary de la cuenta seleccionada y publica margen/capital disponible."><input name="alias" value="{alias}" type="hidden"><button>Refresh cuenta</button></form>
                <form method="post" action="/bridge" data-busy="Refresh IBKR en curso" data-busy-detail="Conecta con IBKR para traer datos frescos. Puede tardar y no autoriza ordenes."><input name="alias" value="{alias}" type="hidden"><button>Refresh IBKR</button></form>
                <form method="post" action="/daily-open" data-busy="Daily open en curso" data-busy-detail="Ejecutando checklist local de apertura."><input name="alias" value="{alias}" type="hidden"><button>Daily open</button></form>
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
        verification_html = ""
        if "remote_verification_ok" in result:
            counts = result.get("remote_verification_counts") if isinstance(result.get("remote_verification_counts"), dict) else {}
            verification_html = """
            <p><strong>Verificacion GPT:</strong> {ok} | status={status} | cuenta={account} | pendientes={open} | cerradas={closed}</p>
            """.format(
                ok="ok" if result.get("remote_verification_ok") else "fallo",
                status=html_escape(result.get("remote_verification_status") or "UNKNOWN"),
                account=html_escape(result.get("remote_verification_account") or "unknown"),
                open=html_escape(counts.get("open", "unknown")),
                closed=html_escape(counts.get("closed", "unknown")),
            )
        result_html = """
        {diagnostic}
        {verification}
        <p><strong>Resultado:</strong> returncode={returncode}</p>
        <pre>{stdout}{stderr}</pre>
        """.format(
            diagnostic=diagnostic,
            verification=verification_html,
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
      <p><a class="tile inline-link" href="/console">Volver a consola <span>Solo relee la pantalla local; no lanza otro trabajo</span></a></p>
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
    prefer_cache = True
    data = load_profiles()
    profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    active = active_profile()
    snapshot = latest_master_snapshot()
    operator_payload = console_operator_payload(prefer_cache=prefer_cache)
    reports = console_reports()
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
          h1 {{ font-size:3.4rem; line-height:.92; margin:0 0 12px; letter-spacing:0; }}
          h2 {{ margin:0 0 12px; }}
          h3 {{ margin:0; }}
          .lede {{ color:var(--muted); max-width:720px; font-size:1.08rem; }}
          .notice,.panel,.card {{ border:1px solid var(--line); background:rgba(255,250,240,.82); border-radius:22px; box-shadow:0 18px 50px rgba(72,52,20,.08); }}
          .notice {{ padding:14px 18px; margin:22px 0; }}
          .today-panel {{ border-color:#bfd7ff; background:#f7fbff; }}
          .today-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; }}
          .control-strip {{ display:grid; grid-template-columns:1.15fr 1.35fr 1fr; gap:14px; align-items:center; border:1px solid var(--line); border-radius:22px; padding:14px 16px; margin-bottom:18px; background:#fffdf6; box-shadow:0 18px 50px rgba(72,52,20,.08); }}
          .signal {{ display:flex; align-items:center; gap:12px; }}
          .signal strong,.signal small,.thinking-now strong,.thinking-now small {{ display:block; }}
          .signal small,.thinking-now small {{ color:var(--muted); margin-top:3px; }}
          .signal-dot {{ width:18px; height:18px; border-radius:999px; flex:0 0 auto; box-shadow:0 0 0 6px rgba(0,0,0,.04); }}
          .health-green .signal-dot {{ background:#16a34a; box-shadow:0 0 0 6px rgba(22,163,74,.14); }}
          .health-amber .signal-dot {{ background:#d97706; box-shadow:0 0 0 6px rgba(217,119,6,.16); }}
          .health-red .signal-dot {{ background:#b42318; box-shadow:0 0 0 6px rgba(180,35,24,.14); }}
          .control-facts {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
          .control-facts span {{ border:1px solid var(--line); border-radius:999px; background:#fffaf0; padding:7px 10px; font-size:.9rem; color:var(--muted); font-weight:800; }}
          .thinking-now {{ border-left:1px solid var(--line); padding-left:14px; }}
          .hero-panel {{ display:grid; grid-template-columns:1.1fr .9fr; gap:24px; align-items:end; padding:28px; }}
          .eyebrow {{ text-transform:uppercase; letter-spacing:.16em; color:var(--accent); font-weight:800; font-size:.78rem; margin:0 0 12px; }}
          .context-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
          .capacity-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; }}
          .metric {{ background:#fffdf6; border:1px solid var(--line); border-radius:18px; padding:14px; }}
          .metric span,.metric small {{ display:block; color:var(--muted); }}
          .metric strong {{ display:block; font-size:1.45rem; margin:4px 0; }}
          .hero-actions {{ grid-column:1 / -1; display:flex; flex-wrap:wrap; align-items:center; gap:10px; border-top:1px solid var(--line); padding-top:14px; }}
          .hero-actions span {{ color:var(--muted); font-size:.92rem; }}
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
          .module-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; }}
          .module-card {{ display:flex; gap:11px; align-items:flex-start; border:1px solid var(--line); background:#fffdf6; border-radius:16px; padding:12px; }}
          .module-card strong,.module-card span,.module-card small {{ display:block; }}
          .module-card span {{ color:var(--ink); margin-top:2px; }}
          .module-card small {{ color:var(--muted); margin-top:3px; }}
          .module-dot {{ width:12px; height:12px; border-radius:999px; margin-top:4px; flex:0 0 auto; background:#94a3b8; box-shadow:0 0 0 5px rgba(148,163,184,.15); }}
          .module-green .module-dot,.timeline-green > span,.check-ok > span {{ background:#16a34a; box-shadow:0 0 0 5px rgba(22,163,74,.14); }}
          .module-amber .module-dot,.timeline-amber > span,.check-wait > span {{ background:#d97706; box-shadow:0 0 0 5px rgba(217,119,6,.16); }}
          .module-red .module-dot,.timeline-red > span {{ background:#b42318; box-shadow:0 0 0 5px rgba(180,35,24,.14); }}
          .timeline {{ list-style:none; padding:0; margin:14px 0 0; display:grid; gap:10px; }}
          .timeline li {{ display:flex; gap:12px; align-items:flex-start; border:1px solid var(--line); border-radius:16px; background:#fffdf6; padding:12px; }}
          .timeline li > span {{ width:12px; height:12px; border-radius:999px; margin-top:4px; flex:0 0 auto; background:#94a3b8; }}
          .timeline strong,.timeline small {{ display:block; }}
          .timeline small {{ color:var(--muted); margin-top:3px; }}
          .market-panel {{ border-color:#bfd7ff; background:#f5f9ff; }}
          .diagnostic-panel {{ border-color:#badbcc; background:#f7fff8; }}
          .process-panel {{ border-color:#d97706; background:#fff8e7; }}
          .process-list {{ display:grid; gap:10px; margin-top:12px; }}
          .process-row {{ display:flex; align-items:center; gap:12px; border:1px solid #efc99d; border-radius:16px; background:#fffdf6; padding:12px; color:var(--ink); text-decoration:none; }}
          .process-row strong,.process-row small {{ display:block; }}
          .process-row small {{ color:var(--muted); }}
          .process-pulse {{ width:12px; height:12px; border-radius:999px; background:#d97706; box-shadow:0 0 0 6px rgba(217,119,6,.16); animation:pulse 1.2s infinite ease-in-out; }}
          @keyframes pulse {{ 0%,100% {{ transform:scale(.86); opacity:.72; }} 50% {{ transform:scale(1.12); opacity:1; }} }}
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
          .alert-title {{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }}
          .alert-title em {{ font-style:normal; border-radius:999px; padding:5px 8px; background:#e8efe7; color:#1d6b4f; font-size:.78rem; font-weight:900; white-space:nowrap; }}
          .status-new .alert-title em {{ background:#fff4d6; color:#9f4b1b; }}
          .status-reviewing .alert-title em,.status-watchlist .alert-title em {{ background:#e8f1ff; color:#174ea6; }}
          .status-rejected .alert-title em,.status-risk-blocked .alert-title em {{ background:#fff1ef; color:var(--risk); }}
          .status-closed .alert-title em,.status-acknowledged .alert-title em,.status-approved-for-manual-review .alert-title em,.status-approved-for-manual-trade .alert-title em {{ background:#eef8ef; color:#1d6b4f; }}
          .contract-line,.review-line,.economics-line,.capacity-line,.why-line {{ margin-top:8px; border:1px solid var(--line); border-radius:12px; padding:8px 10px; background:#fffaf0; font-size:.92rem; line-height:1.35; }}
          .contract-line {{ font-weight:800; color:var(--ink); }}
          .economics-line {{ color:#1d6b4f; background:#f1fbf4; border-color:#badbcc; font-weight:800; }}
          .capacity-line {{ color:#174ea6; background:#eef5ff; border-color:#bfd7ff; font-weight:800; }}
          .why-line {{ background:#f7fbff; border-color:#bfd7ff; color:#174ea6; font-weight:800; }}
          .review-line {{ color:var(--warn); background:#fff7e8; }}
          .alert-checklist {{ list-style:none; padding:0; margin:10px 0 0; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }}
          .alert-checklist li {{ display:grid; grid-template-columns:14px 1fr; column-gap:7px; align-items:start; border:1px solid var(--line); border-radius:11px; padding:7px; background:white; }}
          .alert-checklist li > span {{ width:9px; height:9px; border-radius:999px; margin-top:4px; }}
          .alert-checklist strong {{ font-size:.82rem; line-height:1.1; }}
          .alert-checklist small {{ grid-column:2; font-size:.78rem; margin-top:2px; }}
          .closed-alert {{ opacity:.76; border-style:dashed; }}
          .reviewed-alerts {{ margin-top:14px; }}
          .reviewed-alerts summary {{ cursor:pointer; font-weight:800; color:var(--muted); }}
          .reviewed-alerts .alert-grid {{ margin-top:12px; }}
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
          @media (max-width:900px) {{ .control-strip {{ grid-template-columns:1fr; }} .thinking-now {{ border-left:0; padding-left:0; border-top:1px solid var(--line); padding-top:10px; }} }}
          @media (max-width:820px) {{ h1 {{ font-size:2.4rem; }} .hero-panel {{ grid-template-columns:1fr; }} .context-grid {{ grid-template-columns:1fr; }} .control-facts {{ grid-template-columns:1fr; }} .alert-checklist {{ grid-template-columns:1fr; }} .card {{ align-items:flex-start; flex-direction:column; }} .actions {{ justify-content:flex-start; }} }}
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
          {health}
          {active_process}
          {today}
          {modules}
          {market_mode}
          {timeline}
          {context}
          {capacity}
          {diagnostic}
          {message}
          {job_panel}
          <section class="panel">
            <div class="section-head">
              <h2>Cuentas</h2>
              <p>Escoge la cuenta que quieres revisar. <strong>Usar cuenta</strong> publica contexto para GPT; <strong>Refresh IBKR</strong> solo trae datos frescos del broker.</p>
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
              form.addEventListener("submit", (event) => {{
                const submitter = event.submitter;
                const actionValue = submitter && submitter.name === "action" ? submitter.value : "";
                const reasonInput = form.querySelector('input[name="reason"]');
                const reasonRequired = ["REJECT_SETUP", "APPROVE_MANUAL_REVIEW", "JOURNAL_NOTE"].includes(actionValue);
                if (reasonRequired && reasonInput && !reasonInput.value.trim()) {{
                  event.preventDefault();
                  reasonInput.setCustomValidity("Esta accion requiere nota/razon.");
                  reasonInput.reportValidity();
                  setTimeout(() => reasonInput.setCustomValidity(""), 1200);
                  return;
                }}
                if (actionValue && !form.querySelector('input[name="action"][type="hidden"]')) {{
                  const hiddenAction = document.createElement("input");
                  hiddenAction.type = "hidden";
                  hiddenAction.name = "action";
                  hiddenAction.value = actionValue;
                  form.appendChild(hiddenAction);
                }}
                const label = form.dataset.busy || "Procesando accion local";
                title.textContent = label;
                detail.textContent = form.dataset.busyDetail || "Solicitud enviada. Veras confirmacion o un panel RUNNING/DONE en unos segundos.";
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
        health=render_console_health(active, snapshot, operator_payload),
        active_process=render_active_process_panel(),
        today=render_today_panel(active, snapshot, operator_payload, reports),
        modules=render_module_health(active, snapshot, operator_payload, reports),
        market_mode=render_market_mode_panel(operator_payload, reports),
        timeline=render_timeline(snapshot, operator_payload, reports),
        capacity=render_account_capacity_panel(operator_payload, snapshot),
        diagnostic=render_diagnostic_panel(active, reports),
        message=('<div class="notice">' + html_escape(message) + "</div>") if message else "",
        refresh_meta=refresh_meta,
        job_panel=job_panel,
        profile_cards=render_profile_cards(profiles, active),
        alerts=render_operator_alerts(operator_payload, snapshot),
        actions=render_console_actions(operator_payload),
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
                job_id = start_web_job(alias, account_publish_command(), "Publicar cuenta a GPT")
                self.send_html(
                    "Cuenta seleccionada localmente: alias={alias}. Publicando contexto para GPT; espera DONE y revisa Verificacion GPT.".format(
                        alias=normalize_alias(alias)
                    ),
                    job_id=job_id,
                )
            elif self.path == "/account-capacity":
                job_id = start_web_job(alias, account_capacity_command(), "Refresh capacidad IBKR")
                self.send_html("Refresh de cuenta iniciado. Lee AccountSummary y publica capital/margen disponible.", job_id=job_id)
            elif self.path == "/bridge":
                job_id = start_web_job(alias, console_bridge_command(), "Refresh IBKR")
                self.send_html("Refresh IBKR iniciado. Esto lee broker/opciones; la consola mostrara RUNNING hasta que termine.", job_id=job_id)
            elif self.path == "/daily-open":
                job_id = start_web_job(alias, [sys.executable, "scripts/daily_open_checklist.py", "--refresh"], "Daily open checklist")
                self.send_html("Daily open iniciado. La consola mostrara RUNNING hasta que termine.", job_id=job_id)
            elif self.path == "/diagnostic":
                job_id = start_web_job(alias, console_diagnostic_command(), "Diagnostico completo")
                self.send_html("Diagnostico completo iniciado. Revisa RUNNING/DONE en esta misma consola.", job_id=job_id)
            elif self.path == "/refresh-remote":
                result = fetch_remote_json(
                    "/gpt_v32_operator_today?limit=12",
                    timeout=REMOTE_VERIFY_TIMEOUT_SECONDS,
                    prefer_cache=False,
                )
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                if result.get("ok"):
                    self.send_html(operator_state_message(data))
                else:
                    self.send_html(
                        "No pude actualizar estado remoto: {}".format(result.get("error") or "unknown"),
                        status=400,
                    )
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
                if result.get("ok"):
                    record_local_operator_event(payload, result)
                    fetch_remote_json(
                        "/gpt_v32_operator_today?limit=12",
                        timeout=REMOTE_VERIFY_TIMEOUT_SECONDS,
                        prefer_cache=False,
                    )
                operator_status_label = OPERATOR_STATUS_BY_ACTION.get(action, action or "UNKNOWN")
                ticker_label = (params.get("ticker") or ["UNKNOWN"])[0] or "UNKNOWN"
                message = (
                    "{ticker} marcado como {status}. Queda registrado para seguimiento/backtesting; no autoriza ordenes.".format(
                        ticker=ticker_label,
                        status=operator_status_label,
                    )
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

    publish_context = sub.add_parser("publish-context", help="Publish the currently active account context for GPT visibility.")
    publish_context.set_defaults(func=cmd_publish_context)

    refresh_capacity = sub.add_parser("refresh-account-capacity", help="Read sanitized AccountSummary for the selected account and optionally publish it.")
    refresh_capacity.add_argument("--host", default=os.getenv("IBKR_HOST", "127.0.0.1"))
    refresh_capacity.add_argument("--port", type=int, default=int(os.getenv("IBKR_PORT", "7496")))
    refresh_capacity.add_argument("--client-id", type=int, default=int(os.getenv("IBKR_CLIENT_ID", "74")))
    refresh_capacity.add_argument("--timeout", type=float, default=12.0)
    refresh_capacity.add_argument("--publish", action="store_true")
    refresh_capacity.set_defaults(func=cmd_refresh_account_capacity)

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
