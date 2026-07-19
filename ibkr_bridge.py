from ib_insync import *
import requests
import time
import math
import logging
import signal
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import nest_asyncio
import sys
from pathlib import Path

import runtime_local_technical
import broker_check
import ibkr_diagnostics
import position_management


# === V26 REMOTE MASTER SNAPSHOT PUBLISHER ===
import json as _v26_json
import urllib.request as _v26_urllib_request
import urllib.error as _v26_urllib_error
from datetime import datetime as _v26_datetime, timezone as _v26_timezone
from pathlib import Path as _v26_Path

# ============================================================
# V28.3 OFFICIAL PUBLISHER HOOKED AFTER V26
# ============================================================

from pathlib import Path as _v283_Path
from datetime import datetime as _v283_datetime, timezone as _v283_timezone
import os as _v283_os
import json as _v283_json
import re as _v283_re

try:
    from strategy_rules import (
        OPTION_SPREAD_PCT_READY_MAX,
        OPTION_SPREAD_PCT_RADAR_MAX,
        NAKED_PUT_READY_DTE_MIN,
        NAKED_PUT_READY_DTE_MAX,
        NAKED_PUT_REVIEW_DTE_MIN,
        NAKED_PUT_REVIEW_DTE_MAX,
        NAKED_PUT_READY_DELTA_MIN,
        NAKED_PUT_READY_DELTA_MAX,
        NAKED_PUT_REVIEW_DELTA_MIN,
        NAKED_PUT_REVIEW_DELTA_MAX,
        COVERED_CALL_READY_DELTA_MIN,
        COVERED_CALL_READY_DELTA_MAX,
        COVERED_CALL_REVIEW_DELTA_MIN,
        COVERED_CALL_REVIEW_DELTA_MAX,
    )
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from strategy_rules import (
        OPTION_SPREAD_PCT_READY_MAX,
        OPTION_SPREAD_PCT_RADAR_MAX,
        NAKED_PUT_READY_DTE_MIN,
        NAKED_PUT_READY_DTE_MAX,
        NAKED_PUT_REVIEW_DTE_MIN,
        NAKED_PUT_REVIEW_DTE_MAX,
        NAKED_PUT_READY_DELTA_MIN,
        NAKED_PUT_READY_DELTA_MAX,
        NAKED_PUT_REVIEW_DELTA_MIN,
        NAKED_PUT_REVIEW_DELTA_MAX,
        COVERED_CALL_READY_DELTA_MIN,
        COVERED_CALL_READY_DELTA_MAX,
        COVERED_CALL_REVIEW_DELTA_MIN,
        COVERED_CALL_REVIEW_DELTA_MAX,
    )

try:
    import requests as _v283_requests
except Exception:
    _v283_requests = None

_V283_REMOTE_BASE_URL = _v283_os.environ.get(
    "TRADING_ENGINE_REMOTE_URL",
    "https://trading-engine-p097.onrender.com"
).rstrip("/")

_V283_REMOTE_INGEST_PATH = _v283_os.environ.get(
    "TRADING_ENGINE_INGEST_PATH",
    "/v31_ingest_snapshot"
)
if not _V283_REMOTE_INGEST_PATH.startswith("/"):
    _V283_REMOTE_INGEST_PATH = "/" + _V283_REMOTE_INGEST_PATH

_V283_INGEST_URL = _V283_REMOTE_BASE_URL + _V283_REMOTE_INGEST_PATH
_V283_INGEST_TOKEN = _v283_os.environ.get("TRADING_ENGINE_INGEST_TOKEN", "")
_V283_PUBLISH_TIMEOUT_SECONDS = float(_v283_os.environ.get("TRADING_ENGINE_PUBLISH_TIMEOUT_SECONDS", "45"))
_V283_PUBLISH_RETRIES = max(1, int(_v283_os.environ.get("TRADING_ENGINE_PUBLISH_RETRIES", "3")))
_V283_PUBLISH_RETRY_SLEEP_SECONDS = float(_v283_os.environ.get("TRADING_ENGINE_PUBLISH_RETRY_SLEEP_SECONDS", "3"))

def _v283_now():
    return _v283_datetime.now(_v283_timezone.utc).isoformat()

def _v283_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _v283_load_runtime_jsons():
    runtime = _v283_Path("runtime")
    out = {}
    if not runtime.exists():
        return out

    for p in runtime.glob("*.json"):
        try:
            out[p.name] = _v283_json.loads(p.read_text())
        except Exception:
            pass
    return out

def _v283_extract_options_rows(data):
    rows = []
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

    def completeness_score(row):
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

    def scan(obj):
        if isinstance(obj, dict):
            # Detectar filas de opciones
            ticker = str(obj.get("ticker") or obj.get("symbol") or "").upper().strip()
            strategy = obj.get("strategy") or obj.get("strategy_hint") or obj.get("best_strategy")
            decision = obj.get("decision") or obj.get("final_decision") or obj.get("state")
            quality = obj.get("data_quality") or obj.get("quality")

            if ticker and (strategy or decision or quality or obj.get("can_operate") is not None):
                r = dict(obj)
                r["ticker"] = ticker
                r["strategy"] = str(strategy or "UNKNOWN").upper()
                r["decision"] = str(decision or "RADAR").upper()
                r["score"] = _v283_float(
                    r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"),
                    0
                )
                r["price"] = _v283_float(
                    r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"),
                    None
                )
                r["data_quality"] = quality or "UNKNOWN"
                r["manual_review_ready"] = bool(r.get("manual_review_ready")) or r["decision"] in ["ENTRY", "ENTRY_READY", "OPERAR"]
                r["can_operate"] = False
                r["not_order_instruction"] = True
                rows.append(r)

            for key in [
                "options_rows",
                "rows",
                "top",
                "top_5",
                "sample_rows",
                "best_rows",
                "entry_candidates",
                "radar_candidates"
            ]:
                v = obj.get(key)
                if isinstance(v, list):
                    for x in v:
                        if isinstance(x, dict):
                            rows.append(dict(x))

            for v in obj.values():
                if isinstance(v, (dict, list)):
                    scan(v)

        elif isinstance(obj, list):
            for x in obj:
                scan(x)

    for v in data.values():
        scan(v)

    best_by_key = {}

    for r in rows:
        ticker = str(r.get("ticker") or r.get("symbol") or "").upper().strip()
        if not ticker:
            continue

        strategy = str(r.get("strategy") or r.get("strategy_hint") or "UNKNOWN").upper()
        decision = str(r.get("decision") or r.get("final_decision") or "RADAR").upper()

        r["ticker"] = ticker
        r["strategy"] = strategy
        r["decision"] = decision
        r["score"] = _v283_float(r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"), 0)
        r["price"] = _v283_float(r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"), None)
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"
        r["expiration"] = r.get("expiration") or r.get("expiry") or r.get("exp")

        r["manual_review_ready"] = bool(r.get("manual_review_ready")) or decision in ["ENTRY", "ENTRY_READY", "OPERAR"]
        r["can_operate"] = False
        r["not_order_instruction"] = True

        key = (ticker, strategy, decision)

        current = best_by_key.get(key)
        if current is None or completeness_score(r) > completeness_score(current):
            best_by_key[key] = r

    return sorted(best_by_key.values(), key=completeness_score, reverse=True)

def _v283_extract_technical(data):
    tech = {}

    def scan(obj, parent_key=None):
        if isinstance(obj, dict):
            ticker = str(obj.get("ticker") or obj.get("symbol") or parent_key or "").upper().strip()

            looks_technical = any(k in obj for k in [
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
                "event_risk",
                "technical_score",
                "score"
            ])

            if ticker and looks_technical:
                item = dict(obj)
                item["ticker"] = ticker
                item["trend"] = str(
                    item.get("trend") or item.get("bias") or item.get("technical_bias") or "UNKNOWN"
                ).upper()
                item["score"] = _v283_float(item.get("technical_score") or item.get("score"), None)
                tech[ticker] = item

            for k, v in obj.items():
                if isinstance(v, dict):
                    scan(v, k)
                elif isinstance(v, list):
                    scan(v, None)

        elif isinstance(obj, list):
            for x in obj:
                scan(x, parent_key)

    for v in data.values():
        scan(v)

    return tech

def _bridge_cycle_position_rows():
    rows = []
    account_scope = BRIDGE_ACCOUNT_SCOPE
    try:
        for item in V17_SUMMARY_ROWS:
            if not isinstance(item, dict):
                continue
            if item.get("account_scope") not in [None, "", account_scope]:
                continue
            if (
                item.get("asset_class") == "POSITION"
                or item.get("engine_layer") == "IBKR_PORTFOLIO_COMMANDER"
                or item.get("position_size") is not None
            ):
                rows.append(dict(item))
    except Exception:
        pass
    return rows

def _bridge_account_context_snapshot():
    """Read non-sensitive IBKR account capacity fields for broker checks."""
    selection = _bridge_account_selection()
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
        "account_context_version": "ibkr_account_context_v1",
        "source": "IBKR_ACCOUNT_SUMMARY_SANITIZED",
        "generated_at": _v283_now(),
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
        "not_order_instruction": True,
        **_bridge_public_account_selection(selection),
    }
    selected = selection.get("selected") or ""
    if selection.get("selection_required"):
        context["error"] = "ACCOUNT_SELECTION_REQUIRED"
        context["next_required_action"] = "Set IBKR_ACCOUNT_ALIAS with IBKR_ACCOUNT_MAP, or set IBKR_ACCOUNT_ID locally before running ibkr_bridge.py."
        return context
    if selected and not selection.get("selected_found"):
        context["error"] = "SELECTED_ACCOUNT_NOT_AVAILABLE"
        context["next_required_action"] = "Confirm the selected IBKR account is visible in TWS/IB Gateway managed accounts."
        return context
    try:
        try:
            summary = ib.accountSummary(account=selected) if selected else ib.accountSummary()
        except TypeError:
            summary = ib.accountSummary()
    except Exception as exc:
        context["error"] = str(exc)[:160]
        return context

    preferred = []
    fallback = []
    for item in summary or []:
        if selected and str(getattr(item, "account", "") or "").strip() not in ["", selected]:
            continue
        tag = getattr(item, "tag", None)
        mapped = fields.get(tag)
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
        parsed = safe_round(value, 4)
        if parsed is None:
            continue
        context[mapped] = parsed
        if not context.get("currency") and currency:
            context["currency"] = currency

    context["available_capacity"] = (
        context.get("available_funds")
        if context.get("available_funds") is not None
        else context.get("buying_power")
        if context.get("buying_power") is not None
        else context.get("excess_liquidity")
    )
    context["available"] = any(
        context.get(key) is not None
        for key in [
            "net_liquidation",
            "buying_power",
            "available_funds",
            "excess_liquidity",
            "total_cash_value",
        ]
    )
    return context

def _bridge_broker_snapshot_context(options_rows, runtime_data=None, technical_snapshot=None):
    runtime_data = runtime_data if isinstance(runtime_data, dict) else {}
    account_context = _bridge_account_context_snapshot()
    positions = _bridge_cycle_position_rows()
    return {
        "account_scope": BRIDGE_ACCOUNT_SCOPE,
        "account_alias": BRIDGE_ACCOUNT_ALIAS,
        "options_rows": options_rows if isinstance(options_rows, list) else [],
        "technical_snapshot": technical_snapshot if isinstance(technical_snapshot, dict) else {},
        "account_context": account_context,
        "positions": positions,
        "runtime_data": runtime_data,
        **runtime_data,
    }

def _v283_publish_to_v28():
    if _v283_requests is None:
        print("V28.3 OFFICIAL V28 PUBLISH SKIPPED | requests unavailable")
        return

    runtime_data = _v283_load_runtime_jsons()
    rows = _v283_extract_options_rows(runtime_data)
    tech = _v283_extract_technical(runtime_data)
    tech = runtime_local_technical.merge_local_technical_snapshot(
        tech,
        runtime_data,
        options_rows=rows,
        timeframe="1d",
    )
    broker_context = _bridge_broker_snapshot_context(rows, runtime_data, tech)
    broker_enriched = broker_check.merge_broker_checks(broker_context, rows=rows)
    active_position_management = position_management.build_active_position_management(broker_context)

    payload = {
        "source": "IBKR_BRIDGE_V28_3_OFFICIAL_AFTER_V26_V31_TARGET",
        "generated_at": _v283_now(),
        "account_scope": broker_context.get("account_scope") or BRIDGE_ACCOUNT_SCOPE,
        "account_alias": broker_context.get("account_alias") or BRIDGE_ACCOUNT_ALIAS,
        "options_rows": rows,
        "technical_snapshot": tech,
        "account_context": broker_context.get("account_context") or {},
        "positions": broker_context.get("positions") or [],
        "broker_checks": broker_enriched.get("broker_checks") or [],
        "broker_check_summary": broker_enriched.get("broker_check_summary") or {},
        "active_position_management": active_position_management,
        "market": bridge_market_snapshot("IBKR_BRIDGE_V28_3_OFFICIAL_AFTER_V26_V31_TARGET"),
        "bridge_status": "LIVE_IBKR_AFTER_V26_PUBLISH",
        "runtime_files_seen": sorted(list(runtime_data.keys())),
        "not_order_instruction": True,
    }

    last_error = ""
    for attempt in range(1, _V283_PUBLISH_RETRIES + 1):
        try:
            headers = {}
            if _V283_INGEST_TOKEN:
                headers["X-Snapshot-Ingest-Token"] = _V283_INGEST_TOKEN
            resp = _v283_requests.post(
                _V283_INGEST_URL,
                json=payload,
                headers=headers,
                timeout=_V283_PUBLISH_TIMEOUT_SECONDS,
            )
            ok = 200 <= resp.status_code < 300
            print(
                "V28.3 OFFICIAL V31 SNAPSHOT PUBLISHED"
                f" | ok:{ok}"
                f" | status:{resp.status_code}"
                f" | rows:{len(rows)}"
                f" | technical:{len(tech)}"
                f" | attempt:{attempt}/{_V283_PUBLISH_RETRIES}"
                f" | url:{_V283_INGEST_URL}"
            )
            return {"ok": ok, "status_code": resp.status_code, "attempt": attempt, "url": _V283_INGEST_URL}
        except Exception as e:
            last_error = str(e)
            print(
                "V28.3 OFFICIAL V31 SNAPSHOT RETRY"
                f" | attempt:{attempt}/{_V283_PUBLISH_RETRIES}"
                f" | error:{last_error}"
            )
            if attempt < _V283_PUBLISH_RETRIES:
                time.sleep(_V283_PUBLISH_RETRY_SLEEP_SECONDS)
    print(f"V28.3 OFFICIAL V31 SNAPSHOT ERROR | {last_error}")
    return {"ok": False, "error": last_error, "url": _V283_INGEST_URL}

# ============================================================
# END V28.3 OFFICIAL PUBLISHER HOOKED AFTER V26
# ============================================================


_V26_RENDER_INGEST_URL = "https://trading-engine-p097.onrender.com/v28_ingest_snapshot"
_V26_RUNTIME_DIR = _v26_Path("runtime")
_V26_RUNTIME_DIR.mkdir(exist_ok=True)
_V26_LOCAL_MASTER_SNAPSHOT = _V26_RUNTIME_DIR / "v26_local_master_snapshot.json"
_V26_LAST_REMOTE_RESULT = _V26_RUNTIME_DIR / "v26_last_remote_publish_result.json"


def _v26_now_iso():
    return _v26_datetime.now(_v26_timezone.utc).isoformat()


def _v26_safe_jsonable(obj):
    try:
        _v26_json.dumps(obj, default=str)
        return obj
    except Exception:
        return str(obj)


def _v26_load_json_file(path):
    try:
        p = _v26_Path(path)
        if p.exists():
            return _v26_json.loads(p.read_text())
    except Exception as e:
        return {"_load_error": str(e), "_path": str(path)}
    return None


def _v26_discover_runtime_context():
    """
    Discover existing runtime files generated by previous versions without assuming
    exact structure. This keeps V26 compatible with V18/V19/V22/V25 work.
    """
    files = {}
    candidates = [
        "runtime/technical_snapshot_by_ticker_safe.json",
        "runtime/technical_snapshot_by_ticker.json",
        "runtime/decision_desk_snapshot.json",
        "runtime/decision_snapshot.json",
        "runtime/v18_decision_snapshot.json",
        "runtime/v18_decision_desk_snapshot.json",
        "runtime/v22_2_unified_remote_snapshot.json",
        "runtime/v25_master_snapshot.json",
    ]

    for path in candidates:
        data = _v26_load_json_file(path)
        if data is not None:
            files[path] = data

    return files


def _v26_extract_options_rows_from_context(ctx):
    """
    Try to recover options rows from known snapshot formats.
    """
    rows = []
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

    def completeness_score(row):
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

    for _, data in ctx.items():
        if not isinstance(data, dict):
            continue

        for key in ["options_rows", "rows", "top", "top_5", "sample_rows"]:
            val = data.get(key)
            if isinstance(val, list):
                rows.extend([x for x in val if isinstance(x, dict)])

        summary = data.get("summary")
        if isinstance(summary, dict):
            for key in ["rows", "top", "top_5", "sample_rows"]:
                val = summary.get(key)
                if isinstance(val, list):
                    rows.extend([x for x in val if isinstance(x, dict)])

    best_by_key = {}
    for r in rows:
        ticker = str(r.get("ticker") or r.get("symbol") or "").upper().strip()
        if not ticker:
            continue
        strategy = str(r.get("strategy") or r.get("strategy_hint") or r.get("best_strategy") or "UNKNOWN").upper()
        decision = str(r.get("decision") or r.get("final_decision") or r.get("state") or "RADAR").upper()
        r["ticker"] = ticker
        r["strategy"] = strategy
        r["decision"] = decision
        r["expiration"] = r.get("expiration") or r.get("expiry") or r.get("exp")
        sig = (ticker, strategy, decision)
        current = best_by_key.get(sig)
        if current is None or completeness_score(r) > completeness_score(current):
            best_by_key[sig] = r

    return sorted(best_by_key.values(), key=completeness_score, reverse=True)


def _v26_extract_technical_snapshot_from_context(ctx):
    for _, data in ctx.items():
        if not isinstance(data, dict):
            continue

        # Direct safe technical file
        if data and all(isinstance(v, dict) for v in data.values()):
            tickers = [k for k in data.keys() if isinstance(k, str) and len(k) <= 8]
            if tickers:
                return data

        technical = data.get("technical")
        if isinstance(technical, dict):
            return technical

        snapshot = data.get("technical_snapshot")
        if isinstance(snapshot, dict):
            return snapshot

    return {}


def _v26_build_master_snapshot(extra_payload=None):
    """
    Build one master payload for Render.
    extra_payload can be passed by ibkr_bridge runtime if available.
    """
    ctx = _v26_discover_runtime_context()
    options_rows = _v26_extract_options_rows_from_context(ctx)
    technical_snapshot = _v26_extract_technical_snapshot_from_context(ctx)
    broker_context = _bridge_broker_snapshot_context(options_rows, ctx, technical_snapshot)
    broker_context["runtime_context"] = ctx
    broker_enriched = broker_check.merge_broker_checks(broker_context, rows=options_rows)
    active_position_management = position_management.build_active_position_management(broker_context)

    tickers = set()

    for r in options_rows:
        t = r.get("ticker")
        if t:
            tickers.add(str(t).upper())

    for t in technical_snapshot.keys():
        if isinstance(t, str):
            tickers.add(t.upper())

    if isinstance(extra_payload, dict):
        for key in ["tickers", "symbols", "watchlist"]:
            val = extra_payload.get(key)
            if isinstance(val, list):
                for t in val:
                    tickers.add(str(t).upper())

    master = {
        "source": "IBKR_BRIDGE_V26_REMOTE_MASTER_PUBLISHER",
        "generated_at": _v26_now_iso(),
        "account_scope": broker_context.get("account_scope") or BRIDGE_ACCOUNT_SCOPE,
        "account_alias": broker_context.get("account_alias") or BRIDGE_ACCOUNT_ALIAS,
        "extra_payload": _v26_safe_jsonable(extra_payload or {}),
        "runtime_context_files": list(ctx.keys()),
        "options_rows": options_rows,
        "technical_snapshot": technical_snapshot,
        "account_context": broker_context.get("account_context") or {},
        "positions": broker_context.get("positions") or [],
        "broker_checks": broker_enriched.get("broker_checks") or [],
        "broker_check_summary": broker_enriched.get("broker_check_summary") or {},
        "active_position_management": active_position_management,
        "tickers_detected": sorted(tickers),
        "diagnostics": {
            "options_rows_found": len(options_rows),
            "technical_available": bool(technical_snapshot),
            "technical_tickers": sorted([str(x).upper() for x in technical_snapshot.keys()]) if isinstance(technical_snapshot, dict) else [],
            "runtime_files_found": len(ctx),
        },
    }

    _V26_LOCAL_MASTER_SNAPSHOT.write_text(_v26_json.dumps(master, indent=2, default=str))
    return master


def _v26_publish_master_snapshot(extra_payload=None, timeout=6):
    """
    Publish master snapshot to Render. Never raises into main bridge loop.
    """
    result = {
        "engine": "V26_REMOTE_MASTER_SNAPSHOT_PUBLISHER",
        "generated_at": _v26_now_iso(),
        "target": _V26_RENDER_INGEST_URL,
        "status": "UNKNOWN",
    }

    try:
        master = _v26_build_master_snapshot(extra_payload=extra_payload)

        if (
            not master.get("options_rows")
            and not master.get("technical_snapshot")
            and not master.get("tickers_detected")
        ):
            result.update({
                "status": "SKIPPED_EMPTY",
                "reason": "No useful options/technical/ticker data found to publish.",
                "diagnostics": master.get("diagnostics", {}),
            })
            _V26_LAST_REMOTE_RESULT.write_text(_v26_json.dumps(result, indent=2, default=str))
            print("V26 publish skipped: empty master snapshot.")
            return result

        payload = _v26_json.dumps(master, default=str).encode("utf-8")
        req = _v26_urllib_request.Request(
            _V26_RENDER_INGEST_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with _v26_urllib_request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            result.update({
                "status": "OK",
                "http_status": resp.status,
                "response_preview": body[:800],
                "diagnostics": master.get("diagnostics", {}),
            })

        print(
            "V26 remote publish OK | "
            f"rows={master['diagnostics']['options_rows_found']} | "
            f"technical={master['diagnostics']['technical_available']} | "
            f"tickers={master.get('tickers_detected')}"
        )

    except Exception as e:
        result.update({
            "status": "ERROR",
            "error": str(e),
        })
        print(f"V26 remote publish ERROR: {e}")

    try:
        _V26_LAST_REMOTE_RESULT.write_text(_v26_json.dumps(result, indent=2, default=str))
    except Exception:
        pass

    return result


def _v26_print_remote_publish_status(extra_payload=None):
    return _v26_publish_master_snapshot(extra_payload=extra_payload)
# === END V26 REMOTE MASTER SNAPSHOT PUBLISHER ===


nest_asyncio.apply()

# ============================================================
# SUPER ENGINE BOLSA — IBKR BRIDGE V18_1_REMOTE_SNAPSHOT_INGEST
# IBKR ONLY + READY FOR TRADINGVIEW INTEGRATION
# Market + Portfolio + Options + Strategy Commander
# FULL FILE VERSION
# ============================================================

IB_HOST = _v283_os.environ.get("IBKR_HOST", "127.0.0.1")
IB_PORT = int(_v283_os.environ.get("IBKR_PORT", "7496"))
CLIENT_ID = int(_v283_os.environ.get("IBKR_CLIENT_ID", "42"))
IBKR_REQUEST_TIMEOUT_SECONDS = float(_v283_os.environ.get("IBKR_REQUEST_TIMEOUT_SECONDS", "8"))
ENGINE_POST_TIMEOUT_SECONDS = float(_v283_os.environ.get("IBKR_ENGINE_POST_TIMEOUT_SECONDS", "5"))
POSITION_REQUEST_TIMEOUT_SECONDS = float(_v283_os.environ.get("IBKR_POSITION_REQUEST_TIMEOUT_SECONDS", "12"))
STOCK_PRICE_SNAPSHOT_TIMEOUT_SECONDS = float(_v283_os.environ.get("IBKR_STOCK_PRICE_SNAPSHOT_TIMEOUT_SECONDS", "10"))
POSITION_PRICE_SNAPSHOT_TIMEOUT_SECONDS = float(_v283_os.environ.get("IBKR_POSITION_PRICE_SNAPSHOT_TIMEOUT_SECONDS", "6"))
OPTION_CONTRACT_MARKET_DATA_TIMEOUT_SECONDS = float(_v283_os.environ.get("IBKR_OPTION_CONTRACT_MARKET_DATA_TIMEOUT_SECONDS", "10"))

ENGINE_URL = "https://trading-engine-p097.onrender.com/webhook/ibkr"

def _env_bool(name, default=False):
    raw = _v283_os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    try:
        return int(_v283_os.environ.get(name, default))
    except Exception:
        return default


def _env_float(name, default):
    try:
        return float(_v283_os.environ.get(name, default))
    except Exception:
        return default


def _env_csv_list(name, default):
    raw = _v283_os.environ.get(name, "")
    if not raw.strip():
        return list(default)
    values = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return values or list(default)


IB_CONNECT_TIMEOUT_SECONDS = _env_float("IBKR_CONNECT_TIMEOUT_SECONDS", "20")
IB_CONNECT_RETRIES = _env_int("IBKR_CONNECT_RETRIES", "3")
IB_CONNECT_RETRY_SLEEP_SECONDS = _env_float("IBKR_CONNECT_RETRY_SLEEP_SECONDS", "3")


DAILY_RADAR_FAST = _env_bool("DAILY_RADAR_FAST", False)
COBERTURAS_RSP_WEEKLY = _env_bool("COBERTURAS_RSP_WEEKLY", False)

DEFAULT_WATCHLIST = [
    "QQQ", "SPY", "AAPL", "NVDA", "TSLA",
    "NFLX", "META", "AMZN", "MSFT", "GOOGL",
    "AVGO", "AMD", "COST", "CRM", "ORCL", "TLT", "RSP",
    "ADBE", "NOW", "PANW", "CRWD", "SNOW", "DDOG",
    "NET", "MDB", "SHOP", "UBER", "ABNB", "COIN",
    "HOOD", "PLTR", "APP", "TTD", "ROKU", "ZS",
    "TEAM", "WDAY", "INTU", "ISRG", "LRCX", "KLAC",
    "ASML", "ARM", "MU", "SMCI", "DELL", "VRT",
    "ANET", "MRVL", "MELI", "ELF", "CELH", "DECK",
    "LULU", "AXON", "HUBS", "DASH", "RBLX",
]

DEFAULT_OPTION_SYMBOLS = [
    "QQQ", "SPY", "AAPL", "NVDA", "TSLA",
    "NFLX", "META", "AMZN", "MSFT", "GOOGL",
    "AVGO", "AMD", "COST", "CRM", "ORCL", "TLT", "RSP",
    "ADBE", "NOW", "PANW", "CRWD", "SNOW", "DDOG",
    "NET", "MDB", "SHOP", "UBER", "ABNB", "COIN",
    "HOOD", "PLTR", "APP", "TTD", "ROKU", "ZS",
    "TEAM", "WDAY", "INTU", "ISRG", "LRCX", "KLAC",
    "ASML", "ARM", "MU", "SMCI", "DELL", "VRT",
    "ANET", "MRVL", "MELI", "ELF", "CELH", "DECK",
    "LULU", "AXON", "HUBS", "DASH", "RBLX",
]

FAST_WATCHLIST = list(DEFAULT_WATCHLIST)
FAST_OPTION_SYMBOLS = list(DEFAULT_OPTION_SYMBOLS)

WATCHLIST = _env_csv_list(
    "IBKR_WATCHLIST",
    ["RSP"] if COBERTURAS_RSP_WEEKLY else (FAST_WATCHLIST if DAILY_RADAR_FAST else DEFAULT_WATCHLIST),
)
OPTION_SYMBOLS = _env_csv_list(
    "IBKR_OPTION_SYMBOLS",
    ["RSP"] if COBERTURAS_RSP_WEEKLY else (FAST_OPTION_SYMBOLS if DAILY_RADAR_FAST else DEFAULT_OPTION_SYMBOLS),
)

LOOP_SECONDS = int(_v283_os.environ.get("IBKR_LOOP_SECONDS", "180"))

TARGET_DTE_MIN = _env_int("IBKR_TARGET_DTE_MIN", 7 if COBERTURAS_RSP_WEEKLY else 25)
TARGET_DTE_MAX = _env_int("IBKR_TARGET_DTE_MAX", 14 if COBERTURAS_RSP_WEEKLY else 65)
TARGET_DTE_IDEAL = _env_int("IBKR_TARGET_DTE_IDEAL", 8 if COBERTURAS_RSP_WEEKLY else 45)

MAX_OPTIONS_PER_SYMBOL = _env_int(
    "IBKR_MAX_OPTIONS_PER_SYMBOL",
    4 if COBERTURAS_RSP_WEEKLY else (2 if DAILY_RADAR_FAST else 8),
)
MAX_OPTION_SYMBOLS_PER_RUN = max(1, _env_int(
    "IBKR_MAX_OPTION_SYMBOLS_PER_RUN",
    1 if COBERTURAS_RSP_WEEKLY else (8 if DAILY_RADAR_FAST else 14),
))
MAX_TOTAL_OPTION_CONTRACTS_PER_RUN = max(1, _env_int(
    "IBKR_MAX_TOTAL_OPTION_CONTRACTS_PER_RUN",
    4 if COBERTURAS_RSP_WEEKLY else (16 if DAILY_RADAR_FAST else 64),
))
DYNAMIC_OPTION_UNIVERSE_ENABLED = _env_bool(
    "IBKR_DYNAMIC_OPTION_UNIVERSE_ENABLED",
    False if COBERTURAS_RSP_WEEKLY else True,
)
INCLUDE_RUNTIME_TECHNICAL_OPTION_CANDIDATES = _env_bool(
    "IBKR_INCLUDE_RUNTIME_TECHNICAL_OPTION_CANDIDATES",
    False if COBERTURAS_RSP_WEEKLY else True,
)
OPTION_CORE_SYMBOLS = _env_csv_list(
    "IBKR_OPTION_CORE_SYMBOLS",
    ["RSP"] if COBERTURAS_RSP_WEEKLY else ["QQQ", "SPY"],
)
OPTION_CONTEXT_ONLY_SYMBOLS = _env_csv_list(
    "IBKR_OPTION_CONTEXT_ONLY_SYMBOLS",
    ["TLT"],
)
OPTION_PRIORITY_SYMBOLS = _env_csv_list(
    "IBKR_OPTION_PRIORITY_SYMBOLS",
    [],
)
OPTION_MIN_UNDERLYING_SCORE = _env_float(
    "IBKR_OPTION_MIN_UNDERLYING_SCORE",
    30,
)
OPTION_TECHNICAL_TRIGGER_SCORE = _env_float(
    "IBKR_OPTION_TECHNICAL_TRIGGER_SCORE",
    65,
)
OPTION_CANSLIM_TRIGGER_SCORE = _env_float(
    "IBKR_OPTION_CANSLIM_TRIGGER_SCORE",
    70,
)

# 1 = live, 2 = frozen, 3 = delayed, 4 = delayed frozen
MARKET_DATA_TYPE = int(_v283_os.environ.get("IBKR_MARKET_DATA_TYPE", "1"))


def _env_int_sequence(name, default):
    raw = _v283_os.environ.get(name, "")
    values = []
    if raw.strip():
        for item in raw.split(","):
            try:
                value = int(item.strip())
            except Exception:
                continue
            if value not in values:
                values.append(value)
    if not values:
        values = list(default)
    return values


OPTION_MARKET_DATA_TYPE_SEQUENCE = _env_int_sequence(
    "IBKR_OPTION_MARKET_DATA_TYPE_SEQUENCE",
    [MARKET_DATA_TYPE, 2, 3, 4],
)

# ============================================================
# CONTROL FLAGS
# ============================================================

ENABLE_MARKET_DATA = True
ENABLE_PORTFOLIO_COMMANDER = True
ENABLE_OPTIONS_INTELLIGENCE = True

ENABLE_COVERED_CALLS = True
ENABLE_NAKED_PUTS = True

USE_STANDARD_OPTION_STRIKES = True
STANDARD_STRIKE_MULTIPLE = 5

SHOW_IBKR_CONTRACT_ERRORS = False


class BridgeStepTimeout(TimeoutError):
    pass


@contextmanager
def bridge_step_timeout(seconds, label):
    if not seconds or seconds <= 0:
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)

    def _raise_timeout(signum, frame):
        raise BridgeStepTimeout(f"{label} timed out after {seconds:.1f}s")

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer and previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])

