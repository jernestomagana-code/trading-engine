#!/usr/bin/env python3
"""Run the Stock Ultimus daily open checklist.

This helper answers the operator question "what is missing before I can review
today?" It can optionally refresh IBKR and publish the local runtime snapshot,
then reads the V32 GPT operator endpoint and writes a redacted report.

It never places orders, never authorizes execution, and never prints tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import foundation_health
import operational_evidence_gate
import coberturas_engine

RUNTIME = ROOT / "runtime"
DEFAULT_BASE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_OUT = RUNTIME / "daily_open_checklist_latest.json"
INGEST_KEYCHAIN_SERVICE = "stock-ultimus-snapshot-ingest"
READ_KEYCHAIN_SERVICE = "stock-ultimus-read-access-token"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Stock Ultimus daily open checklist.")
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--ibkr-host", default=os.getenv("IBKR_HOST", "127.0.0.1"))
    parser.add_argument("--ibkr-port", type=int, default=int(os.getenv("IBKR_PORT", "7496")))
    parser.add_argument("--read-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "30")))
    parser.add_argument("--bridge-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_BRIDGE_TIMEOUT", "180")))
    parser.add_argument("--rsp-bridge-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_RSP_BRIDGE_TIMEOUT", "90")))
    parser.add_argument("--capacity-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_CAPACITY_TIMEOUT", "20")))
    parser.add_argument("--control-tower-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_CONTROL_TOWER_TIMEOUT", "90")))
    parser.add_argument("--rsp-account-alias", default=os.getenv("STOCK_ULTIMUS_RSP_ACCOUNT_ALIAS", "retiro"))
    parser.add_argument("--limit", type=int, default=int(os.getenv("STOCK_ULTIMUS_OPERATOR_ALERT_LIMIT", "10")))
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_DAILY_OPEN_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--refresh", action="store_true", help="Run ibkr_bridge.py --once before reading V32.")
    parser.add_argument("--skip-canslim", action="store_true", help="Skip the free CANSLIM candidate builder before refresh.")
    parser.add_argument("--refresh-sec-canslim", action="store_true", help="Refresh SEC companyfacts cache during CANSLIM build.")
    parser.add_argument("--canslim-timeout", type=int, default=int(os.getenv("CANSLIM_BUILDER_TIMEOUT", "120")))
    parser.add_argument("--publish", action="store_true", help="Publish runtime snapshot after refresh/check.")
    parser.add_argument("--allow-stale-publish", action="store_true", help="Pass --allow-stale to the publisher.")
    parser.add_argument("--full-bridge", action="store_true", help="Do not enable DAILY_RADAR_FAST for the bridge.")
    parser.add_argument("--skip-rsp-refresh", action="store_true", help="Skip the dedicated RSP 7-14 DTE refresh during this opening.")
    parser.add_argument("--no-keychain", action="store_true", help="Use env vars only; do not read macOS Keychain.")
    parser.add_argument("--soft-exit", action="store_true", help="Exit 0 when the checklist report is generated, even if action is required.")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def active_position_option_symbols(runtime_dir: Path = RUNTIME) -> list[str]:
    symbols = []
    seen = set()
    for filename in [
        "broker_control_tower_latest.json",
        "v28_master_snapshot.json",
        "decision_desk_snapshot.json",
        "v26_local_master_snapshot.json",
    ]:
        path = runtime_dir / filename
        try:
            payload = json.loads(path.read_text()) if path.exists() else {}
        except Exception:
            payload = {}

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                ticker = str(value.get("ticker") or value.get("symbol") or "").strip().upper()
                sec_type = str(value.get("sec_type") or value.get("security_type") or "").strip().upper()
                quantity = value.get("position_size", value.get("position", value.get("quantity")))
                try:
                    is_open = quantity is not None and float(quantity) != 0
                except Exception:
                    is_open = False
                if ticker and is_open and sec_type in {"STK", "STOCK", "EQUITY", "OPT", "OPTION", "POSITION"} and re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", ticker):
                    if ticker not in seen:
                        seen.add(ticker)
                        symbols.append(ticker)
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(payload)
    return symbols


def age_minutes(value: Any) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return round(max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60.0), 2)
    except Exception:
        return None


def keychain_password(service: str, disabled: bool = False) -> str | None:
    if disabled:
        return None
    user = os.getenv("USER") or ""
    if not user:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", user, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def secret_from_env_or_keychain(env_names: list[str], service: str, no_keychain: bool) -> str | None:
    for name in env_names:
        value = os.getenv(name)
        if value:
            return value
    return keychain_password(service, disabled=no_keychain)


def ibkr_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def runtime_freshness() -> dict[str, Any]:
    files = [path for path in RUNTIME.glob("*") if path.is_file()]
    if not files:
        return {"available": False, "file_count": 0}
    newest = max(files, key=lambda path: path.stat().st_mtime)
    newest_dt = datetime.fromtimestamp(newest.stat().st_mtime, timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - newest_dt).total_seconds() / 60
    return {
        "available": True,
        "file_count": len(files),
        "newest_file": str(newest.relative_to(ROOT)),
        "newest_mtime": newest_dt.isoformat(),
        "age_minutes": round(age_minutes, 2),
    }


def local_foundation_health() -> dict[str, Any]:
    payload = foundation_health.build_foundation_health(RUNTIME)
    return {
        "ok": payload.get("status") in {"OK", "WAITING_FOR_DATA"},
        "status": payload.get("status"),
        "priorities": payload.get("priorities") or [],
        "data_quality": payload.get("data_quality") or {},
        "parameter_review_summary": payload.get("parameter_review_summary") or {},
        "not_order_instruction": payload.get("not_order_instruction") is True,
        "execution_authorized": payload.get("execution_authorized") is True,
    }


def local_operational_evidence_gate() -> dict[str, Any]:
    payload = operational_evidence_gate.build_operational_evidence_gate(
        RUNTIME,
        include_recovery_preview=False,
    )
    return {
        "ok": payload.get("state") in {"SIGNAL_COLLECTION_READY", "OUTCOME_COLLECTION_READY", "PARAMETER_REVIEW_READY"},
        "state": payload.get("state"),
        "blocked_reasons": payload.get("blocked_reasons") or [],
        "next_actions": payload.get("next_actions") or [],
        "capabilities": payload.get("capabilities") or {},
        "evidence_summary": payload.get("evidence_summary") or {},
        "not_order_instruction": payload.get("not_order_instruction") is True,
        "execution_authorized": payload.get("execution_authorized") is True,
    }


def request_json(
    url: str,
    token: str | None = None,
    timeout: int = 30,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if token:
        headers["X-Stock-Ultimus-Read-Token"] = token
    request = urllib.request.Request(url, data=body, headers=headers, method=str(method or "GET").upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:500]}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"detail": str(exc)}
    except (socket.timeout, TimeoutError, OSError) as exc:
        return 0, {"detail": str(exc), "error": exc.__class__.__name__}


def run_command(name: str, command: list[str], timeout: int, env: dict[str, str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        text = (result.stdout + "\n" + result.stderr).strip()
        return {
            "name": name,
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout_tail": text[-2500:],
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "name": name,
            "ok": False,
            "exit_code": None,
            "error": f"TIMEOUT_AFTER_{timeout}_SECONDS",
            "stdout_tail": (stdout + "\n" + stderr)[-2500:],
        }


def rsp_account_environment(args: argparse.Namespace) -> dict[str, str]:
    from scripts import ibkr_account_profile

    profile = ibkr_account_profile.profile_for(args.rsp_account_alias)
    env = ibkr_account_profile.environment_for(profile)
    env["STOCK_ULTIMUS_RSP_ACCOUNT_ALIAS"] = str(args.rsp_account_alias)
    return env


def refresh_bridge(args: argparse.Namespace, ingest_token: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["TRADING_ENGINE_INGEST_TOKEN"] = ingest_token
    env["IBKR_HOST"] = args.ibkr_host
    env["IBKR_PORT"] = str(args.ibkr_port)
    env["PYTHONUNBUFFERED"] = "1"
    env["IBKR_DISABLE_INCREMENTAL_ENGINE_POSTS"] = "1"
    env.setdefault("IBKR_HISTORICAL_DATA_TIMEOUT_SECONDS", "4")
    env.setdefault("IBKR_OPTION_CONTRACT_MARKET_DATA_TIMEOUT_SECONDS", "4")
    env.setdefault("IBKR_OPTION_MARKET_DATA_WAIT_SECONDS", "1.5")
    env.setdefault("IBKR_OPTION_SNAPSHOT_WAIT_SECONDS", "1")
    env.setdefault("IBKR_OPTION_SECOND_PASS_WAIT_SECONDS", "1")
    if not args.full_bridge:
        env.setdefault("DAILY_RADAR_FAST", "1")
        configured_symbols = os.getenv(
            "STOCK_ULTIMUS_DAILY_OPEN_OPTION_SYMBOLS",
            "QQQ,SPY,NVDA,TSLA,META,NFLX,TLT,AAPL,AMZN,MSFT",
        )
        configured = [value.strip().upper() for value in configured_symbols.split(",") if value.strip()]
        active_symbols = active_position_option_symbols()
        daily_symbols_list = list(dict.fromkeys(active_symbols + configured))
        daily_symbols = ",".join(daily_symbols_list)
        env.setdefault("IBKR_WATCHLIST", daily_symbols)
        env.setdefault("IBKR_OPTION_SYMBOLS", daily_symbols)
        env.setdefault("IBKR_MAX_OPTION_SYMBOLS_PER_RUN", "14")
        env.setdefault("IBKR_MAX_OPTIONS_PER_SYMBOL", "2")
        env.setdefault("IBKR_MAX_TOTAL_OPTION_CONTRACTS_PER_RUN", "28")
        env.setdefault("IBKR_DYNAMIC_OPTION_UNIVERSE_ENABLED", "1")
        env.setdefault("IBKR_INCLUDE_RUNTIME_TECHNICAL_OPTION_CANDIDATES", "1")
    return run_command(
        "refresh_ibkr_bridge",
        [sys.executable, "ibkr_bridge.py", "--once"],
        timeout=args.bridge_timeout,
        env=env,
    )


def refresh_rsp_bridge(args: argparse.Namespace, ingest_token: str) -> dict[str, Any]:
    env = rsp_account_environment(args)
    env["TRADING_ENGINE_INGEST_TOKEN"] = ingest_token
    env["IBKR_HOST"] = args.ibkr_host
    env["IBKR_PORT"] = str(args.ibkr_port)
    env["PYTHONUNBUFFERED"] = "1"
    env["IBKR_DISABLE_INCREMENTAL_ENGINE_POSTS"] = "1"
    command = [
        sys.executable,
        "scripts/run_market_bridge_session.py",
        "--max-runs",
        "1",
        "--bridge-timeout",
        str(args.rsp_bridge_timeout),
        "--historical-data-timeout",
        "6",
        "--coberturas-rsp-weekly",
        "--json-out",
        str(RUNTIME / "stock_ultimus_coberturas_rsp_weekly_bridge_latest.json"),
    ]
    return run_command(
        "refresh_coberturas_rsp",
        command,
        timeout=max(args.rsp_bridge_timeout + 45, 90),
        env=env,
    )


def refresh_account_capacity(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        "scripts/ibkr_account_profile.py",
        "refresh-account-capacity",
        "--host",
        args.ibkr_host,
        "--port",
        str(args.ibkr_port),
        "--client-id",
        os.getenv("STOCK_ULTIMUS_CONSOLE_IBKR_CLIENT_ID", "74"),
        "--timeout",
        str(args.capacity_timeout),
        "--json-out",
        str(RUNTIME / "coberturas_rsp_account_capacity_latest.json"),
    ]
    return run_command(
        "refresh_account_capacity",
        command,
        timeout=max(args.capacity_timeout + 15, 35),
        env=rsp_account_environment(args),
    )


def refresh_control_tower(args: argparse.Namespace) -> dict[str, Any]:
    """Capture every account before the slower option-chain scan begins."""
    per_request_timeout = max(
        5,
        min(15, int(os.getenv("STOCK_ULTIMUS_CONTROL_TOWER_ACCOUNT_TIMEOUT", "12"))),
    )
    command = [
        sys.executable,
        "scripts/refresh_multi_account_control_tower.py",
        "--host",
        args.ibkr_host,
        "--port",
        str(args.ibkr_port),
        "--client-id",
        os.getenv("STOCK_ULTIMUS_CONTROL_TOWER_CLIENT_ID", "84"),
        "--timeout",
        str(per_request_timeout),
        "--json-out",
        str(RUNTIME / "broker_control_tower_latest.json"),
    ]
    return run_command(
        "refresh_multi_account_control_tower",
        command,
        timeout=max(args.control_tower_timeout, 45),
        env=os.environ.copy(),
    )


def coberturas_rsp_summary() -> dict[str, Any]:
    try:
        payload = coberturas_engine.build_recommendation(RUNTIME)
    except Exception as exc:
        return {
            "ok": False,
            "status": "RSP_RECOMMENDATION_ERROR",
            "error": str(exc)[:300],
            "execution_authorized": False,
            "not_order_instruction": True,
        }
    context = payload.get("manual_context") if isinstance(payload.get("manual_context"), dict) else {}
    ibkr = payload.get("ibkr") if isinstance(payload.get("ibkr"), dict) else {}
    updated_at = context.get("updated_at")
    context_age_minutes = age_minutes(updated_at)
    context_fresh = context_age_minutes is not None and context_age_minutes <= 24 * 60
    chain_has_rsp = ibkr.get("chain_has_rsp") is True
    chain_is_fresh = ibkr.get("chain_is_fresh") is True
    executable_quote_count = int(ibkr.get("executable_quote_count") or 0)
    context_available = context.get("available") is True
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    automatic_ready = bool(
        chain_has_rsp
        and chain_is_fresh
        and payload.get("spot") is not None
        and position.get("state") not in {None, "", "UNKNOWN"}
    )
    return {
        "ok": automatic_ready,
        "status": (
            "RSP_READY_FOR_MANUAL_REVIEW"
            if automatic_ready and context_fresh
            else "RSP_READY_WITH_STALE_OPTIONAL_GAMMA"
            if automatic_ready
            else "RSP_ACTION_REQUIRED"
        ),
        "decision": payload.get("decision"),
        "next_action": payload.get("next_action"),
        "manual_context_available": context_available,
        "manual_context_updated_at": updated_at,
        "manual_context_age_minutes": context_age_minutes,
        "manual_context_fresh": context_fresh,
        "stale_manual_gamma_excluded_from_new_entry": (
            (payload.get("context_freshness") or {}).get("stale_manual_gamma_excluded_from_new_entry") is True
        ),
        "spot": payload.get("spot"),
        "gamma_bias": context.get("gamma_bias"),
        "chain_has_rsp": chain_has_rsp,
        "chain_is_fresh": chain_is_fresh,
        "executable_quote_count": executable_quote_count,
        "chain_coverage_generated_at": ibkr.get("chain_coverage_generated_at"),
        "candidate_count": payload.get("candidate_count") or 0,
        "blockers": payload.get("blockers") or [],
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_canslim_candidates(args: argparse.Namespace) -> dict[str, Any]:
    if args.skip_canslim:
        return {
            "name": "build_free_canslim_candidates",
            "ok": True,
            "skipped": True,
            "detail": "SKIPPED_BY_OPERATOR",
            "not_order_instruction": True,
        }
    command = [sys.executable, "scripts/build_canslim_free_candidates.py"]
    if args.refresh_sec_canslim:
        command.append("--refresh-sec")
    result = run_command(
        "build_free_canslim_candidates",
        command,
        timeout=args.canslim_timeout,
        env=os.environ.copy(),
    )
    result["non_blocking"] = True
    result["not_order_instruction"] = True
    return result


def publish_runtime(args: argparse.Namespace, ingest_token: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["TRADING_ENGINE_INGEST_TOKEN"] = ingest_token
    command = [sys.executable, "tools/publish_v31_snapshot_from_runtime.py", "--publish"]
    if args.allow_stale_publish:
        command.append("--allow-stale")
    attempt_timeout = max(1, int(env.get("TRADING_ENGINE_PUBLISH_TIMEOUT_SECONDS", "45")))
    attempts = max(1, int(env.get("TRADING_ENGINE_PUBLISH_RETRIES", "3")))
    retry_sleep = max(0.0, float(env.get("TRADING_ENGINE_PUBLISH_RETRY_SLEEP_SECONDS", "3")))
    # The previous fixed 90-second wrapper killed a publisher configured for
    # three 45-second attempts before its own retry policy could finish.
    wrapper_timeout = max(
        90,
        int((attempt_timeout * attempts) + (retry_sleep * max(attempts - 1, 0)) + 15),
    )
    return run_command(
        "publish_runtime_snapshot",
        command,
        timeout=wrapper_timeout,
        env=env,
    )


def ensure_conservative_premarket_context(base_url: str, read_token: str, timeout: int) -> dict[str, Any]:
    current_status, current = request_json(
        f"{base_url}/intraday_futures/premarket_context",
        token=read_token,
        timeout=timeout,
    )
    if current_status == 200 and current.get("found") is True:
        return {
            "ok": True,
            "status": "EXISTING_CONTEXT_PRESERVED",
            "context_id": (current.get("context") or {}).get("context_id"),
            "not_order_instruction": True,
        }

    template_status, template = request_json(
        f"{base_url}/intraday_futures/premarket_context/template?mode=automatic_conservative&updated_by=daily_open",
        token=read_token,
        timeout=timeout,
    )
    context_payload = template.get("payload") if isinstance(template.get("payload"), dict) else {}
    if template_status != 200 or not context_payload:
        return {"ok": False, "status": "TEMPLATE_UNAVAILABLE", "http_status": template_status}
    save_status, saved = request_json(
        f"{base_url}/intraday_futures/premarket_context",
        token=read_token,
        timeout=timeout,
        method="POST",
        payload=context_payload,
    )
    return {
        "ok": save_status == 200 and saved.get("status") == "ok",
        "status": "AUTOMATIC_CONSERVATIVE_CONTEXT_CREATED" if save_status == 200 else "SAVE_FAILED",
        "http_status": save_status,
        "context_id": ((saved.get("context") or {}).get("context_id") if isinstance(saved, dict) else None),
        "manual_validation_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def operator_counts(operator: dict[str, Any]) -> dict[str, int]:
    alerts = operator.get("active_alerts") if isinstance(operator.get("active_alerts"), list) else []
    severity_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    manual_review_ready = 0
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        severity = str(alert.get("severity") or "UNKNOWN")
        state = str(alert.get("state") or "UNKNOWN")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        state_counts[state] = state_counts.get(state, 0) + 1
        if alert.get("manual_review_ready") is True:
            manual_review_ready += 1
    return {
        "active_alerts": len(alerts),
        "action_alerts": severity_counts.get("ACTION", 0),
        "risk_alerts": severity_counts.get("RISK", 0),
        "watch_alerts": severity_counts.get("WATCH", 0),
        "manual_review_ready_alerts": manual_review_ready,
        "wait_market_alerts": state_counts.get("WAIT_MARKET", 0),
        "no_data_alerts": state_counts.get("NO_DATA", 0),
    }


def classify(report: dict[str, Any]) -> tuple[str, str]:
    checks = report["checks"]
    operator = report.get("operator_today") or {}
    counts = report.get("operator_counts") or {}
    if not checks["read_token_available"]["ok"]:
        return "ACTION_REQUIRED", "Configurar READ_ACCESS_TOKEN en env o Keychain."
    if not checks["production_auth"]["ok"]:
        return "ACTION_REQUIRED", "Revisar token/backend: produccion no acepta lectura autenticada."
    if report.get("refresh_step", {}).get("ok") is False:
        error = str(report.get("refresh_step", {}).get("error") or "")
        if error in {"IBKR_PORT_CLOSED", "MISSING_INGEST_TOKEN"}:
            return "ACTION_REQUIRED", "Abrir/desbloquear TWS-IBKR o revisar el token de ingest antes de reintentar."
        return "ACTION_REQUIRED", "IBKR conecto, pero el escaneo principal no termino; revisar timeout/red de produccion y reintentar una sola vez."
    if report.get("control_tower_refresh_step", {}).get("ok") is False:
        return "ACTION_REQUIRED", "IBKR está abierto, pero no se pudieron confirmar las tres cuentas; revisar TWS y refrescar Control Tower."
    if report.get("capacity_refresh_step", {}).get("ok") is False:
        return "ACTION_REQUIRED", "IBKR conecto, pero no se pudo confirmar la capacidad actual de la cuenta para evaluar RSP."
    if report.get("rsp_refresh_step", {}).get("ok") is False:
        return "ACTION_REQUIRED", "Coberturas RSP no completo su refresh IBKR 7-14 DTE; revisar el detalle RSP antes de usar candidatos."
    if report.get("publish_step", {}).get("ok") is False:
        return "ACTION_REQUIRED", "Revisar publicador de snapshot antes de usar el GPT."
    if checks.get("intraday_futures_reconciliation", {}).get("ok") is False:
        return "ACTION_REQUIRED", "No se pudo reconciliar la bandeja de futuros con las señales recibidas; revisar producción antes de operar intradía."
    rsp = report.get("coberturas_rsp") if isinstance(report.get("coberturas_rsp"), dict) else {}
    if report.get("refresh_requested") and not report.get("rsp_refresh_step", {}).get("skipped") and rsp.get("ok") is False:
        if not rsp.get("manual_context_available"):
            return "ACTION_REQUIRED", "Falta contexto RSP inicial; guardar una lectura antes de depender de niveles gamma."
        return "ACTION_REQUIRED", "La lectura RSP esta guardada, pero falta una cadena IBKR RSP fresca de 7-14 DTE."
    if checks.get("v32_operator_today", {}).get("ok") is False:
        return "ACTION_REQUIRED", "Produccion autentico correctamente, pero la lectura V32 fue lenta; reintentar solo Actualizar estado."
    foundation = checks.get("foundation_health") or {}
    if foundation.get("status") == "FAIL":
        priorities = foundation.get("priorities") if isinstance(foundation.get("priorities"), list) else []
        first_priority = priorities[0] if priorities else "Revisar runtime/foundation_health_latest.json."
        return "EVIDENCE_COLLECTION_ONLY", "Apertura tecnica completa; seguir acumulando evidencia antes de depender de ENTRY_READY: " + first_priority
    evidence_gate = checks.get("operational_evidence_gate") or {}
    if evidence_gate.get("state") == "FOUNDATION_BLOCKED":
        next_actions = evidence_gate.get("next_actions") if isinstance(evidence_gate.get("next_actions"), list) else []
        first_action = next_actions[0] if next_actions else "Revisar runtime/operational_evidence_gate_latest.json."
        return "ACTION_REQUIRED", "Resolver Operational Evidence Gate: " + first_action
    status = str(operator.get("status") or "")
    if status in {"NO_DATA", "WAIT_PIPELINE"} or counts.get("no_data_alerts", 0) > 0:
        return "SNAPSHOT_REQUIRED", "Refrescar/publicar snapshot antes de revisar setups."
    if counts.get("action_alerts", 0) or counts.get("risk_alerts", 0) or counts.get("manual_review_ready_alerts", 0):
        return "REVIEW_REQUIRED", "Abrir el GPT y revisar alertas ACTION/RISK/manual review."
    if status == "WAIT_MARKET" or counts.get("wait_market_alerts", 0):
        return "WAIT_MARKET", "Esperar ventana de mercado; no convertir WAIT_* en entrada."
    return "READY", "Preguntar al GPT 'que hago hoy?' y revisar solo flujo manual."


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.base_url.rstrip("/")
    read_token = secret_from_env_or_keychain(
        ["READ_ACCESS_TOKEN", "STOCK_ULTIMUS_READ_TOKEN", "STOCK_ULTIMUS_READ_ACCESS_TOKEN"],
        READ_KEYCHAIN_SERVICE,
        args.no_keychain,
    )
    ingest_token = secret_from_env_or_keychain(
        ["TRADING_ENGINE_INGEST_TOKEN", "SNAPSHOT_INGEST_TOKEN"],
        INGEST_KEYCHAIN_SERVICE,
        args.no_keychain,
    )
    ibkr_open = ibkr_port_open(args.ibkr_host, args.ibkr_port)
    checks: dict[str, Any] = {
        "ibkr_port": {
            "ok": ibkr_open,
            "host": args.ibkr_host,
            "port": args.ibkr_port,
            "detail": "TWS/IB Gateway API port reachable" if ibkr_open else "TWS/IB Gateway API port not reachable",
        },
        "read_token_available": {"ok": bool(read_token), "source": "env_or_keychain" if read_token else None},
        "ingest_token_available": {"ok": bool(ingest_token), "source": "env_or_keychain" if ingest_token else None},
        "runtime_freshness": runtime_freshness(),
    }

    report: dict[str, Any] = {
        "engine": "STOCK_ULTIMUS_DAILY_OPEN_CHECKLIST",
        "checklist_version": "daily_open_checklist_v1",
        "generated_at": now_iso(),
        "base_url": base_url,
        "checks": checks,
        "refresh_requested": bool(args.refresh),
        "publish_requested": bool(args.publish),
        "uses_ingest_token": bool(args.refresh or args.publish),
        "touches_ibkr": bool(args.refresh),
        "rsp_account_alias": str(args.rsp_account_alias),
        "sends_email": False,
        "secrets_printed": False,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }

    premarket_context = None
    if read_token:
        premarket_context = ensure_conservative_premarket_context(
            base_url, read_token, args.read_timeout
        )
        checks["intraday_futures_premarket_context"] = premarket_context
        report["intraday_futures_premarket_context"] = premarket_context

    if args.refresh:
        report["canslim_step"] = build_canslim_candidates(args)
        if not ibkr_open:
            report["control_tower_refresh_step"] = {
                "name": "refresh_multi_account_control_tower",
                "ok": False,
                "error": "IBKR_PORT_CLOSED",
            }
        else:
            report["control_tower_refresh_step"] = refresh_control_tower(args)
        if not ingest_token:
            report["refresh_step"] = {"name": "refresh_ibkr_bridge", "ok": False, "error": "MISSING_INGEST_TOKEN"}
        elif not ibkr_open:
            report["refresh_step"] = {"name": "refresh_ibkr_bridge", "ok": False, "error": "IBKR_PORT_CLOSED"}
        else:
            report["refresh_step"] = refresh_bridge(args, ingest_token)
            checks["runtime_freshness_after_refresh"] = runtime_freshness()
        if not ibkr_open:
            report["capacity_refresh_step"] = {"name": "refresh_account_capacity", "ok": False, "error": "IBKR_PORT_CLOSED"}
        else:
            report["capacity_refresh_step"] = refresh_account_capacity(args)
        if args.skip_rsp_refresh:
            report["rsp_refresh_step"] = {
                "name": "refresh_coberturas_rsp",
                "ok": True,
                "skipped": True,
                "detail": "SKIPPED_BY_OPERATOR",
                "not_order_instruction": True,
            }
        elif not ingest_token:
            report["rsp_refresh_step"] = {"name": "refresh_coberturas_rsp", "ok": False, "error": "MISSING_INGEST_TOKEN"}
        elif not ibkr_open:
            report["rsp_refresh_step"] = {"name": "refresh_coberturas_rsp", "ok": False, "error": "IBKR_PORT_CLOSED"}
        else:
            report["rsp_refresh_step"] = refresh_rsp_bridge(args, ingest_token)
        report["coberturas_rsp"] = coberturas_rsp_summary()

    if args.publish:
        if not ingest_token:
            report["publish_step"] = {"name": "publish_runtime_snapshot", "ok": False, "error": "MISSING_INGEST_TOKEN"}
        else:
            report["publish_step"] = publish_runtime(args, ingest_token)
            checks["runtime_freshness_after_publish"] = runtime_freshness()

    checks["foundation_health"] = local_foundation_health()
    checks["operational_evidence_gate"] = local_operational_evidence_gate()

    if read_token:
        denied_status, _ = request_json(f"{base_url}/v31_system_status", timeout=args.read_timeout)
        allowed_status, allowed = request_json(f"{base_url}/v31_system_status", token=read_token, timeout=args.read_timeout)
        checks["production_auth"] = {
            "ok": denied_status in {401, 503} and allowed_status == 200 and allowed.get("not_order_instruction") is True,
            "unauthorized_status": denied_status,
            "authorized_status": allowed_status,
        }
        reconcile_status, reconciliation = 0, {}
        reconcile_attempts = 0
        for reconcile_attempts in range(1, 3):
            reconcile_status, reconciliation = request_json(
                f"{base_url}/v32_intraday_futures_reconcile?limit=2000",
                token=read_token,
                timeout=max(args.read_timeout, 45),
                method="POST",
            )
            if reconcile_status == 200:
                break
        checks["intraday_futures_reconciliation"] = {
            "ok": reconcile_status == 200,
            "status_code": reconcile_status,
            "attempt_count": reconcile_attempts,
            "processed_count": reconciliation.get("processed_count") if isinstance(reconciliation, dict) else None,
            "candidate_count": reconciliation.get("candidate_count") if isinstance(reconciliation, dict) else None,
        }
        report["intraday_futures_reconciliation"] = reconciliation
        operator_status, operator = request_json(
            f"{base_url}/gpt_v32_operator_today?limit={max(1, args.limit)}",
            token=read_token,
            timeout=args.read_timeout,
        )
        checks["v32_operator_today"] = {"ok": operator_status == 200, "status_code": operator_status}
        if operator_status == 200:
            report["operator_today"] = operator
            report["operator_counts"] = operator_counts(operator)
        else:
            report["operator_today_error"] = operator
    else:
        checks["production_auth"] = {"ok": False, "error": "MISSING_READ_TOKEN"}
        checks["intraday_futures_reconciliation"] = {"ok": False, "error": "MISSING_READ_TOKEN"}
        checks["v32_operator_today"] = {"ok": False, "error": "MISSING_READ_TOKEN"}

    status, next_action = classify(report)
    report["status"] = status
    report["ok"] = status in {"READY", "WAIT_MARKET", "REVIEW_REQUIRED", "EVIDENCE_COLLECTION_ONLY"}
    report["next_required_action"] = next_action
    report["gpt_prompt"] = "que hago hoy?"
    report["operator_dashboard"] = base_url + "/v32_operator_dashboard"
    report["operator_json"] = base_url + "/gpt_v32_operator_today"
    report["operator_events"] = base_url + "/v32_operator_events"
    return report


def print_human(report: dict[str, Any]) -> None:
    print("Stock Ultimus Daily Open Checklist")
    print(f"Estado: {report.get('status')} | ok={report.get('ok')}")
    print(f"Siguiente accion: {report.get('next_required_action')}")
    checks = report.get("checks") or {}
    print("\nChecks:")
    for name in ["ibkr_port", "read_token_available", "ingest_token_available", "foundation_health", "operational_evidence_gate", "production_auth", "intraday_futures_reconciliation", "v32_operator_today"]:
        check = checks.get(name) or {}
        marker = "OK" if check.get("ok") else "FAIL"
        detail = check.get("detail") or check.get("error") or ""
        if name == "foundation_health":
            detail = "status=" + str(check.get("status"))
        if name == "operational_evidence_gate":
            detail = "state=" + str(check.get("state"))
        print(f"- {name}: {marker} {detail}")
    runtime = checks.get("runtime_freshness_after_publish") or checks.get("runtime_freshness_after_refresh") or checks.get("runtime_freshness") or {}
    if runtime:
        print(f"- runtime: newest={runtime.get('newest_file')} age_min={runtime.get('age_minutes')} files={runtime.get('file_count')}")

    operator = report.get("operator_today") or {}
    counts = report.get("operator_counts") or {}
    if operator:
        command = operator.get("command_center") if isinstance(operator.get("command_center"), dict) else {}
        summary = command.get("summary") if isinstance(command.get("summary"), dict) else {}
        print("\nOperador V32:")
        print(f"- status={operator.get('status')} readiness={command.get('operational_readiness')}")
        print(f"- alerts={counts.get('active_alerts')} action={counts.get('action_alerts')} risk={counts.get('risk_alerts')} watch={counts.get('watch_alerts')}")
        print(f"- option_rows_found={summary.get('option_rows_found')} technical_count={summary.get('technical_count')}")
        print(f"- prompt GPT sugerido: {report.get('gpt_prompt')}")
    print("\nGuardrail: Decision support solamente; execution_authorized=false; not_order_instruction=true.")


def main() -> int:
    args = parse_args()
    report = build_report(args)
    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print_human(report)
    if args.soft_exit:
        return 0
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
