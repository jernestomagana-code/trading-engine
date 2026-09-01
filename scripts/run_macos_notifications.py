#!/usr/bin/env python3
"""Deliver deduplicated, actionable Stock Ultimus notifications on macOS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.getenv("STOCK_ULTIMUS_PROJECT_ROOT", str(Path(__file__).resolve().parents[1])))
RUNTIME = Path(os.getenv("STOCK_ULTIMUS_RUNTIME_DIR", str(ROOT / "runtime")))
CONFIG_PATH = RUNTIME / "macos_notification_config.json"
STATE_PATH = RUNTIME / "macos_notification_state.json"
STATUS_PATH = RUNTIME / "macos_notification_status.json"
RISK_PATH = RUNTIME / "portfolio_risk_latest.json"
ENVIRONMENT_PATH = RUNTIME / "environment_alerts_latest.json"
REMOTE_CACHE_PATH = RUNTIME / "stock_ultimus_console_remote_cache.json"
BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://trading-engine-p097.onrender.com").rstrip("/")
KEYCHAIN_SERVICES = ("stock-ultimus-read-access-token", "stock-ultimus-read-access")
DEFAULT_CONFIG = {
    "enabled": True,
    "entry_enabled": True,
    "risk_enabled": True,
    "operational_enabled": True,
    "sound_enabled": True,
    "poll_seconds": 15,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def config() -> dict[str, Any]:
    return {**DEFAULT_CONFIG, **load_json(CONFIG_PATH)}


def read_token() -> str:
    token = os.getenv("READ_ACCESS_TOKEN", "").strip()
    if token:
        return token
    for service in KEYCHAIN_SERVICES:
        try:
            proc = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-a", os.getenv("USER", ""), "-s", service, "-w"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass
    return ""


def fetch(path: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        BASE_URL + path,
        headers={"Accept": "application/json", "X-Stock-Ultimus-Read-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{path}: {exc}") from exc


def stable_id(prefix: str, value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return prefix + "-" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def first_value(item: dict[str, Any], *names: str) -> Any:
    raw = item.get("raw_payload") if isinstance(item.get("raw_payload"), dict) else {}
    decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
    for name in names:
        for source in (item, decision, raw):
            if source.get(name) not in (None, ""):
                return source.get(name)
    return None


def entry_event(item: dict[str, Any]) -> dict[str, Any] | None:
    accepted = item.get("accepted_for_engine") is True or str(item.get("alert_contract_status") or "").upper() == "ACCEPTED"
    state = str(first_value(item, "final_state", "decision_state", "setup_stage") or "").upper()
    event = str(first_value(item, "event", "event_code") or "").upper()
    priority = str(first_value(item, "alert_priority") or "").upper()
    mobile = item.get("mobile_notification") if isinstance(item.get("mobile_notification"), dict) else {}
    is_entry = state in {"ENTRY", "ENTRY_READY", "VALID_ENTRY", "APPROVED_ENTRY"} or "ENTRY_TRIGGER" in event
    is_entry = is_entry or str(mobile.get("kind") or mobile.get("notification_kind") or "").upper() == "ENTRY_TRIGGER"
    if not accepted or not is_entry or priority == "SILENT":
        return None
    ticker = str(first_value(item, "target_instrument", "ticker") or "Futuros")
    direction = str(first_value(item, "direction", "breakout_direction") or "ENTRADA").upper()
    price = first_value(item, "entry_price", "trigger_price", "price")
    stop = first_value(item, "stop_price", "logical_stop")
    tp1 = first_value(item, "tp1_price")
    tp2 = first_value(item, "tp2_price", "logical_target")
    levels = " · ".join(part for part in [f"entrada {price}" if price else "", f"stop {stop}" if stop else "", f"T1 {tp1}" if tp1 else "", f"T2 {tp2}" if tp2 else ""] if part)
    return {
        "id": str(item.get("event_id") or item.get("id") or stable_id("signal", item)),
        "category": "ENTRY",
        "title": f"Entrada {ticker} · {direction}",
        "message": levels or "Nueva entrada validada; revisar la consola antes de actuar.",
        "subtitle": "Stock Ultimus · Futuros",
    }


def operator_entry(item: dict[str, Any]) -> dict[str, Any] | None:
    state = str(item.get("final_state") or item.get("state") or item.get("decision") or "").upper()
    if state not in {"ENTRY", "ENTRY_READY", "VALID_ENTRY", "APPROVED_ENTRY"}:
        return None
    ticker = str(item.get("ticker") or item.get("symbol") or "Oportunidad")
    strategy = str(item.get("strategy") or item.get("strategy_context") or "Entrada")
    reason = str(item.get("instruction") or item.get("recommendation") or item.get("why") or "Revisar la oportunidad en la consola.")
    identity = item.get("alert_id") or item.get("event_id") or item.get("id") or [ticker, strategy, state, item.get("generated_at")]
    return {"id": str(identity) if isinstance(identity, str) else stable_id("operator", identity), "category": "ENTRY", "title": f"Oportunidad {ticker}", "message": f"{strategy}: {reason}"[:240], "subtitle": "Stock Ultimus · ENTRY_READY"}


def cached_remote(path: str) -> dict[str, Any]:
    cache = load_json(REMOTE_CACHE_PATH)
    entries = cache.get("entries") if isinstance(cache.get("entries"), dict) else {}
    entry = entries.get(path) if isinstance(entries.get(path), dict) else {}
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    return result


def collect_remote(token: str, errors: list[str] | None = None) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    try:
        response = fetch("/v32_signal_events?limit=100", token)
        data = response.get("data") if isinstance(response.get("data"), dict) else response
        for item in data.get("events", []) if isinstance(data.get("events"), list) else []:
            if isinstance(item, dict):
                candidate = entry_event(item)
                if candidate:
                    output.append(candidate)
    except Exception as exc:
        if errors is not None:
            errors.append(str(exc))
    operator = cached_remote("/gpt_v32_operator_today?limit=12")
    operator_data = operator.get("data") if isinstance(operator.get("data"), dict) else operator
    for field in ("active_alerts", "next_actions"):
        for item in operator_data.get(field, []) if isinstance(operator_data.get(field), list) else []:
            if isinstance(item, dict):
                candidate = operator_entry(item)
                if candidate:
                    output.append(candidate)
    return output


def collect_local() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    risk = load_json(RISK_PATH)
    for item in risk.get("alerts", []) if isinstance(risk.get("alerts"), list) else []:
        if not isinstance(item, dict) or str(item.get("severity") or "").upper() not in {"HIGH", "CRITICAL"} or str(item.get("lifecycle_status") or "OPEN").upper() != "OPEN":
            continue
        output.append({
            "id": str(item.get("alert_id") or stable_id("risk", item)), "category": "RISK",
            "title": str(item.get("title") or "Riesgo de cartera"),
            "message": str(item.get("recommended_action") or item.get("message") or "Revisar en la consola.")[:240],
            "subtitle": f"Stock Ultimus · Riesgo {str(item.get('severity')).upper()}",
        })
    environment = load_json(ENVIRONMENT_PATH)
    incident = environment.get("incident") if isinstance(environment.get("incident"), dict) else {}
    remediation = environment.get("remediation") if isinstance(environment.get("remediation"), dict) else {}
    if incident.get("active") is True and (incident.get("should_escalate") is True or environment.get("should_notify") is True):
        identity = [environment.get("state_signature"), incident.get("reason"), remediation]
        output.append({
            "id": stable_id("ops", identity), "category": "OPERATIONAL", "title": "Atención operativa requerida",
            "message": str(remediation.get("next_action") or environment.get("notify_reason") or incident.get("reason") or "Abrir Configuración y revisar el diagnóstico.")[:240],
            "subtitle": "Stock Ultimus · Incidencia",
        })
    return output


def display(notification: dict[str, Any], sound: bool = True) -> None:
    script = """on run argv