# Espera para que IBKR entregue bid/ask/greeks en opciones
OPTION_MARKET_DATA_WAIT_SECONDS = float(
    _v283_os.environ.get(
        "IBKR_OPTION_MARKET_DATA_WAIT_SECONDS",
        "3" if DAILY_RADAR_FAST else "8",
    )
)
OPTION_SECOND_PASS_WAIT_SECONDS = float(
    _v283_os.environ.get(
        "IBKR_OPTION_SECOND_PASS_WAIT_SECONDS",
        "2" if DAILY_RADAR_FAST else "5",
    )
)
OPTION_SNAPSHOT_WAIT_SECONDS = float(
    _v283_os.environ.get(
        "IBKR_OPTION_SNAPSHOT_WAIT_SECONDS",
        "2" if DAILY_RADAR_FAST else "4",
    )
)

# Espera para fallback de market data en acciones
STOCK_MARKET_DATA_WAIT_SECONDS = float(
    _v283_os.environ.get(
        "IBKR_STOCK_MARKET_DATA_WAIT_SECONDS",
        "1" if DAILY_RADAR_FAST else "2",
    )
)
HISTORICAL_DATA_TIMEOUT_SECONDS = float(
    _v283_os.environ.get("IBKR_HISTORICAL_DATA_TIMEOUT_SECONDS", "4")
)
LOCAL_TECHNICAL_HISTORICAL_DURATION = _v283_os.environ.get(
    "IBKR_LOCAL_TECHNICAL_HISTORICAL_DURATION",
    "90 D",
)
LOCAL_TECHNICAL_MAX_BARS = int(
    _v283_os.environ.get("IBKR_LOCAL_TECHNICAL_MAX_BARS", "120")
)

# Mandamos opciones aunque estén incompletas, pero la decisión queda bloqueada.
SEND_OPTIONS_WITHOUT_GREEKS = True

# Control de liquidez / spread
# spread_pct is published as a percentage (e.g. 11.76), not a fraction.
MAX_ACCEPTABLE_SPREAD_PCT_FOR_OPERAR = OPTION_SPREAD_PCT_READY_MAX
MAX_ACCEPTABLE_SPREAD_PCT_FOR_RADAR = OPTION_SPREAD_PCT_RADAR_MAX

# Prima mínima para considerar una opción razonable
MIN_OPTION_MID_FOR_RADAR = 0.10
MIN_OPTION_MID_FOR_OPERAR = 0.20

if not SHOW_IBKR_CONTRACT_ERRORS:
    logging.getLogger("ib_insync.wrapper").setLevel(logging.CRITICAL)

ib = IB()
IBKR_CHAIN_DIAGNOSTIC_EVENTS = []


BRIDGE_ACCOUNT_SCOPE = (
    _v283_os.environ.get("STOCK_ULTIMUS_ACCOUNT_SCOPE")
    or _v283_os.environ.get("IBKR_ACCOUNT_ALIAS")
    or "default"
).strip() or "default"
BRIDGE_ACCOUNT_ALIAS = (
    _v283_os.environ.get("IBKR_ACCOUNT_ALIAS")
    or BRIDGE_ACCOUNT_SCOPE
).strip() or "default"


def _bridge_parse_account_map():
    raw = _v283_os.environ.get("IBKR_ACCOUNT_MAP", "").strip()
    if not raw:
        return {}
    try:
        parsed = _v283_json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in parsed.items() if str(k).strip() and str(v).strip()}


def _bridge_selected_ibkr_account():
    account_map = _bridge_parse_account_map()
    return (
        _v283_os.environ.get("IBKR_ACCOUNT_ID")
        or _v283_os.environ.get("IBKR_ACCOUNT")
        or account_map.get(BRIDGE_ACCOUNT_ALIAS)
        or account_map.get(BRIDGE_ACCOUNT_SCOPE)
        or ""
    ).strip()


def _bridge_managed_accounts():
    try:
        accounts = ib.managedAccounts()
    except Exception:
        return []
    return [str(item).strip() for item in accounts or [] if str(item).strip()]


def _bridge_account_selection():
    selected = _bridge_selected_ibkr_account()
    managed = _bridge_managed_accounts()
    multiple_accounts = len(managed) > 1
    selected_found = bool(selected) and (not managed or selected in managed)
    return {
        "account_scope": BRIDGE_ACCOUNT_SCOPE,
        "account_alias": BRIDGE_ACCOUNT_ALIAS,
        "selected": selected,
        "selected_configured": bool(selected),
        "selected_found": selected_found,
        "managed_count": len(managed),
        "selection_required": multiple_accounts and not selected,
    }


def _bridge_public_account_selection(selection=None):
    selection = selection if isinstance(selection, dict) else _bridge_account_selection()
    return {
        "account_scope": selection.get("account_scope") or "default",
        "account_alias": selection.get("account_alias") or "default",
        "selected_account_configured": bool(selection.get("selected_configured")),
        "selected_account_found": bool(selection.get("selected_found")),
        "managed_account_count": int(selection.get("managed_count") or 0),
        "account_selection_required": bool(selection.get("selection_required")),
        "sensitive_identifiers_excluded": True,
    }


def _bridge_health_path():
    return _v283_Path("runtime") / "ibkr_bridge_health_latest.json"


def _write_bridge_health(status, *, detail="", error="", attempt=None, connected=False):
    payload = {
        "engine": "IBKR_BRIDGE_HEALTH",
        "health_version": "ibkr_bridge_health_v1",
        "generated_at": now_iso(),
        "status": status,
        "connected": bool(connected),
        "host": IB_HOST,
        "port": IB_PORT,
        "client_id": CLIENT_ID,
        "account_scope": BRIDGE_ACCOUNT_SCOPE,
        "account_alias": BRIDGE_ACCOUNT_ALIAS,
        "attempt": attempt,
        "max_attempts": max(1, IB_CONNECT_RETRIES),
        "detail": str(detail or "")[:500],
        "error": str(error or "")[:500],
        "next_required_action": (
            "Abrir/desbloquear TWS o IB Gateway, confirmar API activa y reintentar el bridge."
            if status == "CONNECTION_FAILED" else
            "Continuar ciclo normal del bridge."
        ),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
        "secrets_printed": False,
    }
    try:
        path = _bridge_health_path()
        path.parent.mkdir(exist_ok=True)
        path.write_text(_v283_json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except Exception:
        pass
    return payload


def connect_ibkr_with_retries():
    attempts = max(1, IB_CONNECT_RETRIES)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            print(
                "Conectando a IBKR..."
                f" intento {attempt}/{attempts}"
                f" host:{IB_HOST} port:{IB_PORT} clientId:{CLIENT_ID}"
            )
            ib.connect(
                IB_HOST,
                IB_PORT,
                clientId=CLIENT_ID,
                timeout=IB_CONNECT_TIMEOUT_SECONDS,
                readonly=True,
            )
            _write_bridge_health(
                "CONNECTED",
                detail="IBKR conectado correctamente en modo readonly.",
                attempt=attempt,
                connected=True,
            )
            ib.RequestTimeout = IBKR_REQUEST_TIMEOUT_SECONDS
            print(f"IBKR conectado correctamente | request_timeout:{IBKR_REQUEST_TIMEOUT_SECONDS}s")
            return True
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            _write_bridge_health(
                "CONNECTION_RETRYING" if attempt < attempts else "CONNECTION_FAILED",
                detail="No se pudo conectar a IBKR/TWS en modo readonly.",
                error=last_error,
                attempt=attempt,
                connected=False,
            )
            print(f"ERROR conectando IBKR intento {attempt}/{attempts}: {last_error}")
            if ib.isConnected():
                try:
                    ib.disconnect()
                except Exception:
                    pass
            if attempt < attempts:
                time.sleep(max(0.5, IB_CONNECT_RETRY_SLEEP_SECONDS))
    print("IBKR bridge detenido: TWS/IB Gateway no respondio a la API.")
    print(f"Diagnostico local: {_bridge_health_path()}")
    return False


# ============================================================
# PRIMARY EXCHANGE MAP
# ============================================================

PRIMARY_EXCHANGE_MAP = {
    "AAPL": "NASDAQ",
    "NVDA": "NASDAQ",
    "TSLA": "NASDAQ",
    "NFLX": "NASDAQ",
    "META": "NASDAQ",
    "AMZN": "NASDAQ",
    "MSFT": "NASDAQ",
    "GOOGL": "NASDAQ",
    "AVGO": "NASDAQ",
    "AMD": "NASDAQ",
    "COST": "NASDAQ",
    "CRM": "NYSE",
    "ORCL": "NYSE",
    "QQQ": "NASDAQ",
    "SPY": "ARCA",
    "RSP": "ARCA",
    "TLT": "NASDAQ"
}

OPTION_UNDERLYING_TIER_SCORES = {
    "QQQ": 55,
    "SPY": 55,
    "TLT": 38,
    "AAPL": 34,
    "MSFT": 34,
    "NVDA": 34,
    "AMZN": 32,
    "META": 32,
    "GOOGL": 32,
    "TSLA": 30,
    "AVGO": 30,
    "AMD": 28,
    "COST": 28,
    "CRM": 24,
    "ORCL": 24,
    "NFLX": 22,
    "RSP": 38,
    "ADBE": 24,
    "NOW": 24,
    "PANW": 22,
    "CRWD": 22,
    "SNOW": 18,
    "DDOG": 18,
    "NET": 18,
    "MDB": 16,
    "SHOP": 20,
    "UBER": 22,
    "ABNB": 18,
    "COIN": 16,
    "HOOD": 14,
    "PLTR": 18,
    "APP": 14,
    "TTD": 16,
    "ROKU": 12,
    "ZS": 14,
    "TEAM": 16,
    "WDAY": 18,
    "INTU": 24,
    "ISRG": 22,
    "LRCX": 22,
    "KLAC": 22,
    "ASML": 22,
    "ARM": 18,
    "MU": 22,
    "SMCI": 14,
    "DELL": 20,
    "VRT": 16,
    "ANET": 22,
    "MRVL": 20,
    "MELI": 18,
    "ELF": 12,
    "CELH": 12,
    "DECK": 14,
    "LULU": 16,
    "AXON": 14,
    "HUBS": 14,
    "DASH": 18,
    "RBLX": 12,
}

TRADABLE_EQUITY_SYMBOL_RE = _v283_re.compile(r"^[A-Z][A-Z0-9]{0,4}$")
NON_OPTION_UNDERLYING_SYMBOLS = {
    "RAW",
    "GATE",
    "TOP",
    "TECHNICAL",
    "OPTIONS_ROWS",
    "POST_MORTEM",
    "CONTROL_PANEL",
    "OPTION_OPTIMIZER",
    "SCORE_CALIBRATION",
    "CANSLIM",
    "CANSLIM_CONFIDENCE",
    "CONTRACT_COMPLETENESS",
    "MARKET_CONFIRMATION",
    "INSTITUTIONAL_RANKING",
}


# ============================================================
# UTILITIES
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean(x, allow_negative=False):
    try:
        if x is None:
            return None

        x = float(x)

        if math.isnan(x) or math.isinf(x):
            return None

        if not allow_negative and x <= 0:
            return None

        return round(x, 4)

    except Exception:
        return None


def safe_round(x, digits=4):
    try:
        if x is None:
            return None

        x = float(x)

        if math.isnan(x) or math.isinf(x):
            return None

        return round(x, digits)

    except Exception:
        return None


def post(payload):
    try:
        response = requests.post(
            ENGINE_URL,
            json=payload,
            timeout=ENGINE_POST_TIMEOUT_SECONDS
        )

        return response.status_code

    except Exception as e:
        ticker = payload.get("ticker") if isinstance(payload, dict) else ""
        timeframe = payload.get("timeframe") if isinstance(payload, dict) else ""
        print(f"POST ERROR {ticker} {timeframe}:", e, flush=True)
        return None


def set_market_data_type():
    try:
        ib.reqMarketDataType(MARKET_DATA_TYPE)
        print(f"Market data type configurado en: {MARKET_DATA_TYPE}")

    except Exception as e:
        print("No se pudo configurar market data type:", e)


def is_standard_strike(strike):
    try:
        if not USE_STANDARD_OPTION_STRIKES:
            return True

        strike = float(strike)

        if strike >= 100:
            return abs(strike % STANDARD_STRIKE_MULTIPLE) < 0.0001

        return abs(strike % 1) < 0.0001

    except Exception:
        return False


def _as_float(value):
    try:
        if isinstance(value, dict):
            for key in ("strike", "value", "low", "high"):
                if key in value:
                    return _as_float(value.get(key))
            return None
        if value in [None, "", "None"]:
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except Exception:
        return None


def _number_list(value):
    if value in [None, "", "None"]:
        return []
    if isinstance(value, (int, float)):
        parsed = _as_float(value)
        return [parsed] if parsed is not None else []
    if isinstance(value, list):
        out = []
        for item in value:
            parsed = _as_float(item)
            if parsed is not None:
                out.append(parsed)
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_number_list(item))
        return out
    if isinstance(value, str):
        raw = value.replace("$", " ").replace(",", " ")
        out = []
        for token in raw.split():
            parsed = _as_float(token)
            if parsed is not None:
                out.append(parsed)
        return out
    return []


