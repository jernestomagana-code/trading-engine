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
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import alert_lifecycle as shared_alert_lifecycle
import alert_effectiveness as shared_alert_effectiveness
import broker_control_tower as shared_control_tower
import coberturas_engine as shared_coberturas_engine
import decision_outcome_intelligence as shared_decision_outcomes
import executive_reporting as shared_executive_reporting
import gamma_context_store as shared_gamma_context_store
import portfolio_risk_engine as shared_portfolio_risk
import portfolio_risk_operations as shared_risk_operations
import portfolio_stress_engine as shared_portfolio_stress
import portfolio_factor_engine as shared_portfolio_factors
import portfolio_rebalance_engine as shared_portfolio_rebalance
import portfolio_whatif_engine as shared_portfolio_whatif
import preventive_maintenance as shared_preventive_maintenance
import position_management as shared_position_management
import position_management_journal as shared_position_management_journal
import position_context_store as shared_position_context_store
import position_state_alerts as shared_position_state_alerts

RUNTIME = ROOT / "runtime"
PROFILES_PATH = RUNTIME / "ibkr_account_profiles.local.json"
ACTIVE_PATH = RUNTIME / "ibkr_account_active_profile.json"
WEB_LAST_RESULT_PATH = RUNTIME / "ibkr_account_profile_web_last_result.json"
REMOTE_CACHE_PATH = RUNTIME / "stock_ultimus_console_remote_cache.json"
OPERATOR_EVENTS_PATH = RUNTIME / "v32_operator_events.json"
POSITION_MANAGEMENT_JOURNAL_PATH = RUNTIME / "active_position_management_journal.json"
POSITION_CONTEXTS_PATH = RUNTIME / "active_position_contexts.json"
GAMMA_CONTEXTS_PATH = RUNTIME / "gamma_contexts.json"
POSITION_STATE_ALERTS_PATH = RUNTIME / "active_position_state_alerts.json"
ACCOUNT_CAPACITY_PATH = RUNTIME / "ibkr_account_capacity_latest.json"
CONTROL_TOWER_PATH = RUNTIME / "broker_control_tower_latest.json"
PORTFOLIO_RISK_PATH = RUNTIME / "portfolio_risk_latest.json"
PORTFOLIO_RISK_HISTORY_PATH = RUNTIME / "portfolio_risk_history.json"
PORTFOLIO_RISK_POLICY_PATH = ROOT / "config" / "portfolio_risk_policy.json"
PORTFOLIO_RISK_ACTIONS_PATH = RUNTIME / "portfolio_risk_actions.json"
PORTFOLIO_RISK_OUTBOX_PATH = RUNTIME / "portfolio_risk_outbox.json"
PORTFOLIO_RISK_OPERATIONS_STATUS_PATH = RUNTIME / "portfolio_risk_operations_status.json"
PORTFOLIO_RISK_DIGEST_PATH = RUNTIME / "portfolio_risk_digest_latest.json"
PORTFOLIO_RISK_OBSERVATION_PATH = RUNTIME / "portfolio_risk_observation.json"
PORTFOLIO_STRESS_PATH = RUNTIME / "portfolio_stress_latest.json"
PORTFOLIO_STRESS_POLICY_PATH = ROOT / "config" / "portfolio_stress_policy.json"
PORTFOLIO_FACTOR_PATH = RUNTIME / "portfolio_factor_latest.json"
PORTFOLIO_FACTOR_POLICY_PATH = ROOT / "config" / "portfolio_factor_policy.json"
PORTFOLIO_REBALANCE_PATH = RUNTIME / "portfolio_rebalance_latest.json"
PORTFOLIO_REBALANCE_POLICY_PATH = ROOT / "config" / "portfolio_rebalance_policy.json"
PORTFOLIO_WHATIF_PATH = RUNTIME / "portfolio_rebalance_whatif_latest.json"
PORTFOLIO_WHATIF_POLICY_PATH = ROOT / "config" / "portfolio_whatif_policy.json"
DECISION_JOURNAL_PATH = RUNTIME / "v32_decision_journal.json"
OUTCOME_JOURNAL_PATH = RUNTIME / "v32_outcomes_journal.json"
DAILY_OUTCOME_EVALUATION_PATH = RUNTIME / "daily_outcome_evaluation_latest.json"
EXECUTIVE_DAILY_PATH = RUNTIME / "executive_report_daily_latest.json"
EXECUTIVE_WEEKLY_PATH = RUNTIME / "executive_report_weekly_latest.json"
PREVENTIVE_MAINTENANCE_PATH = RUNTIME / "preventive_maintenance_latest.json"
IBKR_BRIDGE_HEALTH_PATH = RUNTIME / "ibkr_bridge_health_latest.json"
CONSOLE_BRIDGE_SESSION_PATH = RUNTIME / "stock_ultimus_console_bridge_latest.json"
TRADINGVIEW_BUNDLE_HEALTH_PATH = RUNTIME / "tradingview_alert_bundle_health.json"
MARKET_OPEN_READINESS_PATH = RUNTIME / "market_open_readiness_latest.json"
POST_OPEN_MONITOR_PATH = RUNTIME / "post_open_monitor_latest.json"
OPERATOR_NOTIFY_PATH = RUNTIME / "v32_operator_notify_latest.json"
OPERATIONAL_EDGE_PATH = RUNTIME / "v32_operational_edge_latest.json"
DAILY_OPEN_CHECKLIST_PATH = RUNTIME / "daily_open_checklist_latest.json"
OPERATOR_GUIDE_PATH = ROOT / "docs" / "guia-consola-stock-ultimus.md"
KEYCHAIN_SERVICE_PREFIX = "stock-ultimus-ibkr-account-"
READ_KEYCHAIN_SERVICES = ("stock-ultimus-read-access-token", "stock-ultimus-read-access")
SNAPSHOT_INGEST_KEYCHAIN_SERVICES = ("stock-ultimus-snapshot-ingest", "stock-ultimus-snapshot-ingest-token")
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"
FAST_KEYCHAIN_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_KEYCHAIN_TIMEOUT_SECONDS", "2"))
REMOTE_READ_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_REMOTE_TIMEOUT_SECONDS", "5"))
REMOTE_VERIFY_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_REMOTE_VERIFY_TIMEOUT_SECONDS", "20"))
REMOTE_CACHE_MAX_AGE_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_REMOTE_CACHE_MAX_AGE_SECONDS", "900"))
LOCAL_JOB_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_JOB_TIMEOUT_SECONDS", "90"))
CONSOLE_DAILY_OPEN_TIMEOUT_SECONDS = float(os.getenv("STOCK_ULTIMUS_CONSOLE_DAILY_OPEN_TIMEOUT_SECONDS", "720"))
CONSOLE_BRIDGE_TIMEOUT_SECONDS = int(float(os.getenv("STOCK_ULTIMUS_CONSOLE_BRIDGE_TIMEOUT_SECONDS", "75")))
CONSOLE_HISTORICAL_TIMEOUT_SECONDS = int(float(os.getenv("STOCK_ULTIMUS_CONSOLE_HISTORICAL_TIMEOUT_SECONDS", "4")))
CONSOLE_IBKR_CLIENT_ID = int(float(os.getenv("STOCK_ULTIMUS_CONSOLE_IBKR_CLIENT_ID", "75")))
CONSOLE_WHATIF_IBKR_CLIENT_ID = int(float(os.getenv("STOCK_ULTIMUS_WHATIF_IBKR_CLIENT_ID", "87")))
CONSOLE_WHATIF_IBKR_PORT = int(float(os.getenv("STOCK_ULTIMUS_WHATIF_IBKR_PORT", os.getenv("IBKR_PORT", "7496"))))
CONSOLE_OPTION_SYMBOLS = os.getenv("STOCK_ULTIMUS_CONSOLE_OPTION_SYMBOLS", "QQQ,SPY,AAPL,NVDA,TSLA,RSP")
CONSOLE_MAX_OPTIONS_PER_SYMBOL = os.getenv("STOCK_ULTIMUS_CONSOLE_MAX_OPTIONS_PER_SYMBOL", "1")
CONSOLE_COBERTURAS_RSP_OPTION_SYMBOLS = os.getenv("STOCK_ULTIMUS_COBERTURAS_RSP_OPTION_SYMBOLS", "RSP")
CONSOLE_COBERTURAS_RSP_ACCOUNT_ALIAS = os.getenv("STOCK_ULTIMUS_RSP_ACCOUNT_ALIAS", "retiro").strip().lower()
CONSOLE_COBERTURAS_RSP_MAX_OPTIONS_PER_SYMBOL = os.getenv("STOCK_ULTIMUS_COBERTURAS_RSP_MAX_OPTIONS_PER_SYMBOL", "12")
CONSOLE_COBERTURAS_RSP_TARGET_DTE_MIN = os.getenv("STOCK_ULTIMUS_COBERTURAS_RSP_TARGET_DTE_MIN", "7")
CONSOLE_COBERTURAS_RSP_TARGET_DTE_MAX = os.getenv("STOCK_ULTIMUS_COBERTURAS_RSP_TARGET_DTE_MAX", "14")
CONSOLE_COBERTURAS_RSP_TARGET_DTE_IDEAL = os.getenv("STOCK_ULTIMUS_COBERTURAS_RSP_TARGET_DTE_IDEAL", "8")
CONSOLE_COBERTURAS_RSP_BRIDGE_TIMEOUT_SECONDS = int(float(os.getenv("STOCK_ULTIMUS_COBERTURAS_RSP_BRIDGE_TIMEOUT_SECONDS", "90")))
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
    "IBKR_NOT_APPLIED",
    "MISSED",
}
HANDLED_OPERATOR_STATUSES = CLOSED_OPERATOR_STATUSES | {
    "ACKNOWLEDGED",
    "REVIEWING",
    "WATCHLIST",
    "NOTE_RECORDED",
    "PAPER_TRACKED",
    "IBKR_APPLIED",
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
    "MARK_PAPER_TRACKED": "PAPER_TRACKED",
    "MARK_IBKR_APPLIED": "IBKR_APPLIED",
    "MARK_IBKR_NOT_APPLIED": "IBKR_NOT_APPLIED",
    "MARK_MISSED": "MISSED",
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
    try:
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
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_keychain_value_any_account(service: str, timeout: float = FAST_KEYCHAIN_TIMEOUT_SECONDS) -> str:
    try:
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
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
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


def resolve_job_alias(alias: str) -> str:
    requested = str(alias or "").strip()
    if requested:
        return normalize_alias(requested)
    active_alias = str(active_profile().get("account_alias") or "").strip()
    if active_alias:
        return normalize_alias(active_alias)
    raise ValueError("Selecciona una cuenta en la consola antes de correr este proceso.")


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


def bridge_report_for_command(command: list[str]) -> Path:
    try:
        if "--json-out" in command:
            return Path(command[command.index("--json-out") + 1])
    except Exception:
        pass
    return RUNTIME / "stock_ultimus_console_bridge_latest.json"


def enrich_console_bridge_output(text: str, command: list[str]) -> str:
    bridge_report = bridge_report_for_command(command)
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
    # A strategy-specific RSP refresh must not replace the operator's general
    # active account. It runs under its dedicated profile only for that job.
    if "--coberturas-rsp-weekly" not in command:
        write_active_profile(profile)
    env = environment_for(profile)
    if is_daily_open_command(command):
        env.setdefault("IBKR_CLIENT_ID", str(CONSOLE_IBKR_CLIENT_ID))
    if any(str(part).endswith("run_market_bridge_session.py") for part in command):
        is_coberturas_rsp = "--coberturas-rsp-weekly" in command
        env.setdefault("IBKR_OPTION_SYMBOLS", CONSOLE_COBERTURAS_RSP_OPTION_SYMBOLS if is_coberturas_rsp else CONSOLE_OPTION_SYMBOLS)
        env.setdefault("IBKR_WATCHLIST", CONSOLE_COBERTURAS_RSP_OPTION_SYMBOLS if is_coberturas_rsp else CONSOLE_OPTION_SYMBOLS)
        env.setdefault("IBKR_MAX_OPTIONS_PER_SYMBOL", CONSOLE_COBERTURAS_RSP_MAX_OPTIONS_PER_SYMBOL if is_coberturas_rsp else CONSOLE_MAX_OPTIONS_PER_SYMBOL)
        if is_coberturas_rsp:
            env.setdefault("COBERTURAS_RSP_WEEKLY", "1")
            env.setdefault("IBKR_MAX_OPTION_SYMBOLS_PER_RUN", "1")
            env.setdefault("IBKR_MAX_TOTAL_OPTION_CONTRACTS_PER_RUN", CONSOLE_COBERTURAS_RSP_MAX_OPTIONS_PER_SYMBOL)
            env.setdefault("IBKR_TARGET_DTE_MIN", CONSOLE_COBERTURAS_RSP_TARGET_DTE_MIN)
            env.setdefault("IBKR_TARGET_DTE_MAX", CONSOLE_COBERTURAS_RSP_TARGET_DTE_MAX)
            env.setdefault("IBKR_TARGET_DTE_IDEAL", CONSOLE_COBERTURAS_RSP_TARGET_DTE_IDEAL)
            env.setdefault("IBKR_DYNAMIC_OPTION_UNIVERSE_ENABLED", "0")
            env.setdefault("IBKR_INCLUDE_RUNTIME_TECHNICAL_OPTION_CANDIDATES", "0")
        env.setdefault("IBKR_OPTION_MARKET_DATA_TYPE_SEQUENCE", CONSOLE_OPTION_MARKET_DATA_TYPES)
        env.setdefault("IBKR_OPTION_MARKET_DATA_WAIT_SECONDS", CONSOLE_OPTION_WAIT_SECONDS)
        env.setdefault("IBKR_OPTION_SNAPSHOT_WAIT_SECONDS", CONSOLE_OPTION_SNAPSHOT_WAIT_SECONDS)
        env.setdefault("IBKR_ENGINE_POST_TIMEOUT_SECONDS", "5")
        env.setdefault("IBKR_POSITION_REQUEST_TIMEOUT_SECONDS", "12")
        env.setdefault("IBKR_STOCK_PRICE_SNAPSHOT_TIMEOUT_SECONDS", "8")
        env.setdefault("IBKR_POSITION_PRICE_SNAPSHOT_TIMEOUT_SECONDS", "5")
        env.setdefault("IBKR_OPTION_CONTRACT_MARKET_DATA_TIMEOUT_SECONDS", "10")
    timeout_seconds = command_timeout_seconds(command)
    timed_out = False
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        returncode = int(result.returncode)
        stdout = enrich_console_bridge_output(result.stdout, command) if is_console_bridge_command(command) else result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = process_output_text(exc.stdout)
        stderr = process_output_text(exc.stderr) + f"\nTIMEOUT: comando detenido despues de {timeout_seconds:.0f}s. Revisa TWS/IBKR Gateway y vuelve a intentar."
    payload = {
        "result_version": "ibkr_account_profile_web_result_v1",
        "generated_at": now_iso(),
        "alias": profile["alias"],
        "account_scope": profile["account_scope"],
        "command": command_label(command),
        "returncode": returncode,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
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
    job_alias = resolve_job_alias(alias)
    job_id = uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "job_version": "stock_ultimus_console_job_v1",
        "status": "RUNNING",
        "label": label,
        "alias": job_alias,
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
            result = run_with_profile_capture(job_alias, command)
            returncode = int(result.get("returncode") or 0)
            if returncode == 0:
                if is_main_console_bridge_command(command):
                    latest_run = latest_console_bridge_run()
                    bridge_published = bool(latest_run.get("published"))
                    result["bridge_local_refresh_ok"] = bool(latest_run.get("ok", True))
                    result["bridge_publish_required"] = True
                    result["bridge_published"] = bridge_published
                    result["bridge_session_status"] = latest_run.get("status") or ""
                    if not bridge_published:
                        fallback = publish_account_context_fallback()
                        fallback_ok = bool(fallback.get("ok"))
                        result["account_context_fallback"] = fallback
                        result["bridge_publish_retry_ok"] = fallback_ok
                        result["bridge_published"] = fallback_ok
                        result["operator_status"] = (
                            "BRIDGE_OK_PUBLISH_RETRIED"
                            if fallback_ok
                            else "BRIDGE_OK_PUBLISH_PENDING"
                        )
                        result["partial_refresh_ok"] = fallback_ok
                        result["stdout_tail"] = (
                            str(result.get("stdout_tail") or "")
                            + "\n\n--- V31 publish retry ---\n"
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
                                + "\nPUBLISH RETRY STDERR:\n"
                                + str(fallback.get("stderr_tail") or "")
                            )[-6000:]
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
                result["partial_refresh_ok"] = bool(fallback.get("ok"))
                result["operator_status"] = "PARTIAL_REFRESH_OK" if fallback.get("ok") else "BRIDGE_REFRESH_FAILED"
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
            effective_ok = returncode == 0 or bool(result.get("partial_refresh_ok"))
            if is_main_console_bridge_command(command) and returncode == 0 and result.get("bridge_publish_required"):
                effective_ok = bool(result.get("bridge_published"))
            with WEB_JOBS_LOCK:
                WEB_JOBS[job_id] = {
                    **WEB_JOBS.get(job_id, job),
                    "status": "DONE" if effective_ok else "ERROR",
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


def running_web_job_by_label(label: str) -> dict[str, Any] | None:
    with WEB_JOBS_LOCK:
        for job in WEB_JOBS.values():
            if job.get("label") == label and job.get("status") == "RUNNING":
                return dict(job)
    return None


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


def console_rsp_weekly_bridge_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_market_bridge_session.py",
        "--max-runs",
        "1",
        "--bridge-timeout",
        str(max(45, CONSOLE_COBERTURAS_RSP_BRIDGE_TIMEOUT_SECONDS)),
        "--historical-data-timeout",
        str(max(CONSOLE_HISTORICAL_TIMEOUT_SECONDS, 8)),
        "--ibkr-client-id",
        str(CONSOLE_IBKR_CLIENT_ID),
        "--coberturas-rsp-weekly",
        "--json-out",
        str(RUNTIME / "stock_ultimus_coberturas_rsp_weekly_bridge_latest.json"),
    ]


def console_deep_bridge_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_market_bridge_session.py",
        "--max-runs",
        "1",
        "--bridge-timeout",
        str(max(120, int(LOCAL_JOB_TIMEOUT_SECONDS) * 3)),
        "--historical-data-timeout",
        str(max(CONSOLE_HISTORICAL_TIMEOUT_SECONDS, 8)),
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


def ibkr_quick_check_command() -> list[str]:
    return [
        sys.executable,
        "scripts/ibkr_account_profile.py",
        "refresh-account-capacity",
        "--client-id",
        str(CONSOLE_IBKR_CLIENT_ID),
        "--timeout",
        "12",
    ]


def daily_open_command() -> list[str]:
    return [
        sys.executable,
        "scripts/daily_open_checklist.py",
        "--refresh",
        "--publish",
        "--allow-stale-publish",
        "--soft-exit",
        "--bridge-timeout",
        "240",
        "--rsp-bridge-timeout",
        "120",
        "--capacity-timeout",
        "20",
        "--read-timeout",
        "30",
    ]


def market_open_readiness_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_market_open_readiness.py",
        "--market-closed-ok",
    ]


def post_open_monitor_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_post_open_monitor.py",
        "--watch",
        "--cycles",
        "18",
        "--interval-seconds",
        "300",
    ]


def environment_alerts_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_environment_alerts.py",
        "--notify-watch",
        "--pushover",
    ]


def security_audit_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_security_audit.py",
        "--pushover",
    ]


def dependency_audit_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_dependency_audit.py",
        "--pushover",
    ]


def local_dashboard_command() -> list[str]:
    return [
        sys.executable,
        "scripts/build_local_environment_dashboard.py",
    ]


def v32_pushover_automation_command(mode: str) -> list[str]:
    return [
        sys.executable,
        "scripts/v32_pushover_automation.py",
        "--mode",
        mode,
    ]


def control_tower_refresh_command() -> list[str]:
    return [
        sys.executable,
        "scripts/refresh_multi_account_control_tower.py",
        "--json-out",
        "runtime/broker_control_tower_latest.json",
    ]


def portfolio_risk_refresh_command() -> list[str]:
    return [
        sys.executable,
        "scripts/evaluate_portfolio_risk.py",
        "--json-out",
        "runtime/portfolio_risk_latest.json",
        "--history-out",
        "runtime/portfolio_risk_history.json",
    ]


def portfolio_stress_refresh_command() -> list[str]:
    return [
        sys.executable,
        "scripts/evaluate_portfolio_stress.py",
        "--json-out",
        "runtime/portfolio_stress_latest.json",
    ]


def portfolio_factor_refresh_command() -> list[str]:
    return [
        sys.executable,
        "scripts/evaluate_portfolio_factors.py",
        "--json-out",
        "runtime/portfolio_factor_latest.json",
    ]


def portfolio_rebalance_refresh_command(ticker: str = "", reduction_pct: str = "") -> list[str]:
    command = [
        sys.executable,
        "scripts/evaluate_portfolio_rebalance.py",
        "--json-out",
        "runtime/portfolio_rebalance_latest.json",
    ]
    if ticker:
        command.extend(["--ticker", ticker])
    if reduction_pct:
        command.extend(["--reduction-pct", reduction_pct])
    return command


def portfolio_whatif_refresh_command(candidate_id: str = "") -> list[str]:
    command = [
        sys.executable,
        "scripts/preview_portfolio_rebalance_whatif.py",
        "--json-out",
        "runtime/portfolio_rebalance_whatif_latest.json",
        "--port",
        str(CONSOLE_WHATIF_IBKR_PORT),
        "--client-id",
        str(CONSOLE_WHATIF_IBKR_CLIENT_ID),
    ]
    if candidate_id:
        command.extend(["--candidate-id", candidate_id])
    return command


def daily_outcome_evaluation_command() -> list[str]:
    return [
        sys.executable,
        "scripts/run_daily_outcome_evaluation.py",
        "--json-out",
        "runtime/daily_outcome_evaluation_latest.json",
        "--outcomes-journal",
        "runtime/v32_outcomes_journal.json",
        "--decisions-journal",
        "runtime/v32_decision_journal.json",
    ]


def executive_report_command(period: str) -> list[str]:
    return [sys.executable, "scripts/build_executive_report.py", "--period", period]


def preventive_maintenance_command() -> list[str]:
    return [sys.executable, "scripts/run_preventive_maintenance.py"]


def portfolio_risk_operations_command(
    mode: str = "preflight",
    *,
    refresh_broker: bool = False,
    local_notify: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        "scripts/run_portfolio_risk_operations.py",
        "--mode",
        mode,
    ]
    if refresh_broker:
        command.append("--refresh-broker")
    if local_notify:
        command.append("--local-notify")
    return command


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


def is_main_console_bridge_command(command: list[str]) -> bool:
    return is_console_bridge_command(command) and str(CONSOLE_BRIDGE_SESSION_PATH) in {str(part) for part in command}


def latest_console_bridge_run() -> dict[str, Any]:
    session = load_json_file(CONSOLE_BRIDGE_SESSION_PATH)
    runs = session.get("runs") if isinstance(session.get("runs"), list) else []
    latest = runs[-1] if runs and isinstance(runs[-1], dict) else {}
    return latest if isinstance(latest, dict) else {}


def is_daily_open_command(command: list[str]) -> bool:
    return any(str(part).endswith("daily_open_checklist.py") for part in command)


def command_timeout_seconds(command: list[str]) -> float:
    if is_daily_open_command(command):
        return max(CONSOLE_DAILY_OPEN_TIMEOUT_SECONDS, LOCAL_JOB_TIMEOUT_SECONDS)
    if any(str(part).endswith("run_post_open_monitor.py") for part in command):
        return max(5700.0, LOCAL_JOB_TIMEOUT_SECONDS)
    if any(str(part).endswith(name) for part in command for name in [
        "run_market_open_readiness.py",
        "run_environment_alerts.py",
        "run_security_audit.py",
        "run_dependency_audit.py",
        "build_local_environment_dashboard.py",
        "v32_pushover_automation.py",
    ]):
        return max(180.0, LOCAL_JOB_TIMEOUT_SECONDS)
    if is_console_bridge_command(command) and "--bridge-timeout" in command:
        try:
            bridge_timeout = int(command[command.index("--bridge-timeout") + 1])
        except Exception:
            bridge_timeout = 0
        if bridge_timeout > CONSOLE_BRIDGE_TIMEOUT_SECONDS:
            return max(float(bridge_timeout + 45), LOCAL_JOB_TIMEOUT_SECONDS * 3)
    return LOCAL_JOB_TIMEOUT_SECONDS


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
    env.setdefault("TRADING_ENGINE_PUBLISH_TIMEOUT_SECONDS", "60")
    env.setdefault("TRADING_ENGINE_PUBLISH_RETRIES", "3")
    env.setdefault("TRADING_ENGINE_PUBLISH_RETRY_SLEEP_SECONDS", "4")
    result = subprocess.run(
        [
            sys.executable,
            "tools/publish_v31_snapshot_from_runtime.py",
            "--publish",
            "--allow-stale",
            "--timeout",
            "60",
            "--retries",
            "3",
            "--retry-sleep",
            "4",
        ],
        cwd=str(ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=210,
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
        "account_scope": os.getenv("STOCK_ULTIMUS_ACCOUNT_SCOPE") or active.get("account_scope") or "unknown",
        "account_alias": os.getenv("IBKR_ACCOUNT_ALIAS") or active.get("account_alias") or "unknown",
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
    capacity_path = Path(args.json_out)
    capacity_path.parent.mkdir(parents=True, exist_ok=True)
    capacity_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n")
    result = {
        "account_capacity": context,
        "capacity_file": str(capacity_path.relative_to(ROOT)) if capacity_path.is_relative_to(ROOT) else str(capacity_path),
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
        "ibkr_fill_price": remote_event.get("ibkr_fill_price") or payload.get("ibkr_fill_price") or None,
        "ibkr_fill_quantity": remote_event.get("ibkr_fill_quantity") or payload.get("ibkr_fill_quantity") or None,
        "ibkr_order_id": remote_event.get("ibkr_order_id") or payload.get("ibkr_order_id") or None,
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
    active_alerts = data.get("active_alerts") if isinstance(data.get("active_alerts"), list) else []
    diagnostic_alerts = data.get("diagnostic_alerts") if isinstance(data.get("diagnostic_alerts"), list) else []
    alerts = active_alerts + diagnostic_alerts
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
        alert["ibkr_fill_price"] = event.get("ibkr_fill_price") or alert.get("ibkr_fill_price")
        alert["ibkr_fill_quantity"] = event.get("ibkr_fill_quantity") or alert.get("ibkr_fill_quantity")
        alert["ibkr_order_id"] = event.get("ibkr_order_id") or alert.get("ibkr_order_id")
        alert["local_operator_event_applied"] = True
    data["local_operator_event_count"] = len(latest)
    return operator_payload


def latest_master_snapshot() -> dict[str, Any]:
    candidates = []
    fixed_names = [
        "decision_desk_snapshot.json",
        "v32_ibkr_chain_coverage.json",
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
    rows = []
    for key in ["options_rows", "option_rows", "rows", "top"]:
        if isinstance(data.get(key), list):
            rows = data.get(key)
            break
    health = data.get("health") if isinstance(data.get("health"), dict) else {}
    if not rows and health.get("rows_captured") is not None:
        rows = [{}] * int(health.get("rows_captured") or 0)
    broker_summary = data.get("broker_check_summary") if isinstance(data.get("broker_check_summary"), dict) else {}
    account_context = data.get("account_context") if isinstance(data.get("account_context"), dict) else {}
    scope = data.get("account_scope") or broker_summary.get("account_scope") or account_context.get("account_scope") or ""
    alias = data.get("account_alias") or broker_summary.get("account_alias") or account_context.get("account_alias") or scope
    try:
        path_label = str(path.relative_to(ROOT))
    except ValueError:
        path_label = str(path)
    return {
        "available": True,
        "path": path_label,
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


def timestamp_sort_value(value: Any) -> float:
    dt = parse_iso_datetime(value)
    if not dt:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


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
    cache = load_json_file(REMOTE_CACHE_PATH)
    entries = cache.get("entries") if isinstance(cache.get("entries"), dict) else {}
    entries[path] = {
        "cached_at": now_iso(),
        "result": {
            "ok": True,
            "error": "",
            "token_present": bool(result.get("token_present")),
            "url": result.get("url"),
            "data": result.get("data") if isinstance(result.get("data"), dict) else {},
        },
    }
    payload = {
        "cache_version": "stock_ultimus_console_remote_cache_v2",
        "cached_at": now_iso(),
        "entries": entries,
        "secrets_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    write_json_file(REMOTE_CACHE_PATH, payload)


def read_remote_cache(path: str, live_error: str = "", allow_stale: bool = False) -> dict[str, Any] | None:
    cache = load_json_file(REMOTE_CACHE_PATH)
    if isinstance(cache.get("entries"), dict):
        entry = cache["entries"].get(path) if isinstance(cache["entries"].get(path), dict) else {}
        cached_at = entry.get("cached_at")
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    elif cache.get("path") == path:
        cached_at = cache.get("cached_at")
        result = cache.get("result") if isinstance(cache.get("result"), dict) else {}
    else:
        return None
    age_seconds = cache_age_seconds(cached_at)
    if age_seconds is None:
        return None
    if not allow_stale and age_seconds > REMOTE_CACHE_MAX_AGE_SECONDS:
        return None
    if not result.get("ok"):
        return None
    out = dict(result)
    out["cached"] = True
    out["stale_cache"] = bool(age_seconds > REMOTE_CACHE_MAX_AGE_SECONDS)
    out["cached_at"] = cached_at
    out["cache_age_label"] = age_label(cached_at)
    out["live_error"] = live_error
    return out


def fetch_remote_json(path: str, timeout: float = REMOTE_READ_TIMEOUT_SECONDS, prefer_cache: bool = False) -> dict[str, Any]:
    if prefer_cache:
        cached = read_remote_cache(path, live_error="CACHE_FIRST_CONSOLE_RENDER", allow_stale=True)
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


def post_remote_form(path: str, payload: dict[str, Any], timeout: float = 15) -> dict[str, Any]:
    token = read_access_token()
    if not token:
        return {"ok": False, "error": "MISSING_READ_ACCESS_TOKEN", "token_present": False, "data": {}}
    url = public_base_url() + path
    body = urlencode(payload, doseq=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "text/html,application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Stock-Ultimus-Read-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
        return {
            "ok": True,
            "error": "",
            "token_present": True,
            "url": url,
            "status_code": getattr(response, "status", 200),
            "final_url": response.geturl(),
            "text": text[:1000],
            "data": {},
        }
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP_{exc.code}", "token_present": True, "url": url, "text": text[:1000], "data": {}}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "token_present": True, "url": url, "data": {}}


def console_operator_payload(prefer_cache: bool = False) -> dict[str, Any]:
    return apply_local_operator_events(fetch_remote_json("/gpt_v32_operator_today?limit=12", prefer_cache=prefer_cache))


def console_v31_payloads(prefer_cache: bool = False) -> dict[str, dict[str, Any]]:
    return {
        "executive": fetch_remote_json("/gpt_v31_executive_status?limit=8", prefer_cache=prefer_cache),
        "rankings": fetch_remote_json("/gpt_v31_daily_rankings", prefer_cache=prefer_cache),
        "active_positions": fetch_remote_json("/v31_active_position_management", prefer_cache=prefer_cache),
        "monitor": fetch_remote_json("/v31_monitor_status", prefer_cache=prefer_cache),
        "reviews": fetch_remote_json("/v31_manual_reviews?limit=250", prefer_cache=prefer_cache),
        "learning": fetch_remote_json("/v31_manual_review_learning?limit=250", prefer_cache=prefer_cache),
        "performance": fetch_remote_json("/v32_strategy_performance?limit=500", prefer_cache=prefer_cache),
    }


def published_context_value(value: Any) -> str:
    text = str(value or "").strip()
    if text.upper() in UNKNOWN_CONTEXT_VALUES:
        return ""
    return text


def first_published_context_value(*values: Any) -> str:
    for value in values:
        text = published_context_value(value)
        if text:
            return text
    return ""


def selected_vs_published(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any]) -> dict[str, Any]:
    operator_data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    operator_context = operator_data.get("account_context") if isinstance(operator_data.get("account_context"), dict) else {}
    remote_ok = bool(operator_payload.get("ok"))
    selected_scope = active.get("account_scope") or ""
    selected_alias = active.get("account_alias") or ""
    published_scope = first_published_context_value(
        operator_data.get("account_scope"),
        operator_context.get("account_scope"),
        snapshot.get("account_scope"),
    )
    published_alias = first_published_context_value(
        operator_data.get("account_alias"),
        operator_context.get("account_alias"),
        snapshot.get("account_alias"),
    )
    matches = bool(selected_scope and published_scope and selected_scope == published_scope)
    missing_published_context = bool(remote_ok and selected_scope and not published_scope)
    inferred_from_local = bool(missing_published_context and selected_scope)
    return {
        "selected_scope": selected_scope,
        "selected_alias": selected_alias,
        "published_scope": published_scope,
        "published_alias": published_alias,
        "display_scope": published_scope or (selected_scope if inferred_from_local else ""),
        "display_alias": published_alias or (selected_alias if inferred_from_local else ""),
        "inferred_from_local": inferred_from_local,
        "missing_published_context": missing_published_context,
        "remote_ok": remote_ok,
        "remote_error": operator_payload.get("error") or "",
        "cached": bool(operator_payload.get("cached")),
        "cache_age_label": operator_payload.get("cache_age_label") or "",
        "live_error": operator_payload.get("live_error") or "",
        "matches": matches,
        "needs_refresh": bool((remote_ok and selected_scope and published_scope and not matches)),
        "status": "MATCH" if matches else ("LOCAL_CONTEXT_INFERRED" if inferred_from_local else "REMOTE_UNAVAILABLE" if not remote_ok else "REFRESH_REQUIRED"),
    }


def render_metric(title: str, value: Any, note: str = "") -> str:
    return """
    <article class="metric">
      <span class="label-text">{title}</span>
      <strong>{value}</strong>
      <small class="body-text">{note}</small>
    </article>
    """.format(title=html_escape(title), value=html_escape(value), note=html_escape(note))


def console_health(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any]) -> dict[str, Any]:
    comparison = selected_vs_published(active, snapshot, operator_payload)
    running = active_web_jobs()
    token_present = bool(operator_payload.get("token_present") or read_access_token())
    remote_ok = bool(operator_payload.get("ok"))
    cached = bool(operator_payload.get("cached"))
    stale_cache = bool(operator_payload.get("stale_cache"))
    capacity = console_account_capacity(operator_payload, snapshot)
    local_core = console_local_core_status(active, snapshot, capacity)
    blockers = []
    warnings = []
    info = []
    if not token_present:
        blockers.append("READ_TOKEN_MISSING")
    if not remote_ok:
        blockers.append("PRODUCTION_UNREACHABLE")
    remote_context_is_stale = bool(cached and stale_cache and comparison.get("needs_refresh"))
    remote_context_pending_after_publish = bool(
        local_core.get("ready")
        and local_core.get("bridge_published")
        and comparison.get("missing_published_context")
    )
    if comparison.get("needs_refresh") and not (
        (local_core.get("ready") and remote_context_is_stale)
        or remote_context_pending_after_publish
    ):
        warnings.append("GPT_CONTEXT_REFRESH_REQUIRED")
    elif remote_context_pending_after_publish:
        info.append("GPT_CONTEXT_REMOTE_PENDING_LOCAL_CORE_READY")
    if cached and stale_cache:
        if local_core.get("ready"):
            info.append("REMOTE_CACHE_STALE_LOCAL_CORE_READY")
        else:
            warnings.append("REMOTE_CACHE_STALE")
    elif cached:
        info.append("REMOTE_CACHE_FRESH")
    for missing in local_core.get("missing") or []:
        if missing not in warnings:
            warnings.append(missing)
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
        if local_core.get("ready"):
            detail = "IBKR, cuenta, snapshot y capacidad locales listos para revision manual."
        else:
            detail = "Produccion, cuenta, snapshot y capacidad estan alineados para revision manual."

    return {
        "level": level,
        "label": label,
        "detail": detail,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "running_jobs": running,
        "remote_ok": remote_ok,
        "cached": cached,
        "stale_cache": stale_cache,
        "token_present": token_present,
        "context_status": "LOCAL_READY_REMOTE_PENDING" if remote_context_pending_after_publish else comparison.get("status"),
        "snapshot_available": bool(snapshot.get("available")),
        "capacity_available": bool(capacity.get("available")),
        "ibkr_connected": bool(local_core.get("ibkr_connected")),
        "bridge_published": bool(local_core.get("bridge_published")),
        "local_core_ready": bool(local_core.get("ready")),
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def next_step_level(mode: str, health_level: str) -> str:
    mode_norm = str(mode or "").lower()
    if str(health_level or "").lower() == "red" or mode_norm in {"bloqueado", "riesgo"}:
        return "red"
    if mode_norm in {"procesando", "revision"}:
        return "amber"
    return "green"


def render_console_health(
    active: dict[str, Any],
    snapshot: dict[str, Any],
    operator_payload: dict[str, Any],
    reports: dict[str, dict[str, Any]] | None = None,
) -> str:
    health = console_health(active, snapshot, operator_payload)
    reports = reports if isinstance(reports, dict) else {}
    today = console_today_summary(active, snapshot, operator_payload, reports)
    active_alias = active.get("account_alias") or ""
    refresh_all_disabled = "" if active_alias else " disabled"
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
    details.extend(health.get("info") or [])
    detail_text = ", ".join(details) if details else "sin bloqueos visibles"
    snapshot_label = "disponible" if health.get("snapshot_available") else "pendiente"
    snapshot_hint = (
        "hay paquete maestro local para evaluar"
        if health.get("snapshot_available")
        else "falta generar/publicar datos frescos"
    )
    return """
    <header class="app-header health-{level}">
      <div class="app-health">
        <span class="signal-dot"></span>
        <div><strong>{label}</strong><small>{friendly_detail}</small></div>
      </div>
      <div class="app-health-chips" aria-label="Estado de conexiones">
        <span class="health-chip {production_class}">Producción {production}</span>
        <span class="health-chip {ibkr_class}">IBKR {ibkr}</span>
        <span class="health-chip {snapshot_class}">Datos {snapshot}</span>
        <span class="health-chip {capacity_class}">Capacidad {capacity}</span>
      </div>
      <div class="header-actions">
        <form method="post" action="/daily-open" data-busy="Corriendo apertura diaria" data-busy-detail="Actualiza cuentas, posiciones, riesgo y RSP. No autoriza órdenes.">
          <input name="alias" value="{active_alias}" type="hidden">
          <button class="primary-action"{refresh_all_disabled}>Ejecutar apertura diaria</button>
        </form>
        <form method="post" action="/refresh-remote" data-busy="Actualizando estado" data-busy-detail="Relee el estado publicado sin cambiar de cuenta.">
          <button class="secondary">Actualizar</button>
        </form>
        <details class="header-more">
          <summary>Más opciones</summary>
          <div>
            <form method="post" action="/ibkr-quick-check" data-busy="Validando IBKR/TWS">
              <input name="alias" value="{active_alias}" type="hidden">
              <button class="secondary"{refresh_all_disabled}>Validar conexión IBKR</button>
            </form>
            <form method="post" action="/refresh-all" data-busy="Alineando y publicando contexto">
              <input name="alias" value="{active_alias}" type="hidden">
              <button class="secondary"{refresh_all_disabled}>Alinear contexto publicado</button>
            </form>
            <small>{running_text} · {detail_text}</small>
          </div>
        </details>
      </div>
    </header>
    """.format(
        level=html_escape(health.get("level")),
        label=html_escape(health.get("label")),
        friendly_detail=html_escape(
            "Datos locales listos. La producción se muestra desde la última actualización guardada; pulsa Actualizar para releerla."
            if health.get("stale_cache") and health.get("local_core_ready")
            else "Conexiones y datos principales disponibles para revisión manual."
            if health.get("level") == "green"
            else health.get("detail")
        ),
        production="guardada" if health.get("stale_cache") else "OK" if health.get("remote_ok") else "pendiente",
        production_class="warn" if health.get("stale_cache") else "ok" if health.get("remote_ok") else "warn",
        ibkr="OK" if health.get("ibkr_connected") else "pendiente",
        ibkr_class="ok" if health.get("ibkr_connected") else "warn",
        snapshot="listos" if health.get("snapshot_available") else "pendientes",
        snapshot_class="ok" if health.get("snapshot_available") else "warn",
        capacity="OK" if health.get("capacity_available") else "pendiente",
        capacity_class="ok" if health.get("capacity_available") else "warn",
        running_text=html_escape(running_text),
        detail_text=html_escape(detail_text),
        active_alias=html_escape(active_alias),
        refresh_all_disabled=refresh_all_disabled,
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
    daily_open = reports.get("daily_open") or {}
    daily_open_status = effective_daily_open_status(daily_open) if daily_open else "SIN APERTURA"
    daily_open_label = "ACUMULANDO EVIDENCIA" if daily_open_status == "EVIDENCE_COLLECTION_ONLY" else daily_open_status
    rsp_open = daily_open.get("coberturas_rsp") if isinstance(daily_open.get("coberturas_rsp"), dict) else {}
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
        "daily_open_status": daily_open_label,
        "daily_open_generated_at": daily_open.get("generated_at"),
        "daily_open_rsp": "RSP OK" if rsp_open.get("ok") else "RSP pendiente",
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
      <div class="today-grid compact-metrics">
        {status}
        {waiting}
        {alert}
        {market}
        {daily_open}
      </div>
    </section>
    """.format(
        mode=html_escape(today["mode"]),
        action=html_escape(today["action"]),
        status=render_metric("Estado operador", today["operator_status"], "pendientes={open} | risk={risk} | action={action}".format(**counts)),
        waiting=render_metric("Esta esperando", today["waiting"], "TradingView=" + str(today.get("tv_status"))),
        alert=render_metric("Ultima alerta viva", today["last_alert"], "notify=" + str(today.get("notify_reason"))),
        market=render_metric("Mercado", today["market_session"], "edge=" + edge_text),
        daily_open=render_metric(
            "Ultima apertura",
            today["daily_open_status"],
            "{} · {}".format(today["daily_open_rsp"], age_label(today.get("daily_open_generated_at"))),
        ),
    )


FRIENDLY_OPERATOR_STATES = {
    "WAIT_MARKET": "Esperando nuevas señales",
    "WAIT_DATA": "Faltan datos",
    "WAIT_ACCOUNT_CAPACITY": "Capacidad de cuenta insuficiente",
    "WAIT_MARGIN_PREVIEW": "Margen IBKR pendiente",
    "WAIT_CAPITAL_DATA": "Datos de capital pendientes",
    "COVERED_CALL_OPEN": "Covered call abierto",
    "SHORT_CALL_OPEN": "Call vendida abierta",
    "SHORT_PUT_OPEN": "Put vendida abierta",
    "READY_FOR_MANUAL_REVIEW": "Listo para revisión manual",
    "ACTION_REQUIRED": "Atención requerida",
    "REVIEW_REQUIRED": "Revisión necesaria",
    "REVIEW_RISK": "Revisar riesgo",
    "REVIEW_DEFENSIVE_EXIT": "Revisar defensa",
    "RISK_REVIEW": "Revisión de riesgo",
    "REVIEW_ASSIGNMENT": "Revisar posible asignación",
    "REFRESH_DATA": "Actualizar datos",
    "ASSIGNMENT_REVIEW": "Revisar asignación",
    "TAKE_PROFIT_REVIEW": "Revisar toma de ganancia",
    "FRESH": "Actualizados",
    "WATCH": "Vigilancia",
    "MONITOR": "Monitoreo",
    "BLOCKED": "Bloqueado",
    "SELL_PUT": "Venta de put",
    "SELL_COVERED_CALL": "Covered call",
    "NO_SHARES": "Sin acciones RSP",
    "ACUMULANDO EVIDENCIA": "Aprendizaje en curso",
}


def friendly_operator_state(value: Any, fallback: str = "Pendiente") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    return FRIENDLY_OPERATOR_STATES.get(raw.upper(), raw.replace("_", " ").capitalize())


def friendly_age(value: Any) -> str:
    label = age_label(value)
    match = re.fullmatch(r"(\d+)s ago", label)
    if match:
        return "hace {} s".format(match.group(1))
    match = re.fullmatch(r"(\d+)m ago", label)
    if match:
        return "hace {} min".format(match.group(1))
    match = re.fullmatch(r"(\d+)h ago", label)
    if match:
        return "hace {} h".format(match.group(1))
    match = re.fullmatch(r"(\d+)d ago", label)
    if match:
        return "hace {} d".format(match.group(1))
    return label


def build_unified_pending_items(
    operator_payload: dict[str, Any],
    position_payload: dict[str, Any],
    risk_payload: dict[str, Any],
    rsp_payload: dict[str, Any],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    risk_alerts = risk_payload.get("alerts") if isinstance(risk_payload.get("alerts"), list) else []
    for alert in risk_alerts:
        if not isinstance(alert, dict) or str(alert.get("operational_status") or "OPEN").upper() != "OPEN":
            continue
        severity = str(alert.get("severity") or "WATCH").upper()
        if severity not in {"CRITICAL", "HIGH"}:
            continue
        items.append({
            "level": "critical" if severity == "CRITICAL" else "high",
            "area": "Riesgo",
            "title": str(alert.get("title") or "Revisar alerta de riesgo"),
            "detail": str(alert.get("recommended_action") or "Revisión manual requerida."),
            "href": "#riesgo",
        })

    positions = position_payload.get("positions") if isinstance(position_payload.get("positions"), list) else []
    acknowledged_positions = shared_position_management_journal.acknowledged_position_reviews(
        position_payload,
        path=POSITION_MANAGEMENT_JOURNAL_PATH,
    )
    for item in positions:
        if not isinstance(item, dict):
            continue
        action = str(item.get("management_action") or "").upper()
        if action in {"", "NO_ACTION_RECOMMENDED", "MONITOR"}:
            continue
        if str(item.get("position_id") or "") in acknowledged_positions:
            continue
        ticker = str(item.get("ticker") or "Posición")
        detail = "Revisar los datos y registrar la decisión manual."
        if "ASSIGNMENT" in action:
            detail = "El subyacente está bajo el strike de la put; revisar asignación, cierre o roll."
        elif "REFRESH" in action:
            detail = "Actualizar precios y contexto antes de decidir."
        items.append({
            "level": "high" if any(word in action for word in ("RISK", "ASSIGNMENT", "DEFENSIVE")) else "watch",
            "area": "Posiciones",
            "title": "{} — {}".format(ticker, friendly_operator_state(action)),
            "detail": detail,
            "href": "#posiciones",
        })

    rsp_ibkr = rsp_payload.get("ibkr") if isinstance(rsp_payload.get("ibkr"), dict) else {}
    rsp_blockers = rsp_payload.get("blockers") if isinstance(rsp_payload.get("blockers"), list) else []
    if rsp_blockers or not rsp_ibkr.get("chain_has_rsp"):
        rsp_title = "Coberturas RSP necesita actualización"
        if "OPEN_RSP_OPTION_REQUIRES_MANAGEMENT" in rsp_blockers:
            rsp_title = "Gestionar covered call RSP abierto"
            rsp_detail = str((rsp_payload.get("position_manager") or {}).get("primary_action") or "Monitorear prima, strike y vencimiento.")
        elif "RSP_FRESH_CHAIN_MISSING" in rsp_blockers:
            rsp_detail = "La lectura está guardada, pero falta una cadena IBKR RSP fresca de 7 a 14 DTE."
        elif "RSP_7_14_DTE_CANDIDATES_MISSING" in rsp_blockers:
            rsp_detail = "La cadena no contiene candidatos válidos en la ventana de 7 a 14 DTE."
        elif "MANUAL_GAMMA_CONTEXT_MISSING" in rsp_blockers:
            rsp_detail = "Falta guardar la lectura diaria de niveles y gamma."
        else:
            rsp_detail = "Revisar frescura, capacidad y datos antes de preparar una operación."
        items.append({
            "level": "watch",
            "area": "RSP",
            "title": rsp_title,
            "detail": rsp_detail,
            "href": "#coberturas-rsp",
        })

    operator_data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    active_alerts = operator_data.get("active_alerts") if isinstance(operator_data.get("active_alerts"), list) else []
    for alert in active_alerts:
        if not isinstance(alert, dict) or is_handled_alert(alert):
            continue
        if alert_operator_visibility(alert) not in {"HIGH_PROBABILITY", "RADAR"}:
            continue
        items.append({
            "level": "high" if str(alert.get("severity") or "").upper() == "ACTION" else "watch",
            "area": "Alerta",
            "title": "{} — {}".format(alert.get("ticker") or "Señal", friendly_operator_state(alert.get("state"))),
            "detail": alert_review_guidance(alert),
            "href": "#alertas",
        })
    rank = {"critical": 0, "high": 1, "watch": 2}
    return sorted(items, key=lambda item: rank.get(item.get("level") or "watch", 3))


def render_command_center(
    active: dict[str, Any],
    snapshot: dict[str, Any],
    operator_payload: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    position_payload: dict[str, Any],
    risk_payload: dict[str, Any],
    rsp_payload: dict[str, Any],
) -> str:
    health = console_health(active, snapshot, operator_payload)
    pending = build_unified_pending_items(operator_payload, position_payload, risk_payload, rsp_payload)
    running = active_web_jobs()
    if health.get("level") == "red":
        level, title = "red", "La consola necesita conexión"
        summary = "Resuelve la conexión o publicación antes de usar información operativa."
    elif running:
        level, title = "blue", "La apertura está trabajando"
        summary = "Espera a que termine; no inicies un segundo proceso."
    elif pending:
        level, title = "amber", "Hay {} {} prioritario{}".format(
            len(pending),
            "pendiente" if len(pending) == 1 else "pendientes",
            "" if len(pending) == 1 else "s",
        )
        summary = pending[0]["title"] + ". " + pending[0]["detail"]
    else:
        level, title = "green", "Todo listo para monitorear"
        summary = "No hay acciones prioritarias. Mantén el monitoreo y espera señales válidas."

    daily = reports.get("daily_open") if isinstance(reports.get("daily_open"), dict) else {}
    daily_status = effective_daily_open_status(daily) if daily else "SIN APERTURA"
    if daily_status == "EVIDENCE_COLLECTION_ONLY":
        opening_label = "Completada"
    elif daily_status in {"ACTION_REQUIRED", "REVIEW_REQUIRED", "BLOCKED"}:
        opening_label = "Terminó con pendientes"
    else:
        opening_label = friendly_operator_state(daily_status, "Sin apertura registrada")
    rsp_open = daily.get("coberturas_rsp") if isinstance(daily.get("coberturas_rsp"), dict) else {}
    opening_detail = "{} · RSP {}".format(
        friendly_age(daily.get("generated_at")),
        "actualizado" if rsp_open.get("ok") else "pendiente",
    ) if daily else "Ejecuta Apertura diaria al comenzar la jornada."

    task_rows = []
    for index, item in enumerate(pending[:6], start=1):
        task_rows.append(
            '<a class="operator-task task-{level}" href="{href}"><span>{index}</span>'
            '<div><small>{area}</small><strong>{title}</strong><p>{detail}</p></div>'
            '<b>Revisar →</b></a>'.format(
                level=html_escape(item.get("level") or "watch"),
                href=html_escape(item.get("href") or "#hoy"),
                index=index,
                area=html_escape(item.get("area") or "Pendiente"),
                title=html_escape(item.get("title") or "Revisión pendiente"),
                detail=html_escape(item.get("detail") or ""),
            )
        )
    if not task_rows:
        task_rows.append('<div class="empty-state"><strong>Sin pendientes prioritarios</strong><span>La consola continuará monitoreando.</span></div>')

    risk_counts = risk_payload.get("alert_counts") if isinstance(risk_payload.get("alert_counts"), dict) else {}
    return """
    <section id="hoy" class="panel command-center command-{level}">
      <div class="command-head">
        <div><p class="eyebrow">Inicio</p><h2>{title}</h2><p>{summary}</p></div>
        <div class="opening-status"><span>Última apertura</span><strong>{opening}</strong><small>{opening_detail}</small></div>
      </div>
      <div class="command-facts">
        <div><span>Riesgo</span><strong>{risk_label}</strong><small>{high} alta(s) · {watch} vigilancia</small></div>
        <div><span>Posiciones</span><strong>{positions}</strong><small>{reviews} requieren revisión</small></div>
        <div><span>RSP</span><strong>{rsp_status}</strong><small>{rsp_candidates} candidato(s) válidos 7–14 DTE</small></div>
        <div><span>Mercado</span><strong>{market}</strong><small>{operator_state}</small></div>
      </div>
      <div id="pendientes" class="pending-queue">
        <div class="queue-head"><h3>Pendientes priorizados</h3><span>Primero riesgo, después gestión y oportunidades.</span></div>
        {tasks}
      </div>
    </section>
    """.format(
        level=html_escape(level),
        title=html_escape(title),
        summary=html_escape(summary),
        opening=html_escape(opening_label),
        opening_detail=html_escape(opening_detail),
        risk_label=html_escape("Alto" if (risk_counts.get("critical") or risk_counts.get("high")) else "Vigilancia" if risk_counts.get("watch") else "Controlado"),
        high=html_escape(risk_counts.get("high") or 0),
        watch=html_escape(risk_counts.get("watch") or 0),
        positions=html_escape(position_payload.get("positions_found") or 0),
        reviews=html_escape(position_payload.get("positions_requiring_review") or 0),
        rsp_status=html_escape("Listo" if not rsp_payload.get("blockers") and (rsp_payload.get("ibkr") or {}).get("chain_has_rsp") else "Revisar"),
        rsp_candidates=html_escape(rsp_payload.get("candidate_count") or 0),
        market=html_escape("Abierto" if is_us_market_session_now() else "Cerrado"),
        operator_state=html_escape(friendly_operator_state((operator_payload.get("data") or {}).get("status"))),
        tasks="".join(task_rows),
    )


def v31_payload_data(payloads: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    payload = payloads.get(key) if isinstance(payloads, dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return data


def v31_latest_reviews_by_ticker(payloads: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    data = v31_payload_data(payloads, "reviews")
    recent = data.get("recent_reviews") if isinstance(data.get("recent_reviews"), list) else []
    latest: dict[str, dict[str, Any]] = {}
    for review in recent:
        if not isinstance(review, dict):
            continue
        ticker = str(review.get("ticker") or "").upper()
        if ticker:
            latest[ticker] = review
    return latest


def v31_items_from_payloads(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rankings = v31_payload_data(payloads, "rankings")
    top = rankings.get("top_recommendations") if isinstance(rankings.get("top_recommendations"), list) else []
    blocked = rankings.get("blocked_or_waiting") if isinstance(rankings.get("blocked_or_waiting"), list) else []
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, Any]] = []
    for item in top + blocked:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("ticker") or ""), str(item.get("final_state") or item.get("state") or ""))
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def render_v31_cause_groups(groups: list[dict[str, Any]]) -> str:
    if not groups:
        return '<p class="empty">Sin grupos de bloqueo disponibles.</p>'
    rows = []
    for group in groups[:8]:
        examples = group.get("examples") if isinstance(group.get("examples"), list) else []
        first = examples[0] if examples and isinstance(examples[0], dict) else {}
        rows.append("""
        <article class="module-card module-{level}">
          <span class="module-dot"></span>
          <div>
            <strong>{cause}</strong>
            <span>{count} setup(s): {tickers}</span>
            <small>{example}</small>
          </div>
        </article>
        """.format(
            level="amber" if str(group.get("cause") or group.get("bucket") or "").lower() != "other" else "neutral",
            cause=html_escape(group.get("cause") or group.get("bucket") or "unknown"),
            count=html_escape(group.get("count") or 0),
            tickers=html_escape(", ".join(str(ticker) for ticker in (group.get("tickers") or [])[:8])),
            example=html_escape(first.get("reason") or first.get("primary_block_reason") or ""),
        ))
    return '<div class="module-grid">{}</div>'.format("".join(rows))


def render_v31_executive_panel(payloads: dict[str, dict[str, Any]]) -> str:
    executive = payloads.get("executive") if isinstance(payloads.get("executive"), dict) else {}
    data = v31_payload_data(payloads, "executive")
    if not executive.get("ok"):
        return """
        <section class="panel today-panel">
          <h2>Estado Ejecutivo V31</h2>
          <p class="muted">No pude leer /gpt_v31_executive_status: {error}</p>
        </section>
        """.format(error=html_escape(executive.get("error") or "unknown"))
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    causes = data.get("blocked_cause_groups") if isinstance(data.get("blocked_cause_groups"), list) else []
    answer = data.get("answer_to_user") or data.get("first_line") or "Sin respuesta ejecutiva."
    return """
    <section class="panel today-panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Estado Ejecutivo V31</p>
          <h2>{status}</h2>
        </div>
        <p>{answer}</p>
      </div>
      <div class="today-grid">
        {entry}
        {risk}
        {wait_options}
        {wait_technical}
      </div>
      <h3>Bloqueos principales</h3>
      {causes}
    </section>
    """.format(
        status=html_escape(data.get("operational_readiness") or data.get("status") or "UNKNOWN"),
        answer=html_escape(answer),
        entry=render_metric("ENTRY_READY", summary.get("entry_ready", 0), "requiere revision manual"),
        risk=render_metric("RISK_BLOCKED", summary.get("risk_blocked", 0), "no accionable"),
        wait_options=render_metric("WAIT_OPTIONS", summary.get("wait_options_data", 0), "datos/contrato pendiente"),
        wait_technical=render_metric("WAIT_TECHNICAL", summary.get("wait_technical", 0), "tecnico pendiente"),
        causes=render_v31_cause_groups(causes),
    )


def v31_contract_line(item: dict[str, Any]) -> str:
    contract = item.get("selected_contract") if isinstance(item.get("selected_contract"), dict) else {}
    return "strike={strike} exp={exp} dte={dte} bid/ask={bid}/{ask} mid={mid} delta={delta} spread%={spread_pct}".format(
        strike=contract.get("strike", ""),
        exp=contract.get("expiration", ""),
        dte=contract.get("dte", ""),
        bid=contract.get("bid", ""),
        ask=contract.get("ask", ""),
        mid=contract.get("mid", ""),
        delta=contract.get("delta", ""),
        spread_pct=contract.get("spread_pct", ""),
    )


def v31_review_actions_html(item: dict[str, Any], latest: dict[str, Any]) -> str:
    ticker = str(item.get("ticker") or "UNKNOWN").upper()
    state = str(item.get("final_state") or item.get("state") or "UNKNOWN").upper()
    strategy = str(item.get("strategy") or "")
    allowed = ["REVIEWING", "WATCHLIST", "REJECTED", "EXPIRED"]
    if state == "ENTRY_READY" and item.get("manual_review_ready") is True:
        allowed.insert(1, "APPROVED_FOR_MANUAL_TRADE")
    labels = {
        "APPROVED_FOR_MANUAL_TRADE": "Approve manual",
        "REVIEWING": "Revisando",
        "WATCHLIST": "Watchlist",
        "REJECTED": "Rechazar",
        "EXPIRED": "Expired",
    }
    reasons = {
        "APPROVED_FOR_MANUAL_TRADE": "Validé manualmente contrato, liquidez, spread, eventos, riesgo de cuenta y ticket en broker/TWS. Ejecución será manual.",
        "REVIEWING": "Iniciando revisión manual desde consola local.",
        "WATCHLIST": "Mantener en watchlist; falta mejor precio, confirmación o timing.",
        "REJECTED": "Descartada tras revisión manual desde consola local.",
        "EXPIRED": "Setup expirado o ya no aplica.",
    }
    buttons = []
    for status in allowed:
        override = '<input type="hidden" name="manual_broker_validation_override" value="true">' if status == "APPROVED_FOR_MANUAL_TRADE" else ""
        buttons.append("""
        <button name="status" value="{status}" class="{css}" data-reason="{reason}">{label}</button>
        {override}
        """.format(
            status=html_escape(status),
            css=html_escape(status.lower().replace("_", "-")),
            label=html_escape(labels.get(status, status)),
            reason=html_escape(reasons.get(status, "")),
            override=override,
        ))
    latest_line = ""
    if latest:
        latest_line = '<small>Ultima revision: {} · {}</small>'.format(
            html_escape(latest.get("status") or ""),
            html_escape(age_label(latest.get("reviewed_at"))),
        )
    return """
    <form method="post" action="/manual-review-event" class="alert-actions manual-review-actions" data-busy="Registrando revision manual V31" data-busy-detail="Guardando en backend Render y releyendo estado. No autoriza ordenes.">
      <input name="ticker" value="{ticker}" type="hidden">
      <input name="strategy" value="{strategy}" type="hidden">
      <input name="state" value="{state}" type="hidden">
      <input name="reason" value="{reason}" type="hidden">
      {latest_line}
      <div class="actions">{buttons}</div>
    </form>
    """.format(
        ticker=html_escape(ticker),
        strategy=html_escape(strategy),
        state=html_escape(state),
        reason=html_escape(reasons.get("REVIEWING", "")),
        latest_line=latest_line,
        buttons="".join(buttons),
    )


def v31_manual_review_has_actionable(payloads: dict[str, dict[str, Any]]) -> bool:
    rankings = payloads.get("rankings") if isinstance(payloads.get("rankings"), dict) else {}
    if not rankings.get("ok"):
        return False
    for item in v31_items_from_payloads(payloads):
        state = str(item.get("final_state") or item.get("state") or "").upper()
        if state == "ENTRY_READY" and item.get("manual_review_ready") is True:
            return True
    return False


def render_v31_manual_review_panel(payloads: dict[str, dict[str, Any]]) -> str:
    rankings = payloads.get("rankings") if isinstance(payloads.get("rankings"), dict) else {}
    if not rankings.get("ok"):
        return """
        <details class="panel support-details">
          <summary>Revision Manual V31 (sin datos)</summary>
          <p class="muted">No pude leer rankings V31: {error}</p>
        </details>
        """.format(error=html_escape(rankings.get("error") or "unknown"))
    items = v31_items_from_payloads(payloads)
    actionable = [
        item
        for item in items
        if str(item.get("final_state") or item.get("state") or "").upper() == "ENTRY_READY"
        and item.get("manual_review_ready") is True
    ]
    non_actionable = [item for item in items if item not in actionable]
    latest_by_ticker = v31_latest_reviews_by_ticker(payloads)
    cards = []
    for item in actionable[:16]:
        ticker = str(item.get("ticker") or "UNKNOWN").upper()
        state = str(item.get("final_state") or item.get("state") or "UNKNOWN").upper()
        latest = latest_by_ticker.get(ticker, {})
        cards.append("""
        <article class="alert-card severity-{severity} status-{status_class}">
          <div class="alert-title"><strong>{ticker}</strong><em>{state}</em></div>
          <span>{strategy} | score={score}</span>
          <div class="contract-line">{contract}</div>
          <div class="why-line">{reason}</div>
          <div class="review-line">{review_note}</div>
          {actions}
        </article>
        """.format(
            severity="action" if state == "ENTRY_READY" else "risk" if state == "RISK_BLOCKED" else "watch",
            status_class=html_escape(state.lower().replace("_", "-")),
            ticker=html_escape(ticker),
            state=html_escape(state),
            strategy=html_escape(item.get("strategy") or ""),
            score=html_escape(item.get("score") or item.get("ranking_score") or ""),
            contract=html_escape(v31_contract_line(item)),
            reason=html_escape(item.get("primary_block_reason") or item.get("main_blocker") or item.get("explanation") or "Sin razon primaria."),
            review_note=html_escape(
                "ENTRY_READY: revisar contrato, liquidez, spread, eventos, riesgo y ticket TWS."
                if state == "ENTRY_READY"
                else "Diagnostico: no accionable hasta resolver bloqueo."
            ),
            actions=v31_review_actions_html(item, latest),
        ))
    if not cards:
        cards.append('<p class="empty">Sin setups accionables para revision manual. Lo bloqueado o sin data suficiente no requiere revision.</p>')
    blocked_rows = []
    for item in non_actionable[:20]:
        ticker = str(item.get("ticker") or "UNKNOWN").upper()
        state = str(item.get("final_state") or item.get("state") or "UNKNOWN").upper()
        reason = item.get("primary_block_reason") or item.get("main_blocker") or item.get("explanation") or "Sin razon primaria."
        blocked_rows.append("""
        <li>
          <strong>{ticker}</strong>
          <small>{state} · {reason}</small>
        </li>
        """.format(ticker=html_escape(ticker), state=html_escape(state), reason=html_escape(reason)))
    blocked_html = ""
    if blocked_rows:
        blocked_html = """
        <details class="diagnostic-alerts">
          <summary>No accionables descartadas del inbox ({count})</summary>
          <ul>{rows}</ul>
        </details>
        """.format(count=html_escape(len(non_actionable)), rows="".join(blocked_rows))
    if not actionable:
        return """
    <details class="panel support-details">
      <summary>Revision Manual V31 (sin ENTRY_READY)</summary>
      <div class="section-head">
        <h2>Revision Manual V31</h2>
        <p>Solo muestra ENTRY_READY con datos suficientes. Lo bloqueado, WAIT o sin contrato completo queda fuera de revision.</p>
      </div>
      <div class="alert-grid">{cards}</div>
      {blocked}
    </details>
    """.format(cards="".join(cards), blocked=blocked_html)
    return """
    <section class="panel">
      <div class="section-head">
        <h2>Revision Manual V31</h2>
        <p>Solo muestra ENTRY_READY con datos suficientes. Lo bloqueado, WAIT o sin contrato completo queda fuera de revision.</p>
      </div>
      <div class="alert-grid">{cards}</div>
      {blocked}
    </section>
    """.format(cards="".join(cards), blocked=blocked_html)


def render_v31_learning_panel(payloads: dict[str, dict[str, Any]]) -> str:
    learning = v31_payload_data(payloads, "learning")
    performance = v31_payload_data(payloads, "performance")
    learning_groups = learning.get("by_manual_status") if isinstance(learning.get("by_manual_status"), dict) else {}
    perf_summary = performance.get("summary") if isinstance(performance.get("summary"), dict) else {}
    best = performance.get("best_signals_by_mfe_r") if isinstance(performance.get("best_signals_by_mfe_r"), list) else []
    worst = performance.get("worst_signals_by_mae_r") if isinstance(performance.get("worst_signals_by_mae_r"), list) else []
    best_line = ", ".join(str(item.get("ticker") or "") for item in best[:4] if isinstance(item, dict)) or "N/D"
    worst_line = ", ".join(str(item.get("ticker") or "") for item in worst[:4] if isinstance(item, dict)) or "N/D"
    return """
    <details class="panel support-details">
      <summary>Learning y Performance</summary>
      <div class="section-head">
        <h2>Learning y Performance</h2>
        <p>Resumen local de historial/learning para evitar abrir dashboards separados.</p>
      </div>
      <div class="tiles">
        <div class="tile">Reviews evaluadas<span>{evaluated}</span></div>
        <div class="tile">Por status<span>{statuses}</span></div>
        <div class="tile">Mejores MFE<span>{best}</span></div>
        <div class="tile">Peores MAE<span>{worst}</span></div>
      </div>
    </details>
    """.format(
        evaluated=html_escape(perf_summary.get("evaluated_signal_count") or learning.get("evaluated_count") or "N/D"),
        statuses=html_escape(", ".join(f"{k}:{v}" for k, v in sorted(learning_groups.items())[:6]) or "N/D"),
        best=html_escape(best_line),
        worst=html_escape(worst_line),
    )


def local_question_answer(question: str, payloads: dict[str, dict[str, Any]]) -> str:
    question_norm = str(question or "").strip().lower()
    executive = v31_payload_data(payloads, "executive")
    items = v31_items_from_payloads(payloads)
    if not question_norm:
        return executive.get("answer_to_user") or "Pregunta vacia. Usa: que oportunidades tengo hoy, por que esta bloqueado MSFT, o estado del motor."
    for item in items:
        ticker = str(item.get("ticker") or "").lower()
        if ticker and ticker in question_norm:
            return "{ticker}: {state} | {strategy} | {contract} | razon={reason}. No autoriza ordenes.".format(
                ticker=str(item.get("ticker") or "").upper(),
                state=item.get("final_state") or item.get("state") or "UNKNOWN",
                strategy=item.get("strategy") or "",
                contract=v31_contract_line(item),
                reason=item.get("primary_block_reason") or item.get("main_blocker") or item.get("explanation") or "sin razon primaria",
            )
    if "bloque" in question_norm or "por que" in question_norm or "por qué" in question_norm:
        causes = executive.get("blocked_cause_groups") if isinstance(executive.get("blocked_cause_groups"), list) else []
        if causes:
            return "Bloqueos principales: " + "; ".join(
                "{cause}={count} ({tickers})".format(
                    cause=group.get("cause") or group.get("bucket"),
                    count=group.get("count"),
                    tickers=", ".join(str(ticker) for ticker in (group.get("tickers") or [])[:5]),
                )
                for group in causes[:5]
            )
    return executive.get("answer_to_user") or executive.get("first_line") or "No pude construir respuesta local; revisa Estado Ejecutivo V31."


def render_local_question_panel(question_answer: str = "") -> str:
    answer_html = ""
    if question_answer:
        answer_html = '<div class="notice">{}</div>'.format(html_escape(question_answer))
    return """
    <section class="panel">
      <div class="section-head">
        <h2>Pregunta operativa local</h2>
        <p>Consulta el mismo backend que usa Super Engine Bolsa, sin salir de esta consola.</p>
      </div>
      {answer}
      <form method="post" action="/ask" class="hero-actions" data-busy="Consultando motor" data-busy-detail="Leyendo endpoints GPT-safe de Render. No ejecuta ordenes.">
        <input name="question" placeholder="Ej. que oportunidades tengo hoy / por que esta bloqueado MSFT / estado del motor">
        <button>Preguntar</button>
        <span>Respuesta basada en datos actuales del motor, no en invencion.</span>
      </form>
    </section>
    """.format(answer=answer_html)


def render_support_bundle(summary: str, *sections: str) -> str:
    body = "\n".join(section for section in sections if section)
    if not body:
        return ""
    return """
    <details class="panel support-details support-bundle">
      <summary>{summary}</summary>
      {body}
    </details>
    """.format(summary=html_escape(summary), body=body)


def module_health_items(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    comparison = selected_vs_published(active, snapshot, operator_payload)
    capacity = console_account_capacity(operator_payload, snapshot)
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    counts = operator_alert_counts(data)
    tradingview = reports.get("tradingview") or {}
    readiness = reports.get("readiness") or {}
    notify = reports.get("notify") or {}
    edge = reports.get("edge") or {}
    ibkr_available = bool(capacity.get("available") or snapshot.get("available"))
    ibkr_detail_time = capacity.get("generated_at") or snapshot.get("mtime") or snapshot.get("generated_at")
    return [
        {
            "name": "TWS/IBKR",
            "level": status_level("OK" if ibkr_available else "WAITING"),
            "status": "capacidad/snapshot OK" if ibkr_available else "sin snapshot",
            "detail": age_label(ibkr_detail_time),
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
        <div class="warning">No pude verificar que cuenta ve GPT porque produccion no respondio a tiempo. Usa <strong>Alinear/Publicar rapido</strong> para dejar contexto disponible; usa refresh profundo IBKR solo si necesitas contratos frescos.</div>
        """
    elif comparison["needs_refresh"]:
        warning = """
        <div class="warning">La seleccion local no coincide con lo que GPT ve. Usa <strong>Alinear/Publicar rapido</strong>; no hace falta correr opciones profundas para corregir contexto GPT.</div>
        """
    elif comparison["inferred_from_local"]:
        warning = """
        <div class="warning">Produccion respondio, pero no devolvio campo de cuenta en este endpoint. La consola muestra la cuenta local activa/publicada como referencia operativa.</div>
        """
    elif not comparison["published_scope"]:
        warning = """
        <div class="warning">No hay contexto publicado para GPT. Usa <strong>Alinear/Publicar rapido</strong>. IBKR/opciones es un paso separado.</div>
        """
    remote_status = "cached" if operator_payload.get("cached") else ("ok" if operator_payload.get("ok") else "timeout" if "timed out" in str(operator_payload.get("error") or "").lower() else "blocked")
    published_value = comparison["display_alias"] or ("unavailable" if not comparison["remote_ok"] else "pendiente")
    if comparison["inferred_from_local"]:
        published_note = "remoto sin campo cuenta; mostrando seleccion local scope=" + (comparison["display_scope"] or "pendiente")
    elif comparison["missing_published_context"]:
        published_note = "sin cuenta publicada; GPT remoto aun no ve " + (comparison["selected_scope"] or "la seleccion local")
    elif comparison["cached"]:
        published_note = "cache=" + comparison["cache_age_label"] + (" | live_error=" + comparison["live_error"] if comparison["live_error"] else "")
    elif not comparison["remote_ok"]:
        published_note = "error=" + comparison["remote_error"]
    else:
        published_note = "scope=" + (comparison["published_scope"] or "pendiente")
    return """
    <details class="panel support-details context-details">
      <summary>Contexto activo Stock Ultimus Console</summary>
      <section class="hero-panel embedded-panel">
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
    </details>
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




def coberturas_form_value(context: dict[str, Any], key: str) -> str:
    value = context.get(key)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return "" if value is None else str(value)


def coberturas_badge(value: Any) -> str:
    state = str(value or "UNKNOWN").upper()
    klass = "neutral"
    if state.startswith("REVIEW"):
        klass = "ok"
    elif state in {"WAIT_DATA", "WAIT_MARKET", "UNKNOWN"}:
        klass = "warn"
    elif "MANAGE" in state:
        klass = "info"
    elif "BLOCK" in state:
        klass = "risk"
    return '<span class="badge {}">{}</span>'.format(klass, html_escape(state))




def coberturas_display_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if str(payload.get("decision") or "").upper() == "REVIEW_RSP_COVERAGE_PATHS":
        rows: list[dict[str, Any]] = []
        for key in ["top_put_candidates", "top_call_candidates"]:
            values = payload.get(key)
            if isinstance(values, list):
                rows.extend(item for item in values[:3] if isinstance(item, dict))
        return rows
    candidates = payload.get("top_candidates")
    return candidates if isinstance(candidates, list) else []


def coberturas_money(value: Any) -> str:
    number = console_float_or_none(value)
    if number is None:
        return "pendiente"
    return "${:,.2f}".format(number)


def coberturas_plain(value: Any, fallback: str = "pendiente") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def coberturas_capital_source(value: Any) -> str:
    return {
        "IBKR_WHAT_IF_MARGIN": "Margen confirmado por IBKR",
        "CONFIGURED_MARGIN_ESTIMATE": "Margen estimado configurado",
        "CONSERVATIVE_CASH_OR_DEBIT_FALLBACK": "Valor nominal conservador",
    }.get(str(value or ""), coberturas_plain(value))


def coberturas_prob_label(probability: Any) -> str:
    if not isinstance(probability, dict) or not probability.get("available"):
        return "probabilidad pendiente"
    otm = probability.get("probability_otm")
    assignment = probability.get("probability_assignment")
    return "OTM {}% / asignacion {}%".format(coberturas_plain(otm), coberturas_plain(assignment))


def render_coberturas_scenarios(payload: dict[str, Any], compact: bool = False) -> str:
    scenarios = payload.get("strategy_scenarios") if isinstance(payload.get("strategy_scenarios"), dict) else {}
    sell_put = scenarios.get("sell_put") if isinstance(scenarios.get("sell_put"), dict) else {}
    buy_write = scenarios.get("buy_100_sell_call") if isinstance(scenarios.get("buy_100_sell_call"), dict) else {}

    def card(title: str, scenario: dict[str, Any], max_key: str, capital_key: str) -> str:
        probability = scenario.get("probability") if isinstance(scenario.get("probability"), dict) else {}
        available = "Datos suficientes para comparar" if scenario.get("available") else "Datos incompletos"
        return """
        <div class="scenario-card">
          <div class="scenario-head"><b>{title}</b>{badge}</div>
          <div class="scenario-lines">
            <span>Strike <strong>{strike}</strong></span>
            <span>Exp <strong>{exp}</strong></span>
            <span>Prima <strong>{premium}</strong></span>
            <span>{capital_label} <strong>{capital}</strong></span>
            <span>Margen IBKR <strong>{margin}</strong></span>
            <span>Capital decision <strong>{decision_capital}</strong></span>
            <span>Fuente capital <strong>{capital_source}</strong></span>
            <span>Retorno capital <strong>{return_margin}</strong></span>
            <span>Max ganancia <strong>{max_profit}</strong></span>
            <span>Breakeven <strong>{breakeven}</strong></span>
          </div>
          <p class="muted">{probability} · Gamma: {gamma_status}</p>
        </div>
        """.format(
            title=html_escape(title),
            badge=coberturas_badge(available),
            strike=html_escape(coberturas_plain(scenario.get("strike"))),
            exp=html_escape(coberturas_plain(scenario.get("expiration"))),
            premium=html_escape(coberturas_money(scenario.get("premium"))),
            capital_label=html_escape("Capital" if capital_key == "cash_secured_notional" else "Debito neto"),
            capital=html_escape(coberturas_money(scenario.get(capital_key))),
            margin=html_escape(coberturas_money(scenario.get("ibkr_initial_margin_required"))),
            decision_capital=html_escape(coberturas_money(scenario.get("decision_capital_required"))),
            capital_source=html_escape(coberturas_capital_source(scenario.get("decision_capital_source"))),
            return_margin=html_escape((str(scenario.get("decision_return_on_capital_pct")) + "%") if scenario.get("decision_return_on_capital_pct") is not None else "pendiente"),
            max_profit=html_escape(coberturas_money(scenario.get(max_key))),
            breakeven=html_escape(coberturas_plain(scenario.get("breakeven"))),
            probability=html_escape(coberturas_prob_label(probability)),
            gamma_status=html_escape(coberturas_plain((scenario.get("gamma_alignment") or {}).get("status"))),
        )

    recommendation = payload.get("strategy_recommendation") if isinstance(payload.get("strategy_recommendation"), dict) else {}
    rec_html = ""
    if recommendation:
        sensitivity = recommendation.get("margin_decision_sensitivity") if isinstance(recommendation.get("margin_decision_sensitivity"), dict) else {}
        rec_html = '<div class="notice"><b>Recomendacion:</b> {status}<br>{reason}<br><b>Margen:</b> {margin_note}</div>'.format(
            status=html_escape(recommendation.get("status") or "pendiente"),
            reason=html_escape(recommendation.get("reason") or ""),
            margin_note=html_escape(sensitivity.get("note") or "Sensibilidad de margen pendiente."),
        )
    html_block = card("Sell put", sell_put, "max_profit", "cash_secured_notional") + card(
        "Comprar 100 + sell call",
        buy_write,
        "max_profit_if_called",
        "net_debit",
    )
    if compact:
        return rec_html + '<div class="scenario-grid compact">{}</div>'.format(html_block)
    return rec_html + '<div class="scenario-grid">{}</div>'.format(html_block)


def render_coberturas_operating_plan(payload: dict[str, Any], compact: bool = False) -> str:
    plan = payload.get("strategy_operating_plan") if isinstance(payload.get("strategy_operating_plan"), dict) else {}
    manager = payload.get("position_manager") if isinstance(payload.get("position_manager"), dict) else {}
    journal = payload.get("learning_journal") if isinstance(payload.get("learning_journal"), dict) else {}
    reconciliation = payload.get("broker_reconciliation") if isinstance(payload.get("broker_reconciliation"), dict) else {}
    scenarios = payload.get("strategy_scenarios") if isinstance(payload.get("strategy_scenarios"), dict) else {}
    sell_ev = ((scenarios.get("sell_put") or {}).get("expected_value") if isinstance(scenarios.get("sell_put"), dict) else {}) or {}
    buy_ev = ((scenarios.get("buy_100_sell_call") or {}).get("expected_value") if isinstance(scenarios.get("buy_100_sell_call"), dict) else {}) or {}
    exit_rules = payload.get("exit_rules") if isinstance(payload.get("exit_rules"), dict) else {}
    management_metrics = manager.get("metrics") if isinstance(manager.get("metrics"), list) else []
    primary_metric = management_metrics[0] if management_metrics and isinstance(management_metrics[0], dict) else {}
    rule_items = []
    for item in (exit_rules.get("global") or [])[:2]:
        rule_items.append("<li>{}</li>".format(html_escape(item)))
    body = """
      <div class="scenario-grid compact">
        <div class="scenario-card">
          <div class="scenario-head"><b>Gestion</b>{status}</div>
          <p class="muted">{action}</p>
          <div class="scenario-lines">
            <span>Strike / vencimiento <strong>{managed_contract}</strong></span>
            <span>Prima entrada / actual <strong>{managed_premium}</strong></span>
            <span>Captura estimada <strong>{managed_capture}</strong></span>
            <span>P/L opción estimado <strong>{managed_pnl}</strong></span>
          </div>
        </div>
        <div class="scenario-card">
          <div class="scenario-head"><b>Valor esperado</b></div>
          <div class="scenario-lines">
            <span>Sell put <strong>{sell_ev}</strong></span>
            <span>Buy-write <strong>{buy_ev}</strong></span>
          </div>
        </div>
        <div class="scenario-card">
          <div class="scenario-head"><b>Bitacora</b></div>
          <div class="scenario-lines">
            <span>Cerradas <strong>{closed}</strong></span>
            <span>Abiertas detectadas <strong>{open_count}</strong></span>
            <span>Registros automáticos <strong>{automatic_count}</strong></span>
            <span>Win rate <strong>{win_rate}</strong></span>
          </div>
          <p class="muted">{learning}</p>
        </div>
      </div>
      <ul class="muted">{rules}</ul>
    """.format(
        status=coberturas_badge(manager.get("status") or "UNKNOWN"),
        action=html_escape(manager.get("primary_action") or "Pendiente"),
        managed_contract=html_escape("{} / {}".format(coberturas_plain(primary_metric.get("strike")), coberturas_plain(primary_metric.get("expiration")))),
        managed_premium=html_escape("{} / {}".format(coberturas_money(primary_metric.get("entry_price_per_share")), coberturas_money(primary_metric.get("current_mid")))),
        managed_capture=html_escape((str(primary_metric.get("premium_capture_pct")) + "%") if primary_metric.get("premium_capture_pct") is not None else "pendiente"),
        managed_pnl=html_escape(coberturas_money(primary_metric.get("unrealized_pnl_estimate"))),
        sell_ev=html_escape(coberturas_money(sell_ev.get("estimated_value"))),
        buy_ev=html_escape(coberturas_money(buy_ev.get("estimated_value"))),
        closed=html_escape(journal.get("closed_count")),
        open_count=html_escape(journal.get("open_count", 0)),
        automatic_count=html_escape(journal.get("automatic_entry_count", 0)),
        win_rate=html_escape((str(journal.get("win_rate_pct")) + "%") if journal.get("win_rate_pct") is not None else "pendiente"),
        learning=html_escape(journal.get("next_learning_goal") or "Registrar operaciones para calibrar."),
        rules="".join(rule_items) or "<li>Sin reglas cargadas.</li>",
    )
    if compact:
        return body
    return '<section class="panel"><h2>Plan operativo</h2>{}</section>'.format(body)

def render_coberturas_rsp_page(message: str = "") -> bytes:
    payload = shared_coberturas_engine.build_recommendation(RUNTIME)
    context = payload.get("manual_context") if isinstance(payload.get("manual_context"), dict) else {}
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    candidates = coberturas_display_candidates(payload)
    rows = []
    for item in candidates:
        rows.append("""
          <tr>
            <td>{side}</td><td>{exp}</td><td>{dte}</td><td>{strike}</td><td>{delta}</td>
            <td>{bid}</td><td>{ask}</td><td>{mid}</td><td>{premium}</td><td>{score}</td><td>{why}</td>
          </tr>
        """.format(
            side=html_escape(item.get("side")),
            exp=html_escape(item.get("expiration")),
            dte=html_escape(item.get("dte")),
            strike=html_escape(item.get("strike")),
            delta=html_escape(item.get("delta")),
            bid=html_escape(item.get("bid")),
            ask=html_escape(item.get("ask")),
            mid=html_escape(item.get("mid")),
            premium=html_escape(item.get("premium_100")),
            score=html_escape(item.get("coberturas_score")),
            why=html_escape("; ".join(item.get("coberturas_reasons") or item.get("coberturas_blockers") or [])),
        ))
    blocker_items = "".join("<li>{}</li>".format(html_escape(item)) for item in payload.get("blockers") or [])
    scenarios_html = render_coberturas_scenarios(payload)
    operating_plan_html = render_coberturas_operating_plan(payload)
    if not blocker_items:
        blocker_items = "<li>Sin bloqueadores criticos detectados.</li>"
    notice = '<div class="notice">{}</div>'.format(html_escape(message)) if message else ""
    body = """
    <!doctype html>
    <html lang="es">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Stock Ultimus | Coberturas RSP</title>
        <style>
          :root {{ --ink:#111827; --muted:#5b6472; --paper:#f4f7fb; --card:#ffffff; --soft:#f8fafc; --accent:#11725f; --line:#d9e2ec; --warn:#a45f09; --risk:#b42318; --info:#2563eb; --display: ui-serif, Georgia, Cambria, "Times New Roman", serif; --body: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
          body {{ margin:0; font-family:var(--body); color:var(--ink); background:var(--paper); }}
          main {{ max-width:1180px; margin:0 auto; padding:28px 18px 60px; }}
          h1 {{ font-family:var(--display); font-size:3.1rem; line-height:1; margin:0 0 12px; letter-spacing:0; }}
          h2 {{ margin:0 0 12px; font-size:1.25rem; }}
          a {{ color:var(--accent); font-weight:800; }}
          .panel,.metric,.notice {{ border:1px solid var(--line); background:var(--card); border-radius:8px; box-shadow:0 8px 24px rgba(17,24,39,.06); }}
          .panel {{ padding:18px; margin:16px 0; }}
          .notice {{ padding:12px 16px; margin:14px 0; }}
          .guardrail {{ border-left:6px solid var(--warn); background:#fff7ed; padding:13px 15px; border-radius:12px; line-height:1.45; }}
          .topbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:18px; }}
          .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }}
          .scenario-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }}
          .scenario-grid.compact {{ grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); margin:10px 0; }}
          .scenario-card {{ border:1px solid var(--line); background:#ffffff; border-radius:8px; padding:14px; box-shadow:none; }}
          .scenario-head {{ display:flex; justify-content:space-between; gap:10px; align-items:center; margin-bottom:10px; }}
          .scenario-lines {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px 10px; }}
          .scenario-lines span {{ color:var(--muted); font-size:12px; }}
          .scenario-lines strong {{ display:block; color:var(--ink); font-family:var(--display); font-size:18px; margin-top:2px; }}
          .metric {{ padding:14px; }}
          .metric span {{ display:block; color:var(--muted); font-size:.78rem; text-transform:uppercase; font-weight:900; }}
          .metric strong {{ display:block; font-family:var(--display); font-size:1.55rem; margin-top:4px; }}
          .layout {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(340px,.78fr); gap:16px; align-items:start; }}
          label {{ display:block; color:var(--muted); font-size:.78rem; font-weight:900; text-transform:uppercase; margin:10px 0 5px; }}
          input, select, textarea {{ width:100%; box-sizing:border-box; border:1px solid var(--line); border-radius:8px; background:#ffffff; padding:10px; font-size:14px; color:var(--ink); font-family:var(--body); }}
          textarea {{ min-height:78px; resize:vertical; }}
          button,.button {{ display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--accent); background:var(--accent); color:white; border-radius:999px; padding:10px 14px; font-weight:900; text-decoration:none; cursor:pointer; }}
          .button.secondary {{ background:#ffffff; color:var(--ink); border-color:var(--line); }}
          table {{ width:100%; border-collapse:collapse; min-width:900px; }}
          th,td {{ padding:10px 11px; border-bottom:1px solid var(--line); text-align:left; font-size:13px; vertical-align:top; }}
          th {{ color:var(--muted); text-transform:uppercase; font-size:11px; }}
          .tablewrap {{ overflow:auto; border:1px solid var(--line); border-radius:8px; background:#ffffff; }}
          .badge {{ display:inline-flex; border-radius:999px; padding:5px 9px; color:white; font-size:12px; font-weight:900; }}
          .badge.ok {{ background:#047857; }} .badge.warn {{ background:#b45309; }} .badge.risk {{ background:#b42318; }} .badge.info {{ background:#2563eb; }} .badge.neutral {{ background:#64748b; }}
          .muted {{ color:var(--muted); line-height:1.45; }}
          pre {{ background:#111827; color:#e5e7eb; border-radius:14px; padding:14px; overflow:auto; font-size:12px; }}
          @media (max-width: 900px) {{ .layout {{ grid-template-columns:1fr; }} h1 {{ font-size:2.3rem; }} }}
        </style>
      </head>
      <body>
        <main>
          <div class="topbar"><a class="button secondary" href="/console">Volver a consola</a><a class="button secondary" href="/coberturas/rsp">Ver JSON</a></div>
          <p class="muted">Stock Ultimus Console</p>
          <h1>Coberturas RSP</h1>
          <div class="guardrail"><b>Guardrail:</b> módulo local de recomendación. No coloca órdenes ni autoriza ejecución. Cada entrada nueva se limita a 1 contrato y el número de ciclos simultáneos tiene un máximo configurable.</div>
          {notice}
          <section class="grid">
            <div class="metric"><span>Decision</span><strong>{decision}</strong></div>
            <div class="metric"><span>Modo</span><strong>{mode}</strong></div>
            <div class="metric"><span>Spot RSP</span><strong>{spot}</strong></div>
            <div class="metric"><span>Candidatos</span><strong>{candidate_count}</strong></div>
          </section>
          <section class="panel">
            <h2>Comparacion de estrategia</h2>
            {scenarios}
          </section>
          {operating_plan}
          <section class="layout">
            <div class="panel">
              <h2>Gamma y niveles del dia</h2>
              <form method="post" action="/coberturas/rsp/manual_context">
                <label for="rsp-position-mode">Modo posicion</label>
                <select id="rsp-position-mode" name="position_mode">
                  <option value="AUTO">Auto desde IBKR</option>
                  <option value="NO_SHARES">Sin acciones</option>
                  <option value="WITH_SHARES">Con acciones</option>
                  <option value="SHORT_PUT_OPEN">Put abierta</option>
                  <option value="SHORT_CALL_OPEN">Call abierta</option>
                </select>
                <label for="rsp-gamma-blob">Lectura completa de gamma / captura</label>
                <textarea id="rsp-gamma-blob" name="gamma_blob" placeholder="Pega aqui el texto que salga de la captura: spot, soportes, resistencias, expected move, call wall, put wall, sesgo gamma.">{gamma_blob}</textarea>
                <label for="rsp-spot">Spot RSP</label><input id="rsp-spot" name="spot" value="{spot_value}">
                <label for="rsp-supports">Soportes separados por coma</label><input id="rsp-supports" name="support_levels" value="{supports}">
                <label for="rsp-resistances">Resistencias separadas por coma</label><input id="rsp-resistances" name="resistance_levels" value="{resistances}">
                <label for="rsp-expected-low">Expected move bajo</label><input id="rsp-expected-low" name="expected_move_low" value="{expected_low}">
                <label for="rsp-expected-high">Expected move alto</label><input id="rsp-expected-high" name="expected_move_high" value="{expected_high}">
                <label for="rsp-call-wall">Call wall</label><input id="rsp-call-wall" name="call_wall" value="{call_wall}">
                <label for="rsp-put-wall">Put wall</label><input id="rsp-put-wall" name="put_wall" value="{put_wall}">
                <label for="rsp-gamma-bias">Sesgo gamma</label><input id="rsp-gamma-bias" name="gamma_bias" value="{gamma_bias}">
                <label for="rsp-gamma-notes">Notas gamma / captura</label><textarea id="rsp-gamma-notes" name="gamma_notes">{gamma_notes}</textarea>
                <label for="rsp-chart-notes">Notas grafico</label><textarea id="rsp-chart-notes" name="chart_notes">{chart_notes}</textarea>
                <button type="submit">Guardar contexto RSP</button>
              </form>
            </div>
            <div class="panel">
              <h2>Lectura actual</h2>
              <p><b>Estado posicion:</b> {position_state}</p>
              <p><b>Razon:</b> {mode_reason}</p>
              <p><b>Siguiente paso:</b> {next_action}</p>
              <h2>Bloqueadores</h2>
              <ul>{blockers}</ul>
              <p class="muted">Despues de guardar gamma, corre Refresh RSP semanal para traer cadena RSP 7-14 DTE fresca desde IBKR.</p>
              <form method="post" action="/coberturas/rsp/refresh"><button class="secondary" type="submit">Refresh RSP semanal IBKR</button></form>
            </div>
          </section>
          <section class="panel">
            <h2>Strikes candidatos</h2>
            <div class="tablewrap"><table>
              <thead><tr><th>Lado</th><th>Exp</th><th>DTE</th><th>Strike</th><th>Delta</th><th>Bid</th><th>Ask</th><th>Mid</th><th>Prima x100</th><th>Score</th><th>Lectura</th></tr></thead>
              <tbody>{rows}</tbody>
            </table></div>
          </section>
          <section class="panel">
            <h2>Bitacora RSP</h2>
            <form method="post" action="/coberturas/rsp/journal">
              <div class="grid">
                <div><label for="rsp-journal-strategy">Estrategia</label><select id="rsp-journal-strategy" name="strategy"><option>SELL_PUT</option><option>BUY_100_SELL_CALL</option><option>MANAGE_OPEN_POSITION</option></select></div>
                <div><label for="rsp-journal-status">Estado</label><select id="rsp-journal-status" name="status"><option>OPEN</option><option>CLOSED</option><option>ROLLED</option><option>ASSIGNED</option><option>EXPIRED</option></select></div>
                <div><label for="rsp-journal-pnl">P/L realizado</label><input id="rsp-journal-pnl" name="realized_pnl" placeholder="0.00"></div>
              </div>
              <label for="rsp-journal-notes">Decision / notas</label><textarea id="rsp-journal-notes" name="notes" placeholder="Que hicimos y por que."></textarea>
              <button type="submit">Registrar en bitacora</button>
            </form>
          </section>
          <details class="panel"><summary><b>Payload tecnico</b></summary><pre>{payload_json}</pre></details>
        </main>
      </body>
    </html>
    """.format(
        notice=notice,
        decision=coberturas_badge(payload.get("decision")),
        mode=html_escape(payload.get("mode")),
        spot=html_escape(payload.get("spot")),
        candidate_count=html_escape(payload.get("candidate_count")),
        scenarios=scenarios_html,
        operating_plan=operating_plan_html,
        gamma_blob=html_escape(coberturas_form_value(context, "gamma_blob")),
        spot_value=html_escape(coberturas_form_value(context, "spot")),
        supports=html_escape(coberturas_form_value(context, "support_levels")),
        resistances=html_escape(coberturas_form_value(context, "resistance_levels")),
        expected_low=html_escape(coberturas_form_value(context, "expected_move_low")),
        expected_high=html_escape(coberturas_form_value(context, "expected_move_high")),
        call_wall=html_escape(coberturas_form_value(context, "call_wall")),
        put_wall=html_escape(coberturas_form_value(context, "put_wall")),
        gamma_bias=html_escape(coberturas_form_value(context, "gamma_bias")),
        gamma_notes=html_escape(coberturas_form_value(context, "gamma_notes")),
        chart_notes=html_escape(coberturas_form_value(context, "chart_notes")),
        position_state=coberturas_badge(position.get("state")),
        mode_reason=html_escape(payload.get("mode_reason")),
        next_action=html_escape(payload.get("next_action")),
        blockers=blocker_items,
        rows="".join(rows) or '<tr><td colspan="11">Sin candidatos RSP todavia. Guarda gamma y corre Refresh RSP semanal IBKR.</td></tr>',
        payload_json=html_escape(json.dumps(payload, indent=2, sort_keys=True, default=str)),
    )
    return body.encode("utf-8")


def render_coberturas_inline_panel(payload: dict[str, Any] | None = None) -> str:
    payload = payload if isinstance(payload, dict) else shared_coberturas_engine.build_recommendation(RUNTIME)
    context = payload.get("manual_context") if isinstance(payload.get("manual_context"), dict) else {}
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    candidates = coberturas_display_candidates(payload)
    rows = []
    for item in candidates[:6]:
        cc_eval = item.get("covered_call_evaluation") if isinstance(item.get("covered_call_evaluation"), dict) else {}
        rows.append(
            """
            <tr>
              <td>{side}</td><td>{exp}</td><td>{dte}</td><td>{strike}</td>
              <td>{delta}</td><td>{premium}</td><td>{moneyness}</td><td>{method_score}</td><td>{score}</td>
            </tr>
            """.format(
                side=html_escape(item.get("side")),
                exp=html_escape(item.get("expiration")),
                dte=html_escape(item.get("dte")),
                strike=html_escape(item.get("strike")),
                delta=html_escape(item.get("delta")),
                premium=html_escape(item.get("premium_100")),
                moneyness=html_escape(cc_eval.get("moneyness") or "-"),
                method_score=html_escape(cc_eval.get("selected_score") if cc_eval else "-"),
                score=html_escape(item.get("coberturas_score")),
            )
        )
    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    blocker_messages = {
        "RSP_OPTION_CHAIN_MISSING": "No hay una cadena de opciones RSP disponible.",
        "RSP_FRESH_CHAIN_MISSING": "Falta una cadena IBKR RSP fresca.",
        "RSP_7_14_DTE_CANDIDATES_MISSING": "No hay candidatos válidos entre 7 y 14 DTE.",
        "MANUAL_GAMMA_CONTEXT_MISSING": "Falta la lectura diaria de niveles y gamma.",
        "RSP_SPOT_MISSING": "Falta el precio actual de RSP.",
        "POSITION_STATE_UNKNOWN": "No se confirmó la posición actual en RSP.",
    }
    blocker_text = " ".join(blocker_messages.get(str(item), friendly_operator_state(item)) for item in blockers) if blockers else "Sin bloqueos de datos críticos."
    gamma_blob = coberturas_form_value(context, "gamma_blob") or coberturas_form_value(context, "gamma_notes")
    managing_position = str(position.get("state") or "") in {"COVERED_CALL_OPEN", "SHORT_CALL_OPEN", "SHORT_PUT_OPEN"}
    manager = payload.get("position_manager") if isinstance(payload.get("position_manager"), dict) else {}
    new_entry = payload.get("new_entry_lane") if isinstance(payload.get("new_entry_lane"), dict) else {}
    cycle_capacity = new_entry.get("cycle_capacity") if isinstance(new_entry.get("cycle_capacity"), dict) else {}
    new_entry_status = str(new_entry.get("status") or "WAIT_DATA")
    scenarios_html = (
        render_coberturas_scenarios(payload, compact=True)
        if payload.get("candidate_count")
        else '<div class="empty-state"><strong>Sin comparación operable</strong><span>Primero se necesita una cadena RSP fresca con candidatos de 7 a 14 DTE.</span></div>'
    )
    parallel_lanes_html = """
      <div class="scenario-grid compact">
        <div class="scenario-card">
          <div class="scenario-head"><b>1. Gestión actual</b>{management_badge}</div>
          <p class="muted">{management_action}</p>
          <div class="scenario-lines">
            <span>Estado broker <strong>{position_state}</strong></span>
            <span>Ciclos activos <strong>{active_cycles}</strong></span>
          </div>
        </div>
        <div class="scenario-card">
          <div class="scenario-head"><b>2. Nueva posición</b>{entry_badge}</div>
          <p class="muted">{entry_action}</p>
          <div class="scenario-lines">
            <span>Preferencia actual <strong>{entry_strategy}</strong></span>
            <span>Espacios de riesgo <strong>{remaining_slots} de {max_cycles}</strong></span>
            <span>Capital estimado mínimo <strong>{required_capital}</strong></span>
            <span>Regla por entrada <strong>1 contrato</strong></span>
          </div>
        </div>
      </div>
    """.format(
        management_badge=coberturas_badge(manager.get("status") or ("MANAGE" if managing_position else "MONITOR")),
        management_action=html_escape(manager.get("primary_action") or "Sin posición abierta que gestionar."),
        position_state=html_escape(position.get("state") or "UNKNOWN"),
        active_cycles=html_escape(cycle_capacity.get("active_cycles", 0)),
        entry_badge=coberturas_badge(new_entry_status),
        entry_action=html_escape(new_entry.get("primary_action") or "Evaluación pendiente."),
        entry_strategy=html_escape(
            (new_entry.get("display_strategy") or "Pendiente")
            + (" · condicionada" if new_entry.get("strategy_role") == "CONDITIONAL_PREFERENCE" and new_entry.get("display_strategy") else "")
        ),
        remaining_slots=html_escape(cycle_capacity.get("remaining_risk_slots", 0)),
        max_cycles=html_escape(cycle_capacity.get("max_concurrent_cycles", 0)),
        required_capital=html_escape(coberturas_money(cycle_capacity.get("estimated_capital_required_min"))),
    )
    operating_plan_html = render_coberturas_operating_plan(payload, compact=True)
    ibkr = payload.get("ibkr") if isinstance(payload.get("ibkr"), dict) else {}
    methodology = payload.get("covered_call_methodology") if isinstance(payload.get("covered_call_methodology"), dict) else {}
    methodology_labels = {
        "INCOME_DEFENSIVE": "Ingreso y defensa",
        "FLEXIBLE_TOTAL_RETURN": "Retorno total flexible",
        "UPSIDE_RETENTION": "Conservar upside",
    }
    methodology_winners = methodology.get("profile_winners") if isinstance(methodology.get("profile_winners"), dict) else {}
    methodology_cards = "".join(
        '<div><span>{label}</span><strong>{strike} · {moneyness}</strong><small>score {score} · spread {spread}% · {quality}</small></div>'.format(
            label=html_escape(methodology_labels.get(profile, profile)),
            strike=html_escape((winner or {}).get("strike")),
            moneyness=html_escape((winner or {}).get("moneyness")),
            score=html_escape((winner or {}).get("score")),
            spread=html_escape((winner or {}).get("spread_pct")),
            quality="apto para revisión manual" if (winner or {}).get("execution_ready_for_review") else "esperar mejor liquidez",
        )
        for profile, winner in methodology_winners.items()
        if isinstance(winner, dict)
    )
    context_age = friendly_age(context.get("updated_at") or context.get("generated_at"))
    chain_age = friendly_age(ibkr.get("chain_coverage_generated_at"))
    data_ready = bool(not blockers and ibkr.get("chain_has_rsp") and (payload.get("candidate_count") or managing_position))
    recommendation = payload.get("strategy_recommendation") if isinstance(payload.get("strategy_recommendation"), dict) else {}
    recommendation_status = str(recommendation.get("status") or "")
    ready = bool(data_ready and recommendation_status not in {"WAIT_ACCOUNT_CAPACITY", "WAIT_MARGIN_PREVIEW", "WAIT_CAPITAL_DATA"})
    if managing_position and new_entry_status.startswith("RECOMMEND_"):
        ready = True
        status_title = "RSP gestiona la posición abierta y propone un nuevo ciclo"
        status_badge = "Gestión + oportunidad"
    elif managing_position and new_entry_status == "WAIT_ACCOUNT_CAPACITY":
        ready = False
        status_title = "RSP gestiona la posición abierta y sigue evaluando nuevas entradas"
        status_badge = "Gestión / falta capacidad"
    elif managing_position:
        ready = False
        status_title = "RSP gestiona la posición abierta; la nueva entrada sigue en evaluación"
        status_badge = "Gestión + evaluación"
    elif recommendation_status == "WAIT_ACCOUNT_CAPACITY":
        status_title = "RSP actualizado; falta capacidad en la cuenta seleccionada"
        status_badge = "Capacidad pendiente"
    elif data_ready and not ready:
        status_title = "RSP actualizado; falta confirmar capital o margen"
        status_badge = "Capital pendiente"
    elif ready:
        status_title = "RSP listo para revisión manual"
        status_badge = "Listo"
    else:
        status_title = "RSP requiere información antes de decidir"
        status_badge = "Revisión pendiente"
    status_detail = payload.get("next_action") or blocker_text
    return """
    <section id="coberturas-rsp" class="panel coberturas-panel">
      <div class="section-head">
        <div>
          <h2>Coberturas RSP</h2>
          <p>Decisión, capacidad y candidatos válidos para una revisión manual. La consola nunca ejecuta la orden.</p>
        </div>
        <span class="readiness-pill readiness-{readiness}">{status_badge}</span>
      </div>
      <div class="rsp-status-line status-{readiness}"><strong>{status_title}</strong><span>{status_detail}</span></div>
      <div class="position-overview rsp-overview">
        <div><span>Decisión</span><strong>{decision}</strong><small>revisión humana</small></div>
        <div><span>Cuenta RSP</span><strong>{rsp_account}</strong><small>asignación permanente de estrategia</small></div>
        <div><span>Precio RSP</span><strong>{spot}</strong><small>última lectura disponible</small></div>
        <div><span>Lectura de niveles</span><strong>{context_status}</strong><small>{context_age}</small></div>
        <div><span>Cadena 7–14 DTE</span><strong>{chain_status}</strong><small>{chain_age}</small></div>
        <div><span>Seguimiento IBKR</span><strong>{sync_status}</strong><small>{sync_detail}</small></div>
      </div>
      <p class="review-line">{blockers}</p>
      {parallel_lanes}
      <details class="operator-subsection">
        <summary>Cómo evalúa strikes ITM, ATM y OTM</summary>
        <p class="muted">Perfil utilizado: <strong>{methodology_profile}</strong>. ITM está permitido; cada strike se compara por prima, protección bajista, ganancia total si es asignado, probabilidad, spread y upside conservado. Un ganador comparativo no queda apto para revisión operativa hasta que su prima y spread sean utilizables.</p>
        <div class="position-overview rsp-overview">{methodology_cards}</div>
      </details>
      <div class="rsp-decision-body">
        {scenarios}
        <details class="operator-subsection"{candidate_open}>
          <summary>Candidatos válidos de la cadena actual ({candidate_count})</summary>
          <div class="table-scroll"><table>
            <thead><tr><th>Lado</th><th>Vencimiento</th><th>DTE</th><th>Strike</th><th>Delta</th><th>Prima</th><th>ITM/ATM/OTM</th><th>Score método</th><th>Score técnico</th></tr></thead>
            <tbody>{rows}</tbody>
          </table></div>
        </details>
        <details class="operator-subsection">
          <summary>Actualizar lectura de mercado RSP</summary>
          <form method="post" action="/coberturas/rsp/manual_context" data-busy="Guardando lectura RSP">
            <input type="hidden" name="return_to" value="console">
            <input type="hidden" name="position_mode" value="AUTO">
            <label>Lectura de niveles y gamma</label>
            <textarea name="gamma_blob" placeholder="Pega una lectura RSP con spot, soportes, resistencias, expected move, call wall, put wall y sesgo gamma.">{gamma_blob}</textarea>
            <p><button type="submit">Guardar lectura RSP</button></p>
          </form>
        </details>
        <details class="operator-subsection">
          <summary>Gestión, valor esperado y bitácora</summary>{operating_plan}
        </details>
      </div>
      <div class="section-actions">
        <form method="post" action="/coberturas/rsp/refresh" data-background-submit="true" data-status-target="rsp-refresh-status" data-busy="Consultando RSP semanal en IBKR" data-busy-detail="Lee RSP 7-14 DTE desde IBKR. No autoriza ordenes. Puedes seguir en esta pagina.">
          <input type="hidden" name="return_to" value="console">
          <button class="secondary" type="submit">Actualizar sólo RSP</button>
        </form>
        <a class="text-link" href="/coberturas/rsp">Ver datos técnicos</a>
        <span id="rsp-refresh-status" class="muted">La Apertura diaria ya incluye esta actualización.</span>
      </div>
    </section>
    """.format(
        gamma_blob=html_escape(gamma_blob),
        decision=html_escape(friendly_operator_state(payload.get("decision"))),
        rsp_account=html_escape(ibkr.get("configured_account_alias") or CONSOLE_COBERTURAS_RSP_ACCOUNT_ALIAS),
        spot=html_escape(payload.get("spot")),
        context_status=html_escape("Guardada" if context.get("available") else "Pendiente"),
        context_age=html_escape(context_age),
        chain_status=html_escape("Actualizada" if ibkr.get("chain_has_rsp") else "Pendiente"),
        chain_age=html_escape(chain_age),
        sync_status=html_escape("Automático" if (payload.get("broker_reconciliation") or {}).get("ok") else "Pendiente"),
        sync_detail=html_escape(friendly_operator_state((payload.get("broker_reconciliation") or {}).get("position_state") or "esperando refresco")),
        readiness="ready" if ready else "review",
        status_title=html_escape(status_title),
        status_badge=html_escape(status_badge),
        status_detail=html_escape(status_detail),
        scenarios=scenarios_html,
        operating_plan=operating_plan_html,
        blockers=html_escape(blocker_text),
        parallel_lanes=parallel_lanes_html,
        methodology_profile=html_escape(methodology_labels.get(str(methodology.get("selected_profile") or ""), methodology.get("selected_profile") or "Retorno total flexible")),
        methodology_cards=methodology_cards or '<div><span>Comparación</span><strong>Pendiente</strong><small>Se completará con la próxima cadena ampliada.</small></div>',
        candidate_count=html_escape(payload.get("candidate_count") or 0),
        candidate_open=" open" if payload.get("candidate_count") else "",
        rows="".join(rows) or '<tr><td colspan="9">No hay candidatos vigentes de 7 a 14 DTE. No uses contratos históricos.</td></tr>',
    )


def render_console_actions(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any] | None = None) -> str:
    operator_payload = operator_payload if isinstance(operator_payload, dict) else {}
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    comparison = selected_vs_published(active, snapshot, operator_payload)
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
    account = comparison["display_alias"] or data.get("account_alias") or data.get("account_scope") or "pendiente"
    status = data.get("status") or ("OK" if operator_payload.get("ok") else operator_payload.get("error") or "UNKNOWN")
    return """
    <section class="panel embedded-support-panel">
      <div class="section-head">
        <h2>Administracion desde esta consola</h2>
        <p>Accesos de soporte para administrar sin salir del cockpit principal.</p>
      </div>
      <div class="tiles">
        <div class="tile">Alertas y acciones<span>{open} pendientes: {risk} riesgo, {watch} watch, {action} action. Usa los botones de cada tarjeta aqui mismo.</span></div>
        <div class="tile">Contexto GPT activo<span>status={status} | cuenta={account}. Actualiza con el boton de arriba; no necesitas abrir otro dashboard.</span></div>
        <div class="tile">Siguiente paso<span>{next_label}</span></div>
        <div class="tile">Futuros intradia<span>{intraday_message}</span></div>
        <a class="tile inline-link" href="#coberturas-rsp">Coberturas RSP<span>Panel integrado para vender put / covered call en RSP. Recomendacion manual, sin ordenes.</span></a>
        <div class="tile">Historial local visible<span>{closed} alerta(s) cerrada(s) o revisada(s) quedan debajo de Alertas V32.</span></div>
      </div>
      <p class="muted">No hace falta salir de esta consola para administrar cuenta, refrescar IBKR, revisar alertas o registrar decisiones. Rutas de diagnostico protegidas: /gpt_v32_operator_today · /v32_operator_dashboard · /coberturas · /v32_operator_daily_summary_email/preview · /v32_operator_tracking_status.</p>
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


def render_notification_test_panel() -> str:
    return """
    <details class="panel support-details">
      <summary>Prueba de notificaciones</summary>
      <div class="section-head">
        <h2>Prueba de notificaciones</h2>
        <p>Valida canales externos sin generar senales ni ordenes. Preview no envia; prueba forzada envia un resumen operativo.</p>
      </div>
      <div class="hero-actions">
        <form method="post" action="/notification-preview" data-busy="Leyendo preview notificaciones" data-busy-detail="Consulta email/Pushover en modo preview. No envia.">
          <button>Preview alertas</button>
        </form>
        <form method="post" action="/notification-test-email" data-busy="Enviando email de prueba" data-busy-detail="Envio forzado de resumen operativo. No autoriza ordenes.">
          <button class="secondary">Enviar email prueba</button>
        </form>
        <form method="post" action="/notification-test-push" data-busy="Enviando push de prueba" data-busy-detail="Envio forzado Pushover operativo. No autoriza ordenes.">
          <button class="secondary">Enviar push prueba</button>
        </form>
        <span>Usa estas pruebas si no ves alertas en correo o movil.</span>
      </div>
    </details>
    """


def compact_contract_value(value: Any, suffix: str = "") -> str:
    if value in [None, "", "None"]:
        return "-"
    try:
        number = float(value)
        text = ("{:.4f}".format(number)).rstrip("0").rstrip(".")
    except Exception:
        text = str(value)
    return text + suffix


def compact_volatility_value(value: Any) -> str:
    number = console_float_or_none(value)
    if number is None:
        return "-"
    if abs(number) <= 1:
        number *= 100.0
    return ("{:.2f}".format(number)).rstrip("0").rstrip(".") + "%"


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
            remote_time = max(timestamp_sort_value(capacity.get("generated_at")), timestamp_sort_value(context.get("generated_at")))
            local_time = timestamp_sort_value(local_capacity.get("generated_at"))
            local_is_newer = local_time >= remote_time
            if local_is_newer or not capacity:
                capacity = {**capacity, **local_capacity}
                context = {**context, **local_capacity}
            else:
                capacity = {**local_capacity, **capacity}
                context = {**local_capacity, **context}
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
    active = active_profile()
    account_alias = first_published_context_value(
        data.get("account_alias"),
        context.get("account_alias"),
        snapshot.get("account_alias"),
        active.get("account_alias"),
    )
    account_scope = first_published_context_value(
        data.get("account_scope"),
        context.get("account_scope"),
        snapshot.get("account_scope"),
        active.get("account_scope"),
    )
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
        "account_alias": account_alias,
        "account_scope": account_scope,
        "sensitive_identifiers_excluded": True,
    }


def latest_ibkr_connection_status(active: dict[str, Any]) -> dict[str, Any]:
    health = load_json_file(IBKR_BRIDGE_HEALTH_PATH)
    session = load_json_file(CONSOLE_BRIDGE_SESSION_PATH)
    runs = session.get("runs") if isinstance(session.get("runs"), list) else []
    latest_run = runs[-1] if runs and isinstance(runs[-1], dict) else {}
    active_scope = active.get("account_scope") or ""
    active_alias = active.get("account_alias") or ""
    health_scope = health.get("account_scope") or ""
    health_alias = health.get("account_alias") or ""
    account_matches = True
    if active_scope and health_scope:
        account_matches = active_scope == health_scope
    elif active_alias and health_alias:
        account_matches = active_alias == health_alias
    connected = bool(
        health.get("connected")
        or str(health.get("status") or "").upper() == "CONNECTED"
        or latest_run.get("ok")
    )
    published = bool(
        latest_run.get("published")
        or any(bool(run.get("published")) for run in runs if isinstance(run, dict))
    )
    return {
        "available": bool(connected and account_matches),
        "connected": connected,
        "account_matches": account_matches,
        "status": health.get("status") or latest_run.get("status") or "",
        "generated_at": health.get("generated_at") or latest_run.get("finished_at") or session.get("finished_at") or "",
        "published": published,
    }


def console_local_core_status(active: dict[str, Any], snapshot: dict[str, Any], capacity: dict[str, Any]) -> dict[str, Any]:
    bridge = latest_ibkr_connection_status(active)
    account_selected = bool(active.get("account_scope") or active.get("account_alias"))
    missing = []
    if not account_selected:
        missing.append("ACCOUNT_NOT_SELECTED")
    if not bridge.get("available"):
        missing.append("IBKR_NOT_CONNECTED")
    if not snapshot.get("available"):
        missing.append("SNAPSHOT_MISSING")
    if not capacity.get("available"):
        missing.append("IBKR_CAPACITY_NOT_REFRESHED")
    return {
        "ready": not missing,
        "missing": missing,
        "ibkr_connected": bool(bridge.get("available")),
        "bridge_published": bool(bridge.get("published")),
        "bridge_status": bridge.get("status") or "",
        "bridge_generated_at": bridge.get("generated_at") or "",
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
    iv = contract.get("iv")
    iv_rank = contract.get("iv_rank")
    vol_context = contract.get("volatility_context") if isinstance(contract.get("volatility_context"), dict) else {}
    premium_state = vol_context.get("premium_state") or "N/D"
    has_contract = any(value not in [None, "", "None"] for value in [strike, expiration, dte, bid, ask, mid, spread, delta, iv, iv_rank])
    if not has_contract:
        return "Contrato: pendiente de datos"
    return (
        "Contrato: strike {strike} | exp {expiration} | DTE {dte} | bid/ask {bid}/{ask} | mid {mid} | spread {spread} | delta {delta} | IV {iv} | IVR {iv_rank} | prima {premium_state}"
    ).format(
        strike=compact_contract_value(strike),
        expiration=compact_contract_value(expiration),
        dte=compact_contract_value(dte),
        bid=compact_contract_value(bid),
        ask=compact_contract_value(ask),
        mid=compact_contract_value(mid),
        spread=compact_contract_value(spread, "%"),
        delta=compact_contract_value(delta),
        iv=compact_volatility_value(iv),
        iv_rank=compact_contract_value(iv_rank),
        premium_state=compact_contract_value(premium_state),
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
    vol_context = contract.get("volatility_context") if isinstance(contract.get("volatility_context"), dict) else {}
    premium_state = str(vol_context.get("premium_state") or "").upper()
    iv = console_float_or_none(contract.get("iv") or vol_context.get("iv"))
    iv_rank = console_float_or_none(contract.get("iv_rank") or vol_context.get("iv_rank"))
    volatility_ok = premium_state in {"FAIR", "RICH"} or (iv_rank is not None and iv_rank >= 35) or (iv is not None and iv >= 0.18)
    volatility_note = (
        "prima " + premium_state.lower()
        if premium_state
        else ("IV/IVR presente" if iv is not None or iv_rank is not None else "falta IV/IV rank")
    )
    risk_ok = severity != "RISK" and state != "RISK_BLOCKED" and not str(alert.get("risk_blocker") or "")
    score_ok = any(alert.get(field) not in [None, "", "None"] for field in ["setup_validity_pct", "conviction_score", "ranking_score", "raw_score"])
    return [
        ("Score", score_ok, "score/conviccion visible" if score_ok else "falta score visible"),
        ("Tecnico", technical_ok, "confirmado o esperando mercado" if technical_ok else "falta confirmacion tecnica"),
        ("Opciones", options_ok, "strike/DTE/delta presentes" if options_ok else "contrato incompleto"),
        ("Volatilidad", volatility_ok, volatility_note),
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


def render_alert_lifecycle_line(alert: dict[str, Any]) -> str:
    lifecycle = shared_alert_lifecycle.alert_lifecycle_state(alert)
    expires = lifecycle.get("expires_at") or "sin hora"
    age = lifecycle.get("age_minutes")
    age_label = "edad n/d" if age is None else f"{age} min"
    completeness = lifecycle.get("contract_completeness") if isinstance(lifecycle.get("contract_completeness"), dict) else {}
    return (
        "Vigencia: {state} | TTL {ttl} min | vence {expires} | {age} | "
        "Backtesting: {bucket} | contrato {contract_score}% | paper {paper} | IBKR real {real}"
    ).format(
        state=html_escape(lifecycle.get("lifecycle_state") or "UNKNOWN"),
        ttl=html_escape(lifecycle.get("ttl_minutes")),
        expires=html_escape(expires),
        age=html_escape(age_label),
        bucket=html_escape(lifecycle.get("backtesting_bucket") or "UNKNOWN"),
        contract_score=html_escape(completeness.get("score")),
        paper="si" if lifecycle.get("paper_tracking_allowed") else "no",
        real="si" if lifecycle.get("ibkr_real_performance_allowed") else "no",
    )


def alert_quality_score(alert: dict[str, Any]) -> float:
    values = [
        console_float_or_none(alert.get("setup_validity_pct")),
        console_float_or_none(alert.get("conviction_score")),
        console_float_or_none(alert.get("ranking_score")),
        console_float_or_none(alert.get("evidence_quality_score")),
        console_float_or_none((alert.get("alert_lifecycle") if isinstance(alert.get("alert_lifecycle"), dict) else {}).get("contract_completeness", {}).get("score") if isinstance((alert.get("alert_lifecycle") if isinstance(alert.get("alert_lifecycle"), dict) else {}).get("contract_completeness"), dict) else None),
    ]
    clean = [value for value in values if value is not None]
    if not clean:
        return 0.0
    normalized = [min(max(value, 0.0), 100.0) for value in clean]
    return round(max(normalized), 2)


def is_intraday_futures_alert(alert: dict[str, Any]) -> bool:
    strategy = str(alert.get("strategy") or "").upper()
    ticker = str(alert.get("ticker") or alert.get("symbol") or "").upper()
    return strategy == "INTRADAY_INDEX_FUTURES" or ticker in {"MNQ", "MNQ1!", "NQ", "MES", "MES1!", "ES"}


def alert_operator_visibility(alert: dict[str, Any]) -> str:
    state = str(alert.get("state") or alert.get("final_state") or "").upper()
    severity = str(alert.get("severity") or "").upper()
    lifecycle = alert.get("alert_lifecycle") if isinstance(alert.get("alert_lifecycle"), dict) else {}
    bucket = str(alert.get("backtesting_bucket") or lifecycle.get("backtesting_bucket") or "").upper()
    quality = alert_quality_score(alert)
    if is_intraday_futures_alert(alert):
        return "INTRADAY"
    if state in {"NO_DATA", "WAIT_ACCOUNT_CONTEXT"} or severity == "INFO" or bucket == "NOISE":
        return "DIAGNOSTIC"
    if state.startswith("WAIT_"):
        return "DIAGNOSTIC"
    if severity == "RISK" or state == "RISK_BLOCKED" or bucket == "RISK_BLOCKED":
        return "DIAGNOSTIC"
    if (severity == "ACTION" or state in {"ENTRY_READY", "MANUAL_REVIEW"}) and quality >= 80:
        return "HIGH_PROBABILITY"
    if (severity == "ACTION" or state in {"ENTRY_READY", "MANUAL_REVIEW"}) and alert.get("manual_review_ready") is True:
        return "RADAR"
    if quality >= 65 and state in {"ENTRY_READY", "MANUAL_REVIEW"}:
        return "RADAR"
    return "DIAGNOSTIC"


def alert_success_label(alert: dict[str, Any]) -> str:
    quality = alert_quality_score(alert)
    visibility = alert_operator_visibility(alert)
    if visibility == "HIGH_PROBABILITY":
        return f"Alta probabilidad ({quality:.0f}%)"
    if visibility == "RADAR":
        return f"Radar ({quality:.0f}%)"
    if visibility == "INTRADAY":
        return f"Futuros intradia ({quality:.0f}%)"
    return f"Diagnostico ({quality:.0f}%)"


def compact_alert_summary(alert: dict[str, Any]) -> str:
    return "{ticker} | {state} | {quality} | blocker {blocker}".format(
        ticker=alert.get("ticker") or "UNKNOWN",
        state=alert.get("state") or "UNKNOWN",
        quality=alert_success_label(alert),
        blocker=alert.get("main_blocker") or "NONE",
    )


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


def operator_state_message(data: dict[str, Any], account_hint: str = "") -> str:
    counts = operator_alert_counts(data)
    account = account_hint or data.get("account_alias") or data.get("account_scope") or "unknown"
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
                <input name="reason" placeholder="Ej. revisar tamano, descartar por capital, mantener watch, fill IBKR">
                <div class="fill-grid">
                  <input name="ibkr_fill_price" inputmode="decimal" placeholder="Fill IBKR si aplicada">
                  <input name="ibkr_fill_quantity" inputmode="numeric" placeholder="Contratos/cantidad">
                </div>
                <small>Paper no cuenta como real. IBKR aplicada requiere nota, fill y cantidad; nunca autoriza orden.</small>
                <div class="actions">
                  <button name="action" value="ACK_ALERT">Visto</button>
                  <button name="action" value="MARK_REVIEWING">Revisando</button>
                  <button name="action" value="MARK_WATCHLIST">Watch</button>
                  <button name="action" value="MARK_PAPER_TRACKED">Paper</button>
                  <button name="action" value="MARK_IBKR_APPLIED">IBKR aplicada</button>
                  <button name="action" value="MARK_IBKR_NOT_APPLIED">No aplicada</button>
                  <button name="action" value="MARK_MISSED">Missed</button>
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
              <div class="success-line">{success_label}</div>
              <span>{date_label}</span>
              <span>{strategy} | {severity_label} | {state}</span>
              <div class="contract-line">{contract}</div>
              <div class="economics-line">{economics}</div>
              <div class="capacity-line">{capacity}</div>
              <div class="lifecycle-line">{lifecycle}</div>
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
        success_label=html_escape(alert_success_label(alert)),
        date_label=html_escape(alert_date_label(alert)),
        severity_label=html_escape(alert.get("severity") or "UNKNOWN"),
        state=html_escape(alert.get("state") or "UNKNOWN"),
        strategy=html_escape(alert.get("strategy") or ""),
        contract=html_escape(render_alert_contract(alert)),
        economics=render_alert_economics(alert),
        capacity=render_alert_capacity(alert, account_capacity),
        lifecycle=render_alert_lifecycle_line(alert),
        why=html_escape(alert_reason_plain(alert)),
        checklist=render_alert_checklist(alert, account_capacity),
        guidance=html_escape(alert_review_guidance(alert)),
        blocker=html_escape(alert.get("main_blocker") or "NONE"),
        actions=actions_html,
    )


def render_diagnostic_alert_list(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return ""
    rows = "".join(
        "<li>{summary}</li>".format(summary=html_escape(compact_alert_summary(alert)))
        for alert in alerts[:25]
        if isinstance(alert, dict)
    )
    return """
      <details class="diagnostic-alerts">
        <summary>{count} alerta(s) ocultas por baja calidad/datos insuficientes</summary>
        <p class="muted">No se muestran como decision principal porque son `NO_DATA`, riesgo bloqueado, WAIT sin evidencia suficiente o score bajo.</p>
        <ul>{rows}</ul>
      </details>
    """.format(count=html_escape(len(alerts)), rows=rows)


def render_intraday_futures_alerts(futures_alerts: list[dict[str, Any]], operator_payload: dict[str, Any], reports: dict[str, dict[str, Any]] | None = None) -> str:
    reports = reports if isinstance(reports, dict) else {}
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    intraday = data.get("intraday_futures") if isinstance(data.get("intraday_futures"), dict) else {}
    tradingview = reports.get("tradingview") or {}
    if futures_alerts:
        cards = "".join(render_alert_card(alert, account_capacity=console_account_capacity(operator_payload, {})) for alert in futures_alerts[:4])
        body = '<div class="alert-grid">{}</div>'.format(cards)
        status = "Hay futuros intradia para revisar ahora."
    else:
        body = """
        <div class="tiles">
          <div class="tile">Sin senal intradia viva<span>No hay ENTRY/RISK de futuros en el payload actual.</span></div>
          <div class="tile">TradingView<span>{received}/{required} eventos requeridos recibidos.</span></div>
          <div class="tile">Estado<span>{status}</span></div>
        </div>
        """.format(
            received=html_escape(tradingview.get("total_received_required_event_count", 0)),
            required=html_escape(tradingview.get("total_required_logical_event_count", tradingview.get("total_required_alert_count", 0))),
            status=html_escape(intraday.get("status") or tradingview.get("status") or "sin reporte"),
        )
        status = intraday.get("message") or "Sin alertas intradia de futuros en este momento."
    return """
    <section class="panel intraday-panel">
      <div class="section-head">
        <h2>Futuros Intradia</h2>
        <p>{status}</p>
      </div>
      {body}
    </section>
    """.format(status=html_escape(status), body=body)


def render_operator_alerts(operator_payload: dict[str, Any], snapshot: dict[str, Any] | None = None, reports: dict[str, dict[str, Any]] | None = None) -> str:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    reports = reports if isinstance(reports, dict) else {}
    if not operator_payload.get("ok"):
        return """
        <section class="panel">
          <h2>Alertas V32</h2>
          <p class="muted">No pude leer el endpoint protegido: {error}. Configura READ_ACCESS_TOKEN o revisa produccion.</p>
        </section>
        """.format(error=html_escape(operator_payload.get("error") or "unknown"))
    data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    alerts = data.get("active_alerts") if isinstance(data.get("active_alerts"), list) else []
    remote_diagnostic_alerts = data.get("diagnostic_alerts") if isinstance(data.get("diagnostic_alerts"), list) else []
    next_actions = data.get("next_actions") if isinstance(data.get("next_actions"), list) else []
    account_capacity = console_account_capacity(operator_payload, snapshot)
    pending_alerts = [alert for alert in alerts if not is_handled_alert(alert)]
    handled_alerts = [alert for alert in alerts if is_handled_alert(alert)]
    futures_alerts = [alert for alert in pending_alerts if is_intraday_futures_alert(alert)]
    decision_alerts = [
        alert for alert in pending_alerts
        if alert not in futures_alerts and alert_operator_visibility(alert) in {"HIGH_PROBABILITY", "RADAR"}
    ]
    diagnostic_alerts = [
        alert for alert in pending_alerts
        if alert not in futures_alerts and alert not in decision_alerts
    ]
    diagnostic_ids = {str(alert.get("alert_id") or "") for alert in diagnostic_alerts if isinstance(alert, dict)}
    for alert in remote_diagnostic_alerts:
        if not isinstance(alert, dict):
            continue
        alert_id = str(alert.get("alert_id") or "")
        if alert_id and alert_id in diagnostic_ids:
            continue
        diagnostic_alerts.append(alert)
        if alert_id:
            diagnostic_ids.add(alert_id)
    decision_alerts = sorted(
        decision_alerts,
        key=lambda alert: (alert_operator_visibility(alert) != "HIGH_PROBABILITY", -alert_quality_score(alert)),
    )
    if not decision_alerts:
        alert_html = '<p class="empty">Sin alertas operables de alta probabilidad ahora. Datos insuficientes quedan abajo como diagnostico, no como decision.</p>'
    else:
        alert_html = "".join(render_alert_card(alert, account_capacity=account_capacity) for alert in decision_alerts[:6])
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
        "decision": len(decision_alerts),
        "futures": len(futures_alerts),
        "diagnostic": len(diagnostic_alerts),
        "closed": len(handled_alerts),
    }
    next_action = (
        "{decision} operable(s), {futures} futuro(s) intradia, {diagnostic} diagnostico(s) ocultos. Ya atendidas: {closed}. Siguiente: {label}."
    ).format(
        decision=local_counts["decision"],
        futures=local_counts["futures"],
        diagnostic=local_counts["diagnostic"],
        closed=local_counts["closed"],
        label=action.get("label") or "Sin accion inmediata",
    )
    return """
    <section class="panel operator-alerts-panel">
      <div class="section-head">
        <h2>Alertas Operables</h2>
        <p>{next_action}</p>
      </div>
      <div class="alert-grid">{alerts}</div>
      {diagnostic_alerts}
      {closed_alerts}
    </section>
    {intraday_alerts}
    """.format(
        next_action=html_escape(next_action),
        alerts=alert_html,
        diagnostic_alerts=render_diagnostic_alert_list(diagnostic_alerts),
        closed_alerts=closed_html,
        intraday_alerts=render_intraday_futures_alerts(futures_alerts, operator_payload, reports),
    )


def console_runtime_position_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    runtime_data: dict[str, Any] = {}
    newest_mtime = None
    if RUNTIME.exists():
        for path in RUNTIME.glob("*.json"):
            if not path.is_file():
                continue
            data = load_json_file(path)
            if isinstance(data, dict) and data:
                runtime_data[path.name] = data
                try:
                    mtime = path.stat().st_mtime
                    newest_mtime = mtime if newest_mtime is None else max(newest_mtime, mtime)
                except Exception:
                    pass
    snapshot_data = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else {}
    generated_at = snapshot_data.get("generated_at") or snapshot.get("generated_at") or snapshot.get("mtime")
    if newest_mtime is not None:
        try:
            generated_at = datetime.fromtimestamp(newest_mtime, timezone.utc).isoformat()
        except Exception:
            pass
    context = {
        "generated_at": generated_at,
        "runtime_data": runtime_data,
        **runtime_data,
    }
    for key in ["account_context", "account_scope", "account_alias", "technical_snapshot", "positions"]:
        if snapshot_data.get(key) not in [None, "", [], {}]:
            context[key] = snapshot_data.get(key)
    local_contexts = shared_position_context_store.load_contexts(POSITION_CONTEXTS_PATH)
    context["active_position_contexts"] = local_contexts
    context["gamma_contexts"] = shared_gamma_context_store.load_contexts(GAMMA_CONTEXTS_PATH)
    return context


def console_active_position_management(snapshot: dict[str, Any] | None = None, v31_payloads: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    snapshot = snapshot if isinstance(snapshot, dict) else latest_master_snapshot()
    v31_payloads = v31_payloads if isinstance(v31_payloads, dict) else {}
    remote_result = v31_payloads.get("active_positions") if isinstance(v31_payloads.get("active_positions"), dict) else {}
    remote = remote_result.get("data") if isinstance(remote_result.get("data"), dict) else {}
    data = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else {}
    if isinstance(data, dict):
        data = dict(data)
        data["active_position_contexts"] = shared_position_context_store.load_contexts(POSITION_CONTEXTS_PATH)
        data["gamma_contexts"] = shared_gamma_context_store.load_contexts(GAMMA_CONTEXTS_PATH)
    existing = data.get("active_position_management") if isinstance(data.get("active_position_management"), dict) else {}
    if existing.get("position_management_version"):
        local = dict(existing)
        local["source"] = "local_master_snapshot_embedded"
        local["source_path"] = snapshot.get("path") or ""
    else:
        try:
            local = shared_position_management.build_active_position_management(data)
            local["source"] = "local_master_snapshot_recalculated"
            local["source_path"] = snapshot.get("path") or ""
        except Exception as exc:
            local = {
                "position_management_version": "active_position_management_v1",
                "status": "ERROR",
                "positions_found": 0,
                "positions_requiring_review": 0,
                "risk_review_count": 0,
                "positions": [],
                "summary": {},
                "error": str(exc)[:180],
                "source": "local_master_snapshot_error",
                "not_order_instruction": True,
                "execution_authorized": False,
                "can_operate": False,
            }
    if int(local.get("positions_found") or 0) == 0:
        try:
            runtime_context = console_runtime_position_context(snapshot)
            runtime_local = shared_position_management.build_active_position_management(runtime_context)
            if int(runtime_local.get("positions_found") or 0) > 0:
                local = runtime_local
                local["source"] = "local_runtime_recalculated"
                local["source_path"] = "runtime/*.json"
        except Exception:
            pass
    remote_positions = int(remote.get("positions_found") or 0) if remote else 0
    local_positions = int(local.get("positions_found") or 0)
    if remote.get("position_management_version") and (local_positions == 0 and remote_positions > 0):
        payload = dict(remote)
        payload["source"] = "remote_v31_active_position_management"
        payload["remote_cached"] = bool(remote_result.get("cached"))
        payload["remote_error"] = remote_result.get("live_error") or remote_result.get("error") or ""
    else:
        payload = local
        payload["remote_available"] = bool(remote.get("position_management_version"))
        payload["remote_error"] = remote_result.get("live_error") or remote_result.get("error") or ""
    payload["console_endpoint"] = "/active-positions"
    payload["not_order_instruction"] = True
    payload["execution_authorized"] = False
    payload["can_operate"] = False
    try:
        state_alerts = shared_position_state_alerts.update_from_management(payload, POSITION_STATE_ALERTS_PATH)
        payload["state_change_alerts"] = {
            "state_alert_version": state_alerts.get("state_alert_version"),
            "latest_alerts": state_alerts.get("latest_alerts") or [],
            "alert_count": len(state_alerts.get("alerts") or []),
            "not_order_instruction": True,
            "execution_authorized": False,
        }
    except Exception:
        payload["state_change_alerts"] = shared_position_state_alerts.summary(POSITION_STATE_ALERTS_PATH)
    payload["management_journal"] = shared_position_management_journal.summary(POSITION_MANAGEMENT_JOURNAL_PATH)
    payload["management_journal_evaluation"] = shared_position_management_journal.evaluate_against_management(
        payload,
        path=POSITION_MANAGEMENT_JOURNAL_PATH,
    )
    return payload


def position_badge(value: Any, label: str = "") -> str:
    text = str(value or "UNKNOWN").upper()
    klass = "neutral"
    if text in {"NO_ACTION_RECOMMENDED", "MONITOR", "NO_POSITION"}:
        klass = "ok"
    elif "REFRESH" in text or "WAIT" in text:
        klass = "warn"
    elif "RISK" in text or "DEFENSIVE" in text or "ASSIGNMENT" in text:
        klass = "risk"
    elif "REVIEW" in text:
        klass = "info"
    return '<span class="badge {}">{}</span>'.format(klass, html_escape(label or friendly_operator_state(text)))


def friendly_position_reason(text: str) -> str:
    replacements = {
        "Underlying is below the short-put strike; assignment risk needs review.": "El precio está por debajo del strike de la put vendida; revisa el riesgo de asignación.",
        "Long stock is eligible for covered-call review, but no exit trigger is active.": "La posición permite evaluar un covered call, pero no existe una señal de salida activa.",
        "Bearish trend with intact support requires comparing hold, income overlays, protection, and reduction.": "La tendencia es bajista, pero el soporte sigue intacto; comparar mantener, generar prima, proteger y reducir.",
        "Long-stock thesis may be damaged by event risk or a broken support level.": "La tesis de las acciones puede estar dañada por un evento de riesgo o por ruptura de soporte.",
    }
    return replacements.get(text, text)


def render_position_alternatives(item: dict[str, Any]) -> str:
    payload = item.get("management_alternatives") if isinstance(item.get("management_alternatives"), dict) else {}
    alternatives = payload.get("alternatives") if isinstance(payload.get("alternatives"), list) else []
    if not alternatives:
        return '<div class="position-alternatives-empty">Alternativas pendientes de cálculo.</div>'
    status_labels = {
        "READY_FOR_MANUAL_REVIEW": "Lista para revisar",
        "WAIT_OPTION_CHAIN": "Falta cadena",
        "WAIT_MARKET_DATA": "Faltan datos",
        "WAIT_LIQUIDITY": "Esperar liquidez",
        "WAIT_UNDERLYING_PRICE": "Falta precio",
        "WAIT_OPTION_MARK": "Falta precio de opción",
        "NOT_AVAILABLE_ALREADY_COVERED": "Lotes ya cubiertos",
        "RISK_BLOCKED": "Bloqueada por riesgo",
        "RISK_BLOCKED_COVERAGE": "Rompería la cobertura",
    }

    def expiration_label(value: Any) -> str:
        raw = str(value or "").strip().replace("-", "")
        if len(raw) == 8 and raw.isdigit():
            months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
            try:
                return "{} {} {}".format(int(raw[6:8]), months[int(raw[4:6]) - 1], raw[:4])
            except (ValueError, IndexError):
                pass
        return str(value or "N/D")

    def variant_structure(value: dict[str, Any]) -> str:
        call = value.get("contract") if isinstance(value.get("contract"), dict) else {}
        put = value.get("put_contract") if isinstance(value.get("put_contract"), dict) else {}
        parts = []
        if call.get("strike") is not None:
            parts.append("C{}".format(call.get("strike")))
        if put.get("strike") is not None:
            parts.append("P{}".format(put.get("strike")))
        expiration = call.get("expiration") or put.get("expiration")
        contracts = value.get("contracts")
        if not parts:
            return "—"
        return "{} · {}{}".format(
            " / ".join(parts),
            expiration_label(expiration),
            (" · {} contrato(s)".format(contracts)) if contracts else "",
        )

    def card(alternative: dict[str, Any]) -> str:
        candidates = alternative.get("contract_candidates") if isinstance(alternative.get("contract_candidates"), list) else []
        contract = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        contract_text = ""
        if contract:
            contract_text = "Mejor contrato visible: {right} {strike} · {expiration} · {moneyness} · prima {premium}".format(
                right=contract.get("right") or "",
                strike=contract.get("strike") if contract.get("strike") is not None else "N/D",
                expiration=contract.get("expiration") or "N/D",
                moneyness=contract.get("moneyness") or "N/D",
                premium=coberturas_money(contract.get("premium_per_contract")),
            )
        effects = alternative.get("effects") if isinstance(alternative.get("effects"), list) else []
        return """
          <div class="position-alternative {primary}">
            <div><b>{label}</b><span>{status}</span></div>
            <p>{reason}</p>
            <small>{contracts}{contract}{effects}</small>
          </div>
        """.format(
            primary="alternative-primary" if alternative.get("is_primary_management_path") else "",
            label=html_escape(alternative.get("label") or alternative.get("alternative_id") or "Alternativa"),
            status=html_escape(status_labels.get(str(alternative.get("status") or ""), friendly_operator_state(alternative.get("status")))),
            reason=html_escape(alternative.get("reason") or ""),
            contracts=html_escape(("Hasta {} contrato(s). ".format(alternative.get("contracts"))) if alternative.get("contracts") is not None else ""),
            contract=html_escape((contract_text + ". ") if contract_text else ""),
            effects=html_escape("Efectos: " + "; ".join(str(value) for value in effects[:3]) if effects else ""),
        )

    recommendation = payload.get("recommendation") if isinstance(payload.get("recommendation"), dict) else {}
    comparison = payload.get("strategy_comparison") if isinstance(payload.get("strategy_comparison"), dict) else {}
    primary_id = recommendation.get("alternative_id")
    primary = next((value for value in alternatives if isinstance(value, dict) and value.get("alternative_id") == primary_id), alternatives[0])
    contract = recommendation.get("contract") if isinstance(recommendation.get("contract"), dict) else {}
    put_contract = recommendation.get("put_contract") if isinstance(recommendation.get("put_contract"), dict) else {}
    structure_html = ""
    if contract:
        contracts = int(console_float_or_none(recommendation.get("contracts")) or 0)
        covered_shares = contracts * 100
        total_shares = int(console_float_or_none(comparison.get("shares")) or 0)
        free_shares = max(0, total_shares - covered_shares) if total_shares else None
        call_value = contract.get("bid_per_contract") if contract.get("bid_per_contract") is not None else contract.get("premium_per_contract")
        put_value = put_contract.get("ask_per_contract") if put_contract.get("ask_per_contract") is not None else put_contract.get("premium_per_contract")
        net_per_share = None
        if console_float_or_none(contract.get("bid")) is not None:
            net_per_share = console_float_or_none(contract.get("bid"))
            if put_contract and console_float_or_none(put_contract.get("ask")) is not None:
                net_per_share -= console_float_or_none(put_contract.get("ask")) or 0.0
        net_total = net_per_share * covered_shares if net_per_share is not None and covered_shares else None
        put_leg = ""
        if put_contract:
            put_leg = """
              <div class="position-structure-leg protection-leg">
                <span>2 · Comprar put protectora</span>
                <b>P {put_strike} · vence {put_expiration}</b>
                <small>Ask usado: {put_cost} por contrato</small>
              </div>
            """.format(
                put_strike=html_escape(put_contract.get("strike") if put_contract.get("strike") is not None else "N/D"),
                put_expiration=html_escape(expiration_label(put_contract.get("expiration"))),
                put_cost=html_escape(coberturas_money(put_value)),
            )
        structure_html = """
          <div class="position-structure">
            <div class="position-structure-title"><b>Estructura propuesta</b><span>{contracts} contratos · {covered} acciones · {coverage}%</span></div>
            <div class="position-structure-grid">
              <div class="position-structure-leg income-leg">
                <span>1 · Vender call cubierta</span>
                <b>C {call_strike} · vence {call_expiration}</b>
                <small>Bid usado: {call_credit} por contrato</small>
              </div>
              {put_leg}
            </div>
            <div class="position-structure-result">
              <span>{net}</span>
              <small>{free}</small>
            </div>
          </div>
        """.format(
            contracts=html_escape(contracts or "N/D"),
            covered=html_escape(covered_shares or "N/D"),
            coverage=html_escape(recommendation.get("coverage_pct") or "N/D"),
            call_strike=html_escape(contract.get("strike") if contract.get("strike") is not None else "N/D"),
            call_expiration=html_escape(expiration_label(contract.get("expiration"))),
            call_credit=html_escape(coberturas_money(call_value)),
            put_leg=put_leg,
            net=html_escape(
                "Crédito neto estimado: {} por acción cubierta · {} total".format(
                    coberturas_money(net_per_share), coberturas_money(net_total)
                ) if net_per_share is not None else "Prima/costo neto pendiente"
            ),
            free=html_escape(
                "{} acciones permanecen sin esta estructura y conservan toda su exposición.".format(free_shares)
                if free_shares is not None else "Revisar las acciones restantes antes de ejecutar."
            ),
        )
    profile_labels = {
        "capital_protection": "Mayor protección",
        "balanced": "Mejor balance",
        "income_recovery": "Prima y recuperación",
        "upside_preservation": "Mayor subida",
    }
    leaders = comparison.get("profile_leaders") if isinstance(comparison.get("profile_leaders"), dict) else {}
    leader_cards = []
    seen_leaders = set()
    for profile_id, profile_label in profile_labels.items():
        leader = leaders.get(profile_id) if isinstance(leaders.get(profile_id), dict) else {}
        leader_key = (profile_id, leader.get("variant_id"))
        if not leader or leader_key in seen_leaders:
            continue
        seen_leaders.add(leader_key)
        leader_cards.append(
            '<div class="position-profile"><span>{}</span><b>{}</b><small>{}</small><small>Peor escenario {} · lateral {}</small></div>'.format(
                html_escape(profile_label),
                html_escape(leader.get("label") or leader.get("alternative_id") or "N/D"),
                html_escape(variant_structure(leader)),
                html_escape(coberturas_money(leader.get("worst_case_pnl"))),
                html_escape(coberturas_money(leader.get("flat_pnl"))),
            )
        )
    variants = comparison.get("variants") if isinstance(comparison.get("variants"), list) else []
    comparison_rows = []
    displayed_ids = set()
    for variant in variants:
        if not isinstance(variant, dict) or variant.get("alternative_id") in displayed_ids:
            continue
        displayed_ids.add(variant.get("alternative_id"))
        comparison_rows.append(
            "<tr><td>{label}</td><td>{structure}</td><td>{support}</td><td>{flat}</td><td>{resistance}</td><td>{worst}</td></tr>".format(
                label=html_escape(variant.get("label") or variant.get("alternative_id") or "N/D"),
                structure=html_escape(variant_structure(variant)),
                support=html_escape(coberturas_money(variant.get("support_pnl"))),
                flat=html_escape(coberturas_money(variant.get("flat_pnl"))),
                resistance=html_escape(coberturas_money(variant.get("resistance_pnl"))),
                worst=html_escape(coberturas_money(variant.get("worst_case_pnl"))),
            )
        )
    comparison_html = ""
    if comparison.get("available") and leader_cards:
        comparison_html = """
        <div class="position-comparison">
          <div class="position-profile-grid">{leaders}</div>
          <details>
            <summary>Ver comparación numérica y supuestos</summary>
            <div class="position-comparison-scroll"><table><thead><tr><th>Alternativa</th><th>Estructura</th><th>Soporte</th><th>Lateral</th><th>Resistencia</th><th>Peor caso</th></tr></thead><tbody>{rows}</tbody></table></div>
            <small>Estimación desde el precio actual; usa bid para calls vendidas y ask para puts compradas. No incluye comisiones ni impuestos. Las ponderaciones son de revisión, no probabilidades.</small>
          </details>
        </div>
        """.format(leaders="".join(leader_cards), rows="".join(comparison_rows))
    secondary = [value for value in alternatives if isinstance(value, dict) and value.get("alternative_id") != primary_id]
    more = '<details class="position-alternatives-more"><summary>Ver otras {} posibilidades</summary>{}</details>'.format(
        len(secondary),
        "".join(card(value) for value in secondary),
    ) if secondary else ""
    return """
      <div class="position-alternatives">
        <div class="position-alternatives-head"><b>Recomendación del motor</b><span>Confianza {confidence}</span></div>
        <div class="position-recommendation">
          <div><b>{label}</b><span>{status}</span></div>
          <p>{reason}</p>
          {structure}
        </div>
        {comparison}
        {more}
      </div>
    """.format(
        confidence=html_escape(recommendation.get("confidence") or "LOW"),
        label=html_escape(recommendation.get("label") or primary.get("label") or "Mantener y monitorear"),
        status=html_escape(status_labels.get(str(recommendation.get("status") or primary.get("status") or ""), friendly_operator_state(recommendation.get("status") or primary.get("status")))),
        reason=html_escape(recommendation.get("reason") or primary.get("reason") or ""),
        structure=structure_html,
        comparison=comparison_html,
        more=more,
    )


def render_position_management_card(item: dict[str, Any], acknowledged_event: dict[str, Any] | None = None) -> str:
    technical = item.get("technical") if isinstance(item.get("technical"), dict) else {}
    thesis = item.get("thesis") if isinstance(item.get("thesis"), dict) else {}
    reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
    warnings = item.get("warnings") if isinstance(item.get("warnings"), list) else []
    blockers = item.get("blockers") if isinstance(item.get("blockers"), list) else []
    reason_text = "; ".join(friendly_position_reason(str(x)) for x in (reasons[:2] or warnings[:2] or blockers[:2])) or "Sin nota adicional."
    stock_position = str(item.get("sec_type") or "").upper() in {"STK", "STOCK", "EQUITY"}
    strike_value = console_float_or_none(item.get("strike"))
    contract_bits = [
        item.get("strategy"),
        item.get("sec_type"),
        ("qty " + str(item.get("position_size"))) if item.get("position_size") is not None else "",
        ("strike " + str(item.get("strike"))) if not stock_position and strike_value not in [None, 0.0] else "",
        ("DTE " + str(item.get("dte"))) if item.get("dte") is not None else "",
    ]
    market_bits = [
        "trend=" + str(technical.get("trend") or "UNKNOWN"),
        "precio=" + str(item.get("underlying_price") or "pendiente"),
        "soporte=" + str(technical.get("support") or "pendiente"),
        "resistencia=" + str(technical.get("resistance") or "pendiente"),
        "gamma=" + ("OK" if technical.get("gamma_available") else "pendiente"),
    ]
    primary_action = friendly_operator_state(item.get("management_action"))
    needs_attention = any(word in str(item.get("management_action") or "").upper() for word in ("RISK", "ASSIGNMENT", "DEFENSIVE", "REVIEW"))
    management_fingerprint = shared_position_management_journal.management_fingerprint(item)
    action_upper = str(item.get("management_action") or "").upper()
    if acknowledged_event:
        review_control = '<div class="position-review-confirmed"><b>Revisión registrada</b><span>Volverá a pendientes sólo si cambia la posición o la recomendación.</span></div>'
    elif action_upper == "REFRESH_DATA":
        review_control = '<div class="position-data-required"><b>Esta pendiente requiere datos, no sólo confirmación.</b><span>Actualiza IBKR; si los datos quedan completos desaparecerá automáticamente.</span><a href="#position-refresh">Ir a actualizar datos</a></div>'
    else:
        review_control = """
        <form method="post" action="/position-management-event" class="position-review-control" data-busy="Registrando revisión" data-busy-detail="Marca esta lectura como revisada. No ejecuta órdenes.">
          <input type="hidden" name="position_id" value="{position_id}">
          <input type="hidden" name="ticker" value="{ticker}">
          <input type="hidden" name="strategy" value="{strategy}">
          <input type="hidden" name="recommended_action" value="{action}">
          <input type="hidden" name="recommended_state" value="{state}">
          <input type="hidden" name="management_fingerprint" value="{fingerprint}">
          <button name="operator_action" value="REVIEW_COMPLETED">Marcar revisión completada</button>
          <small>No ejecuta la recomendación; sólo confirma que ya la evaluaste.</small>
        </form>
        """.format(
            position_id=html_escape(item.get("position_id") or ""),
            ticker=html_escape(item.get("ticker") or ""),
            strategy=html_escape(item.get("strategy") or ""),
            action=html_escape(item.get("management_action") or ""),
            state=html_escape(item.get("exit_state") or ""),
            fingerprint=html_escape(management_fingerprint),
        )
    return """
    <article class="alert-card position-card">
      <div class="alert-title"><strong>{ticker}</strong><em>{action}</em></div>
      <div class="review-line">{reason}</div>
      <p class="position-summary">{contract}</p>
      {alternatives}
      {review_control}
      <details class="position-details"{open_attr}>
        <summary>Ver detalles y registrar gestión</summary>
        <div class="position-detail-grid">
          <div><span>Estado</span><strong>{state}</strong></div>
          <div><span>Prima capturada</span><strong>{capture}</strong></div>
          <div><span>P&amp;L</span><strong>{pnl}</strong></div>
          <div><span>Peso</span><strong>{weight}</strong></div>
        </div>
        <p class="capacity-line">{market}</p>
        <details class="diagnostic-alerts">
          <summary>Editar tesis y datos de entrada</summary>
        <form method="post" action="/position-context" class="alert-actions" data-busy="Guardando tesis de posicion" data-busy-detail="Actualiza contexto local para el motor. No ejecuta ordenes.">
          <input type="hidden" name="position_id" value="{position_id}">
          <input type="hidden" name="ticker" value="{ticker_raw}">
          <input type="hidden" name="strategy" value="{strategy_raw}">
          <label>Tesis / razon de entrada</label>
          <input name="thesis_text" value="{thesis_text}" placeholder="Ej. soporte intacto, prima vendida por IV alta">
          <div class="fill-grid">
            <input name="invalidation_level" value="{invalidation}" placeholder="Invalidacion / soporte clave">
            <input name="target" value="{target}" placeholder="Target / captura">
          </div>
          <div class="fill-grid">
            <input name="entry_credit" value="{entry_credit}" placeholder="Credito entrada">
            <input name="entry_date" value="{entry_date}" placeholder="Fecha entrada YYYY-MM-DD">
          </div>
          <input name="roll_plan" value="{roll_plan}" placeholder="Plan de roll / asignacion">
          <p><button>Guardar tesis</button></p>
        </form>
        </details>
        <form method="post" action="/position-management-event" class="alert-actions" data-busy="Registrando gestion de posicion" data-busy-detail="Guarda bitacora local. No ejecuta ordenes.">
          <input type="hidden" name="position_id" value="{position_id}">
          <input type="hidden" name="ticker" value="{ticker_raw}">
          <input type="hidden" name="strategy" value="{strategy_raw}">
          <input type="hidden" name="recommended_action" value="{recommended_action}">
          <input type="hidden" name="recommended_state" value="{recommended_state}">
          <input type="hidden" name="management_fingerprint" value="{management_fingerprint}">
          <label>Nota de revisión</label>
          <input name="operator_reason" placeholder="Qué revisaste y por qué">
          <div class="actions">
            <button class="secondary" name="operator_action" value="NO_ACTION_TAKEN">Mantener sin cambios</button>
            <button name="operator_action" value="ASSIGNMENT_REVIEWED">Revisé asignación</button>
            <details class="advanced-actions"><summary>Más acciones</summary>
              <button name="operator_action" value="MANUAL_CLOSE_REVIEWED">Revisé cierre</button>
              <button name="operator_action" value="MANUAL_ROLL_REVIEWED">Revisé roll</button>
              <button name="operator_action" value="RISK_REDUCTION_REVIEWED">Revisé reducción de riesgo</button>
              <button class="secondary" name="operator_action" value="DATA_REFRESHED">Datos actualizados</button>
            </details>
          </div>
        </form>
        <details class="technical-details"><summary>Ver diagnóstico técnico</summary><small>Advertencias: {warnings} · Bloqueadores: {blockers}</small></details>
      </details>
    </article>
    """.format(
        ticker=html_escape(item.get("ticker") or "UNKNOWN"),
        ticker_raw=html_escape(item.get("ticker") or ""),
        position_id=html_escape(item.get("position_id") or ""),
        strategy_raw=html_escape(item.get("strategy") or ""),
        recommended_action=html_escape(item.get("management_action") or ""),
        recommended_state=html_escape(item.get("exit_state") or ""),
        management_fingerprint=html_escape(management_fingerprint),
        thesis_text=html_escape(thesis.get("text") or ""),
        invalidation=html_escape(thesis.get("invalidation_level") or ""),
        target=html_escape(thesis.get("target") or ""),
        entry_credit=html_escape(item.get("entry_credit") or ""),
        entry_date=html_escape(item.get("entry_date") or ""),
        roll_plan=html_escape(thesis.get("roll_plan") or ""),
        action=position_badge(item.get("management_action"), primary_action),
        state=position_badge(item.get("exit_state")),
        open_attr=" open" if needs_attention else "",
        contract=html_escape(" | ".join(str(bit) for bit in contract_bits if bit not in [None, ""])),
        capture=html_escape(str(item.get("premium_capture_pct") if item.get("premium_capture_pct") is not None else "pendiente")),
        pnl=html_escape(str(item.get("unrealized_pl") if item.get("unrealized_pl") is not None else "pendiente")),
        weight=html_escape(str(item.get("portfolio_weight_pct") if item.get("portfolio_weight_pct") is not None else "pendiente")),
        market=html_escape(" | ".join(market_bits)),
        reason=html_escape(reason_text),
        alternatives=render_position_alternatives(item),
        review_control=review_control,
        warnings=html_escape(", ".join(str(x) for x in warnings[:4]) or "none"),
        blockers=html_escape(", ".join(str(x) for x in blockers[:4]) or "none"),
    )


def render_active_positions_panel(
    snapshot: dict[str, Any],
    v31_payloads: dict[str, dict[str, Any]],
    active: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> str:
    payload = payload if isinstance(payload, dict) else console_active_position_management(snapshot, v31_payloads)
    journal_summary = shared_position_management_journal.summary(POSITION_MANAGEMENT_JOURNAL_PATH)
    journal_evaluation = shared_position_management_journal.evaluate_against_management(payload, path=POSITION_MANAGEMENT_JOURNAL_PATH)
    positions = payload.get("positions") if isinstance(payload.get("positions"), list) else []
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    freshness = payload.get("freshness") if isinstance(payload.get("freshness"), dict) else {}
    portfolio_risk = payload.get("portfolio_risk") if isinstance(payload.get("portfolio_risk"), dict) else {}
    battle_plan = payload.get("battle_plan") if isinstance(payload.get("battle_plan"), dict) else {}
    state_alerts = payload.get("state_change_alerts") if isinstance(payload.get("state_change_alerts"), dict) else {}
    top_step = battle_plan.get("top_step") if isinstance(battle_plan.get("top_step"), dict) else {}
    alias = active.get("account_alias") or ""
    disabled = "" if alias else " disabled"
    acknowledged_positions = shared_position_management_journal.acknowledged_position_reviews(
        payload,
        path=POSITION_MANAGEMENT_JOURNAL_PATH,
    )
    if positions:
        priority = lambda item: 0 if any(word in str((item or {}).get("management_action") or "").upper() for word in ("RISK", "ASSIGNMENT", "DEFENSIVE", "REVIEW")) else 1
        cards = "".join(
            render_position_management_card(item, acknowledged_positions.get(str(item.get("position_id") or "")))
            for item in sorted(positions, key=priority)[:8]
            if isinstance(item, dict)
        )
    else:
        cards = """
        <div class="tiles">
          <div class="tile">Sin posiciones activas detectadas<span>Corre Refresh IBKR para leer posiciones del broker.</span></div>
          <div class="tile">Fuente<span>{source}</span></div>
        </div>
        """.format(source=html_escape(payload.get("source") or "sin fuente"))
    alert_rows = "".join(
        "<li><strong>{ticker}</strong><small>{old} -> {new}</small></li>".format(
            ticker=html_escape(alert.get("ticker") or "UNKNOWN"),
            old=html_escape(alert.get("from_management_action") or "NONE"),
            new=html_escape(alert.get("to_management_action") or "NONE"),
        )
        for alert in (state_alerts.get("latest_alerts") or [])[:5]
        if isinstance(alert, dict)
    )
    alerts_html = ""
    if alert_rows:
        alerts_html = """
        <div class="daily-open-summary summary-amber">
          <h3>Cambios de estado detectados</h3>
          <ol class="timeline">{rows}</ol>
        </div>
        """.format(rows=alert_rows)
    next_text = "Sin acción inmediata; mantener monitoreo." if not payload.get("manual_review_required") else "Hay posiciones que requieren revisión manual."
    if summary.get("top_action"):
        next_text = "{} Prioridad: {} — {}.".format(
            next_text,
            summary.get("top_ticker") or "N/D",
            friendly_operator_state(summary.get("top_action")),
        )
    return """
    <section class="panel positions-panel">
      <div class="section-head">
        <h2>Posiciones activas</h2>
        <p>{next_text}</p>
      </div>
      <div class="position-overview">
        <div><span>Posiciones</span><strong>{positions_found}</strong><small>{review_count} requieren revisión</small></div>
        <div><span>Riesgo inmediato</span><strong>{risk_count}</strong><small>{portfolio_status}</small></div>
        <div><span>Datos</span><strong>{freshness}</strong><small>{age}</small></div>
        <div><span>Seguimiento</span><strong>{pending_followup}</strong><small>pendiente(s)</small></div>
      </div>
      <div class="alert-grid">{cards}</div>
      {alerts_html}
      <form id="position-refresh" method="post" action="/bridge" class="hero-actions" data-busy="Refrescando posiciones IBKR" data-busy-detail="Lee broker, posiciones, opciones y publica snapshot. No ejecuta ordenes.">
        <input name="alias" value="{alias}" type="hidden">
        <button{disabled}>Refresh posiciones IBKR</button>
        <span>Úsalo cuando la consola indique datos desactualizados o incompletos.</span>
      </form>
    </section>
    """.format(
        next_text=html_escape(next_text),
        positions_found=html_escape(payload.get("positions_found", 0)),
        review_count=html_escape(payload.get("positions_requiring_review", 0)),
        risk_count=html_escape(payload.get("risk_review_count", 0)),
        portfolio_status=html_escape(portfolio_risk.get("status") or "UNKNOWN"),
        freshness=html_escape(friendly_operator_state(freshness.get("status") or "UNKNOWN")),
        age=html_escape(friendly_age(payload.get("generated_at"))),
        journal_count=html_escape(journal_summary.get("event_count", 0)),
        pending_followup=html_escape(journal_evaluation.get("pending_followup_count", 0)),
        cards=cards,
        alerts_html=alerts_html,
        alias=html_escape(alias),
        disabled=disabled,
    )


def render_gamma_context_panel(position_payload: dict[str, Any] | None = None) -> str:
    summary = shared_gamma_context_store.summary(GAMMA_CONTEXTS_PATH)
    latest = summary.get("latest_context") if isinstance(summary.get("latest_context"), dict) else {}
    positions = position_payload.get("positions") if isinstance(position_payload, dict) and isinstance(position_payload.get("positions"), list) else []
    tickers = sorted({str(item.get("ticker") or "").upper() for item in positions if isinstance(item, dict) and item.get("ticker")})
    ticker_options = "".join('<option value="{}">{}</option>'.format(html_escape(ticker), html_escape(ticker)) for ticker in tickers)
    return """
    <section class="panel embedded-support-panel">
      <div class="section-head">
        <h2>Contexto técnico complementario</h2>
        <p>Pega el mismo tipo de JSON usado para RSP en cualquier activo abierto. Soportes, resistencias, rango esperado y gamma complementan la lectura automática.</p>
      </div>
      <div class="tiles compact-status">
        <div class="tile">Tickers<span>{tickers}</span></div>
        <div class="tile">Ultimo<span>{latest}</span></div>
      </div>
      <form method="post" action="/gamma-context" class="hero-actions" data-busy="Guardando gamma manual" data-busy-detail="Actualiza runtime/gamma_contexts.json. No ejecuta ordenes.">
        <select name="ticker" required><option value="">Selecciona posición</option>{ticker_options}</select>
        <textarea name="gamma_blob" placeholder="Pega aquí el JSON o texto con spot, soportes, resistencias, expected move, call wall, put wall y sesgo gamma."></textarea>
        <input name="gamma_wall" placeholder="Gamma wall">
        <input name="call_wall" placeholder="Call wall">
        <input name="put_wall" placeholder="Put wall">
        <input name="zero_gamma" placeholder="Zero gamma">
        <input name="notes" placeholder="Notas / fuente">
        <button>Guardar contexto del activo</button>
      </form>
    </section>
    """.format(
        tickers=html_escape(", ".join(summary.get("tickers") or []) or "sin gamma manual"),
        latest=html_escape((latest.get("ticker") or "N/D") + " " + str(latest.get("as_of") or "")),
        ticker_options=ticker_options,
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
                <p class="muted">Boton recomendado: alinea cuenta y publica contexto rapido. El refresh profundo de IBKR queda en Avanzado.</p>
              </div>
              <div class="actions">
                <form method="post" action="/select-refresh" data-busy="Alineando cuenta rapido" data-busy-detail="Selecciona cuenta y publica contexto para GPT sin escanear opciones. No autoriza ordenes."><input name="alias" value="{alias}" type="hidden"><button>Alinear cuenta rapido</button></form>
                <details class="advanced-actions">
                  <summary>Avanzado</summary>
                  <form method="post" action="/select" data-busy="Publicando cuenta para GPT" data-busy-detail="Solo publica la cuenta para GPT; no conecta con IBKR."><input name="alias" value="{alias}" type="hidden"><button class="secondary">Solo usar cuenta</button></form>
                  <form method="post" action="/account-capacity" data-busy="Leyendo capacidad IBKR" data-busy-detail="Lee solo AccountSummary de la cuenta seleccionada y publica margen/capital disponible."><input name="alias" value="{alias}" type="hidden"><button class="secondary">Solo capacidad</button></form>
                  <form method="post" action="/bridge" data-busy="Refresh profundo IBKR" data-busy-detail="Escanea broker/opciones con timeout corto. Si no termina, no invalida el contexto publicado."><input name="alias" value="{alias}" type="hidden"><button class="secondary">Refresh IBKR corto</button></form>
                  <form method="post" action="/bridge-deep" data-busy="Refresh profundo largo" data-busy-detail="Escaneo IBKR/opciones con mayor timeout. Usalo solo cuando TWS este estable y necesites contratos frescos."><input name="alias" value="{alias}" type="hidden"><button class="secondary">Refresh profundo opciones</button></form>
                  <form method="post" action="/daily-open" data-busy="Daily open en curso" data-busy-detail="Ejecutando checklist local de apertura."><input name="alias" value="{alias}" type="hidden"><button class="secondary">Daily open</button></form>
                </details>
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


def is_daily_open_result(result: dict[str, Any]) -> bool:
    return "daily_open_checklist.py" in str(result.get("command") or "")


def effective_daily_open_status(report: dict[str, Any]) -> str:
    status = str(report.get("status") or "UNKNOWN")
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    foundation = checks.get("foundation_health") if isinstance(checks.get("foundation_health"), dict) else {}
    mechanics_ok = all(
        isinstance(report.get(key), dict) and report[key].get("ok") is True
        for key in ["refresh_step", "capacity_refresh_step", "rsp_refresh_step", "coberturas_rsp", "publish_step"]
    )
    production_ok = (checks.get("production_auth") or {}).get("ok") is True and (checks.get("v32_operator_today") or {}).get("ok") is True
    if status == "ACTION_REQUIRED" and mechanics_ok and production_ok and foundation.get("status") == "FAIL":
        return "EVIDENCE_COLLECTION_ONLY"
    return status


def status_word(ok: Any, good: str = "OK", bad: str = "REVISAR") -> str:
    if ok is True:
        return good
    if ok is False:
        return bad
    return "N/D"


def render_daily_open_summary(result: dict[str, Any]) -> str:
    if not is_daily_open_result(result):
        return ""
    report = load_json_file(DAILY_OPEN_CHECKLIST_PATH)
    if not report:
        return """
        <div class="warning">Apertura diaria no dejo reporte estructurado. Revisa el detalle tecnico antes de asumir que termino bien.</div>
        """
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    canslim = report.get("canslim_step") if isinstance(report.get("canslim_step"), dict) else {}
    refresh = report.get("refresh_step") if isinstance(report.get("refresh_step"), dict) else {}
    capacity_refresh = report.get("capacity_refresh_step") if isinstance(report.get("capacity_refresh_step"), dict) else {}
    rsp_refresh = report.get("rsp_refresh_step") if isinstance(report.get("rsp_refresh_step"), dict) else {}
    rsp = report.get("coberturas_rsp") if isinstance(report.get("coberturas_rsp"), dict) else {}
    publish = report.get("publish_step") if isinstance(report.get("publish_step"), dict) else {}
    ibkr_port = checks.get("ibkr_port") if isinstance(checks.get("ibkr_port"), dict) else {}
    production_auth = checks.get("production_auth") if isinstance(checks.get("production_auth"), dict) else {}
    operator_today = checks.get("v32_operator_today") if isinstance(checks.get("v32_operator_today"), dict) else {}
    foundation = checks.get("foundation_health") if isinstance(checks.get("foundation_health"), dict) else {}
    evidence = checks.get("operational_evidence_gate") if isinstance(checks.get("operational_evidence_gate"), dict) else {}
    text = "\n".join([
        str(refresh.get("stdout_tail") or ""),
        str(publish.get("stdout_tail") or ""),
        str(result.get("stdout_tail") or ""),
        str(result.get("stderr_tail") or ""),
    ])
    ibkr_detail = "TWS/API alcanzable" if ibkr_port.get("ok") else "TWS/API no alcanzable"
    if refresh.get("ok"):
        ibkr_status = "OK"
        ibkr_detail = "Bridge completo."
    elif "IBKR conectado correctamente" in text and "positions request timed out" in text:
        ibkr_status = "PARCIAL"
        ibkr_detail = "Conecto y leyo precios; posiciones/portfolio no respondieron."
    elif refresh.get("error"):
        ibkr_status = "REVISAR"
        ibkr_detail = str(refresh.get("error"))
    else:
        ibkr_status = status_word(refresh.get("ok"))
    publish_detail = "Snapshot publicado." if publish.get("ok") else (str(publish.get("error") or "Render/publicacion no confirmo a tiempo."))
    if "The read operation timed out" in str(publish.get("stdout_tail") or ""):
        publish_detail = "Render recibio solicitud, pero no confirmo respuesta antes del timeout."
    gpt_status = result.get("remote_verification_status") or ("OK" if operator_today.get("ok") else "NO CONFIRMADO")
    overall = effective_daily_open_status(report)
    overall_label = "ACUMULANDO EVIDENCIA" if overall == "EVIDENCE_COLLECTION_ONLY" else overall
    next_action = report.get("next_required_action") or "Sin siguiente accion reportada."
    if overall == "EVIDENCE_COLLECTION_ONLY":
        next_action = "Apertura tecnica completa. Continuar acumulando evidencia; no cambiar parametros ni forzar ENTRY_READY."
    level = "green" if overall in {"READY", "WAIT_MARKET", "REVIEW_REQUIRED"} and refresh.get("ok") else "amber"
    if overall == "ACTION_REQUIRED" or refresh.get("ok") is False or publish.get("ok") is False:
        level = "red"
    rsp_status = status_word(rsp_refresh.get("ok"), good="ACTUALIZADO")
    if rsp_refresh.get("skipped"):
        rsp_status = "OMITIDO"
    rsp_detail = "contexto={} · cadena={} · candidatos={}".format(
        "fresco" if rsp.get("manual_context_fresh") else "revisar",
        "OK" if rsp.get("chain_has_rsp") else "pendiente",
        rsp.get("candidate_count") or 0,
    )
    return """
    <div class="daily-open-summary summary-{level}">
      <div class="section-head">
        <div>
          <p class="eyebrow">Resultado operativo</p>
          <h2>Apertura diaria: {overall}</h2>
        </div>
        <p>{next_action}</p>
      </div>
      <div class="tiles compact-status">
        <div class="tile">CANSLIM<span>{canslim_status}. Candidatos actualizados si el paso marco OK.</span></div>
        <div class="tile">IBKR/TWS<span>{ibkr_status}: {ibkr_detail}</span></div>
        <div class="tile">Capacidad de cuenta<span>{capacity_status}. Lectura incluida en la apertura.</span></div>
        <div class="tile">Coberturas RSP<span>{rsp_status}: {rsp_detail}</span></div>
        <div class="tile">Publicacion<span>{publish_status}: {publish_detail}</span></div>
        <div class="tile">GPT/Produccion<span>{gpt_status}. Auth={production_status}; operador={operator_status}.</span></div>
        <div class="tile">Foundation<span>{foundation_status}</span></div>
        <div class="tile">Evidence Gate<span>{evidence_status}</span></div>
      </div>
    </div>
    """.format(
        level=html_escape(level),
        overall=html_escape(overall_label),
        next_action=html_escape(next_action),
        canslim_status=html_escape(status_word(canslim.get("ok"))),
        ibkr_status=html_escape(ibkr_status),
        ibkr_detail=html_escape(ibkr_detail),
        capacity_status=html_escape(status_word(capacity_refresh.get("ok"), good="ACTUALIZADA")),
        rsp_status=html_escape(rsp_status),
        rsp_detail=html_escape(rsp_detail),
        publish_status=html_escape(status_word(publish.get("ok"))),
        publish_detail=html_escape(publish_detail),
        gpt_status=html_escape(gpt_status),
        production_status=html_escape(status_word(production_auth.get("ok"))),
        operator_status=html_escape(status_word(operator_today.get("ok"))),
        foundation_status=html_escape(str(foundation.get("status") or status_word(foundation.get("ok")))),
        evidence_status=html_escape(str(evidence.get("state") or status_word(evidence.get("ok")))),
    )


def load_control_tower(profiles: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(CONTROL_TOWER_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    profile_map = profiles if isinstance(profiles, dict) else {}
    if profile_map:
        persisted_accounts = {
            str(row.get("account_alias") or ""): row
            for row in (data.get("accounts") or [])
            if isinstance(row, dict)
        }
        keychain_ready = {
            alias: bool(persisted_accounts.get(alias, {}).get("keychain_ready"))
            for alias in profile_map
        }
        registry = shared_control_tower.build_registry(
            profile_map,
            active.get("account_alias") or "",
            keychain_ready,
        )
        snapshots = shared_control_tower.load_snapshots(RUNTIME, registry)
        if any(snapshots.values()):
            return shared_control_tower.consolidate(registry, snapshots)
    if isinstance(data, dict) and data.get("control_tower_version"):
        return data
    registry = shared_control_tower.build_registry(
        profile_map,
        active.get("account_alias") or "",
        {alias: False for alias in profile_map},
    )
    return shared_control_tower.consolidate(registry, {})


def _tower_money(value: Any) -> str:
    parsed = console_float_or_none(value)
    return "N/D" if parsed is None else "${:,.2f}".format(parsed)


def render_control_tower_panel(profiles: dict[str, Any], active: dict[str, Any]) -> str:
    payload = load_control_tower(profiles, active)
    capacity = payload.get("consolidated_capacity") if isinstance(payload.get("consolidated_capacity"), dict) else {}
    rows = []
    for account in payload.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        account_capacity = account.get("capacity") if isinstance(account.get("capacity"), dict) else {}
        status = str(account.get("refresh_status") or "UNREFRESHED").upper()
        rows.append(
            """
            <article class="card status-{status_class}">
              <div>
                <h3>{alias}</h3>
                <p><strong>{broker}</strong> · scope {scope}</p>
                <p class="muted">{status} · edad {age} min · posiciones {positions}</p>
              </div>
              <div>
                <p><strong>NAV:</strong> {nav}</p>
                <p><strong>Disponible:</strong> {available}</p>
                <p><strong>Buying power:</strong> {buying_power}</p>
              </div>
            </article>
            """.format(
                status_class=html_escape(status.lower()),
                alias=html_escape(account.get("account_alias") or "unknown"),
                broker=html_escape(account.get("broker") or "unknown"),
                scope=html_escape(account.get("account_scope") or "unknown"),
                status=html_escape(status),
                age=html_escape(account.get("snapshot_age_minutes") if account.get("snapshot_age_minutes") is not None else "N/D"),
                positions=html_escape(account.get("position_count") or 0),
                nav=html_escape(_tower_money(account_capacity.get("net_liquidation"))),
                available=html_escape(_tower_money(account_capacity.get("available_funds"))),
                buying_power=html_escape(_tower_money(account_capacity.get("buying_power"))),
            )
        )
    if not rows:
        rows.append('<p class="empty">No hay cuentas configuradas para Control Tower.</p>')
    aliases = [str(item.get("account_alias") or "") for item in (payload.get("accounts") or []) if isinstance(item, dict)]
    job_alias = active.get("account_alias") or (aliases[0] if aliases else "")
    action = (
        '<form method="post" action="/control-tower-refresh" data-busy="Actualizando todas las cuentas" '
        'data-busy-detail="Lectura secuencial y de solo consulta en IBKR; no coloca ordenes.">'
        f'<input type="hidden" name="alias" value="{html_escape(job_alias)}">'
        '<button>Refrescar todas las cuentas</button></form>'
        if job_alias else ""
    )
    warnings = ", ".join(payload.get("warnings") or []) or "ninguna"
    return """
    <section class="panel control-tower">
      <div class="section-head">
        <h2>Control Tower multi-cuenta</h2>
        <p><strong>{status}</strong> · {ready}/{total} cuentas listas · IDs reales excluidos.</p>
      </div>
      <div class="control-facts">
        <div><span>NAV consolidado</span><strong>{nav}</strong></div>
        <div><span>Fondos disponibles</span><strong>{available}</strong></div>
        <div><span>Buying power</span><strong>{buying_power}</strong></div>
      </div>
      <p class="muted">Advertencias: {warnings}</p>
      <div class="grid">{rows}</div>
      <div class="actions">{action}</div>
    </section>
    """.format(
        status=html_escape(payload.get("status") or "WAIT_ACCOUNT_REFRESH"),
        ready=html_escape(payload.get("ready_account_count") or 0),
        total=html_escape(payload.get("account_count") or 0),
        nav=html_escape(_tower_money(capacity.get("net_liquidation"))),
        available=html_escape(_tower_money(capacity.get("available_funds"))),
        buying_power=html_escape(_tower_money(capacity.get("buying_power"))),
        warnings=html_escape(warnings),
        rows="".join(rows),
        action=action,
    )


def load_portfolio_risk(profiles: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
    tower = load_control_tower(profiles, active)
    policy = shared_portfolio_risk.load_policy(PORTFOLIO_RISK_POLICY_PATH)
    evaluation = shared_portfolio_risk.evaluate(tower, policy)
    actions = shared_risk_operations.load_json(PORTFOLIO_RISK_ACTIONS_PATH)
    return shared_risk_operations.decorate_evaluation(evaluation, actions)


def _tower_percent(value: Any) -> str:
    parsed = console_float_or_none(value)
    return "N/D" if parsed is None else "{:.1f}%".format(parsed * 100)


def render_portfolio_risk_panel(
    profiles: dict[str, Any],
    active: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> str:
    payload = payload if isinstance(payload, dict) else load_portfolio_risk(profiles, active)
    counts = payload.get("alert_counts") if isinstance(payload.get("alert_counts"), dict) else {}
    alert_rows = []
    for alert in (payload.get("alerts") or [])[:10]:
        if not isinstance(alert, dict):
            continue
        metric = str(alert.get("metric") or "")
        value = alert.get("value")
        threshold = alert.get("threshold")
        ratio_metric = metric.endswith("_ratio") or metric == "account_nav_share"
        value_label = _tower_percent(value) if ratio_metric else ("N/D" if value is None else str(value))
        threshold_label = _tower_percent(threshold) if ratio_metric else ("N/D" if threshold is None else str(threshold))
        operational_status = str(alert.get("operational_status") or "OPEN").upper()
        alert_id = str(alert.get("alert_id") or "")
        if operational_status == "OPEN":
            lifecycle_actions = """
              <form method="post" action="/portfolio-risk-action" class="risk-actions" data-busy="Guardando acción de riesgo">
                <input type="hidden" name="alert_id" value="{alert_id}">
                <input name="reason" placeholder="Nota opcional de revisión">
                <div class="actions">
                  <button name="action" value="ACKNOWLEDGE">Confirmar que lo revisé</button>
                  <button class="secondary" name="action" value="SNOOZE">Recordar en 60 min</button>
                </div>
              </form>
            """.format(alert_id=html_escape(alert_id))
        else:
            lifecycle_actions = """
              <form method="post" action="/portfolio-risk-action" class="risk-actions" data-busy="Reabriendo alerta de riesgo">
                <input type="hidden" name="alert_id" value="{alert_id}">
                <button class="secondary" name="action" value="REOPEN">Reabrir ahora</button>
              </form>
            """.format(alert_id=html_escape(alert_id))
        alert_rows.append(
            """
            <article class="risk-alert severity-{severity_class}">
              <div class="risk-alert-title"><strong>{severity}</strong><span>{account} · {operational_status}</span></div>
              <h3>{title}</h3>
              <p>{message}</p>
              <details class="technical-details"><summary>Ver cálculo</summary><p class="muted">Métrica: {metric} · valor {value} · límite {threshold}</p></details>
              <p><strong>Siguiente paso:</strong> {action}</p>
              {lifecycle_actions}
            </article>
            """.format(
                severity_class=html_escape(str(alert.get("severity") or "watch").lower()),
                severity=html_escape(alert.get("severity") or "WATCH"),
                account=html_escape(alert.get("account_alias") or alert.get("scope") or "SISTEMA"),
                operational_status=html_escape(operational_status),
                title=html_escape(alert.get("title") or alert.get("rule") or "Alerta de riesgo"),
                message=html_escape(alert.get("message") or ""),
                metric=html_escape(metric or "N/D"),
                value=html_escape(value_label),
                threshold=html_escape(threshold_label),
                action=html_escape(alert.get("recommended_action") or "Revisión manual."),
                lifecycle_actions=lifecycle_actions,
            )
        )
    if not alert_rows:
        alert_rows.append('<p class="empty">Sin alertas de cartera bajo la política vigente.</p>')
    primary_alerts = alert_rows[:3]
    secondary_alerts = alert_rows[3:]
    alerts_html = "".join(primary_alerts)
    if secondary_alerts:
        alerts_html += (
            '<details class="remaining-risk-alerts">'
            f'<summary>Ver {len(secondary_alerts)} alertas adicionales</summary>'
            f'<div class="risk-alert-list">{"".join(secondary_alerts)}</div>'
            '</details>'
        )
    alias = active.get("account_alias") or next(iter(profiles or {}), "")
    action = (
        '<form method="post" action="/portfolio-risk-refresh" data-busy="Reevaluando riesgo" '
        'data-busy-detail="Aplica la política a los snapshots sanitizados; no transmite ni ejecuta órdenes.">'
        f'<input type="hidden" name="alias" value="{html_escape(alias)}">'
        '<button>Reevaluar riesgo</button></form>'
        if alias else ""
    )
    return """
    <section class="panel portfolio-risk status-{status_class}">
      <div class="section-head">
        <div><h2>Riesgo de cartera</h2><p>{decision}</p></div>
        <div class="risk-score"><span>Nivel de riesgo</span><strong>{risk_label}</strong><small>{score}/100</small></div>
      </div>
      <div class="control-facts">
        <div><span>Estado</span><strong>{status}</strong></div>
        <div><span>Críticas</span><strong>{critical}</strong></div>
        <div><span>Altas</span><strong>{high}</strong></div>
        <div><span>Vigilancia</span><strong>{watch}</strong></div>
      </div>
      <p class="muted">Las alertas están ordenadas por severidad. La consola explica y registra; cualquier ajuste de cartera sigue siendo manual.</p>
      <div class="risk-alert-list">{alerts}</div>
      <div class="actions">{action}</div>
    </section>
    """.format(
        status_class=html_escape(str(payload.get("status") or "blocked").lower()),
        status=html_escape(friendly_operator_state(payload.get("status") or "BLOCKED")),
        decision=html_escape(friendly_operator_state(payload.get("decision_support") or "NO_NEW_RISK")),
        score=html_escape(payload.get("risk_score") or 0),
        risk_label=html_escape("Alto" if (counts.get("critical") or counts.get("high")) else "Vigilancia" if counts.get("watch") else "Controlado"),
        critical=html_escape(counts.get("critical") or 0),
        high=html_escape(counts.get("high") or 0),
        watch=html_escape(counts.get("watch") or 0),
        policy=html_escape(payload.get("policy_version") or "unknown"),
        alerts=alerts_html,
        action=action,
    )


def load_portfolio_stress(profiles: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
    tower = load_control_tower(profiles, active)
    policy = shared_portfolio_stress.load_policy(PORTFOLIO_STRESS_POLICY_PATH)
    return shared_portfolio_stress.evaluate(tower, policy)


def render_portfolio_stress_panel(profiles: dict[str, Any], active: dict[str, Any]) -> str:
    payload = load_portfolio_stress(profiles, active)
    scenario_cards = []
    for scenario in payload.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        pnl = console_float_or_none(scenario.get("estimated_pnl"))
        loss_ratio = console_float_or_none(scenario.get("loss_nav_ratio"))
        scenario_cards.append("""
          <article class="scenario-card severity-{severity}">
            <div class="scenario-head"><strong>{name}</strong><span>{severity_label}</span></div>
            <p class="muted">{description}</p>
            <div class="scenario-lines">
              <div><span>Impacto estimado</span><strong>{pnl}</strong></div>
              <div><span>Pérdida sobre NAV</span><strong>{loss}</strong></div>
              <div><span>NAV proyectado</span><strong>{projected_nav}</strong></div>
              <div><span>Cuenta más expuesta</span><strong>{account}</strong></div>
            </div>
          </article>
        """.format(
            severity=html_escape(str(scenario.get("severity") or "info").lower()),
            severity_label=html_escape(scenario.get("severity") or "INFO"),
            name=html_escape(scenario.get("name") or "Escenario"),
            description=html_escape(scenario.get("description") or ""),
            pnl=html_escape("N/D" if pnl is None else "${:,.2f}".format(pnl)),
            loss=html_escape("N/D" if loss_ratio is None else "{:.1f}%".format(loss_ratio * 100)),
            projected_nav=html_escape(_tower_money(scenario.get("projected_nav"))),
            account=html_escape(scenario.get("most_exposed_account") or "N/D"),
        ))
    concentrations = ", ".join(
        "{} ({:.1f}%)".format(item.get("ticker") or "UNKNOWN", (console_float_or_none(item.get("gross_share")) or 0) * 100)
        for item in (payload.get("concentrations") or [])[:5]
        if isinstance(item, dict)
    ) or "sin posiciones valorables"
    warnings = ", ".join(payload.get("warnings") or []) or "ninguna"
    alias = active.get("account_alias") or next(iter(profiles or {}), "")
    action = (
        '<form method="post" action="/portfolio-stress-refresh" data-busy="Calculando escenarios de estrés" '
        'data-busy-detail="Usa snapshots sanitizados; no consulta ni opera el broker.">'
        f'<input type="hidden" name="alias" value="{html_escape(alias)}">'
        '<button>Recalcular escenarios</button></form>'
        if alias else ""
    )
    return """
    <section class="panel portfolio-stress status-{status_class}">
      <div class="section-head">
        <div><h2>Estrés y escenarios multicuenta</h2><p>Impacto potencial agregado y por cuenta.</p></div>
        <div class="risk-score"><span>Cobertura exacta</span><strong>{coverage}</strong></div>
      </div>
      <div class="control-facts">
        <div><span>Estado</span><strong>{status}</strong></div>
        <div><span>Peor impacto</span><strong>{worst_pnl}</strong></div>
        <div><span>Peor pérdida/NAV</span><strong>{worst_loss}</strong></div>
        <div><span>Escenarios</span><strong>{count}</strong></div>
      </div>
      <div class="scenario-grid">{scenarios}</div>
      <p><strong>Mayor concentración:</strong> {concentrations}</p>
      <p class="muted">Advertencias: {warnings}. Modelo determinista para apoyo de decisión; no es pronóstico ni VaR. Sin ejecución automática.</p>
      <div class="actions">{action}</div>
    </section>
    """.format(
        status_class=html_escape(str(payload.get("status") or "blocked").lower()),
        status=html_escape(payload.get("status") or "BLOCKED"),
        coverage=html_escape(_tower_percent(payload.get("valuation_coverage_ratio"))),
        worst_pnl=html_escape(_tower_money(payload.get("worst_estimated_pnl"))),
        worst_loss=html_escape(_tower_percent(payload.get("worst_loss_nav_ratio"))),
        count=html_escape(payload.get("scenario_count") or 0),
        scenarios="".join(scenario_cards) or '<p class="empty">No hay escenarios configurados.</p>',
        concentrations=html_escape(concentrations),
        warnings=html_escape(warnings),
        action=action,
    )


def load_portfolio_factors(profiles: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
    tower = load_control_tower(profiles, active)
    policy = shared_portfolio_factors.load_policy(PORTFOLIO_FACTOR_POLICY_PATH)
    return shared_portfolio_factors.evaluate(tower, policy)


def render_portfolio_factor_panel(profiles: dict[str, Any], active: dict[str, Any]) -> str:
    payload = load_portfolio_factors(profiles, active)
    historical = payload.get("historical_risk") if isinstance(payload.get("historical_risk"), dict) else {}
    greeks = payload.get("option_greeks") if isinstance(payload.get("option_greeks"), dict) else {}
    factor_cards = []
    for group in payload.get("factor_groups") or []:
        if not isinstance(group, dict):
            continue
        leaders = group.get("factors") if isinstance(group.get("factors"), list) else []
        top = leaders[0] if leaders and isinstance(leaders[0], dict) else {}
        factor_cards.append("""
          <article class="scenario-card">
            <div class="scenario-head"><strong>{group}</strong><span>{share}</span></div>
            <h3>{label}</h3>
            <p class="muted">Exposición neta {exposure} · {dominant}</p>
          </article>
        """.format(
            group=html_escape(str(group.get("group") or "factor").replace("_", " ").title()),
            share=html_escape(_tower_percent(top.get("gross_share"))),
            label=html_escape(top.get("label") or "N/D"),
            exposure=html_escape(_tower_money(top.get("signed_exposure"))),
            dominant="factor dominante" if group.get("dominant") else "diversificado",
        ))
    correlation_rows = []
    for row in (payload.get("correlations") or [])[:6]:
        if not isinstance(row, dict):
            continue
        correlation_rows.append("<li><strong>{left} / {right}</strong><span>{value} · {state}</span></li>".format(
            left=html_escape(row.get("left") or ""),
            right=html_escape(row.get("right") or ""),
            value=html_escape("{:.2f}".format(console_float_or_none(row.get("correlation")) or 0)),
            state="alta" if row.get("high_correlation") else "normal",
        ))
    warnings = ", ".join(payload.get("warnings") or []) or "ninguna"
    alias = active.get("account_alias") or next(iter(profiles or {}), "")
    action = (
        '<form method="post" action="/portfolio-factor-refresh" data-busy="Actualizando inteligencia de cartera" '
        'data-busy-detail="Recalcula factores, historia, correlaciones y Greeks sin operar el broker.">'
        f'<input type="hidden" name="alias" value="{html_escape(alias)}">'
        '<button>Recalcular inteligencia</button></form>'
        if alias else ""
    )
    return """
    <section class="panel portfolio-factors status-{status_class}">
      <div class="section-head">
        <div><h2>Inteligencia avanzada de cartera</h2><p>Factores, comportamiento histórico, correlaciones y opciones.</p></div>
        <strong>{status}</strong>
      </div>
      <div class="control-facts">
        <div><span>Historia cubierta</span><strong>{history_coverage}</strong></div>
        <div><span>Greeks cubiertos</span><strong>{greeks_coverage}</strong></div>
        <div><span>Volatilidad anual</span><strong>{volatility}</strong></div>
        <div><span>Pérdida cola 95%</span><strong>{tail_loss}</strong></div>
        <div><span>Correlaciones altas</span><strong>{high_corr}</strong></div>
      </div>
      <div class="scenario-grid">{factor_cards}</div>
      <div class="scenario-grid">
        <article class="scenario-card">
          <h3>Greeks agregados</h3>
          <div class="scenario-lines">
            <div><span>Dollar delta</span><strong>{dollar_delta}</strong></div>
            <div><span>Theta diario</span><strong>{theta}</strong></div>
            <div><span>Vega / punto</span><strong>{vega}</strong></div>
            <div><span>Gamma P&amp;L 1%</span><strong>{gamma}</strong></div>
          </div>
        </article>
        <article class="scenario-card">
          <h3>Correlaciones principales</h3>
          <ul class="factor-correlation-list">{correlations}</ul>
        </article>
      </div>
      <p class="muted">Advertencias: {warnings}. Sensibilidad histórica, no pronóstico. Sin órdenes ni liquidación automática.</p>
      <div class="actions">{action}</div>
    </section>
    """.format(
        status_class=html_escape(str(payload.get("status") or "blocked").lower()),
        status=html_escape(payload.get("status") or "BLOCKED"),
        history_coverage=html_escape(_tower_percent(payload.get("history_coverage_ratio"))),
        greeks_coverage=html_escape(_tower_percent(payload.get("greeks_coverage_ratio"))),
        volatility=html_escape(_tower_percent(historical.get("annualized_volatility"))),
        tail_loss=html_escape(_tower_money(historical.get("estimated_tail_loss_dollars"))),
        high_corr=html_escape(payload.get("high_correlation_pair_count") or 0),
        factor_cards="".join(factor_cards) or '<p class="empty">Sin factores valorables.</p>',
        dollar_delta=html_escape(_tower_money(greeks.get("dollar_delta"))),
        theta=html_escape(_tower_money(greeks.get("theta_daily"))),
        vega=html_escape(_tower_money(greeks.get("vega_per_vol_point"))),
        gamma=html_escape(_tower_money(greeks.get("gamma_pnl_1pct"))),
        correlations="".join(correlation_rows) or '<li><span>Sin pares suficientes.</span></li>',
        warnings=html_escape(warnings),
        action=action,
    )


def load_portfolio_rebalance(profiles: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
    persisted = shared_risk_operations.load_json(PORTFOLIO_REBALANCE_PATH)
    if persisted.get("rebalance_engine_version"):
        return persisted
    tower = load_control_tower(profiles, active)
    return shared_portfolio_rebalance.evaluate(
        tower,
        shared_portfolio_rebalance.load_policy(PORTFOLIO_REBALANCE_POLICY_PATH),
        shared_portfolio_stress.load_policy(PORTFOLIO_STRESS_POLICY_PATH),
        shared_portfolio_factors.load_policy(PORTFOLIO_FACTOR_POLICY_PATH),
    )


def render_portfolio_rebalance_panel(profiles: dict[str, Any], active: dict[str, Any]) -> str:
    payload = load_portfolio_rebalance(profiles, active)
    baseline = payload.get("baseline") if isinstance(payload.get("baseline"), dict) else {}
    cards = []
    preferred = str(payload.get("preferred_simulation_id") or "")
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
        improvements = candidate.get("improvements") if isinstance(candidate.get("improvements"), dict) else {}
        constraints = candidate.get("constraints") if isinstance(candidate.get("constraints"), dict) else {}
        actions = candidate.get("virtual_actions") if isinstance(candidate.get("virtual_actions"), list) else []
        action_summary = ", ".join(
            "{} {}".format(item.get("ticker") or "", item.get("simulation_action") or "")
            for item in actions[:4] if isinstance(item, dict)
        ) or "sin cambios virtuales"
        is_preferred = str(candidate.get("candidate_id") or "") == preferred
        cards.append("""
          <article class="scenario-card rebalance-card {preferred_class}">
            <div class="scenario-head"><strong>{name}</strong><span>{label}</span></div>
            <p>{description}</p>
            <div class="scenario-lines">
              <div><span>Estrés peor caso</span><strong>{stress}</strong></div>
              <div><span>Volatilidad</span><strong>{volatility}</strong></div>
              <div><span>Concentración mayor</span><strong>{concentration}</strong></div>
              <div><span>Dollar delta</span><strong>{delta}</strong></div>
              <div><span>Rotación virtual</span><strong>{turnover}</strong></div>
              <div><span>Mejora cola</span><strong>{tail_improvement}</strong></div>
            </div>
            <p class="muted">Cambios: {actions}. Score comparativo {score}; restricciones {constraints}; decisión manual obligatoria.</p>
          </article>
        """.format(
            preferred_class="preferred-simulation" if is_preferred else "",
            name=html_escape(candidate.get("name") or "Simulación"),
            label="MEJOR EQUILIBRIO" if is_preferred else "ALTERNATIVA",
            description=html_escape(candidate.get("description") or ""),
            stress=html_escape(_tower_percent(metrics.get("worst_stress_loss_ratio"))),
            volatility=html_escape(_tower_percent(metrics.get("annualized_volatility"))),
            concentration=html_escape(_tower_percent(metrics.get("top_ticker_share"))),
            delta=html_escape(_tower_money(metrics.get("option_dollar_delta"))),
            turnover=html_escape(_tower_money(candidate.get("turnover_dollars"))),
            tail_improvement=html_escape(_tower_money(improvements.get("tail_loss_reduction_dollars"))),
            actions=html_escape(action_summary),
            score=html_escape(candidate.get("model_score") or 0),
            constraints="cumplidas" if constraints.get("all_satisfied") else "no cumplidas",
        ))
    ticker_options = "".join(
        '<option value="{ticker}">{ticker}</option>'.format(ticker=html_escape(ticker))
        for ticker in (payload.get("available_tickers") or [])
    )
    warnings = ", ".join(payload.get("warnings") or []) or "ninguna"
    alias = active.get("account_alias") or next(iter(profiles or {}), "")
    custom_form = (
        '<form method="post" action="/portfolio-rebalance-simulate" data-busy="Simulando rebalanceo" '
        'data-busy-detail="Crea una comparación virtual; no crea ni transmite órdenes.">'
        f'<input type="hidden" name="alias" value="{html_escape(alias)}">'
        f'<label>Ticker <select name="ticker" required>{ticker_options}</select></label>'
        '<label>Reducción virtual % <input type="number" name="reduction_pct" min="1" max="100" step="1" value="10" required></label>'
        '<button>Simular solamente</button></form>'
        if alias and ticker_options else ""
    )
    return """
    <section class="panel portfolio-rebalance status-{status_class}">
      <div class="section-head">
        <div><h2>Simulador de rebalanceo</h2><p>Compara alternativas virtuales antes de cualquier decisión manual.</p></div>
        <strong>{status}</strong>
      </div>
      <div class="control-facts">
        <div><span>Estrés actual</span><strong>{stress}</strong></div>
        <div><span>Volatilidad actual</span><strong>{volatility}</strong></div>
        <div><span>Concentración actual</span><strong>{concentration}</strong></div>
        <div><span>Liquidez mínima</span><strong>{liquidity}</strong></div>
        <div><span>Alternativas</span><strong>{count}</strong></div>
      </div>
      <div class="scenario-grid">{cards}</div>
      <div class="rebalance-custom">
        <h3>Simulación personalizada</h3>
        <p class="muted">Elige un ticker y un porcentaje. Solo altera una copia matemática de la cartera.</p>
        {custom_form}
      </div>
      <p class="muted">Advertencias: {warnings}. No incluye impuestos, deslizamiento ni ejecución. Órdenes creadas: 0.</p>
    </section>
    """.format(
        status_class=html_escape(str(payload.get("status") or "blocked").lower()),
        status=html_escape(payload.get("status") or "BLOCKED"),
        stress=html_escape(_tower_percent(baseline.get("worst_stress_loss_ratio"))),
        volatility=html_escape(_tower_percent(baseline.get("annualized_volatility"))),
        concentration=html_escape(_tower_percent(baseline.get("top_ticker_share"))),
        liquidity=html_escape(_tower_percent(baseline.get("minimum_excess_liquidity_ratio"))),
        count=html_escape(payload.get("candidate_count") or 0),
        cards="".join(cards) or '<p class="empty">No se detectó un cambio virtual necesario bajo la política actual.</p>',
        custom_form=custom_form,
        warnings=html_escape(warnings),
    )


def load_portfolio_whatif() -> dict[str, Any]:
    return shared_risk_operations.load_json(PORTFOLIO_WHATIF_PATH)


def render_portfolio_whatif_panel(profiles: dict[str, Any], active: dict[str, Any]) -> str:
    payload = load_portfolio_whatif()
    rebalance_payload = load_portfolio_rebalance(profiles, active)
    preview_cards = []
    for preview in payload.get("previews") or []:
        if not isinstance(preview, dict):
            continue
        preview_cards.append("""
          <article class="scenario-card status-{status_class}">
            <div class="scenario-head"><strong>{ticker} {action}</strong><span>{status}</span></div>
            <p>{account} · {security_type} · cantidad {quantity}</p>
            <div class="scenario-lines">
              <div><span>Margen inicial</span><strong>{initial}</strong></div>
              <div><span>Margen mantenimiento</span><strong>{maintenance}</strong></div>
              <div><span>Comisión</span><strong>{commission}</strong></div>
              <div><span>Modo IBKR</span><strong>WHAT-IF</strong></div>
            </div>
            <p class="muted">{warning}</p>
          </article>
        """.format(
            status_class=html_escape(str(preview.get("status") or "failed").lower()),
            ticker=html_escape(preview.get("ticker") or "N/D"),
            action=html_escape(preview.get("action") or ""),
            status=html_escape(preview.get("status") or "FAILED"),
            account=html_escape(preview.get("account_alias") or "N/D"),
            security_type=html_escape(preview.get("security_type") or "N/D"),
            quantity=html_escape(preview.get("quantity") or 0),
            initial=html_escape(_tower_money(preview.get("init_margin_change"))),
            maintenance=html_escape(_tower_money(preview.get("maintenance_margin_change"))),
            commission=html_escape(_tower_money(preview.get("commission") or preview.get("maximum_commission"))),
            warning=html_escape(preview.get("warning_text") or preview.get("error") or "Preview oficial IBKR sin transmisión."),
        ))
    candidates = [row for row in (rebalance_payload.get("candidates") or []) if isinstance(row, dict)]
    candidate_options = "".join(
        '<option value="{candidate_id}"{selected}>{name}</option>'.format(
            candidate_id=html_escape(row.get("candidate_id") or ""),
            name=html_escape(row.get("name") or row.get("candidate_id") or "Simulación"),
            selected=" selected" if str(row.get("candidate_id") or "") == str(rebalance_payload.get("preferred_simulation_id") or "") else "",
        )
        for row in candidates
    )
    alias = active.get("account_alias") or next(iter(profiles or {}), "")
    action_form = (
        '<form method="post" action="/portfolio-rebalance-whatif" data-busy="Consultando what-if oficial IBKR" '
        'data-busy-detail="IBKR exige transmit=true para procesar el preview; whatIf=true impide crear una orden real.">'
        f'<input type="hidden" name="alias" value="{html_escape(alias)}">'
        f'<label>Alternativa <select name="candidate_id" required>{candidate_options}</select></label>'
        '<button>Validar margen y comisión</button></form>'
        if alias and candidate_options else ""
    )
    status = payload.get("status") or "SIN_VALIDAR"
    unchanged = payload.get("open_order_fingerprint_unchanged")
    unchanged_label = "SÍ" if unchanged is True else "NO" if unchanged is False else "PENDIENTE"
    isolation = payload.get("channel_isolation") if isinstance(payload.get("channel_isolation"), dict) else {}
    if not isolation:
        runner_path = ROOT / "scripts" / "preview_portfolio_rebalance_whatif.py"
        isolation = shared_portfolio_whatif.evaluate_channel_isolation(
            shared_portfolio_whatif.load_policy(PORTFOLIO_WHATIF_POLICY_PATH),
            client_id=CONSOLE_WHATIF_IBKR_CLIENT_ID,
            runner_source=runner_path.read_text(encoding="utf-8"),
            dedicated_tws_session=str(os.getenv("STOCK_ULTIMUS_WHATIF_DEDICATED_TWS", "")).lower()
            in {"1", "true", "yes"},
        )
    logical_label = "SÍ" if isolation.get("logical_isolation_ready") else "PENDIENTE"
    physical_label = "SÍ" if isolation.get("physical_isolation_ready") else "NO"
    preview_rows = [row for row in (payload.get("previews") or []) if isinstance(row, dict)]
    timeout_only = bool(preview_rows) and all(
        str(row.get("status") or "") != "READY" and "TimeoutError" in str(row.get("error") or "")
        for row in preview_rows
    )
    operator_notice = ""
    if payload.get("operator_state") == "TWS_CONFIRMATION_REQUIRED" or timeout_only:
        operator_notice = """
        <div class="notice warn">
          <strong>Acción requerida en TWS</strong>
          <p>{message}</p>
          <p>La consola no acepta automáticamente esta decisión porque desactivaría precauciones para todas las órdenes API, incluidas posibles órdenes reales futuras.</p>
        </div>
        """.format(message=html_escape(payload.get("operator_message") or "TWS está esperando una confirmación."))
    return """
    <section class="panel portfolio-whatif status-{status_class}">
      <div class="section-head">
        <div><h2>Validación oficial IBKR what-if</h2><p>Margen y comisiones sin transmitir órdenes.</p></div>
        <strong>{status}</strong>
      </div>
      <div class="control-facts">
        <div><span>Alternativa</span><strong>{candidate}</strong></div>
        <div><span>Previews listos</span><strong>{ready}/{requested}</strong></div>
        <div><span>Comisión estimada</span><strong>{commission}</strong></div>
        <div><span>Cambio margen mant.</span><strong>{maintenance}</strong></div>
        <div><span>Órdenes sin cambio</span><strong>{unchanged}</strong></div>
        <div><span>Canal sin ejecución real</span><strong>{logical}</strong></div>
        <div><span>Sesión TWS dedicada</span><strong>{physical}</strong></div>
      </div>
      {operator_notice}
      <div class="scenario-grid">{previews}</div>
      <div class="rebalance-custom">
        <h3>Validar una alternativa</h3>
        {action_form}
      </div>
      <p class="muted">Los cambios de margen se suman como previews independientes y no equivalen a una cesta combinada. IBKR recibe whatIf=true y transmit=true solo para procesar el preview; órdenes reales creadas {orders}.</p>
    </section>
    """.format(
        status_class=html_escape(str(status).lower()),
        status=html_escape(status),
        candidate=html_escape(payload.get("candidate_name") or payload.get("candidate_id") or "Pendiente"),
        ready=html_escape(payload.get("ready_preview_count") or 0),
        requested=html_escape(payload.get("requested_preview_count") or 0),
        commission=html_escape(_tower_money(payload.get("estimated_commission_total"))),
        maintenance=html_escape(_tower_money(payload.get("independent_maintenance_margin_change_sum"))),
        unchanged=html_escape(unchanged_label),
        logical=html_escape(logical_label),
        physical=html_escape(physical_label),
        operator_notice=operator_notice,
        previews="".join(preview_cards) or '<p class="empty">Selecciona una alternativa para consultar el what-if oficial.</p>',
        action_form=action_form,
        orders=html_escape(payload.get("orders_created") if payload.get("orders_created") is not None else "N/D"),
    )
def load_decision_outcome_intelligence() -> dict[str, Any]:
    def rows(path: Path, key: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = []
        values = payload if isinstance(payload, list) else payload.get(key) or [] if isinstance(payload, dict) else []
        return [item for item in values if isinstance(item, dict)]

    decisions = rows(DECISION_JOURNAL_PATH, "decisions")
    outcomes = rows(OUTCOME_JOURNAL_PATH, "outcomes")
    return shared_decision_outcomes.build_intelligence(decisions, outcomes)


def render_decision_outcome_panel() -> str:
    payload = load_decision_outcome_intelligence()
    automation = shared_risk_operations.load_json(DAILY_OUTCOME_EVALUATION_PATH)
    evaluation_rows = [row for row in (automation.get("evaluations") or []) if isinstance(row, dict)]
    evaluated_total = sum(int(row.get("evaluated_count") or 0) for row in evaluation_rows)
    saved_total = sum(int(row.get("saved_count") or 0) for row in evaluation_rows)
    pending_total = sum(int(row.get("not_evaluated_count") or 0) for row in evaluation_rows)
    sync = automation.get("local_outcome_sync") if isinstance(automation.get("local_outcome_sync"), dict) else {}
    decision_sync = automation.get("local_decision_sync") if isinstance(automation.get("local_decision_sync"), dict) else {}
    automation_installed = (Path.home() / "Library" / "LaunchAgents" / "com.stockultimus.v32-pushover-postclose.plist").exists()
    recent_rows = []
    for row in payload.get("recent_decisions") or []:
        recent_rows.append("""
          <tr>
            <td><strong>{ticker}</strong><br><span class="muted">{strategy}</span></td>
            <td>{decision}<br><span class="muted">{action}</span></td>
            <td><strong>{outcome}</strong></td>
            <td>{pnl}</td>
            <td>{recorded}</td>
          </tr>
        """.format(
            ticker=html_escape(row.get("ticker") or "N/D"),
            strategy=html_escape(row.get("strategy") or "N/D"),
            decision=html_escape(row.get("final_state") or row.get("decision") or "N/D"),
            action=html_escape(row.get("action") or "Sin detalle"),
            outcome=html_escape(row.get("outcome") or "PENDIENTE"),
            pnl=html_escape(f"{row.get('pnl_r'):.2f} R" if isinstance(row.get("pnl_r"), (int, float)) else "Pendiente"),
            recorded=html_escape(str(row.get("recorded_at") or "N/D").replace("T", " ")[:16]),
        ))
    strategy_rows = []
    for row in payload.get("strategies") or []:
        win_rate = row.get("win_rate")
        expectancy = row.get("expectancy_r")
        strategy_rows.append("""
          <tr>
            <td><strong>{strategy}</strong></td><td>{decisions}</td><td>{closed}</td><td>{complete}/30</td>
            <td>{win_rate}</td><td>{expectancy}</td><td>{state}</td>
          </tr>
        """.format(
            strategy=html_escape(row.get("strategy") or "UNKNOWN"),
            decisions=html_escape(row.get("decisions") or 0),
            closed=html_escape(row.get("closed_outcomes") or 0),
            complete=html_escape(row.get("complete_closed_outcomes") or 0),
            win_rate=html_escape(f"{win_rate:.1f}%" if isinstance(win_rate, (int, float)) else "Sin muestra"),
            expectancy=html_escape(f"{expectancy:.2f} R" if isinstance(expectancy, (int, float)) else "Sin muestra"),
            state="LISTA" if row.get("parameter_review_ready") else "ACUMULANDO",
        ))
    coverage = payload.get("actionable_outcome_coverage_pct")
    return """
    <section class="panel decision-outcomes status-{status_class}">
      <div class="section-head">
        <div><h2>Historial de decisiones y resultados</h2><p>Trazabilidad, efectividad y evidencia acumulada por estrategia.</p></div>
        <strong>{status}</strong>
      </div>
      <div class="control-facts">
        <div><span>Decisiones registradas</span><strong>{decisions}</strong></div>
        <div><span>Decisiones accionables</span><strong>{actionable}</strong></div>
        <div><span>Resultados vinculados</span><strong>{linked}</strong></div>
        <div><span>Cobertura accionable</span><strong>{coverage}</strong></div>
        <div><span>Resultados completos</span><strong>{complete}/30</strong></div>
        <div><span>Avance de evidencia</span><strong>{progress}</strong></div>
      </div>
      <div class="control-facts">
        <div><span>Seguimiento automático</span><strong>{automation_status}</strong></div>
        <div><span>Última evaluación</span><strong>{last_run}</strong></div>
        <div><span>Evaluaciones procesadas</span><strong>{evaluated}</strong></div>
        <div><span>Checkpoints guardados</span><strong>{saved}</strong></div>
        <div><span>Pendientes de datos</span><strong>{pending}</strong></div>
        <div><span>Resultados sincronizados</span><strong>{sync_status}</strong></div>
        <div><span>Decisiones sincronizadas</span><strong>{decision_sync_status}</strong></div>
      </div>
      <form method="post" action="/daily-outcome-evaluation" data-busy="Actualizando seguimiento de resultados" data-busy-detail="Evalúa checkpoints y sincroniza el diario local; no toca IBKR ni crea órdenes.">
        <button class="secondary">Actualizar seguimiento ahora</button>
      </form>
      <h3>Rendimiento por estrategia</h3>
      <div class="table-scroll"><table><thead><tr><th>Estrategia</th><th>Decisiones</th><th>Cerrados</th><th>Completos</th><th>Acierto</th><th>Expectativa</th><th>Estado</th></tr></thead>
      <tbody>{strategies}</tbody></table></div>
      <h3>Decisiones recientes</h3>
      <div class="table-scroll"><table><thead><tr><th>Activo</th><th>Decisión</th><th>Resultado</th><th>PnL</th><th>Fecha</th></tr></thead>
      <tbody>{recent}</tbody></table></div>
      <p class="muted">La consola no cambia parámetros automáticamente. Se requieren 30 resultados cerrados y completos antes de habilitar una revisión profesional de parámetros.</p>
    </section>
    """.format(
        status_class=html_escape(str(payload.get("status") or "building").lower()),
        status="EVIDENCIA LISTA" if payload.get("parameter_review_ready") else "ACUMULANDO EVIDENCIA",
        decisions=html_escape(payload.get("decision_count") or 0),
        actionable=html_escape(payload.get("actionable_decision_count") or 0),
        linked=html_escape(payload.get("linked_actionable_outcome_count") or 0),
        coverage=html_escape(f"{coverage:.1f}%" if isinstance(coverage, (int, float)) else "Sin decisiones"),
        complete=html_escape(payload.get("complete_closed_outcomes") or 0),
        progress=html_escape(f"{float(payload.get('evidence_progress_pct') or 0):.1f}%"),
        automation_status="ACTIVO" if automation_installed else "NO INSTALADO",
        last_run=html_escape(age_label(automation.get("checked_at")) if automation.get("checked_at") else "Sin ejecución"),
        evaluated=html_escape(evaluated_total),
        saved=html_escape(saved_total),
        pending=html_escape(pending_total),
        sync_status=html_escape(sync.get("status") or "PENDIENTE DE PRIMER CICLO"),
        decision_sync_status=html_escape(decision_sync.get("status") or "PENDIENTE DE PRIMER CICLO"),
        strategies="".join(strategy_rows) or '<tr><td colspan="7">Todavía no hay resultados por estrategia.</td></tr>',
        recent="".join(recent_rows) or '<tr><td colspan="5">Todavía no hay decisiones accionables registradas.</td></tr>',
    )


def load_alert_effectiveness() -> dict[str, Any]:
    return shared_alert_effectiveness.build_from_runtime(RUNTIME)


def render_alert_effectiveness_panel() -> str:
    payload = load_alert_effectiveness()
    resolved = int(payload.get("resolved_entry_alert_count") or 0)
    coverage = payload.get("entry_tracking_coverage_pct")
    precision = payload.get("verified_precision_pct")
    attribution = payload.get("source_attribution_coverage_pct")
    sample_label = "Sin muestra" if resolved == 0 else str(resolved)
    return """
    <section class="panel alert-effectiveness status-{status_class}">
      <div class="section-head">
        <div><h2>Efectividad del alertamiento</h2><p>Calidad verificable de alertas, filtros y seguimiento.</p></div>
        <strong>{status}</strong>
      </div>
      <div class="control-facts">
        <div><span>Alertas lógicas</span><strong>{logical}</strong></div>
        <div><span>Duplicados consolidados</span><strong>{duplicates}</strong></div>
        <div><span>Alertas de entrada</span><strong>{entries}</strong></div>
        <div><span>Cobertura de seguimiento</span><strong>{coverage}</strong></div>
        <div><span>Alertas resueltas</span><strong>{resolved}/30</strong></div>
        <div><span>Precisión verificada</span><strong>{precision}</strong></div>
      </div>
      <div class="control-facts">
        <div><span>Alertas acertadas</span><strong>{useful}</strong></div>
        <div><span>Falsas alarmas</span><strong>{false_positive}</strong></div>
        <div><span>Oportunidades perdidas</span><strong>{missed}</strong></div>
        <div><span>Bloqueos de riesgo correctos</span><strong>{correct_blocks}</strong></div>
        <div><span>Atribución de fuente</span><strong>{attribution}</strong></div>
        <div><span>Brecha principal</span><strong>{gap}</strong></div>
      </div>
      <p class="muted">“Falsa alarma”, “oportunidad perdida” y “bloqueo correcto” sólo se contabilizan con un resultado cerrado vinculado. Hasta entonces se muestran como “Sin muestra”. Ninguna métrica cambia reglas automáticamente.</p>
    </section>
    """.format(
        status_class=html_escape(str(payload.get("status") or "waiting").lower()),
        status="REVISABLE" if payload.get("status") == "REVIEWABLE" else "ESPERANDO RESULTADOS" if resolved == 0 else "ACUMULANDO EVIDENCIA",
        logical=html_escape(payload.get("logical_alert_count") or 0),
        duplicates=html_escape(payload.get("duplicate_decisions_collapsed") or 0),
        entries=html_escape(payload.get("entry_alert_count") or 0),
        coverage=html_escape(f"{coverage:.1f}%" if isinstance(coverage, (int, float)) else "Sin alertas"),
        resolved=html_escape(resolved),
        precision=html_escape(f"{precision:.1f}%" if isinstance(precision, (int, float)) else "Sin muestra"),
        useful=html_escape(payload.get("useful_alert_count") if resolved else sample_label),
        false_positive=html_escape(payload.get("false_positive_count") if resolved else sample_label),
        missed=html_escape(payload.get("missed_opportunity_count") if resolved else sample_label),
        correct_blocks=html_escape(payload.get("correct_risk_block_count") if resolved else sample_label),
        attribution=html_escape(f"{attribution:.1f}%" if isinstance(attribution, (int, float)) else "Sin datos"),
        gap=html_escape(payload.get("primary_gap") or "N/D"),
    )


def load_executive_reports() -> dict[str, Any]:
    daily = shared_risk_operations.load_json(EXECUTIVE_DAILY_PATH)
    weekly = shared_risk_operations.load_json(EXECUTIVE_WEEKLY_PATH)
    if not daily.get("report_version"):
        daily = shared_executive_reporting.build_report(RUNTIME, "daily")
    if not weekly.get("report_version"):
        weekly = shared_executive_reporting.build_report(RUNTIME, "weekly")
    return {"daily": daily, "weekly": weekly, "execution_authorized": False, "not_order_instruction": True}


def render_executive_report_panel() -> str:
    reports = load_executive_reports()
    daily = reports.get("daily") or {}
    weekly = reports.get("weekly") or {}
    portfolio = daily.get("portfolio") or {}
    evidence = daily.get("decisions_and_results") or {}
    weekly_activity = weekly.get("period_activity") or {}
    pending_rows = []
    for item in daily.get("pending_actions") or []:
        pending_rows.append("""
          <article class="scenario-card">
            <div class="scenario-head"><strong>{title}</strong><span>{priority}</span></div>
            <p>{detail}</p>
          </article>
        """.format(
            title=html_escape(item.get("title") or "Pendiente"),
            priority=html_escape(item.get("priority") or "REVIEW"),
            detail=html_escape(item.get("detail") or ""),
        ))
    precision = evidence.get("verified_precision_pct")
    return """
    <section class="panel executive-report status-{status_class}">
      <div class="section-head">
        <div><h2>Reporte ejecutivo</h2><p>Resumen diario y semanal de cartera, riesgo, evidencia y mantenimiento.</p></div>
        <strong>{status}</strong>
      </div>
      <div class="notice"><strong>{headline}</strong></div>
      <div class="control-facts">
        <div><span>Cuentas</span><strong>{accounts}</strong></div>
        <div><span>Riesgo</span><strong>{risk}</strong></div>
        <div><span>Score de riesgo</span><strong>{risk_score}</strong></div>
        <div><span>Alertas prioritarias</span><strong>{alerts}</strong></div>
        <div><span>Resultados completos</span><strong>{complete}/30</strong></div>
        <div><span>Precisión verificada</span><strong>{precision}</strong></div>
      </div>
      <div class="control-facts">
        <div><span>Eventos semanales</span><strong>{weekly_events}</strong></div>
        <div><span>Riesgos abiertos semana</span><strong>{weekly_opened}</strong></div>
        <div><span>Riesgos resueltos semana</span><strong>{weekly_resolved}</strong></div>
        <div><span>Último diario</span><strong>{daily_age}</strong></div>
        <div><span>Último semanal</span><strong>{weekly_age}</strong></div>
        <div><span>Pendientes ejecutivos</span><strong>{pending_count}</strong></div>
      </div>
      <h3>Prioridades ejecutivas</h3>
      <div class="scenario-grid">{pending}</div>
      <div class="actions">
        <form method="post" action="/executive-report-daily" data-busy="Generando reporte ejecutivo diario"><button class="secondary">Actualizar reporte diario</button></form>
        <form method="post" action="/executive-report-weekly" data-busy="Generando reporte ejecutivo semanal"><button class="secondary">Actualizar reporte semanal</button></form>
      </div>
      <p class="muted">Los reportes quedan archivados localmente y se actualizan por horario. No envían mensajes, no cambian reglas y no autorizan órdenes.</p>
    </section>
    """.format(
        status_class=html_escape(str(daily.get("status") or "unknown").lower()),
        status=html_escape(daily.get("status") or "SIN REPORTE"),
        headline=html_escape(daily.get("headline") or "Sin lectura ejecutiva."),
        accounts=html_escape(portfolio.get("account_count") or 0),
        risk=html_escape(portfolio.get("risk_status") or "UNKNOWN"),
        risk_score=html_escape(portfolio.get("risk_score") if portfolio.get("risk_score") is not None else "N/D"),
        alerts=html_escape(portfolio.get("critical_high_alert_count") or 0),
        complete=html_escape(evidence.get("complete_closed_outcomes") or 0),
        precision=html_escape(f"{precision:.1f}%" if isinstance(precision, (int, float)) else "Sin muestra"),
        weekly_events=html_escape(weekly_activity.get("risk_event_count") or 0),
        weekly_opened=html_escape(weekly_activity.get("risk_events_opened") or 0),
        weekly_resolved=html_escape(weekly_activity.get("risk_events_resolved") or 0),
        daily_age=html_escape(age_label(daily.get("generated_at")) if daily.get("generated_at") else "Sin reporte"),
        weekly_age=html_escape(age_label(weekly.get("generated_at")) if weekly.get("generated_at") else "Sin reporte"),
        pending_count=html_escape(daily.get("pending_action_count") or 0),
        pending="".join(pending_rows) or '<p class="empty">Sin pendientes ejecutivos.</p>',
    )


def load_preventive_maintenance() -> dict[str, Any]:
    payload = shared_risk_operations.load_json(PREVENTIVE_MAINTENANCE_PATH)
    return payload if payload.get("maintenance_version") else shared_preventive_maintenance.build_maintenance_report(RUNTIME)


def render_preventive_maintenance_panel() -> str:
    payload = load_preventive_maintenance()
    summary = payload.get("summary") or {}
    action_cards = []
    for item in payload.get("actions") or []:
        action_cards.append("""
          <article class="scenario-card">
            <div class="scenario-head"><strong>{title}</strong><span>{priority}</span></div>
            <p>{detail}</p>
          </article>
        """.format(
            title=html_escape(item.get("title") or "Revisión"),
            priority=html_escape(item.get("priority") or "WATCH"),
            detail=html_escape(item.get("detail") or ""),
        ))
    return """
    <section class="panel preventive-maintenance status-{status_class}">
      <div class="section-head">
        <div><h2>Mantenimiento preventivo</h2><p>Datos, procesos, conexión IBKR, históricos y almacenamiento.</p></div>
        <strong>{status}</strong>
      </div>
      <div class="control-facts">
        <div><span>Archivos saludables</span><strong>{healthy}/{files}</strong></div>
        <div><span>Datos vencidos/advertencias</span><strong>{warnings}</strong></div>
        <div><span>Fallas altas</span><strong>{high}</strong></div>
        <div><span>Procesos instalados</span><strong>{installed}/{jobs}</strong></div>
        <div><span>Conexión IBKR</span><strong>{bridge}</strong></div>
        <div><span>Acciones pendientes</span><strong>{actions}</strong></div>
      </div>
      <div class="control-facts">
        <div><span>Archivos runtime</span><strong>{runtime_files}</strong></div>
        <div><span>Tamaño runtime</span><strong>{runtime_size} MB</strong></div>
        <div><span>Espacio libre</span><strong>{disk_free} GB</strong></div>
        <div><span>Almacenamiento</span><strong>{storage}</strong></div>
        <div><span>Última revisión</span><strong>{age}</strong></div>
        <div><span>Autoeliminación</span><strong>DESACTIVADA</strong></div>
      </div>
      <div class="scenario-grid">{action_cards}</div>
      <form method="post" action="/preventive-maintenance" data-busy="Ejecutando mantenimiento preventivo" data-busy-detail="Diagnostica sin borrar archivos ni reiniciar servicios.">
        <button class="secondary">Revisar mantenimiento ahora</button>
      </form>
      <p class="muted">El mantenimiento automático diagnostica y prioriza. Cualquier eliminación, rotación material o reinicio requiere una acción separada y explícita.</p>
    </section>
    """.format(
        status_class=html_escape(str(payload.get("status") or "unknown").lower()),
        status=html_escape(payload.get("status") or "SIN REPORTE"),
        healthy=html_escape(summary.get("healthy_file_count") or 0),
        files=html_escape(summary.get("file_check_count") or 0),
        warnings=html_escape(summary.get("stale_or_warning_file_count") or 0),
        high=html_escape(summary.get("high_file_count") or 0),
        installed=html_escape(summary.get("installed_job_count") or 0),
        jobs=html_escape(summary.get("expected_job_count") or 0),
        bridge="CONECTADO" if summary.get("bridge_connected") else "REVISAR",
        actions=html_escape(summary.get("action_count") or 0),
        runtime_files=html_escape(summary.get("runtime_file_count") or 0),
        runtime_size=html_escape(summary.get("runtime_size_mb") or 0),
        disk_free=html_escape(summary.get("disk_free_gb") or 0),
        storage=html_escape(summary.get("storage_status") or "UNKNOWN"),
        age=html_escape(age_label(payload.get("generated_at")) if payload.get("generated_at") else "Sin revisión"),
        action_cards="".join(action_cards) or '<p class="empty">Sin acciones preventivas pendientes.</p>',
    )


def render_portfolio_operations_panel() -> str:
    status = shared_risk_operations.load_json(PORTFOLIO_RISK_OPERATIONS_STATUS_PATH)
    outbox = shared_risk_operations.load_json(PORTFOLIO_RISK_OUTBOX_PATH)
    digest = shared_risk_operations.load_json(PORTFOLIO_RISK_DIGEST_PATH)
    observation = shared_risk_operations.load_json(PORTFOLIO_RISK_OBSERVATION_PATH)
    actions = shared_risk_operations.load_json(PORTFOLIO_RISK_ACTIONS_PATH)
    action_rows = actions.get("actions") if isinstance(actions.get("actions"), dict) else {}
    installed_jobs = sum(
        1
        for label in [
            "com.stockultimus.portfolio-risk-monitor",
            "com.stockultimus.portfolio-risk-digest",
            "com.stockultimus.portfolio-risk-preflight",
        ]
        if (Path.home() / "Library" / "LaunchAgents" / f"{label}.plist").exists()
    )
    return """
    <section class="panel portfolio-operations">
      <div class="section-head">
        <div><h2>Operación y mantenimiento</h2><p>Automatización local, trazable y sin ejecución de órdenes.</p></div>
        <strong>{automation}</strong>
      </div>
      <div class="control-facts">
        <div><span>Último ciclo</span><strong>{cycle}</strong></div>
        <div><span>Outbox pendiente</span><strong>{pending}</strong></div>
        <div><span>Acciones humanas</span><strong>{actions}</strong></div>
        <div><span>Digest</span><strong>{digest}</strong></div>
        <div><span>Observación</span><strong>{observed}/{target}</strong></div>
      </div>
      <p class="muted">Notificación local: {local_notify} · notificación externa: DESACTIVADA · jobs instalados {installed}/3 · calibración: {observation_status} · faltan {remaining} sesiones limpias.</p>
      <div class="actions">
        <form method="post" action="/portfolio-risk-operations-run" data-busy="Ejecutando mantenimiento de riesgo" data-busy-detail="Reevalúa, actualiza outbox y digest sin consultar ni operar el broker.">
          <button>Ejecutar mantenimiento ahora</button>
        </form>
      </div>
    </section>
    """.format(
        automation=html_escape("AUTOMATIZADO" if installed_jobs == 3 else "LISTO PARA ACTIVAR"),
        cycle=html_escape(status.get("status") or "SIN EJECUTAR"),
        pending=html_escape(outbox.get("pending_count") or 0),
        actions=html_escape(len(action_rows)),
        digest=html_escape("LISTO" if digest.get("digest_version") else "PENDIENTE"),
        observed=html_escape(observation.get("consecutive_clean_sessions") or 0),
        target=html_escape(observation.get("target_sessions") or 5),
        observation_status=html_escape(observation.get("status") or "OBSERVING"),
        remaining=html_escape(observation.get("remaining_clean_sessions") if observation.get("remaining_clean_sessions") is not None else 5),
        local_notify=html_escape("ACTIVA" if status.get("local_notifications_enabled") else "INACTIVA"),
        installed=html_escape(installed_jobs),
    )


def render_job_panel(job_id: str = "") -> tuple[str, str]:
    job = web_job(job_id)
    if not job:
        return "", ""
    status = str(job.get("status") or "UNKNOWN")
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    result_html = ""
    if result:
        diagnostic = console_job_diagnostic(result)
        daily_open_summary = render_daily_open_summary(result)
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
        {daily_open_summary}
        {verification}
        <p><strong>Resultado:</strong> returncode={returncode}</p>
        <pre>{stdout}{stderr}</pre>
        """.format(
            diagnostic=diagnostic,
            daily_open_summary=daily_open_summary,
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
        <li><span>Comando</span><strong class="job-command">{command}</strong></li>
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


def console_last_action_status(result: dict[str, Any]) -> str:
    text = "\n".join([str(result.get("stdout_tail") or ""), str(result.get("stderr_tail") or "")])
    if is_daily_open_result(result):
        report = load_json_file(DAILY_OPEN_CHECKLIST_PATH)
        status = effective_daily_open_status(report)
        if status == "ACTION_REQUIRED":
            return "APERTURA: requiere revision"
        if status in {"READY", "WAIT_MARKET", "REVIEW_REQUIRED", "EVIDENCE_COLLECTION_ONLY"}:
            return "APERTURA: completada"
        return "APERTURA: " + status
    inferred_partial = "BRIDGE_TIMEOUT" in text and "FALLBACK_PUBLISHED" in text and "ok: True" in text
    if result.get("partial_refresh_ok") or result.get("operator_status") == "PARTIAL_REFRESH_OK" or inferred_partial:
        return "PARCIAL: contexto publicado, bridge IBKR no completo"
    returncode_value = result.get("returncode")
    try:
        return "OK" if int(returncode_value or 0) == 0 else "REVISAR"
    except Exception:
        return "REVISAR"


def console_last_action_summary(result: dict[str, Any]) -> str:
    text = "\n".join([str(result.get("stdout_tail") or ""), str(result.get("stderr_tail") or "")])
    if is_daily_open_result(result):
        report = load_json_file(DAILY_OPEN_CHECKLIST_PATH)
        status = effective_daily_open_status(report)
        next_action = report.get("next_required_action") or "Revisar el resumen operativo de Apertura diaria."
        if status == "ACTION_REQUIRED":
            return "Apertura diaria corrio, pero no quedo lista para confiar sin revision. Siguiente paso: " + str(next_action)
        if status == "EVIDENCE_COLLECTION_ONLY":
            return "Apertura tecnica completa. El sistema queda acumulando evidencia; no es un fallo de conexion ni publicacion."
        return "Apertura diaria genero reporte: {}. Siguiente paso: {}".format(status, next_action)
    inferred_partial = "BRIDGE_TIMEOUT" in text and "FALLBACK_PUBLISHED" in text and "ok: True" in text
    if result.get("partial_refresh_ok") or result.get("operator_status") == "PARTIAL_REFRESH_OK" or inferred_partial:
        return (
            "El refresh IBKR no terminó a tiempo, pero la consola publicó contexto fallback a Render. "
            "Puedes seguir leyendo estado/GPT; para datos frescos de opciones, reintenta Refresh IBKR cuando TWS esté estable."
        )
    if result.get("returncode") not in [0, "0", None]:
        return "La última acción técnica requiere revisión. Abre el detalle solo si necesitas diagnosticar."
    return "Última acción completada correctamente."


def operator_guide_inline(value: str) -> str:
    """Render the small inline subset used by the trusted local guide."""
    escaped = html_escape(value)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def operator_guide_markdown_to_html(markdown_text: str) -> str:
    """Render the project's operator guide without an external dependency."""
    lines = markdown_text.splitlines()
    rendered: list[str] = []
    paragraph: list[str] = []
    list_kind = ""
    in_code = False
    code_lines: list[str] = []

    def close_paragraph() -> None:
        if paragraph:
            rendered.append("<p>{}</p>".format(operator_guide_inline(" ".join(paragraph))))
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            rendered.append(f"</{list_kind}>")
            list_kind = ""

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            close_paragraph()
            close_list()
            if in_code:
                rendered.append("<pre><code>{}</code></pre>".format(html_escape("\n".join(code_lines))))
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not stripped:
            close_paragraph()
            close_list()
            index += 1
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            close_paragraph()
            close_list()
            level = len(heading.group(1))
            rendered.append(f"<h{level}>{operator_guide_inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        if stripped.startswith("|") and index + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[index + 1]):
            close_paragraph()
            close_list()
            headers = [cell.strip() for cell in stripped.strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            rendered.append("<div class=\"guide-table\"><table><thead><tr>{}</tr></thead><tbody>{}</tbody></table></div>".format(
                "".join(f"<th>{operator_guide_inline(cell)}</th>" for cell in headers),
                "".join("<tr>{}</tr>".format("".join(f"<td>{operator_guide_inline(cell)}</td>" for cell in row)) for row in rows),
            ))
            continue
        unordered = re.match(r"^-\s+(.+)$", stripped)
        ordered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if unordered or ordered:
            close_paragraph()
            requested_kind = "ul" if unordered else "ol"
            if list_kind != requested_kind:
                close_list()
                list_kind = requested_kind
                rendered.append(f"<{list_kind}>")
            rendered.append("<li>{}</li>".format(operator_guide_inline((unordered or ordered).group(1))))
            index += 1
            continue
        paragraph.append(stripped)
        index += 1

    close_paragraph()
    close_list()
    if in_code:
        rendered.append("<pre><code>{}</code></pre>".format(html_escape("\n".join(code_lines))))
    return "\n".join(rendered)


def render_operator_guide_page() -> bytes:
    try:
        markdown_text = OPERATOR_GUIDE_PATH.read_text(encoding="utf-8")
        guide_html = operator_guide_markdown_to_html(markdown_text)
        guide_status = "Guía oficial cargada desde el proyecto"
    except Exception as exc:
        guide_html = "<h1>Guía no disponible</h1><p>{}</p>".format(html_escape(str(exc)))
        guide_status = "Revisar archivo oficial"
    page = """
    <!doctype html>
    <html lang="es">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Guía · Stock Ultimus Console</title>
        <style>
          :root {{ --ink:#111827; --muted:#5b6472; --paper:#f4f7fb; --card:#fff; --line:#d9e2ec; --accent:#11725f; }}
          * {{ box-sizing:border-box; }}
          body {{ margin:0; color:var(--ink); background:var(--paper); font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.58; }}
          main {{ width:min(980px,calc(100% - 24px)); margin:24px auto 60px; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:clamp(20px,5vw,54px); box-shadow:0 12px 36px rgba(17,24,39,.08); }}
          .guide-top {{ position:sticky; top:8px; z-index:2; display:flex; flex-wrap:wrap; justify-content:space-between; gap:10px; align-items:center; padding:10px 12px; margin:-8px 0 28px; background:rgba(255,255,255,.96); border:1px solid var(--line); border-radius:10px; }}
          .guide-top a {{ color:white; background:var(--accent); padding:8px 12px; border-radius:8px; text-decoration:none; font-weight:800; }}
          .guide-top span {{ color:var(--muted); font-size:.86rem; }}
          h1 {{ font-size:clamp(2rem,5vw,3.2rem); line-height:1.05; margin:0 0 22px; }}
          h2 {{ margin:42px 0 12px; padding-top:10px; border-top:1px solid var(--line); font-size:1.45rem; }}
          h3 {{ margin:26px 0 8px; font-size:1.12rem; }}
          p,li {{ max-width:78ch; }}
          li {{ margin:5px 0; }}
          code {{ background:#eef2f7; border-radius:5px; padding:2px 5px; }}
          pre {{ overflow:auto; max-width:100%; padding:16px; border-radius:9px; color:#f8fafc; background:#111827; }}
          pre code {{ padding:0; background:transparent; }}
          .guide-table {{ overflow-x:auto; border:1px solid var(--line); border-radius:9px; margin:14px 0 22px; }}
          table {{ width:100%; min-width:620px; border-collapse:collapse; }}
          th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
          th {{ background:#f8fafc; font-size:.8rem; text-transform:uppercase; }}
          @media (max-width:640px) {{ main {{ margin-top:8px; }} .guide-top {{ top:4px; }} }}
        </style>
      </head>
      <body>
        <main>
          <div class="guide-top"><a href="/console">← Volver a la consola</a><span>{status}</span></div>
          {guide}
        </main>
      </body>
    </html>
    """.format(status=html_escape(guide_status), guide=guide_html)
    return page.encode("utf-8")


def render_web_page(message: str = "", result: dict[str, Any] | None = None, job_id: str = "", question_answer: str = "") -> bytes:
    current_job = web_job(job_id)
    prefer_cache = True
    data = load_profiles()
    profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    active = active_profile()
    snapshot = latest_master_snapshot()
    operator_payload = console_operator_payload(prefer_cache=prefer_cache)
    v31_payloads = console_v31_payloads(prefer_cache=prefer_cache)
    reports = console_reports()
    position_payload = console_active_position_management(snapshot, v31_payloads)
    risk_payload = load_portfolio_risk(profiles, active)
    rsp_payload = shared_coberturas_engine.build_recommendation(RUNTIME)
    result = result or web_last_result()
    refresh_meta, job_panel = render_job_panel(job_id)
    manual_review_html = render_v31_manual_review_panel(v31_payloads)
    coberturas = render_coberturas_inline_panel(rsp_payload)
    v31_console_support = render_support_bundle(
        "Estado Ejecutivo y Revision Manual V31",
        render_v31_executive_panel(v31_payloads),
        manual_review_html,
    )
    question_support = render_support_bundle(
        "Pregunta operativa local",
        render_local_question_panel(question_answer),
    )
    admin_support = render_support_bundle(
        "Capacidad y administracion operativa",
        render_account_capacity_panel(operator_payload, snapshot),
        render_gamma_context_panel(position_payload),
        render_console_actions(active, snapshot, operator_payload),
    )

    output = ""
    if result:
        last_action_status = console_last_action_status(result)
        last_action_summary = console_last_action_summary(result)
        daily_open_summary = render_daily_open_summary(result)
        output_open_attr = " open" if is_daily_open_result(result) and "requiere revision" in last_action_status.lower() else ""
        output = """
        <details class="panel support-details"{output_open_attr}>
          <summary>Ultima accion tecnica: {status}</summary>
          <p class="muted">{summary}</p>
          {daily_open_summary}
          <p><strong class="job-command">{command}</strong> | alias={alias} scope={scope} | returncode={returncode}</p>
          <pre>{stdout}{stderr}</pre>
        </details>
        """.format(
            output_open_attr=output_open_attr,
            status=html_escape(last_action_status),
            summary=html_escape(last_action_summary),
            daily_open_summary=daily_open_summary,
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
          :root {{ --ink:#111827; --muted:#5b6472; --paper:#f4f7fb; --card:#ffffff; --soft:#f8fafc; --accent:#11725f; --accent-strong:#0f5f50; --line:#d9e2ec; --warn:#a45f09; --risk:#b42318; --info:#2563eb; --display: ui-serif, Georgia, Cambria, "Times New Roman", serif; --body: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
          *,*::before,*::after {{ box-sizing:border-box; }}
          html,body {{ max-width:100%; overflow-x:clip; }}
          body {{ margin:0; font-family:var(--body); color:var(--ink); background:var(--paper); }}
          main {{ max-width:1180px; margin:0 auto; padding:28px 18px 60px; }}
          [id] {{ scroll-margin-top:84px; }}
          h1 {{ font-family:var(--display); font-size:3.25rem; line-height:1; margin:0 0 12px; letter-spacing:0; }}
          h2 {{ margin:0 0 12px; font-size:1.25rem; }}
          h3 {{ margin:0; font-size:1.05rem; }}
          .lede,.body-text {{ color:var(--muted); max-width:720px; font-size:.95rem; line-height:1.45; }}
          .notice,.panel,.card {{ border:1px solid var(--line); background:var(--card); border-radius:8px; box-shadow:0 8px 24px rgba(17,24,39,.06); }}
          .notice {{ padding:14px 18px; margin:22px 0; }}
          .today-panel {{ border-color:#bfd7ff; border-left:6px solid #2563eb; background:#f7fbff; }}
          .today-panel .section-head {{ gap:14px; }}
          .today-panel .section-head h2 {{ margin-bottom:0; font-size:1.15rem; }}
          .today-panel .section-head p:last-child {{ font-size:.92rem; line-height:1.35; }}
          .today-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; }}
          .app-header {{ display:grid; grid-template-columns:minmax(220px,1fr) auto; gap:12px 18px; align-items:center; border:1px solid var(--line); border-left:6px solid #16a34a; border-radius:12px; padding:14px 16px; margin-bottom:14px; background:var(--card); box-shadow:0 8px 24px rgba(17,24,39,.06); }}
          .app-header.health-amber {{ border-left-color:#d97706; }}
          .app-header.health-red {{ border-left-color:#b42318; }}
          .app-health {{ display:flex; align-items:center; gap:12px; min-width:0; }}
          .app-health strong,.app-health small {{ display:block; }}
          .app-health small {{ color:var(--muted); margin-top:3px; line-height:1.3; }}
          .app-health-chips {{ display:flex; flex-wrap:wrap; gap:6px; justify-content:flex-end; }}
          .health-chip {{ border:1px solid var(--line); border-radius:999px; padding:6px 9px; font-size:.76rem; font-weight:850; background:var(--soft); }}
          .health-chip.ok {{ color:#05603a; border-color:#86d5aa; background:#f3fbf6; }}
          .health-chip.warn {{ color:#7a3b09; border-color:#f4c58f; background:#fff8ed; }}
          .header-actions {{ grid-column:1 / -1; display:flex; align-items:center; gap:8px; border-top:1px solid var(--line); padding-top:11px; }}
          .header-actions form {{ margin:0; }}
          button.primary-action {{ background:#0f6b57; padding:11px 16px; }}
          .header-more {{ position:relative; }}
          .header-more > summary {{ cursor:pointer; font-weight:800; color:var(--muted); padding:8px 10px; }}
          .header-more > div {{ position:absolute; z-index:12; left:0; top:calc(100% + 6px); width:min(360px,80vw); display:grid; gap:8px; border:1px solid var(--line); border-radius:10px; padding:12px; background:white; box-shadow:0 16px 40px rgba(17,24,39,.16); }}
          .header-more small {{ color:var(--muted); line-height:1.3; }}
          .command-center {{ padding:0; overflow:hidden; border-left:6px solid #d97706; }}
          .command-green {{ border-left-color:#16a34a; }} .command-red {{ border-left-color:#b42318; }} .command-blue {{ border-left-color:#2563eb; }}
          .command-head {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(190px,.32fr); gap:20px; padding:20px; background:linear-gradient(135deg,#ffffff,#f8fafc); border-bottom:1px solid var(--line); }}
          .command-head h2 {{ font-size:1.45rem; margin-bottom:6px; }}
          .command-head p {{ margin:0; color:var(--muted); line-height:1.4; }}
          .opening-status {{ border-left:1px solid var(--line); padding-left:18px; }}
          .opening-status span,.opening-status strong,.opening-status small {{ display:block; }}
          .opening-status span {{ color:var(--muted); text-transform:uppercase; font-size:.7rem; font-weight:900; }}
          .opening-status strong {{ margin:5px 0 3px; font-size:1.1rem; }}
          .opening-status small {{ color:var(--muted); }}
          .command-facts,.position-overview {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0; border-bottom:1px solid var(--line); }}
          .command-facts > div,.position-overview > div {{ padding:14px 16px; border-right:1px solid var(--line); min-width:0; }}
          .command-facts > div:last-child,.position-overview > div:last-child {{ border-right:0; }}
          .command-facts span,.command-facts strong,.command-facts small,.position-overview span,.position-overview strong,.position-overview small {{ display:block; overflow-wrap:anywhere; }}
          .command-facts span,.position-overview span {{ color:var(--muted); font-size:.72rem; text-transform:uppercase; font-weight:850; }}
          .command-facts strong,.position-overview strong {{ font-size:1.05rem; margin:4px 0; }}
          .command-facts small,.position-overview small {{ color:var(--muted); line-height:1.25; }}
          .pending-queue {{ padding:18px 20px 20px; }}
          .queue-head {{ display:flex; align-items:baseline; justify-content:space-between; gap:14px; margin-bottom:10px; }}
          .queue-head h3 {{ margin:0; }} .queue-head span {{ color:var(--muted); font-size:.84rem; }}
          .operator-task {{ display:grid; grid-template-columns:30px minmax(0,1fr) auto; gap:12px; align-items:center; color:var(--ink); text-decoration:none; border:1px solid var(--line); border-left:5px solid #2563eb; border-radius:10px; padding:11px 13px; margin-top:8px; background:#fff; }}
          .operator-task.task-critical {{ border-left-color:#b42318; }} .operator-task.task-high {{ border-left-color:#d97706; }}
          .operator-task > span {{ display:grid; place-items:center; width:28px; height:28px; border-radius:999px; background:var(--soft); font-weight:900; }}
          .operator-task small,.operator-task strong,.operator-task p {{ display:block; margin:0; }}
          .operator-task small {{ color:var(--muted); text-transform:uppercase; font-size:.68rem; font-weight:900; }}
          .operator-task strong {{ margin-top:2px; }} .operator-task p {{ color:var(--muted); font-size:.84rem; margin-top:2px; line-height:1.3; }}
          .operator-task > b {{ color:var(--accent-strong); font-size:.82rem; white-space:nowrap; }}
          .empty-state {{ display:flex; justify-content:space-between; gap:12px; border:1px solid #86d5aa; border-radius:10px; padding:14px; background:#f3fbf6; }}
          .empty-state span {{ color:var(--muted); }}
          .secondary-workspace {{ margin-top:14px; }}
          .position-overview {{ margin:14px 0; border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
          .position-summary {{ color:var(--muted); margin:10px 0 0; line-height:1.35; }}
          .position-details,.operator-subsection {{ border:1px solid var(--line); border-radius:10px; margin-top:12px; background:#fff; overflow:hidden; }}
          .position-details > summary,.operator-subsection > summary {{ cursor:pointer; padding:12px 14px; font-weight:850; color:var(--accent-strong); }}
          .position-details[open] > summary,.operator-subsection[open] > summary {{ border-bottom:1px solid var(--line); background:var(--soft); }}
          .position-details > :not(summary),.operator-subsection > :not(summary) {{ margin-left:12px; margin-right:12px; }}
          .position-detail-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; padding-top:12px; }}
          .position-detail-grid span,.position-detail-grid strong {{ display:block; }}
          .position-detail-grid span {{ color:var(--muted); font-size:.75rem; }}
          .technical-details {{ margin-top:8px; color:var(--muted); }}
          .technical-details > summary {{ cursor:pointer; font-size:.82rem; font-weight:800; }}
          .readiness-pill {{ align-self:flex-start; border-radius:999px; padding:7px 10px; font-size:.78rem; font-weight:900; }}
          .readiness-ready {{ color:#05603a; background:#e9f8ef; }} .readiness-review {{ color:#7a3b09; background:#fff3dd; }}
          .rsp-status-line {{ display:flex; justify-content:space-between; gap:16px; border:1px solid #f4c58f; border-radius:10px; padding:12px 14px; background:#fff8ed; }}
          .rsp-status-line.status-ready {{ border-color:#86d5aa; background:#f3fbf6; }}
          .rsp-status-line span {{ color:var(--muted); text-align:right; }}
          .rsp-decision-body {{ margin-top:12px; }}
          .section-actions {{ display:flex; flex-wrap:wrap; align-items:center; gap:12px; margin-top:14px; }}
          .text-link {{ color:var(--accent-strong); font-weight:800; }}
          .control-strip {{ display:grid; grid-template-columns:minmax(220px,.95fr) minmax(360px,1.45fr) minmax(190px,.8fr); gap:10px; align-items:center; border:1px solid var(--line); border-left-width:6px; border-radius:8px; padding:10px 12px; margin-bottom:14px; background:var(--card); box-shadow:0 8px 24px rgba(17,24,39,.06); }}
          .health-green {{ border-left-color:#16a34a; }}
          .health-amber {{ border-left-color:#d97706; }}
          .health-red {{ border-left-color:#b42318; }}
          .signal {{ display:flex; align-items:center; gap:12px; }}
          .signal strong,.signal small,.thinking-now strong,.thinking-now small {{ display:block; }}
          .signal strong,.thinking-now strong {{ font-size:.98rem; }}
          .signal small,.thinking-now small {{ color:var(--muted); margin-top:2px; font-size:.82rem; line-height:1.25; }}
          .signal-dot {{ width:14px; height:14px; border-radius:999px; flex:0 0 auto; box-shadow:0 0 0 5px rgba(0,0,0,.04); }}
          .health-green .signal-dot {{ background:#16a34a; box-shadow:0 0 0 6px rgba(22,163,74,.14); }}
          .health-amber .signal-dot {{ background:#d97706; box-shadow:0 0 0 6px rgba(217,119,6,.16); }}
          .health-red .signal-dot {{ background:#b42318; box-shadow:0 0 0 6px rgba(180,35,24,.14); }}
          .control-facts {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:6px; }}
          .control-facts span {{ border:1px solid var(--line); border-radius:8px; background:var(--soft); padding:6px 8px; font-size:.86rem; color:var(--ink); font-weight:800; min-height:40px; display:flex; flex-direction:column; justify-content:center; }}
          .control-facts b {{ color:var(--muted); font-size:.66rem; text-transform:uppercase; margin-bottom:1px; }}
          .thinking-now {{ border-left:1px solid var(--line); padding-left:10px; }}
          .operator-next {{ grid-column:1 / -1; display:grid; grid-template-columns:180px 1fr auto; gap:10px; align-items:center; border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#ffffff; }}
          .signal,.thinking-now,.control-facts,.operator-next,.top-quick-actions {{ min-width:0; }}
          .signal strong,.signal small,.thinking-now strong,.thinking-now small,.operator-next strong,.operator-next small,.top-quick-actions span {{ overflow-wrap:anywhere; }}
          .operator-next span {{ color:var(--muted); font-size:.72rem; text-transform:uppercase; font-weight:900; }}
          .operator-next strong {{ font-size:1rem; line-height:1.25; }}
          .operator-next small {{ color:var(--muted); font-weight:800; }}
          .next-green {{ border-color:#86d5aa; background:#f3fbf6; }}
          .next-amber {{ border-color:#f4c58f; background:#fff8ed; }}
          .next-red {{ border-color:#f4a6a6; background:#fff5f5; }}
          .top-quick-actions {{ grid-column:1 / -1; display:flex; flex-wrap:wrap; gap:8px; border-top:1px solid var(--line); padding-top:9px; }}
          .top-quick-actions form {{ display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin:0; }}
          .top-quick-actions button {{ padding:8px 11px; font-size:.9rem; }}
          .top-quick-actions span {{ color:var(--muted); font-size:.8rem; }}
          .operator-nav {{ position:sticky; top:8px; z-index:10; display:flex; gap:6px; align-items:center; overflow-x:auto; margin:0 0 14px; padding:7px; border:1px solid var(--line); border-radius:10px; background:rgba(255,255,255,.96); box-shadow:0 8px 24px rgba(17,24,39,.10); backdrop-filter:blur(10px); }}
          .operator-nav a {{ flex:0 0 auto; color:var(--ink); text-decoration:none; font-size:.84rem; font-weight:850; border-radius:7px; padding:8px 10px; }}
          .operator-nav a:hover,.operator-nav a:focus-visible {{ color:var(--accent-strong); background:#eaf6f2; outline:none; }}
          .operator-workspace {{ padding:0; overflow:hidden; margin-top:18px; background:#fbfcfe; }}
          .operator-workspace > summary {{ cursor:pointer; list-style:none; display:flex; justify-content:space-between; gap:18px; align-items:center; padding:17px 20px; }}
          .operator-workspace > summary::-webkit-details-marker {{ display:none; }}
          .operator-workspace > summary::after {{ content:"Abrir"; flex:0 0 auto; color:var(--accent-strong); background:#eaf6f2; border-radius:999px; padding:6px 10px; font-size:.78rem; font-weight:900; }}
          .operator-workspace[open] > summary::after {{ content:"Cerrar"; }}
          .operator-workspace > summary span,.operator-workspace > summary small {{ display:block; }}
          .operator-workspace > summary span {{ font-weight:900; }}
          .operator-workspace > summary small {{ margin-top:3px; color:var(--muted); font-size:.8rem; line-height:1.3; }}
          .workspace-body {{ padding:0 18px 18px; border-top:1px solid var(--line); }}
          .workspace-body > .panel:first-child,.workspace-body > details:first-child {{ margin-top:18px; }}
          .hero-panel {{ display:grid; grid-template-columns:1.1fr .9fr; gap:24px; align-items:end; padding:28px; }}
          .embedded-panel {{ padding:12px 0 0; }}
          .eyebrow {{ text-transform:uppercase; letter-spacing:.16em; color:var(--accent); font-weight:800; font-size:.78rem; margin:0 0 12px; }}
          .context-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
          .capacity-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; }}
          .scenario-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; margin:10px 0; }}
          .scenario-card {{ border:1px solid var(--line); background:#ffffff; border-radius:8px; padding:12px; box-shadow:none; }}
          .scenario-head {{ display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:8px; }}
          .scenario-lines {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px 10px; }}
          .scenario-lines span {{ color:var(--muted); font-size:.75rem; }}
          .scenario-lines strong {{ display:block; color:var(--ink); font-family:var(--display); font-size:1.1rem; margin-top:2px; overflow-wrap:anywhere; }}
          .metric {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px; }}
          .metric span,.metric small {{ display:block; color:var(--muted); }}
          .metric .label-text,.metric span {{ font-family:var(--body); font-size:.75rem; text-transform:uppercase; font-weight:900; }}
          .metric strong {{ display:block; font-family:var(--display); font-size:1.55rem; line-height:1.1; margin:4px 0; color:var(--ink); overflow-wrap:anywhere; }}
          .compact-metrics .metric {{ padding:10px 12px; min-height:0; }}
          .compact-metrics .metric .label-text,.compact-metrics .metric span {{ font-size:.68rem; }}
          .compact-metrics .metric strong {{ font-family:var(--body); font-size:1rem; line-height:1.25; font-weight:850; }}
          .compact-metrics .metric small {{ font-size:.78rem; line-height:1.25; }}
          .hero-actions {{ grid-column:1 / -1; display:flex; flex-wrap:wrap; align-items:center; gap:10px; border-top:1px solid var(--line); padding-top:14px; }}
          .hero-actions span {{ color:var(--muted); font-size:.92rem; }}
          .warning {{ grid-column:1 / -1; background:#fff7ed; color:var(--warn); border:1px solid #f4c58f; border-radius:8px; padding:12px 14px; font-weight:700; }}
          .grid {{ display:grid; gap:14px; margin:22px 0; }}
          .card {{ display:flex; justify-content:space-between; gap:18px; padding:20px; align-items:center; }}
          .card.active {{ outline:3px solid rgba(29,107,79,.25); }}
          .card h3 {{ margin:0; font-family:var(--display); font-size:1.55rem; }}
          .card p {{ margin:5px 0; }}
          .muted,.empty {{ color:var(--muted); }}
          .actions {{ display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; }}
          .advanced-actions {{ width:100%; text-align:right; color:var(--muted); }}
          .advanced-actions summary {{ cursor:pointer; font-weight:800; }}
          .advanced-actions form {{ display:inline-block; margin:8px 0 0 6px; }}
          button {{ border:0; border-radius:8px; padding:10px 14px; background:var(--accent); color:white; font-weight:700; cursor:pointer; }}
          button:disabled {{ opacity:.62; cursor:wait; }}
          button.secondary {{ background:#475569; }}
          .panel {{ padding:20px; margin-top:20px; }}
          main,section,details,.panel,.support-bundle,.embedded-support-panel {{ min-width:0; max-width:100%; }}
          details:not([open]) > :not(summary) {{ display:none; }}
          details strong,details span,details small,details p {{ overflow-wrap:anywhere; }}
          .job-panel {{ border-color:#b88b2a; background:#fff8e7; }}
          .job-panel.status-done {{ border-color:#1d6b4f; background:#eef8ef; }}
          .job-panel.status-error {{ border-color:var(--risk); background:#fff1ef; }}
          .daily-open-summary {{ border:1px solid var(--line); border-left:6px solid #d97706; border-radius:8px; background:#ffffff; padding:14px; margin:12px 0; }}
          .daily-open-summary.summary-green {{ border-left-color:#16a34a; background:#f3fbf6; }}
          .daily-open-summary.summary-amber {{ border-left-color:#d97706; background:#fff8ed; }}
          .daily-open-summary.summary-red {{ border-left-color:#b42318; background:#fff5f5; }}
          .compact-status {{ margin-top:12px; }}
          .compact-status .tile {{ padding:10px 12px; }}
          .compact-status .tile span {{ font-size:.84rem; line-height:1.28; }}
          .module-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; }}
          .module-card {{ display:flex; gap:11px; align-items:flex-start; border:1px solid var(--line); background:var(--card); border-radius:8px; padding:12px; }}
          .module-card > div,.timeline li > div {{ min-width:0; }}
          .module-card strong,.module-card span,.module-card small {{ display:block; }}
          .module-card span {{ color:var(--ink); margin-top:2px; }}
          .module-card small {{ color:var(--muted); margin-top:3px; }}
          .module-dot {{ width:12px; height:12px; border-radius:999px; margin-top:4px; flex:0 0 auto; background:#94a3b8; box-shadow:0 0 0 5px rgba(148,163,184,.15); }}
          .module-green .module-dot,.timeline-green > span,.check-ok > span {{ background:#16a34a; box-shadow:0 0 0 5px rgba(22,163,74,.14); }}
          .module-amber .module-dot,.timeline-amber > span,.check-wait > span {{ background:#d97706; box-shadow:0 0 0 5px rgba(217,119,6,.16); }}
          .module-red .module-dot,.timeline-red > span {{ background:#b42318; box-shadow:0 0 0 5px rgba(180,35,24,.14); }}
          .timeline {{ list-style:none; padding:0; margin:14px 0 0; display:grid; gap:10px; }}
          .timeline li {{ display:flex; gap:12px; align-items:flex-start; border:1px solid var(--line); border-radius:8px; background:var(--card); padding:12px; }}
          .timeline li > span {{ width:12px; height:12px; border-radius:999px; margin-top:4px; flex:0 0 auto; background:#94a3b8; }}
          .timeline strong,.timeline small {{ display:block; }}
          .timeline small {{ color:var(--muted); margin-top:3px; }}
          .market-panel {{ border-color:#bfd7ff; background:#f5f9ff; }}
          .intraday-panel {{ border-color:#8ecae6; background:#f5fbff; }}
          .diagnostic-panel {{ border-color:#badbcc; background:#f7fff8; }}
          .positions-panel {{ border-left:6px solid #2563eb; background:#f7fbff; }}
          .positions-panel > .alert-grid {{ grid-template-columns:minmax(0,1fr); }}
          .position-card {{ border-color:#bfd7ff; min-width:0; overflow:hidden; }}
          .position-card > *,.position-alternatives,.position-recommendation,.position-structure,.position-comparison {{ min-width:0; max-width:100%; }}
          .position-card b,.position-card strong,.position-card span,.position-card small,.position-card p {{ overflow-wrap:anywhere; word-break:normal; }}
          .position-alternatives {{ display:grid; gap:7px; margin-top:12px; border-top:1px solid var(--line); padding-top:10px; }}
          .position-alternatives-head {{ display:flex; justify-content:space-between; gap:10px; align-items:baseline; }}
          .position-alternatives-head span {{ margin:0; font-size:.76rem; }}
          .position-alternative {{ border:1px solid var(--line); border-left:4px solid #94a3b8; border-radius:8px; padding:9px 10px; background:#fff; }}
          .position-alternative.alternative-primary {{ border-left-color:#2563eb; background:#f5f9ff; }}
          .position-recommendation {{ border:1px solid #93c5fd; border-left:6px solid #2563eb; border-radius:8px; padding:12px; background:#eff6ff; }}
          .position-recommendation > div {{ display:flex; justify-content:space-between; gap:10px; }}
          .position-recommendation > div span {{ font-size:.72rem; font-weight:900; color:#1d4ed8; }}
          .position-recommendation p {{ margin:7px 0; line-height:1.4; }}
          .position-recommendation small {{ color:var(--muted); }}
          .position-structure {{ display:grid; gap:8px; margin-top:10px; padding:10px; border:1px solid #bfdbfe; border-radius:8px; background:#fff; }}
          .position-structure-title {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:6px; align-items:baseline; }}
          .position-structure-title span {{ color:#1d4ed8; font-size:.74rem; font-weight:850; }}
          .position-structure-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }}
          .position-structure-leg {{ display:grid; gap:2px; padding:9px; border-radius:7px; border-left:4px solid #2563eb; background:#eff6ff; }}
          .position-structure-leg.protection-leg {{ border-left-color:#16a34a; background:#f0fdf4; }}
          .position-structure-leg span {{ font-size:.7rem; font-weight:850; color:var(--muted); text-transform:uppercase; }}
          .position-structure-leg b {{ font-size:.9rem; }}
          .position-structure-leg small {{ font-size:.7rem; }}
          .position-structure-result {{ display:grid; gap:2px; padding-top:7px; border-top:1px solid var(--line); }}
          .position-structure-result span {{ font-weight:900; font-size:.8rem; color:var(--ink); }}
          .position-structure-result small {{ font-size:.7rem; }}
          .position-comparison {{ display:grid; gap:7px; }}
          .position-profile-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:6px; }}
          .position-profile {{ display:grid; gap:2px; padding:8px; border:1px solid var(--line); border-radius:8px; background:#fbfdff; }}
          .position-profile span {{ color:var(--muted); font-size:.68rem; font-weight:800; text-transform:uppercase; }}
          .position-profile b {{ font-size:.8rem; }}
          .position-profile small {{ font-size:.68rem; color:var(--muted); }}
          .position-comparison details > summary {{ cursor:pointer; color:var(--accent-strong); font-size:.78rem; font-weight:850; }}
          .position-comparison-scroll {{ overflow-x:auto; max-width:100%; margin-top:7px; overscroll-behavior-inline:contain; -webkit-overflow-scrolling:touch; }}
          .position-comparison table {{ width:100%; border-collapse:collapse; font-size:.72rem; }}
          .position-comparison th, .position-comparison td {{ padding:5px 7px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
          .position-comparison th:first-child, .position-comparison td:first-child {{ text-align:left; }}
          .position-comparison details > small {{ display:block; margin-top:6px; color:var(--muted); font-size:.67rem; }}
          .position-alternative > div {{ display:flex; justify-content:space-between; gap:10px; }}
          .position-alternative > div span {{ margin:0; font-size:.72rem; font-weight:850; }}
          .position-alternative p {{ margin:5px 0; color:var(--muted); font-size:.82rem; line-height:1.3; }}
          .position-alternative small {{ margin:0; font-size:.74rem; line-height:1.3; }}
          .position-alternatives-more {{ margin-top:2px; }}
          .position-alternatives-more > summary {{ cursor:pointer; color:var(--accent-strong); font-size:.8rem; font-weight:850; }}
          .position-alternatives-more .position-alternative {{ margin-top:7px; }}
          .position-alternatives-empty {{ margin-top:10px; color:var(--muted); font-size:.82rem; }}
          .position-review-control,.position-review-confirmed,.position-data-required {{ display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; margin-top:10px; padding:10px; border:1px solid var(--line); border-radius:8px; background:#fff; }}
          .position-review-control small,.position-review-confirmed span,.position-data-required span {{ flex:1 1 220px; margin:0; font-size:.74rem; }}
          .position-review-confirmed {{ border-color:#86c99d; background:#f0fdf4; color:#166534; }}
          .position-data-required {{ border-color:#f2c47c; background:#fff8e8; }}
          .position-data-required a {{ color:#174ea6; font-weight:900; }}
          .operator-alerts-panel {{ border-left:6px solid #d97706; }}
          .support-details > summary,.diagnostic-alerts > summary {{ cursor:pointer; font-weight:900; color:var(--ink); }}
          .support-details[open] > summary,.diagnostic-alerts[open] > summary {{ margin-bottom:12px; }}
          .support-details .panel {{ box-shadow:none; margin-top:12px; }}
          .support-bundle {{ background:#fbfcfe; }}
          .embedded-support-panel {{ background:#ffffff; }}
          .diagnostic-alerts {{ margin-top:14px; border:1px dashed var(--line); border-radius:8px; padding:12px; background:var(--card); }}
          .diagnostic-alerts ul {{ margin:10px 0 0; padding-left:18px; color:var(--muted); }}
          .process-panel {{ border-color:#d97706; background:#fff8e7; }}
          .process-list {{ display:grid; gap:10px; margin-top:12px; }}
          .process-row {{ display:flex; align-items:center; gap:12px; border:1px solid #efc99d; border-radius:8px; background:#ffffff; padding:12px; color:var(--ink); text-decoration:none; }}
          .process-row strong,.process-row small {{ display:block; }}
          .process-row small {{ color:var(--muted); }}
          .process-pulse {{ width:12px; height:12px; border-radius:999px; background:#d97706; box-shadow:0 0 0 6px rgba(217,119,6,.16); animation:pulse 1.2s infinite ease-in-out; }}
          @keyframes pulse {{ 0%,100% {{ transform:scale(.86); opacity:.72; }} 50% {{ transform:scale(1.12); opacity:1; }} }}
          .job-facts {{ list-style:none; padding:0; margin:12px 0; display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:8px; }}
          .job-facts li {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:var(--card); }}
          .job-facts span,.job-facts strong {{ display:block; }}
          .job-facts span {{ color:var(--muted); font-size:.9rem; }}
          .job-facts strong {{ overflow-wrap:anywhere; }}
          .job-command {{ overflow-wrap:anywhere; word-break:break-word; }}
          .section-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:20px; }}
          .section-head p {{ margin:0; color:var(--muted); max-width:620px; }}
          .tiles,.alert-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
          .tiles > *,.alert-grid > *,.module-grid > *,.scenario-grid > *,.coberturas-grid > * {{ min-width:0; }}
          .tile,.alert-card {{ border:1px solid var(--line); background:var(--card); border-radius:8px; padding:14px; text-decoration:none; color:var(--ink); }}
          .inline-link {{ display:inline-block; }}
          .tile {{ font-weight:800; }}
          .tile span,.alert-card span,.alert-card small {{ display:block; color:var(--muted); margin-top:6px; font-weight:400; }}
          .alert-card strong {{ font-size:1.35rem; }}
          .alert-title {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:flex-start; gap:10px; }}
          .alert-title em {{ max-width:100%; font-style:normal; border-radius:999px; padding:5px 8px; background:#e8efe7; color:#1d6b4f; font-size:.78rem; font-weight:900; white-space:normal; overflow-wrap:anywhere; }}
          .success-line {{ display:inline-block; margin-top:8px; border-radius:999px; padding:6px 10px; background:#e8f7ee; color:#1d6b4f; font-weight:900; font-size:.9rem; }}
          .status-new .alert-title em {{ background:#fff4d6; color:#9f4b1b; }}
          .status-reviewing .alert-title em,.status-watchlist .alert-title em {{ background:#e8f1ff; color:#174ea6; }}
          .status-rejected .alert-title em,.status-risk-blocked .alert-title em {{ background:#fff1ef; color:var(--risk); }}
          .status-closed .alert-title em,.status-acknowledged .alert-title em,.status-approved-for-manual-review .alert-title em,.status-approved-for-manual-trade .alert-title em {{ background:#eef8ef; color:#1d6b4f; }}
          .contract-line,.review-line,.economics-line,.capacity-line,.lifecycle-line,.why-line {{ margin-top:8px; border:1px solid var(--line); border-radius:8px; padding:8px 10px; background:var(--soft); font-size:.92rem; line-height:1.35; }}
          .contract-line {{ font-weight:800; color:var(--ink); }}
          .economics-line {{ color:#1d6b4f; background:#f1fbf4; border-color:#badbcc; font-weight:800; }}
          .capacity-line {{ color:#174ea6; background:#eef5ff; border-color:#bfd7ff; font-weight:800; }}
          .lifecycle-line {{ color:#4f3a06; background:#fff8dd; border-color:#ead48a; font-weight:800; }}
          .why-line {{ background:#f7fbff; border-color:#bfd7ff; color:#174ea6; font-weight:800; }}
          .review-line {{ color:var(--warn); background:#fff7e8; }}
          .alert-checklist {{ list-style:none; padding:0; margin:10px 0 0; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }}
          .alert-checklist li {{ display:grid; grid-template-columns:14px 1fr; column-gap:7px; align-items:start; border:1px solid var(--line); border-radius:8px; padding:7px; background:white; }}
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
          .alert-actions .fill-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
          .alert-actions .actions {{ justify-content:flex-start; }}
          .alert-actions button {{ padding:8px 11px; font-size:.9rem; }}
          .manual-review-actions .approved-for-manual-trade {{ background:#16a34a; }}
          .manual-review-actions .reviewing {{ background:#d97706; }}
          .manual-review-actions .watchlist {{ background:#2563eb; }}
          .manual-review-actions .rejected {{ background:#dc2626; }}
          .manual-review-actions .expired {{ background:#475569; }}
          .severity-action {{ border-color:#d97706; }}
          .severity-risk {{ border-color:var(--risk); }}
          .severity-watch {{ border-color:#2563eb; }}
          .portfolio-risk.status-blocked {{ border-color:#dc7a68; background:#fff8f5; }}
          .portfolio-risk.status-action_required {{ border-color:#d97706; background:#fffbef; }}
          .portfolio-risk.status-watch {{ border-color:#6a8fc8; background:#f7faff; }}
          .risk-score {{ min-width:96px; text-align:center; border:1px solid var(--line); border-radius:16px; padding:9px 14px; background:#fffdf6; }}
          .risk-score span,.risk-score strong {{ display:block; }}
          .risk-score span {{ color:var(--muted); font-size:.82rem; }}
          .risk-score strong {{ font-size:1.35rem; }}
          .risk-alert-list {{ display:grid; gap:10px; margin-top:14px; }}
          .remaining-risk-alerts {{ margin-top:12px; border:1px dashed var(--line); border-radius:10px; padding:12px; background:#ffffff; }}
          .remaining-risk-alerts > summary {{ cursor:pointer; font-weight:900; color:var(--accent-strong); }}
          .risk-alert {{ border:1px solid var(--line); border-left-width:6px; border-radius:16px; padding:14px; background:#fffdf6; }}
          .risk-alert h3,.risk-alert p {{ margin:6px 0 0; }}
          .risk-alert-title {{ display:flex; justify-content:space-between; gap:12px; font-size:.82rem; letter-spacing:.04em; }}
          .risk-alert-title span {{ color:var(--muted); }}
          .risk-alert.severity-critical {{ border-left-color:#b42318; }}
          .risk-alert.severity-high {{ border-left-color:#d97706; }}
          .risk-alert.severity-watch {{ border-left-color:#2563eb; }}
          .risk-alert.severity-info {{ border-left-color:#1d6b4f; }}
          .risk-actions {{ margin-top:12px; padding-top:10px; border-top:1px solid var(--line); }}
          .risk-actions input {{ margin-bottom:8px; }}
          .risk-actions .actions {{ justify-content:flex-start; }}
          .risk-actions button {{ padding:8px 11px; font-size:.9rem; }}
          .portfolio-operations {{ background:#f8fbf6; }}
          label {{ display:block; margin:10px 0 4px; font-weight:700; }}
          input, select, textarea {{ width:min(520px,100%); border:1px solid var(--line); border-radius:8px; padding:11px 12px; font:inherit; background:white; box-sizing:border-box; }}
          textarea {{ width:100%; min-height:128px; resize:vertical; line-height:1.35; }}
          table {{ width:100%; border-collapse:collapse; }}
          th,td {{ padding:8px 9px; border-bottom:1px solid var(--line); text-align:left; font-size:.9rem; vertical-align:top; }}
          th {{ color:var(--muted); text-transform:uppercase; font-size:.72rem; }}
          .table-scroll {{ overflow-x:auto; max-width:100%; min-width:0; border:1px solid var(--line); border-radius:8px; background:#ffffff; }}
          .badge {{ display:inline-flex; border-radius:999px; padding:5px 9px; color:white; font-size:12px; font-weight:900; }}
          .badge.ok {{ background:#047857; }} .badge.warn {{ background:#b45309; }} .badge.risk {{ background:#b42318; }} .badge.info {{ background:#2563eb; }} .badge.neutral {{ background:#64748b; }}
          .coberturas-panel {{ border-color:#8ecae6; background:#ffffff; }}
          .coberturas-grid {{ display:grid; grid-template-columns:minmax(280px,.8fr) minmax(0,1.2fr); gap:14px; align-items:start; }}
          .coberturas-form,.coberturas-read {{ min-width:0; }}
          .coberturas-panel .metric,.coberturas-panel .scenario-card,.coberturas-panel .table-scroll {{ background:#ffffff; box-shadow:none; }}
          .coberturas-panel .status-metric .badge {{ background:#ffffff; color:var(--ink); border:1px solid var(--line); box-shadow:none; }}
          .coberturas-panel .status-metric .badge.ok {{ border-color:#86d5aa; color:#05603a; }}
          .coberturas-panel .status-metric .badge.warn {{ border-color:#f4c58f; color:#7a3b09; }}
          .coberturas-panel .status-metric .badge.info {{ border-color:#bfd7ff; color:#174ea6; }}
          .coberturas-panel .status-metric .badge.risk {{ border-color:#f4a6a6; color:#9f1239; }}
          .coberturas-panel .review-line {{ color:#7a3b09; background:#fff7ed; border-color:#f4c58f; }}
          .mini-tile {{ padding:9px 12px; border-radius:8px; }}
          pre {{ white-space:pre-wrap; overflow:auto; background:#111827; color:#f8fafc; border-radius:8px; padding:14px; max-height:360px; }}
          .busy-overlay[hidden] {{ display:none; }}
          .busy-overlay {{ position:fixed; inset:0; background:rgba(23,32,25,.62); display:grid; place-items:center; z-index:20; padding:20px; }}
          .busy-box {{ width:min(460px,100%); background:#ffffff; border:1px solid var(--line); border-radius:8px; padding:20px; box-shadow:0 18px 50px rgba(0,0,0,.22); }}
          .busy-box strong,.busy-box span {{ display:block; }}
          .busy-box span {{ color:var(--muted); margin-top:8px; }}
          footer {{ margin-top:26px; color:var(--muted); font-size:.95rem; }}
          .sr-only {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
          @media (max-width:900px) {{ .app-header {{ grid-template-columns:1fr; }} .app-health-chips {{ justify-content:flex-start; }} .control-strip,.coberturas-grid {{ grid-template-columns:1fr; }} .thinking-now {{ border-left:0; padding-left:0; border-top:1px solid var(--line); padding-top:10px; }} .operator-next {{ grid-template-columns:minmax(0,1fr); }} .top-quick-actions form {{ width:100%; }} .top-quick-actions span {{ flex:1 1 150px; min-width:0; }} }}
          @media (max-width:820px) {{ main {{ padding:10px 8px 44px; }} h1 {{ font-size:2.35rem; }} .app-header {{ padding:12px; }} .header-actions {{ flex-wrap:wrap; }} .header-actions form:first-child {{ flex:1 1 100%; }} .header-actions form:first-child button {{ width:100%; }} .header-more > div {{ left:auto; right:0; }} .command-head {{ grid-template-columns:1fr; padding:16px; }} .opening-status {{ border-left:0; border-top:1px solid var(--line); padding:12px 0 0; }} .command-facts,.position-overview {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .command-facts > div:nth-child(2),.position-overview > div:nth-child(2) {{ border-right:0; }} .command-facts > div:nth-child(-n+2),.position-overview > div:nth-child(-n+2) {{ border-bottom:1px solid var(--line); }} .pending-queue {{ padding:14px; }} .queue-head {{ display:block; }} .queue-head span {{ display:block; margin-top:4px; }} .operator-task {{ grid-template-columns:28px minmax(0,1fr); }} .operator-task > b {{ grid-column:2; }} .rsp-status-line {{ display:block; }} .rsp-status-line span {{ display:block; text-align:left; margin-top:5px; }} .position-detail-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .hero-panel {{ grid-template-columns:1fr; }} .context-grid {{ grid-template-columns:1fr; }} .control-facts {{ grid-template-columns:1fr; }} .alert-checklist {{ grid-template-columns:1fr; }} .scenario-grid {{ grid-template-columns:1fr; }} .card {{ align-items:flex-start; flex-direction:column; }} .actions {{ justify-content:flex-start; }} .operator-nav {{ top:4px; margin-bottom:10px; gap:2px; }} .operator-nav a {{ padding:8px; }} .operator-workspace > summary {{ align-items:flex-start; padding:14px; }} .workspace-body {{ padding:0 10px 10px; }} }}
          @media (max-width:620px) {{ .section-head {{ display:block; }} .section-head p {{ margin-top:5px; }} .alert-actions .fill-grid {{ grid-template-columns:1fr; }} .position-recommendation {{ padding:9px; border-left-width:4px; }} .position-recommendation > div,.position-structure-title,.position-alternative > div {{ display:grid; grid-template-columns:minmax(0,1fr); gap:3px; }} .position-structure {{ padding:8px; }} .position-structure-grid,.position-profile-grid {{ grid-template-columns:minmax(0,1fr); }} .position-structure-leg {{ padding:8px; }} .position-comparison th,.position-comparison td {{ padding:5px; }} }}
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
          <h1 class="sr-only">Stock Ultimus Console</h1>
          {health}
          <nav class="operator-nav" aria-label="Navegación principal de la consola">
            <a href="#hoy">Inicio</a>
            <a href="#pendientes">Pendientes</a>
            <a href="#riesgo">Riesgo</a>
            <a href="#posiciones">Posiciones</a>
            <a href="#coberturas-rsp">RSP</a>
            <a href="#analisis">Análisis</a>
            <a href="#herramientas">Administración</a>
            <a href="/guide">Ayuda</a>
          </nav>
          {active_process}
          {command_center}
          {message}
          {job_panel}
          <details id="alertas" class="panel operator-workspace secondary-workspace"{alert_open}>
            <summary><span>Alertas y diagnósticos<small>Señales operables, futuros intradía y eventos descartados por baja calidad.</small></span></summary>
            <div class="workspace-body">{alerts}</div>
          </details>
          <div id="riesgo">{portfolio_risk}</div>
          <div id="posiciones">{active_positions}</div>
          {coberturas}

          <details id="analisis" class="panel operator-workspace">
            <summary><span>Análisis<small>Cartera avanzada, escenarios, resultados y aprendizaje.</small></span></summary>
            <div class="workspace-body">
              <details id="cartera" class="operator-subsection">
                <summary>Cartera, riesgo y escenarios avanzados</summary>
                {control_tower}
                {portfolio_stress}
                {portfolio_factors}
                {portfolio_rebalance}
                {portfolio_whatif}
                {portfolio_operations}
              </details>
              <details id="resultados" class="operator-subsection">
                <summary>Resultados, reportes y aprendizaje</summary>
                {decision_outcomes}
                {alert_effectiveness}
                {executive_report}
                {v31_learning}
              </details>
            </div>
          </details>

          <details id="herramientas" class="panel operator-workspace">
            <summary><span>Administración<small>Cuentas, conexión, publicación, mantenimiento y diagnóstico técnico.</small></span></summary>
            <div class="workspace-body">
              {v31_console_support}
              {question_support}
              {admin_support}
              {context}
              {notifications}
              {preventive_maintenance}
              <details class="panel support-details">
                <summary>Ver diagnostico tecnico y salud de modulos</summary>
                {modules}
                {market_mode}
                {timeline}
                {diagnostic}
              </details>
              <details class="panel support-details">
                <summary>Administrar cuentas y perfiles</summary>
                <section>
                  <div class="section-head">
                    <h2>Cuentas</h2>
                    <p>Escoge la cuenta que quieres revisar. <strong>Usar cuenta</strong> publica contexto para GPT; <strong>Refresh IBKR</strong> solo trae datos frescos del broker.</p>
                  </div>
                </section>
                <section class="grid">{profile_cards}</section>
                <section>
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
              </details>
              {output}
            </div>
          </details>
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
                const fillPriceInput = form.querySelector('input[name="ibkr_fill_price"]');
                const fillQuantityInput = form.querySelector('input[name="ibkr_fill_quantity"]');
                const reasonRequired = ["REJECT_SETUP", "APPROVE_MANUAL_REVIEW", "JOURNAL_NOTE", "MARK_IBKR_APPLIED", "MARK_IBKR_NOT_APPLIED", "MARK_MISSED"].includes(actionValue);
                if (reasonRequired && reasonInput && !reasonInput.value.trim()) {{
                  event.preventDefault();
                  reasonInput.setCustomValidity("Esta accion requiere nota/razon.");
                  reasonInput.reportValidity();
                  setTimeout(() => reasonInput.setCustomValidity(""), 1200);
                  return;
                }}
                if (actionValue === "MARK_IBKR_APPLIED" && fillPriceInput && fillQuantityInput && (!fillPriceInput.value.trim() || !fillQuantityInput.value.trim())) {{
                  event.preventDefault();
                  const target = !fillPriceInput.value.trim() ? fillPriceInput : fillQuantityInput;
                  target.setCustomValidity("IBKR aplicada requiere fill y cantidad para medir performance real.");
                  target.reportValidity();
                  setTimeout(() => target.setCustomValidity(""), 1600);
                  return;
                }}
                if (actionValue && !form.querySelector('input[name="action"][type="hidden"]')) {{
                  const hiddenAction = document.createElement("input");
                  hiddenAction.type = "hidden";
                  hiddenAction.name = "action";
                  hiddenAction.value = actionValue;
                  form.appendChild(hiddenAction);
                }}
                const manualStatus = submitter && submitter.name === "status" ? submitter.value : "";
                const manualReason = submitter && submitter.dataset ? submitter.dataset.reason : "";
                if (manualStatus && manualReason) {{
                  const reason = form.querySelector('input[name="reason"]');
                  if (reason) reason.value = manualReason;
                }}
                const label = form.dataset.busy || "Procesando accion local";
                const backgroundSubmit = form.dataset.backgroundSubmit === "true";
                title.textContent = label;
                detail.textContent = form.dataset.busyDetail || "Solicitud enviada. Veras confirmacion o un panel RUNNING/DONE en unos segundos.";
                overlay.hidden = false;
                const buttons = Array.from(form.querySelectorAll("button"));
                buttons.forEach((button) => {{
                  button.dataset.originalText = button.dataset.originalText || button.textContent;
                  button.disabled = true;
                  button.textContent = "Trabajando...";
                }});
                if (backgroundSubmit) {{
                  event.preventDefault();
                  const statusTarget = form.dataset.statusTarget ? document.getElementById(form.dataset.statusTarget) : null;
                  if (statusTarget) statusTarget.textContent = "Refresh RSP solicitado. Esperando confirmacion local...";
                  fetch(form.action, {{
                    method: (form.method || "post").toUpperCase(),
                    body: new FormData(form),
                    headers: {{ "Accept": "application/json" }}
                  }})
                    .then((response) => response.json())
                    .then((payload) => {{
                      const job = payload.job_id ? " Job: " + payload.job_id : "";
                      const message = payload.message || (payload.ok ? "Refresh RSP iniciado." : "No pude iniciar Refresh RSP.");
                      title.textContent = payload.already_running ? "Refresh RSP ya esta corriendo" : "Refresh RSP iniciado";
                      detail.textContent = message + job;
                      if (statusTarget) statusTarget.textContent = message + job;
                    }})
                    .catch((error) => {{
                      title.textContent = "Refresh RSP no confirmado";
                      detail.textContent = String(error || "Error local");
                      if (statusTarget) statusTarget.textContent = "No pude confirmar el refresh RSP. Revisa la consola.";
                    }})
                    .finally(() => {{
                      buttons.forEach((button) => {{
                        button.disabled = false;
                        button.textContent = button.dataset.originalText || "Enviar";
                      }});
                      setTimeout(() => {{ overlay.hidden = true; }}, 1200);
                    }});
                }}
              }});
            }});
          }})();
        </script>
      </body>
    </html>
    """.format(
        context=render_console_context(active, snapshot, operator_payload),
        health=render_console_health(active, snapshot, operator_payload, reports),
        active_process=render_active_process_panel(),
        today=render_today_panel(active, snapshot, operator_payload, reports),
        command_center=render_command_center(active, snapshot, operator_payload, reports, position_payload, risk_payload, rsp_payload),
        modules=render_module_health(active, snapshot, operator_payload, reports),
        market_mode=render_market_mode_panel(operator_payload, reports),
        timeline=render_timeline(snapshot, operator_payload, reports),
        control_tower=render_control_tower_panel(profiles, active),
        portfolio_risk=render_portfolio_risk_panel(profiles, active, risk_payload),
        portfolio_stress=render_portfolio_stress_panel(profiles, active),
        portfolio_factors=render_portfolio_factor_panel(profiles, active),
        portfolio_rebalance=render_portfolio_rebalance_panel(profiles, active),
        portfolio_whatif=render_portfolio_whatif_panel(profiles, active),
        portfolio_operations=render_portfolio_operations_panel(),
        decision_outcomes=render_decision_outcome_panel(),
        alert_effectiveness=render_alert_effectiveness_panel(),
        executive_report=render_executive_report_panel(),
        preventive_maintenance=render_preventive_maintenance_panel(),
        diagnostic=render_diagnostic_panel(active, reports),
        message=('<div class="notice">' + html_escape(message) + "</div>") if message else "",
        refresh_meta=refresh_meta,
        job_panel=job_panel,
        profile_cards=render_profile_cards(profiles, active),
        alerts=render_operator_alerts(operator_payload, snapshot, reports),
        alert_open=" open" if any(alert_operator_visibility(alert) in {"HIGH_PROBABILITY", "RADAR"} and not is_handled_alert(alert) for alert in ((operator_payload.get("data") or {}).get("active_alerts") or []) if isinstance(alert, dict)) else "",
        active_positions=render_active_positions_panel(snapshot, v31_payloads, active, position_payload),
        v31_learning=render_v31_learning_panel(v31_payloads),
        coberturas=coberturas,
        v31_console_support=v31_console_support,
        question_support=question_support,
        admin_support=admin_support,
        notifications=render_notification_test_panel(),
        output=output,
    )
    return body.encode("utf-8")


class AccountProfileWebHandler(BaseHTTPRequestHandler):
    server_version = "StockUltimusIBKRProfile/1.0"

    def send_html(
        self,
        message: str = "",
        result: dict[str, Any] | None = None,
        status: int = 200,
        job_id: str = "",
        question_answer: str = "",
    ) -> None:
        if job_id and "application/json" in str(self.headers.get("Accept") or ""):
            self.send_json({
                "ok": status < 400,
                "status": "ACCEPTED" if status < 400 else "ERROR",
                "message": message,
                "job_id": job_id,
                "execution_authorized": False,
                "not_order_instruction": True,
            }, status=status)
            return
        payload = render_web_page(message=message, result=result, job_id=job_id, question_answer=question_answer)
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
        if path == "/coberturas/rsp":
            self.send_json(shared_coberturas_engine.build_recommendation(RUNTIME))
            return
        if path == "/active-positions":
            snapshot = latest_master_snapshot()
            v31_payloads = console_v31_payloads(prefer_cache=True)
            self.send_json(console_active_position_management(snapshot, v31_payloads))
            return
        if path == "/coberturas":
            payload = render_coberturas_rsp_page(message=(params.get("message") or [""])[0])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/guide":
            payload = render_operator_guide_page()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/control-tower":
            profile_data = load_profiles()
            profile_map = profile_data.get("profiles") if isinstance(profile_data.get("profiles"), dict) else {}
            self.send_json(load_control_tower(profile_map, active_profile()))
            return
        if path == "/portfolio-risk":
            profile_data = load_profiles()
            profile_map = profile_data.get("profiles") if isinstance(profile_data.get("profiles"), dict) else {}
            self.send_json(load_portfolio_risk(profile_map, active_profile()))
            return
        if path == "/portfolio-stress":
            profile_data = load_profiles()
            profile_map = profile_data.get("profiles") if isinstance(profile_data.get("profiles"), dict) else {}
            self.send_json(load_portfolio_stress(profile_map, active_profile()))
            return
        if path == "/portfolio-factors":
            profile_data = load_profiles()
            profile_map = profile_data.get("profiles") if isinstance(profile_data.get("profiles"), dict) else {}
            self.send_json(load_portfolio_factors(profile_map, active_profile()))
            return
        if path == "/portfolio-rebalance":
            profile_data = load_profiles()
            profile_map = profile_data.get("profiles") if isinstance(profile_data.get("profiles"), dict) else {}
            self.send_json(load_portfolio_rebalance(profile_map, active_profile()))
            return
        if path == "/portfolio-rebalance-whatif":
            self.send_json(load_portfolio_whatif())
            return
        if path == "/decision-outcomes":
            self.send_json(load_decision_outcome_intelligence())
            return
        if path == "/alert-effectiveness":
            self.send_json(load_alert_effectiveness())
            return
        if path == "/executive-report":
            self.send_json(load_executive_reports())
            return
        if path == "/preventive-maintenance":
            self.send_json(load_preventive_maintenance())
            return
        if path == "/portfolio-risk-outbox":
            self.send_json(shared_risk_operations.load_json(PORTFOLIO_RISK_OUTBOX_PATH))
            return
        if path == "/portfolio-risk-operations":
            self.send_json(shared_risk_operations.load_json(PORTFOLIO_RISK_OPERATIONS_STATUS_PATH))
            return
        if path not in ["/", "", "/console"]:
            self.send_html("Ruta no encontrada.", status=404)
            return
        self.send_html(job_id=(params.get("job_id") or [""])[0])

    def do_HEAD(self) -> None:
        path = self.path.split("?", 1)[0]
        json_paths = {
            "/coberturas/rsp",
            "/active-positions",
            "/control-tower",
            "/portfolio-risk",
            "/portfolio-stress",
            "/portfolio-factors",
            "/portfolio-rebalance",
            "/portfolio-rebalance-whatif",
            "/decision-outcomes",
            "/alert-effectiveness",
            "/executive-report",
            "/preventive-maintenance",
            "/portfolio-risk-outbox",
            "/portfolio-risk-operations",
        }
        status = 200 if path in ["/", "", "/console", "/coberturas", "/guide", *json_paths] else 404
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8" if path in json_paths else "text/html; charset=utf-8")
        self.end_headers()

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
            raw_body = self.rfile.read(length)
            params = parse_qs(raw_body.decode("utf-8"))
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
            elif self.path == "/select-refresh":
                args = argparse.Namespace(alias=alias)
                cmd_select(args)
                job_id = start_web_job(alias, account_publish_command(), "Alinear/Publicar rapido")
                self.send_html(
                    "Alineacion rapida iniciada: alias={alias}. Publica contexto para GPT sin escaneo profundo de IBKR/opciones.".format(
                        alias=normalize_alias(alias)
                    ),
                    job_id=job_id,
                )
            elif self.path == "/refresh-all":
                active = active_profile()
                selected_alias = alias or active.get("account_alias") or ""
                if not selected_alias:
                    self.send_html("Selecciona una cuenta antes de correr Alinear/Publicar rapido.", status=400)
                    return
                cmd_select(argparse.Namespace(alias=selected_alias))
                job_id = start_web_job(selected_alias, account_publish_command(), "Alinear/Publicar rapido")
                self.send_html(
                    "Alinear/Publicar rapido iniciado: cuenta + contexto GPT. No escanea opciones ni autoriza ordenes.",
                    job_id=job_id,
                )
            elif self.path == "/account-capacity":
                job_id = start_web_job(alias, account_capacity_command(), "Refresh capacidad IBKR")
                self.send_html("Refresh de cuenta iniciado. Lee AccountSummary y publica capital/margen disponible.", job_id=job_id)
            elif self.path == "/ibkr-quick-check":
                job_id = start_web_job(alias, ibkr_quick_check_command(), "Validar IBKR rapido")
                self.send_html("Validacion rapida IBKR iniciada. Lee TWS/API y AccountSummary; no escanea opciones.", job_id=job_id)
            elif self.path == "/control-tower-refresh":
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                job_id = start_web_job(selected_alias, control_tower_refresh_command(), "Control Tower multi-cuenta")
                self.send_html(
                    "Refresco multi-cuenta iniciado. Lee todas las cuentas configuradas de forma secuencial y sanitizada; no autoriza ordenes.",
                    job_id=job_id,
                )
            elif self.path == "/portfolio-risk-refresh":
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                job_id = start_web_job(selected_alias, portfolio_risk_refresh_command(), "Reevaluar riesgo de cartera")
                self.send_html(
                    "Evaluación de riesgo iniciada sobre los snapshots sanitizados. No transmite ni ejecuta órdenes.",
                    job_id=job_id,
                )
            elif self.path == "/portfolio-stress-refresh":
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                job_id = start_web_job(selected_alias, portfolio_stress_refresh_command(), "Estrés multicuenta")
                self.send_html(
                    "Cálculo de estrés iniciado sobre snapshots sanitizados. No transmite ni ejecuta órdenes.",
                    job_id=job_id,
                )
            elif self.path == "/portfolio-factor-refresh":
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                job_id = start_web_job(selected_alias, portfolio_factor_refresh_command(), "Inteligencia avanzada de cartera")
                self.send_html(
                    "Análisis avanzado iniciado sobre datos sanitizados. No transmite ni ejecuta órdenes.",
                    job_id=job_id,
                )
            elif self.path == "/portfolio-rebalance-simulate":
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                ticker = str((params.get("ticker") or [""])[0]).upper().strip()
                reduction_pct = str((params.get("reduction_pct") or [""])[0]).strip()
                job_id = start_web_job(
                    selected_alias,
                    portfolio_rebalance_refresh_command(ticker, reduction_pct),
                    "Simulación virtual de rebalanceo",
                )
                self.send_html(
                    "Simulación iniciada sobre una copia matemática. No se creó ni transmitió ninguna orden.",
                    job_id=job_id,
                )
            elif self.path == "/portfolio-rebalance-whatif":
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                candidate_id = str((params.get("candidate_id") or [""])[0]).strip()
                job_id = start_web_job(
                    selected_alias,
                    portfolio_whatif_refresh_command(candidate_id),
                    "Validación oficial IBKR what-if",
                )
                self.send_html(
                    "Validación what-if iniciada. IBKR procesa el preview con whatIf=true; no se crea una orden real.",
                    job_id=job_id,
                )
            elif self.path == "/portfolio-risk-operations-run":
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                job_id = start_web_job(selected_alias, portfolio_risk_operations_command(), "Mantenimiento de riesgo")
                self.send_html(
                    "Mantenimiento iniciado: reevaluación, outbox y digest locales; no consulta ni opera el broker.",
                    job_id=job_id,
                )
            elif self.path in {"/portfolio-risk-monitor", "/portfolio-risk-preflight", "/portfolio-risk-digest"}:
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                mode = {
                    "/portfolio-risk-monitor": "monitor",
                    "/portfolio-risk-preflight": "preflight",
                    "/portfolio-risk-digest": "digest",
                }[self.path]
                local_notify = (params.get("local_notify") or ["0"])[0] == "1"
                job_id = start_web_job(
                    selected_alias,
                    portfolio_risk_operations_command(
                        mode,
                        refresh_broker=mode == "monitor",
                        local_notify=local_notify and mode == "monitor",
                    ),
                    f"Riesgo de cartera: {mode}",
                )
                self.send_html(
                    f"Ciclo {mode} iniciado mediante el puente local; sin ejecución de órdenes.",
                    job_id=job_id,
                )
            elif self.path == "/portfolio-risk-action":
                profile_data = load_profiles()
                profile_map = profile_data.get("profiles") if isinstance(profile_data.get("profiles"), dict) else {}
                current_risk = load_portfolio_risk(profile_map, active_profile())
                active_alerts_by_id = {
                    str(item.get("alert_id") or ""): item
                    for item in (current_risk.get("alerts") or [])
                    if isinstance(item, dict) and item.get("alert_id")
                }
                known_alert_ids = {
                    alert_id for alert_id in active_alerts_by_id
                }
                requested_alert_id = (params.get("alert_id") or [""])[0]
                item = shared_risk_operations.record_action(
                    PORTFOLIO_RISK_ACTIONS_PATH,
                    alert_id=requested_alert_id,
                    action=(params.get("action") or [""])[0],
                    reason=(params.get("reason") or [""])[0],
                    snooze_minutes=60,
                    acknowledgement_minutes=240,
                    alert_severity=(active_alerts_by_id.get(requested_alert_id) or {}).get("severity") or "",
                    known_alert_ids=known_alert_ids,
                )
                self.send_html(
                    "Alerta de riesgo actualizada: {status}. Esta acción no modifica posiciones ni órdenes.".format(
                        status=item.get("status") or "UNKNOWN"
                    )
                )
            elif self.path == "/bridge":
                job_id = start_web_job(alias, console_bridge_command(), "Refresh profundo IBKR/opciones")
                self.send_html("Refresh IBKR iniciado en modo profundo/opciones. Usalo solo si necesitas contratos/opciones frescas.", job_id=job_id)
            elif self.path == "/bridge-deep":
                job_id = start_web_job(alias, console_deep_bridge_command(), "Refresh profundo IBKR/opciones")
                self.send_html("Refresh profundo iniciado. Mayor timeout para contratos/opciones; usalo solo cuando TWS este estable.", job_id=job_id)
            elif self.path == "/coberturas/rsp/refresh":
                wants_json = "application/json" in (self.headers.get("Accept") or "")
                selected_alias = CONSOLE_COBERTURAS_RSP_ACCOUNT_ALIAS
                if not selected_alias:
                    message = "Selecciona una cuenta antes de correr Refresh RSP semanal IBKR."
                    if wants_json:
                        self.send_json({"ok": False, "status": "MISSING_ACCOUNT", "message": message}, status=400)
                    else:
                        self.send_html(message, status=400)
                    return
                existing_job = running_web_job_by_label("Refresh RSP semanal IBKR")
                if existing_job:
                    message = "Ya hay un Refresh RSP semanal corriendo. No lance otro proceso."
                    if wants_json:
                        self.send_json({
                            "ok": True,
                            "already_running": True,
                            "status": "RUNNING",
                            "message": message,
                            "job_id": existing_job.get("job_id"),
                        })
                    else:
                        page = render_coberturas_rsp_page("{} Job: {}".format(message, existing_job.get("job_id")))
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(page)))
                        self.end_headers()
                        self.wfile.write(page)
                    return
                job_id = start_web_job(selected_alias, console_rsp_weekly_bridge_command(), "Refresh RSP semanal IBKR")
                message = "Refresh RSP semanal iniciado. Solo consulta RSP, busca vencimientos 7-14 DTE y no autoriza ordenes."
                if wants_json:
                    self.send_json({"ok": True, "status": "RUNNING", "message": message, "job_id": job_id})
                    return
                page = render_coberturas_rsp_page("{} Job: {}".format(message, job_id))
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/daily-open":
                job_id = start_web_job(alias, daily_open_command(), "Daily open checklist")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "Daily open iniciado.", "job_id": job_id})
                    return
                self.send_html("Daily open iniciado. La consola mostrara RUNNING hasta que termine.", job_id=job_id)
            elif self.path == "/daily-outcome-evaluation":
                existing_job = running_web_job_by_label("Seguimiento automático de resultados")
                if existing_job:
                    self.send_html(
                        "El seguimiento de resultados ya está corriendo.",
                        job_id=existing_job.get("job_id"),
                    )
                    return
                selected_alias = normalize_alias(alias or active_profile().get("account_alias") or "")
                job_id = start_web_job(
                    selected_alias,
                    daily_outcome_evaluation_command(),
                    "Seguimiento automático de resultados",
                )
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({
                        "ok": True,
                        "status": "RUNNING",
                        "message": "Seguimiento automático iniciado.",
                        "job_id": job_id,
                        "execution_authorized": False,
                        "not_order_instruction": True,
                    })
                    return
                self.send_html(
                    "Seguimiento iniciado: evalúa checkpoints y sincroniza resultados sin tocar IBKR.",
                    job_id=job_id,
                )
            elif self.path in {"/executive-report-daily", "/executive-report-weekly"}:
                period = "weekly" if self.path.endswith("weekly") else "daily"
                label = f"Reporte ejecutivo {period}"
                existing_job = running_web_job_by_label(label)
                if existing_job:
                    self.send_html("El reporte ejecutivo ya se está generando.", job_id=existing_job.get("job_id"))
                    return
                job_id = start_web_job(
                    normalize_alias(alias or active_profile().get("account_alias") or ""),
                    executive_report_command(period),
                    label,
                )
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({
                        "ok": True, "status": "RUNNING", "job_id": job_id,
                        "message": f"Reporte ejecutivo {period} iniciado.",
                        "execution_authorized": False, "not_order_instruction": True,
                    })
                    return
                self.send_html(f"Reporte ejecutivo {period} iniciado.", job_id=job_id)
            elif self.path == "/preventive-maintenance":
                existing_job = running_web_job_by_label("Mantenimiento preventivo")
                if existing_job:
                    self.send_html("El mantenimiento preventivo ya está corriendo.", job_id=existing_job.get("job_id"))
                    return
                job_id = start_web_job(
                    normalize_alias(alias or active_profile().get("account_alias") or ""),
                    preventive_maintenance_command(),
                    "Mantenimiento preventivo",
                )
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({
                        "ok": True, "status": "RUNNING", "job_id": job_id,
                        "message": "Mantenimiento preventivo iniciado.",
                        "automatic_deletion_authorized": False,
                        "automatic_restart_authorized": False,
                        "execution_authorized": False, "not_order_instruction": True,
                    })
                    return
                self.send_html("Mantenimiento preventivo iniciado sin borrar ni reiniciar.", job_id=job_id)
            elif self.path == "/diagnostic":
                job_id = start_web_job(alias, console_diagnostic_command(), "Diagnostico completo")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "Diagnostico completo iniciado.", "job_id": job_id})
                    return
                self.send_html("Diagnostico completo iniciado. Revisa RUNNING/DONE en esta misma consola.", job_id=job_id)
            elif self.path == "/market-open-readiness":
                job_id = start_web_job(alias, market_open_readiness_command(), "Market open readiness")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "Market open readiness iniciado.", "job_id": job_id})
                    return
                self.send_html("Market open readiness iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/post-open-monitor":
                existing_job = running_web_job_by_label("Post-open monitor")
                if existing_job:
                    if "application/json" in (self.headers.get("Accept") or ""):
                        self.send_json({"ok": True, "already_running": True, "status": "RUNNING", "message": "Post-open monitor ya esta corriendo.", "job_id": existing_job.get("job_id")})
                        return
                    self.send_html("Post-open monitor ya esta corriendo.", job_id=existing_job.get("job_id"))
                    return
                job_id = start_web_job(alias, post_open_monitor_command(), "Post-open monitor")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "Post-open monitor iniciado.", "job_id": job_id})
                    return
                self.send_html("Post-open monitor iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/environment-alerts":
                job_id = start_web_job(alias, environment_alerts_command(), "Environment alerts")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "Environment alerts iniciado.", "job_id": job_id})
                    return
                self.send_html("Environment alerts iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/security-audit":
                job_id = start_web_job(alias, security_audit_command(), "Security audit")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "Security audit iniciado.", "job_id": job_id})
                    return
                self.send_html("Security audit iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/dependency-audit":
                job_id = start_web_job(alias, dependency_audit_command(), "Dependency audit")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "Dependency audit iniciado.", "job_id": job_id})
                    return
                self.send_html("Dependency audit iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/local-dashboard-refresh":
                job_id = start_web_job(alias, local_dashboard_command(), "Dashboard local")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "Dashboard local iniciado.", "job_id": job_id})
                    return
                self.send_html("Dashboard local iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/v32-pushover-monitor":
                job_id = start_web_job(alias, v32_pushover_automation_command("monitor"), "V32 Pushover monitor")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "V32 Pushover monitor iniciado.", "job_id": job_id})
                    return
                self.send_html("V32 Pushover monitor iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/v32-pushover-postclose":
                job_id = start_web_job(alias, v32_pushover_automation_command("post-close"), "V32 Pushover post-close")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "V32 Pushover post-close iniciado.", "job_id": job_id})
                    return
                self.send_html("V32 Pushover post-close iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/v32-pushover-preflight":
                job_id = start_web_job(alias, v32_pushover_automation_command("preflight"), "V32 Pushover preflight")
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json({"ok": True, "status": "RUNNING", "message": "V32 Pushover preflight iniciado.", "job_id": job_id})
                    return
                self.send_html("V32 Pushover preflight iniciado desde launchd/console.", job_id=job_id)
            elif self.path == "/coberturas/rsp/manual_context":
                payload = {key: (values[0] if values else "") for key, values in params.items()}
                shared_coberturas_engine.write_manual_context(payload)
                if payload.get("return_to") == "console":
                    self.send_html("Lectura RSP guardada. Coberturas se actualizo en esta consola principal.")
                    return
                page = render_coberturas_rsp_page("Contexto RSP guardado en la consola local.")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/coberturas/rsp/journal":
                payload = {key: (values[0] if values else "") for key, values in params.items()}
                result = shared_coberturas_engine.record_journal_entry(payload)
                if "application/json" in (self.headers.get("Accept") or ""):
                    self.send_json(result)
                    return
                page = render_coberturas_rsp_page("Bitacora RSP actualizada.")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/refresh-remote":
                result = fetch_remote_json(
                    "/gpt_v32_operator_today?limit=12",
                    timeout=REMOTE_VERIFY_TIMEOUT_SECONDS,
                    prefer_cache=False,
                )
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                if result.get("ok"):
                    comparison = selected_vs_published(active_profile(), latest_master_snapshot(), result)
                    self.send_html(operator_state_message(data, comparison.get("display_alias") or ""))
                else:
                    self.send_html(
                        "No pude actualizar estado remoto: {}".format(result.get("error") or "unknown"),
                        status=400,
                    )
            elif self.path == "/notification-preview":
                email_preview = fetch_remote_json("/v32_operator_daily_summary_email/preview?force=true", timeout=REMOTE_VERIFY_TIMEOUT_SECONDS, prefer_cache=False)
                push_preview = fetch_remote_json("/v32_operator_pushover_notify/preview?force=true", timeout=REMOTE_VERIFY_TIMEOUT_SECONDS, prefer_cache=False)
                self.send_html("Preview de notificaciones consultado. No se envio nada.", result={
                    "command": "GET email/pushover preview",
                    "alias": active_profile().get("account_alias") or "",
                    "account_scope": active_profile().get("account_scope") or "",
                    "returncode": 0 if email_preview.get("ok") or push_preview.get("ok") else 1,
                    "stdout_tail": json.dumps({
                        "email_preview_ok": email_preview.get("ok"),
                        "email_status": (email_preview.get("data") or {}).get("status"),
                        "email_would_notify": (email_preview.get("data") or {}).get("would_notify"),
                        "push_preview_ok": push_preview.get("ok"),
                        "push_status": (push_preview.get("data") or {}).get("status"),
                        "push_would_notify": (push_preview.get("data") or {}).get("would_notify"),
                        "not_order_instruction": True,
                        "execution_authorized": False,
                    }, indent=2, sort_keys=True),
                })
            elif self.path == "/notification-test-email":
                result = post_remote_json("/v32_operator_daily_summary_email?force=true", {}, timeout=max(45, REMOTE_VERIFY_TIMEOUT_SECONDS))
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                self.send_html("Prueba email solicitada: status={}. Revisa bandeja/spam si email_sent=true.".format(data.get("status") or result.get("error") or "unknown"), result={
                    "command": "POST /v32_operator_daily_summary_email?force=true",
                    "alias": active_profile().get("account_alias") or "",
                    "account_scope": active_profile().get("account_scope") or "",
                    "returncode": 0 if result.get("ok") else 1,
                    "stdout_tail": json.dumps({
                        "ok": result.get("ok"),
                        "status": data.get("status"),
                        "email_sent": data.get("email_sent"),
                        "reason": data.get("reason"),
                        "not_order_instruction": True,
                        "execution_authorized": False,
                    }, indent=2, sort_keys=True),
                })
            elif self.path == "/notification-test-push":
                result = post_remote_json("/v32_operator_pushover_notify?force=true", {}, timeout=max(45, REMOTE_VERIFY_TIMEOUT_SECONDS))
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                self.send_html("Prueba push solicitada: status={}. Revisa movil si pushover_sent=true.".format(data.get("status") or result.get("error") or "unknown"), result={
                    "command": "POST /v32_operator_pushover_notify?force=true",
                    "alias": active_profile().get("account_alias") or "",
                    "account_scope": active_profile().get("account_scope") or "",
                    "returncode": 0 if result.get("ok") else 1,
                    "stdout_tail": json.dumps({
                        "ok": result.get("ok"),
                        "status": data.get("status"),
                        "pushover_sent": data.get("pushover_sent"),
                        "reason": data.get("reason"),
                        "not_order_instruction": True,
                        "execution_authorized": False,
                    }, indent=2, sort_keys=True),
                })
            elif self.path == "/ask":
                question = (params.get("question") or [""])[0].strip()
                payloads = console_v31_payloads(prefer_cache=False)
                answer = local_question_answer(question, payloads)
                self.send_html(
                    "Pregunta consultada contra el motor. Decision support solamente.",
                    question_answer=answer,
                )
            elif self.path == "/manual-review-event":
                status_value = (params.get("status") or ["REVIEWING"])[0]
                reason = (params.get("reason") or [""])[0].strip()
                if not reason:
                    reason = "Revision manual registrada desde consola local."
                form_payload = {
                    "ticker": (params.get("ticker") or [""])[0],
                    "status": status_value,
                    "reason": reason,
                }
                if status_value == "APPROVED_FOR_MANUAL_TRADE":
                    form_payload["manual_broker_validation_override"] = "true"
                    if "valid" not in reason.lower():
                        form_payload["reason"] = (
                            "Validé manualmente contrato, liquidez, spread, eventos, riesgo de cuenta y ticket en broker/TWS. "
                            "Ejecución será manual."
                        )
                result = post_remote_form("/v31_manual_review_inbox/record", form_payload)
                ticker_label = form_payload.get("ticker") or "UNKNOWN"
                message = (
                    "{ticker} registrado como {status}. Registro enviado a Render; no autoriza ordenes.".format(
                        ticker=ticker_label,
                        status=status_value,
                    )
                    if result.get("ok")
                    else "No pude registrar revision V31: {}".format(result.get("error") or result.get("text") or "unknown")
                )
                if result.get("ok"):
                    fetch_remote_json("/v31_manual_reviews?limit=250", timeout=REMOTE_VERIFY_TIMEOUT_SECONDS, prefer_cache=False)
                    fetch_remote_json("/gpt_v31_daily_rankings", timeout=REMOTE_VERIFY_TIMEOUT_SECONDS, prefer_cache=False)
                self.send_html(message, result={
                    "command": "POST /v31_manual_review_inbox/record",
                    "alias": active_profile().get("account_alias") or "",
                    "account_scope": active_profile().get("account_scope") or "",
                    "returncode": 0 if result.get("ok") else 1,
                    "stdout_tail": json.dumps({
                        "ok": result.get("ok"),
                        "status": status_value,
                        "ticker": ticker_label,
                        "final_url": result.get("final_url"),
                        "not_order_instruction": True,
                        "execution_authorized": False,
                    }, indent=2, sort_keys=True)[:6000],
                    "stderr_tail": "" if result.get("ok") else str(result.get("error") or result.get("text") or ""),
                }, status=200 if result.get("ok") else 400)
            elif self.path == "/position-management-event":
                operator_action = (params.get("operator_action") or [""])[0]
                ticker_label = (params.get("ticker") or [""])[0] or "UNKNOWN"
                try:
                    shared_position_management_journal.record_event(
                        {
                            "position_id": (params.get("position_id") or [""])[0],
                            "ticker": ticker_label,
                            "strategy": (params.get("strategy") or [""])[0],
                            "recommended_action": (params.get("recommended_action") or [""])[0],
                            "recommended_state": (params.get("recommended_state") or [""])[0],
                            "management_fingerprint": (params.get("management_fingerprint") or [""])[0],
                            "operator_action": operator_action,
                            "operator_reason": (params.get("operator_reason") or [""])[0],
                            "source": "stock_ultimus_console",
                        },
                        path=POSITION_MANAGEMENT_JOURNAL_PATH,
                    )
                    self.send_html("Gestion de posicion registrada: {} {}. No autoriza ordenes.".format(operator_action, ticker_label))
                except Exception as exc:
                    self.send_html("No pude registrar gestion de posicion: {}".format(str(exc)[:160]), status=400)
            elif self.path == "/position-context":
                ticker_label = (params.get("ticker") or [""])[0] or "UNKNOWN"
                try:
                    shared_position_context_store.upsert_context(
                        {
                            "position_id": (params.get("position_id") or [""])[0],
                            "ticker": ticker_label,
                            "strategy": (params.get("strategy") or [""])[0],
                            "thesis_text": (params.get("thesis_text") or [""])[0],
                            "invalidation_level": (params.get("invalidation_level") or [""])[0],
                            "target": (params.get("target") or [""])[0],
                            "entry_credit": (params.get("entry_credit") or [""])[0],
                            "entry_date": (params.get("entry_date") or [""])[0],
                            "roll_plan": (params.get("roll_plan") or [""])[0],
                            "source": "stock_ultimus_console",
                        },
                        path=POSITION_CONTEXTS_PATH,
                    )
                    self.send_html("Tesis/entrada guardada para {}. El motor la usara en la proxima lectura de posiciones.".format(ticker_label))
                except Exception as exc:
                    self.send_html("No pude guardar tesis de posicion: {}".format(str(exc)[:160]), status=400)
            elif self.path == "/gamma-context":
                ticker_label = (params.get("ticker") or [""])[0] or "UNKNOWN"
                try:
                    gamma_blob = (params.get("gamma_blob") or [""])[0]
                    parsed_context = shared_coberturas_engine.parse_gamma_blob(gamma_blob)
                    shared_gamma_context_store.upsert_context(
                        {
                            "ticker": ticker_label,
                            "spot": parsed_context.get("spot"),
                            "support_levels": parsed_context.get("support_levels") or [],
                            "resistance_levels": parsed_context.get("resistance_levels") or [],
                            "expected_move_low": parsed_context.get("expected_move_low"),
                            "expected_move_high": parsed_context.get("expected_move_high"),
                            "gamma_bias": parsed_context.get("gamma_bias"),
                            "gamma_wall": (params.get("gamma_wall") or [""])[0] or parsed_context.get("gamma_wall"),
                            "call_wall": (params.get("call_wall") or [""])[0] or parsed_context.get("call_wall"),
                            "put_wall": (params.get("put_wall") or [""])[0] or parsed_context.get("put_wall"),
                            "zero_gamma": (params.get("zero_gamma") or [""])[0] or parsed_context.get("zero_gamma"),
                            "notes": (params.get("notes") or [""])[0],
                            "source": "stock_ultimus_console_json_or_manual",
                        },
                        path=GAMMA_CONTEXTS_PATH,
                    )
                    self.send_html("Contexto complementario guardado para {}. Se aplicara en el siguiente calculo.".format(ticker_label))
                except Exception as exc:
                    self.send_html("No pude guardar gamma manual: {}".format(str(exc)[:160]), status=400)
            elif self.path == "/operator-event":
                action = (params.get("action") or [""])[0]
                reason = (params.get("reason") or [""])[0].strip()
                ibkr_fill_price = (params.get("ibkr_fill_price") or [""])[0].strip()
                ibkr_fill_quantity = (params.get("ibkr_fill_quantity") or [""])[0].strip()
                if action in {"REJECT_SETUP", "APPROVE_MANUAL_REVIEW", "JOURNAL_NOTE", "MARK_IBKR_APPLIED", "MARK_IBKR_NOT_APPLIED", "MARK_MISSED"} and not reason:
                    self.send_html("Esta accion requiere nota/razon antes de registrarla.", status=400)
                    return
                if action == "MARK_IBKR_APPLIED" and (not ibkr_fill_price or not ibkr_fill_quantity):
                    self.send_html("IBKR aplicada requiere fill y cantidad para medir performance real.", status=400)
                    return
                payload = {
                    "action": action,
                    "alert_id": (params.get("alert_id") or [""])[0],
                    "ticker": (params.get("ticker") or [""])[0],
                    "strategy": (params.get("strategy") or [""])[0],
                    "state": (params.get("state") or [""])[0],
                    "reason": reason,
                    "ibkr_fill_price": ibkr_fill_price,
                    "ibkr_fill_quantity": ibkr_fill_quantity,
                    "ibkr_order_id": (params.get("ibkr_order_id") or [""])[0].strip(),
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
        except (Exception, SystemExit) as exc:
            sys.stderr.write(f"ibkr-profile-web POST ERROR {self.path}: {exc}\n")
            sys.stderr.flush()
            if "application/json" in (self.headers.get("Accept") or ""):
                self.send_json({"ok": False, "status": "ERROR", "message": str(exc)}, status=400)
                return
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
    refresh_capacity.add_argument("--json-out", default=str(ACCOUNT_CAPACITY_PATH))
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
