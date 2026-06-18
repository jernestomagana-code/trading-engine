#!/usr/bin/env python3
"""Guard legacy-compatible endpoints keep explicit lifecycle metadata."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
V28_MASTER = RUNTIME_DIR / "v28_master_snapshot.json"
V25_ALIAS = RUNTIME_DIR / "v25_master_snapshot.json"
V22_2_TECH = RUNTIME_DIR / "technical_snapshot_by_ticker_safe.json"
V22_2_DECISION = RUNTIME_DIR / "decision_desk_snapshot.json"
V22_2_UNIFIED = RUNTIME_DIR / "v22_2_unified_remote_snapshot.json"


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_legacy_guard", app_path)
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


def assert_legacy_payload(payload, engine_name, replacement_prefix):
    require(isinstance(payload, dict), f"{engine_name}: payload must be dict")
    require(payload.get("engine_lifecycle") == "legacy_compatibility_only", f"{engine_name}: missing legacy lifecycle")
    require(payload.get("canonical_source_of_truth") is False, f"{engine_name}: canonical flag must be false")

    compat = payload.get("legacy_compatibility") or {}
    require(compat.get("engine") == engine_name, f"{engine_name}: wrong legacy engine metadata {compat}")
    require(compat.get("lifecycle") == "legacy_compatibility_only", f"{engine_name}: wrong compatibility lifecycle {compat}")
    replacements = compat.get("replacement_endpoints") or []
    require(any(str(item).startswith(replacement_prefix) for item in replacements), f"{engine_name}: missing replacement {replacement_prefix}")


async def maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value


def parity_payload():
    return {
        "source": "LEGACY_INGEST_PARITY_TEST",
        "generated_at": "2026-06-16T00:00:00+00:00",
        "options_rows": [
            {
                "ticker": "AAPL",
                "strategy": "NAKED_PUT",
                "decision": "ENTRY",
                "score": 92,
                "price": 185.0,
                "data_quality": "FULL_WITH_GREEKS",
                "risk": {"passes": True},
                "strike": 180.0,
                "expiration": "2026-07-17",
                "dte": 39,
                "bid": 1.2,
                "ask": 1.35,
                "mid": 1.275,
                "spread": 0.15,
                "spread_pct": 11.76,
                "delta": -0.28,
                "volume": 150,
                "open_interest": 500,
            }
        ],
        "technical_snapshot": {
            "AAPL": {
                "ticker": "AAPL",
                "trend": "BULLISH",
                "score": 85,
                "event_risk": False,
                "earnings_soon": False,
            }
        },
        "market": {
            "is_regular_market_open": True,
            "options_bidask_expected": True,
            "label": "PARITY_TEST",
        },
    }


def split_technical_payload():
    return {
        "ticker": "AAPL",
        "technical": {
            "trend": "BULLISH",
            "score": 85,
            "event_risk": False,
            "earnings_soon": False,
        },
        "source": "LEGACY_V22_2_SPLIT_TECH_TEST",
    }


def split_decision_payload():
    base = parity_payload()
    return {
        "source": "LEGACY_V22_2_SPLIT_DECISION_TEST",
        "rows": list(base["options_rows"]),
        "market_hours": {
            "status": "REGULAR_OPTIONS_SESSION",
            "label": "PARITY_TEST",
            "is_regular_market_open": True,
            "options_bidask_expected": True,
        },
    }


def snapshot_summary():
    master = json.loads(V28_MASTER.read_text())
    alias = json.loads(V25_ALIAS.read_text())
    return {
        "master": {
            "rows_found": master.get("rows_found"),
            "tickers_detected": master.get("tickers_detected"),
            "technical_available": master.get("technical_available"),
        },
        "alias": {
            "rows_found": alias.get("rows_found"),
            "tickers_detected": alias.get("tickers_detected"),
            "technical_available": alias.get("technical_available"),
        },
    }


def resolve_runtime_path(value):
    return str((ROOT / str(value)).resolve()) if not Path(str(value)).is_absolute() else str(Path(str(value)).resolve())


async def main_async() -> int:
    app = load_app_module()
    app.SNAPSHOT_INGEST_TOKEN = "local-integrity-test-token"
    RUNTIME_DIR.mkdir(exist_ok=True)

    backups = {}
    for path in [V28_MASTER, V25_ALIAS, V22_2_TECH, V22_2_DECISION, V22_2_UNIFIED]:
        backups[path] = path.read_text() if path.exists() else None

    try:
        inventory = app.decision_engine_inventory()
        require(inventory.get("status") == "OK", f"inventory not OK: {inventory}")
        canonical = inventory.get("canonical_source_of_truth") or []
        legacy = inventory.get("legacy_compatibility_only") or []
        require(any(item.get("engine") == "V29_FINAL_DECISION_QUALITY_ENGINE" for item in canonical), "inventory missing V29 canonical engine")
        require(any(item.get("engine") == "V22_UNIFIED_TRADING_DECISION_ENGINE" for item in legacy), "inventory missing V22 legacy engine")

        v28_response = await maybe_await(
            app.v28_ingest_snapshot(
                parity_payload(),
                "local-integrity-test-token",
                None,
                None,
            )
        )
        require(v28_response.get("status") == "OK", f"v28 ingest failed: {v28_response}")
        v28_summary = snapshot_summary()
        v28_decision = app._v29_decide_ticker("AAPL")
        require(v28_decision.get("final_state") == "ENTRY_READY", f"v28 parity decision mismatch: {v28_decision}")

        v25_response = await maybe_await(app.v25_ingest_snapshot(parity_payload()))
        require(v25_response.get("status") == "OK", f"v25 ingest failed: {v25_response}")
        require(v25_response.get("delegated_to") == "/v28_ingest_snapshot", f"v25 missing delegation marker: {v25_response}")
        require(resolve_runtime_path(v25_response.get("canonical_stored_file")) == str(V28_MASTER.resolve()), f"v25 wrong canonical file: {v25_response}")
        v25_summary = snapshot_summary()
        require(v25_summary == v28_summary, f"v25 canonical snapshot mismatch: {v25_summary} != {v28_summary}")
        v25_decision = app._v29_decide_ticker("AAPL")
        require(v25_decision.get("final_state") == v28_decision.get("final_state"), f"v25 parity decision mismatch: {v25_decision} vs {v28_decision}")

        v22_2_response = app.v22_2_ingest_unified_snapshot(parity_payload())
        require(v22_2_response.get("status") == "OK", f"v22.2 unified ingest failed: {v22_2_response}")
        require(resolve_runtime_path(v22_2_response.get("canonical_stored_file")) == str(V28_MASTER.resolve()), f"v22.2 wrong canonical file: {v22_2_response}")
        require(V22_2_UNIFIED.exists(), "v22.2 unified file was not written")
        v22_2_summary = snapshot_summary()
        require(v22_2_summary == v28_summary, f"v22.2 canonical snapshot mismatch: {v22_2_summary} != {v28_summary}")
        v22_2_decision = app._v29_decide_ticker("AAPL")
        require(v22_2_decision.get("final_state") == v28_decision.get("final_state"), f"v22.2 parity decision mismatch: {v22_2_decision} vs {v28_decision}")

        for path in [V28_MASTER, V25_ALIAS, V22_2_TECH, V22_2_DECISION, V22_2_UNIFIED]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

        split_tech_response = app.v22_2_ingest_technical_snapshot(split_technical_payload())
        require(split_tech_response.get("status") == "OK", f"v22.2 technical ingest failed: {split_tech_response}")
        require(resolve_runtime_path(split_tech_response.get("canonical_stored_file")) == str(V28_MASTER.resolve()), f"v22.2 technical wrong canonical file: {split_tech_response}")
        require(V22_2_TECH.exists(), "v22.2 technical file was not written")
        split_after_tech = app._v29_decide_ticker("AAPL")
        require(split_after_tech.get("final_state") == "WAIT_OPTIONS_DATA", f"split technical should leave WAIT_OPTIONS_DATA, got {split_after_tech}")

        split_decision_response = app.v22_2_ingest_decision_snapshot(split_decision_payload())
        require(split_decision_response.get("status") == "OK", f"v22.2 decision ingest failed: {split_decision_response}")
        require(resolve_runtime_path(split_decision_response.get("canonical_stored_file")) == str(V28_MASTER.resolve()), f"v22.2 decision wrong canonical file: {split_decision_response}")
        require(V22_2_DECISION.exists(), "v22.2 decision file was not written")
        split_summary = snapshot_summary()
        require(split_summary == v28_summary, f"v22.2 split canonical snapshot mismatch: {split_summary} != {v28_summary}")
        split_after_decision = app._v29_decide_ticker("AAPL")
        require(split_after_decision.get("final_state") == "ENTRY_READY", f"split decision should promote to ENTRY_READY, got {split_after_decision}")

        app._v22_build_trade_decision = lambda ticker: {
            "engine": "V22_UNIFIED_TRADING_DECISION_ENGINE",
            "ticker": ticker,
            "final_state": "WAIT_OPTIONS_DATA",
            "decision": "WAIT_OPTIONS_DATA",
            "can_operate": False,
        }
        assert_legacy_payload(app.v22_trade_decision("AAPL"), "V22_UNIFIED_TRADING_DECISION_ENGINE", "/v29_trade_decision")
        assert_legacy_payload(app.gpt_trade_decision("AAPL"), "V22_UNIFIED_TRADING_DECISION_ENGINE", "/v29_trade_decision")

        app._v23_build_trade_readiness = lambda ticker: {
            "engine": "V23_TRADE_READINESS_EXECUTION_GUARD",
            "ticker": ticker,
            "final_state": "WAIT_TECHNICAL",
            "decision": "WAIT_TECHNICAL",
            "can_operate": False,
        }
        v23 = await maybe_await(app.v23_trade_decision("AAPL"))
        assert_legacy_payload(v23, "V23_TRADE_READINESS_EXECUTION_GUARD", "/v29_trade_decision")

        app._v24_decision_for_ticker = lambda ticker: {
            "engine": "V24_UNIFIED_DATA_RESOLVER",
            "ticker": ticker,
            "final_state": "WAIT_MARKET_OPEN",
            "decision": "WAIT_MARKET_OPEN",
            "can_operate": False,
        }
        v24 = await maybe_await(app.v24_trade_decision("AAPL"))
        assert_legacy_payload(v24, "V24_UNIFIED_DATA_RESOLVER", "/v27_1_runtime_inventory")

        app._v241_trade_decision = lambda ticker: {
            "engine": "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD",
            "ticker": ticker,
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
        }
        app._v241_load_all_runtime_context = lambda: {
            "files": ["runtime/v28_master_snapshot.json"],
            "file_report": [],
            "rows": [],
            "rows_found": 0,
            "technical_by_ticker": {},
            "technical_tickers": [],
            "tickers": [],
        }
        v241_inventory = await maybe_await(app.v24_1_runtime_inventory())
        assert_legacy_payload(v241_inventory, "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD", "/v27_1_runtime_inventory")
        v241 = await maybe_await(app.v24_1_trade_decision("AAPL"))
        assert_legacy_payload(v241, "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD", "/v27_1_runtime_inventory")

        app._v25_make_decision = lambda ticker: {
            "engine": "V25_REMOTE_SNAPSHOT_STORE",
            "ticker": ticker,
            "final_state": "RISK_BLOCKED",
            "decision": "RISK_BLOCKED",
            "can_operate": False,
        }
        v25 = await maybe_await(app.v25_trade_decision("AAPL"))
        assert_legacy_payload(v25, "V25_REMOTE_SNAPSHOT_STORE", "/v28_ingest_snapshot")
    finally:
        for path, backup in backups.items():
            if backup is None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            else:
                path.write_text(backup)

    print("Validated legacy compatibility metadata and ingest parity on V22-V25 wrappers.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
