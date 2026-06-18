#!/usr/bin/env python3
"""Guard canonical V31-style states on newer legacy-compatible paths."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_v31_guard", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")

    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def option_row(**overrides):
    row = {
        "ticker": "AAPL",
        "strategy": "NAKED_PUT",
        "strategy_hint": "NAKED_PUT",
        "decision": "ENTRY",
        "score": 90,
        "data_quality": "FULL_WITH_GREEKS",
        "can_operate": True,
        "missing_confirmations": [],
        "volume": 150,
        "open_interest": 500,
    }
    row.update(overrides)
    return row


def technical(**overrides):
    data = {
        "ticker": "AAPL",
        "trend": "BULLISH",
        "score": 85,
        "rsi": 50,
        "adx": 18,
        "event_risk": False,
        "earnings_soon": False,
    }
    data.update(overrides)
    return data


def market(is_open=True):
    return {
        "label": "TEST",
        "is_regular_market_open": is_open,
        "options_bidask_expected": is_open,
        "raw": {},
    }


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    app = load_app_module()

    app._v27_save_json_file = lambda *args, **kwargs: None
    app._v27_get_master_snapshot = lambda: {"source": "test"}
    app._v27_extract_option_rows = lambda master: [option_row()]
    app._v27_load_technical_map = lambda: ({"AAPL": technical(event_risk=True)}, [])
    app._v27_market_hours = lambda master: market(True)
    v27 = app._v27_decide_for_ticker("AAPL")
    require(v27.get("final_state") == "RISK_BLOCKED", f"v27 should risk-block event risk, got {v27}")
    require(v27.get("main_blocker") == "EVENT_RISK_ACTIVE", f"v27 wrong blocker: {v27}")

    app._v271_find_best_runtime_snapshot = lambda: ({}, "test-runtime", {"best_candidates": []})
    app._v271_rows_from_anywhere = lambda data: [option_row()]
    app._v271_technical_from_anywhere = lambda data: {"AAPL": None}
    app._v27_load_technical_map = lambda: ({}, [])
    app._v271_market_from_anywhere = lambda data: market(True)
    v271 = app._v271_decide_for_ticker("AAPL")
    require(v271.get("final_state") == "WAIT_TECHNICAL", f"v27.1 should use canonical WAIT_TECHNICAL, got {v271}")

    app._v28_load_master = lambda: ({}, "test-master")
    app._v28_rows = lambda data: [option_row()]
    app._v28_technical_map = lambda data: {"AAPL": technical()}
    app._v28_market = lambda data: market(False)
    v28_market = app._v28_decide("AAPL")
    require(v28_market.get("final_state") == "WAIT_MARKET_OPEN", f"v28 should use WAIT_MARKET_OPEN, got {v28_market}")
    require(v28_market.get("can_operate") is False, f"v28 WAIT_MARKET_OPEN must not be operable, got {v28_market}")

    app._v28_market = lambda data: market(True)
    app._v28_rows = lambda data: [option_row(volume=10, open_interest=500)]
    v28_liquidity = app._v28_decide("AAPL")
    require(v28_liquidity.get("final_state") == "RISK_BLOCKED", f"v28 should risk-block low volume, got {v28_liquidity}")
    require(v28_liquidity.get("main_blocker") == "LOW_OPTION_VOLUME", f"v28 wrong liquidity blocker: {v28_liquidity}")

    print("Validated V31 canonical states on v27/v27.1/v28 paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
