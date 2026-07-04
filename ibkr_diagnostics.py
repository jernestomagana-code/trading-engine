"""IBKR market-data coverage diagnostics for Stock Ultimus."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DIAGNOSTIC_VERSION = "ibkr_chain_coverage_v1"
DEFAULT_DIAGNOSTIC_PATH = Path("runtime/v32_ibkr_chain_coverage.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def option_row_diagnostic(row: dict[str, Any]) -> dict[str, Any]:
    row = row if isinstance(row, dict) else {}
    missing = []
    for field in ["bid", "ask", "mid", "spread_pct", "delta", "strike", "expiration", "dte"]:
        if row.get(field) in [None, "", "None"]:
            missing.append(field)
    return {
        "ticker": safe_upper(row.get("ticker") or row.get("symbol"), "UNKNOWN"),
        "strategy": safe_upper(row.get("strategy") or row.get("strategy_hint"), "UNKNOWN"),
        "local_symbol": row.get("local_symbol") or row.get("option_symbol"),
        "data_quality": row.get("data_quality"),
        "decision": row.get("decision") or row.get("final_decision"),
        "missing_execution_fields": missing,
        "market_data_source": row.get("option_market_data_source") or row.get("market_data_source"),
        "market_data_attempts": row.get("option_market_data_attempts") or row.get("market_data_attempts") or [],
        "not_order_instruction": True,
    }


def build_cycle_diagnostic(
    *,
    symbols: list[str] | None = None,
    chain_events: list[dict[str, Any]] | None = None,
    option_rows: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    chain_events = [item for item in (chain_events or []) if isinstance(item, dict)]
    option_rows = [item for item in (option_rows or []) if isinstance(item, dict)]
    row_diagnostics = [option_row_diagnostic(row) for row in option_rows]
    rows_by_ticker = Counter(item["ticker"] for item in row_diagnostics)
    quality_counts = Counter(str(item.get("data_quality") or "UNKNOWN") for item in row_diagnostics)
    missing_counts = Counter()
    for item in row_diagnostics:
        for field in item.get("missing_execution_fields") or []:
            missing_counts[field] += 1
    chain_by_ticker = {
        safe_upper(item.get("ticker"), "UNKNOWN"): item
        for item in chain_events
        if item.get("ticker")
    }
    return {
        "engine": "IBKR_CHAIN_COVERAGE_DIAGNOSTIC",
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "generated_at": generated_at or now_iso(),
        "symbols_requested": [safe_upper(symbol, "UNKNOWN") for symbol in (symbols or [])],
        "chain_event_count": len(chain_events),
        "option_row_count": len(option_rows),
        "rows_by_ticker": dict(sorted(rows_by_ticker.items())),
        "data_quality_counts": dict(sorted(quality_counts.items())),
        "missing_execution_field_counts": dict(sorted(missing_counts.items())),
        "chain_by_ticker": chain_by_ticker,
        "option_rows": row_diagnostics,
        "primary_gap": primary_gap(chain_events, row_diagnostics),
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def primary_gap(chain_events: list[dict[str, Any]], row_diagnostics: list[dict[str, Any]]) -> str:
    if not chain_events and not row_diagnostics:
        return "NO_IBKR_OPTION_DIAGNOSTICS"
    if any(item.get("status") == "NO_CHAIN" for item in chain_events):
        return "MISSING_OPTION_CHAIN"
    if any(item.get("missing_execution_fields") for item in row_diagnostics):
        return "INCOMPLETE_OPTION_MARKET_DATA"
    if not row_diagnostics:
        return "NO_OPTION_ROWS"
    return "COVERAGE_REVIEWABLE"


def write_cycle_diagnostic(payload: dict[str, Any], path: str | Path = DEFAULT_DIAGNOSTIC_PATH) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return {
        "status": "SAVED",
        "path": str(target),
        "option_row_count": payload.get("option_row_count"),
        "primary_gap": payload.get("primary_gap"),
        "execution_authorized": False,
        "not_order_instruction": True,
    }
