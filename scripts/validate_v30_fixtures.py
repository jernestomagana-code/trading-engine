#!/usr/bin/env python3
"""Validate V30 decision integrity fixtures and basic no-auto-order guardrails."""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "v30"
SCAN_PATHS = [
    ROOT / "ibkr_bridge.py",
    ROOT / "app" / "main.py",
    ROOT / "tmp_v30_patch" / "ibkr_bridge.py",
    ROOT / "tmp_v30_patch" / "app" / "main.py",
]
REQUIRED_OPTION_FIELDS = {
    "strike",
    "expiration",
    "dte",
    "bid",
    "ask",
    "mid",
    "spread",
    "spread_pct",
    "delta",
}
ENTRY_READY_DECISIONS = {"ENTRY_READY"}
WAIT_OPTIONS_DECISIONS = {"WAIT_OPTIONS_DATA"}
WAIT_TECHNICAL_DECISIONS = {"WAIT_TECHNICAL"}
FORBIDDEN_ORDER_PATTERNS = {
    "placeOrder": re.compile(r"\bplaceOrder\s*\("),
    "submitOrder": re.compile(r"\bsubmitOrder\s*\("),
    "bracketOrder": re.compile(r"\bbracketOrder\s*\("),
    "transmit_true": re.compile(r"\btransmit\s*=\s*True\b"),
    "whatif_false": re.compile(r"\bwhatIf\s*=\s*False\b"),
}


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_fixture(path: Path) -> tuple[dict, list[str]]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {}, [f"invalid JSON: {exc}"]

    if not isinstance(data, dict):
        return {}, ["fixture root must be an object"]

    return data, []


def option_validity_errors(option: object) -> list[str]:
    errors: list[str] = []

    if not isinstance(option, dict):
        return ["candidate.option must be an object"]

    missing_fields = REQUIRED_OPTION_FIELDS - set(option)
    if missing_fields:
        errors.append(f"missing option fields: {sorted(missing_fields)}")

    strike = option.get("strike")
    if "strike" in option and (not is_number(strike) or strike <= 0):
        errors.append("strike must be a positive finite number")

    expiration = option.get("expiration")
    if "expiration" in option:
        if not isinstance(expiration, str) or not expiration.strip():
            errors.append("expiration must be a non-empty YYYY-MM-DD string")
        else:
            try:
                date.fromisoformat(expiration)
            except ValueError:
                errors.append("expiration must be parseable as YYYY-MM-DD")

    dte = option.get("dte")
    if "dte" in option and (not is_number(dte) or dte < 0):
        errors.append("dte must be a non-negative finite number")
    if "dte" in option and is_number(dte) and int(dte) != dte:
        errors.append("dte must be an integer")

    bid = option.get("bid")
    ask = option.get("ask")
    mid = option.get("mid")
    spread = option.get("spread")
    spread_pct = option.get("spread_pct")
    delta = option.get("delta")

    if "bid" in option and (not is_number(bid) or bid <= 0):
        errors.append("bid must be a positive finite number")
    if "ask" in option and (not is_number(ask) or ask <= 0):
        errors.append("ask must be a positive finite number")
    if is_number(bid) and is_number(ask) and ask < bid:
        errors.append("ask must be greater than or equal to bid")
    if "mid" in option and (not is_number(mid) or mid <= 0):
        errors.append("mid must be a positive finite number")
    if "spread" in option and (not is_number(spread) or spread < 0):
        errors.append("spread must be a non-negative finite number")
    if "spread_pct" in option and (not is_number(spread_pct) or spread_pct < 0):
        errors.append("spread_pct must be a non-negative finite number")
    if "delta" in option and not is_number(delta):
        errors.append("delta must be a finite number")
    if is_number(delta) and (delta < -1 or delta > 1):
        errors.append("delta must be between -1 and 1")
    if is_number(bid) and is_number(ask) and is_number(mid):
        expected_mid = round((bid + ask) / 2, 4)
        if abs(mid - expected_mid) > 0.01:
            errors.append("mid must match bid/ask midpoint")
    if is_number(bid) and is_number(ask) and is_number(spread):
        expected_spread = round(ask - bid, 4)
        if abs(spread - expected_spread) > 0.01:
            errors.append("spread must match ask - bid")
    if is_number(spread) and is_number(mid) and mid > 0 and is_number(spread_pct):
        expected_spread_pct = round((spread / mid) * 100, 2)
        if abs(spread_pct - expected_spread_pct) > 0.25:
            errors.append("spread_pct must match spread / mid")

    return errors


def option_is_complete(option: object) -> bool:
    return not option_validity_errors(option)


def expected_decision_from_fixture(data: dict) -> str:
    technical_confirmed = bool((data.get("technical") or {}).get("confirmed"))
    candidate = data.get("candidate") or {}
    has_candidate_intent = bool(candidate.get("intent"))
    option = candidate.get("option")
    risk = data.get("risk") or {}

    if technical_confirmed and has_candidate_intent and not option_is_complete(option):
        return "WAIT_OPTIONS_DATA"
    if not technical_confirmed:
        return "WAIT_TECHNICAL"
    if risk.get("passes") is False:
        return "RISK_BLOCKED"
    if technical_confirmed and option_is_complete(option) and risk.get("passes", True) is True:
        return "ENTRY_READY"

    return "WAIT_OPTIONS_DATA"


def validate_fixture(path: Path) -> list[str]:
    data, errors = parse_fixture(path)
    if errors:
        return errors

    if "ticker" not in data:
        errors.append("missing ticker")
    if "strategy" not in data:
        errors.append("missing strategy")
    if "expected_decision" not in data:
        errors.append("missing expected_decision")

    expected = str(data.get("expected_decision") or "").upper()
    candidate = data.get("candidate") or {}
    option = candidate.get("option")
    option_errors = option_validity_errors(option)

    derived = expected_decision_from_fixture(data)
    if expected and expected != derived:
        errors.append(f"expected_decision {expected} conflicts with derived decision {derived}")

    if expected in ENTRY_READY_DECISIONS:
        if option_errors:
            errors.append(f"ENTRY_READY requires complete executable option data: {option_errors}")
        if not bool((data.get("technical") or {}).get("confirmed")):
            errors.append("ENTRY_READY requires confirmed technical signal")
        if (data.get("risk") or {}).get("passes", True) is not True:
            errors.append("ENTRY_READY requires passing risk rules")

    if expected in WAIT_OPTIONS_DECISIONS and not option_errors:
        errors.append("WAIT_OPTIONS_DATA fixture should include missing or invalid executable option data")

    if expected in WAIT_TECHNICAL_DECISIONS and option_errors:
        errors.append(f"WAIT_TECHNICAL fixture must not hide incomplete option data: {option_errors}")

    return errors


def validate_no_auto_order_execution() -> list[str]:
    errors: list[str] = []
    for path in SCAN_PATHS:
        if not path.exists():
            continue

        text = path.read_text()
        for name, pattern in FORBIDDEN_ORDER_PATTERNS.items():
            match = pattern.search(text)
            if match:
                line_no = text.count("\n", 0, match.start()) + 1
                rel = path.relative_to(ROOT)
                errors.append(f"{rel}:{line_no}: forbidden automatic order pattern: {name}")

    return errors


def main() -> int:
    failures: list[str] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        errors = validate_fixture(path)
        failures.extend(f"{path.relative_to(ROOT)}: {error}" for error in errors)

    failures.extend(validate_no_auto_order_execution())

    if failures:
        print("\n".join(failures))
        return 1

    print(f"Validated {len(list(FIXTURE_DIR.glob('*.json')))} V30 fixtures and no-auto-order guardrails.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
