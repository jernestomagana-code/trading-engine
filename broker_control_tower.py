"""Sanitized multi-account broker registry and consolidation engine.

The module is deliberately read-only.  It never receives order instructions and
never persists real broker account identifiers.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTROL_TOWER_VERSION = "stock_ultimus_control_tower_v1"
ACCOUNT_SNAPSHOT_VERSION = "broker_account_snapshot_v1"
CAPACITY_FIELDS = (
    "net_liquidation",
    "buying_power",
    "available_funds",
    "excess_liquidity",
    "total_cash_value",
    "initial_margin_required",
    "maintenance_margin_required",
    "gross_position_value",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_alias(value: Any) -> str:
    alias = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in "-_")
    if not alias:
        raise ValueError("account alias is required")
    return alias


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return round(number, 4)


def parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def snapshot_age_minutes(snapshot: dict[str, Any], reference: datetime | None = None) -> float | None:
    generated = parse_datetime(snapshot.get("generated_at"))
    if not generated:
        return None
    reference = reference or datetime.now(timezone.utc)
    return round(max(0.0, (reference - generated).total_seconds() / 60), 2)


def build_registry(
    profiles: dict[str, Any],
    active_alias: str = "",
    keychain_ready: dict[str, bool] | None = None,
) -> dict[str, Any]:
    keychain_ready = keychain_ready or {}
    rows = []
    seen_scopes: set[str] = set()
    warnings: list[str] = []
    for raw_alias, raw_profile in sorted((profiles or {}).items()):
        if not isinstance(raw_profile, dict):
            continue
        alias = normalize_alias(raw_profile.get("alias") or raw_alias)
        scope = normalize_alias(raw_profile.get("account_scope") or alias)
        if scope in seen_scopes:
            warnings.append(f"DUPLICATE_ACCOUNT_SCOPE:{scope}")
        seen_scopes.add(scope)
        rows.append({
            "broker": str(raw_profile.get("broker") or "IBKR").upper(),
            "account_alias": alias,
            "account_scope": scope,
            "active": alias == normalize_alias(active_alias) if active_alias else False,
            "configured": True,
            "keychain_ready": bool(keychain_ready.get(alias)),
            "real_account_id_excluded": True,
        })
    return {
        "registry_version": "broker_account_registry_v1",
        "generated_at": now_iso(),
        "accounts": rows,
        "account_count": len(rows),
        "active_account_alias": normalize_alias(active_alias) if active_alias else "",
        "warnings": warnings,
        "ambiguous_default_account": any(row["account_alias"] == "default" for row in rows),
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def account_snapshot(
    *,
    broker: str,
    alias: str,
    scope: str,
    capacity: dict[str, Any] | None = None,
    positions: list[dict[str, Any]] | None = None,
    status: str = "READY",
    error: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    capacity = capacity if isinstance(capacity, dict) else {}
    clean_capacity = {field: safe_float(capacity.get(field)) for field in CAPACITY_FIELDS}
    clean_capacity["available_capacity"] = safe_float(
        capacity.get("available_capacity")
        if capacity.get("available_capacity") is not None
        else capacity.get("available_funds")
    )
    clean_positions = []
    for item in positions or []:
        if not isinstance(item, dict):
            continue
        clean_positions.append({
            "ticker": str(item.get("ticker") or item.get("symbol") or "UNKNOWN").upper().strip(),
            "security_type": str(item.get("security_type") or item.get("sec_type") or "UNKNOWN").upper(),
            "currency": str(item.get("currency") or "").upper(),
            "quantity": safe_float(item.get("quantity")),
            "average_cost": safe_float(item.get("average_cost") or item.get("avg_cost")),
            "strike": safe_float(item.get("strike")),
            "expiration": str(item.get("expiration") or ""),
            "right": str(item.get("right") or "").upper(),
            "multiplier": str(item.get("multiplier") or ""),
            "market_price": safe_float(item.get("market_price")),
            "market_value": safe_float(item.get("market_value")),
            "unrealized_pl": safe_float(item.get("unrealized_pl") or item.get("unrealized_pnl")),
        })
    ready = status == "READY" and any(value is not None for value in clean_capacity.values())
    effective_status = "READY" if ready else ("CAPACITY_UNAVAILABLE" if status == "READY" else status)
    return {
        "account_snapshot_version": ACCOUNT_SNAPSHOT_VERSION,
        "generated_at": generated_at or now_iso(),
        "broker": str(broker or "UNKNOWN").upper(),
        "account_alias": normalize_alias(alias),
        "account_scope": normalize_alias(scope or alias),
        "status": effective_status,
        "ok": bool(ready),
        "capacity": clean_capacity,
        "currency": str(capacity.get("currency") or "USD").upper(),
        "positions": clean_positions,
        "position_count": len(clean_positions),
        "error": str(error or "")[:300],
        "sensitive_identifiers_excluded": True,
        "real_account_id_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _position_key(position: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(position.get("ticker") or "UNKNOWN"),
        str(position.get("security_type") or "UNKNOWN"),
        str(position.get("expiration") or ""),
        str(position.get("strike") or ""),
        str(position.get("right") or ""),
    )


def consolidate(
    registry: dict[str, Any],
    snapshots: dict[str, dict[str, Any]],
    *,
    max_age_minutes: float = 15,
    reference: datetime | None = None,
) -> dict[str, Any]:
    reference = reference or datetime.now(timezone.utc)
    accounts = []
    totals = {field: 0.0 for field in CAPACITY_FIELDS}
    totals["available_capacity"] = 0.0
    aggregates: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    ready_count = stale_count = failed_count = 0

    for account in registry.get("accounts") or []:
        alias = account.get("account_alias")
        snapshot = snapshots.get(alias) if isinstance(snapshots.get(alias), dict) else {}
        age = snapshot_age_minutes(snapshot, reference)
        state = str(snapshot.get("status") or "UNREFRESHED").upper()
        if snapshot.get("ok") and age is not None and age <= max_age_minutes:
            state = "READY"
            ready_count += 1
        elif snapshot.get("ok"):
            state = "STALE"
            stale_count += 1
        else:
            failed_count += 1
        capacity = snapshot.get("capacity") if isinstance(snapshot.get("capacity"), dict) else {}
        if state in {"READY", "STALE"}:
            for field in totals:
                value = safe_float(capacity.get(field))
                if value is not None:
                    totals[field] = round(totals[field] + value, 4)
            for position in snapshot.get("positions") or []:
                if not isinstance(position, dict):
                    continue
                key = _position_key(position)
                bucket = aggregates.setdefault(key, {
                    **{name: position.get(name) for name in ("ticker", "security_type", "expiration", "strike", "right", "currency")},
                    "quantity": 0.0,
                    "market_value": 0.0,
                    "market_value_available": False,
                    "account_aliases": [],
                })
                bucket["quantity"] = round(bucket["quantity"] + (safe_float(position.get("quantity")) or 0.0), 4)
                market_value = safe_float(position.get("market_value"))
                if market_value is not None:
                    bucket["market_value"] = round(bucket["market_value"] + market_value, 4)
                    bucket["market_value_available"] = True
                if alias not in bucket["account_aliases"]:
                    bucket["account_aliases"].append(alias)
        accounts.append({
            **account,
            "refresh_status": state,
            "snapshot_age_minutes": age,
            "generated_at": snapshot.get("generated_at"),
            "capacity": capacity,
            "positions": snapshot.get("positions") if isinstance(snapshot.get("positions"), list) else [],
            "position_count": int(snapshot.get("position_count") or 0),
            "error": snapshot.get("error") or "",
        })

    account_count = len(registry.get("accounts") or [])
    status = "READY" if account_count and ready_count == account_count else "PARTIAL" if ready_count or stale_count else "WAIT_ACCOUNT_REFRESH"
    warnings = list(registry.get("warnings") or [])
    if registry.get("ambiguous_default_account"):
        warnings.append("AMBIGUOUS_DEFAULT_ACCOUNT")
    if stale_count:
        warnings.append("STALE_ACCOUNT_SNAPSHOTS")
    if failed_count:
        warnings.append("ACCOUNT_REFRESH_INCOMPLETE")
    return {
        "control_tower_version": CONTROL_TOWER_VERSION,
        "generated_at": reference.isoformat(),
        "status": status,
        "broker_count": len({row.get("broker") for row in accounts}),
        "account_count": account_count,
        "ready_account_count": ready_count,
        "stale_account_count": stale_count,
        "failed_account_count": failed_count,
        "active_account_alias": registry.get("active_account_alias") or "",
        "accounts": accounts,
        "consolidated_capacity": totals,
        "consolidated_positions": sorted(aggregates.values(), key=lambda row: (row.get("ticker") or "", row.get("security_type") or "")),
        "warnings": sorted(set(warnings)),
        "manual_review_required": status != "READY" or bool(warnings),
        "sensitive_identifiers_excluded": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def account_snapshot_path(runtime_dir: Path, alias: str) -> Path:
    return runtime_dir / "accounts" / normalize_alias(alias) / "account_snapshot.json"


def load_snapshots(runtime_dir: Path, registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshots = {}
    for account in registry.get("accounts") or []:
        alias = account.get("account_alias")
        path = account_snapshot_path(runtime_dir, alias)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        snapshots[alias] = data if isinstance(data, dict) else {}
    return snapshots


def write_snapshot(runtime_dir: Path, snapshot: dict[str, Any]) -> Path:
    path = account_snapshot_path(runtime_dir, snapshot.get("account_alias"))
    _write_json_atomic(path, snapshot)
    return path


def write_control_tower(path: Path, payload: dict[str, Any]) -> Path:
    _write_json_atomic(path, payload)
    return path


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
