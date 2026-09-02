"""Data contracts and readiness audit for premium strategy research.

The module inventories local evidence and stores research observations. It does
not request, construct, recommend, or execute trades.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DATASET_VERSION = "premium_strategy_dataset_v1"
REPORT_VERSION = "premium_strategy_data_readiness_v1"
EARNINGS_FIELDS = {
    "ticker", "earnings_date", "event_timing", "confirmed", "source",
    "observed_at",
}
OPTION_FIELDS = {
    "ticker", "observed_at", "expiration", "dte", "right", "strike",
    "bid", "ask", "delta", "iv", "underlying_price", "source",
}
UNDERLYING_FIELDS = {"ticker", "observed_at", "close", "source"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return default


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_record(record: dict[str, Any], record_type: str) -> list[str]:
    required = (
        EARNINGS_FIELDS if record_type == "earnings_event"
        else OPTION_FIELDS if record_type == "option_observation"
        else UNDERLYING_FIELDS if record_type == "underlying_observation"
        else None
    )
    if required is None:
        raise ValueError(f"unknown premium research record type {record_type}")
    missing = sorted(field for field in required if record.get(field) in (None, ""))
    if record_type == "earnings_event" and record.get("confirmed") is not True:
        missing.append("confirmed_true")
    if record_type == "option_observation":
        for field in ("dte", "strike", "bid", "ask", "delta", "iv", "underlying_price"):
            if _number(record.get(field)) is None:
                missing.append(f"numeric_{field}")
    if record_type == "underlying_observation" and _number(record.get("close")) is None:
        missing.append("numeric_close")
    return list(dict.fromkeys(missing))


def append_observations(path: Path, records: Iterable[dict[str, Any]], record_type: str) -> dict[str, Any]:
    """Append valid, de-identified research records to JSONL, deduplicated."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                existing_ids.add(str(json.loads(line).get("observation_id") or ""))
            except (ValueError, TypeError):
                continue
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in records:
        record = dict(raw)
        missing = validate_record(record, record_type)
        if missing:
            rejected.append({"ticker": record.get("ticker"), "missing": missing})
            continue
        identity_fields = EARNINGS_FIELDS if record_type == "earnings_event" else OPTION_FIELDS if record_type == "option_observation" else UNDERLYING_FIELDS
        identity = "|".join(str(record.get(key) or "") for key in sorted(identity_fields))
        observation_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        if observation_id in existing_ids:
            continue
        record.update({
            "observation_id": observation_id,
            "record_type": record_type,
            "dataset_version": DATASET_VERSION,
            "not_order_instruction": True,
            "execution_authorized": False,
        })
        existing_ids.add(observation_id)
        accepted.append(record)
    if accepted:
        with path.open("a") as handle:
            for record in accepted:
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return {"accepted": len(accepted), "rejected": rejected, "path": str(path)}


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except (ValueError, TypeError):
            continue
    return rows


def volatility_statistics(iv_values: Iterable[Any], current_iv: Any) -> dict[str, float | None]:
    history = sorted(value for raw in iv_values if (value := _number(raw)) is not None)
    current = _number(current_iv)
    if current is None or not history:
        return {"iv_rank": None, "iv_percentile": None}
    low, high = history[0], history[-1]
    rank = 0.0 if high == low else (current - low) / (high - low) * 100
    percentile = sum(value <= current for value in history) / len(history) * 100
    return {"iv_rank": round(max(0.0, min(100.0, rank)), 2), "iv_percentile": round(percentile, 2)}


def annualized_realized_volatility(closes: Iterable[Any], periods: int = 252) -> float | None:
    prices = [value for raw in closes if (value := _number(raw)) is not None and value > 0]
    if len(prices) < 3:
        return None
    returns = [math.log(current / previous) for previous, current in zip(prices, prices[1:])]
    return round(statistics.stdev(returns) * math.sqrt(periods), 6)


def event_move_ratio(implied_move_pct: Any, historical_absolute_moves_pct: Iterable[Any]) -> float | None:
    implied = _number(implied_move_pct)
    history = [value for raw in historical_absolute_moves_pct if (value := _number(raw)) is not None and value >= 0]
    if implied is None or not history:
        return None
    baseline = statistics.median(history)
    return round(implied / baseline, 4) if baseline > 0 else None


