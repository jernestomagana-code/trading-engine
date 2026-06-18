#!/usr/bin/env python3
"""Static checks for Stock Ultimus TradingView Pine scripts."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PINE_DIR = ROOT / "tradingview"
CONTRACT_VERSION = "strategy_signal_contract_v1"
REQUIRED_SNIPPETS = [
    "//@version=5",
    "strategy_context",
    CONTRACT_VERSION,
    "alert(",
]


def validate_pine(path: Path) -> list[str]:
    text = path.read_text()
    errors: list[str] = []

    for snippet in REQUIRED_SNIPPETS:
        if snippet not in text:
            errors.append(f"missing required snippet: {snippet}")

    if "placeOrder" in text or "strategy.order" in text or "strategy.entry" in text:
        errors.append("Pine alert scripts must not contain order/strategy execution calls")

    if "token" in text.lower() or "api_key" in text.lower() or "secret" in text.lower():
        errors.append("Pine alert scripts must not embed secrets or token-like fields")

    if re.search(r'^\s*payload\s*=.*\+\s*$', text, flags=re.MULTILINE):
        errors.append("payload assignment must not use an end-of-line continuation operator")

    if path.name == "stock_ultimus_futures_signal_pro_v2.pine":
        for snippet in ["canonicalTicker", "chart_ticker"]:
            if snippet not in text:
                errors.append(f"futures Pro V2 missing canonical ticker field: {snippet}")

    return errors


def main() -> int:
    failures: list[str] = []
    paths = sorted(PINE_DIR.glob("*.pine"))
    if not paths:
        failures.append(f"missing Pine scripts in {PINE_DIR.relative_to(ROOT)}")

    for path in paths:
        errors = validate_pine(path)
        failures.extend(f"{path.relative_to(ROOT)}: {error}" for error in errors)

    if failures:
        print("\n".join(failures))
        return 1

    print(f"Validated {len(paths)} TradingView Pine scripts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
