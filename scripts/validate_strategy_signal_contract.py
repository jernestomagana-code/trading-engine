#!/usr/bin/env python3
"""Validate TradingView strategy signal payload fixtures."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "tradingview"
CONTRACT_VERSION = "strategy_signal_contract_v1"
REQUIRED_FIELDS = {
    "ticker",
    "timeframe",
    "strategy_context",
    "trend",
    "score",
}
ALLOWED_CONTEXTS = {
    "NAKED_PUT",
    "CASH_SECURED_PUT",
    "COVERED_CALL",
    "IRON_CONDOR",
    "FUTURES",
    "CANSLIM_FILTER",
}
ALLOWED_TRENDS = {
    "BULLISH",
    "BEARISH",
    "NEUTRAL",
    "RANGE",
    "SIDEWAYS",
    "UP",
    "DOWN",
    "ALCISTA",
    "BAJISTA",
}
NUMERIC_FIELDS = {
    "score",
    "rsi",
    "adx",
    "volume_relative",
    "iv_rank",
    "iv_percentile",
    "canslim_score",
}
BOOLEAN_FIELDS = {
    "support_near",
    "resistance_near",
    "range_20d",
    "range_breakout",
    "earnings_soon",
    "event_risk",
    "canslim_passes",
}
FORBIDDEN_SENSITIVE_KEYS = {
    "account",
    "account_id",
    "acct",
    "balance",
    "buying_power",
    "cash",
    "token",
    "api_key",
    "secret",
    "password",
    "cookie",
    "authorization",
}


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def upper(value: object) -> str:
    return str(value or "").strip().upper()


def walk_sensitive_keys(value: object, prefix: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            key_norm = re.sub(r"[^a-z0-9_]", "_", key_text.lower())
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_norm in FORBIDDEN_SENSITIVE_KEYS:
                hits.append(path)
            hits.extend(walk_sensitive_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(walk_sensitive_keys(child, f"{prefix}[{index}]"))
    return hits


def validate_canslim(payload: dict) -> list[str]:
    errors: list[str] = []
    canslim = payload.get("canslim")
    flat_score = payload.get("canslim_score")
    flat_passes = payload.get("canslim_passes")

    if canslim is None and flat_score is None and flat_passes is None:
        return errors

    if canslim is not None and not isinstance(canslim, dict):
        return ["canslim must be an object when provided"]

    source = canslim if isinstance(canslim, dict) else payload
    score = source.get("score", flat_score)
    passes = source.get("passes", flat_passes)

    if score is not None and not is_number(score):
        errors.append("canslim score must be a finite number")
    if is_number(score) and not 0 <= score <= 100:
        errors.append("canslim score must be between 0 and 100")
    if passes is not None and not isinstance(passes, bool):
        errors.append("canslim passes must be boolean")

    return errors


def validate_payload(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]

    if not isinstance(payload, dict):
        return ["payload root must be an object"]

    missing = sorted(REQUIRED_FIELDS - set(payload))
    if missing:
        errors.append(f"missing required fields: {missing}")

    ticker = payload.get("ticker")
    if not isinstance(ticker, str) or not re.fullmatch(r"[A-Z0-9._-]{1,12}", ticker.strip().upper()):
        errors.append("ticker must be a compact symbol string")

    timeframe = payload.get("timeframe")
    if not isinstance(timeframe, str) or not timeframe.strip():
        errors.append("timeframe must be a non-empty string")

    context = upper(payload.get("strategy_context"))
    if context not in ALLOWED_CONTEXTS:
        errors.append(f"strategy_context must be one of {sorted(ALLOWED_CONTEXTS)}")

    trend = upper(payload.get("trend"))
    if trend not in ALLOWED_TRENDS:
        errors.append(f"trend must be one of {sorted(ALLOWED_TRENDS)}")

    version = payload.get("contract_version")
    if version is not None and version != CONTRACT_VERSION:
        errors.append(f"contract_version must be {CONTRACT_VERSION}")

    for field in NUMERIC_FIELDS:
        if field in payload and payload.get(field) is not None and not is_number(payload.get(field)):
            errors.append(f"{field} must be a finite number")

    score = payload.get("score")
    if is_number(score) and not 0 <= score <= 100:
        errors.append("score must be between 0 and 100")

    for field in BOOLEAN_FIELDS:
        if field in payload and payload.get(field) is not None and not isinstance(payload.get(field), bool):
            errors.append(f"{field} must be boolean")

    sensitive_hits = walk_sensitive_keys(payload)
    if sensitive_hits:
        errors.append(f"payload contains sensitive keys: {sensitive_hits}")

    errors.extend(validate_canslim(payload))

    return errors


def main() -> int:
    failures: list[str] = []
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    if not paths:
        failures.append(f"missing TradingView fixtures in {FIXTURE_DIR.relative_to(ROOT)}")

    for path in paths:
        errors = validate_payload(path)
        failures.extend(f"{path.relative_to(ROOT)}: {error}" for error in errors)

    if failures:
        print("\n".join(failures))
        return 1

    print(f"Validated {len(paths)} TradingView strategy signal fixtures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
