"""Manual/imported gamma context store for Stock Ultimus."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GAMMA_CONTEXT_STORE_VERSION = "gamma_context_store_v1"
DEFAULT_GAMMA_CONTEXT_PATH = Path("runtime") / "gamma_contexts.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    try:
        if value in [None, "", "None", "null"]:
            return None
        return float(value)
    except Exception:
        return None


def safe_upper(value: Any, default: str = "") -> str:
    text = str(value or "").strip().upper()
    return text or default


def load_contexts(path: str | Path = DEFAULT_GAMMA_CONTEXT_PATH) -> dict[str, Any]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text())
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    contexts = payload.get("contexts") if isinstance(payload.get("contexts"), list) else []
    return {
        "gamma_context_store_version": payload.get("gamma_context_store_version") or GAMMA_CONTEXT_STORE_VERSION,
        "updated_at": payload.get("updated_at"),
        "contexts": [normalize_context(item) for item in contexts if isinstance(item, dict)],
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def save_contexts(payload: dict[str, Any], path: str | Path = DEFAULT_GAMMA_CONTEXT_PATH) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload or {})
    payload["gamma_context_store_version"] = GAMMA_CONTEXT_STORE_VERSION
    payload["updated_at"] = now_iso()
    payload["not_order_instruction"] = True
    payload["execution_authorized"] = False
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return payload


def normalize_context(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item or {})
    ticker = safe_upper(item.get("ticker") or item.get("symbol"))
    context = {
        "ticker": ticker,
        "as_of": item.get("as_of") or item.get("generated_at") or now_iso(),
        "source": str(item.get("source") or "manual_gamma_json").strip(),
        "gamma_wall": safe_float(item.get("gamma_wall")),
        "call_wall": safe_float(item.get("call_wall")),
        "put_wall": safe_float(item.get("put_wall")),
        "zero_gamma": safe_float(item.get("zero_gamma")),
        "net_gamma": safe_float(item.get("net_gamma")),
        "gamma_exposure": safe_float(item.get("gamma_exposure")),
        "notes": str(item.get("notes") or "").strip(),
        "not_order_instruction": True,
        "execution_authorized": False,
    }
    return {key: value for key, value in context.items() if value not in [None, ""]}


def upsert_context(item: dict[str, Any], path: str | Path = DEFAULT_GAMMA_CONTEXT_PATH) -> dict[str, Any]:
    incoming = normalize_context(item)
    if not incoming.get("ticker"):
        raise ValueError("gamma context requires ticker")
    payload = load_contexts(path)
    contexts = []
    replaced = False
    for existing in payload.get("contexts") or []:
        if safe_upper(existing.get("ticker")) == incoming["ticker"]:
            contexts.append(incoming)
            replaced = True
        else:
            contexts.append(existing)
    if not replaced:
        contexts.insert(0, incoming)
    payload["contexts"] = contexts[:500]
    return save_contexts(payload, path)


def by_ticker(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = payload if isinstance(payload, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for item in payload.get("contexts") or []:
        if not isinstance(item, dict):
            continue
        ticker = safe_upper(item.get("ticker"))
        if ticker:
            out[ticker] = normalize_context(item)
    return out


def summary(path: str | Path = DEFAULT_GAMMA_CONTEXT_PATH) -> dict[str, Any]:
    payload = load_contexts(path)
    contexts = payload.get("contexts") or []
    return {
        "gamma_context_store_version": GAMMA_CONTEXT_STORE_VERSION,
        "context_count": len(contexts),
        "tickers": sorted([item.get("ticker") for item in contexts if item.get("ticker")]),
        "latest_context": contexts[0] if contexts else None,
        "not_order_instruction": True,
        "execution_authorized": False,
    }
