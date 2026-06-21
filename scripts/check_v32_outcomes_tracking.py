#!/usr/bin/env python3
"""Guard V32 decision journaling and outcomes tracking."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
V28_MASTER = RUNTIME_DIR / "v28_master_snapshot.json"
V25_ALIAS = RUNTIME_DIR / "v25_master_snapshot.json"
LEGACY_DECISION = RUNTIME_DIR / "decision_desk_snapshot.json"
LEGACY_DECISION_ALIAS = RUNTIME_DIR / "decision_snapshot.json"
V32_DECISIONS = RUNTIME_DIR / "v32_decision_journal.json"
V32_OUTCOMES = RUNTIME_DIR / "v32_outcomes_journal.json"
AUDIT_LOG = RUNTIME_DIR / "stock_ultimus_audit_log.json"


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_v32_guard", app_path)
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


async def maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value


def parity_payload():
    return {
        "source": "V32_OUTCOMES_TEST",
        "generated_at": "2026-06-17T00:00:00+00:00",
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
            "label": "V32_TEST",
        },
    }


async def main_async() -> int:
    app = load_app_module()
    app.SNAPSHOT_INGEST_TOKEN = "local-integrity-test-token"
    RUNTIME_DIR.mkdir(exist_ok=True)

    backups = {}
    managed_paths = [V28_MASTER, V25_ALIAS, LEGACY_DECISION, LEGACY_DECISION_ALIAS, V32_DECISIONS, V32_OUTCOMES, AUDIT_LOG]
    for path in managed_paths:
        backups[path] = path.read_text() if path.exists() else None

    for path in managed_paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    try:
        ingest = await maybe_await(
            app.v28_ingest_snapshot(
                parity_payload(),
                "local-integrity-test-token",
                None,
                None,
            )
        )
        require(ingest.get("status") == "OK", f"v28 ingest failed: {ingest}")

        d1 = await maybe_await(app.v29_trade_decision("AAPL"))
        d2 = await maybe_await(app.v29_trade_decision("AAPL"))
        require(d1.get("decision_id"), f"missing decision_id on first v29 decision: {d1}")
        require(d1.get("decision_id") == d2.get("decision_id"), f"decision_id must be stable: {d1} vs {d2}")

        journal = app._v32_load_decision_journal()
        require(len(journal) == 1, f"journal should dedupe duplicate decision reads: {journal}")
        require(journal[0].get("final_state") == "ENTRY_READY", f"unexpected initial journal state: {journal[0]}")

        v31 = await maybe_await(app.v31_trade_decision("AAPL"))
        require(v31.get("decision_id") == d1.get("decision_id"), f"v31 must preserve decision_id: {v31} vs {d1}")

        followup_1 = await maybe_await(app.v32_record_followup({
            "decision_id": d1.get("decision_id"),
            "tag": "CHECK_1",
            "underlying_price": 184.0,
            "option_mid": 1.4,
            "pnl_r": -0.3,
        }))
        require(followup_1.get("status") == "ok", f"first followup failed: {followup_1}")

        followup_2 = await maybe_await(app.v32_record_followup({
            "decision_id": d1.get("decision_id"),
            "tag": "CHECK_2",
            "underlying_price": 187.0,
            "option_mid": 0.9,
            "pnl_r": 1.2,
        }))
        require(followup_2.get("status") == "ok", f"second followup failed: {followup_2}")
        require(followup_2.get("followup_summary", {}).get("mfe_r") == 1.2, f"mfe_r not updated: {followup_2}")
        require(followup_2.get("followup_summary", {}).get("mae_r") == -0.3, f"mae_r not updated: {followup_2}")

        history = await maybe_await(app.v32_decision_history(limit=10, ticker="AAPL"))
        require(history.get("showing") == 1, f"decision history should show one decision: {history}")
        latest = (history.get("decisions") or [{}])[-1]
        require(latest.get("followup_summary", {}).get("observation_count") == 2, f"followup count mismatch: {latest}")

        outcome = await maybe_await(app.v32_record_outcome({
            "decision_id": d1.get("decision_id"),
            "outcome": "WIN",
            "pnl": 120.0,
            "pnl_r": 1.0,
            "mfe_r": 1.2,
            "mae_r": -0.3,
            "exit_underlying_price": 187.0,
            "exit_option_mid": 0.9,
        }))
        require(outcome.get("status") == "ok", f"outcome failed: {outcome}")
        require(outcome.get("outcome", {}).get("duration_minutes") is not None, f"duration_minutes missing: {outcome}")

        summary = await maybe_await(app.v32_outcomes_summary(limit=10))
        stats = summary.get("summary", {}).get("outcomes", {})
        require(stats.get("closed_outcomes") == 1, f"closed_outcomes mismatch: {summary}")
        require(stats.get("wins") == 1, f"wins mismatch: {summary}")
        require(stats.get("win_rate") == 100.0, f"win_rate mismatch: {summary}")
        require(
            summary.get("strategy_performance", {}).get("strategy_performance_version") == "strategy_performance_v1",
            f"strategy performance summary missing: {summary}",
        )
        require(
            summary.get("endpoints", {}).get("strategy_performance") == "/v32_strategy_performance",
            f"strategy performance endpoint missing: {summary}",
        )

        performance = await maybe_await(app.v32_strategy_performance())
        require(performance.get("engine") == "V32_STRATEGY_PERFORMANCE", f"unexpected performance engine: {performance}")
        require(performance.get("not_order_instruction") is True, f"performance must preserve no-order guard: {performance}")
        require(performance.get("execution_authorized") is False, f"performance must never authorize execution: {performance}")
        naked_put = next(
            (item for item in performance.get("strategies", []) if item.get("strategy") == "NAKED_PUT"),
            None,
        )
        require(naked_put is not None, f"NAKED_PUT performance row missing: {performance}")
        require(naked_put.get("closed_outcomes") == 1, f"NAKED_PUT closed outcomes mismatch: {naked_put}")
        require(naked_put.get("wins") == 1, f"NAKED_PUT wins mismatch: {naked_put}")
        require(naked_put.get("win_rate") == 100.0, f"NAKED_PUT win rate mismatch: {naked_put}")
        require(naked_put.get("net_pnl_r") == 1.0, f"NAKED_PUT pnl_r mismatch: {naked_put}")
        require(naked_put.get("sample_size_warning") is True, f"small sample warning missing: {naked_put}")

        audit_events = app._audit_events(limit=20)
        audit_types = [event.get("event_type") for event in audit_events]
        require(
            any(event_type in audit_types for event_type in ["DECISION_RECORDED", "DECISION_REFRESHED"]),
            f"decision audit event missing: {audit_events}",
        )
        require("FOLLOWUP_RECORDED" in audit_types, f"followup audit event missing: {audit_events}")
        require("OUTCOME_RECORDED" in audit_types, f"outcome audit event missing: {audit_events}")
        require(all(event.get("sensitive_values_redacted") is True for event in audit_events), f"audit redaction flag missing: {audit_events}")

    finally:
        for path, backup in backups.items():
            if backup is None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            else:
                path.write_text(backup)

    print("Validated V32 decision journaling and outcomes tracking.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
