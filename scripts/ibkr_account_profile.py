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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
PROFILES_PATH = RUNTIME / "ibkr_account_profiles.local.json"
ACTIVE_PATH = RUNTIME / "ibkr_account_active_profile.json"
WEB_LAST_RESULT_PATH = RUNTIME / "ibkr_account_profile_web_last_result.json"
KEYCHAIN_SERVICE_PREFIX = "stock-ultimus-ibkr-account-"
READ_KEYCHAIN_SERVICES = ("stock-ultimus-read-access-token", "stock-ultimus-read-access")
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"


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


def read_keychain_value(service: str) -> str:
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
        timeout=10,
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
    account = read_keychain_value(service)
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
    result = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=None,
    )
    payload = {
        "result_version": "ibkr_account_profile_web_result_v1",
        "generated_at": now_iso(),
        "alias": profile["alias"],
        "account_scope": profile["account_scope"],
        "command": command_label(command),
        "returncode": int(result.returncode),
        "stdout_tail": sanitize_output(result.stdout, env),
        "stderr_tail": sanitize_output(result.stderr, env),
        "account_id_printed": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    RUNTIME.mkdir(exist_ok=True)
    WEB_LAST_RESULT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def cmd_run(args: argparse.Namespace) -> int:
    if not args.command:
        raise SystemExit("Falta comando despues de --. Ejemplo: run primary -- python3 ibkr_bridge.py --once")
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    return run_with_profile(args.alias, command)


def cmd_bridge(args: argparse.Namespace) -> int:
    return run_with_profile(args.alias, [sys.executable, "ibkr_bridge.py", "--once"])


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
        token = read_keychain_value(service)
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


def fetch_remote_json(path: str, timeout: int = 8) -> dict[str, Any]:
    token = read_access_token()
    if not token:
        return {"ok": False, "error": "MISSING_READ_ACCESS_TOKEN", "token_present": False, "data": {}}
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
        return {"ok": True, "error": "", "token_present": True, "url": url, "data": data if isinstance(data, dict) else {}}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP_{exc.code}", "token_present": True, "url": url, "data": {}}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "token_present": True, "url": url, "data": {}}


def console_operator_payload() -> dict[str, Any]:
    return fetch_remote_json("/gpt_v32_operator_today?limit=12")


def selected_vs_published(active: dict[str, Any], snapshot: dict[str, Any], operator_payload: dict[str, Any]) -> dict[str, Any]:
    operator_data = operator_payload.get("data") if isinstance(operator_payload.get("data"), dict) else {}
    operator_context = operator_data.get("account_context") if isinstance(operator_data.get("account_context"), dict) else {}
    selected_scope = active.get("account_scope") or ""
    selected_alias = active.get("account_alias") or ""
    published_scope = (
        operator_data.get("account_scope")
        or operator_context.get("account_scope")
        or snapshot.get("account_scope")
        or ""
    )
    published_alias = (
        operator_data.get("account_alias")
        or operator_context.get("account_alias")
        or snapshot.get("account_alias")
        or ""
    )
    matches = bool(selected_scope and published_scope and selected_scope == published_scope)
    return {
        "selected_scope": selected_scope,
        "selected_alias": selected_alias,
        "published_scope": published_scope,
        "published_alias": published_alias,
        "matches": matches,
        "needs_refresh": bool(selected_scope and published_scope and not matches),
        "status": "MATCH" if matches else "REFRESH_REQUIRED",
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
    if comparison["needs_refresh"]:
        warning = """
        <div class="warning">Seleccion local y contexto publicado no coinciden. Refresca IBKR antes de pedirle al GPT que interprete broker/account context.</div>
        """
    elif not comparison["published_scope"]:
        warning = """
        <div class="warning">No hay contexto publicado para GPT. Selecciona una cuenta y refresca el bridge.</div>
        """
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
            comparison["published_alias"] or "none",
            "scope=" + (comparison["published_scope"] or "none"),
        ),
        snapshot=render_metric(
            "Snapshot",
            "available" if snapshot.get("available") else "missing",
            (snapshot.get("path") or "no file") + " | " + age_label(snapshot.get("generated_at") or snapshot.get("mtime")),
        ),
        operator=render_metric(
            "V32 status",
            status,
            "remote=" + ("ok" if operator_payload.get("ok") else "blocked"),
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
            </article>
            """.format(
                ticker=html_escape(alert.get("ticker") or "UNKNOWN"),
                severity=html_escape(str(alert.get("severity") or "UNKNOWN").lower()),
                state=html_escape(alert.get("state") or "UNKNOWN"),
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
                <form method="post" action="/select"><input name="alias" value="{alias}" type="hidden"><button>Usar</button></form>
                <form method="post" action="/bridge"><input name="alias" value="{alias}" type="hidden"><button>Usar + Refresh IBKR</button></form>
                <form method="post" action="/daily-open"><input name="alias" value="{alias}" type="hidden"><button>Daily open</button></form>
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


def render_web_page(message: str = "", result: dict[str, Any] | None = None) -> bytes:
    data = load_profiles()
    profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
    active = active_profile()
    snapshot = latest_master_snapshot()
    operator_payload = console_operator_payload()
    result = result or web_last_result()

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
          button.secondary {{ background:#6c5f45; }}
          .panel {{ padding:20px; margin-top:20px; }}
          .section-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:20px; }}
          .section-head p {{ margin:0; color:var(--muted); max-width:620px; }}
          .tiles,.alert-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
          .tile,.alert-card {{ border:1px solid var(--line); background:#fffdf6; border-radius:18px; padding:14px; text-decoration:none; color:var(--ink); }}
          .tile {{ font-weight:800; }}
          .tile span,.alert-card span,.alert-card small {{ display:block; color:var(--muted); margin-top:6px; font-weight:400; }}
          .alert-card strong {{ font-size:1.35rem; }}
          .severity-action {{ border-color:#d97706; }}
          .severity-risk {{ border-color:var(--risk); }}
          .severity-watch {{ border-color:#2563eb; }}
          label {{ display:block; margin:10px 0 4px; font-weight:700; }}
          input {{ width:min(520px,100%); border:1px solid var(--line); border-radius:12px; padding:11px 12px; font:inherit; background:white; box-sizing:border-box; }}
          pre {{ white-space:pre-wrap; overflow:auto; background:#162019; color:#f6f1df; border-radius:14px; padding:14px; max-height:360px; }}
          footer {{ margin-top:26px; color:var(--muted); font-size:.95rem; }}
          @media (max-width:820px) {{ .hero-panel {{ grid-template-columns:1fr; }} .context-grid {{ grid-template-columns:1fr; }} .card {{ align-items:flex-start; flex-direction:column; }} .actions {{ justify-content:flex-start; }} }}
        </style>
      </head>
      <body>
        <main>
          {context}
          {message}
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
            <form method="post" action="/setup" autocomplete="off">
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
      </body>
    </html>
    """.format(
        context=render_console_context(active, snapshot, operator_payload),
        message=('<div class="notice">' + html_escape(message) + "</div>") if message else "",
        profile_cards=render_profile_cards(profiles, active),
        alerts=render_operator_alerts(operator_payload),
        actions=render_console_actions(),
        output=output,
    )
    return body.encode("utf-8")


class AccountProfileWebHandler(BaseHTTPRequestHandler):
    server_version = "StockUltimusIBKRProfile/1.0"

    def send_html(self, message: str = "", result: dict[str, Any] | None = None, status: int = 200) -> None:
        payload = render_web_page(message=message, result=result)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ["/", "", "/console"]:
            self.send_html("Ruta no encontrada.", status=404)
            return
        self.send_html()

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
                result = run_with_profile_capture(alias, [sys.executable, "ibkr_bridge.py", "--once"])
                self.send_html("Bridge refresh terminado. Revisa returncode y salida.", result=result)
            elif self.path == "/daily-open":
                result = run_with_profile_capture(alias, [sys.executable, "scripts/daily_open_checklist.py", "--refresh"])
                self.send_html("Daily open terminado. Revisa returncode y salida.", result=result)
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
    server = HTTPServer((host, int(args.port)), AccountProfileWebHandler)
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