def _append_unique_strike(out, strike):
    parsed = _as_float(strike)
    if parsed is None:
        return
    rounded = round(parsed, 4)
    if all(abs(existing - rounded) > 0.0001 for existing in out):
        out.append(rounded)


def _nearest_available_strike(strikes, target, max_distance=2.51):
    parsed = _as_float(target)
    if parsed is None:
        return None
    candidates = [float(strike) for strike in strikes if strike is not None]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda strike: abs(strike - parsed))
    if abs(nearest - parsed) <= max_distance:
        return round(nearest, 4)
    return None


def _load_rsp_manual_context():
    path = _v283_Path("runtime") / "coberturas_rsp_manual_context.json"
    try:
        data = _v283_json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _rsp_gamma_blob(context):
    raw = context.get("gamma_blob")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = _v283_json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _rsp_manual_candidate_strikes(context, right):
    blob = _rsp_gamma_blob(context)
    wanted_type = "put" if right == "P" else "call"
    out = []
    for source in [context, blob]:
        candidates = source.get("option_chain_candidates") if isinstance(source, dict) else None
        if not isinstance(candidates, list):
            continue
        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or item.get("right") or "").strip().lower()
            if item_type and wanted_type not in item_type and right.lower() not in item_type:
                continue
            _append_unique_strike(out, item.get("strike"))
    return out


def _rsp_context_level_strikes(context, right):
    blob = _rsp_gamma_blob(context)
    out = []
    if right == "P":
        keys = ("expected_move_low", "put_wall", "support_levels")
        blob_values = [
            (blob.get("expected_move") or {}).get("low") if isinstance(blob.get("expected_move"), dict) else None,
            (blob.get("gamma_context") or {}).get("put_wall") if isinstance(blob.get("gamma_context"), dict) else None,
            (blob.get("technical_levels") or {}).get("supports") if isinstance(blob.get("technical_levels"), dict) else None,
        ]
    else:
        keys = ("expected_move_high", "call_wall", "resistance_levels")
        blob_values = [
            (blob.get("expected_move") or {}).get("high") if isinstance(blob.get("expected_move"), dict) else None,
            (blob.get("gamma_context") or {}).get("call_wall") if isinstance(blob.get("gamma_context"), dict) else None,
            (blob.get("technical_levels") or {}).get("resistances") if isinstance(blob.get("technical_levels"), dict) else None,
        ]
    for key in keys:
        for value in _number_list(context.get(key)):
            _append_unique_strike(out, value)
    for value in blob_values:
        for item in _number_list(value):
            _append_unique_strike(out, item)
    return out


def pick_rsp_weekly_strikes(strikes, stock_price, right, limit):
    context = _load_rsp_manual_context()
    targets = []
    for value in _rsp_manual_candidate_strikes(context, right):
        _append_unique_strike(targets, value)
    context_levels = _rsp_context_level_strikes(context, right)
    if right == "P":
        context_levels = [item for item in context_levels if item <= stock_price]
    else:
        context_levels = [item for item in context_levels if item >= stock_price]
    for value in context_levels:
        _append_unique_strike(targets, value)

    if not targets:
        if right == "P":
            targets = sorted(
                [strike for strike in strikes if 0 <= (stock_price - strike) / stock_price <= 0.055],
                key=lambda strike: abs(abs((strike - stock_price) / stock_price) - 0.02),
            )
        else:
            targets = sorted(
                [strike for strike in strikes if 0.005 <= (strike - stock_price) / stock_price <= 0.055],
                key=lambda strike: abs(abs((strike - stock_price) / stock_price) - 0.025),
            )

    selected = []
    for target in targets:
        strike = _nearest_available_strike(strikes, target)
        if strike is not None:
            _append_unique_strike(selected, strike)
        if len(selected) >= limit:
            break
    return selected[:limit]


def tradingview_context_stub(symbol):
    """
    V15 mantiene el payload listo para integración TradingView.
    En una fase posterior, este bloque se alimentará desde el engine/dashboard:
    última señal técnica, tendencia, score, setup y timeframe.
    """
    return {
        "tradingview_signal_available": False,
        "tradingview_last_setup": None,
        "tradingview_last_trend": None,
        "tradingview_last_score": None,
        "tradingview_last_timeframe": None,
        "tradingview_last_signal_time": None
    }


