"""Local editable context for active position thesis and entry data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POSITION_CONTEXT_STORE_VERSION = "position_context_store_v1"
DEFAULT_CONTEXT_PATH = Path("runtime") / "active_position_contexts.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def load_contexts(path: str | Path = DEFAULT_CONTEXT_PATH) -> dict[str, Any]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text())
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    contexts = payload.get("contexts") if isinstance(payload.get("contexts"), list) else []
    return {
        "context_store_version": payload.get("context_store_version") or POSITION_CONTEXT_STORE_VERSION,
        "updated_at": payload.get("updated_at"),
        "contexts": [item for item in contexts if isinstance(item, dict)],
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def save_contexts(payload: dict[str, Any], path: str | Path = DEFAULT_CONTEXT_PATH) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload or {})
    payload["context_store_version"] = POSITION_CONTEXT_STORE_VERSION
    payload["updated_at"] = now_iso()
    payload["not_order_instruction"] = True
    payload["execution_authorized"] = False
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return payload


def context_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        clean_text(item.get("position_id")),
        safe_upper(item.get("ticker")),
        safe_upper(item.get("strategy") or item.get("position_strategy")),
    )


def normalize_context(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item or {})
    thesis = item.get("thesis") if isinstance(item.get("thesis"), dict) else {}
    entry = item.get("entry") if isinstance(item.get("entry"), dict) else {}
    normalized = {
        "position_id": clean_text(item.get("position_id")),
        "ticker": safe_upper(item.get("ticker")),
        "strategy": safe_upper(item.get("strategy") or item.get("position_strategy")),
        "updated_at": item.get("updated_at") or now_iso(),
        "thesis": {
            "text": clean_text(thesis.get("text") or item.get("thesis_text")),
            "entry_reason": clean_text(thesis.get("entry_reason") or item.get("entry_reason")),
            "invalidation_level": thesis.get("invalidation_level", item.get("invalidation_level")),
            "target": thesis.get("target", item.get("target")),
            "assignment_preference": clean_text(thesis.get("assignment_preference") or item.get("assignment_preference")),
            "roll_plan": clean_text(thesis.get("roll_plan") or item.get("roll_plan")),
        },
        "entry": {
            "entry_date": clean_text(entry.get("entry_date") or item.get("entry_date")),
            "entry_credit": entry.get("entry_credit", item.get("entry_credit")),
            "entry_debit": entry.get("entry_debit", item.get("entry_debit")),
            "entry_price": entry.get("entry_price", item.get("entry_price")),
            "entry_quantity": entry.get("entry_quantity", item.get("entry_quantity")),
            "cost_basis": entry.get("cost_basis", item.get("cost_basis")),
            "source": clean_text(entry.get("source") or item.get("source") or "stock_ultimus_console"),
        },
        "notes": clean_text(item.get("notes")),
        "not_order_instruction": True,
        "execution_authorized": False,
    }
    normalized["thesis"] = {k: v for k, v in normalized["thesis"].items() if v not in [None, ""]}
    normalized["entry"] = {k: v for k, v in normalized["entry"].items() if v not in [None, ""]}
    return normalized


def upsert_context(item: dict[str, Any], path: str | Path = DEFAULT_CONTEXT_PATH) -> dict[str, Any]:
    incoming = normalize_context(item)
    if not incoming.get("position_id") and not incoming.get("ticker"):
        raise ValueError("position context requires position_id or ticker")
    payload = load_contexts(path)
    incoming_key = context_key(incoming)
    contexts = []
    replaced = False
    for existing in payload.get("contexts") or []:
        existing_key = context_key(existing)
        same_position = incoming_key[0] and existing_key[0] == incoming_key[0]
        same_ticker_strategy = incoming_key[1] and existing_key[1] == incoming_key[1] and existing_key[2] == incoming_key[2]
        if same_position or same_ticker_strategy:
            contexts.append(incoming)
            replaced = True
        else:
            contexts.append(existing)
    if not replaced:
        contexts.insert(0, incoming)
    payload["contexts"] = contexts[:500]
    return save_contexts(payload, path)


def find_context(row: dict[str, Any], contexts: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    row_key = context_key(row)
    fallback = None
    for item in contexts or []:
        if not isinstance(item, dict):
            continue
        item_key = context_key(item)
        if row_key[0] and item_key[0] == row_key[0]:
            return item
        if row_key[1] and item_key[1] == row_key[1] and (not row_key[2] or not item_key[2] or item_key[2] == row_key[2]):
            fallback = fallback or item
    return fallback


def merge_context_into_position(row: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, dict):
        return dict(row or {})
    merged = dict(row or {})
    thesis = context.get("thesis") if isinstance(context.get("thesis"), dict) else {}
    entry = context.get("entry") if isinstance(context.get("entry"), dict) else {}
    if thesis:
        merged["thesis"] = thesis
        for key in ["invalidation_level", "target", "assignment_preference", "roll_plan", "entry_reason"]:
            if thesis.get(key) not in [None, ""]:
                merged[key] = thesis.get(key)
        if thesis.get("text"):
            merged["entry_thesis"] = thesis.get("text")
    for key, value in entry.items():
        if value not in [None, ""]:
            merged[key] = value
    merged["position_context_source"] = context.get("entry", {}).get("source") or "active_position_contexts"
    merged["position_context_updated_at"] = context.get("updated_at")
    return merged


def summary(path: str | Path = DEFAULT_CONTEXT_PATH) -> dict[str, Any]:
    payload = load_contexts(path)
    contexts = payload.get("contexts") or []
    return {
        "context_store_version": POSITION_CONTEXT_STORE_VERSION,
        "context_count": len(contexts),
        "latest_context": contexts[0] if contexts else None,
        "not_order_instruction": True,
        "execution_authorized": False,
    }
