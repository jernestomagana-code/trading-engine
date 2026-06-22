#!/usr/bin/env python3
"""Validate LOCAL_TECHNICAL_ENGINE contract and app integration."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def bullish_bars(count: int = 60) -> list[dict]:
    price = 100.0
    rows = []
    for index in range(count):
        price += 0.3
        rows.append({
            "timestamp": f"2026-06-{(index % 28) + 1:02d}T14:30:00+00:00",
            "open": price - 0.25,
            "high": price + 0.45,
            "low": price - 0.55,
            "close": price,
            "volume": 1_000_000 + index,
        })
    return rows


def choppy_bars(count: int = 60) -> list[dict]:
    price = 100.0
    rows = []
    for index in range(count):
        price += 0.35 if index % 2 == 0 else -0.33
        rows.append({
            "open": price - 0.1,
            "high": price + 0.4,
            "low": price - 0.4,
            "close": price,
            "volume": 800_000,
        })
    return rows


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import local_technical_engine

    caps = local_technical_engine.capabilities()
    require(caps.get("tradingview_required") is False, f"TradingView must not be required: {caps}")
    require(caps.get("execution_authorized") is False, f"Execution must not be authorized: {caps}")
    require(caps.get("not_order_instruction") is True, f"No-order guardrail missing: {caps}")

    snapshot = local_technical_engine.build_technical_snapshot({
        "QQQ": bullish_bars(),
        "SPY": choppy_bars(),
    })
    require(set(snapshot) == {"QQQ", "SPY"}, f"Ticker-keyed snapshot mismatch: {snapshot.keys()}")
    qqq = snapshot["QQQ"]
    require(qqq.get("source") == "LOCAL_TECHNICAL_ENGINE", f"Wrong source: {qqq}")
    require(qqq.get("execution_authorized") is False, f"Execution guardrail missing: {qqq}")
    require(qqq.get("not_order_instruction") is True, f"No-order guardrail missing: {qqq}")
    require("by_strategy_context" in qqq, f"Missing strategy contexts: {qqq}")
    require("CASH_SECURED_PUT" in qqq["by_strategy_context"], f"Missing CSP context: {qqq}")
    require("NAKED_PUT" in qqq["by_strategy_context"], f"Missing Naked Put alias: {qqq}")

    insufficient = local_technical_engine.evaluate_symbol("MSFT", [{"close": 100}], "CASH_SECURED_PUT")
    require(insufficient.get("confirmed") is False, f"Insufficient bars should not confirm: {insufficient}")
    require("INSUFFICIENT_LOCAL_BARS" in insufficient.get("blockers", []), f"Missing blocker: {insufficient}")

    # Avoid importing the full FastAPI app here: local Python 3.9 + current
    # Pydantic stack cannot evaluate some pre-existing ``str | None`` endpoint
    # annotations in app/main.py.  The integration contract is still checked by
    # py_compile plus route/source assertions.
    app_source = (ROOT / "app" / "main.py").read_text()
    require("import local_technical_engine as shared_local_technical_engine" in app_source, "Missing app import")
    require("@app.get(\"/strategy_local_technical_engine\")" in app_source, "Missing metadata endpoint")
    require("@app.post(\"/strategy_local_technical_engine/evaluate\")" in app_source, "Missing evaluate endpoint")
    require("\"local_technical_engine\": shared_local_technical_engine.capabilities()" in app_source, "Missing playbook link")

    print("Validated LOCAL_TECHNICAL_ENGINE contract, V31 compatibility, and no-order guardrails.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
