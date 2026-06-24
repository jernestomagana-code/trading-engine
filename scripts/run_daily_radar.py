#!/usr/bin/env python3
"""Refresh and read the Stock Ultimus daily radar.

This script is a local operator helper. It refreshes IBKR data through the
bridge, then reads the GPT-facing V31 daily ranking endpoint. It never places
orders and never prints tokens.
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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"
INGEST_KEYCHAIN_SERVICE = "stock-ultimus-snapshot-ingest"
READ_KEYCHAIN_SERVICE = "stock-ultimus-read-access-token"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Stock Ultimus daily radar.")
    parser.add_argument("--public-base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL))
    parser.add_argument("--ibkr-host", default=os.getenv("IBKR_HOST", "127.0.0.1"))
    parser.add_argument("--ibkr-port", type=int, default=int(os.getenv("IBKR_PORT", "7496")))
    parser.add_argument("--bridge-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_BRIDGE_TIMEOUT", "240")))
    parser.add_argument("--read-timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "30")))
    parser.add_argument("--skip-bridge", action="store_true", help="Only read the current cloud radar.")
    parser.add_argument("--allow-partial", action="store_true", help="Continue to cloud read even if the bridge refresh fails.")
    parser.add_argument("--json-out", help="Optional path to save the raw /gpt_v31_daily_rankings response.")
    parser.add_argument("--preview", type=int, default=5, help="Rows to print per ranking section.")
    return parser.parse_args()


def keychain_password(service: str) -> str | None:
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


def secret_from_env_or_keychain(env_names: list[str], keychain_service: str) -> str | None:
    for name in env_names:
        value = os.getenv(name)
        if value:
            return value
    return keychain_password(keychain_service)


def ibkr_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_bridge(args: argparse.Namespace, ingest_token: str) -> int:
    if not ibkr_port_open(args.ibkr_host, args.ibkr_port):
        print(f"IBKR no parece estar escuchando en {args.ibkr_host}:{args.ibkr_port}.")
        return 20

    env = os.environ.copy()
    env["TRADING_ENGINE_INGEST_TOKEN"] = ingest_token
    env["IBKR_HOST"] = args.ibkr_host
    env["IBKR_PORT"] = str(args.ibkr_port)
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [sys.executable, str(ROOT / "ibkr_bridge.py"), "--once"]
    print("Refrescando snapshot con ibkr_bridge.py --once ...")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=args.bridge_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(f"Bridge excedio {args.bridge_timeout}s.")
        return 21

    if result.returncode != 0:
        print(f"Bridge termino con codigo {result.returncode}.")
        tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-12:])
        if tail:
            print(tail)
    else:
        print("Snapshot publicado por bridge.")
    return result.returncode


def read_daily_rankings(base_url: str, read_token: str, timeout: int) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/gpt_v31_daily_rankings"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Stock-Ultimus-Read-Token": read_token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} fallo con HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {url} fallo: {exc}") from exc
    return json.loads(payload)


def selected_contract(item: dict[str, Any]) -> dict[str, Any]:
    contract = item.get("selected_contract") if isinstance(item.get("selected_contract"), dict) else {}
    if contract:
        return contract
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    options = evidence.get("options") if isinstance(evidence.get("options"), dict) else {}
    contract = options.get("contract") if isinstance(options.get("contract"), dict) else {}
    return contract


def short_row(item: dict[str, Any]) -> str:
    contract = selected_contract(item)
    parts = [
        str(item.get("ticker") or "?"),
        str(item.get("strategy") or "?"),
        str(item.get("final_state") or item.get("decision") or "?"),
        f"score={item.get('conviction_score', item.get('ranking_score', item.get('score', '?')))}",
    ]
    if contract:
        values = [
            contract.get(key)
            for key in ["strike", "expiration", "dte", "bid", "ask", "delta"]
            if contract.get(key) is not None
        ]
        if values:
            parts.append("contract=" + "/".join(str(value) for value in values))
    blocker = item.get("main_blocker")
    if blocker:
        parts.append(f"blocker={blocker}")
    return " | ".join(parts)


def section_rows(payload: dict[str, Any], *names: str) -> list[dict[str, Any]]:
    for name in names:
        rows = payload.get(name)
        if isinstance(rows, list):
            return rows
    return []


def print_section(title: str, rows: list[dict[str, Any]], preview: int) -> None:
    print(f"\n{title}: {len(rows)}")
    for item in rows[: max(0, preview)]:
        print(f"- {short_row(item)}")
    if len(rows) > preview:
        print(f"- ... {len(rows) - preview} mas")


def print_summary(payload: dict[str, Any], preview: int) -> None:
    readiness = payload.get("data_readiness") or {}
    summary = payload.get("summary") or {}
    guidance = payload.get("answer_guidance") or {}
    top = section_rows(payload, "top_recommendations", "top_manual_review")
    all_items = section_rows(payload, "items", "all_ranked")
    no_trade = section_rows(payload, "no_trade", "blocked")
    top_ids = {(item.get("ticker"), item.get("strategy"), item.get("final_state")) for item in top}
    no_trade_ids = {(item.get("ticker"), item.get("strategy"), item.get("final_state")) for item in no_trade}
    watchlist = [
        item for item in all_items
        if (item.get("ticker"), item.get("strategy"), item.get("final_state")) not in top_ids | no_trade_ids
    ] or section_rows(payload, "watchlist")

    print("\nStock Ultimus Daily Radar")
    print(f"Motor: {payload.get('engine')} | generado: {payload.get('generated_at')}")
    print(f"Estado: {readiness.get('status')} | operativo: {readiness.get('operational_readiness')}")
    print(f"Bloqueador principal: {readiness.get('main_blocker') or 'ninguno'}")
    print(f"Resumen: {summary}")
    print(
        "Datos: "
        f"opciones={readiness.get('option_rows_found')} | "
        f"tecnicos={readiness.get('technical_count')} | "
        f"wait_market={readiness.get('wait_market_like_count')}"
    )
    if guidance.get("lead_message"):
        print(f"Respuesta sugerida: {guidance.get('lead_message')}")

    print_section("Oportunidades para revision manual", top, preview)
    print_section("Watchlist", watchlist, preview)
    print_section("No trade / bloqueadas", no_trade, preview)

    next_actions = readiness.get("next_required_actions") or []
    if next_actions:
        print("\nSiguientes acciones:")
        for action in next_actions:
            print(f"- {action}")

    print("\nNota: esto no autoriza ordenes. ENTRY_READY significa revision manual.")


def main() -> int:
    args = parse_args()

    if not args.skip_bridge:
        ingest_token = secret_from_env_or_keychain(
            ["TRADING_ENGINE_INGEST_TOKEN", "SNAPSHOT_INGEST_TOKEN"],
            INGEST_KEYCHAIN_SERVICE,
        )
        if not ingest_token:
            print("Falta TRADING_ENGINE_INGEST_TOKEN o token Keychain de ingest.")
            return 10
        bridge_code = run_bridge(args, ingest_token)
        if bridge_code != 0 and not args.allow_partial:
            return bridge_code

    read_token = secret_from_env_or_keychain(
        ["READ_ACCESS_TOKEN", "STOCK_ULTIMUS_READ_TOKEN"],
        READ_KEYCHAIN_SERVICE,
    )
    if not read_token:
        print("Falta READ_ACCESS_TOKEN o token Keychain de lectura.")
        return 11

    try:
        payload = read_daily_rankings(args.public_base_url, read_token, args.read_timeout)
    except RuntimeError as exc:
        print(str(exc))
        return 12

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"Respuesta JSON guardada en {out_path}")

    print_summary(payload, args.preview)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
