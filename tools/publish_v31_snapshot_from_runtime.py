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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request, error

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime_local_technical
import broker_check


DEFAULT_REMOTE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_INGEST_PATH = "/v31_ingest_snapshot"
DEFAULT_MAX_AGE_MINUTES = 90


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
    return {
        "account_context_version": "local_runtime_active_account_context_v1",
        "account_scope": scope or "unknown",
        "account_alias": alias or "unknown",
        "selected_at": data.get("selected_at"),
        "selected_account_configured": bool(scope or alias),
        "real_account_id_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


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
        if not ticker:
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

        ticker = str(value.get("ticker") or value.get("symbol") or key or "").upper().strip()
        if not ticker:
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
    broker_enriched = broker_check.merge_broker_checks(
        {
            "account_scope": account_context.get("account_scope"),
            "account_alias": account_context.get("account_alias"),
            "account_context": account_context,
            "options_rows": options_rows,
            "runtime_data": runtime_data,
            **runtime_data,
        },
        rows=options_rows,
    )

    return {
        "source": "LOCAL_RUNTIME_V31_PUBLISHER",
        "generated_at": now_iso(),
        "account_scope": account_context.get("account_scope"),
        "account_alias": account_context.get("account_alias"),
        "account_context": json_safe(account_context),
        "options_rows": json_safe(options_rows),
        "technical_snapshot": json_safe(technical_snapshot),
        "broker_checks": json_safe(broker_enriched.get("broker_checks") or []),
        "broker_check_summary": json_safe(broker_enriched.get("broker_check_summary") or {}),
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish local runtime snapshot to V31 ingest.")
    parser.add_argument("--runtime-dir", default="runtime", help="Runtime directory to scan.")
    parser.add_argument("--remote-url", default=os.environ.get("TRADING_ENGINE_REMOTE_URL", DEFAULT_REMOTE_URL))
    parser.add_argument("--ingest-path", default=os.environ.get("TRADING_ENGINE_INGEST_PATH", DEFAULT_INGEST_PATH))
    parser.add_argument("--publish", action="store_true", help="POST snapshot to remote V31 ingest.")
    parser.add_argument("--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES)
    parser.add_argument("--allow-stale", action="store_true", help="Allow publish even if runtime files are stale.")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    ingest_path = args.ingest_path if args.ingest_path.startswith("/") else f"/{args.ingest_path}"
    url = args.remote_url.rstrip("/") + ingest_path
    runtime_dir = Path(args.runtime_dir)
    freshness = runtime_freshness(runtime_dir)
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
        result["publish_result"] = post_json(url, payload, args.timeout)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if (not args.publish or result.get("publish_result", {}).get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
