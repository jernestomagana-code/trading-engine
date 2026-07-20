"""Active position-management engine for Stock Ultimus.

The engine is pure decision support. It reads already-sanitized broker,
technical, and strategy context and returns review states for open positions.
It never creates, routes, or authorizes orders.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
import math

import broker_check
import gamma_context_store
import position_context_store
import strategy_exit_playbook


POSITION_MANAGEMENT_VERSION = "active_position_management_v5"
DEFAULT_MAX_CONTEXT_AGE_MINUTES = 15
DEFAULT_CONTRACT_MULTIPLIER = 100

ACTION_PRIORITY = {
    "REVIEW_RISK": 1000,
    "REVIEW_DEFENSIVE_EXIT": 950,
    "REVIEW_ASSIGNMENT": 900,
    "REVIEW_ROLL": 760,
    "REVIEW_CLOSE_OR_BUY_BACK": 700,
    "REFRESH_DATA": 520,
    "NO_ACTION_RECOMMENDED": 120,
    "NO_POSITION": 0,
}

SCENARIO_MOVES_PCT = [-5.0, -3.0, 0.0, 3.0, 5.0]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in [None, "", "None", "null"]:
            return default
        return float(value)
    except Exception:
        return default


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def age_minutes(value: Any, now: datetime | None = None) -> float | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    now = now or datetime.now(timezone.utc)
    return round((now.astimezone(timezone.utc) - parsed).total_seconds() / 60.0, 2)


def parse_expiration(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        return datetime.fromisoformat(text[:10]).date()
    except Exception:
        return None


def days_to_expiration(value: Any, today: date | None = None) -> int | None:
    expiration = parse_expiration(value)
    if expiration is None:
        return None
    today = today or datetime.now(timezone.utc).date()
    return (expiration - today).days


def _walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_dicts(item)


def _raw_positions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    found: list[dict[str, Any]] = []
    for key in ["positions", "portfolio_positions", "position_rows"]:
        value = snapshot.get(key)
        if isinstance(value, list):
            found.extend(item for item in value if isinstance(item, dict))
    if found:
        return found
    return broker_check.extract_positions(snapshot)


def _position_key(row: dict[str, Any]) -> str:
    parts = [
        safe_upper(row.get("ticker") or row.get("symbol"), "UNKNOWN"),
        safe_upper(row.get("sec_type") or row.get("security_type"), "UNKNOWN"),
        safe_upper(row.get("right")),
        str(row.get("strike") or ""),
        str(row.get("expiration") or row.get("lastTradeDateOrContractMonth") or ""),
        str(row.get("local_symbol") or ""),
    ]
    return "|".join(parts)


def normalize_position(row: dict[str, Any]) -> dict[str, Any]:
    row = row if isinstance(row, dict) else {}
    ticker = safe_upper(row.get("ticker") or row.get("symbol"), "UNKNOWN")
    sec_type = safe_upper(row.get("sec_type") or row.get("security_type") or row.get("asset_class"), "UNKNOWN")
    qty = safe_float(row.get("position_size", row.get("position", row.get("quantity", row.get("qty")))), 0.0) or 0.0
    multiplier = safe_float(row.get("multiplier") or row.get("contract_multiplier"), DEFAULT_CONTRACT_MULTIPLIER) or DEFAULT_CONTRACT_MULTIPLIER
    expiration = row.get("expiration") or row.get("lastTradeDateOrContractMonth")
    dte = safe_float(row.get("dte"))
    if dte is None:
        parsed_dte = days_to_expiration(expiration)
        dte = float(parsed_dte) if parsed_dte is not None else None
    normalized = dict(row)
    normalized.update({
        "position_id": str(row.get("position_id") or _position_key(row)),
        "ticker": ticker,
        "sec_type": sec_type,
        "right": safe_upper(row.get("right")) if sec_type in ["OPT", "OPTION"] else "",
        "strike": safe_float(row.get("strike")),
        "expiration": expiration,
        "dte": dte,
        "position_size": qty,
        "avg_cost": safe_float(row.get("avg_cost")),
        "market_price": safe_float(row.get("market_price") or row.get("price")),
        "market_value": safe_float(row.get("market_value")),
        "unrealized_pl": safe_float(row.get("unrealized_pl") or row.get("unrealized_pnl")),
        "portfolio_weight_pct": safe_float(row.get("portfolio_weight_pct")),
        "multiplier": multiplier,
    })
    return normalized


def _technical_by_ticker(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    raw = snapshot.get("technical_snapshot")
    if raw is None:
        raw = snapshot.get("technical") or snapshot.get("technical_by_ticker")
    out: dict[str, dict[str, Any]] = {}

    def add(value: Any, forced_ticker: Any = None) -> None:
        if not isinstance(value, dict):
            return
        sec_type = safe_upper(value.get("sec_type") or value.get("security_type") or value.get("asset_class"))
        right = safe_upper(value.get("right") or value.get("option_type"))
        if sec_type in {"OPT", "OPTION"} or (right in {"C", "P"} and value.get("strike") not in [None, ""]):
            return
        ticker = safe_upper(value.get("ticker") or value.get("symbol") or forced_ticker)
        strong_technical = any(
            key in value
            for key in [
                "trend",
                "bias",
                "technical_bias",
                "support",
                "support_level",
                "support_levels",
                "support_near",
                "support_broken",
                "resistance",
                "resistance_level",
                "resistance_levels",
                "resistance_near",
                "range_breakout",
                "event_risk",
                "gamma",
                "gamma_context",
                "gamma_wall",
                "call_wall",
                "put_wall",
            ]
        )
        price_context = any(value.get(key) not in [None, ""] for key in ["price", "underlying_price"])
        looks_like_decision_row = bool(value.get("decision") or value.get("final_decision")) and bool(value.get("strategy") or value.get("strategy_hint"))
        explicit_directional_context = any(key in value for key in ["trend", "bias", "technical_bias", "support", "support_level", "resistance", "resistance_level"])
        if looks_like_decision_row and not explicit_directional_context:
            return
        looks_technical = strong_technical or (price_context and not looks_like_decision_row)
        if ticker and looks_technical:
            item = {**dict(out.get(ticker) or {}), **dict(value)}
            item["ticker"] = ticker
            spot = safe_float(item.get("spot"))
            if spot is not None:
                item["price"] = spot
                item["underlying_price"] = spot
            support_levels = [safe_float(level) for level in (item.get("support_levels") or [])] if isinstance(item.get("support_levels"), list) else []
            support_levels = [level for level in support_levels if level is not None]
            resistance_levels = [safe_float(level) for level in (item.get("resistance_levels") or [])] if isinstance(item.get("resistance_levels"), list) else []
            resistance_levels = [level for level in resistance_levels if level is not None]
            if support_levels and item.get("support") is None:
                item["support"] = max([level for level in support_levels if spot is None or level <= spot], default=max(support_levels))
                item["support_level"] = item["support"]
            if resistance_levels and item.get("resistance") is None:
                item["resistance"] = min([level for level in resistance_levels if spot is None or level >= spot], default=min(resistance_levels))
                item["resistance_level"] = item["resistance"]
            out[ticker] = item

    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                add(value, key)
        add(raw)
    elif isinstance(raw, list):
        for item in raw:
            add(item)
    runtime_data = snapshot.get("runtime_data") if isinstance(snapshot.get("runtime_data"), dict) else {}
    for item in _walk_dicts(runtime_data):
        add(item)

    active_technical = runtime_data.get("active_position_technical_latest.json")
    if isinstance(active_technical, dict):
        active_by_ticker = active_technical.get("by_ticker") if isinstance(active_technical.get("by_ticker"), dict) else {}
        for ticker, item in active_by_ticker.items():
            add(item, ticker)
    rsp_manual_context = runtime_data.get("coberturas_rsp_manual_context.json")
    if isinstance(rsp_manual_context, dict):
        add(rsp_manual_context, "RSP")

    # The per-position chain store is intentionally durable: a later generic
    # scan may contain empty technical rows, while the last successful chain
    # still has the broker-observed stock price. Apply that price last so open
    # positions do not lose actionable sizing and moneyness context.
    chain_stores: list[dict[str, Any]] = []
    top_level_store = snapshot.get("active_position_option_chains")
    if isinstance(top_level_store, dict):
        chain_stores.append(top_level_store)
    runtime_store = runtime_data.get("active_position_option_chains_latest.json")
    if isinstance(runtime_store, dict):
        chain_stores.append(runtime_store)
    for store in chain_stores:
        by_ticker = store.get("by_ticker") if isinstance(store.get("by_ticker"), dict) else {}
        for raw_ticker, block in by_ticker.items():
            if not isinstance(block, dict):
                continue
            ticker = safe_upper(raw_ticker)
            event = block.get("chain_event") if isinstance(block.get("chain_event"), dict) else {}
            price = safe_float(event.get("stock_price") or event.get("underlying_price"))
            if price is None:
                rows = block.get("option_rows") if isinstance(block.get("option_rows"), list) else []
                for option_row in rows:
                    if isinstance(option_row, dict):
                        price = safe_float(option_row.get("underlying_price"))
                    if price is not None:
                        break
            if not ticker or price is None:
                continue
            technical = dict(out.get(ticker) or {"ticker": ticker})
            technical["ticker"] = ticker
            technical["price"] = price
            technical["underlying_price"] = price
            technical["position_chain_generated_at"] = block.get("last_successful_at") or event.get("generated_at")
            out[ticker] = technical
    gamma_payload = snapshot.get("gamma_contexts") if isinstance(snapshot.get("gamma_contexts"), dict) else None
    if gamma_payload is None and isinstance(snapshot.get("runtime_data"), dict):
        gamma_payload = snapshot["runtime_data"].get("gamma_contexts.json")
    for ticker, gamma in gamma_context_store.by_ticker(gamma_payload).items():
        technical = dict(out.get(ticker) or {"ticker": ticker})
        for key in ["gamma_wall", "call_wall", "put_wall", "zero_gamma", "net_gamma", "gamma_exposure"]:
            if gamma.get(key) is not None:
                technical[key] = gamma.get(key)
        support_levels = gamma.get("support_levels") if isinstance(gamma.get("support_levels"), list) else []
        resistance_levels = gamma.get("resistance_levels") if isinstance(gamma.get("resistance_levels"), list) else []
        spot = safe_float(gamma.get("spot"))
        if spot is not None:
            technical["price"] = spot
            technical["underlying_price"] = spot
        if support_levels:
            technical["support_levels"] = support_levels
            technical["support"] = max([value for value in support_levels if spot is None or value <= spot], default=max(support_levels))
            technical["support_level"] = technical["support"]
        if resistance_levels:
            technical["resistance_levels"] = resistance_levels
            technical["resistance"] = min([value for value in resistance_levels if spot is None or value >= spot], default=min(resistance_levels))
            technical["resistance_level"] = technical["resistance"]
        for key in ["expected_move_low", "expected_move_high", "gamma_bias"]:
            if gamma.get(key) not in [None, ""]:
                technical[key] = gamma.get(key)
        technical["gamma_context"] = {
            "source": gamma.get("source"),
            "as_of": gamma.get("as_of"),
            "notes": gamma.get("notes"),
        }
        technical["ticker"] = ticker
        out[ticker] = technical
    return out


def _position_groups(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in positions:
        ticker = safe_upper(row.get("ticker"), "UNKNOWN")
        group = groups.setdefault(ticker, {"shares": 0.0, "stock_value": 0.0, "short_calls": 0.0, "short_puts": 0.0})
        qty = safe_float(row.get("position_size"), 0.0) or 0.0
        sec_type = safe_upper(row.get("sec_type"))
        right = safe_upper(row.get("right"))
        if sec_type in ["STK", "STOCK", "EQUITY"]:
            group["shares"] += qty
            group["stock_value"] += abs(safe_float(row.get("market_value"), 0.0) or 0.0)
        if sec_type in ["OPT", "OPTION"]:
            if right == "C" and qty < 0:
                group["short_calls"] += abs(qty)
            if right == "P" and qty < 0:
                group["short_puts"] += abs(qty)
    return groups


def _dedupe_position_copies(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove identical position copies propagated through multiple snapshots."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in positions:
        account = safe_upper(row.get("account_alias") or row.get("account_scope") or row.get("account"))
        strike = safe_float(row.get("strike"))
        strike = None if strike in [None, 0.0] else strike
        key = (
            safe_upper(row.get("ticker")),
            safe_upper(row.get("sec_type")),
            safe_upper(row.get("right")),
            strike,
            str(row.get("expiration") or ""),
            str(row.get("local_symbol") or ""),
            safe_float(row.get("position_size"), 0.0),
            account,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _position_contexts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    candidates = []
    for key in ["active_position_contexts", "position_contexts"]:
        value = snapshot.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            rows = value.get("contexts") if isinstance(value.get("contexts"), list) else []
            candidates.extend(item for item in rows if isinstance(item, dict))
    runtime_data = snapshot.get("runtime_data") if isinstance(snapshot.get("runtime_data"), dict) else {}
    for value in runtime_data.values():
        if isinstance(value, dict) and value.get("context_store_version"):
            rows = value.get("contexts") if isinstance(value.get("contexts"), list) else []
            candidates.extend(item for item in rows if isinstance(item, dict))
    return [position_context_store.normalize_context(item) for item in candidates]


def _option_candidates_by_ticker(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    sources: list[dict[str, Any]] = []
    runtime_data = snapshot.get("runtime_data") if isinstance(snapshot.get("runtime_data"), dict) else {}
    for key in ["active_position_option_chains", "option_chain_coverage", "v32_ibkr_chain_coverage"]:
        value = snapshot.get(key)
        if isinstance(value, dict):
            sources.append(value)
    for filename, value in runtime_data.items():
        if isinstance(value, dict) and (
            "chain" in str(filename).lower()
            or value.get("store_version") == "active_position_option_chain_store_v1"
            or value.get("diagnostic_version")
        ):
            sources.append(value)

    def add(row: dict[str, Any], forced_ticker: str = "") -> None:
        ticker = safe_upper(row.get("ticker") or row.get("symbol") or forced_ticker)
        if not ticker:
            return
        right = safe_upper(row.get("right") or row.get("option_type"))
        strategy = safe_upper(row.get("strategy") or row.get("strategy_hint"))
        if not right:
            right = "C" if "CALL" in strategy else "P" if "PUT" in strategy else ""
        if right not in {"C", "P"}:
            return
        normalized = dict(row)
        normalized.update({
            "ticker": ticker,
            "right": right,
            "strike": safe_float(row.get("strike")),
            "dte": safe_float(row.get("dte")),
            "bid": safe_float(row.get("bid")),
            "ask": safe_float(row.get("ask")),
            "mid": safe_float(row.get("mid")),
            "delta": safe_float(row.get("delta")),
            "spread_pct": safe_float(row.get("spread_pct")),
            "expiration": row.get("expiration") or row.get("expiry"),
        })
        out.setdefault(ticker, []).append(normalized)

    for source in sources:
        by_ticker = source.get("by_ticker") if isinstance(source.get("by_ticker"), dict) else {}
        for ticker, block in by_ticker.items():
            if isinstance(block, dict):
                for row in block.get("option_rows") or []:
                    if isinstance(row, dict):
                        add(row, safe_upper(ticker))
        for row in source.get("option_rows") or []:
            if isinstance(row, dict):
                add(row)

    for ticker, rows in list(out.items()):
        seen = set()
        unique = []
        for row in rows:
            key = (row.get("right"), row.get("expiration"), row.get("strike"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        out[ticker] = unique
    return out


def infer_strategy(row: dict[str, Any], group: dict[str, Any] | None = None) -> str:
    explicit = safe_upper(row.get("strategy") or row.get("strategy_hint") or row.get("position_strategy"))
    if explicit:
        if explicit in ["NAKED_PUT", "SHORT_PUT"]:
            return "CASH_SECURED_PUT"
        return explicit
    group = group if isinstance(group, dict) else {}
    sec_type = safe_upper(row.get("sec_type"))
    qty = safe_float(row.get("position_size"), 0.0) or 0.0
    right = safe_upper(row.get("right"))
    position_class = safe_upper(row.get("position_class"))
    if position_class in ["COVERED_CALL_CANDIDATE", "LONG_STOCK_SMALL", "LONG_STOCK"] and qty > 0:
        return "LONG_STOCK"
    if sec_type == "POSITION" and qty > 0 and not right:
        return "LONG_STOCK"
    if sec_type in ["STK", "STOCK", "EQUITY"] and qty > 0:
        return "LONG_STOCK"
    if sec_type in ["OPT", "OPTION"] and right == "P" and qty < 0:
        return "CASH_SECURED_PUT"
    if sec_type in ["OPT", "OPTION"] and right == "C" and qty < 0:
        required_shares = abs(qty) * DEFAULT_CONTRACT_MULTIPLIER
        return "COVERED_CALL" if (safe_float(group.get("shares"), 0.0) or 0.0) >= required_shares else "SHORT_CALL_UNCOVERED_REVIEW"
    if sec_type in ["OPT", "OPTION"] and right == "C" and qty > 0:
        return "LONG_CALL"
    if sec_type in ["OPT", "OPTION"] and right == "P" and qty > 0:
        return "LONG_PUT"
    if sec_type in ["FUT", "CONTFUT"]:
        return "FUTURES_POSITION"
    return "POSITION"


def _option_mark(row: dict[str, Any]) -> float | None:
    mark = safe_float(
        row.get("option_mid_or_mark")
        or row.get("option_mark")
        or row.get("mark")
        or row.get("mid")
        or row.get("market_price")
        or row.get("price")
    )
    multiplier = safe_float(row.get("multiplier"), DEFAULT_CONTRACT_MULTIPLIER) or DEFAULT_CONTRACT_MULTIPLIER
    if mark is not None and mark > 25 and safe_upper(row.get("sec_type")) in ["OPT", "OPTION"]:
        return round(mark / multiplier, 4)
    return mark


def _entry_credit(row: dict[str, Any]) -> float | None:
    credit = safe_float(row.get("entry_credit") or row.get("credit") or row.get("avg_credit"))
    if credit is not None:
        return credit
    avg_cost = safe_float(row.get("avg_cost"))
    if avg_cost is None:
        return None
    multiplier = safe_float(row.get("multiplier"), DEFAULT_CONTRACT_MULTIPLIER) or DEFAULT_CONTRACT_MULTIPLIER
    value = abs(avg_cost)
    if value > 25 and safe_upper(row.get("sec_type")) in ["OPT", "OPTION"]:
        value = value / multiplier
    return round(value, 4)


def _premium_capture_pct(row: dict[str, Any]) -> float | None:
    qty = safe_float(row.get("position_size"), 0.0) or 0.0
    if qty >= 0:
        return None
    credit = _entry_credit(row)
    mark = _option_mark(row)
    if credit is None or credit <= 0 or mark is None:
        return None
    return round(((credit - mark) / credit) * 100.0, 2)


def _technical_context(row: dict[str, Any], technical_store: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ticker = safe_upper(row.get("ticker"))
    technical = dict(technical_store.get(ticker) or {})
    qty = safe_float(row.get("position_size"), 0.0) or 0.0
    market_value = safe_float(row.get("market_value"))
    is_stock = safe_upper(row.get("sec_type")) in ["STK", "STOCK", "EQUITY"]
    implied_stock_price = abs(market_value / qty) if is_stock and market_value is not None and qty else None
    row_underlying = row.get("underlying_price") if is_stock else None
    price = safe_float(
        row_underlying
        or (row.get("market_price") if is_stock else None)
        or technical.get("underlying_price")
        or technical.get("price")
        or implied_stock_price
    )
    support = safe_float(technical.get("support") or technical.get("support_level") or technical.get("nearest_support"))
    resistance = safe_float(technical.get("resistance") or technical.get("resistance_level") or technical.get("nearest_resistance"))
    trend = safe_upper(technical.get("trend") or technical.get("bias") or technical.get("technical_bias"), "UNKNOWN")
    gamma_context = technical.get("gamma_context") if isinstance(technical.get("gamma_context"), dict) else {}
    gamma_fields = {
        key: technical.get(key)
        for key in ["gamma_wall", "call_wall", "put_wall", "gamma_exposure", "net_gamma", "zero_gamma"]
        if technical.get(key) not in [None, "", [], {}]
    }
    if gamma_context:
        gamma_fields["gamma_context"] = gamma_context
    support_broken = bool(technical.get("support_broken") or technical.get("technical_breakdown"))
    if price is not None and support is not None and price < support:
        support_broken = True
    resistance_breakout = bool(technical.get("range_breakout") or technical.get("resistance_breakout"))
    if price is not None and resistance is not None and price > resistance:
        resistance_breakout = True
    return {
        "available": bool(technical),
        "ticker": ticker,
        "trend": trend,
        "score": safe_float(technical.get("technical_score") or technical.get("score")),
        "price": price,
        "support": support,
        "resistance": resistance,
        "support_near": technical.get("support_near"),
        "resistance_near": technical.get("resistance_near"),
        "support_broken": support_broken,
        "resistance_breakout": resistance_breakout,
        "event_risk": bool(technical.get("event_risk") or technical.get("earnings_soon")),
        "indicators": technical.get("indicators") if isinstance(technical.get("indicators"), dict) else {},
        "expected_move_low": safe_float(technical.get("expected_move_low")),
        "expected_move_high": safe_float(technical.get("expected_move_high")),
        "gamma": gamma_fields,
        "gamma_available": bool(gamma_fields),
        "raw_fields_present": sorted([key for key in technical.keys() if key not in {"account", "token", "secret"}])[:60],
    }


def _context_freshness(snapshot: dict[str, Any], account_context: dict[str, Any], max_age_minutes: int) -> dict[str, Any]:
    candidates = [
        snapshot.get("generated_at"),
        account_context.get("generated_at") if isinstance(account_context, dict) else None,
    ]
    ages = [age_minutes(value) for value in candidates if value]
    ages = [age for age in ages if age is not None]
    warnings: list[str] = []
    blockers: list[str] = []
    status = "UNKNOWN"
    if not ages:
        warnings.append("POSITION_CONTEXT_TIMESTAMP_MISSING")
        status = "WARNING"
    else:
        max_age = max(ages)
        status = "FRESH" if max_age <= max_age_minutes else "STALE"
        if status == "STALE":
            blockers.append("POSITION_CONTEXT_STALE")
    return {
        "status": status,
        "ok": status == "FRESH",
        "age_minutes": max(ages) if ages else None,
        "max_age_minutes": max_age_minutes,
        "blockers": blockers,
        "warnings": warnings,
        "not_order_instruction": True,
    }


def _market_regime(snapshot: dict[str, Any], technical: dict[str, Any]) -> str:
    for value in [
        technical.get("market_regime"),
        technical.get("regime"),
        (snapshot.get("market") or {}).get("regime") if isinstance(snapshot.get("market"), dict) else None,
        (snapshot.get("risk_profile") or {}).get("market_regime") if isinstance(snapshot.get("risk_profile"), dict) else None,
    ]:
        text = safe_upper(value)
        if text:
            if "HIGH" in text and ("VOL" in text or "EVENT" in text):
                return "HIGH_VOL_EVENT_RISK"
            if "BEAR" in text or "CORRECTION" in text:
                return "BEARISH_OR_CORRECTION"
            if "RANGE" in text or "NEUTRAL" in text:
                return "NEUTRAL_RANGE"
            if "BULL" in text:
                return "BULLISH_LOW_VOL"
            return text
    trend = safe_upper(technical.get("trend"))
    if trend in ["BEARISH", "DOWN", "SELL"]:
        return "BEARISH_OR_CORRECTION"
    if trend in ["BULLISH", "UP", "BUY"]:
        return "BULLISH_LOW_VOL"
    return "NEUTRAL_RANGE"


def _threshold(block: dict[str, Any], key: str, default: float) -> float:
    value = safe_float(block.get(key), default)
    return value if value is not None else default


def _thesis_from_context(row: dict[str, Any], strategy: str, technical: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("thesis") if isinstance(row.get("thesis"), dict) else {}
    invalidation = raw.get("invalidation_level") or row.get("invalidation_level")
    if invalidation is None:
        if strategy in ["CASH_SECURED_PUT", "LONG_STOCK"]:
            invalidation = technical.get("support") or row.get("strike")
        elif strategy == "COVERED_CALL":
            invalidation = technical.get("resistance") or row.get("strike")
    target = raw.get("target") or row.get("target_price")
    if target is None and strategy in ["CASH_SECURED_PUT", "COVERED_CALL"]:
        target = "premium_capture"
    thesis_text = (
        raw.get("text")
        or row.get("entry_thesis")
        or row.get("trade_thesis")
        or row.get("notes")
        or "No saved entry thesis; using strategy playbook and current technical context."
    )
    status = "AVAILABLE" if raw or any(row.get(key) for key in ["entry_thesis", "trade_thesis", "invalidation_level", "target_price"]) else "INFERRED"
    thesis_intact = True
    reasons: list[str] = []
    price = safe_float(technical.get("price"))
    invalidation_float = safe_float(invalidation)
    if technical.get("event_risk"):
        thesis_intact = False
        reasons.append("EVENT_RISK_ACTIVE")
    if technical.get("support_broken") and strategy in ["CASH_SECURED_PUT", "LONG_STOCK"]:
        thesis_intact = False
        reasons.append("SUPPORT_BROKEN")
    if technical.get("resistance_breakout") and strategy == "COVERED_CALL":
        thesis_intact = False
        reasons.append("RESISTANCE_BREAKOUT_AGAINST_CALL")
    if price is not None and invalidation_float is not None:
        if strategy in ["CASH_SECURED_PUT", "LONG_STOCK"] and price < invalidation_float:
            thesis_intact = False
            reasons.append("PRICE_BELOW_INVALIDATION")
        if strategy == "COVERED_CALL" and price > invalidation_float:
            reasons.append("PRICE_ABOVE_CALL_REVIEW_LEVEL")
    return {
        "thesis_version": "position_thesis_v1",
        "status": status,
        "text": thesis_text,
        "entry_reason": raw.get("entry_reason") or row.get("entry_reason"),
        "invalidation_level": invalidation,
        "target": target,
        "assignment_preference": raw.get("assignment_preference") or row.get("assignment_preference"),
        "roll_plan": raw.get("roll_plan") or row.get("roll_plan"),
        "thesis_intact": thesis_intact,
        "thesis_risks": reasons,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def _scenario_analysis(row: dict[str, Any], strategy: str, technical: dict[str, Any]) -> dict[str, Any]:
    price = safe_float(technical.get("price") or row.get("underlying_price"))
    strike = safe_float(row.get("strike"))
    qty = safe_float(row.get("position_size"), 0.0) or 0.0
    mark = _option_mark(row)
    credit = _entry_credit(row)
    delta = safe_float(row.get("delta") or row.get("option_delta"), 0.0) or 0.0
    multiplier = safe_float(row.get("multiplier"), DEFAULT_CONTRACT_MULTIPLIER) or DEFAULT_CONTRACT_MULTIPLIER
    scenarios = []
    for move in SCENARIO_MOVES_PCT:
        scenario_price = round(price * (1 + move / 100.0), 2) if price is not None else None
        estimated_option_mark = None
        estimated_pnl = None
        assignment_flag = False
        called_away_flag = False
        if scenario_price is not None and mark is not None and price is not None and safe_upper(row.get("sec_type")) in ["OPT", "OPTION"]:
            estimated_option_mark = max(0.01, round(mark + delta * (scenario_price - price), 2))
            if qty < 0 and credit is not None:
                estimated_pnl = round((credit - estimated_option_mark) * abs(qty) * multiplier, 2)
        elif scenario_price is not None and safe_upper(row.get("sec_type")) in ["STK", "STOCK", "EQUITY"]:
            avg_cost = safe_float(row.get("avg_cost"))
            if avg_cost is not None:
                estimated_pnl = round((scenario_price - avg_cost) * qty, 2)
        if strategy == "CASH_SECURED_PUT" and strike is not None and scenario_price is not None:
            assignment_flag = scenario_price < strike
        if strategy == "COVERED_CALL" and strike is not None and scenario_price is not None:
            called_away_flag = scenario_price > strike
        scenarios.append({
            "underlying_move_pct": move,
            "underlying_price": scenario_price,
            "estimated_option_mark": estimated_option_mark,
            "estimated_position_pnl": estimated_pnl,
            "assignment_review": assignment_flag,
            "called_away_review": called_away_flag,
        })
    return {
        "scenario_version": "position_scenario_v1",
        "method": "simple_delta_and_threshold_estimate",
        "available": price is not None,
        "scenarios": scenarios,
        "limitations": [
            "Uses simple delta/threshold estimates when full greeks or volatility surface are missing.",
            "Manual broker/TWS validation is still required.",
        ],
        "not_order_instruction": True,
    }


def _contract_review_status(row: dict[str, Any]) -> str:
    critical = {"NO_BID_ASK", "NO_VALID_OPTION_PRICE", "NO_GREEKS", "NO_SPREAD"}
    missing = set(row.get("missing_execution_fields") or [])
    discard = set(row.get("discard_reasons") or [])
    if row.get("bid") is None or row.get("ask") is None or row.get("mid") is None:
        return "WAIT_MARKET_DATA"
    if missing.intersection({"bid", "ask", "mid", "spread_pct", "delta"}) or discard.intersection(critical):
        return "WAIT_MARKET_DATA"
    spread = safe_float(row.get("spread_pct"))
    if spread is not None and spread > 25:
        return "WAIT_LIQUIDITY"
    return "READY_FOR_MANUAL_REVIEW"


def _contract_summary(row: dict[str, Any], price: float | None) -> dict[str, Any]:
    strike = safe_float(row.get("strike"))
    right = safe_upper(row.get("right"))
    mid = safe_float(row.get("mid"))
    moneyness = "UNKNOWN"
    if strike is not None and price is not None and price > 0:
        distance = (strike - price) / price
        if abs(distance) <= 0.0025:
            moneyness = "ATM"
        elif (right == "C" and strike < price) or (right == "P" and strike > price):
            moneyness = "ITM"
        else:
            moneyness = "OTM"
    return {
        "right": right,
        "expiration": row.get("expiration"),
        "dte": row.get("dte"),
        "strike": strike,
        "moneyness": moneyness,
        "bid": row.get("bid"),
        "ask": row.get("ask"),
        "mid": mid,
        "bid_per_contract": round((safe_float(row.get("bid")) or 0.0) * DEFAULT_CONTRACT_MULTIPLIER, 2) if safe_float(row.get("bid")) is not None else None,
        "ask_per_contract": round((safe_float(row.get("ask")) or 0.0) * DEFAULT_CONTRACT_MULTIPLIER, 2) if safe_float(row.get("ask")) is not None else None,
        "premium_per_contract": round(mid * DEFAULT_CONTRACT_MULTIPLIER, 2) if mid is not None else None,
        "delta": row.get("delta"),
        "implied_volatility": row.get("implied_volatility") or row.get("iv"),
        "volume": row.get("volume"),
        "open_interest": row.get("open_interest"),
        "spread_pct": row.get("spread_pct"),
        "review_status": _contract_review_status(row),
        "not_order_instruction": True,
    }


def _rank_contracts(rows: list[dict[str, Any]], right: str, price: float | None) -> list[dict[str, Any]]:
    candidates = [_contract_summary(row, price) for row in rows if safe_upper(row.get("right")) == right]
    status_rank = {"READY_FOR_MANUAL_REVIEW": 0, "WAIT_LIQUIDITY": 1, "WAIT_MARKET_DATA": 2}
    target_distance = 0.02
    candidates.sort(key=lambda row: (
        status_rank.get(str(row.get("review_status")), 9),
        abs(abs(((safe_float(row.get("strike"), price) or 0) - (price or 0)) / price) - target_distance) if price else 999,
        safe_float(row.get("spread_pct"), 999) or 999,
    ))
    return candidates


def _alternative(
    alternative_id: str,
    label: str,
    category: str,
    status: str,
    reason: str,
    *,
    contracts: int | None = None,
    candidates: list[dict[str, Any]] | None = None,
    effects: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "alternative_id": alternative_id,
        "label": label,
        "category": category,
        "status": status,
        "reason": reason,
        "contracts": contracts,
        "contract_candidates": (candidates or [])[:5],
        "effects": effects or [],
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _long_stock_strategy_comparison(
    price: float | None,
    shares: float,
    uncovered_share_lots: int,
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    technical: dict[str, Any],
) -> dict[str, Any]:
    if price is None or price <= 0 or shares <= 0:
        return {"available": False, "reason": "UNDERLYING_PRICE_MISSING", "variants": []}
    indicators = technical.get("indicators") if isinstance(technical.get("indicators"), dict) else {}
    atr = safe_float(indicators.get("atr_14")) or price * 0.04
    support = safe_float(technical.get("support"))
    resistance = safe_float(technical.get("resistance"))
    trend = safe_upper(technical.get("trend"), "UNKNOWN")
    deep_down = max(price * 0.65, min(price * 0.80, price - (3 * atr)))
    support_case = support if support is not None and deep_down < support < price else max(deep_down, price - atr)
    resistance_case = resistance if resistance is not None and resistance > price else price + max(2 * atr, price * 0.08)
    strong_up = max(price * 1.20, resistance_case + atr)
    if trend in {"BEARISH", "DOWN", "SELL", "NEUTRAL_TO_BEARISH"}:
        weights = [0.25, 0.25, 0.20, 0.20, 0.10]
    elif trend in {"BULLISH", "UP", "BUY", "NEUTRAL_TO_BULLISH"}:
        weights = [0.10, 0.15, 0.20, 0.25, 0.30]
    else:
        weights = [0.15, 0.20, 0.25, 0.25, 0.15]
    scenarios = [
        {"scenario_id": "DEEP_DOWNSIDE", "label": "Caída fuerte", "price": round(deep_down, 2), "weight": weights[0]},
        {"scenario_id": "SUPPORT", "label": "Zona de soporte", "price": round(support_case, 2), "weight": weights[1]},
        {"scenario_id": "FLAT", "label": "Sin cambio", "price": round(price, 4), "weight": weights[2]},
        {"scenario_id": "RESISTANCE", "label": "Rebote a resistencia", "price": round(resistance_case, 2), "weight": weights[3]},
        {"scenario_id": "STRONG_UPSIDE", "label": "Subida fuerte", "price": round(strong_up, 2), "weight": weights[4]},
    ]

    def summarize(
        alternative_id: str,
        label: str,
        pnl_fn: Any,
        *,
        contracts: int | None = None,
        contract: dict[str, Any] | None = None,
        put_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        outcomes = []
        for scenario in scenarios:
            pnl = round(float(pnl_fn(float(scenario["price"]))), 2)
            outcomes.append({**scenario, "estimated_pnl_from_now": pnl})
        by_id = {item["scenario_id"]: item["estimated_pnl_from_now"] for item in outcomes}
        weighted = round(sum(item["estimated_pnl_from_now"] * item["weight"] for item in outcomes), 2)
        worst = min(item["estimated_pnl_from_now"] for item in outcomes)
        return {
            "variant_id": alternative_id + ("_{}".format(contracts) if contracts else ""),
            "alternative_id": alternative_id,
            "label": label,
            "contracts": contracts,
            "coverage_pct": round((contracts * DEFAULT_CONTRACT_MULTIPLIER / shares) * 100, 1) if contracts else None,
            "contract": contract,
            "put_contract": put_contract,
            "weighted_pnl": weighted,
            "worst_case_pnl": worst,
            "flat_pnl": by_id.get("FLAT"),
            "support_pnl": by_id.get("SUPPORT"),
            "resistance_pnl": by_id.get("RESISTANCE"),
            "strong_upside_pnl": by_id.get("STRONG_UPSIDE"),
            "balanced_score": round(weighted + (0.12 * worst), 2),
            "scenario_outcomes": outcomes,
            "execution_authorized": False,
            "not_order_instruction": True,
        }

    variants = [
        summarize("HOLD_MONITOR", "Mantener", lambda terminal: (terminal - price) * shares),
    ]
    reduction_shares = max(1, int(round(shares * 0.25)))
    variants.append(summarize(
        "REDUCE_25",
        "Reducir 25%",
        lambda terminal: (terminal - price) * max(0.0, shares - reduction_shares),
    ))
    target_contracts = uncovered_share_lots * 0.25
    contract_choices = sorted({
        max(1, min(uncovered_share_lots, int(math.floor(target_contracts)))),
        max(1, min(uncovered_share_lots, int(math.ceil(target_contracts)))),
    }) if uncovered_share_lots else []
    ready_calls = [item for item in calls if item.get("review_status") == "READY_FOR_MANUAL_REVIEW" and safe_float(item.get("bid")) is not None]
    ready_puts = [item for item in puts if item.get("review_status") == "READY_FOR_MANUAL_REVIEW" and safe_float(item.get("ask")) is not None]
    for contracts in contract_choices:
        covered_shares = contracts * DEFAULT_CONTRACT_MULTIPLIER
        for call in ready_calls[:6]:
            strike = safe_float(call.get("strike"))
            premium = safe_float(call.get("bid"))
            if strike is None or premium is None:
                continue
            variants.append(summarize(
                "COVERED_CALL_PARTIAL",
                "Covered call parcial",
                lambda terminal, strike=strike, premium=premium, covered_shares=covered_shares: (
                    (terminal - price) * shares
                    + premium * covered_shares
                    - max(0.0, terminal - strike) * covered_shares
                ),
                contracts=contracts,
                contract=call,
            ))
        for call in ready_calls[:4]:
            for put in ready_puts[:4]:
                if call.get("expiration") and put.get("expiration") and call.get("expiration") != put.get("expiration"):
                    continue
                call_strike = safe_float(call.get("strike"))
                put_strike = safe_float(put.get("strike"))
                call_premium = safe_float(call.get("bid"))
                put_cost = safe_float(put.get("ask"))
                if None in [call_strike, put_strike, call_premium, put_cost]:
                    continue
                protected_shares = contracts * DEFAULT_CONTRACT_MULTIPLIER
                variants.append(summarize(
                    "COLLAR",
                    "Collar parcial",
                    lambda terminal, cs=call_strike, ps=put_strike, cp=call_premium, pc=put_cost, protected=protected_shares: (
                        (terminal - price) * shares
                        + (cp - pc) * protected
                        - max(0.0, terminal - cs) * protected
                        + max(0.0, ps - terminal) * protected
                    ),
                    contracts=contracts,
                    contract=call,
                    put_contract=put,
                ))

    def score_value(item: dict[str, Any], score_key: str) -> float:
        value = safe_float(item.get(score_key))
        return value if value is not None else -1e18

    def best(rows: list[dict[str, Any]], score_key: str) -> dict[str, Any] | None:
        return max(rows, key=lambda item: score_value(item, score_key)) if rows else None

    call_variants = [item for item in variants if item.get("alternative_id") == "COVERED_CALL_PARTIAL"]
    collar_variants = [item for item in variants if item.get("alternative_id") == "COLLAR"]
    preferred_call = best(call_variants, "balanced_score")
    profile_candidates = {
        "capital_protection": max(variants, key=lambda item: score_value(item, "worst_case_pnl")),
        "balanced": best(variants, "balanced_score"),
        "income_recovery": (
            max(
                call_variants,
                key=lambda item: (
                    (item.get("flat_pnl") or 0) * 0.30
                    + (item.get("support_pnl") or 0) * 0.20
                    + (item.get("resistance_pnl") or 0) * 0.35
                    + (item.get("worst_case_pnl") or 0) * 0.15
                ),
            )
            if call_variants
            else None
        ),
        "upside_preservation": max(variants, key=lambda item: score_value(item, "strong_upside_pnl")),
    }
    return {
        "comparison_version": "long_stock_strategy_comparison_v1",
        "available": True,
        "price": round(price, 4),
        "shares": shares,
        "target_overlay_pct": 25.0,
        "contract_choices": contract_choices,
        "scenarios": scenarios,
        "variants": sorted(variants, key=lambda item: score_value(item, "balanced_score"), reverse=True),
        "preferred_covered_call": preferred_call,
        "preferred_collar": best(collar_variants, "balanced_score"),
        "profile_leaders": {
            name: ({key: value for key, value in leader.items() if key != "scenario_outcomes"} if leader else None)
            for name, leader in profile_candidates.items()
        },
        "limitations": [
            "P/L is measured from the current underlying price, before commissions and taxes.",
            "Selling calls uses bid and buying puts uses ask for conservative review.",
            "Scenario weights are technical-review weights, not probabilities or return guarantees.",
        ],
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _management_alternatives(
    row: dict[str, Any],
    strategy: str,
    technical: dict[str, Any],
    group: dict[str, Any],
    option_rows: list[dict[str, Any]],
    management_action: str,
) -> dict[str, Any]:
    price = safe_float(technical.get("price") or row.get("underlying_price") or row.get("market_price"))
    qty = safe_float(row.get("position_size"), 0.0) or 0.0
    shares = max(0.0, safe_float(group.get("shares"), 0.0) or 0.0)
    share_lots = int(shares // DEFAULT_CONTRACT_MULTIPLIER)
    short_calls = int(safe_float(group.get("short_calls"), 0.0) or 0.0)
    uncovered_share_lots = max(0, share_lots - short_calls)
    calls = _rank_contracts(option_rows, "C", price)
    puts = _rank_contracts(option_rows, "P", price)
    strategy_comparison = (
        _long_stock_strategy_comparison(price, shares, uncovered_share_lots, calls, puts, technical)
        if strategy == "LONG_STOCK"
        else {"available": False, "variants": []}
    )
    preferred_call = strategy_comparison.get("preferred_covered_call") if isinstance(strategy_comparison.get("preferred_covered_call"), dict) else {}
    preferred_collar = strategy_comparison.get("preferred_collar") if isinstance(strategy_comparison.get("preferred_collar"), dict) else {}
    profile_leaders = strategy_comparison.get("profile_leaders") if isinstance(strategy_comparison.get("profile_leaders"), dict) else {}
    balanced_leader = profile_leaders.get("balanced") if isinstance(profile_leaders.get("balanced"), dict) else {}
    preferred_call_contract = preferred_call.get("contract") if isinstance(preferred_call.get("contract"), dict) else {}
    if preferred_call_contract:
        calls.sort(key=lambda item: 0 if (
            item.get("strike") == preferred_call_contract.get("strike")
            and item.get("expiration") == preferred_call_contract.get("expiration")
        ) else 1)

    def option_status(candidates: list[dict[str, Any]]) -> str:
        if not candidates:
            return "WAIT_OPTION_CHAIN"
        if any(item.get("review_status") == "READY_FOR_MANUAL_REVIEW" for item in candidates):
            return "READY_FOR_MANUAL_REVIEW"
        if any(item.get("review_status") == "WAIT_LIQUIDITY" for item in candidates):
            return "WAIT_LIQUIDITY"
        return "WAIT_MARKET_DATA"

    price_status = "READY_FOR_MANUAL_REVIEW" if price is not None else "WAIT_UNDERLYING_PRICE"
    hold_status = "RISK_BLOCKED" if strategy == "SHORT_CALL_UNCOVERED_REVIEW" else "READY_FOR_MANUAL_REVIEW"
    hold_reason = (
        "No se considera prudente mantener una call descubierta sin corregir primero la falta de cobertura."
        if strategy == "SHORT_CALL_UNCOVERED_REVIEW"
        else "Conservar la posición mientras la tesis y los límites de riesgo sigan válidos."
    )
    alternatives = [
        _alternative("HOLD_MONITOR", "Mantener y monitorear", "BASE", hold_status, hold_reason, effects=["Mantiene exposición actual", "No genera prima nueva"]),
    ]
    if strategy == "LONG_STOCK":
        call_status = option_status(calls)
        put_status = option_status(puts)
        partial_contracts = int(preferred_call.get("contracts") or max(1, round(uncovered_share_lots * 0.25))) if uncovered_share_lots else 0
        reduction_status = price_status if short_calls == 0 else "RISK_BLOCKED_COVERAGE"
        reduction_reason = (
            "No reducir acciones sin cerrar o ajustar primero las calls cubiertas; hacerlo rompería la cobertura."
            if short_calls
            else "Disminuir parcialmente exposición y concentración conservando la mayor parte de la tesis."
        )
        alternatives.extend([
            _alternative("COVERED_CALL_PARTIAL", "Covered call parcial", "INCOME", call_status if uncovered_share_lots else "NOT_AVAILABLE_ALREADY_COVERED", "Vender calls sobre parte de los lotes disponibles para generar prima sin limitar toda la posición.", contracts=partial_contracts, candidates=calls, effects=["Genera prima", "Limita upside sólo en lotes cubiertos", "Riesgo de asignación"]),
            _alternative("COVERED_CALL_FULL", "Covered call sobre todos los lotes disponibles", "INCOME", call_status if uncovered_share_lots else "NOT_AVAILABLE_ALREADY_COVERED", "Cubrir con calls todos los lotes que todavía no tienen una call corta.", contracts=uncovered_share_lots, candidates=calls, effects=["Mayor prima", "Limita upside de todos los lotes cubiertos", "Riesgo de salida por asignación"]),
            _alternative("PROTECTIVE_PUT", "Comprar protective put", "DEFENSE", put_status, "Comprar puts para definir protección bajista sin vender las acciones.", contracts=share_lots, candidates=puts, effects=["Define piso de protección", "Tiene costo de prima", "Conserva upside"]),
            _alternative("COLLAR", "Construir collar", "DEFENSE_INCOME", "READY_FOR_MANUAL_REVIEW" if call_status == put_status == "READY_FOR_MANUAL_REVIEW" and uncovered_share_lots else ("WAIT_OPTION_CHAIN" if not calls or not puts else "WAIT_MARKET_DATA"), "Combinar call cubierta y protective put sobre lotes equivalentes.", contracts=uncovered_share_lots, candidates=(calls[:3] + puts[:3]), effects=["Reduce costo de protección", "Limita downside y upside", "Requiere vencimientos y cantidades compatibles"]),
            _alternative("REDUCE_25", "Reducir 25% de las acciones", "REDUCE", reduction_status, reduction_reason, effects=["Libera capital", "Reduce riesgo direccional", "Puede generar impacto fiscal"]),
            _alternative("REDUCE_50", "Reducir 50% de las acciones", "REDUCE", reduction_status, reduction_reason, effects=["Libera más capital", "Reduce volatilidad de cartera", "Puede generar impacto fiscal"]),
            _alternative("EXIT_FULL", "Cerrar la posición completa", "EXIT", reduction_status, "Cerrar acciones requiere cerrar o incluir simultáneamente todas las calls cubiertas." if short_calls else "Revisar salida total sólo si la tesis quedó invalidada o la exposición ya no es deseada.", effects=["Elimina riesgo direccional", "Realiza P/L", "Puede generar impacto fiscal"]),
        ])
    elif strategy == "CASH_SECURED_PUT":
        alternatives.extend([
            _alternative("BUY_BACK_CLOSE", "Comprar para cerrar", "EXIT", price_status if _option_mark(row) is not None else "WAIT_OPTION_MARK", "Cerrar la put elimina obligación de asignación y riesgo abierto."),
            _alternative("ROLL_PUT", "Rolar put en tiempo o strike", "ROLL", option_status(puts), "Comparar puts posteriores sólo si el roll no aumenta riesgo injustificadamente.", contracts=int(abs(qty)), candidates=puts),
            _alternative("ACCEPT_ASSIGNMENT", "Aceptar posible asignación", "ASSIGNMENT", price_status, "Aceptar acciones únicamente si capital, tesis y tamaño siguen siendo adecuados."),
            _alternative("DEFENSIVE_EXIT", "Salida defensiva", "DEFENSE", price_status, "Priorizar reducción de riesgo si soporte, evento o tesis se deterioran."),
        ])
    elif strategy == "COVERED_CALL":
        alternatives.extend([
            _alternative("BUY_BACK_CALL", "Comprar call para cerrar", "EXIT_OPTION", "READY_FOR_MANUAL_REVIEW" if _option_mark(row) is not None else "WAIT_OPTION_MARK", "Cerrar la call conserva las acciones y reabre su upside."),
            _alternative("ROLL_CALL", "Rolar call", "ROLL", option_status(calls), "Comparar otro vencimiento o strike manteniendo siempre cobertura suficiente.", contracts=int(abs(qty)), candidates=calls),
            _alternative("ACCEPT_CALLED_AWAY", "Aceptar salida por asignación", "ASSIGNMENT", price_status, "Permitir que las acciones sean llamadas si el precio de salida cumple el plan."),
            _alternative("CLOSE_COMBINED", "Cerrar call y revisar acciones", "COMBINED", price_status, "Evaluar conjuntamente el cierre de la call y la permanencia o reducción de las acciones."),
        ])
    elif strategy == "SHORT_CALL_UNCOVERED_REVIEW":
        alternatives.extend([
            _alternative("BUY_BACK_UNCOVERED_CALL", "Cerrar call descubierta", "RISK_EXIT", "READY_FOR_MANUAL_REVIEW" if _option_mark(row) is not None else "WAIT_OPTION_MARK", "Eliminar primero el riesgo descubierto antes de considerar cualquier otra alternativa."),
            _alternative("ADD_COVERING_SHARES_REVIEW", "Revisar cobertura con acciones", "RISK_REVIEW", price_status, "Sólo evaluar acciones suficientes si el aumento de exposición está expresamente justificado."),
        ])
    elif strategy in {"LONG_CALL", "LONG_PUT"}:
        same_side = calls if strategy == "LONG_CALL" else puts
        alternatives.extend([
            _alternative("CLOSE_LONG_OPTION", "Cerrar opción larga", "EXIT_OPTION", "READY_FOR_MANUAL_REVIEW" if _option_mark(row) is not None else "WAIT_OPTION_MARK", "Realizar P/L o evitar pérdida adicional de valor temporal."),
            _alternative("ROLL_LONG_OPTION", "Rolar opción larga", "ROLL", option_status(same_side), "Comparar extensión de vencimiento sin aumentar tamaño automáticamente.", contracts=int(abs(qty)), candidates=same_side),
        ])
    else:
        alternatives.extend([
            _alternative("REDUCE_POSITION", "Reducir posición", "REDUCE", price_status, "Reducir exposición mientras se completa la clasificación y la tesis."),
            _alternative("EXIT_POSITION", "Cerrar posición", "EXIT", price_status, "Revisar salida completa si el instrumento o riesgo ya no son deseados."),
        ])

    primary_map = {
        "NO_ACTION_RECOMMENDED": "HOLD_MONITOR",
        "REVIEW_CLOSE_OR_BUY_BACK": "BUY_BACK_CLOSE" if strategy == "CASH_SECURED_PUT" else "BUY_BACK_CALL",
        "REVIEW_ROLL": "ROLL_PUT" if strategy == "CASH_SECURED_PUT" else "ROLL_CALL",
        "REVIEW_ASSIGNMENT": "ACCEPT_ASSIGNMENT" if strategy == "CASH_SECURED_PUT" else "ACCEPT_CALLED_AWAY",
        "REVIEW_DEFENSIVE_EXIT": "DEFENSIVE_EXIT" if strategy == "CASH_SECURED_PUT" else "EXIT_FULL",
    }
    primary_id = primary_map.get(management_action) or "HOLD_MONITOR"
    recommendation_reason = "No existe un disparador determinista que justifique cambiar la posición."
    recommendation_confidence = "MEDIUM" if price is not None else "LOW"
    trend = safe_upper(technical.get("trend"), "UNKNOWN")
    directional_ready = trend not in {"", "UNKNOWN"} and price is not None
    by_id = {item.get("alternative_id"): item for item in alternatives}
    if strategy_comparison.get("available"):
        for alternative_id in ["HOLD_MONITOR", "REDUCE_25", "COVERED_CALL_PARTIAL", "COLLAR"]:
            alternative = by_id.get(alternative_id)
            if alternative:
                alternative["quantitative_comparison_available"] = True
        if by_id.get("COVERED_CALL_PARTIAL"):
            by_id["COVERED_CALL_PARTIAL"]["contract_choices"] = strategy_comparison.get("contract_choices") or []
            by_id["COVERED_CALL_PARTIAL"]["preferred_variant"] = preferred_call or None
        if by_id.get("COLLAR"):
            by_id["COLLAR"]["preferred_variant"] = preferred_collar or None
            if preferred_collar.get("contracts"):
                by_id["COLLAR"]["contracts"] = preferred_collar.get("contracts")

    def choose(alternative_id: str, reason: str, confidence: str = "MEDIUM") -> None:
        nonlocal primary_id, recommendation_reason, recommendation_confidence
        candidate = by_id.get(alternative_id)
        if not candidate or candidate.get("status") != "READY_FOR_MANUAL_REVIEW":
            primary_id = "HOLD_MONITOR"
            recommendation_reason = "No hacer cambios por ahora: faltan datos o liquidez para respaldar una alternativa superior."
            recommendation_confidence = "LOW"
            return
        primary_id = alternative_id
        recommendation_reason = reason
        recommendation_confidence = confidence

    if strategy == "SHORT_CALL_UNCOVERED_REVIEW":
        choose("BUY_BACK_UNCOVERED_CALL", "Prioridad de riesgo: eliminar la exposición descubierta antes de evaluar otras rutas.", "HIGH")
    elif management_action == "REVIEW_CLOSE_OR_BUY_BACK":
        choose("BUY_BACK_CLOSE" if strategy == "CASH_SECURED_PUT" else "BUY_BACK_CALL", "La captura de prima alcanzó el umbral del plan; revisar cierre es la ruta preferida.", "HIGH")
    elif management_action == "REVIEW_ROLL":
        choose("ROLL_PUT" if strategy == "CASH_SECURED_PUT" else "ROLL_CALL", "DTE y delta activaron revisión de roll; priorizar sólo un contrato que no aumente el riesgo.", "HIGH")
    elif management_action == "REFRESH_DATA":
        choose("HOLD_MONITOR", "No hacer cambios hasta completar los datos económicos de la posición y recalcular la recomendación.", "LOW")
    elif strategy == "LONG_STOCK":
        weight = safe_float(row.get("portfolio_weight_pct") or group.get("portfolio_stock_weight_pct"))
        indicators = technical.get("indicators") if isinstance(technical.get("indicators"), dict) else {}
        rsi_14 = safe_float(indicators.get("rsi_14"))
        if short_calls and uncovered_share_lots == 0:
            choose("HOLD_MONITOR", "Las acciones ya respaldan calls cubiertas; mantener la cobertura y gestionar la operación desde la pata de covered call.", "HIGH")
        elif technical.get("support_broken"):
            choose("REDUCE_25", "El soporte fue roto; la reducción ofrece protección bajista real que una covered call sólo compensa parcialmente.", "HIGH")
        elif weight is not None and weight >= 60:
            choose("REDUCE_25", "La concentración es extrema; liberar capital domina a conservar toda la exposición por una prima limitada.", "HIGH")
        elif rsi_14 is not None and rsi_14 < 30:
            choose("HOLD_MONITOR", "El activo está sobrevendido; no conviene limitar un posible rebote con una call nueva sin confirmación adicional.", "MEDIUM")
        elif trend in {"BEARISH", "DOWN", "SELL", "NEUTRAL_TO_BEARISH", "NEUTRAL"} and balanced_leader:
            leader_id = str(balanced_leader.get("alternative_id") or "HOLD_MONITOR")
            leader_contract = balanced_leader.get("contract") if isinstance(balanced_leader.get("contract"), dict) else {}
            details = []
            if balanced_leader.get("contracts"):
                details.append("{} contrato(s)".format(balanced_leader.get("contracts")))
            if balanced_leader.get("coverage_pct"):
                details.append("{}% de cobertura".format(balanced_leader.get("coverage_pct")))
            if leader_contract.get("strike") is not None:
                details.append("strike {}".format(leader_contract.get("strike")))
            leader_put = balanced_leader.get("put_contract") if isinstance(balanced_leader.get("put_contract"), dict) else {}
            if leader_put.get("strike") is not None:
                details.append("put de protección {}".format(leader_put.get("strike")))
            choose(
                leader_id,
                "El soporte sigue intacto. La comparación de cinco escenarios favorece {}{}; reducir queda como defensa si rompe soporte.".format(
                    balanced_leader.get("label") or leader_id,
                    (" (" + ", ".join(details) + ")") if details else "",
                ),
                "MEDIUM",
            )
        elif trend in {"BEARISH", "DOWN", "SELL"}:
            choose("HOLD_MONITOR", "La tendencia es bajista, pero sin soporte roto ni cadena comparable no hay evidencia suficiente para vender acciones o limitar el rebote.", "LOW")
        elif trend in {"NEUTRAL_TO_BEARISH", "NEUTRAL"} and uncovered_share_lots:
            choose("COVERED_CALL_PARTIAL", "El sesgo neutral favorece generar prima sobre una parte de las acciones sin limitar toda la posición.")
        elif directional_ready:
            choose("HOLD_MONITOR", "La tesis técnica no muestra daño suficiente; mantener y monitorear es preferible a operar por operar.")
        else:
            choose("HOLD_MONITOR", "No hacer cambios hasta completar tendencia y niveles críticos del activo.", "LOW")
    elif strategy == "CASH_SECURED_PUT" and management_action == "REVIEW_ASSIGNMENT":
        if trend in {"BEARISH", "DOWN", "SELL", "NEUTRAL_TO_BEARISH"} or technical.get("support_broken"):
            choose("DEFENSIVE_EXIT", "El subyacente está bajo el strike y el contexto técnico es débil; priorizar defensa sobre aceptar asignación.", "HIGH")
        elif trend in {"BULLISH", "UP", "BUY", "NEUTRAL_TO_BULLISH"} and not technical.get("support_broken"):
            choose("ACCEPT_ASSIGNMENT", "El precio está bajo el strike, pero la tesis técnica permanece favorable; aceptar asignación es la ruta preferida si el capital está reservado.")
        else:
            choose("HOLD_MONITOR", "No elegir entre cierre y asignación hasta completar tendencia, soporte y precio correcto del subyacente.", "LOW")
    elif strategy == "COVERED_CALL" and management_action == "REVIEW_ASSIGNMENT":
        if trend in {"BULLISH", "UP", "BUY", "NEUTRAL_TO_BULLISH"} or technical.get("resistance_breakout"):
            choose("ROLL_CALL", "El activo mantiene impulso alcista; revisar roll domina a entregar las acciones si existe contrato líquido.")
        elif directional_ready:
            choose("ACCEPT_CALLED_AWAY", "Sin impulso alcista suficiente, aceptar la salida al strike respeta la estructura de la covered call.")
        else:
            choose("HOLD_MONITOR", "No decidir roll o asignación hasta completar el contexto técnico del subyacente.", "LOW")
    elif strategy in {"CASH_SECURED_PUT", "COVERED_CALL", "LONG_CALL", "LONG_PUT"} and not directional_ready:
        choose("HOLD_MONITOR", "No hacer cambios hasta completar la lectura direccional y los niveles críticos.", "LOW")

    for alternative in alternatives:
        alternative["is_primary_management_path"] = alternative.get("alternative_id") == primary_id
    alternatives.sort(key=lambda item: 0 if item.get("is_primary_management_path") else 1)
    primary = by_id.get(primary_id) or by_id.get("HOLD_MONITOR") or {}
    recommendation = {
        "recommendation_version": "position_primary_recommendation_v1",
        "alternative_id": primary.get("alternative_id"),
        "label": primary.get("label"),
        "status": primary.get("status"),
        "reason": recommendation_reason,
        "confidence": recommendation_confidence,
        "contract": (
            balanced_leader.get("contract")
            if primary.get("alternative_id") == balanced_leader.get("alternative_id") and isinstance(balanced_leader.get("contract"), dict)
            else ((primary.get("contract_candidates") or [None])[0])
        ),
        "put_contract": (
            balanced_leader.get("put_contract")
            if primary.get("alternative_id") == balanced_leader.get("alternative_id") and isinstance(balanced_leader.get("put_contract"), dict)
            else None
        ),
        "contracts": balanced_leader.get("contracts") if primary.get("alternative_id") == balanced_leader.get("alternative_id") else primary.get("contracts"),
        "coverage_pct": balanced_leader.get("coverage_pct") if primary.get("alternative_id") == balanced_leader.get("alternative_id") else None,
        "scenario_variant": balanced_leader if primary.get("alternative_id") == balanced_leader.get("alternative_id") else None,
        "data_complete": directional_ready,
        "can_recommend_no_action": True,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    return {
        "alternatives_version": "position_management_alternatives_v1",
        "strategy": strategy,
        "alternative_count": len(alternatives),
        "reviewable_count": sum(1 for item in alternatives if item.get("status") == "READY_FOR_MANUAL_REVIEW"),
        "option_candidate_count": len(option_rows),
        "underlying_price_available": price is not None,
        "share_lots": share_lots,
        "uncovered_share_lots": uncovered_share_lots,
        "strategy_comparison": strategy_comparison,
        "recommendation": recommendation,
        "alternatives": alternatives,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _management_outcome_template(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "outcome_template_version": "position_management_outcome_v1",
        "position_id": report.get("position_id"),
        "ticker": report.get("ticker"),
        "strategy": report.get("strategy"),
        "recommended_action": report.get("management_action"),
        "recommended_state": report.get("exit_state"),
        "operator_action_options": [
            "NO_ACTION_TAKEN",
            "MANUAL_CLOSE_REVIEWED",
            "MANUAL_ROLL_REVIEWED",
            "ASSIGNMENT_REVIEWED",
            "RISK_REDUCTION_REVIEWED",
            "DATA_REFRESHED",
        ],
        "outcome_fields": [
            "operator_action",
            "operator_reason",
            "followup_required",
            "observed_pnl",
            "premium_capture_pct",
            "days_in_trade",
            "post_action_state",
        ],
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _base_position_report(row: dict[str, Any], strategy: str, technical: dict[str, Any], account_context: dict[str, Any], playbook: dict[str, Any]) -> dict[str, Any]:
    premium_capture = _premium_capture_pct(row)
    option_mark = _option_mark(row)
    entry_credit = _entry_credit(row)
    overlay = strategy_exit_playbook.exit_overlay(
        {
            **row,
            "strategy": strategy,
            "position_open": (safe_float(row.get("position_size"), 0.0) or 0.0) != 0,
            "market_regime": _market_regime({"account_context": account_context}, technical),
        },
        playbook,
    )
    report = {
        "position_management_version": POSITION_MANAGEMENT_VERSION,
        "generated_at": now_iso(),
        "position_id": row.get("position_id"),
        "ticker": row.get("ticker"),
        "strategy": strategy,
        "sec_type": row.get("sec_type"),
        "right": row.get("right"),
        "strike": row.get("strike"),
        "expiration": row.get("expiration"),
        "dte": row.get("dte"),
        "position_size": row.get("position_size"),
        "market_value": row.get("market_value"),
        "portfolio_weight_pct": row.get("portfolio_weight_pct"),
        "unrealized_pl": row.get("unrealized_pl"),
        "entry_credit": entry_credit,
        "option_mark": option_mark,
        "premium_capture_pct": premium_capture,
        "underlying_price": technical.get("price"),
        "technical": technical,
        "thesis": _thesis_from_context(row, strategy, technical),
        "scenario_analysis": _scenario_analysis(row, strategy, technical),
        "exit_overlay": overlay,
        "exit_state": "MONITOR",
        "management_action": "NO_ACTION_RECOMMENDED",
        "manual_review_required": False,
        "confidence": "MEDIUM",
        "reasons": [],
        "warnings": [],
        "blockers": [],
        "not_order_instruction": True,
        "execution_authorized": False,
        "can_operate": False,
    }
    if not technical.get("available"):
        report["warnings"].append("TECHNICAL_CONTEXT_MISSING")
    if not technical.get("gamma_available"):
        report["warnings"].append("GAMMA_CONTEXT_MISSING")
    if safe_upper(row.get("sec_type")) in ["OPT", "OPTION"]:
        if row.get("dte") is None:
            report["warnings"].append("DTE_MISSING")
        if option_mark is None:
            report["warnings"].append("OPTION_MARK_MISSING")
        if entry_credit is None and (safe_float(row.get("position_size"), 0.0) or 0.0) < 0:
            report["warnings"].append("ENTRY_CREDIT_MISSING")
    substantive_warnings = [warning for warning in report["warnings"] if warning != "GAMMA_CONTEXT_MISSING"]
    if substantive_warnings:
        report["confidence"] = "LOW"
    report["management_outcome_template"] = _management_outcome_template(report)
    return report


def evaluate_position(
    row: dict[str, Any],
    *,
    group: dict[str, Any] | None = None,
    technical_store: dict[str, dict[str, Any]] | None = None,
    account_context: dict[str, Any] | None = None,
    playbook: dict[str, Any] | None = None,
    option_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row = normalize_position(row)
    group = group if isinstance(group, dict) else {}
    technical_store = technical_store if isinstance(technical_store, dict) else {}
    account_context = account_context if isinstance(account_context, dict) else {}
    playbook = playbook if isinstance(playbook, dict) else strategy_exit_playbook.load_exit_playbook()
    option_rows = [item for item in (option_rows or []) if isinstance(item, dict)]
    strategy = infer_strategy(row, group)
    technical = _technical_context(row, technical_store)
    report = _base_position_report(row, strategy, technical, account_context, playbook)
    strategy_rules = strategy_exit_playbook.get_exit_strategy(playbook, strategy) or {}
    regime_adjustment = report["exit_overlay"].get("regime_exit_adjustment") or {}
    take_profit = strategy_rules.get("take_profit_review") if isinstance(strategy_rules.get("take_profit_review"), dict) else {}
    roll = strategy_rules.get("roll_review") if isinstance(strategy_rules.get("roll_review"), dict) else {}
    premium_threshold = _threshold(regime_adjustment, "take_profit_capture_pct_min", _threshold(take_profit, "premium_capture_pct_min", 50.0))
    dte = safe_float(row.get("dte"))
    delta = safe_float(row.get("delta") or row.get("option_delta"))
    abs_delta = abs(delta) if delta is not None else None
    qty = safe_float(row.get("position_size"), 0.0) or 0.0
    underlying_price = safe_float(technical.get("price"))
    strike = safe_float(row.get("strike"))
    premium_capture = safe_float(report.get("premium_capture_pct"))
    event_or_damage = bool(technical.get("event_risk") or technical.get("support_broken"))
    trend = safe_upper(technical.get("trend"))
    if trend in ["BEARISH", "DOWN", "SELL"] and strategy == "CASH_SECURED_PUT":
        event_or_damage = True

    def set_review(exit_state: str, action: str, reason: str, blocker: str | None = None) -> None:
        report["exit_state"] = exit_state
        report["management_action"] = action
        report["manual_review_required"] = action not in ["NO_ACTION_RECOMMENDED", "NO_POSITION"]
        report["reasons"].append(reason)
        if blocker:
            report["blockers"].append(blocker)

    if qty == 0:
        set_review("NO_POSITION", "NO_POSITION", "Position is closed or flat.")
    elif strategy == "SHORT_CALL_UNCOVERED_REVIEW":
        set_review("RISK_REVIEW", "REVIEW_RISK", "Short call is not covered by detected long shares.", "UNCOVERED_SHORT_CALL")
    elif dte is not None and dte < 0:
        set_review("EXPIRED_OR_CLOSED", "NO_POSITION", "Position expiration is in the past.")
    elif strategy == "CASH_SECURED_PUT":
        if event_or_damage:
            set_review("RISK_REVIEW", "REVIEW_DEFENSIVE_EXIT", "Event risk, bearish trend, or support break can invalidate the short-put thesis.", "SHORT_PUT_THESIS_RISK")
        elif underlying_price is not None and strike is not None and underlying_price < strike:
            set_review("ASSIGNMENT_REVIEW", "REVIEW_ASSIGNMENT", "Underlying is below the short-put strike; assignment risk needs review.", "SHORT_PUT_UNDERLYING_BELOW_STRIKE")
        elif premium_capture is not None and premium_capture >= premium_threshold:
            set_review("TAKE_PROFIT_REVIEW", "REVIEW_CLOSE_OR_BUY_BACK", f"Premium capture is {premium_capture}% versus {premium_threshold}% review threshold.")
        elif dte is not None and dte <= _threshold(roll, "dte_max", 14.0) and abs_delta is not None and abs_delta >= _threshold(roll, "abs_delta_min", 0.30):
            set_review("ROLL_REVIEW", "REVIEW_ROLL", "Short put is near expiration with elevated delta; review roll only if risk is not increased.")
        else:
            report["reasons"].append("Short put has no deterministic exit trigger; monitor.")
    elif strategy == "COVERED_CALL":
        required_shares = abs(qty) * (safe_float(row.get("multiplier"), DEFAULT_CONTRACT_MULTIPLIER) or DEFAULT_CONTRACT_MULTIPLIER)
        if (safe_float(group.get("shares"), 0.0) or 0.0) < required_shares:
            set_review("RISK_REVIEW", "REVIEW_RISK", "Covered call no longer has enough detected shares.", "COVERED_CALL_SHARE_MISMATCH")
        elif underlying_price is not None and strike is not None and underlying_price > strike:
            set_review("ASSIGNMENT_REVIEW", "REVIEW_ASSIGNMENT", "Underlying is above the short-call strike; assignment or roll choice needs review.", "COVERED_CALL_UNDERLYING_ABOVE_STRIKE")
        elif technical.get("resistance_breakout"):
            set_review("RISK_REVIEW", "REVIEW_RISK", "Breakout can move against the covered call.", "COVERED_CALL_BREAKOUT_RISK")
        elif premium_capture is not None and premium_capture >= premium_threshold:
            set_review("TAKE_PROFIT_REVIEW", "REVIEW_CLOSE_OR_BUY_BACK", f"Premium capture is {premium_capture}% versus {premium_threshold}% review threshold.")
        elif dte is not None and dte <= _threshold(roll, "dte_max", 14.0) and abs_delta is not None and abs_delta >= _threshold(roll, "abs_delta_min", 0.35):
            set_review("ROLL_REVIEW", "REVIEW_ROLL", "Covered call is near expiration with elevated delta; review covered roll only.")
        else:
            report["reasons"].append("Covered call has no deterministic exit trigger; monitor.")
    elif strategy == "LONG_STOCK":
        weight = safe_float(row.get("portfolio_weight_pct"))
        if event_or_damage:
            set_review("EXIT_REVIEW", "REVIEW_DEFENSIVE_EXIT", "Long-stock thesis may be damaged by event risk or a broken support level.", "LONG_STOCK_THESIS_RISK")
        elif trend in ["BEARISH", "DOWN", "SELL"]:
            set_review("RISK_REVIEW", "REVIEW_RISK", "Bearish trend with intact support requires comparing hold, income overlays, protection, and reduction.", "LONG_STOCK_BEARISH_REVIEW")
        elif weight is not None and weight >= 35:
            set_review("RISK_REVIEW", "REVIEW_RISK", "Long-stock position is a high portfolio concentration.", "LONG_STOCK_CONCENTRATION_HIGH")
        elif qty >= DEFAULT_CONTRACT_MULTIPLIER:
            report["reasons"].append("Long stock is eligible for covered-call review, but no exit trigger is active.")
        else:
            report["reasons"].append("Long stock has no deterministic action trigger; monitor.")
    else:
        report["warnings"].append("POSITION_STRATEGY_NOT_REGISTERED")
        report["confidence"] = "LOW"
        report["reasons"].append("Strategy is not registered in the active position playbook; monitor manually.")

    refresh_warnings = {"TECHNICAL_CONTEXT_MISSING", "DTE_MISSING", "OPTION_MARK_MISSING", "ENTRY_CREDIT_MISSING"}
    if any(warning in refresh_warnings for warning in report["warnings"]) and report["management_action"] == "NO_ACTION_RECOMMENDED":
        report["management_action"] = "REFRESH_DATA"
        report["manual_review_required"] = True
    report["management_alternatives"] = _management_alternatives(
        row,
        strategy,
        technical,
        group,
        option_rows,
        report["management_action"],
    )
    report["urgency_rank"] = ACTION_PRIORITY.get(report["management_action"], 0)
    report["management_outcome_template"] = _management_outcome_template(report)
    return report


def _portfolio_risk_summary(reports: list[dict[str, Any]], account_context: dict[str, Any]) -> dict[str, Any]:
    net_liq = safe_float(account_context.get("net_liquidation"))
    by_ticker: dict[str, dict[str, Any]] = {}
    by_strategy: dict[str, int] = {}
    gross_market_value = 0.0
    short_put_notional = 0.0
    uncovered_short_calls = 0
    concentration_warnings: list[str] = []
    for report in reports:
        ticker = safe_upper(report.get("ticker"), "UNKNOWN")
        strategy = safe_upper(report.get("strategy"), "UNKNOWN")
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1
        item = by_ticker.setdefault(ticker, {"ticker": ticker, "market_value": 0.0, "position_count": 0, "review_count": 0})
        market_value = abs(safe_float(report.get("market_value"), 0.0) or 0.0)
        item["market_value"] += market_value
        item["position_count"] += 1
        if report.get("manual_review_required"):
            item["review_count"] += 1
        gross_market_value += market_value
        if strategy == "CASH_SECURED_PUT":
            strike = safe_float(report.get("strike"))
            qty = abs(safe_float(report.get("position_size"), 0.0) or 0.0)
            multiplier = DEFAULT_CONTRACT_MULTIPLIER
            if strike is not None:
                short_put_notional += strike * qty * multiplier
        if strategy == "SHORT_CALL_UNCOVERED_REVIEW":
            uncovered_short_calls += 1
    for item in by_ticker.values():
        if net_liq and net_liq > 0:
            item["net_liq_weight_pct"] = round((item["market_value"] / net_liq) * 100.0, 2)
            if item["net_liq_weight_pct"] >= 35:
                concentration_warnings.append(f"{item['ticker']}_CONCENTRATION_HIGH")
        else:
            item["net_liq_weight_pct"] = None
    risk_flags = []
    if uncovered_short_calls:
        risk_flags.append("UNCOVERED_SHORT_CALLS_PRESENT")
    if concentration_warnings:
        risk_flags.extend(concentration_warnings)
    if short_put_notional and net_liq and short_put_notional / net_liq >= 0.5:
        risk_flags.append("SHORT_PUT_NOTIONAL_HIGH_VS_NET_LIQ")
    return {
        "portfolio_risk_version": "active_position_portfolio_risk_v1",
        "gross_market_value": round(gross_market_value, 2),
        "short_put_notional": round(short_put_notional, 2),
        "short_put_notional_pct_net_liq": round((short_put_notional / net_liq) * 100.0, 2) if net_liq and net_liq > 0 else None,
        "uncovered_short_call_count": uncovered_short_calls,
        "by_strategy": by_strategy,
        "by_ticker": sorted(by_ticker.values(), key=lambda item: item.get("market_value") or 0, reverse=True),
        "risk_flags": risk_flags,
        "status": "RISK_REVIEW" if risk_flags else "OK",
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def _battle_plan(reports: list[dict[str, Any]], portfolio_risk: dict[str, Any], freshness: dict[str, Any]) -> dict[str, Any]:
    steps = []
    if freshness.get("ok") is not True:
        steps.append({
            "priority": 1,
            "type": "DATA",
            "label": "Refresh broker/technical context before managing positions.",
            "reason": ", ".join(freshness.get("blockers") or freshness.get("warnings") or ["context not fresh"]),
        })
    if portfolio_risk.get("status") == "RISK_REVIEW":
        steps.append({
            "priority": 2,
            "type": "PORTFOLIO_RISK",
            "label": "Review aggregate portfolio risk first.",
            "reason": ", ".join(portfolio_risk.get("risk_flags") or []),
        })
    for report in reports[:10]:
        action = report.get("management_action")
        if action in ["NO_ACTION_RECOMMENDED", "NO_POSITION"]:
            continue
        steps.append({
            "priority": ACTION_PRIORITY.get(action, 0),
            "type": "POSITION",
            "ticker": report.get("ticker"),
            "strategy": report.get("strategy"),
            "label": f"{report.get('ticker')}: {action}",
            "reason": "; ".join(str(x) for x in (report.get("reasons") or report.get("warnings") or report.get("blockers") or [])[:3]),
            "exit_state": report.get("exit_state"),
            "management_action": action,
        })
    if not steps and reports:
        steps.append({
            "priority": 0,
            "type": "MONITOR",
            "label": "No position requires deterministic action now.",
            "reason": "All active positions are in monitor/no-action state.",
        })
    if not reports:
        steps.append({
            "priority": 0,
            "type": "NO_POSITIONS",
            "label": "No active positions detected.",
            "reason": "Refresh IBKR if this is unexpected.",
        })
    steps = sorted(steps, key=lambda item: item.get("priority", 0), reverse=True)
    return {
        "battle_plan_version": "active_position_battle_plan_v1",
        "top_step": steps[0] if steps else None,
        "steps": steps,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def build_active_position_management(snapshot: dict[str, Any], playbook: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    playbook = playbook if isinstance(playbook, dict) else strategy_exit_playbook.load_exit_playbook()
    contexts = _position_contexts(snapshot)
    raw_positions = []
    for row in _raw_positions(snapshot):
        normalized_row = normalize_position(row)
        context = position_context_store.find_context(normalized_row, contexts)
        raw_positions.append(position_context_store.merge_context_into_position(normalized_row, context))
    positions = [normalize_position(row) for row in raw_positions]
    positions = [row for row in positions if safe_float(row.get("position_size"), 0.0) not in [None, 0.0]]
    positions = _dedupe_position_copies(positions)
    technical_store = _technical_by_ticker(snapshot)
    option_candidates = _option_candidates_by_ticker(snapshot)
    account_context = snapshot.get("account_context") if isinstance(snapshot.get("account_context"), dict) else broker_check.extract_account_context(snapshot)
    policy = snapshot.get("position_management_policy") if isinstance(snapshot.get("position_management_policy"), dict) else {}
    max_age = int(safe_float(policy.get("max_context_age_minutes"), DEFAULT_MAX_CONTEXT_AGE_MINUTES) or DEFAULT_MAX_CONTEXT_AGE_MINUTES)
    freshness = _context_freshness(snapshot, account_context if isinstance(account_context, dict) else {}, max_age)
    groups = _position_groups(positions)
    total_stock_value = sum(safe_float(group.get("stock_value"), 0.0) or 0.0 for group in groups.values())
    portfolio_value = safe_float(account_context.get("net_liquidation")) if isinstance(account_context, dict) else None
    concentration_base = portfolio_value if portfolio_value is not None and portfolio_value > 0 else total_stock_value
    for group in groups.values():
        stock_value = safe_float(group.get("stock_value"), 0.0) or 0.0
        group["portfolio_stock_weight_pct"] = round((stock_value / concentration_base) * 100, 2) if concentration_base > 0 and stock_value > 0 else None
    reports = [
        evaluate_position(
            row,
            group=groups.get(safe_upper(row.get("ticker")), {}),
            technical_store=technical_store,
            account_context=account_context,
            playbook=playbook,
            option_rows=option_candidates.get(safe_upper(row.get("ticker")), []),
        )
        for row in positions
    ]
    if freshness.get("ok") is not True:
        for report in reports:
            report["warnings"].extend(freshness.get("blockers") or freshness.get("warnings") or [])
            report["confidence"] = "LOW"
            if report["management_action"] == "NO_ACTION_RECOMMENDED":
                report["management_action"] = "REFRESH_DATA"
                report["manual_review_required"] = True
                report["urgency_rank"] = ACTION_PRIORITY["REFRESH_DATA"]
    reports = sorted(reports, key=lambda item: item.get("urgency_rank", 0), reverse=True)
    action_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    for report in reports:
        action_counts[report.get("management_action") or "UNKNOWN"] = action_counts.get(report.get("management_action") or "UNKNOWN", 0) + 1
        state_counts[report.get("exit_state") or "UNKNOWN"] = state_counts.get(report.get("exit_state") or "UNKNOWN", 0) + 1
    actionable = [item for item in reports if item.get("manual_review_required") is True]
    risk = [item for item in reports if item.get("management_action") in ["REVIEW_RISK", "REVIEW_DEFENSIVE_EXIT", "REVIEW_ASSIGNMENT"]]
    status = "NO_POSITIONS"
    if reports:
        status = "RISK_REVIEW" if risk else ("REVIEW" if actionable else "MONITOR")
    portfolio_risk = _portfolio_risk_summary(reports, account_context if isinstance(account_context, dict) else {})
    battle_plan = _battle_plan(reports, portfolio_risk, freshness)
    return {
        "position_management_version": POSITION_MANAGEMENT_VERSION,
        "generated_at": now_iso(),
        "status": status,
        "freshness": freshness,
        "positions_found": len(positions),
        "positions_requiring_review": len(actionable),
        "risk_review_count": len(risk),
        "summary": {
            "by_action": action_counts,
            "by_exit_state": state_counts,
            "top_action": reports[0].get("management_action") if reports else None,
            "top_ticker": reports[0].get("ticker") if reports else None,
            "battle_plan_top_step": (battle_plan.get("top_step") or {}).get("label") if isinstance(battle_plan.get("top_step"), dict) else None,
        },
        "portfolio_risk": portfolio_risk,
        "battle_plan": battle_plan,
        "positions": reports,
        "position_context_summary": {
            "context_count": len(contexts),
            "contexts_applied": sum(1 for row in raw_positions if row.get("position_context_updated_at")),
            "not_order_instruction": True,
            "execution_authorized": False,
        },
        "option_alternatives_summary": {
            "tickers_with_preserved_chains": sorted(option_candidates.keys()),
            "positions_with_option_candidates": sum(
                1 for report in reports
                if ((report.get("management_alternatives") or {}).get("option_candidate_count") or 0) > 0
            ),
            "total_alternatives": sum(
                (report.get("management_alternatives") or {}).get("alternative_count") or 0
                for report in reports
            ),
            "not_order_instruction": True,
            "execution_authorized": False,
        },
        "playbook": strategy_exit_playbook.exit_playbook_summary(playbook),
        "manual_review_required": bool(actionable),
        "not_order_instruction": True,
        "execution_authorized": False,
        "can_operate": False,
    }