def _bridge_unique_symbols(values):
    out = []
    seen = set()
    for value in values or []:
        symbol = str(value or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _bridge_is_tradable_equity_symbol(symbol):
    symbol = str(symbol or "").strip().upper()
    if not TRADABLE_EQUITY_SYMBOL_RE.match(symbol):
        return False
    return symbol not in NON_OPTION_UNDERLYING_SYMBOLS


def _bridge_unique_tradable_symbols(values):
    return [
        symbol for symbol in _bridge_unique_symbols(values)
        if _bridge_is_tradable_equity_symbol(symbol)
    ]


def _bridge_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().upper()
    if text in {"TRUE", "YES", "Y", "1", "PASS", "PASSES"}:
        return True
    if text in {"FALSE", "NO", "N", "0", "FAIL", "BLOCKED"}:
        return False
    return None


def _bridge_find_named_dict(obj, name, depth=0):
    if depth > 5:
        return None
    if isinstance(obj, dict):
        direct = obj.get(name)
        if isinstance(direct, dict):
            return direct
        for value in obj.values():
            found = _bridge_find_named_dict(value, name, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _bridge_find_named_dict(value, name, depth + 1)
            if found:
                return found
    return None


def _bridge_technical_score(technical):
    technical = technical if isinstance(technical, dict) else {}
    return _v283_float(
        technical.get("technical_score")
        or technical.get("score")
        or technical.get("trend_score"),
        None,
    )


def _bridge_technical_confirmed(technical):
    technical = technical if isinstance(technical, dict) else {}
    for key in ["confirmed", "technical_confirmed", "passes", "pass"]:
        value = _bridge_bool(technical.get(key))
        if value is not None:
            return value
    score = _bridge_technical_score(technical)
    if score is not None:
        return score >= OPTION_TECHNICAL_TRIGGER_SCORE
    return False


def _bridge_canslim_snapshot(technical):
    technical = technical if isinstance(technical, dict) else {}
    canslim = _bridge_find_named_dict(technical, "canslim") or {}
    score = _v283_float(
        canslim.get("score")
        or canslim.get("rating_score")
        or canslim.get("composite_score"),
        None,
    )
    passes = _bridge_bool(canslim.get("passes") if canslim else None)
    if passes is None and score is not None:
        passes = score >= OPTION_CANSLIM_TRIGGER_SCORE
    return {
        "available": bool(canslim),
        "passes": passes,
        "score": score,
        "rating": canslim.get("rating") if isinstance(canslim, dict) else None,
    }


def _bridge_canslim_candidate_from_row(row, source_name="runtime"):
    row = row if isinstance(row, dict) else {}
    symbol = str(row.get("ticker") or row.get("symbol") or row.get("underlying") or "").upper().strip()
    if not symbol:
        return None

    nested = row.get("canslim") if isinstance(row.get("canslim"), dict) else {}
    has_canslim_signal = bool(nested) or any(
        key in row for key in [
            "canslim_score",
            "canslim_passes",
            "canslim_rating",
            "rating_score",
            "composite_score",
            "composite_rating",
        ]
    )
    if not has_canslim_signal:
        return None

    score = _v283_float(
        nested.get("score")
        or nested.get("rating_score")
        or nested.get("composite_score")
        or row.get("canslim_score")
        or row.get("rating_score")
        or row.get("composite_score")
        or row.get("composite_rating"),
        None,
    )
    passes = _bridge_bool(
        nested.get("passes")
        if nested
        else row.get("canslim_passes")
    )
    if passes is None and score is not None:
        passes = score >= OPTION_CANSLIM_TRIGGER_SCORE

    fundamental = row.get("fundamental") if isinstance(row.get("fundamental"), dict) else {}
    for key in ["eps_growth", "sales_growth", "roe", "debt_to_equity", "institutional_ownership"]:
        if key in row and key not in fundamental:
            fundamental[key] = row.get(key)

    return {
        "ticker": symbol,
        "canslim": {
            "available": True,
            "passes": passes,
            "score": score,
            "rating": nested.get("rating") or row.get("canslim_rating") or row.get("rating"),
            "source": row.get("source") or source_name,
        },
        "fundamental": fundamental,
        "source": row.get("source") or source_name,
        "not_order_instruction": True,
    }


def _bridge_extract_canslim_candidates(runtime_data):
    runtime_data = runtime_data if isinstance(runtime_data, dict) else {}
    candidates = {}

    def scan(obj, source_name):
        if isinstance(obj, dict):
            candidate = _bridge_canslim_candidate_from_row(obj, source_name)
            if candidate:
                symbol = candidate["ticker"]
                current = candidates.get(symbol)
                current_score = _v283_float((current or {}).get("canslim", {}).get("score"), -1)
                candidate_score = _v283_float(candidate.get("canslim", {}).get("score"), -1)
                if current is None or candidate_score >= current_score:
                    candidates[symbol] = candidate
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    scan(value, source_name)
        elif isinstance(obj, list):
            for value in obj:
                scan(value, source_name)

    for source_name, payload in runtime_data.items():
        scan(payload, source_name)

    return candidates


def _bridge_merge_canslim_candidates_into_technical(technical, canslim_candidates):
    technical = technical if isinstance(technical, dict) else {}
    merged = {
        str(symbol).upper(): dict(value)
        for symbol, value in technical.items()
        if isinstance(value, dict) and _bridge_is_tradable_equity_symbol(symbol)
    }
    for symbol, candidate in (canslim_candidates or {}).items():
        symbol = str(symbol or "").upper().strip()
        if not _bridge_is_tradable_equity_symbol(symbol):
            continue
        target = dict(merged.get(symbol) or {"ticker": symbol, "symbol": symbol})
        candidate_canslim = candidate.get("canslim") if isinstance(candidate.get("canslim"), dict) else {}
        existing_canslim = target.get("canslim") if isinstance(target.get("canslim"), dict) else {}
        existing_score = _v283_float(existing_canslim.get("score") or existing_canslim.get("rating_score"), None)
        candidate_score = _v283_float(candidate_canslim.get("score") or candidate_canslim.get("rating_score"), None)
        if not existing_canslim or existing_score is None or (candidate_score is not None and candidate_score >= existing_score):
            target["canslim"] = dict(candidate_canslim)
            target["canslim_score"] = candidate_canslim.get("score")
            target["canslim_passes"] = candidate_canslim.get("passes")
            target["canslim_rating"] = candidate_canslim.get("rating")
            target["canslim_source"] = candidate_canslim.get("source")
        if isinstance(candidate.get("fundamental"), dict):
            existing_fundamental = target.get("fundamental") if isinstance(target.get("fundamental"), dict) else {}
            target["fundamental"] = {**existing_fundamental, **candidate["fundamental"]}
        merged[symbol] = target
    return merged


def _bridge_held_underlying_symbols():
    held = []
    for row in _bridge_cycle_position_rows():
        symbol = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        try:
            size = float(row.get("position_size") or row.get("position") or 0)
        except Exception:
            size = 0
        if abs(size) > 0:
            held.append(symbol)
    return set(_bridge_unique_symbols(held))


def _bridge_option_universe_runtime_context():
    runtime_data = _v283_load_runtime_jsons()
    option_rows = _v283_extract_options_rows(runtime_data)
    technical = _v283_extract_technical(runtime_data)
    canslim_candidates = _bridge_extract_canslim_candidates(runtime_data)
    try:
        technical = runtime_local_technical.merge_local_technical_snapshot(
            technical,
            runtime_data,
            options_rows=option_rows,
            timeframe="1d",
        )
    except Exception:
        pass
    technical = _bridge_merge_canslim_candidates_into_technical(technical, canslim_candidates)
    return runtime_data, technical if isinstance(technical, dict) else {}, option_rows


def option_underlying_rank(symbol, technical=None, *, held_symbols=None, original_index=0):
    symbol = str(symbol or "").upper().strip()
    if not _bridge_is_tradable_equity_symbol(symbol):
        return {
            "symbol": symbol,
            "score": 0.0,
            "qualifies": False,
            "triggers": [],
            "reasons": ["simbolo no valido para universo de opciones"],
            "blockers": ["INVALID_OPTION_UNDERLYING_SYMBOL"],
            "technical_score": None,
            "technical_confirmed": False,
            "canslim": {"available": False, "passes": None, "score": None, "rating": None},
            "tier_score": 0,
            "not_order_instruction": True,
        }
    technical = technical if isinstance(technical, dict) else {}
    held_symbols = held_symbols if isinstance(held_symbols, set) else set()
    core = set(_bridge_unique_symbols(OPTION_CORE_SYMBOLS))
    context_only = set(_bridge_unique_symbols(OPTION_CONTEXT_ONLY_SYMBOLS))
    priority = set(_bridge_unique_symbols(OPTION_PRIORITY_SYMBOLS))
    tier_score = float(OPTION_UNDERLYING_TIER_SCORES.get(symbol, 0))
    tech_score = _bridge_technical_score(technical)
    canslim = _bridge_canslim_snapshot(technical)
    trend = str(
        technical.get("trend")
        or technical.get("bias")
        or technical.get("technical_bias")
        or ""
    ).upper()

    score = 0.0
    triggers = []
    reasons = []
    blockers = []

    if symbol in core:
        score += 100
        triggers.append("CORE_MARKET_CONTEXT")
        reasons.append("contexto de mercado/riesgo")
    if symbol in context_only:
        score += 25
        reasons.append("contexto macro, no consume chain sin detonador")
    if symbol in priority:
        score += 85
        triggers.append("OPERATOR_PRIORITY")
        reasons.append("prioridad configurada por operador")
    if symbol in held_symbols:
        score += 75
        triggers.append("EXISTING_POSITION")
        reasons.append("posicion existente puede requerir manejo")
    if tier_score:
        score += tier_score
        if tier_score >= 28:
            triggers.append("LIQUID_LARGE_CAP")
        reasons.append(f"liquidez/large-cap tier {tier_score:.0f}")

    if tech_score is not None:
        score += min(max(tech_score, 0), 100) * 0.35
        reasons.append(f"score tecnico {tech_score:.1f}")
        if tech_score >= OPTION_TECHNICAL_TRIGGER_SCORE:
            triggers.append("TECHNICAL_TRIGGER")

    if _bridge_technical_confirmed(technical):
        score += 20
        triggers.append("TECHNICAL_CONFIRMED")
        reasons.append("tecnico confirmado")

    if any(token in trend for token in ["BULL", "UP", "LONG", "BREAKOUT", "MOMENTUM"]):
        score += 10
        reasons.append("sesgo tecnico positivo")
    elif any(token in trend for token in ["BEAR", "DOWN", "SHORT", "RISK_OFF"]):
        score += 5
        reasons.append("sesgo tecnico defensivo")

    if canslim["available"]:
        if canslim["passes"] is True:
            score += 40
            triggers.append("CANSLIM_PASS")
            reasons.append("CANSLIM pasa")
        elif canslim["passes"] is False:
            score -= 35
            blockers.append("CANSLIM_FAIL")
            reasons.append("CANSLIM falla")
        if canslim["score"] is not None:
            score += min(max(canslim["score"], 0), 100) * 0.20
            reasons.append(f"CANSLIM score {canslim['score']:.1f}")
            if canslim["score"] >= OPTION_CANSLIM_TRIGGER_SCORE:
                triggers.append("CANSLIM_SCORE_TRIGGER")

    score -= min(max(original_index, 0), 500) * 0.01
    score = round(max(0.0, score), 2)
    qualifies = bool(triggers) or score >= OPTION_MIN_UNDERLYING_SCORE
    if symbol in context_only:
        actionable_triggers = [
            trigger for trigger in triggers
            if trigger not in {"LIQUID_LARGE_CAP", "CORE_MARKET_CONTEXT"}
        ]
        if not actionable_triggers:
            qualifies = False
            blockers.append("CONTEXT_ONLY_NO_ACTION_TRIGGER")
    if not qualifies:
        blockers.append("NO_DYNAMIC_UNDERLYING_TRIGGER")

    return {
        "symbol": symbol,
        "score": score,
        "qualifies": qualifies,
        "triggers": _bridge_unique_symbols(triggers),
        "reasons": reasons,
        "blockers": _bridge_unique_symbols(blockers),
        "technical_score": tech_score,
        "technical_confirmed": _bridge_technical_confirmed(technical),
        "canslim": canslim,
        "tier_score": tier_score,
        "not_order_instruction": True,
    }


def build_dynamic_option_symbol_plan(symbols, technical_snapshot=None):
    base_symbols = _bridge_unique_tradable_symbols(symbols)
    technical_snapshot = technical_snapshot if isinstance(technical_snapshot, dict) else {}
    candidate_symbols = list(base_symbols)
    if INCLUDE_RUNTIME_TECHNICAL_OPTION_CANDIDATES:
        candidate_symbols.extend(str(symbol).upper() for symbol in technical_snapshot.keys())
    all_candidate_symbols = _bridge_unique_symbols(candidate_symbols)
    invalid_candidate_symbols = [
        symbol for symbol in all_candidate_symbols
        if not _bridge_is_tradable_equity_symbol(symbol)
    ]
    candidate_symbols = _bridge_unique_tradable_symbols(candidate_symbols)

    if not DYNAMIC_OPTION_UNIVERSE_ENABLED:
        selected = candidate_symbols[:]
        return {
            "plan_version": "dynamic_option_underlying_universe_v1",
            "enabled": False,
            "reason": "IBKR_DYNAMIC_OPTION_UNIVERSE_ENABLED=false",
            "input_symbols": base_symbols,
            "candidate_count": len(candidate_symbols),
            "invalid_candidate_symbols": invalid_candidate_symbols,
            "selected_symbols": selected,
            "selected_count": len(selected),
            "max_symbols_per_run": None,
            "max_total_option_contracts_per_run": MAX_TOTAL_OPTION_CONTRACTS_PER_RUN,
            "ranked": [
                {"rank": idx + 1, "symbol": symbol, "score": None, "qualifies": True}
                for idx, symbol in enumerate(selected)
            ],
            "skipped": [],
            "not_order_instruction": True,
        }

    held_symbols = _bridge_held_underlying_symbols()
    ranked = []
    for idx, symbol in enumerate(candidate_symbols):
        ranked.append(
            option_underlying_rank(
                symbol,
                technical_snapshot.get(symbol) or {},
                held_symbols=held_symbols,
                original_index=idx,
            )
        )

    ranked = sorted(
        ranked,
        key=lambda item: (
            1 if item.get("qualifies") else 0,
            item.get("score") or 0,
            -candidate_symbols.index(item["symbol"]),
        ),
        reverse=True,
    )
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx

    selected_rows = [
        item for item in ranked
        if item.get("qualifies") and (item.get("score") or 0) >= OPTION_MIN_UNDERLYING_SCORE
    ][:MAX_OPTION_SYMBOLS_PER_RUN]
    selected_symbols = [item["symbol"] for item in selected_rows]
    skipped = [
        {
            "symbol": item["symbol"],
            "score": item.get("score"),
            "rank": item.get("rank"),
            "blockers": item.get("blockers") or ["OUTSIDE_SYMBOL_BUDGET"],
            "triggers": item.get("triggers") or [],
        }
        for item in ranked
        if item["symbol"] not in selected_symbols
    ]

    return {
        "plan_version": "dynamic_option_underlying_universe_v1",
        "enabled": True,
        "input_symbols": base_symbols,
        "candidate_count": len(candidate_symbols),
        "invalid_candidate_symbols": invalid_candidate_symbols,
        "canslim_candidate_count": len([
            symbol for symbol in candidate_symbols
            if _bridge_canslim_snapshot(technical_snapshot.get(symbol) or {}).get("available")
        ]),
        "runtime_technical_candidate_count": len([
            symbol for symbol in candidate_symbols
            if symbol not in base_symbols and symbol in technical_snapshot
        ]),
        "selected_symbols": selected_symbols,
        "selected_count": len(selected_symbols),
        "max_symbols_per_run": MAX_OPTION_SYMBOLS_PER_RUN,
        "max_total_option_contracts_per_run": MAX_TOTAL_OPTION_CONTRACTS_PER_RUN,
        "min_underlying_score": OPTION_MIN_UNDERLYING_SCORE,
        "technical_trigger_score": OPTION_TECHNICAL_TRIGGER_SCORE,
        "canslim_trigger_score": OPTION_CANSLIM_TRIGGER_SCORE,
        "ranked": ranked,
        "skipped": skipped,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


# ============================================================
# CONTRACT HELPERS
# ============================================================

def stock_contract(symbol):
    """
    V15:
    1. Intenta contrato SMART + primaryExchange.
    2. Si falla, intenta SMART simple.
    3. Devuelve contrato calificado cuando IBKR lo permite.
    """
    primary_exchange = PRIMARY_EXCHANGE_MAP.get(symbol)

    attempts = []

    if primary_exchange:
        attempts.append(
            Stock(
                symbol=symbol,
                exchange="SMART",
                currency="USD",
                primaryExchange=primary_exchange
            )
        )

    attempts.append(
        Stock(
            symbol=symbol,
            exchange="SMART",
            currency="USD"
        )
    )

    for contract in attempts:
        try:
            qualified = ib.qualifyContracts(contract)

            if qualified:
                return qualified[0]

        except Exception:
            pass

    try:
        matches = ib.reqMatchingSymbols(symbol)
        for match in matches or []:
            matched = getattr(match, "contract", None)
            if not matched:
                continue
            if str(getattr(matched, "symbol", "") or "").upper() != str(symbol or "").upper():
                continue
            if str(getattr(matched, "secType", "") or "").upper() != "STK":
                continue
            if str(getattr(matched, "currency", "") or "").upper() != "USD":
                continue
            if primary_exchange and str(getattr(matched, "primaryExchange", "") or getattr(matched, "exchange", "") or "").upper() != primary_exchange:
                continue
            return Stock(
                symbol=symbol,
                exchange="SMART",
                currency="USD",
                primaryExchange=primary_exchange or getattr(matched, "primaryExchange", None) or getattr(matched, "exchange", None),
                conId=int(getattr(matched, "conId", 0) or 0),
            )
    except Exception as exc:
        print(symbol, "matching symbol fallback failed:", exc)

    # Fallback final
    if primary_exchange:
        return Stock(
            symbol=symbol,
            exchange="SMART",
            currency="USD",
            primaryExchange=primary_exchange
        )

    return Stock(symbol, "SMART", "USD")






def _observed_fixed_market_holiday(year, month, day):
    holiday = datetime(year, month, day).date()
    if holiday.weekday() == 5:  # Saturday observed Friday
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:  # Sunday observed Monday
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday_date(year, month, weekday, occurrence):
    current = datetime(year, month, 1).date()
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (occurrence - 1))


def _last_weekday_date(year, month, weekday):
    if month == 12:
        current = datetime(year, 12, 31).date()
    else:
        current = datetime(year, month + 1, 1).date() - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _easter_date(year):
    """Gregorian Easter date; Good Friday is two days earlier."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day).date()


def _us_market_holiday_dates(year):
    holidays = {
        _observed_fixed_market_holiday(year, 1, 1),   # New Year's Day
        _nth_weekday_date(year, 1, 0, 3),             # Martin Luther King Jr. Day
        _nth_weekday_date(year, 2, 0, 3),             # Washington's Birthday
        _easter_date(year) - timedelta(days=2),       # Good Friday
        _last_weekday_date(year, 5, 0),               # Memorial Day
        _observed_fixed_market_holiday(year, 6, 19),  # Juneteenth
        _observed_fixed_market_holiday(year, 7, 4),   # Independence Day
        _nth_weekday_date(year, 9, 0, 1),             # Labor Day
        _nth_weekday_date(year, 11, 3, 4),            # Thanksgiving Day
        _observed_fixed_market_holiday(year, 12, 25), # Christmas Day
    }
    return holidays


def ibkr_market_is_us_holiday(now_et=None):
    try:
        current = now_et or datetime.now(ZoneInfo("America/New_York"))
        current_date = current.date()
        years = {current_date.year - 1, current_date.year, current_date.year + 1}
        return any(current_date in _us_market_holiday_dates(year) for year in years)
    except Exception:
        return False


def ibkr_market_is_open_for_options(now_et=None):
    """
    V16.1 Market-Aware:
    Detecta si estamos en horario regular aproximado de mercado USA,
    respetando feriados principales de NYSE/Nasdaq.
    Sirve para no castigar bid/ask faltante cuando el mercado está cerrado.
    """
    try:
        now_et = now_et or datetime.now(ZoneInfo("America/New_York"))
        weekday = now_et.weekday() < 5
        if not weekday or ibkr_market_is_us_holiday(now_et):
            return False
        minutes_et = now_et.hour * 60 + now_et.minute
        regular_session = (9 * 60 + 30) <= minutes_et < (16 * 60)
        return regular_session
    except Exception:
        return False


def bridge_market_snapshot(source):
    now_et = datetime.now(ZoneInfo("America/New_York"))
    is_open = ibkr_market_is_open_for_options()
    is_holiday = ibkr_market_is_us_holiday(now_et)
    return {
        "status": "REGULAR_OPTIONS_SESSION" if is_open else "OUTSIDE_REGULAR_OPTIONS_SESSION",
        "label": (
            "Mercado abierto: opciones en ventana regular"
            if is_open
            else "Fuera de la sesion regular de opciones"
        ),
        "is_regular_market_open": is_open,
        "options_bidask_expected": is_open,
        "source": source,
        "generated_at": now_iso(),
        "calendar_precision": "NYSE_HOLIDAY_AWARE_ESTIMATE",
        "market_holiday": is_holiday,
    }


def market_closed_bidask_note():
    return "MARKET_CLOSED_NO_BIDASK_EXPECTED"

def option_needs_second_pass(ticker):
    """
    V16 incremental:
    Detecta si una opción necesita más tiempo para que IBKR entregue griegas o bid/ask.
    No bloquea la estrategia; solo mejora la probabilidad de recibir delta/IV/bid/ask.
    """
    try:
        bid = clean_price(getattr(ticker, "bid", None))
        ask = clean_price(getattr(ticker, "ask", None))
        greeks = option_greeks(ticker)
        has_delta = greeks.get("delta") is not None
        has_iv = greeks.get("iv") is not None
        has_bidask = bool(bid and ask)
        return not (has_delta and has_iv and has_bidask)
    except Exception:
        return True

def option_greeks(ticker):
    greeks = (
        ticker.modelGreeks
        or ticker.bidGreeks
        or ticker.askGreeks
        or ticker.lastGreeks
    )

    if not greeks:
        return {
            "iv": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None
        }

    return {
        "iv": safe_round(getattr(greeks, "impliedVol", None), 4),
        "delta": safe_round(getattr(greeks, "delta", None), 4),
        "gamma": safe_round(getattr(greeks, "gamma", None), 6),
        "theta": safe_round(getattr(greeks, "theta", None), 4),
        "vega": safe_round(getattr(greeks, "vega", None), 4)
    }


def calculate_spread_pct(bid, ask, mid):
    try:
        if bid is None or ask is None or mid is None:
            return None

        if bid <= 0 or ask <= 0 or mid <= 0:
            return None

        spread = ask - bid

        if spread < 0:
            return None

        return safe_round((spread / mid) * 100, 2)

    except Exception:
        return None


def data_quality_for_option(bid, ask, mid, greeks):
    has_price = mid is not None and mid > 0
    has_bid_ask = (
        bid is not None
        and ask is not None
        and bid > 0
        and ask > 0
        and ask >= bid
    )
    has_delta = greeks.get("delta") is not None
    has_iv = greeks.get("iv") is not None

    if has_price and has_bid_ask and has_delta and has_iv:
        return "FULL_WITH_GREEKS"

    if has_price and has_delta and has_iv:
        return "PRICE_WITH_GREEKS_NO_BIDASK"

    if has_price and not has_delta and not has_iv:
        return "PRICE_ONLY_NO_GREEKS"

    if has_price:
        return "PARTIAL_OPTION_DATA"

    return "NO_VALID_OPTION_PRICE"


def normalize_option_quote_fields(bid, ask, last, close, market_price, greeks):
    """
    Pure V30 quote normalization for executable option fields.

    - Sanitizes IBKR placeholder values such as nan, -1, and 0.
    - Uses bid/ask only when both are positive and ordered.
    - Computes mid/spread/spread_pct consistently.
    - Allows a non-executable mid from market/last/close, but never invents
      bid/ask/spread from it.
    """
    bid = clean(bid)
    ask = clean(ask)
    last = clean(last)
    close = clean(close)
    market_price = clean(market_price)
    greeks = greeks or {}

    has_ordered_bidask = (
        bid is not None
        and ask is not None
        and ask >= bid
    )

    mid = None
    spread = None
    if has_ordered_bidask:
        mid = safe_round((bid + ask) / 2, 4)
        spread = safe_round(ask - bid, 4)
    elif market_price:
        mid = market_price
    elif last:
        mid = last
    elif close:
        mid = close

    spread_pct = calculate_spread_pct(
        bid=bid,
        ask=ask,
        mid=mid,
    )

    return {
        "bid": bid,
        "ask": ask,
        "last": last,
        "close": close,
        "market_price": market_price,
        "mid": mid,
        "spread": spread,
        "spread_pct": spread_pct,
        "data_quality": data_quality_for_option(
            bid=bid,
            ask=ask,
            mid=mid,
            greeks=greeks,
        ),
    }


def option_market_data_score(data):
    data = data or {}
    greeks = data.get("greeks") or {}
    fields = [
        data.get("bid"),
        data.get("ask"),
        data.get("mid"),
        data.get("spread"),
        data.get("spread_pct"),
        greeks.get("delta"),
    ]
    complete = sum(1 for value in fields if value not in [None, "", "None"])
    quality_rank = {
        "FULL_WITH_GREEKS": 4,
        "PRICE_WITH_GREEKS_NO_BIDASK": 3,
        "PARTIAL_OPTION_DATA": 2,
        "PRICE_ONLY_NO_GREEKS": 1,
        "NO_VALID_OPTION_PRICE": 0,
        "OPTION_MARKET_DATA_ERROR": -1,
    }.get(str(data.get("data_quality") or ""), 0)
    return (
        complete,
        quality_rank,
        1 if data.get("bid") is not None and data.get("ask") is not None else 0,
        1 if data.get("mid") is not None else 0,
    )


# ============================================================
# STOCK PRICE FALLBACKS
# ============================================================

def extract_price_from_ticker(ticker):
    price = clean(ticker.marketPrice())
    last = clean(ticker.last)
    bid = clean(ticker.bid)
    ask = clean(ticker.ask)
    close = clean(ticker.close)

    final_price = (
        price
        or last
        or ((bid + ask) / 2 if bid and ask else None)
        or close
    )

    final_price = clean(final_price)

    return {
        "price": final_price,
        "bid": bid,
        "ask": ask,
        "last": last,
        "close": close,
        "market_price": price
    }


def get_price_snapshot_req_tickers(symbol, contract):
    try:
        tickers = ib.reqTickers(contract)

        if not tickers:
            return None

        ticker = tickers[0]
        data = extract_price_from_ticker(ticker)

        if data["price"] is None:
            return None

        return {
            "ticker": symbol,
            "price": data["price"],
            "bid": data["bid"],
            "ask": data["ask"],
            "last": data["last"],
            "close": data["close"],
            "market_price": data["market_price"],
            "source": "IBKR_REALTIME_V18_1_REMOTE_SNAPSHOT_INGEST",
            "price_source": "IBKR_REQ_TICKERS"
        }

    except Exception:
        return None


def get_price_snapshot_req_mkt_data(symbol, contract):
    ticker = None

    try:
        ticker = ib.reqMktData(
            contract,
            genericTickList="",
            snapshot=False,
            regulatorySnapshot=False
        )

        ib.sleep(STOCK_MARKET_DATA_WAIT_SECONDS)

        data = extract_price_from_ticker(ticker)

        try:
            ib.cancelMktData(contract)
        except Exception:
            pass

        if data["price"] is None:
            return None

        return {
            "ticker": symbol,
            "price": data["price"],
            "bid": data["bid"],
            "ask": data["ask"],
            "last": data["last"],
            "close": data["close"],
            "market_price": data["market_price"],
            "source": "IBKR_REALTIME_V18_1_REMOTE_SNAPSHOT_INGEST",
            "price_source": "IBKR_MKT_DATA_FALLBACK"
        }

    except Exception:
        try:
            if ticker is not None:
                ib.cancelMktData(contract)
        except Exception:
            pass

        return None


def get_price_snapshot_historical(symbol, contract):
    """
    Fallback final:
    Si no hay precio vivo, intenta obtener último cierre histórico.
    Esto ayuda con casos como NFLX cuando reqTickers no devuelve precio.
    """
    previous_timeout = getattr(ib, "RequestTimeout", 0)
    try:
        ib.RequestTimeout = HISTORICAL_DATA_TIMEOUT_SECONDS
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=LOCAL_TECHNICAL_HISTORICAL_DURATION,
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
            keepUpToDate=False
        )

        if not bars:
            return None

        last_bar = bars[-1]
        close = clean(last_bar.close)

        if close is None:
            return None

        historical_bars = []
        for bar in bars[-LOCAL_TECHNICAL_MAX_BARS:]:
            try:
                historical_bars.append({
                    "timestamp": str(getattr(bar, "date", "")),
                    "open": clean(getattr(bar, "open", None)),
                    "high": clean(getattr(bar, "high", None)),
                    "low": clean(getattr(bar, "low", None)),
                    "close": clean(getattr(bar, "close", None)),
                    "volume": clean(getattr(bar, "volume", None)),
                })
            except Exception:
                pass

        return {
            "ticker": symbol,
            "price": close,
            "bid": None,
            "ask": None,
            "last": None,
            "close": close,
            "market_price": None,
            "source": "IBKR_HISTORICAL_V18_1_REMOTE_SNAPSHOT_INGEST",
            "price_source": "IBKR_HISTORICAL_CLOSE_FALLBACK",
            "historical_bars": historical_bars,
            "historical_bar_count": len(historical_bars),
            "local_technical_candidate": len(historical_bars) >= 30,
        }

    except Exception:
        return None
    finally:
        try:
            ib.RequestTimeout = previous_timeout
        except Exception:
            pass


# ============================================================
# MARKET DATA
# ============================================================

def get_price_snapshot(symbol):
    try:
        contract = stock_contract(symbol)

        # 1. Método principal
        snap = get_price_snapshot_req_tickers(symbol, contract)

        if snap and snap.get("price") is not None:
            return snap

        # 2. Fallback por streaming market data
        snap = get_price_snapshot_req_mkt_data(symbol, contract)

        if snap and snap.get("price") is not None:
            return snap

        # 3. Fallback histórico
        snap = get_price_snapshot_historical(symbol, contract)

        if snap and snap.get("price") is not None:
            return snap

        return None

    except Exception as e:
        print(symbol, "PRICE ERROR:", e)
        return None


def send_market_data():
    print("\n=== MARKET DATA V18_1_REMOTE_SNAPSHOT_INGEST ===\n")

    for symbol in WATCHLIST:
        try:
            with bridge_step_timeout(STOCK_PRICE_SNAPSHOT_TIMEOUT_SECONDS, f"market data {symbol}"):
                snap = get_price_snapshot(symbol)
        except BridgeStepTimeout as exc:
            print(symbol, "PRICE TIMEOUT:", exc)
            continue

        if not snap or snap.get("price") is None:
            print(symbol, "sin precio válido")
            continue

        tv_context = tradingview_context_stub(symbol)

        payload = {
            "ticker": symbol,
            "timeframe": "live",
            "setup": "IBKR_LIVE_MARKET_V15",
            "trend": "",
            "score": 0,
            "price": snap["price"],
            "bid": snap["bid"],
            "ask": snap["ask"],
            "last": snap["last"],
            "close": snap["close"],
            "market_price": snap["market_price"],
            "source": snap["source"],
            "price_source": snap["price_source"],
            "asset_class": "EQUITY",
            "engine_layer": "IBKR_MARKET_DATA",
            "integration_ready_for_tradingview": True,
            "received_at_bridge": now_iso(),
            **tv_context
        }

        status = post(payload)

        print(
            f"{symbol} | price:{snap['price']} "
            f"bid:{snap['bid']} ask:{snap['ask']} "
            f"price_source:{snap['price_source']} status:{status}"
        )


# ============================================================
# PORTFOLIO COMMANDER
# ============================================================

def get_positions_rows():
    rows = []
    total_abs_value = 0
    selection = _bridge_account_selection()
    selected = selection.get("selected") or ""
    if selection.get("selection_required"):
        print("POSITIONS SKIPPED: multiple IBKR accounts detected; set IBKR_ACCOUNT_ALIAS/IBKR_ACCOUNT_MAP or IBKR_ACCOUNT_ID locally.")
        return rows
    if selected and not selection.get("selected_found"):
        print("POSITIONS SKIPPED: selected IBKR account is not visible in TWS/IB Gateway.")
        return rows

    try:
        print("POSITIONS REQUEST START", flush=True)
        with bridge_step_timeout(POSITION_REQUEST_TIMEOUT_SECONDS, "positions request"):
            positions = ib.positions()
        print(f"POSITIONS REQUEST OK: {len(positions)} row(s)", flush=True)
    except BridgeStepTimeout as e:
        print("POSITIONS TIMEOUT:", e, flush=True)
        return rows
    except Exception as e:
        print("POSITIONS ERROR:", e, flush=True)
        return rows

    for position in positions:
        try:
            if selected and str(getattr(position, "account", "") or "").strip() not in ["", selected]:
                continue
            contract = position.contract
            symbol = contract.symbol
            sec_type = contract.secType

            if COBERTURAS_RSP_WEEKLY and str(symbol or "").upper() != "RSP":
                continue

            qty = safe_round(position.position, 4)
            avg = safe_round(position.avgCost, 4)

            market_price = None
            market_value = None
            unrealized_pl = None
            price_source = None

            if sec_type == "STK":
                try:
                    with bridge_step_timeout(POSITION_PRICE_SNAPSHOT_TIMEOUT_SECONDS, f"position price {symbol}"):
                        snap = get_price_snapshot(symbol)
                except BridgeStepTimeout as exc:
                    print("POSITION PRICE TIMEOUT:", symbol, exc)
                    snap = None

                if snap and snap.get("price"):
                    market_price = snap["price"]
                    price_source = snap.get("price_source")
                    market_value = safe_round(market_price * position.position, 2)

                    unrealized_pl = safe_round(
                        (market_price - position.avgCost) * position.position,
                        2
                    )

                    total_abs_value += abs(market_value or 0)

            row = {
                "ticker": symbol,
                "local_symbol": getattr(contract, "localSymbol", None),
                "sec_type": sec_type,
                "right": getattr(contract, "right", None),
                "strike": getattr(contract, "strike", None),
                "expiration": getattr(contract, "lastTradeDateOrContractMonth", None),
                "position_size": qty,
                "avg_cost": avg,
                "market_price": market_price,
                "market_value": market_value,
                "unrealized_pl": unrealized_pl,
                "price_source": price_source,
                "account_scope": BRIDGE_ACCOUNT_SCOPE,
                "account_alias": BRIDGE_ACCOUNT_ALIAS,
                "sensitive_identifiers_excluded": True,
            }

            rows.append(row)

        except Exception as e:
            print("POSITION ROW ERROR:", e)

    for row in rows:
        weight = None

        if total_abs_value > 0 and row.get("market_value") is not None:
            weight = safe_round(
                abs(row["market_value"]) / total_abs_value * 100,
                2
            )

        row["portfolio_weight_pct"] = weight

    return rows


def classify_position(row):
    sec_type = row.get("sec_type")
    qty = row.get("position_size") or 0

    if sec_type == "STK" and qty > 0:
        if qty >= 100:
            return "COVERED_CALL_CANDIDATE"

        return "LONG_STOCK_SMALL"

    if sec_type == "STK" and qty < 0:
        return "SHORT_STOCK"

    if sec_type == "OPT":
        right = row.get("right")

        if right == "C" and qty < 0:
            return "SHORT_CALL"

        if right == "P" and qty < 0:
            return "SHORT_PUT"

        if right == "C" and qty > 0:
            return "LONG_CALL"

        if right == "P" and qty > 0:
            return "LONG_PUT"

    if sec_type in ["FUT", "CONTFUT"]:
        return "FUTURES_POSITION"

    return "POSITION"


def send_positions():
    print("\n=== PORTFOLIO COMMANDER V18_1_REMOTE_SNAPSHOT_INGEST ===\n")

    rows = get_positions_rows()

    if not rows:
        print("Sin posiciones detectadas.")
        return

    for row in rows:
        position_class = classify_position(row)
        tv_context = tradingview_context_stub(row["ticker"])

        payload = {
            "ticker": row["ticker"],
            "timeframe": "position",
            "setup": f"IBKR_{position_class}_V15",
            "trend": "",
            "score": 0,
            "source": "IBKR_PORTFOLIO_V15",
            "asset_class": "POSITION",
            "engine_layer": "IBKR_PORTFOLIO_COMMANDER",
            "integration_ready_for_tradingview": True,
            "account_scope": row["account_scope"],
            "account_alias": row["account_alias"],
            "sensitive_identifiers_excluded": True,
            "position_class": position_class,
            "local_symbol": row["local_symbol"],
            "sec_type": row["sec_type"],
            "right": row["right"],
            "strike": row["strike"],
            "expiration": row["expiration"],
            "position_size": row["position_size"],
            "avg_cost": row["avg_cost"],
            "market_price": row["market_price"],
            "market_value": row["market_value"],
            "unrealized_pl": row["unrealized_pl"],
            "portfolio_weight_pct": row["portfolio_weight_pct"],
            "price_source": row["price_source"],
            "received_at_bridge": now_iso(),
            **tv_context
        }

        v17_store_row(payload)

        status = post(payload)

        print(
            f"POS {row['ticker']} | type:{row['sec_type']} "
            f"class:{position_class} size:{row['position_size']} "
            f"value:{row['market_value']} pnl:{row['unrealized_pl']} "
            f"weight:{row['portfolio_weight_pct']} "
            f"price_source:{row['price_source']} status:{status}"
        )


# ============================================================
# OPTIONS INTELLIGENCE
# ============================================================

def choose_expiration_from_chain(expirations):
    today = datetime.now().date()
    candidates = []

    for exp in sorted(expirations):
        try:
            exp_date = datetime.strptime(exp, "%Y%m%d").date()
            dte = (exp_date - today).days

            if TARGET_DTE_MIN <= dte <= TARGET_DTE_MAX:
                candidates.append((exp, dte))

        except Exception:
            pass

    if candidates:
        return sorted(
            candidates,
            key=lambda x: abs(x[1] - TARGET_DTE_IDEAL)
        )[0]

    return None, None



def score_option_candidate(*args, **kwargs):
    """
    V16.2 Decision Cap:
    Envuelve la evaluación original de opciones.
    - Mercado cerrado: nunca permite OPERAR; máximo RADAR/preparación.
    - Mercado abierto: si faltan bid/ask/spread confiable, bloquea OPERAR.
    """
    result = _score_option_candidate_core(*args, **kwargs)

    if not isinstance(result, dict):
        return result

    market_open = ibkr_market_is_open_for_options()
    result["market_open_for_options"] = market_open

    decision = str(result.get("decision", "")).upper()
    final_decision = str(result.get("final_decision", "")).upper()
    strategy_decision = str(result.get("strategy_decision", "")).upper()
    cap = str(result.get("cap", "")).upper()
    quality = str(result.get("data_quality", result.get("quality", ""))).upper()

    blockers = result.get("blockers", [])
    if blockers is None:
        blockers = []
    if not isinstance(blockers, list):
        blockers = [str(blockers)]

    warnings = result.get("warnings", [])
    if warnings is None:
        warnings = []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    # Mercado cerrado: no hay entrada ejecutable.
    if not market_open:
        result["market_closed_note"] = "MARKET_CLOSED_NO_BIDASK_EXPECTED"
        result["execution_cap"] = "RADAR_ONLY_MARKET_CLOSED"

        if decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]:
            result["decision"] = "RADAR"

        if final_decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]:
            result["final_decision"] = "RADAR"

        if strategy_decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]:
            result["strategy_decision"] = "RADAR"

        if cap in ["OPERAR", "ENTRY", "TRADE"]:
            result["cap"] = "RADAR"

        if "Mercado cerrado: bid/ask de opciones puede no ser confiable." not in warnings:
            warnings.append("Mercado cerrado: bid/ask de opciones puede no ser confiable.")

        result["warnings"] = warnings
        result["blockers"] = blockers
        result["can_operar"] = False

        if result.get("decision") in [None, "", "OPERAR"]:
            result["decision"] = "RADAR"

        v17_store_row(result)
        return result

    # Mercado abierto: si el motor quería OPERAR pero no hay bid/ask o spread completo, se bloquea.
    wants_operate = (
        decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]
        or final_decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]
        or strategy_decision in ["OPERAR", "ENTRY_OPPORTUNITY", "TRADE", "BUY", "SELL"]
    )

    incomplete_market_quality = (
        "NO_BIDASK" in quality
        or "NO_GREEKS" in quality
        or "WAIT_FOR_GREEKS" in cap
        or "PRICE_ONLY" in quality
    )

    if market_open and wants_operate and incomplete_market_quality:
        result["execution_cap"] = "BLOCKED_OPEN_MARKET_REQUIRES_BIDASK_SPREAD"
        result["decision"] = "RADAR"
        result["final_decision"] = "RADAR"
        result["strategy_decision"] = "RADAR"
        result["cap"] = "RADAR"
        result["can_operar"] = False

        blocker = "Mercado abierto: para OPERAR se requiere bid/ask/spread y griegas confiables."
        if blocker not in blockers:
            blockers.append(blocker)

    result["warnings"] = warnings
    result["blockers"] = blockers
    v17_store_row(result)
    return result


def option_chain_symbol_match_rank(symbol, chain):
    trading_class = str(getattr(chain, "tradingClass", "") or "").upper()
    symbol = str(symbol or "").upper()
    if trading_class == symbol:
        return 0
    if trading_class.endswith(symbol) and trading_class != symbol:
        return 2
    return 1


def get_option_chain(symbol):
    try:
        stock = stock_contract(symbol)

        chains = ib.reqSecDefOptParams(
            stock.symbol,
            "",
            stock.secType,
            stock.conId
        )

        if not chains:
            print(symbol, "sin option chains desde IBKR")
            IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
                "ticker": symbol,
                "status": "NO_CHAIN",
                "chain_count": 0,
                "generated_at": now_iso(),
                "not_order_instruction": True,
            })
            return None, None, None

        usable = []
        chain_summaries = []

        for chain in chains:
            expirations = list(chain.expirations or [])
            strikes = list(chain.strikes or [])
            chain_summaries.append({
                "exchange": getattr(chain, "exchange", None),
                "tradingClass": getattr(chain, "tradingClass", None),
                "multiplier": getattr(chain, "multiplier", None),
                "expiration_count": len(expirations),
                "strike_count": len(strikes),
                "symbol_match_rank": option_chain_symbol_match_rank(symbol, chain),
            })

            if not expirations or not strikes:
                continue

            expiry, dte = choose_expiration_from_chain(expirations)

            if expiry:
                usable.append(
                    {
                        "chain": chain,
                        "expiry": expiry,
                        "dte": dte,
                        "symbol_match_rank": option_chain_symbol_match_rank(symbol, chain),
                        "is_smart": chain.exchange == "SMART",
                        "strike_count": len(strikes)
                    }
                )

        if usable:
            selected = sorted(
                usable,
                key=lambda x: (
                    x["symbol_match_rank"],
                    0 if x["is_smart"] else 1,
                    abs(x["dte"] - TARGET_DTE_IDEAL),
                    -x["strike_count"]
                )
            )[0]
            IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
                "ticker": symbol,
                "status": "CHAIN_SELECTED",
                "chain_count": len(chains),
                "usable_chain_count": len(usable),
                "selected_expiry": selected["expiry"],
                "selected_dte": selected["dte"],
                "selected_exchange": getattr(selected["chain"], "exchange", None),
                "selected_trading_class": getattr(selected["chain"], "tradingClass", None),
                "selected_multiplier": getattr(selected["chain"], "multiplier", None),
                "chain_summaries": chain_summaries,
                "generated_at": now_iso(),
                "not_order_instruction": True,
            })

            return selected["chain"], selected["expiry"], selected["dte"]

        # Fallback: si ninguna cadena tiene 25-65 DTE, usamos la mejor mayor a 10 DTE.
        fallback = []

        today = datetime.now().date()

        for chain in chains:
            expirations = list(chain.expirations or [])
            strikes = list(chain.strikes or [])

            if not expirations or not strikes:
                continue

            for exp in sorted(expirations):
                try:
                    exp_date = datetime.strptime(exp, "%Y%m%d").date()
                    dte = (exp_date - today).days

                    if dte > 10:
                        fallback.append(
                            {
                                "chain": chain,
                                "expiry": exp,
                                "dte": dte,
                                "symbol_match_rank": option_chain_symbol_match_rank(symbol, chain),
                                "is_smart": chain.exchange == "SMART",
                                "strike_count": len(strikes)
                            }
                        )

                except Exception:
                    pass

        if fallback:
            selected = sorted(
                fallback,
                key=lambda x: (
                    x["symbol_match_rank"],
                    0 if x["is_smart"] else 1,
                    abs(x["dte"] - TARGET_DTE_IDEAL),
                    -x["strike_count"]
                )
            )[0]
            IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
                "ticker": symbol,
                "status": "FALLBACK_CHAIN_SELECTED",
                "chain_count": len(chains),
                "usable_chain_count": len(usable),
                "fallback_count": len(fallback),
                "selected_expiry": selected["expiry"],
                "selected_dte": selected["dte"],
                "selected_exchange": getattr(selected["chain"], "exchange", None),
                "selected_trading_class": getattr(selected["chain"], "tradingClass", None),
                "selected_multiplier": getattr(selected["chain"], "multiplier", None),
                "chain_summaries": chain_summaries,
                "generated_at": now_iso(),
                "not_order_instruction": True,
            })

            return selected["chain"], selected["expiry"], selected["dte"]

        print(symbol, "sin expiración válida")
        IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
            "ticker": symbol,
            "status": "NO_VALID_EXPIRATION",
            "chain_count": len(chains),
            "usable_chain_count": len(usable),
            "chain_summaries": chain_summaries,
            "generated_at": now_iso(),
            "not_order_instruction": True,
        })
        return None, None, None

    except Exception as e:
        print(symbol, "CHAIN ERROR:", e)
        IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
            "ticker": symbol,
            "status": "CHAIN_ERROR",
            "error": str(e)[:500],
            "generated_at": now_iso(),
            "not_order_instruction": True,
        })
        return None, None, None


def qualify_option(symbol, expiry, strike, right, chain):
    try:
        trading_class = getattr(chain, "tradingClass", None)
        multiplier = getattr(chain, "multiplier", None)

        contract = Option(
            symbol=symbol,
            lastTradeDateOrContractMonth=expiry,
            strike=float(strike),
            right=right,
            exchange="SMART",
            currency="USD",
            multiplier=multiplier,
            tradingClass=trading_class
        )

        if COBERTURAS_RSP_WEEKLY and str(symbol or "").upper() == "RSP":
            return contract

        qualified = ib.qualifyContracts(contract)

        if qualified:
            return qualified[0]

        return contract

    except Exception as exc:
        print(symbol, "option qualify fallback:", exc)
        return contract if "contract" in locals() else None


def pick_put_strikes(strikes, stock_price):
    raw_puts = []

    for strike in strikes:
        distance = (strike - stock_price) / stock_price

        if -0.18 < distance < -0.05:
            if is_standard_strike(strike):
                raw_puts.append(strike)

    selected = sorted(
        raw_puts,
        key=lambda x: abs(abs((x - stock_price) / stock_price) - 0.10)
    )[:4]

    return selected


def pick_call_strikes(strikes, stock_price):
    raw_calls = []

    for strike in strikes:
        distance = (strike - stock_price) / stock_price

        if 0.03 < distance < 0.15:
            if is_standard_strike(strike):
                raw_calls.append(strike)

    selected = sorted(
        raw_calls,
        key=lambda x: abs(abs((x - stock_price) / stock_price) - 0.08)
    )[:4]

    return selected


def build_option_candidates(symbol, stock_price):
    chain, expiry, dte = get_option_chain(symbol)

    if chain is None:
        print(symbol, "sin cadena")
        return []

    strikes = sorted([
        float(strike)
        for strike in chain.strikes
        if strike is not None and float(strike) > 0
    ])

    if len(strikes) == 0:
        print(symbol, "sin strikes")
        return []

    puts = []
    calls = []

    if COBERTURAS_RSP_WEEKLY and str(symbol or "").upper() == "RSP":
        per_side = max(1, (MAX_OPTIONS_PER_SYMBOL + 1) // 2)
        if ENABLE_NAKED_PUTS:
            puts = pick_rsp_weekly_strikes(strikes, stock_price, "P", per_side)
        if ENABLE_COVERED_CALLS:
            calls = pick_rsp_weekly_strikes(strikes, stock_price, "C", per_side)
    else:
        if ENABLE_NAKED_PUTS:
            puts = pick_put_strikes(strikes, stock_price)

        if ENABLE_COVERED_CALLS:
            calls = pick_call_strikes(strikes, stock_price)

    valid = []
    invalid_count = 0
    contract_specs = []

    if COBERTURAS_RSP_WEEKLY and str(symbol or "").upper() == "RSP":
        per_side = max(1, (MAX_OPTIONS_PER_SYMBOL + 1) // 2)
        rsp_puts = puts[:per_side]
        rsp_calls = calls[:per_side]
        for index in range(max(len(rsp_puts), len(rsp_calls))):
            if index < len(rsp_puts):
                contract_specs.append((rsp_puts[index], "P", "NAKED_PUT"))
            if index < len(rsp_calls):
                contract_specs.append((rsp_calls[index], "C", "COVERED_CALL"))
    else:
        contract_specs.extend((strike, "P", "NAKED_PUT") for strike in puts)
        contract_specs.extend((strike, "C", "COVERED_CALL") for strike in calls)

    for strike, right, strategy in contract_specs:
        contract = qualify_option(
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            right=right,
            chain=chain
        )

        if contract:
            valid.append((contract, dte, strategy))
        else:
            invalid_count += 1

    print(
        f"{symbol} contratos válidos:",
        len(valid),
        "| inválidos filtrados:",
        invalid_count,
        "| expiry:",
        expiry,
        "| dte:",
        dte,
        "| chain exchange:",
        getattr(chain, "exchange", None),
        "| tradingClass:",
        getattr(chain, "tradingClass", None),
        "| multiplier:",
        getattr(chain, "multiplier", None)
    )
    IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
        "ticker": symbol,
        "status": "CONTRACT_CANDIDATES_BUILT",
        "stock_price": stock_price,
        "expiry": expiry,
        "dte": dte,
        "put_strikes_selected": puts,
        "call_strikes_selected": calls,
        "valid_contract_count": len(valid),
        "invalid_contract_count": invalid_count,
        "max_options_per_symbol": MAX_OPTIONS_PER_SYMBOL,
        "generated_at": now_iso(),
        "not_order_instruction": True,
    })

    return valid[:MAX_OPTIONS_PER_SYMBOL]


def _empty_option_market_data(error=None, source="OPTION_MARKET_DATA_ERROR"):
    out = {
        "bid": None,
        "ask": None,
        "last": None,
        "close": None,
        "market_price": None,
        "mid": None,
        "spread_pct": None,
        "spread": None,
        "greeks": {
            "iv": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None
        },
        "data_quality": "OPTION_MARKET_DATA_ERROR",
        "volume": None,
        "open_interest": None,
        "market_data_source": source,
    }
    if error:
        out["error"] = str(error)
    return out


def _request_option_market_data_once(contract, market_data_type, snapshot=False):
    ticker = None

    try:
        ib.reqMarketDataType(market_data_type)
        ticker = ib.reqMktData(
            contract,
            genericTickList="100,101,106",
            snapshot=bool(snapshot),
            regulatorySnapshot=False
        )

        ib.sleep(OPTION_SNAPSHOT_WAIT_SECONDS if snapshot else OPTION_MARKET_DATA_WAIT_SECONDS)

        greeks = option_greeks(ticker)
        quote = normalize_option_quote_fields(
            bid=getattr(ticker, "bid", None),
            ask=getattr(ticker, "ask", None),
            last=getattr(ticker, "last", None),
            close=getattr(ticker, "close", None),
            market_price=ticker.marketPrice(),
            greeks=greeks,
        )
        bid = quote["bid"]
        ask = quote["ask"]
        last = quote["last"]
        close = quote["close"]
        market_price = quote["market_price"]
        mid = quote["mid"]
        spread_pct = quote["spread_pct"]
        spread = quote["spread"]

        volume = clean(getattr(ticker, "volume", None))
        if getattr(contract, "right", "") == "P":
            option_volume = clean(getattr(ticker, "putVolume", None)) or volume
            open_interest = clean(getattr(ticker, "putOpenInterest", None))
        elif getattr(contract, "right", "") == "C":
            option_volume = clean(getattr(ticker, "callVolume", None)) or volume
            open_interest = clean(getattr(ticker, "callOpenInterest", None))
        else:
            option_volume = volume
            open_interest = None

        data_quality = quote["data_quality"]

        try:
            ib.cancelMktData(contract)
        except Exception:
            pass

        return {
            "bid": bid,
            "ask": ask,
            "last": last,
            "close": close,
            "market_price": market_price,
            "mid": mid,
            "spread_pct": spread_pct,
            "spread": spread,
            "greeks": greeks,
            "data_quality": data_quality,
            "volume": option_volume,
            "open_interest": open_interest,
            "market_data_source": (
                f"IBKR_OPTION_{'SNAPSHOT' if snapshot else 'STREAM'}_TYPE_{market_data_type}"
            ),
        }

    except Exception as e:
        try:
            if ticker is not None:
                ib.cancelMktData(contract)
        except Exception:
            pass

        return _empty_option_market_data(
            error=e,
            source=f"IBKR_OPTION_{'SNAPSHOT' if snapshot else 'STREAM'}_TYPE_{market_data_type}_ERROR",
        )


def request_option_market_data(contract):
    best = None
    attempts = []

    for market_data_type in OPTION_MARKET_DATA_TYPE_SEQUENCE:
        attempts.append(_request_option_market_data_once(contract, market_data_type, snapshot=False))

        if attempts[-1].get("data_quality") == "FULL_WITH_GREEKS":
            best = attempts[-1]
            break

        attempts.append(_request_option_market_data_once(contract, market_data_type, snapshot=True))

        if attempts[-1].get("data_quality") == "FULL_WITH_GREEKS":
            best = attempts[-1]
            break

    if best is None and attempts:
        best = max(attempts, key=option_market_data_score)

    try:
        ib.reqMarketDataType(MARKET_DATA_TYPE)
    except Exception:
        pass

    if not best:
        best = _empty_option_market_data()

    best["market_data_attempts"] = [
        {
            "source": item.get("market_data_source"),
            "data_quality": item.get("data_quality"),
            "score": option_market_data_score(item),
        }
        for item in attempts
    ]
    return best


def liquidity_decision_cap(data_quality, spread_pct, mid):
    if mid is None or mid <= 0:
        return "NO_OPERAR_SIN_PRECIO"

    if mid < MIN_OPTION_MID_FOR_RADAR:
        return "ESPERAR"

    if data_quality in ["NO_VALID_OPTION_PRICE", "OPTION_MARKET_DATA_ERROR"]:
        return "NO_OPERAR_SIN_PRECIO"

    if data_quality == "PRICE_ONLY_NO_GREEKS":
        return "WAIT_FOR_GREEKS"

    if data_quality == "PARTIAL_OPTION_DATA":
        return "WAIT_FOR_GREEKS"

    if data_quality == "PRICE_WITH_GREEKS_NO_BIDASK":
        return "RADAR"

    if data_quality == "FULL_WITH_GREEKS":
        if spread_pct is None:
            return "RADAR"

        if spread_pct > MAX_ACCEPTABLE_SPREAD_PCT_FOR_RADAR:
            return "ESPERAR"

        if spread_pct > MAX_ACCEPTABLE_SPREAD_PCT_FOR_OPERAR:
            return "RADAR"

        return "OPERAR_ALLOWED"

    return "ESPERAR"


def apply_decision_cap(raw_decision, decision_cap):
    if decision_cap == "NO_OPERAR_SIN_PRECIO":
        return "NO_OPERAR_SIN_PRECIO"

    if decision_cap == "WAIT_FOR_GREEKS":
        return "WAIT_FOR_GREEKS"

    if decision_cap == "ESPERAR":
        return "ESPERAR"

    if decision_cap == "RADAR":
        if raw_decision == "OPERAR":
            return "RADAR"
        return raw_decision

    if decision_cap == "OPERAR_ALLOWED":
        return raw_decision

    return "ESPERAR"


def _score_option_candidate_core(strategy, option_type, strike, stock_price, dte, greeks, mid, data_quality, spread_pct):
    score = 50
    reason = []

    delta = greeks.get("delta")
    iv = greeks.get("iv")

    if mid is None or mid <= 0:
        score -= 50
        reason.append("sin precio válido de opción")

    elif mid < MIN_OPTION_MID_FOR_RADAR:
        score -= 25
        reason.append("prima demasiado baja")

    elif mid >= MIN_OPTION_MID_FOR_OPERAR:
        score += 5
        reason.append("prima disponible")

    if data_quality == "FULL_WITH_GREEKS":
        score += 10
        reason.append("data completa con griegas")

    elif data_quality == "PRICE_WITH_GREEKS_NO_BIDASK":
        score -= 5
        reason.append("griegas disponibles sin bid/ask completo")

    elif data_quality == "PRICE_ONLY_NO_GREEKS":
        score -= 25
        reason.append("sin delta ni IV")

    elif data_quality == "PARTIAL_OPTION_DATA":
        score -= 20
        reason.append("data parcial")

    elif data_quality in ["NO_VALID_OPTION_PRICE", "OPTION_MARKET_DATA_ERROR"]:
        score -= 40
        reason.append("sin precio válido o error de market data")

    if spread_pct is not None:
        if spread_pct <= MAX_ACCEPTABLE_SPREAD_PCT_FOR_OPERAR:
            score += 10
            reason.append("spread razonable")

        elif spread_pct <= MAX_ACCEPTABLE_SPREAD_PCT_FOR_RADAR:
            score -= 5
            reason.append("spread moderado")

        else:
            score -= 20
            reason.append("spread amplio")
    else:
        reason.append("spread no disponible")

    if strategy == "NAKED_PUT":
        if delta is not None:
            abs_delta = abs(delta)

            if NAKED_PUT_READY_DELTA_MIN <= abs_delta <= NAKED_PUT_READY_DELTA_MAX:
                score += 25
                reason.append("delta favorable naked put")

            elif NAKED_PUT_REVIEW_DELTA_MIN <= abs_delta <= NAKED_PUT_REVIEW_DELTA_MAX:
                score += 10
                reason.append("delta util pero fuera de readiness naked put")

            elif abs_delta < NAKED_PUT_REVIEW_DELTA_MIN:
                score -= 5
                reason.append("delta muy bajo, prima probablemente baja")

            else:
                score -= 20
                reason.append("delta alto para naked put")
        else:
            score -= 20
            reason.append("delta no disponible")

        if strike < stock_price:
            score += 10
            reason.append("strike OTM")

        else:
            score -= 30
            reason.append("strike no está OTM para naked put")

    if strategy == "COVERED_CALL":
        if delta is not None:
            abs_delta = abs(delta)

            if COVERED_CALL_READY_DELTA_MIN <= abs_delta <= COVERED_CALL_READY_DELTA_MAX:
                score += 25
                reason.append("delta favorable covered call")

            elif COVERED_CALL_REVIEW_DELTA_MIN <= abs_delta <= COVERED_CALL_REVIEW_DELTA_MAX:
                score += 10
                reason.append("delta util pero fuera de readiness covered call")

            elif abs_delta < COVERED_CALL_REVIEW_DELTA_MIN:
                score -= 5
                reason.append("delta muy bajo, prima probablemente baja")

            else:
                score -= 20
                reason.append("call muy cercana o agresiva")
        else:
            score -= 20
            reason.append("delta no disponible")

        if strike > stock_price:
            score += 10
            reason.append("call OTM")

        else:
            score -= 30
            reason.append("call no está OTM")

    if iv is not None:
        if iv >= 0.35:
            score += 10
            reason.append("IV atractiva")

        elif 0.18 <= iv < 0.35:
            score += 5
            reason.append("IV razonable")

        elif iv < 0.15:
            score -= 10
            reason.append("IV baja")
    else:
        score -= 15
        reason.append("IV no disponible")

    if dte is not None and NAKED_PUT_READY_DTE_MIN <= dte <= NAKED_PUT_READY_DTE_MAX:
        score += 10
        reason.append("DTE adecuado para readiness")

    elif dte is not None and NAKED_PUT_REVIEW_DTE_MIN <= dte <= NAKED_PUT_REVIEW_DTE_MAX:
        score += 3
        reason.append("DTE util pero fuera de readiness")

    elif dte is not None:
        score -= 10
        reason.append("DTE fuera de rango ideal")

    else:
        score -= 10
        reason.append("DTE no disponible")

    score = max(0, min(100, score))

    if score >= 85:
        raw_decision = "OPERAR"

    elif score >= 65:
        raw_decision = "RADAR"

    elif data_quality in ["PRICE_ONLY_NO_GREEKS", "PARTIAL_OPTION_DATA"]:
        raw_decision = "WAIT_FOR_GREEKS"

    else:
        raw_decision = "ESPERAR"

    decision_cap = liquidity_decision_cap(
        data_quality=data_quality,
        spread_pct=spread_pct,
        mid=mid
    )

    final_decision = apply_decision_cap(
        raw_decision=raw_decision,
        decision_cap=decision_cap
    )

    if final_decision != raw_decision:
        reason.append(f"decisión limitada por calidad/liquidez: {decision_cap}")

    return score, final_decision, "; ".join(reason), decision_cap




# ============================================================
# COBERTURAS RSP MARGIN PREVIEW (IBKR WHAT-IF, NO TRANSMIT)
# ============================================================

COBERTURAS_RSP_MARGIN_PREVIEW_PATH = _v283_Path("runtime") / "coberturas_rsp_margin_preview_latest.json"


def margin_number(value):
    if value in [None, "", "None"]:
        return None
    try:
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        token = text.split()[0]
        number = float(token)
        if math.isnan(number) or math.isinf(number):
            return None
        return round(number, 4)
    except Exception:
        return None


def rsp_best_row(rows, strategy):
    strategy = str(strategy or "").upper()
    valid = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or row.get("symbol") or "").upper() != "RSP":
            continue
        if str(row.get("strategy") or row.get("strategy_hint") or "").upper() != strategy:
            continue
        if row.get("strike") is None or not row.get("expiration"):
            continue
        valid.append(row)
    if not valid:
        return None
    return sorted(
        valid,
        key=lambda row: (
            1 if row.get("mid") is not None else 0,
            safe_round(row.get("score"), 0) or 0,
            -(safe_round(row.get("strike"), 0) or 0) if strategy == "NAKED_PUT" else safe_round(row.get("strike"), 0) or 0,
        ),
        reverse=True,
    )[0]


def rsp_option_contract_from_row(row):
    right = "P" if str(row.get("strategy") or "").upper() == "NAKED_PUT" else "C"
    return Option(
        symbol="RSP",
        lastTradeDateOrContractMonth=str(row.get("expiration")),
        strike=float(row.get("strike")),
        right=right,
        exchange="SMART",
        currency="USD",
        multiplier="100",
        tradingClass="RSP",
    )


def rsp_order_limit_price(row, fallback=0.01):
    for key in ["mid", "bid", "ask", "last", "market_price"]:
        value = clean(row.get(key))
        if value is not None:
            return max(0.01, value)
    return fallback


def resolve_contract_for_margin(contract, timeout=4):
    previous_timeout = getattr(ib, "RequestTimeout", 0)
    try:
        ib.RequestTimeout = timeout
        try:
            qualified = ib.qualifyContracts(contract)
            if qualified:
                return qualified[0]
        except Exception:
            pass
        try:
            details = ib.reqContractDetails(contract)
            if details:
                return details[0].contract
        except Exception:
            pass
        return contract
    finally:
        try:
            ib.RequestTimeout = previous_timeout
        except Exception:
            pass


def order_state_payload(order_state):
    return {
        "status": getattr(order_state, "status", None),
        "init_margin_before": margin_number(getattr(order_state, "initMarginBefore", None)),
        "maint_margin_before": margin_number(getattr(order_state, "maintMarginBefore", None)),
        "equity_with_loan_before": margin_number(getattr(order_state, "equityWithLoanBefore", None)),
        "init_margin_change": margin_number(getattr(order_state, "initMarginChange", None)),
        "maint_margin_change": margin_number(getattr(order_state, "maintMarginChange", None)),
        "equity_with_loan_change": margin_number(getattr(order_state, "equityWithLoanChange", None)),
        "init_margin_after": margin_number(getattr(order_state, "initMarginAfter", None)),
        "maint_margin_after": margin_number(getattr(order_state, "maintMarginAfter", None)),
        "equity_with_loan_after": margin_number(getattr(order_state, "equityWithLoanAfter", None)),
        "commission": margin_number(getattr(order_state, "commission", None)),
        "min_commission": margin_number(getattr(order_state, "minCommission", None)),
        "max_commission": margin_number(getattr(order_state, "maxCommission", None)),
        "commission_currency": getattr(order_state, "commissionCurrency", None),
        "warning_text": str(getattr(order_state, "warningText", "") or ""),
        "completed_status": str(getattr(order_state, "completedStatus", "") or ""),
        "completed_time": str(getattr(order_state, "completedTime", "") or ""),
        "raw_init_margin_change": str(getattr(order_state, "initMarginChange", "") or ""),
        "raw_maint_margin_change": str(getattr(order_state, "maintMarginChange", "") or ""),
    }


def whatif_margin_preview(contract, order, label):
    selected_account = _bridge_selected_ibkr_account()
    order.whatIf = True
    order.transmit = False
    if selected_account:
        order.account = selected_account
    preview = {
        "label": label,
        "status": "UNKNOWN",
        "account_alias": BRIDGE_ACCOUNT_ALIAS,
        "account_scope": BRIDGE_ACCOUNT_SCOPE,
        "selected_account_configured": bool(selected_account),
        "selected_account_printed": False,
        "order_type": getattr(order, "orderType", None),
        "action": getattr(order, "action", None),
        "quantity": safe_round(getattr(order, "totalQuantity", None), 4),
        "limit_price": safe_round(getattr(order, "lmtPrice", None), 4),
        "what_if": True,
        "transmit": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    try:
        state = ib.whatIfOrder(contract, order)
        preview.update(order_state_payload(state))
        preview["status"] = "MARGIN_PREVIEW_READY" if preview.get("init_margin_change") is not None else "MARGIN_PREVIEW_PARTIAL"
        if preview["status"] == "MARGIN_PREVIEW_PARTIAL" and getattr(order, "orderType", "") == "LMT":
            retry_order = MarketOrder(getattr(order, "action", ""), getattr(order, "totalQuantity", 0))
            retry_order.whatIf = True
            retry_order.transmit = False
            if selected_account:
                retry_order.account = selected_account
            try:
                retry_state = ib.whatIfOrder(contract, retry_order)
                retry_payload = order_state_payload(retry_state)
                preview["market_order_retry"] = retry_payload
                if retry_payload.get("init_margin_change") is not None:
                    preview.update(retry_payload)
                    preview["status"] = "MARGIN_PREVIEW_READY"
                    preview["order_type_used_for_margin"] = "MKT_RETRY"
            except Exception as retry_exc:
                preview["market_order_retry_error"] = str(retry_exc)[:500]
    except Exception as exc:
        preview.update({
            "status": "MARGIN_PREVIEW_FAILED",
            "error": str(exc)[:500],
        })
    return preview


def build_rsp_margin_previews(option_rows):
    payload = {
        "margin_preview_version": "coberturas_rsp_margin_preview_v1",
        "source": "IBKR_WHAT_IF_ORDER_PREVIEW",
        "generated_at": now_iso(),
        "ticker": "RSP",
        "preview_count": 0,
        "previews": [],
        "warnings": [],
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    if not COBERTURAS_RSP_WEEKLY:
        payload["status"] = "SKIPPED_NOT_COBERTURAS_RSP_WEEKLY"
        return payload

    put_row = rsp_best_row(option_rows, "NAKED_PUT")
    call_row = rsp_best_row(option_rows, "COVERED_CALL")

    if put_row:
        put_contract = resolve_contract_for_margin(rsp_option_contract_from_row(put_row))
        put_order = LimitOrder("SELL", 1, rsp_order_limit_price(put_row))
        preview = whatif_margin_preview(put_contract, put_order, "SELL_PUT")
        preview.update({
            "strategy": "SELL_PUT",
            "ticker": "RSP",
            "expiration": put_row.get("expiration"),
            "strike": put_row.get("strike"),
            "premium_reference": rsp_order_limit_price(put_row),
            "candidate_data_quality": put_row.get("data_quality"),
        })
        payload["previews"].append(preview)
    else:
        payload["warnings"].append("NO_SELL_PUT_CANDIDATE_FOR_MARGIN")

    if call_row:
        stock = resolve_contract_for_margin(stock_contract("RSP"))
        call_contract = resolve_contract_for_margin(rsp_option_contract_from_row(call_row))
        stock_conid = int(getattr(stock, "conId", 0) or 0)
        call_conid = int(getattr(call_contract, "conId", 0) or 0)
        if stock_conid and call_conid:
            combo = Contract()
            combo.symbol = "RSP"
            combo.secType = "BAG"
            combo.exchange = "SMART"
            combo.currency = "USD"
            combo.comboLegs = [
                ComboLeg(conId=stock_conid, ratio=100, action="BUY", exchange="SMART"),
                ComboLeg(conId=call_conid, ratio=1, action="SELL", exchange="SMART"),
            ]
            stock_price = clean(call_row.get("price")) or clean(call_row.get("underlying_price")) or 0
            call_credit = rsp_order_limit_price(call_row)
            combo_limit = max(0.01, (stock_price * 100) - (call_credit * 100)) if stock_price else 0.01
            combo_order = LimitOrder("BUY", 1, combo_limit)
            preview = whatif_margin_preview(combo, combo_order, "BUY_100_SELL_CALL")
            preview.update({
                "strategy": "BUY_100_SELL_CALL",
                "ticker": "RSP",
                "expiration": call_row.get("expiration"),
                "strike": call_row.get("strike"),
                "premium_reference": call_credit,
                "underlying_reference": stock_price,
                "candidate_data_quality": call_row.get("data_quality"),
                "combo_stock_conid_available": True,
                "combo_option_conid_available": True,
            })
            payload["previews"].append(preview)
        else:
            payload["previews"].append({
                "label": "BUY_100_SELL_CALL",
                "strategy": "BUY_100_SELL_CALL",
                "ticker": "RSP",
                "expiration": call_row.get("expiration"),
                "strike": call_row.get("strike"),
                "status": "MARGIN_PREVIEW_FAILED",
                "error": "COMBO_CONID_MISSING",
                "combo_stock_conid_available": bool(stock_conid),
                "combo_option_conid_available": bool(call_conid),
                "execution_authorized": False,
                "not_order_instruction": True,
            })
    else:
        payload["warnings"].append("NO_BUY_WRITE_CALL_CANDIDATE_FOR_MARGIN")

    payload["preview_count"] = len(payload["previews"])
    payload["status"] = "MARGIN_PREVIEW_READY" if any(p.get("status") == "MARGIN_PREVIEW_READY" for p in payload["previews"]) else "MARGIN_PREVIEW_INCOMPLETE"
    return payload


def write_rsp_margin_previews(option_rows):
    payload = build_rsp_margin_previews(option_rows)
    try:
        COBERTURAS_RSP_MARGIN_PREVIEW_PATH.parent.mkdir(exist_ok=True)
        COBERTURAS_RSP_MARGIN_PREVIEW_PATH.write_text(_v283_json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    except Exception as exc:
        print("RSP MARGIN PREVIEW WRITE ERROR:", exc)
    print(
        "RSP MARGIN PREVIEW"
        f" | status:{payload.get('status')}"
        f" | previews:{payload.get('preview_count')}"
        f" | path:{COBERTURAS_RSP_MARGIN_PREVIEW_PATH}"
    )
    return payload

def send_options_intelligence():
    print("\n=== OPTIONS INTELLIGENCE V18_1_REMOTE_SNAPSHOT_INGEST ===\n")
    IBKR_CHAIN_DIAGNOSTIC_EVENTS.clear()
    cycle_option_rows = []
    _, technical_snapshot, _ = _bridge_option_universe_runtime_context()
    symbol_plan = build_dynamic_option_symbol_plan(OPTION_SYMBOLS, technical_snapshot)
    selected_symbols = symbol_plan.get("selected_symbols") or []
    plan_by_symbol = {
        item.get("symbol"): item
        for item in symbol_plan.get("ranked") or []
        if isinstance(item, dict) and item.get("symbol")
    }
    remaining_contract_budget = MAX_TOTAL_OPTION_CONTRACTS_PER_RUN

    print(
        "OPTION UNDERLYING UNIVERSE"
        f" | dynamic:{symbol_plan.get('enabled')}"
        f" | candidates:{symbol_plan.get('candidate_count')}"
        f" | selected:{','.join(selected_symbols) if selected_symbols else 'NONE'}"
        f" | max_symbols:{symbol_plan.get('max_symbols_per_run')}"
        f" | max_contracts:{MAX_TOTAL_OPTION_CONTRACTS_PER_RUN}"
    )

    for symbol in selected_symbols:
        try:
            if remaining_contract_budget <= 0:
                IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
                    "ticker": symbol,
                    "status": "OPTION_CONTRACT_BUDGET_EXHAUSTED",
                    "max_total_option_contracts_per_run": MAX_TOTAL_OPTION_CONTRACTS_PER_RUN,
                    "generated_at": now_iso(),
                    "not_order_instruction": True,
                })
                break

            snap = get_price_snapshot(symbol)

            if not snap or not snap.get("price"):
                print(symbol, "sin precio para opciones")
                continue

            stock_price = snap["price"]

            candidates = build_option_candidates(symbol, stock_price)

            if not candidates:
                print(symbol, "sin opciones candidatas")
                continue

            if len(candidates) > remaining_contract_budget:
                IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
                    "ticker": symbol,
                    "status": "OPTION_CONTRACT_BUDGET_APPLIED",
                    "candidate_contract_count": len(candidates),
                    "contracts_allowed": remaining_contract_budget,
                    "max_total_option_contracts_per_run": MAX_TOTAL_OPTION_CONTRACTS_PER_RUN,
                    "generated_at": now_iso(),
                    "not_order_instruction": True,
                })
                candidates = candidates[:remaining_contract_budget]

            remaining_contract_budget -= len(candidates)
            rank_entry = plan_by_symbol.get(symbol) or {}

            for item in candidates:
                try:
                    contract = item[0]
                    dte = item[1]
                    strategy = item[2]

                    try:
                        with bridge_step_timeout(
                            OPTION_CONTRACT_MARKET_DATA_TIMEOUT_SECONDS,
                            f"option market data {symbol} {strategy} {contract.strike}",
                        ):
                            option_data = request_option_market_data(contract)
                    except BridgeStepTimeout as exc:
                        print(f"{symbol} {strategy} {contract.strike} option TIMEOUT: {exc}")
                        option_data = _empty_option_market_data(
                            error=exc,
                            source="OPTION_CONTRACT_TIMEOUT",
                        )

                    bid = option_data.get("bid")
                    ask = option_data.get("ask")
                    last = option_data.get("last")
                    close = option_data.get("close")
                    market_price = option_data.get("market_price")
                    mid = option_data.get("mid")
                    spread_pct = option_data.get("spread_pct")
                    spread = option_data.get("spread")
                    greeks = option_data.get("greeks")
                    data_quality = option_data.get("data_quality")
                    volume = option_data.get("volume")
                    open_interest = option_data.get("open_interest")
                    option_market_data_source = option_data.get("market_data_source")
                    option_market_data_attempts = option_data.get("market_data_attempts")

                    if not SEND_OPTIONS_WITHOUT_GREEKS:
                        if data_quality != "FULL_WITH_GREEKS":
                            print(
                                f"{symbol} {strategy} {contract.strike} "
                                f"omitida por data_quality:{data_quality}"
                            )
                            continue

                    option_type = "PUT" if contract.right == "P" else "CALL"

                    score, decision, reason, decision_cap = score_option_candidate(
                        strategy=strategy,
                        option_type=option_type,
                        strike=contract.strike,
                        stock_price=stock_price,
                        dte=dte,
                        greeks=greeks,
                        mid=mid,
                        data_quality=data_quality,
                        spread_pct=spread_pct
                    )

                    required_execution_fields = {
                        "bid": bid,
                        "ask": ask,
                        "spread": spread,
                        "spread_pct": spread_pct,
                        "strike": contract.strike,
                        "expiration": contract.lastTradeDateOrContractMonth,
                        "dte": dte,
                        "delta": greeks.get("delta"),
                    }
                    missing_confirmations = [
                        key
                        for key, value in required_execution_fields.items()
                        if value is None
                    ]
                    manual_review_ready = (
                        len(missing_confirmations) == 0
                        and decision in ["OPERAR", "ENTRY", "ENTRY_READY"]
                    )
                    option_discard_reasons = ibkr_diagnostics.option_discard_reasons({
                        "bid": bid,
                        "ask": ask,
                        "spread": spread,
                        "spread_pct": spread_pct,
                        "delta": greeks.get("delta"),
                        "iv": greeks.get("iv"),
                        "volume": volume,
                        "open_interest": open_interest,
                        "data_quality": data_quality,
                        "decision_cap": decision_cap,
                        "manual_review_ready": manual_review_ready,
                    })

                    tv_context = tradingview_context_stub(symbol)

                    payload = {
                        "ticker": symbol,
                        "timeframe": "options",
                        "setup": f"IBKR_{strategy}_V15",
                        "trend": "",
                        "score": score,
                        "price": stock_price,
                        "underlying_price_source": snap.get("price_source"),
                        "source": "IBKR_OPTIONS_V18_1_REMOTE_SNAPSHOT_INGEST",
                        "asset_class": "OPTION",
                        "engine_layer": "IBKR_OPTIONS_INTELLIGENCE",
                        "integration_ready_for_tradingview": True,
                        "data_quality": data_quality,
                        "decision_cap": decision_cap,
                        "decision": "ENTRY_READY" if manual_review_ready else decision,
                        "final_decision": "ENTRY_READY" if manual_review_ready else decision,
                        "option_symbol": contract.localSymbol,
                        "local_symbol": contract.localSymbol,
                        "option_type": option_type,
                        "strategy_hint": strategy,
                        "strategy_decision": decision,
                        "strategy_reason": reason,
                        "strike": contract.strike,
                        "expiration": contract.lastTradeDateOrContractMonth,
                        "dte": dte,
                        "bid": bid,
                        "ask": ask,
                        "last": last,
                        "close": close,
                        "market_price": market_price,
                        "mid": mid,
                        "spread_pct": spread_pct,
                        "spread": spread,
                        "implied_volatility": greeks["iv"],
                        "iv": greeks["iv"],
                        "delta": greeks["delta"],
                        "gamma": greeks["gamma"],
                        "theta": greeks["theta"],
                        "vega": greeks["vega"],
                        "volume": volume,
                        "open_interest": open_interest,
                        "option_market_data_source": option_market_data_source,
                        "option_market_data_attempts": option_market_data_attempts,
                        "option_discard_reasons": option_discard_reasons,
                        "discarded_for_manual_review": bool(option_discard_reasons),
                        "underlying_universe_rank": rank_entry.get("rank"),
                        "underlying_rank_score": rank_entry.get("score"),
                        "underlying_rank_triggers": rank_entry.get("triggers") or [],
                        "underlying_rank_reasons": rank_entry.get("reasons") or [],
                        "can_operate": False,
                        "manual_review_ready": manual_review_ready,
                        "not_order_instruction": True,
                        "missing_confirmations": missing_confirmations,
                        "recommendation": "LISTO_PARA_REVISION_MANUAL" if manual_review_ready else "ESPERAR_DATOS_EJECUTABLES",
                        "reason": reason,
                        "v30_contract_enrichment": True,
                        "v30_required_fields_complete": len(missing_confirmations) == 0,
                        "moneyness_pct": safe_round(
                            (contract.strike / stock_price - 1) * 100,
                            2
                        ),
                        "received_at_bridge": now_iso(),
                        **tv_context
                    }

                    v17_store_row(payload)
                    cycle_option_rows.append(payload)

                    status = post(payload)

                    print(
                        f"{symbol} {strategy} "
                        f"{contract.strike} exp:{contract.lastTradeDateOrContractMonth} "
                        f"mid:{mid} bid:{bid} ask:{ask} spread:{spread} spread_pct:{spread_pct} "
                        f"delta:{greeks['delta']} iv:{greeks['iv']} "
                        f"quality:{data_quality} cap:{decision_cap} "
                        f"score:{score} decision:{decision} "
                        f"underlying_source:{snap.get('price_source')} "
                        f"option_source:{option_market_data_source} "
                        f"status:{status}"
                    )

                except Exception as e:
                    print(symbol, "OPTION ROW ERROR:", e)

        except Exception as e:
            print(symbol, "OPTIONS ERROR:", e)
            IBKR_CHAIN_DIAGNOSTIC_EVENTS.append({
                "ticker": symbol,
                "status": "OPTIONS_INTELLIGENCE_ERROR",
                "error": str(e)[:500],
                "generated_at": now_iso(),
                "not_order_instruction": True,
            })
    if COBERTURAS_RSP_WEEKLY:
        write_rsp_margin_previews(cycle_option_rows)

    diagnostic = ibkr_diagnostics.build_cycle_diagnostic(
        symbols=list(selected_symbols),
        chain_events=list(IBKR_CHAIN_DIAGNOSTIC_EVENTS),
        option_rows=cycle_option_rows,
        generated_at=now_iso(),
        symbol_plan=symbol_plan,
    )
    saved = ibkr_diagnostics.write_cycle_diagnostic(diagnostic)
    print(
        "IBKR CHAIN COVERAGE DIAGNOSTIC"
        f" | rows:{diagnostic.get('option_row_count')}"
        f" | gap:{diagnostic.get('primary_gap')}"
        f" | path:{saved.get('path')}"
    )
    return diagnostic


# ============================================================
# MAIN LOOP
# ============================================================




if not connect_ibkr_with_retries():
    raise SystemExit(30)


set_market_data_type()

print("")


# ============================================================
# SUPER ENGINE BOLSA — V17.1 SUMMARY STORE
# ============================================================

V17_SUMMARY_ROWS = []

def v17_store_row(row):
    try:
        if isinstance(row, dict):
            V17_SUMMARY_ROWS.append(row)
    except Exception:
        pass
    return row

def v17_store_rows(rows):
    try:
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    V17_SUMMARY_ROWS.append(r)
        elif isinstance(rows, dict):
            V17_SUMMARY_ROWS.append(rows)
    except Exception:
        pass
    return rows

def v17_reset_summary_rows():
    try:
        V17_SUMMARY_ROWS.clear()
    except Exception:
        pass






# ============================================================
# SUPER ENGINE BOLSA — V18.1 REMOTE SNAPSHOT INGEST CLIENT
# ============================================================

import os as _v18_1_os
import urllib.request as _v18_1_urllib_request
import urllib.error as _v18_1_urllib_error

V18_1_REMOTE_INGEST_URL = _v18_1_os.getenv(
    "DECISION_DESK_INGEST_URL",
    "https://trading-engine-p097.onrender.com/decision_desk/ingest"
)

V18_1_INGEST_TOKEN = _v18_1_os.getenv("DECISION_DESK_INGEST_TOKEN", "")

def v18_1_post_decision_snapshot(payload):
    """
    V18.1:
    Envía el snapshot generado localmente por ibkr_bridge.py hacia Render,
    para que /decision_desk, /decision_desk/{ticker} y /decision_desk/health
    puedan mostrar datos reales.
    """
    try:
        if not payload or not isinstance(payload, dict):
            return {"posted": False, "reason": "empty_payload"}

        body = _v18_json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SuperEngineBolsa-V18.1",
        }

        if V18_1_INGEST_TOKEN:
            headers["X-Decision-Desk-Token"] = V18_1_INGEST_TOKEN

        req = _v18_1_urllib_request.Request(
            V18_1_REMOTE_INGEST_URL,
            data=body,
            headers=headers,
            method="POST",
        )

        with _v18_1_urllib_request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return {
                "posted": True,
                "status": getattr(resp, "status", None),
                "response": raw[:300],
            }

    except Exception as e:
        return {
            "posted": False,
            "error": str(e),
            "url": V18_1_REMOTE_INGEST_URL,
        }

# ============================================================
# SUPER ENGINE BOLSA — V18 OPERATIONAL DECISION API HELPERS
# ============================================================

import json as _v18_json
from pathlib import Path as _v18_Path
from datetime import datetime as _v18_datetime, timezone as _v18_timezone

V18_SNAPSHOT_PATH = _v18_Path("runtime/decision_desk_snapshot.json")

def v18_safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def v18_normalize_decision(raw):
    try:
        d = str(raw or "").upper().strip()
    except Exception:
        d = ""

    if d in ["ENTRY", "ENTRY_READY", "ENTRY_OPPORTUNITY", "OPERAR", "TRADE"]:
        return "ENTRY"
    if d in ["MANAGE_POSITION", "MANAGE", "GESTION", "REVISAR_GESTION"]:
        return "MANAGE_POSITION"
    if d in ["RADAR", "WATCH", "PREPARATION", "PREPARACION"]:
        return "RADAR"
    if d in ["WAIT_FOR_GREEKS", "WAIT_GREEKS"]:
        return "WAIT_GREEKS"
    if d in ["WAIT_FOR_DATA", "MISSING_DATA", "WAIT_DATA"]:
        return "WAIT_DATA"
    if d in ["BLOCKED", "NO_TRADE", "REJECTED"]:
        return "BLOCKED"
    if d in ["ESPERAR", "WAIT"]:
        return "WAIT_DATA"

    return d or "WAIT_DATA"

def v18_missing_confirmations(row):
    missing = []

    quality = str(row.get("data_quality") or row.get("quality") or "").upper()
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))

    if "NO_BIDASK" in quality:
        missing.append("bid_ask")
        missing.append("spread")

    if "PRICE_ONLY" in quality:
        missing.append("greeks")
        missing.append("bid_ask")
        missing.append("spread")

    if decision == "WAIT_GREEKS":
        if "greeks" not in missing:
            missing.append("greeks")

    if decision == "WAIT_DATA":
        if "data_confirmation" not in missing:
            missing.append("data_confirmation")

    if row.get("price") in [None, "", "None"]:
        missing.append("price")

    for field in [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
    ]:
        if row.get(field) in [None, "", "None"]:
            missing.append(field)

    try:
        bid = v18_safe_float(row.get("bid"), 0)
        ask = v18_safe_float(row.get("ask"), 0)
        if bid <= 0:
            missing.append("bid")
        if ask <= 0:
            missing.append("ask")
        if bid > 0 and ask > 0 and ask < bid:
            missing.append("bid_ask_order")
    except Exception:
        pass

    # Deduplicar preservando orden
    final = []
    for x in missing:
        if x not in final:
            final.append(x)

    return final

def v18_manual_review_ready(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    missing = v18_missing_confirmations(row)
    score = v18_safe_float(row.get("score"), 0)

    if decision != "ENTRY":
        return False

    if score < 80:
        return False

    if missing:
        return False

    return True

def v18_can_operate(row):
    return False

def v18_recommendation(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    missing = v18_missing_confirmations(row)
    manual_review_ready = v18_manual_review_ready(row)

    if manual_review_ready:
        return "Listo para revision manual. Validar tamano, riesgo y confirmacion final en TWS. No es orden ni autorizacion de ejecucion."

    if decision == "MANAGE_POSITION":
        return "Prioridad de gestión. Revisar posición abierta antes de abrir nuevas operaciones."

    if decision == "RADAR":
        if missing:
            return "Mantener en radar. No operar directo hasta confirmar: " + ", ".join(missing) + "."
        return "Mantener en radar. Aún no es entrada confirmada."

    if decision == "WAIT_GREEKS":
        return "Esperar. Faltan griegas o datos suficientes para validar la operación."

    if decision == "WAIT_DATA":
        return "Esperar. Faltan datos críticos o confirmación suficiente."

    if decision == "BLOCKED":
        return "Bloqueado. No operar bajo las condiciones actuales."

    return "Esperar. No hay ventaja operativa suficiente."

def v18_reason(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    quality = str(row.get("data_quality") or row.get("quality") or "UNKNOWN")
    score = v18_safe_float(row.get("score"), 0)
    missing = v18_missing_confirmations(row)

    if decision == "RADAR" and score >= 80:
        if missing:
            return f"Score alto y datos parciales útiles, pero faltan confirmaciones: {', '.join(missing)}."
        return "Score alto, pero la señal permanece en radar y no en entrada."

    if decision == "WAIT_GREEKS":
        return "La oportunidad requiere griegas completas antes de tomar decisión."

    if decision == "WAIT_DATA":
        return "La oportunidad requiere más datos antes de tomar decisión."

    if decision == "BLOCKED":
        return "La operación fue bloqueada por calidad, liquidez, spread o reglas de seguridad."

    if decision == "ENTRY":
        return "La oportunidad cumple criterios principales de entrada, sujeto a gestión de riesgo."

    return f"Decisión {decision} con calidad de datos {quality}."

def v18_compact_row(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))

    compact = {
        "ticker": str(row.get("ticker") or row.get("symbol") or "UNKNOWN"),
        "strategy": str(row.get("strategy") or row.get("strategy_hint") or row.get("setup") or "UNKNOWN"),
        "decision": decision,
        "score": v18_safe_float(row.get("score"), 0),
        "price": row.get("price") or row.get("mid") or row.get("last"),
        "data_quality": row.get("data_quality") or row.get("quality") or "UNKNOWN",
        "can_operate": False,
        "manual_review_ready": False,
        "not_order_instruction": True,
        "missing_confirmations": [],
        "recommendation": "",
        "reason": "",
    }

    for field in [
        "strike",
        "expiration",
        "dte",
        "bid",
        "ask",
        "mid",
        "spread",
        "spread_pct",
        "delta",
        "gamma",
        "theta",
        "vega",
        "iv",
        "implied_volatility",
        "volume",
        "open_interest",
        "option_symbol",
        "local_symbol",
        "option_type",
        "decision_cap",
        "v30_contract_enrichment",
        "v30_required_fields_complete",
    ]:
        if field in row:
            compact[field] = row.get(field)

    compact["missing_confirmations"] = v18_missing_confirmations(compact | row)
    compact["manual_review_ready"] = v18_manual_review_ready(compact | row)
    compact["can_operate"] = False
    compact["not_order_instruction"] = True
    compact["recommendation"] = v18_recommendation(compact | row)
    compact["reason"] = v18_reason(compact | row)

    return compact

def v18_priority_rank(row):
    decision = v18_normalize_decision(row.get("decision"))
    score = v18_safe_float(row.get("score"), 0)

    decision_weight = {
        "MANAGE_POSITION": 500,
        "ENTRY": 400,
        "RADAR": 300,
        "WAIT_GREEKS": 150,
        "WAIT_DATA": 100,
        "BLOCKED": 0,
    }.get(decision, 50)

    return decision_weight + score

def v18_build_decision_payload(rows=None):
    try:
        if rows is None:
            rows = []

        clean_rows = []
        seen = set()

        for row in rows:
            if not isinstance(row, dict):
                continue

            c = v18_compact_row(row)
            key = (
                c.get("ticker"),
                c.get("strategy"),
                c.get("decision"),
                str(c.get("price")),
                str(c.get("score")),
            )

            if key in seen:
                continue

            seen.add(key)
            clean_rows.append(c)

        clean_rows.sort(key=v18_priority_rank, reverse=True)

        summary = {
            "entry": sum(1 for r in clean_rows if r["decision"] == "ENTRY"),
            "manage_position": sum(1 for r in clean_rows if r["decision"] == "MANAGE_POSITION"),
            "radar": sum(1 for r in clean_rows if r["decision"] == "RADAR"),
            "wait_greeks": sum(1 for r in clean_rows if r["decision"] == "WAIT_GREEKS"),
            "wait_data": sum(1 for r in clean_rows if r["decision"] == "WAIT_DATA"),
            "blocked": sum(1 for r in clean_rows if r["decision"] == "BLOCKED"),
            "total": len(clean_rows),
        }

        by_ticker = {}
        by_strategy = {}

        for r in clean_rows:
            ticker = r["ticker"]
            strategy = r["strategy"]
            decision = r["decision"]

            by_ticker.setdefault(ticker, {
                "ticker": ticker,
                "total": 0,
                "entry": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "best": None,
            })

            by_strategy.setdefault(strategy, {
                "strategy": strategy,
                "total": 0,
                "entry": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "best": None,
            })

            for bucket in [by_ticker[ticker], by_strategy[strategy]]:
                bucket["total"] += 1
                if decision == "ENTRY":
                    bucket["entry"] += 1
                elif decision == "RADAR":
                    bucket["radar"] += 1
                elif decision == "WAIT_GREEKS":
                    bucket["wait_greeks"] += 1
                elif decision == "WAIT_DATA":
                    bucket["wait_data"] += 1
                elif decision == "BLOCKED":
                    bucket["blocked"] += 1

                if bucket["best"] is None or v18_priority_rank(r) > v18_priority_rank(bucket["best"]):
                    bucket["best"] = r

        next_best_action = clean_rows[0] if clean_rows else None

        if next_best_action:
            global_recommendation = next_best_action.get("recommendation")
        else:
            global_recommendation = "No hay oportunidades operativas disponibles en el último ciclo."

        payload = {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "generated_at": _v18_datetime.now(_v18_timezone.utc).isoformat(),
            "summary": summary,
            "next_best_action": next_best_action,
            "recommendation": global_recommendation,
            "by_ticker": list(by_ticker.values()),
            "by_strategy": list(by_strategy.values()),
            "top": clean_rows[:20],
            "health": {
                "snapshot_available": True,
                "rows_captured": len(clean_rows),
                "manual_review_ready_count": sum(1 for r in clean_rows if r.get("manual_review_ready")),
                "can_operate_count": 0,
            },
            "not_order_instruction": True,
            "execution_authorized": False,
        }

        return payload

    except Exception as e:
        return {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "generated_at": _v18_datetime.now(_v18_timezone.utc).isoformat(),
            "error": str(e),
            "summary": {
                "entry": 0,
                "manage_position": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "total": 0,
            },
            "next_best_action": None,
            "recommendation": "No se pudo construir la decisión operativa.",
            "by_ticker": [],
            "by_strategy": [],
            "top": [],
            "health": {
                "snapshot_available": False,
                "rows_captured": 0,
                "can_operate_count": 0,
            },
        }

def v18_write_decision_snapshot(rows=None):
    try:
        payload = v18_build_decision_payload(rows or V17_SUMMARY_ROWS)
        V18_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        V18_SNAPSHOT_PATH.write_text(_v18_json.dumps(payload, ensure_ascii=False, indent=2))
        return payload
    except Exception as e:
        return {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "error": str(e),
            "recommendation": "No se pudo guardar el snapshot V18.",
        }

# ============================================================
# SUPER ENGINE BOLSA — V17.3C SUPPRESS IBKR NOISE
# ============================================================

import sys as _v17_sys
import logging as _v17_logging

class V17NoiseFilter:
    def __init__(self, stream):
        self.stream = stream

    def write(self, message):
        try:
            msg = str(message)
            if "Unknown contract:" in msg:
                return
            if "Option(symbol=" in msg and "tradingClass=" in msg:
                return
            return self.stream.write(message)
        except Exception:
            return self.stream.write(message)

    def flush(self):
        try:
            return self.stream.flush()
        except Exception:
            pass

try:
    _v17_sys.stderr = V17NoiseFilter(_v17_sys.stderr)
except Exception:
    pass

try:
    class V17LoggingNoiseFilter(_v17_logging.Filter):
        def filter(self, record):
            msg = str(record.getMessage())
            if "Unknown contract:" in msg:
                return False
            if "Option(symbol=" in msg and "tradingClass=" in msg:
                return False
            return True

    _v17_logging.getLogger().addFilter(V17LoggingNoiseFilter())
    _v17_logging.getLogger("ib_insync").addFilter(V17LoggingNoiseFilter())
except Exception:
    pass

# ============================================================
# SUPER ENGINE BOLSA — V17.3 CLEAN CONSOLE
# ============================================================

V17_CLEAN_CONSOLE = True

def v17_should_hide_console_line(text):
    try:
        if not V17_CLEAN_CONSOLE:
            return False

        if not isinstance(text, str):
            text = str(text)

        stripped = text.strip()

        if not stripped:
            return False

        # Ocultar ruido de contratos inválidos / desconocidos
        if "Unknown contract:" in stripped:
            return True

        if "Option(symbol=" in stripped and "tradingClass=" in stripped:
            return True

        # Ocultar líneas masivas de contratos de opciones individuales.
        # El resumen ejecutivo ya captura esta información.
        option_tokens = [
            " NAKED_PUT ",
            " COVERED_CALL ",
            " SHORT_PUT ",
            " SHORT_CALL ",
            " IRON_CONDOR ",
        ]

        if any(tok in stripped for tok in option_tokens):
            if " exp:" in stripped and (" decision:" in stripped or " cap:" in stripped or " quality:" in stripped):
                return True

        # Ocultar dumps largos de status si son demasiado técnicos
        if len(stripped) > 240 and (" underlying_source:" in stripped or " price_source:" in stripped):
            return True

        return False

    except Exception:
        return False

# ============================================================
# SUPER ENGINE BOLSA — V17.2 CONSOLE CAPTURE
# ============================================================

import builtins as _v17_builtins
import re as _v17_re

V17_ORIGINAL_PRINT = _v17_builtins.print

def v17_parse_console_line_for_summary(text):
    try:
        if not isinstance(text, str):
            text = str(text)

        if " decision:" not in text and " cap:" not in text:
            return None

        if " score:" not in text:
            return None

        parts = text.strip().split()
        if len(parts) < 2:
            return None

        ticker = parts[0]
        strategy = parts[1]

        def pick(pattern, default=None):
            m = _v17_re.search(pattern, text)
            return m.group(1) if m else default

        score = pick(r"score:([-+]?\d+\.?\d*)", 0)
        decision = pick(r"decision:([A-Z_]+)", None)
        cap = pick(r"cap:([A-Z_]+)", None)
        quality = pick(r"quality:([A-Z_]+)", "CONSOLE_CAPTURE")
        price = pick(r"price:([-+]?\d+\.?\d*)", None)
        mid = pick(r"mid:([-+]?\d+\.?\d*)", None)

        final_decision = decision or cap or "WAIT"

        row = {
            "ticker": ticker,
            "strategy": strategy,
            "decision": final_decision,
            "score": float(score) if score is not None else 0,
            "data_quality": quality,
            "source": "CONSOLE_CAPTURE",
        }

        if price is not None:
            row["price"] = price
        elif mid is not None:
            row["price"] = mid

        return row

    except Exception:
        return None


def v17_print(*args, **kwargs):
    try:
        text = " ".join(str(a) for a in args)

        # Primero capturamos para summary, aunque luego ocultemos la línea.
        for line in text.splitlines():
            row = v17_parse_console_line_for_summary(line)
            if row:
                try:
                    v17_store_row(row)
                except Exception:
                    pass

        # Después filtramos ruido visual de consola.
        visible_lines = []
        for line in text.splitlines():
            if not v17_should_hide_console_line(line):
                visible_lines.append(line)

        if not visible_lines and text.strip():
            return None

        if visible_lines and len(visible_lines) != len(text.splitlines()):
            return V17_ORIGINAL_PRINT("\n".join(visible_lines), **kwargs)

    except Exception:
        pass

    return V17_ORIGINAL_PRINT(*args, **kwargs)

if getattr(_v17_builtins.print, "__name__", "") != "v17_print":
    _v17_builtins.print = v17_print

# ============================================================
# SUPER ENGINE BOLSA — V17 OPERATIONAL DESK OUTPUT
# ============================================================

def v17_safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def v17_get(row, *keys, default=None):
    try:
        for k in keys:
            if isinstance(row, dict) and row.get(k) is not None:
                return row.get(k)
    except Exception:
        pass
    return default


def v17_collect_rows(obj, out=None, max_items=300):
    if out is None:
        out = []

    if len(out) >= max_items:
        return out

    try:
        if isinstance(obj, dict):
            keys = set(obj.keys())
            if (
                "ticker" in keys
                or "symbol" in keys
                or "decision" in keys
                or "final_decision" in keys
                or "strategy_decision" in keys
                or "score" in keys
                or "master_score" in keys
                or "position_class" in keys
                or "quality" in keys
                or "data_quality" in keys
            ):
                out.append(obj)

            for v in obj.values():
                if isinstance(v, (dict, list, tuple)):
                    v17_collect_rows(v, out, max_items)

        elif isinstance(obj, (list, tuple)):
            for item in obj:
                if isinstance(item, (dict, list, tuple)):
                    v17_collect_rows(item, out, max_items)
    except Exception:
        pass

    return out


def v17_score(row):
    return v17_safe_float(
        v17_get(
            row,
            "master_score",
            "priority_score",
            "score",
            "best_entry_score",
            "best_management_score",
            default=0,
        )
    )


def v17_decision(row):
    return str(
        v17_get(
            row,
            "final_action",
            "final_decision",
            "strategy_decision",
            "option_decision",
            "decision",
            "cap",
            default="WAIT",
        )
    )


def v17_ticker(row):
    return str(
        v17_get(
            row,
            "ticker",
            "symbol",
            "local_symbol",
            "option_symbol",
            "underlying",
            default="UNKNOWN",
        )
    )


def v17_strategy(row):
    return str(
        v17_get(
            row,
            "best_strategy",
            "strategy",
            "strategy_hint",
            "option_strategy_hint",
            "setup",
            "position_class",
            "asset_class",
            default="GENERAL",
        )
    )


def v17_quality(row):
    return str(
        v17_get(
            row,
            "data_quality",
            "quality",
            "price_source",
            "source",
            default="NO_QUALITY",
        )
    )


def v17_bucket(row):
    d = v17_decision(row).upper()
    q = v17_quality(row).upper()
    cap = str(v17_get(row, "execution_cap", "cap", default="")).upper()
    blockers = v17_get(row, "blockers", default=[])
    missing = v17_get(row, "missing_data", "entry_missing_data", default=[])

    if blockers and "RADAR_ONLY_MARKET_CLOSED" not in cap:
        return "BLOCKED"

    if "OPERAR" in d or "ENTRY_OPPORTUNITY" in d or d in ["BUY", "SELL", "TRADE"]:
        return "ENTRY"

    if "BLOCKED" in d or "BLOCKED" in cap:
        return "BLOCKED"

    if "RADAR" in d or "RADAR" in cap:
        return "RADAR"

    if "WAIT_FOR_GREEKS" in d or "WAIT_FOR_GREEKS" in cap or "NO_GREEKS" in q:
        return "WAIT_GREEKS"

    if missing:
        return "WAIT_DATA"

    return "WAIT"


def v17_format_row(row):
    price = v17_get(row, "price", "market_price", "latest_price", "last", "close", default=None)
    price_txt = f" | price:{price}" if price is not None else ""
    return (
        f"{v17_ticker(row)} | "
        f"{v17_strategy(row)} | "
        f"{v17_decision(row)} | "
        f"score:{v17_score(row):.1f}"
        f"{price_txt} | "
        f"{v17_quality(row)}"
    )


def v17_build_cycle_summary(local_vars):
    try:
        rows = []
        try:
            rows.extend(V17_SUMMARY_ROWS)
        except Exception:
            pass

        for name, value in local_vars.items():
            if name.startswith("__"):
                continue
            if isinstance(value, (dict, list, tuple)):
                rows.extend(v17_collect_rows(value))

        seen = set()
        unique = []

        for r in rows:
            if not isinstance(r, dict):
                continue

            key = (
                v17_ticker(r),
                v17_strategy(r),
                v17_decision(r),
                round(v17_score(r), 2),
                v17_quality(r),
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(r)

        buckets = {
            "ENTRY": [],
            "RADAR": [],
            "WAIT_GREEKS": [],
            "WAIT_DATA": [],
            "BLOCKED": [],
            "WAIT": [],
        }

        for r in unique:
            buckets.setdefault(v17_bucket(r), []).append(r)

        for k in buckets:
            buckets[k] = sorted(buckets[k], key=v17_score, reverse=True)[:8]

        top = (
            buckets["ENTRY"][:1]
            or buckets["RADAR"][:1]
            or buckets["BLOCKED"][:1]
            or buckets["WAIT_GREEKS"][:1]
            or buckets["WAIT_DATA"][:1]
            or buckets["WAIT"][:1]
        )

        lines = []
        lines.append("")
        lines.append("============================================================")
        lines.append("V17 OPERATIONAL DESK SUMMARY")
        lines.append("============================================================")
        lines.append(
            f"ENTRY:{len(buckets['ENTRY'])} | "
            f"RADAR:{len(buckets['RADAR'])} | "
            f"WAIT_GREEKS:{len(buckets['WAIT_GREEKS'])} | "
            f"WAIT_DATA:{len(buckets['WAIT_DATA'])} | "
            f"BLOCKED:{len(buckets['BLOCKED'])}"
        )
        lines.append("")

        if top:
            lines.append("NEXT BEST ACTION:")
            lines.append("  " + v17_format_row(top[0]))
            lines.append("")

        if buckets["ENTRY"]:
            lines.append("ENTRY CANDIDATES:")
            for r in buckets["ENTRY"][:5]:
                lines.append("  - " + v17_format_row(r))
            lines.append("")

        if buckets["RADAR"]:
            lines.append("RADAR / PREPARACION:")
            for r in buckets["RADAR"][:5]:
                lines.append("  - " + v17_format_row(r))
            lines.append("")

        if buckets["BLOCKED"]:
            lines.append("BLOCKED / NO OPERAR:")
            for r in buckets["BLOCKED"][:5]:
                lines.append("  - " + v17_format_row(r))
            lines.append("")

        if buckets["WAIT_GREEKS"] or buckets["WAIT_DATA"]:
            lines.append("FALTANTES DE DATOS:")
            for r in (buckets["WAIT_GREEKS"] + buckets["WAIT_DATA"])[:5]:
                lines.append("  - " + v17_format_row(r))
            lines.append("")

        lines.append("============================================================")
        return "\n".join(lines)

    except Exception as e:
        return f"V17 summary unavailable: {e}"
print("SUPER ENGINE IBKR BRIDGE V18_1_REMOTE_SNAPSHOT_INGEST")
print("Market + Portfolio + Options + Strategy Commander")
print("IBKR ONLY + READY FOR TRADINGVIEW INTEGRATION")
print("Naked Put + Covered Call activos")
print("Decision safety locks enabled")
print("Robust stock price fallback enabled")
print(
    "Daily radar fast mode:"
    f" {DAILY_RADAR_FAST}"
    f" | watchlist:{','.join(WATCHLIST)}"
    f" | option_symbols:{','.join(OPTION_SYMBOLS)}"
    f" | coberturas_rsp_weekly:{COBERTURAS_RSP_WEEKLY}"
    f" | target_dte:{TARGET_DTE_MIN}-{TARGET_DTE_MAX}/{TARGET_DTE_IDEAL}"
    f" | max_options_per_symbol:{MAX_OPTIONS_PER_SYMBOL}"
    f" | dynamic_option_universe:{DYNAMIC_OPTION_UNIVERSE_ENABLED}"
    f" | max_option_symbols_per_run:{MAX_OPTION_SYMBOLS_PER_RUN}"
    f" | max_total_option_contracts_per_run:{MAX_TOTAL_OPTION_CONTRACTS_PER_RUN}"
    f" | option_wait:{OPTION_MARKET_DATA_WAIT_SECONDS}s"
)
print("")


def run_bridge_cycle():
    """Collect one IBKR cycle and publish its fresh canonical snapshot."""
    print("")
    print("=========================================")
    print("NUEVO CICLO V18_1_REMOTE_SNAPSHOT_INGEST")
    print("=========================================")

    if ENABLE_MARKET_DATA:
        send_market_data()

    if ENABLE_PORTFOLIO_COMMANDER:
        send_positions()

    if ENABLE_OPTIONS_INTELLIGENCE:
        send_options_intelligence()

        try:
            print(v17_build_cycle_summary(locals()))
            try:
                v18_payload = v18_write_decision_snapshot(V17_SUMMARY_ROWS)
                v18_remote = v18_1_post_decision_snapshot(v18_payload)
                nba = v18_payload.get("next_best_action")
                if nba:
                    print("")
                    print("V18 DECISION API SNAPSHOT UPDATED")
                    print(
                        "NEXT: "
                        f"{nba.get('ticker')} | {nba.get('strategy')} | {nba.get('decision')} "
                        f"| manual_review_ready:{nba.get('manual_review_ready')} "
                        "| can_operate:False | not_order_instruction:True"
                    )
                else:
                    print("")
                    print("V18 DECISION API SNAPSHOT UPDATED | No next_best_action")
                try:
                    print(f"REMOTE INGEST: {v18_remote.get('posted')} | status:{v18_remote.get('status')} | url:{v18_remote.get('url', '')}")
                except Exception:
                    pass
            except Exception as e:
                print(f"V18 snapshot error: {e}")
        except Exception as e:
            print(f"V17 summary error: {e}")

    try:
        _v283_publish_to_v28()
    except Exception as publish_error:
        print(f"V31 canonical publish call error: {publish_error}")


# ============================================================
# V22.2 REMOTE SNAPSHOT SYNC — LOCAL BRIDGE POST TO RENDER
# ============================================================

import json as _v22_2_json
from pathlib import Path as _v22_2_Path
from datetime import datetime as _v22_2_datetime, timezone as _v22_2_timezone

try:
    import requests as _v22_2_requests
except Exception:
    _v22_2_requests = None

V22_2_REMOTE_BASE_URL = "https://trading-engine-p097.onrender.com"

def _v22_2_now_iso():
    return _v22_2_datetime.now(_v22_2_timezone.utc).isoformat()

def _v22_2_read_json_file(path):
    try:
        p = _v22_2_Path(path)
        if p.exists():
            return _v22_2_json.loads(p.read_text())
    except Exception:
        pass
    return None

def _v22_2_post_json(endpoint, payload, timeout=8):
    if _v22_2_requests is None:
        return {"ok": False, "status": "NO_REQUESTS_LIB", "url": endpoint}

    url = V22_2_REMOTE_BASE_URL.rstrip("/") + endpoint
    try:
        r = _v22_2_requests.post(url, json=payload, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = {"text": r.text[:500]}
        return {
            "ok": 200 <= r.status_code < 300,
            "status": r.status_code,
            "url": url,
            "body": body,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "POST_ERROR",
            "url": url,
            "error": str(e),
        }

def _v22_2_collect_candidate_files():
    return {
        "technical": [
            "runtime/technical_snapshot_by_ticker_safe.json",
            "runtime/technical_snapshot_by_ticker.json",
            "technical_snapshot_by_ticker_safe.json",
            "technical_snapshot_by_ticker.json",
        ],
        "decision": [
            "runtime/decision_desk_snapshot.json",
            "runtime/v18_decision_snapshot.json",
            "runtime/v18_decision_desk_snapshot.json",
            "decision_desk_snapshot.json",
            "decision_snapshot.json",
        ],
    }

def _v22_2_find_first_json(paths):
    for p in paths:
        data = _v22_2_read_json_file(p)
        if data:
            return p, data
    return None, None

def _v22_2_remote_sync_snapshots(extra_payload=None):
    files = _v22_2_collect_candidate_files()

    tech_path, tech_data = _v22_2_find_first_json(files["technical"])
    decision_path, decision_data = _v22_2_find_first_json(files["decision"])

    results = {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "generated_at": _v22_2_now_iso(),
        "technical_path": tech_path,
        "decision_path": decision_path,
        "technical_sent": False,
        "decision_sent": False,
        "unified_sent": False,
        "responses": {},
    }

    if isinstance(tech_data, dict):
        # Caso A: store por ticker {"QQQ": {...}, "SPY": {...}}
        if any(isinstance(v, dict) for v in tech_data.values()):
            for ticker, snap in tech_data.items():
                if isinstance(snap, dict):
                    payload = {
                        "ticker": str(ticker).upper(),
                        "snapshot": snap,
                        "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
                        "local_path": tech_path,
                    }
                    resp = _v22_2_post_json("/v22_2_ingest_technical_snapshot", payload)
                    results["responses"][f"technical_{ticker}"] = resp
                    if resp.get("ok"):
                        results["technical_sent"] = True
        # Caso B: snapshot directo {"ticker":"QQQ", ...}
        elif tech_data.get("ticker"):
            payload = {
                "ticker": str(tech_data.get("ticker")).upper(),
                "snapshot": tech_data,
                "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
                "local_path": tech_path,
            }
            resp = _v22_2_post_json("/v22_2_ingest_technical_snapshot", payload)
            results["responses"]["technical_single"] = resp
            if resp.get("ok"):
                results["technical_sent"] = True

    if isinstance(decision_data, dict):
        payload = dict(decision_data)
        payload["source"] = payload.get("source") or "IBKR_BRIDGE_V22_2_REMOTE_SYNC"
        payload["local_path"] = decision_path
        resp = _v22_2_post_json("/v22_2_ingest_decision_snapshot", payload)
        results["responses"]["decision"] = resp
        if resp.get("ok"):
            results["decision_sent"] = True

    unified_payload = {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "generated_at": _v22_2_now_iso(),
        "technical_available": bool(tech_data),
        "decision_available": bool(decision_data),
        "technical_path": tech_path,
        "decision_path": decision_path,
        "extra_payload": extra_payload or {},
        "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
    }
    resp = _v22_2_post_json("/v22_2_ingest_unified_snapshot", unified_payload)
    results["responses"]["unified"] = resp
    if resp.get("ok"):
        results["unified_sent"] = True

    return results

def v22_2_print_remote_sync_status(extra_payload=None):
    try:
        res = _v22_2_remote_sync_snapshots(extra_payload=extra_payload)
        print("")
        print("=== V22.2 REMOTE SNAPSHOT SYNC ===")
        print(f"technical_sent: {res.get('technical_sent')} | path: {res.get('technical_path')}")
        print(f"decision_sent: {res.get('decision_sent')} | path: {res.get('decision_path')}")
        print(f"unified_sent: {res.get('unified_sent')}")
        for k, v in (res.get("responses") or {}).items():
            print(f"{k}: ok={v.get('ok')} status={v.get('status')}")
        print("==================================")
        print("")
        return res
    except Exception as e:
        print(f"V22.2 remote sync error: {e}")
        return {"ok": False, "error": str(e)}



# ============================================================
# V28 REMOTE MASTER SNAPSHOT AUTO PUBLISHER
# ============================================================
import os as _v28_os
import json as _v28_json_bridge
from datetime import datetime as _v28_bridge_datetime, timezone as _v28_bridge_timezone

try:
    import requests as _v28_requests
except Exception:
    _v28_requests = None

_V28_REMOTE_BASE_URL = _v28_os.environ.get(
    "TRADING_ENGINE_REMOTE_URL",
    "https://trading-engine-p097.onrender.com"
).rstrip("/")

_V28_REMOTE_INGEST_PATH = _v28_os.environ.get(
    "TRADING_ENGINE_INGEST_PATH",
    "/v31_ingest_snapshot"
)
if not _V28_REMOTE_INGEST_PATH.startswith("/"):
    _V28_REMOTE_INGEST_PATH = "/" + _V28_REMOTE_INGEST_PATH

_V28_REMOTE_INGEST_URL = _V28_REMOTE_BASE_URL + _V28_REMOTE_INGEST_PATH

def _v28_bridge_now():
    return _v28_bridge_datetime.now(_v28_bridge_timezone.utc).isoformat()

def _v28_bridge_json_safe(obj):
    try:
        _v28_json_bridge.dumps(obj)
        return obj
    except Exception:
        if isinstance(obj, dict):
            return {str(k): _v28_bridge_json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_v28_bridge_json_safe(x) for x in obj]
        try:
            return float(obj)
        except Exception:
            return str(obj)

def _v28_bridge_collect_runtime_json():
    out = {}
    runtime = Path("runtime")
    try:
        for p in runtime.glob("*.json"):
            try:
                out[p.name] = _v28_json_bridge.loads(p.read_text())
            except Exception:
                pass
    except Exception:
        pass
    return out

def _v28_bridge_extract_options_rows(runtime_data):
    rows = []
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

    def completeness_score(row):
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

    def add_from(x):
        if isinstance(x, list):
            for r in x:
                if isinstance(r, dict):
                    rows.append(dict(r))
        elif isinstance(x, dict):
            for k in ["options_rows", "rows", "top", "top_5", "sample_rows", "best_rows"]:
                v = x.get(k)
                if isinstance(v, list):
                    add_from(v)
            opt = x.get("options")
            if isinstance(opt, dict):
                add_from(opt)
            for k in ["best_row", "best", "next_best_action"]:
                v = x.get(k)
                if isinstance(v, dict):
                    rows.append(dict(v))

    for _name, data in runtime_data.items():
        add_from(data)

    best_by_key = {}
    for r in rows:
        ticker = str(r.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        r["ticker"] = ticker
        r["strategy"] = str(r.get("strategy") or r.get("strategy_hint") or r.get("best_strategy") or "UNKNOWN").upper()
        r["decision"] = str(r.get("decision") or r.get("final_decision") or r.get("state") or "RADAR").upper()
        r["score"] = r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score")
        r["price"] = r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid")
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"
        r["expiration"] = r.get("expiration") or r.get("expiry") or r.get("exp")
        key = (r.get("ticker"), r.get("strategy"), r.get("decision"))
        current = best_by_key.get(key)
        if current is None or completeness_score(r) > completeness_score(current):
            best_by_key[key] = r
    return sorted(best_by_key.values(), key=completeness_score, reverse=True)

def _v28_bridge_extract_technical_snapshot(runtime_data):
    tech = {}

    def add_candidate(k, v):
        if not isinstance(v, dict):
            return
        ticker = str(v.get("ticker") or k or "").upper().strip()
        if not ticker:
            return
        # only accept objects that look technical
        looks = any(x in v for x in ["trend", "rsi", "adx", "vwap_position", "volume_relative", "support_near", "resistance_near", "score"])
        if looks:
            vv = dict(v)
            vv["ticker"] = ticker
            tech[ticker] = vv

    def walk(obj, forced_key=None):
        if isinstance(obj, dict):
            if forced_key:
                add_candidate(forced_key, obj)
            for k, v in obj.items():
                if isinstance(v, dict):
                    add_candidate(k, v)
                    walk(v, k)
                elif isinstance(v, list):
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for _name, data in runtime_data.items():
        walk(data)

    return tech

def _v28_bridge_market_snapshot():
    return bridge_market_snapshot("IBKR_BRIDGE_V28_AUTO_PUBLISHER")

def _v28_publish_master_snapshot(extra_payload=None):
    if _v28_requests is None:
        print("V28 REMOTE MASTER SNAPSHOT NOT PUBLISHED | requests not available")
        return {"ok": False, "error": "requests_not_available"}

    runtime_data = _v28_bridge_collect_runtime_json()
    options_rows = _v28_bridge_extract_options_rows(runtime_data)
    technical_snapshot = _v28_bridge_extract_technical_snapshot(runtime_data)
    technical_snapshot = runtime_local_technical.merge_local_technical_snapshot(
        technical_snapshot,
        runtime_data,
        options_rows=options_rows,
        timeframe="1d",
    )
    # Runtime documents contain internal sections that can look like ticker
    # dictionaries (for example ``GATE`` or ``TOP``).  Never publish those as
    # market symbols in the canonical snapshot.
    reserved_non_tickers = {
        "CANSLIM", "CONTROL_PANEL", "GATE", "MARKET", "OPTIONS", "POST_MORTEM",
        "RAW", "SCORE_CALIBRATION", "TECHNICAL", "TOP",
    }
    technical_snapshot = {
        str(symbol).strip().upper(): value
        for symbol, value in technical_snapshot.items()
        if isinstance(value, dict)
        and str(symbol).strip().upper() not in reserved_non_tickers
        and str(symbol).strip().upper().replace(".", "").replace("-", "").isalnum()
        and 1 <= len(str(symbol).strip().upper()) <= 12
    }
    broker_context = _bridge_broker_snapshot_context(options_rows, runtime_data, technical_snapshot)
    broker_enriched = broker_check.merge_broker_checks(broker_context, rows=options_rows)
    active_position_management = position_management.build_active_position_management(broker_context)

    payload = {
        "source": "IBKR_BRIDGE_V28_AUTO_PUBLISHER",
        "generated_at": _v28_bridge_now(),
        "account_scope": broker_context.get("account_scope") or BRIDGE_ACCOUNT_SCOPE,
        "account_alias": broker_context.get("account_alias") or BRIDGE_ACCOUNT_ALIAS,
        "options_rows": _v28_bridge_json_safe(options_rows),
        "technical_snapshot": _v28_bridge_json_safe(technical_snapshot),
        "account_context": _v28_bridge_json_safe(broker_context.get("account_context") or {}),
        "positions": _v28_bridge_json_safe(broker_context.get("positions") or []),
        "broker_checks": _v28_bridge_json_safe(broker_enriched.get("broker_checks") or []),
        "broker_check_summary": _v28_bridge_json_safe(broker_enriched.get("broker_check_summary") or {}),
        "active_position_management": _v28_bridge_json_safe(active_position_management),
        "market": _v28_bridge_market_snapshot(),
        "runtime_files_seen": sorted(list(runtime_data.keys())),
        "bridge_status": "PUBLISHED_FROM_LOCAL_IBKR",
        "not_order_instruction": True,
    }

    if isinstance(extra_payload, dict):
        payload.update(extra_payload)

    try:
        resp = _v28_requests.post(_V28_REMOTE_INGEST_URL, json=payload, timeout=15)
        ok = 200 <= resp.status_code < 300
        print(
            "V31 REMOTE MASTER SNAPSHOT PUBLISHED"
            f" | ok:{ok}"
            f" | status:{resp.status_code}"
            f" | rows:{len(options_rows)}"
            f" | technical:{len(technical_snapshot)}"
            f" | url:{_V28_REMOTE_INGEST_URL}"
        )
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "rows": len(options_rows),
            "technical": len(technical_snapshot),
            "url": _V28_REMOTE_INGEST_URL,
            "text": resp.text[:500],
        }
    except Exception as e:
        print(f"V28 REMOTE MASTER SNAPSHOT PUBLISH ERROR | {e}")
        return {"ok": False, "error": str(e), "url": _V28_REMOTE_INGEST_URL}

# ============================================================
# END V28 REMOTE MASTER SNAPSHOT AUTO PUBLISHER
# ============================================================


def run_bridge_forever():
    """Run bridge cycles at a controlled cadence until interrupted."""
    try:
        while True:
            cycle_started = time.monotonic()
            try:
                run_bridge_cycle()
            except Exception as exc:
                print(f"BRIDGE CYCLE ERROR: {exc}")

            elapsed = time.monotonic() - cycle_started
            wait_seconds = max(1.0, float(LOOP_SECONDS) - elapsed)
            print(f"Esperando {wait_seconds:.1f} segundos...")
            print("")
            time.sleep(wait_seconds)
    except KeyboardInterrupt:
        print("Bridge detenido por el usuario.")
    finally:
        if ib.isConnected():
            ib.disconnect()


if __name__ == "__main__":
    if "--once" in sys.argv:
        try:
            run_bridge_cycle()
        finally:
            if ib.isConnected():
                ib.disconnect()
    else:
        run_bridge_forever()
