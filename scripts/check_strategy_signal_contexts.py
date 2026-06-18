#!/usr/bin/env python3
"""Validate strategy-context signal fusion and CANSLIM preservation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_signal_contexts", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")

    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    app = load_app_module()
    contexts = {
        "NAKED_PUT": {
            "ticker": "AAPL",
            "strategy_context": "NAKED_PUT",
            "trend": "bullish",
            "score": 82,
            "received_at": "2026-06-17T20:00:00+00:00",
        },
        "COVERED_CALL": {
            "ticker": "AAPL",
            "strategy_context": "COVERED_CALL",
            "trend": "neutral",
            "score": 74,
            "received_at": "2026-06-17T20:01:00+00:00",
        },
        "CANSLIM_FILTER": {
            "ticker": "AAPL",
            "strategy_context": "CANSLIM_FILTER",
            "trend": "bullish",
            "score": 42,
            "canslim": {"passes": False, "score": 42, "rating": "FAIL"},
            "received_at": "2026-06-17T20:02:00+00:00",
        },
    }

    merged = app._strategy_signal_merge_contexts("AAPL", contexts)
    technical = {"AAPL": merged}

    naked_put = app._v29_technical_state("AAPL", technical, "NAKED_PUT")
    require(naked_put.get("score") == 82, f"Naked Put context score mismatch: {naked_put}")
    require(naked_put.get("trend") == "BULLISH", f"Naked Put trend mismatch: {naked_put}")
    require(naked_put.get("strategy_context") == "NAKED_PUT", f"Naked Put context mismatch: {naked_put}")

    covered_call = app._v29_technical_state("AAPL", technical, "COVERED_CALL")
    require(covered_call.get("score") == 74, f"Covered Call context score mismatch: {covered_call}")
    require(covered_call.get("trend") == "NEUTRAL", f"Covered Call trend mismatch: {covered_call}")
    require(covered_call.get("strategy_context") == "COVERED_CALL", f"Covered Call context mismatch: {covered_call}")

    canslim = (naked_put.get("raw") or {}).get("canslim") or {}
    require(canslim.get("passes") is False, f"CANSLIM result was not preserved: {naked_put}")
    canslim_gate = app._v29_canslim_gate({}, naked_put.get("raw") or {}, "NAKED_PUT")
    require(canslim_gate.get("ok") is False, f"CANSLIM failure should block: {canslim_gate}")
    require(canslim_gate.get("blockers") == ["CANSLIM_BLOCKED"], f"Unexpected CANSLIM blockers: {canslim_gate}")

    require(
        merged.get("available_strategy_contexts") == ["CANSLIM_FILTER", "COVERED_CALL", "NAKED_PUT"],
        f"Available contexts mismatch: {merged.get('available_strategy_contexts')}",
    )

    print("Validated strategy-context signal fusion and CANSLIM preservation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
