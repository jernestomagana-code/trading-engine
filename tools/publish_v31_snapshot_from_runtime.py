#!/usr/bin/env python3
"""
Build a V31-compatible master snapshot from local runtime JSON files.

Default mode is dry-run. Use --publish to POST to Render.
This utility does not import ibkr_bridge.py and never connects to IBKR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request, error

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime_local_technical
import broker_check
import gamma_context_store
import position_management
import position_context_store


DEFAULT_REMOTE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_INGEST_PATH = "/v31_ingest_snapshot"
DEFAULT_MAX_AGE_MINUTES = 90
DEFAULT_PUBLISH_TIMEOUT_SECONDS = int(os.getenv("TRADING_ENGINE_PUBLISH_TIMEOUT_SECONDS", "45"))
DEFAULT_PUBLISH_RETRIES = max(1, int(os.getenv("TRADING_ENGINE_PUBLISH_RETRIES", "3")))
DEFAULT_PUBLISH_RETRY_SLEEP_SECONDS = float(os.getenv("TRADING_ENGINE_PUBLISH_RETRY_SLEEP_SECONDS", "3"))
PUBLISH_DATA_FILES = (
    "decision_desk_snapshot.json",
    "v32_ibkr_chain_coverage.json",
    "active_position_option_chains_latest.json",
    "active_position_technical_latest.json",
    "stock_ultimus_console_bridge_latest.json",
    "market_bridge_session_latest.json",
    "daily_radar_latest.json",
    "canslim_candidates_latest.json",
    "technical_snapshot_by_ticker_safe.json",
    "technical_snapshot_by_ticker.json",
    "v26_local_master_snapshot.json",
    "v28_master_snapshot.json",
    "v25_master_snapshot.json",
    "ibkr_account_capacity_latest.json",
    "gamma_contexts.json",
    "active_position_contexts.json",
)
RESERVED_NON_TICKERS = {
    "CANSLIM",
    "CONTROL_PANEL",
    "GATE",
    "MARKET",
    "OPTIONS",
    "POST_MORTEM",
    "RAW",
    "SCORE_CALIBRATION",
    "TECHNICAL",
    "TOP",
}
MARKET_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{0,8}(?:[.!-][A-Z0-9]{1,4})?!?$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def active_account_context(runtime_dir: Path) -> dict[str, Any]:
    path = runtime_dir / "ibkr_account_active_profile.json"
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    scope = data.get("account_scope") or ""
    alias = data.get("account_alias") or scope
    context = {
        "account_context_version": "local_runtime_active_account_context_v1",
        "account_scope": scope or "unknown",
        "account_alias": alias or "unknown",
        "selected_at": data.get("selected_at"),
        "selected_account_configured": bool(scope or alias),
        "real_account_id_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    capacity_path = runtime_dir / "ibkr_account_capacity_latest.json"
    try:
        capacity = json.loads(capacity_path.read_text())
    except Exception:
        capacity = {}
    if isinstance(capacity, dict):
        cap_scope = capacity.get("account_scope")
        cap_alias = capacity.get("account_alias")
        if not cap_scope or cap_scope == context.get("account_scope") or cap_alias == context.get("account_alias"):
            for key in [
                "available",
                "currency",
                "net_liquidation",
                "buying_power",
                "available_funds",
                "excess_liquidity",
                "available_capacity",
                "total_cash_value",
                "initial_margin_required",
                "maintenance_margin_required",
                "gross_position_value",
                "cushion",
                "generated_at",
                "source",
                "sensitive_identifiers_excluded",
            ]:
                if capacity.get(key) is not None:
                    context[key] = capacity.get(key)
            context["account_context_version"] = "local_runtime_account_context_with_capacity_v1"
            context["capacity_source_file"] = str(capacity_path)
    return context


def json_safe(obj: Any) -> Any:
    try:
        json.dumps(obj)
        return obj
    except Exception:
        if isinstance(obj, dict):
            return {str(k): json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [json_safe(x) for x in obj]
        try:
            return float(obj)
        except Exception:
            return str(obj)


def load_runtime_json(runtime_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not runtime_dir.exists():
        return out

    for path in sorted(runtime_dir.glob("*.json")):
        try:
            out[path.name] = json.loads(path.read_text())
        except Exception as exc:
            out[path.name] = {"_load_error": str(exc)}
    return out


def runtime_freshness(runtime_dir: Path) -> dict[str, Any]:
    files = [p for p in runtime_dir.glob("*.json")] if runtime_dir.exists() else []
    if not files:
        return {
            "newest_file": None,
            "newest_mtime": None,
            "age_minutes": None,
            "file_count": 0,
        }

    newest = max(files, key=lambda p: p.stat().st_mtime)
    newest_dt = datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - newest_dt).total_seconds() / 60
    return {
        "newest_file": str(newest),
        "newest_mtime": newest_dt.isoformat(),
        "age_minutes": round(age_minutes, 2),
        "file_count": len(files),
    }


def publish_data_freshness(runtime_dir: Path) -> dict[str, Any]:
    """Freshness of market/account inputs, excluding monitor and notification state."""
    files = [runtime_dir / name for name in PUBLISH_DATA_FILES if (runtime_dir / name).exists()]
    if not files:
        return {
            "newest_file": None,
            "newest_mtime": None,
            "age_minutes": None,
            "file_count": 0,
            "considered_files": [],
        }
    newest = max(files, key=lambda path: path.stat().st_mtime)
    newest_dt = datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - newest_dt).total_seconds() / 60
    return {
        "newest_file": str(newest),
        "newest_mtime": newest_dt.isoformat(),
        "age_minutes": round(age_minutes, 2),
        "file_count": len(files),
        "considered_files": [path.name for path in files],
    }


def valid_market_symbol(value: Any) -> bool:
    symbol = str(value or "").upper().strip()
    return bool(symbol and symbol not in RESERVED_NON_TICKERS and MARKET_SYMBOL_RE.fullmatch(symbol))


def extract_options_rows(runtime_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    execution_fields = [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
    ]

    def completeness_score(row: dict[str, Any]) -> tuple[int, float]:
        complete = sum(
            1
            for field in execution_fields
            if row.get(field) not in [None, "", "None"]
        )
        try:
            score = float(row.get("score") or 0)
        except Exception:
            score = 0.0
        return complete, score

    def add_from(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    rows.append(dict(item))
            return

        if not isinstance(obj, dict):
            return

        for key in ["options_rows", "rows", "top", "top_5", "sample_rows", "best_rows"]:
            value = obj.get(key)
            if isinstance(value, list):
                add_from(value)

        options = obj.get("options")
        if isinstance(options, dict):
            add_from(options)

        for key in ["best_row", "best", "next_best_action"]:
            value = obj.get(key)
            if isinstance(value, dict):
                rows.append(dict(value))

    for data in runtime_data.values():
        add_from(data)

    best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not valid_market_symbol(ticker):
            continue

        row["ticker"] = ticker
        row["strategy"] = str(row.get("strategy") or row.get("strategy_hint") or row.get("best_strategy") or "UNKNOWN").upper()
        row["decision"] = str(row.get("decision") or row.get("final_decision") or row.get("state") or "RADAR").upper()
        row["score"] = row.get("score") or row.get("combined_score") or row.get("master_score") or row.get("options_score")
        row["price"] = row.get("price") or row.get("premium") or row.get("option_price") or row.get("mid")
        row["data_quality"] = row.get("data_quality") or row.get("quality") or "UNKNOWN"

        row["expiration"] = row.get("expiration") or row.get("expiry") or row.get("exp")

        key = (str(row.get("ticker")), str(row.get("strategy")), str(row.get("decision")))
        current = best_by_key.get(key)
        if current is None or completeness_score(row) > completeness_score(current):
            best_by_key[key] = row

    return sorted(
        best_by_key.values(),
        key=lambda row: completeness_score(row),
        reverse=True,
    )


def extract_technical_snapshot(runtime_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    technical: dict[str, dict[str, Any]] = {}

    def add_candidate(key: Any, value: Any) -> None:
        if not isinstance(value, dict):
            return

        explicit_ticker = value.get("ticker") or value.get("symbol")
        ticker = str(explicit_ticker or key or "").upper().strip()
        if not valid_market_symbol(ticker):
            return

        looks_technical = any(
            field in value
            for field in [
                "trend",
                "bias",
                "technical_bias",
                "rsi",
                "adx",
                "vwap_position",
                "volume_relative",
                "support_near",
                "resistance_near",
                "range_breakout",
                "score",
                "technical_score",
            ]
        )
        if looks_technical:
            item = dict(value)
            item["ticker"] = ticker
            technical[ticker] = item

    def walk(obj: Any, forced_key: Any = None) -> None:
        if isinstance(obj, dict):
            if forced_key is not None:
                add_candidate(forced_key, obj)
            for key, value in obj.items():
                if isinstance(value, dict):
                    add_candidate(key, value)
                    walk(value, key)
                elif isinstance(value, list):
                    walk(value, key)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, forced_key)

    for data in runtime_data.values():
        walk(data)

    return technical


def build_payload(runtime_dir: Path) -> dict[str, Any]:
    runtime_data = load_runtime_json(runtime_dir)
    account_context = active_account_context(runtime_dir)
    options_rows = extract_options_rows(runtime_data)
    technical_snapshot = extract_technical_snapshot(runtime_data)
    technical_snapshot = runtime_local_technical.merge_local_technical_snapshot(
        technical_snapshot,
        runtime_data,
        options_rows=options_rows,
        timeframe="1d",
    )
    technical_snapshot = {
        str(ticker).upper().strip(): value
        for ticker, value in technical_snapshot.items()
        if valid_market_symbol(ticker) and isinstance(value, dict)
    }
    broker_context = {
        "account_scope": account_context.get("account_scope"),
        "account_alias": account_context.get("account_alias"),
        "account_context": account_context,
        "options_rows": options_rows,
        "technical_snapshot": technical_snapshot,
        "runtime_data": runtime_data,
        **runtime_data,
    }
    active_position_contexts = runtime_data.get("active_position_contexts.json") or position_context_store.load_contexts(runtime_dir / "active_position_contexts.json")
    broker_context["active_position_contexts"] = active_position_contexts
    gamma_contexts = runtime_data.get("gamma_contexts.json") or gamma_context_store.load_contexts(runtime_dir / "gamma_contexts.json")
    broker_context["gamma_contexts"] = gamma_contexts
    positions = broker_check.extract_positions(broker_context)
    broker_context["positions"] = positions
    broker_enriched = broker_check.merge_broker_checks(broker_context, rows=options_rows)
    active_position_management = position_management.build_active_position_management(broker_context)

    return {
        "source": "LOCAL_RUNTIME_V31_PUBLISHER",
        "generated_at": now_iso(),
        "account_scope": account_context.get("account_scope"),
        "account_alias": account_context.get("account_alias"),
        "account_context": json_safe(account_context),
        "coberturas_rsp_manual_context": json_safe(
            runtime_data.get("coberturas_rsp_manual_context.json") or {}
        ),
        "positions": json_safe(positions),
        "active_position_contexts": json_safe(active_position_contexts),
        "gamma_contexts": json_safe(gamma_contexts),
        "options_rows": json_safe(options_rows),
        "technical_snapshot": json_safe(technical_snapshot),
        "broker_checks": json_safe(broker_enriched.get("broker_checks") or []),
        "broker_check_summary": json_safe(broker_enriched.get("broker_check_summary") or {}),
        "active_position_management": json_safe(active_position_management),
        "market": {
            "status": "MANUAL_RUNTIME_PUBLISH",
            "label": "Runtime snapshot publisher; validate market state manually.",
            "is_regular_market_open": False,
            "options_bidask_expected": False,
            "source": "LOCAL_RUNTIME_V31_PUBLISHER",
            "generated_at": now_iso(),
        },
        "runtime_files_seen": sorted(runtime_data.keys()),
        "bridge_status": "PUBLISHED_FROM_LOCAL_RUNTIME_WITHOUT_IBKR_CONNECTION",
        "not_order_instruction": True,
    }


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, default=str).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    ingest_token = os.getenv("TRADING_ENGINE_INGEST_TOKEN", "")
    if ingest_token:
        headers["X-Snapshot-Ingest-Token"] = ingest_token
    req = request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= resp.status < 300,
                "status_code": resp.status,
                "url": url,
                "text": text[:1000],
            }
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status_code": exc.code, "url": url, "text": text[:1000]}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def post_json_with_retries(
    url: str,
    payload: dict[str, Any],
    timeout: int,
    retries: int,
    retry_sleep: float,
) -> dict[str, Any]:
    attempts = []
    final: dict[str, Any] = {"ok": False, "url": url, "error": "not_attempted"}
    for attempt in range(1, max(1, retries) + 1):
        result = post_json(url, payload, timeout)
        result["attempt"] = attempt
        result["max_attempts"] = max(1, retries)
        attempts.append(result)
        final = dict(result)
        if result.get("ok"):
            break
        if attempt < max(1, retries):
            time.sleep(max(0.0, retry_sleep))
    final["attempts"] = attempts
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish local runtime snapshot to V31 ingest.")
    parser.add_argument("--runtime-dir", default="runtime", help="Runtime directory to scan.")
    parser.add_argument("--remote-url", default=os.environ.get("TRADING_ENGINE_REMOTE_URL", DEFAULT_REMOTE_URL))
    parser.add_argument("--ingest-path", default=os.environ.get("TRADING_ENGINE_INGEST_PATH", DEFAULT_INGEST_PATH))
    parser.add_argument("--publish", action="store_true", help="POST snapshot to remote V31 ingest.")
    parser.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    parser.add_argument("--allow-stale", action="store_true", help="Allow publish even if runtime files are stale.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_PUBLISH_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=DEFAULT_PUBLISH_RETRIES)
    parser.add_argument("--retry-sleep", type=float, default=DEFAULT_PUBLISH_RETRY_SLEEP_SECONDS)
    args = parser.parse_args()

    ingest_path = args.ingest_path if args.ingest_path.startswith("/") else f"/{args.ingest_path}"
    url = args.remote_url.rstrip("/") + ingest_path
    runtime_dir = Path(args.runtime_dir)
    freshness = publish_data_freshness(runtime_dir)
    payload = build_payload(runtime_dir)
    age = freshness.get("age_minutes")
    stale = bool(age is None or age > args.max_age_minutes)

    result = {
        "mode": "publish" if args.publish else "dry_run",
        "target": url,
        "runtime_dir": args.runtime_dir,
        "freshness": freshness,
        "max_age_minutes": args.max_age_minutes,
        "stale": stale,
        "runtime_files_seen": payload["runtime_files_seen"],
        "rows_found": len(payload["options_rows"]),
        "technical_count": len(payload["technical_snapshot"]),
        "tickers_detected": sorted(
            set(
                [str(r.get("ticker")).upper() for r in payload["options_rows"] if isinstance(r, dict) and r.get("ticker")]
                + [str(t).upper() for t in payload["technical_snapshot"].keys()]
            )
        ),
        "not_order_instruction": True,
    }

    if args.publish:
        if stale and not args.allow_stale:
            result["publish_result"] = {
                "ok": False,
                "blocked": "STALE_RUNTIME_SNAPSHOT",
                "message": "Refusing to publish stale or missing runtime files. Use --allow-stale only for explicit historical testing.",
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 2
        result["publish_result"] = post_json_with_retries(
            url,
            payload,
            args.timeout,
            args.retries,
            args.retry_sleep,
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if (not args.publish or result.get("publish_result", {}).get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
