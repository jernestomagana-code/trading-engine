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
    parser.add_argument("--bridge-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_BRIDGE_TIMEOUT", "240")))
    parser.add_argument("--limit", type=int, default=int(os.getenv("STOCK_ULTIMUS_OPERATOR_ALERT_LIMIT", "10")))
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_DAILY_OPEN_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--refresh", action="store_true", help="Run ibkr_bridge.py --once before reading V32.")
    parser.add_argument("--publish", action="store_true", help="Publish runtime snapshot after refresh/check.")
    parser.add_argument("--allow-stale-publish", action="store_true", help="Pass --allow-stale to the publisher.")
    parser.add_argument("--full-bridge", action="store_true", help="Do not enable DAILY_RADAR_FAST for the bridge.")
    parser.add_argument("--no-keychain", action="store_true", help="Use env vars only; do not read macOS Keychain.")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def request_json(url: str, token: str | None = None, timeout: int = 30) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Stock-Ultimus-Read-Token"] = token
    request = urllib.request.Request(url, headers=headers)
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


def refresh_bridge(args: argparse.Namespace, ingest_token: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["TRADING_ENGINE_INGEST_TOKEN"] = ingest_token
    env["IBKR_HOST"] = args.ibkr_host
    env["IBKR_PORT"] = str(args.ibkr_port)
    env["PYTHONUNBUFFERED"] = "1"
    if not args.full_bridge:
        env.setdefault("DAILY_RADAR_FAST", "1")
    return run_command(
        "refresh_ibkr_bridge",
        [sys.executable, "ibkr_bridge.py", "--once"],
        timeout=args.bridge_timeout,
        env=env,
    )


def publish_runtime(args: argparse.Namespace, ingest_token: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["TRADING_ENGINE_INGEST_TOKEN"] = ingest_token
    command = [sys.executable, "tools/publish_v31_snapshot_from_runtime.py", "--publish"]
    if args.allow_stale_publish:
        command.append("--allow-stale")
    return run_command("publish_runtime_snapshot", command, timeout=90, env=env)


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
        return "ACTION_REQUIRED", "Abrir/desbloquear TWS-IBKR y reintentar refresh."
    if report.get("publish_step", {}).get("ok") is False:
        return "ACTION_REQUIRED", "Revisar publicador de snapshot antes de usar el GPT."
    foundation = checks.get("foundation_health") or {}
    if foundation.get("status") == "FAIL":
        priorities = foundation.get("priorities") if isinstance(foundation.get("priorities"), list) else []
        first_priority = priorities[0] if priorities else "Revisar runtime/foundation_health_latest.json."
        return "ACTION_REQUIRED", "Resolver Foundation Health antes de depender del motor: " + first_priority
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
        "sends_email": False,
        "secrets_printed": False,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }

    if args.refresh:
        if not ingest_token:
            report["refresh_step"] = {"name": "refresh_ibkr_bridge", "ok": False, "error": "MISSING_INGEST_TOKEN"}
        elif not ibkr_open:
            report["refresh_step"] = {"name": "refresh_ibkr_bridge", "ok": False, "error": "IBKR_PORT_CLOSED"}
        else:
            report["refresh_step"] = refresh_bridge(args, ingest_token)
            checks["runtime_freshness_after_refresh"] = runtime_freshness()

    if args.publish:
        if not ingest_token:
            report["publish_step"] = {"name": "publish_runtime_snapshot", "ok": False, "error": "MISSING_INGEST_TOKEN"}
        else:
            report["publish_step"] = publish_runtime(args, ingest_token)
            checks["runtime_freshness_after_publish"] = runtime_freshness()

    checks["foundation_health"] = local_foundation_health()

    if read_token:
        denied_status, _ = request_json(f"{base_url}/v31_system_status", timeout=args.read_timeout)
        allowed_status, allowed = request_json(f"{base_url}/v31_system_status", token=read_token, timeout=args.read_timeout)
        checks["production_auth"] = {
            "ok": denied_status in {401, 503} and allowed_status == 200 and allowed.get("not_order_instruction") is True,
            "unauthorized_status": denied_status,
            "authorized_status": allowed_status,
        }
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
        checks["v32_operator_today"] = {"ok": False, "error": "MISSING_READ_TOKEN"}

    status, next_action = classify(report)
    report["status"] = status
    report["ok"] = status in {"READY", "WAIT_MARKET", "REVIEW_REQUIRED"}
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
    for name in ["ibkr_port", "read_token_available", "ingest_token_available", "foundation_health", "production_auth", "v32_operator_today"]:
        check = checks.get(name) or {}
        marker = "OK" if check.get("ok") else "FAIL"
        detail = check.get("detail") or check.get("error") or ""
        if name == "foundation_health":
            detail = "status=" + str(check.get("status"))
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
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