set nTitle to item 1 of argv
set nSubtitle to item 2 of argv
set nMessage to item 3 of argv
if (item 4 of argv) is \"yes\" then
display notification nMessage with title nTitle subtitle nSubtitle sound name \"Glass\"
else
display notification nMessage with title nTitle subtitle nSubtitle
end if
end run"""
    proc = subprocess.run(["/usr/bin/osascript", "-e", script, "--", notification["title"], notification["subtitle"], notification["message"], "yes" if sound else "no"], capture_output=True, text=True, timeout=10, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "osascript failed").strip())


def run(prime: bool = False, test: bool = False) -> dict[str, Any]:
    settings = config()
    state = load_json(STATE_PATH)
    seen = set(str(value) for value in state.get("seen_ids", []) if value)
    errors: list[str] = []
    candidates: list[dict[str, Any]] = []
    if test:
        candidates = [{"id": stable_id("test", now_iso()), "category": "TEST", "title": "Stock Ultimus listo", "message": "Los avisos emergentes de esta Mac funcionan correctamente.", "subtitle": "Prueba local · no es señal"}]
    else:
        candidates.extend(collect_local())
        token = read_token()
        if token:
            candidates.extend(collect_remote(token, errors))
        else:
            errors.append("No se encontró el token local de lectura.")
    unique = {str(item["id"]): item for item in candidates}
    enabled_categories = {
        "ENTRY": bool(settings.get("entry_enabled")), "RISK": bool(settings.get("risk_enabled")),
        "OPERATIONAL": bool(settings.get("operational_enabled")), "TEST": True,
    }
    eligible = [item for item in unique.values() if enabled_categories.get(item["category"], False)]
    sent: list[str] = []
    if not prime and (settings.get("enabled") or test):
        for item in eligible:
            if item["id"] in seen and not test:
                continue
            try:
                display(item, bool(settings.get("sound_enabled")))
                sent.append(item["id"])
            except Exception as exc:
                errors.append(str(exc))
    seen.update(unique)
    bounded_seen = list(dict.fromkeys([*state.get("seen_ids", []), *unique.keys()]))[-5000:]
    save_json(STATE_PATH, {"state_version": "macos_notification_state_v1", "updated_at": now_iso(), "primed_at": now_iso() if prime else state.get("primed_at"), "seen_ids": bounded_seen})
    status = {
        "engine": "STOCK_ULTIMUS_MACOS_NOTIFICATIONS", "status_version": "macos_notification_status_v1",
        "checked_at": now_iso(), "enabled": bool(settings.get("enabled")), "primed": bool(prime),
        "candidate_count": len(unique), "eligible_count": len(eligible), "new_notification_count": len(sent),
        "sent_ids": sent, "errors": errors, "status": "OK" if not errors else "DEGRADED",
        "execution_authorized": False, "not_order_instruction": True,
    }
    save_json(STATUS_PATH, status)
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prime", action="store_true", help="Remember current items without displaying them.")
    parser.add_argument("--test", action="store_true", help="Display one harmless test notification.")
    args = parser.parse_args()
    result = run(prime=args.prime, test=args.test)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "OK" or args.test else 1


if __name__ == "__main__":
    raise SystemExit(main())
