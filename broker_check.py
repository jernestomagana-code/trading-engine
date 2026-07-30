"""Automatic broker-context checks for Stock Ultimus decisions.

This module is intentionally pure: it does not connect to IBKR, it does not
read credentials, and it never creates or submits orders. It only evaluates the
broker/account context already present in a snapshot so downstream V31 decisions
can avoid treating a setup as review-ready when the real account context does
not support it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


BROKER_CHECK_VERSION = "broker_check_v1"
DEFAULT_CONTRACT_MULTIPLIER = 100
DEFAULT_BROKER_CHECK_MAX_AGE_MINUTES = 15
DEFAULT_MAX_TRADE_CAPACITY_PCT = 25.0
DEFAULT_MAX_UNDERLYING_CONCENTRATION_PCT = 50.0
DEFAULT_WARN_UNDERLYING_CONCENTRATION_PCT = 35.0
DEFAULT_MAX_SHORT_PUTS_PER_TICKER = 1


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


def broker_check_freshness(check: dict[str, Any], *, max_age_minutes: int = DEFAULT_BROKER_CHECK_MAX_AGE_MINUTES) -> dict[str, Any]:
    check = check if isinstance(check, dict) else {}
    generated_at = check.get("generated_at")
    age = age_minutes(generated_at)
    status = "UNKNOWN"
    blockers: list[str] = []
    warnings: list[str] = []
    if age is None:
        warnings.append("BROKER_CHECK_TIMESTAMP_MISSING")
    elif age > max_age_minutes:
        status = "STALE"
        blockers.append("BROKER_CHECK_STALE")
    else:
        status = "FRESH"
    if status == "UNKNOWN":
        status = "WARNING"
    return {
        "freshness_version": "broker_check_freshness_v1",
        "status": status,
        "ok": status == "FRESH",
        "generated_at": generated_at,
        "age_minutes": age,
        "max_age_minutes": max_age_minutes,
        "blockers": blockers,
        "warnings": warnings,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def strategy_family(strategy: Any) -> str:
    strategy = safe_upper(strategy, "UNKNOWN")
    if "COVERED" in strategy and "CALL" in strategy:
        return "COVERED_CALL"
    if "PUT" in strategy:
        return "NAKED_PUT"
    if "CALL" in strategy:
        return "CALL"
    return strategy


def _walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_dicts(item)


def _is_position_like(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    if safe_upper(item.get("asset_class")) == "POSITION":
        return True
    if safe_upper(item.get("engine_layer")) == "IBKR_PORTFOLIO_COMMANDER":
        return True
    sec_type = safe_upper(item.get("sec_type") or item.get("security_type"))
    if sec_type in ["STK", "STOCK", "EQUITY", "OPT", "OPTION", "FUT", "CONTFUT"]:
        return any(key in item for key in ["position_size", "position", "qty", "market_value", "portfolio_weight_pct", "avg_cost"]) and bool(item.get("ticker") or item.get("symbol"))
    return False


def extract_positions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract sanitized position rows from known runtime/master shapes."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    found: list[dict[str, Any]] = []

    for key in ["positions", "portfolio_positions", "position_rows"]:
        value = snapshot.get(key)
        if isinstance(value, list):
            found.extend(item for item in value if isinstance(item, dict))

    for item in _walk_dicts(snapshot):
        if _is_position_like(item):
            found.append(dict(item))

    cleaned: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str, str, str]] = set()
    for row in found:
        ticker = safe_upper(row.get("ticker") or row.get("symbol"))
        if not ticker:
            continue
        sec_type = safe_upper(row.get("sec_type") or row.get("security_type") or row.get("asset_class"), "UNKNOWN")
        position_size = safe_float(
            row.get("position_size", row.get("position", row.get("quantity", row.get("qty")))),
            0.0,
        )
        local_symbol = str(row.get("local_symbol") or "")
        right = safe_upper(row.get("right"))
        strike = str(safe_float(row.get("strike")) or "")
        expiration = str(row.get("expiration") or row.get("lastTradeDateOrContractMonth") or "")
        account_alias = str(row.get("account_alias") or row.get("account_scope") or "")
        key = (ticker, sec_type, right, strike, expiration, str(position_size), local_symbol, account_alias)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({
            "account_alias": row.get("account_alias"),
            "account_scope": row.get("account_scope"),
            "ticker": ticker,
            "sec_type": sec_type,
            "right": row.get("right"),
            "strike": row.get("strike"),
            "expiration": row.get("expiration"),
            "position_size": position_size,
            "avg_cost": safe_float(row.get("avg_cost")),
            "market_price": safe_float(row.get("market_price") or row.get("price")),
            "market_value": safe_float(row.get("market_value")),
            "portfolio_weight_pct": safe_float(row.get("portfolio_weight_pct")),
            "position_class": row.get("position_class"),
        })
    return cleaned


def extract_account_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Extract non-secret account risk capacity values from a snapshot."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    candidates: list[dict[str, Any]] = []
    for key in ["account", "account_context", "balances", "portfolio", "financials"]:
        value = snapshot.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(snapshot)

    def first_number(*names: str) -> float | None:
        for item in candidates:
            for name in names:
                value = safe_float(item.get(name))
                if value is not None:
                    return value
        return None

    context = {
        "net_liquidation": first_number("net_liquidation", "net_liquidation_value", "nlv", "account_nlv"),
        "buying_power": first_number("buying_power", "option_buying_power", "cash_buying_power"),
        "available_funds": first_number("available_funds", "available_cash", "cash", "cash_balance"),
        "excess_liquidity": first_number("excess_liquidity", "excess_liquidity_value"),
        "source": "snapshot_account_context",
    }
    context["available_capacity"] = first_number(
        "available_funds",
        "buying_power",
        "excess_liquidity",
        "available_cash",
        "cash",
    )
    context["available"] = any(value is not None for key, value in context.items() if key != "source")
    return context


def _position_summary(ticker: str, positions: list[dict[str, Any]]) -> dict[str, Any]:
    ticker = safe_upper(ticker)
    underlying_shares = 0.0
    option_positions = []
    short_put_count = 0
    short_call_count = 0
    underlying_market_value = 0.0
    position_rows = []
    for row in positions:
        if safe_upper(row.get("ticker")) != ticker:
            continue
        position_rows.append(row)
        qty = safe_float(row.get("position_size"), 0.0) or 0.0
        if safe_upper(row.get("sec_type")) in ["STK", "STOCK", "EQUITY", "POSITION"]:
            underlying_shares += qty
            underlying_market_value += abs(safe_float(row.get("market_value"), 0.0) or 0.0)
        elif safe_upper(row.get("sec_type")) in ["OPT", "OPTION"]:
            right = safe_upper(row.get("right"))
            if right == "P" and qty < 0:
                short_put_count += abs(qty)
            if right == "C" and qty < 0:
                short_call_count += abs(qty)
            option_positions.append({
                "right": row.get("right"),
                "strike": row.get("strike"),
                "expiration": row.get("expiration"),
                "position_size": qty,
            })
    return {
        "underlying_shares": underlying_shares,
        "underlying_market_value": underlying_market_value or None,
        "option_position_count": len(option_positions),
        "short_put_count": short_put_count,
        "short_call_count": short_call_count,
        "option_positions": option_positions[:20],
        "positions_found": len(position_rows),
    }


def build_broker_check(
    row: dict[str, Any],
    *,
    positions: list[dict[str, Any]] | None = None,
    account_context: dict[str, Any] | None = None,
    generated_at: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one broker-context check for a candidate row."""
    row = row if isinstance(row, dict) else {}
    positions = positions if isinstance(positions, list) else []
    account_context = account_context if isinstance(account_context, dict) else {}
    policy = policy if isinstance(policy, dict) else {}

    ticker = safe_upper(row.get("ticker") or row.get("symbol"), "UNKNOWN")
    strategy = safe_upper(row.get("strategy") or row.get("strategy_hint"), "UNKNOWN")
    family = strategy_family(strategy)
    blockers: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []

    strike = safe_float(row.get("strike"))
    contracts = safe_float(row.get("contracts") or row.get("quantity") or row.get("contract_count"), 1.0) or 1.0
    multiplier = safe_float(row.get("multiplier") or row.get("contract_multiplier"), DEFAULT_CONTRACT_MULTIPLIER) or DEFAULT_CONTRACT_MULTIPLIER
    pos = _position_summary(ticker, positions)
    capacity = safe_float(account_context.get("available_capacity"))
    net_liq = safe_float(account_context.get("net_liquidation"))
    max_trade_capacity_pct = safe_float(policy.get("max_trade_capacity_pct"), DEFAULT_MAX_TRADE_CAPACITY_PCT) or DEFAULT_MAX_TRADE_CAPACITY_PCT
    max_concentration_pct = safe_float(policy.get("max_underlying_concentration_pct"), DEFAULT_MAX_UNDERLYING_CONCENTRATION_PCT) or DEFAULT_MAX_UNDERLYING_CONCENTRATION_PCT
    warn_concentration_pct = safe_float(policy.get("warn_underlying_concentration_pct"), DEFAULT_WARN_UNDERLYING_CONCENTRATION_PCT) or DEFAULT_WARN_UNDERLYING_CONCENTRATION_PCT
    max_short_puts_per_ticker = safe_float(policy.get("max_short_puts_per_ticker"), DEFAULT_MAX_SHORT_PUTS_PER_TICKER)

    if not positions:
        warnings.append("BROKER_POSITIONS_MISSING")
    if not account_context.get("available"):
        warnings.append("BROKER_ACCOUNT_CONTEXT_MISSING")

    if family == "COVERED_CALL":
        required_shares = contracts * multiplier
        shares_ok = pos["underlying_shares"] >= required_shares
        checks.append({
            "name": "COVERED_CALL_SHARES",
            "status": "PASS" if shares_ok else "BLOCKED",
            "value": pos["underlying_shares"],
            "required": required_shares,
            "note": "Covered Call requires enough long underlying shares.",
        })
        if not shares_ok:
            blockers.append("BROKER_COVERED_CALL_SHARES_INSUFFICIENT")

    elif family == "NAKED_PUT":
        estimated_cash_secured_requirement = strike * multiplier * contracts if strike is not None else None
        capacity_ok = (
            capacity is not None
            and estimated_cash_secured_requirement is not None
            and capacity >= estimated_cash_secured_requirement
        )
        checks.append({
            "name": "PUT_CAPACITY_CHECK",
            "status": "PASS" if capacity_ok else ("UNKNOWN" if capacity is None or estimated_cash_secured_requirement is None else "BLOCKED"),
            "value": capacity,
            "required": estimated_cash_secured_requirement,
            "shortfall": (
                round(estimated_cash_secured_requirement - capacity, 2)
                if capacity is not None
                and estimated_cash_secured_requirement is not None
                and estimated_cash_secured_requirement > capacity
                else 0
            ),
            "capacity_pct_required": (
                round((estimated_cash_secured_requirement / capacity) * 100.0, 2)
                if capacity is not None
                and capacity > 0
                and estimated_cash_secured_requirement is not None
                else None
            ),
            "note": "Approximate cash-secured requirement. Broker margin can differ; validate manually in TWS.",
        })
        if capacity is None or estimated_cash_secured_requirement is None:
            warnings.append("BROKER_PUT_CAPACITY_UNKNOWN")
        elif not capacity_ok:
            blockers.append("BROKER_PUT_CAPACITY_INSUFFICIENT")
        else:
            trade_capacity_pct = round((estimated_cash_secured_requirement / capacity) * 100.0, 2) if capacity > 0 else None
            checks.append({
                "name": "TRADE_CAPACITY_PCT",
                "status": "PASS" if trade_capacity_pct is not None and trade_capacity_pct <= max_trade_capacity_pct else "BLOCKED",
                "value": trade_capacity_pct,
                "limit": max_trade_capacity_pct,
                "note": "Estimated cash-secured requirement as a percentage of available capacity.",
            })
            if trade_capacity_pct is not None and trade_capacity_pct > max_trade_capacity_pct:
                blockers.append("BROKER_TRADE_SIZE_TOO_LARGE")
        if max_short_puts_per_ticker is not None:
            checks.append({
                "name": "OPEN_SHORT_PUTS_PER_TICKER",
                "status": "PASS" if pos.get("short_put_count", 0) < max_short_puts_per_ticker else "BLOCKED",
                "value": pos.get("short_put_count", 0),
                "limit": max_short_puts_per_ticker,
                "note": "Avoid stacking additional naked puts when short puts already exist for the ticker.",
            })
            if pos.get("short_put_count", 0) >= max_short_puts_per_ticker:
                blockers.append("BROKER_EXISTING_SHORT_PUT_EXPOSURE")

    if net_liq is not None and pos.get("underlying_market_value") is not None and net_liq > 0:
        concentration_pct = round((pos["underlying_market_value"] / net_liq) * 100.0, 2)
        checks.append({
            "name": "UNDERLYING_CONCENTRATION",
            "status": "BLOCKED" if concentration_pct > max_concentration_pct else ("WARNING" if concentration_pct > warn_concentration_pct else "PASS"),
            "value": concentration_pct,
            "warning_limit": warn_concentration_pct,
            "block_limit": max_concentration_pct,
            "note": "Underlying concentration based on current detected stock market value vs net liquidation.",
        })
        if concentration_pct > max_concentration_pct:
            blockers.append("BROKER_UNDERLYING_CONCENTRATION_TOO_HIGH")
        elif concentration_pct > warn_concentration_pct:
            warnings.append("BROKER_UNDERLYING_CONCENTRATION_HIGH")

    status = "BLOCKED" if blockers else ("WARNING" if warnings else "OK")
    return {
        "broker_check_version": BROKER_CHECK_VERSION,
        "generated_at": generated_at or now_iso(),
        "ticker": ticker,
        "strategy": strategy,
        "status": status,
        "ok_for_manual_review": status in ["OK", "WARNING"],
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "policy": {
            "max_trade_capacity_pct": max_trade_capacity_pct,
            "warn_underlying_concentration_pct": warn_concentration_pct,
            "max_underlying_concentration_pct": max_concentration_pct,
            "max_short_puts_per_ticker": max_short_puts_per_ticker,
        },
        "position": pos,
        "account_context": {
            "net_liquidation_present": account_context.get("net_liquidation") is not None,
            "buying_power_present": account_context.get("buying_power") is not None,
            "available_funds_present": account_context.get("available_funds") is not None,
            "available_capacity_present": account_context.get("available_capacity") is not None,
        },
        "manual_broker_ticket_still_required": True,
        "can_operate": False,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_broker_checks(snapshot: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    rows = rows if isinstance(rows, list) else snapshot.get("options_rows")
    if not isinstance(rows, list):
        rows = []
    positions = extract_positions(snapshot)
    account_context = extract_account_context(snapshot)
    policy = snapshot.get("broker_check_policy") if isinstance(snapshot.get("broker_check_policy"), dict) else {}
    generated_at = now_iso()
    checks: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = safe_upper(row.get("ticker") or row.get("symbol"))
        strategy = safe_upper(row.get("strategy") or row.get("strategy_hint"), "UNKNOWN")
        if not ticker:
            continue
        key = (ticker, strategy)
        if key in seen:
            continue
        seen.add(key)
        checks.append(build_broker_check(row, positions=positions, account_context=account_context, generated_at=generated_at, policy=policy))
    return checks


def broker_check_for_ticker(snapshot: dict[str, Any], ticker: str, strategy: str | None = None) -> dict[str, Any] | None:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    ticker = safe_upper(ticker)
    strategy = safe_upper(strategy, "")
    checks = snapshot.get("broker_checks") or snapshot.get("broker_check_by_ticker") or []
    if isinstance(checks, dict):
        candidate = checks.get(ticker) or checks.get(ticker.upper())
        return candidate if isinstance(candidate, dict) else None
    if not isinstance(checks, list):
        return None
    fallback = None
    for check in checks:
        if not isinstance(check, dict):
            continue
        if safe_upper(check.get("ticker")) != ticker:
            continue
        if strategy and safe_upper(check.get("strategy")) == strategy:
            return check
        fallback = fallback or check
    return fallback


def merge_broker_checks(snapshot: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a copy of snapshot enriched with broker_checks."""
    snapshot = dict(snapshot or {})
    rows = rows if isinstance(rows, list) else snapshot.get("options_rows")
    checks = build_broker_checks(snapshot, rows if isinstance(rows, list) else [])
    snapshot["broker_checks"] = checks
    snapshot["broker_check_summary"] = {
        "broker_check_version": BROKER_CHECK_VERSION,
        "generated_at": now_iso(),
        "total": len(checks),
        "ok": sum(1 for item in checks if item.get("status") == "OK"),
        "warning": sum(1 for item in checks if item.get("status") == "WARNING"),
        "blocked": sum(1 for item in checks if item.get("status") == "BLOCKED"),
        "unknown": sum(1 for item in checks if item.get("status") == "UNKNOWN"),
        "manual_broker_ticket_still_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    return snapshot