def _live_option_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = []
    by_ticker = payload.get("by_ticker")
    if isinstance(by_ticker, dict):
        for ticker, item in by_ticker.items():
            if not isinstance(item, dict):
                continue
            for row in item.get("option_rows") or []:
                if isinstance(row, dict):
                    rows.append({"ticker": ticker, **row})
    return rows


def capture_runtime_observations(runtime_dir: Path, observed_at: str | None = None) -> dict[str, Any]:
    """Preserve usable current quotes so a prospective history starts now."""
    payload = _load_json(runtime_dir / "active_position_option_chains_latest.json", {})
    rows = _live_option_rows(payload)
    timestamp = observed_at or now_iso()
    options = []
    underlyings: dict[str, dict[str, Any]] = {}
    for row in rows:
        strategy = str(row.get("strategy") or "").upper()
        right = "C" if "CALL" in strategy else "P" if "PUT" in strategy else str(row.get("right") or "").upper()
        option = {
            "ticker": str(row.get("ticker") or "").upper(),
            "observed_at": timestamp,
            "expiration": row.get("expiration"),
            "dte": row.get("dte"),
            "right": right,
            "strike": row.get("strike"),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
            "delta": row.get("delta"),
            "iv": row.get("iv"),
            "underlying_price": row.get("underlying_price"),
            "open_interest": row.get("open_interest"),
            "volume": row.get("volume"),
            "source": row.get("market_data_source") or "IBKR_RUNTIME_SNAPSHOT",
        }
        if not validate_record(option, "option_observation"):
            options.append(option)
        ticker = option["ticker"]
        if ticker and _number(option["underlying_price"]) is not None:
            underlyings[ticker] = {
                "ticker": ticker,
                "observed_at": timestamp,
                "close": option["underlying_price"],
                "source": row.get("underlying_price_source") or "IBKR_RUNTIME_SNAPSHOT",
            }
    return {
        "options": append_observations(runtime_dir / "premium_research_option_observations.jsonl", options, "option_observation"),
        "underlyings": append_observations(runtime_dir / "premium_research_underlying_observations.jsonl", underlyings.values(), "underlying_observation"),
        "available_live_rows": len(rows),
        "usable_option_rows": len(options),
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def build_readiness(runtime_dir: Path, generated_at: str | None = None) -> dict[str, Any]:
    candidates_payload = _load_json(runtime_dir / "canslim_candidates_latest.json", {})
    candidates = candidates_payload.get("candidates") if isinstance(candidates_payload, dict) else []
    candidates = [row for row in candidates or [] if isinstance(row, dict)]
    canslim_passed = [row for row in candidates if row.get("canslim_passes") is True]
    canslim_full = [row for row in canslim_passed if (_number(row.get("canslim_component_coverage_pct")) or 0) >= 85]

    live_rows = _live_option_rows(_load_json(runtime_dir / "active_position_option_chains_latest.json", {}))
    quoted_rows = [row for row in live_rows if all(_number(row.get(field)) is not None for field in ("bid", "ask", "delta", "iv"))]
    earnings_rows = _jsonl_rows(runtime_dir / "premium_research_earnings_events.jsonl")
    option_history = _jsonl_rows(runtime_dir / "premium_research_option_observations.jsonl")
    underlying_history = _jsonl_rows(runtime_dir / "premium_research_underlying_observations.jsonl")
    expired_history = _jsonl_rows(runtime_dir / "premium_research_expired_option_backfill.jsonl")
    long_dated_rows = [
        row for row in option_history
        if str(row.get("ticker") or "").upper() in {"SPY", "RSP"}
        and (_number(row.get("target_dte")) or _number(row.get("dte")) or 0) in {120, 150, 180}
    ]
    def row_spread_pct(row: dict[str, Any]) -> float:
        explicit = _number(row.get("spread_pct"))
        if explicit is not None:
            return explicit
        bid, ask = _number(row.get("bid")), _number(row.get("ask"))
        mid = ((bid + ask) / 2) if bid is not None and ask is not None else 0
        return ((ask - bid) / mid * 100) if mid > 0 and ask >= bid else 999

    liquid_cells = {
        (str(row.get("ticker") or "").upper(), int(_number(row.get("target_dte")) or 0))
        for row in long_dated_rows
        if (_number(row.get("open_interest")) or 0) >= 500
        and row_spread_pct(row) <= 8
        and (_number(row.get("delta_distance")) or 999) <= 0.03
    }
    confirmed_events = [row for row in earnings_rows if row.get("confirmed") is True]
    wsh_status = _load_json(runtime_dir / "premium_research_wsh_status.json", {})

    earnings_missing = []
    if not canslim_full:
        earnings_missing.append("CANSLIM_FULL_COVERAGE")
    if not confirmed_events:
        earnings_missing.append("CONFIRMED_EARNINGS_CALENDAR")
    if not option_history:
        earnings_missing.append("PROSPECTIVE_OPTION_HISTORY")
    if not expired_history:
        earnings_missing.append("HISTORICAL_EXPIRED_OPTION_BACKFILL")

    long_missing = []
    if not long_dated_rows:
        long_missing.append("SPY_RSP_120_150_180_DTE_OBSERVATIONS")
    if len(liquid_cells) < 6:
        long_missing.append("LIQUID_LONG_DATED_GRID_INCOMPLETE")
    if not expired_history:
        long_missing.append("HISTORICAL_EXPIRED_OPTION_BACKFILL")
    if not long_dated_rows:
        long_next_action = "Ejecutar captura IBKR de 120/150/180 DTE e importar historia licenciada."
    elif len(liquid_cells) < 6:
        long_next_action = "Seguir acumulando cotizaciones; varios horizontes no tienen todavía liquidez suficiente. Importar historia licenciada."
    else:
        long_next_action = "Importar historia licenciada y ejecutar backtest research-only." if not expired_history else "Ejecutar backtest research-only."

    return {
        "report_version": REPORT_VERSION,
        "dataset_version": DATASET_VERSION,
        "generated_at": generated_at or now_iso(),
        "mode": "RESEARCH_PAPER_ONLY",
        "summary": {
            "canslim_candidates": len(candidates),
            "canslim_passed": len(canslim_passed),
            "canslim_full_coverage": len(canslim_full),
            "live_option_rows": len(live_rows),
            "live_fully_quoted_rows": len(quoted_rows),
            "confirmed_earnings_events": len(confirmed_events),
            "earnings_calendar_provider": "IBKR_WSH" if wsh_status.get("metadata_available") else "UNAVAILABLE",
            "earnings_calendar_blocker": wsh_status.get("blocker"),
            "prospective_option_observations": len(option_history),
            "underlying_price_observations": len(underlying_history),
            "long_dated_spy_rsp_observations": len(long_dated_rows),
            "liquid_long_dated_grid_cells": len(liquid_cells),
            "expired_option_backfill_rows": len(expired_history),
        },
        "strategies": {
            "CANSLIM_EARNINGS_VOLATILITY_HARVEST": {
                "data_state": "DATA_READY_FOR_BACKTEST" if not earnings_missing else "DATA_COLLECTION_REQUIRED",
                "missing": earnings_missing,
                "next_action": "Confirmar calendario de earnings y comenzar captura diaria; importar historia licenciada para backtest." if earnings_missing else "Ejecutar backtest research-only.",
            },
            "SPY_RSP_LONG_DATED_PUTWRITE": {
                "data_state": "DATA_READY_FOR_BACKTEST" if not long_missing else "DATA_COLLECTION_REQUIRED",
                "missing": long_missing,
                "next_action": long_next_action,
            },
        },
        "not_order_instruction": True,
        "execution_authorized": False,
        "maximum_state": "PAPER_ELIGIBLE",
    }


def write_readiness(runtime_dir: Path, output: Path | None = None) -> dict[str, Any]:
    report = build_readiness(runtime_dir)
    _atomic_json(output or runtime_dir / "premium_strategy_data_readiness_latest.json", report)
    return report
