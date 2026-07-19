"""Build local technical snapshots from runtime OHLCV bars.

This module bridges local runtime/IBKR bar data into ``local_technical_engine``
without connecting to any broker and without weakening TradingView precedence.
"""

from __future__ import annotations

import re
from typing import Any

import local_technical_engine


BAR_CONTAINER_KEYS = {
    "bars",
    "historical_bars",
    "ibkr_historical_bars",
    "ohlcv",
    "ohlcv_bars",
    "price_bars",
    "local_bars",
}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,4}$")
NON_TICKER_KEYS = {
    "RAW",
    "TOP",
    "GATE",
    "TECHNICAL",
    "OPTIONS_ROWS",
    "CANSLIM",
    "POST_MORTEM",
    "CONTROL_PANEL",
    "OPTION_OPTIMIZER",
    "SCORE_CALIBRATION",
    "CANSLIM_CONFIDENCE",
    "CONTRACT_COMPLETENESS",
    "MARKET_CONFIRMATION",
    "INSTITUTIONAL_RANKING",
    "CASH_SECURED_PUT",
    "COVERED_CALL",
    "NAKED_PUT",
    "IRON_CONDOR",
    "FUTURES",
    "INTRADAY_INDEX_FUTURES",
    "CANSLIM_GROWTH_FILTER",
}


def _upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _is_ticker(value: Any) -> bool:
    ticker = _upper(value)
    return bool(TICKER_RE.match(ticker)) and ticker not in NON_TICKER_KEYS


def _looks_like_bar(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(key in value for key in ["close", "c", "last", "price"])


def _looks_like_bar_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and any(_looks_like_bar(item) for item in value[:5])


def _strategy_for_ticker(ticker: str, options_rows: list[dict[str, Any]]) -> str:
    ticker = _upper(ticker)
    for row in options_rows:
        if _upper(row.get("ticker") or row.get("symbol")) == ticker:
            strategy = _upper(row.get("strategy") or row.get("strategy_hint") or row.get("best_strategy"), "")
            if strategy:
                return strategy
    return "CASH_SECURED_PUT"


def extract_local_bar_sets(runtime_data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Extract ticker-keyed OHLCV bars from permissive runtime JSON shapes."""

    bars_by_ticker: dict[str, list[dict[str, Any]]] = {}

    def add_bars(ticker: Any, bars: Any) -> None:
        ticker_key = _upper(ticker)
        if not _is_ticker(ticker_key) or not _looks_like_bar_list(bars):
            return
        current = bars_by_ticker.get(ticker_key, [])
        # Prefer the richer/longer bar set for the same ticker.
        if len(bars) > len(current):
            bars_by_ticker[ticker_key] = [dict(item) for item in bars if isinstance(item, dict)]

    def walk(obj: Any, parent_key: Any = None, parent_ticker: Any = None) -> None:
        if isinstance(obj, dict):
            ticker = obj.get("ticker") or obj.get("symbol") or parent_ticker

            for key, value in obj.items():
                if key in BAR_CONTAINER_KEYS:
                    if isinstance(value, dict):
                        for maybe_ticker, maybe_bars in value.items():
                            add_bars(maybe_ticker, maybe_bars)
                    else:
                        add_bars(ticker or parent_key, value)

            # Also accept ticker-keyed objects like {"QQQ": [{"close": ...}]}.
            for key, value in obj.items():
                if _looks_like_bar_list(value):
                    add_bars(key if _upper(key) not in BAR_CONTAINER_KEYS else ticker, value)
                elif isinstance(value, (dict, list)):
                    walk(value, key, ticker)

        elif isinstance(obj, list):
            if _looks_like_bar_list(obj):
                add_bars(parent_ticker or parent_key, obj)
            else:
                for item in obj:
                    walk(item, parent_key, parent_ticker)

    for name, data in (runtime_data or {}).items():
        walk(data, name)

    return bars_by_ticker


def build_local_technical_snapshot(
    runtime_data: dict[str, Any],
    *,
    existing_technical: dict[str, dict[str, Any]] | None = None,
    options_rows: list[dict[str, Any]] | None = None,
    timeframe: str = "1d",
) -> dict[str, dict[str, Any]]:
    """Return local technical snapshots only for tickers missing technical data."""

    existing_technical = existing_technical or {}
    options_rows = options_rows or []
    local_bars = extract_local_bar_sets(runtime_data)
    local_snapshot: dict[str, dict[str, Any]] = {}

    for ticker, bars in sorted(local_bars.items()):
        if ticker in existing_technical:
            continue
        strategy = _strategy_for_ticker(ticker, options_rows)
        evaluated = local_technical_engine.evaluate_symbol(
            ticker,
            bars,
            strategy=strategy,
            timeframe=timeframe,
        )
        evaluated["source_priority"] = "LOCAL_FALLBACK_ONLY_TRADINGVIEW_NOT_PRESENT"
        evaluated["tradingview_overridden"] = False
        evaluated["manual_review_required"] = True
        evaluated["execution_authorized"] = False
        evaluated["not_order_instruction"] = True
        local_snapshot[ticker] = evaluated

    return local_snapshot


def merge_local_technical_snapshot(
    existing_technical: dict[str, dict[str, Any]],
    runtime_data: dict[str, Any],
    *,
    options_rows: list[dict[str, Any]] | None = None,
    timeframe: str = "1d",
) -> dict[str, dict[str, Any]]:
    merged = dict(existing_technical or {})
    local = build_local_technical_snapshot(
        runtime_data,
        existing_technical=merged,
        options_rows=options_rows or [],
        timeframe=timeframe,
    )
    merged.update(local)
    return merged
