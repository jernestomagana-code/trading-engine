#!/usr/bin/env python3
"""Collect WSH earnings and long-dated SPY/RSP option evidence read-only."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ib_insync import IB


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ibkr_premium_research_collector as collector
import premium_strategy_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("IBKR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("IBKR_PORT", "7496")))
    parser.add_argument("--client-id", type=int, default=94)
    parser.add_argument("--runtime-dir", default=os.getenv("STOCK_ULTIMUS_RUNTIME_DIR", str(ROOT / "runtime")))
    parser.add_argument("--days-ahead", type=int, default=60)
    parser.add_argument("--wait-seconds", type=float, default=8)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--skip-earnings", action="store_true")
    parser.add_argument("--skip-long-dated", action="store_true")
    return parser.parse_args()


def canslim_tickers(runtime_dir: Path) -> list[str]:
    try:
        payload = json.loads((runtime_dir / "canslim_candidates_latest.json").read_text())
    except Exception:
        return []
    return [
        str(row.get("ticker") or "").upper()
        for row in payload.get("candidates") or []
        if isinstance(row, dict) and row.get("canslim_passes") is True
        and float(row.get("canslim_component_coverage_pct") or 0) >= 85
        and row.get("ticker")
    ]


def main() -> int:
    args = parse_args()
    runtime = Path(args.runtime_dir)
    result = {
        "collector_version": collector.COLLECTOR_VERSION,
        "generated_at": premium_strategy_data.now_iso(),
        "readonly": True,
        "mode": "RESEARCH_PAPER_ONLY",
        "not_order_instruction": True,
        "execution_authorized": False,
    }
    ib = IB()
    errors = []
    ib.errorEvent += lambda request_id, code, message, contract: errors.append({"code": code, "message": str(message)[:250]})
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, readonly=True, timeout=args.timeout)
        ib.RequestTimeout = max(2, args.timeout)
        if not args.skip_long_dated:
            long_dated = collector.collect_long_dated_puts(ib, ("SPY", "RSP"), args.wait_seconds)
            long_store = premium_strategy_data.append_observations(
                runtime / "premium_research_option_observations.jsonl",
                long_dated["records"],
                "option_observation",
            )
            result["long_dated"] = {**long_dated, "store": long_store}
        if not args.skip_earnings:
            today = datetime.now(timezone.utc).date()
            earnings = collector.collect_earnings_calendar(
                ib,
                canslim_tickers(runtime),
                today.strftime("%Y%m%d"),
                (today + timedelta(days=max(1, args.days_ahead))).strftime("%Y%m%d"),
            )
            earnings_store = premium_strategy_data.append_observations(
                runtime / "premium_research_earnings_events.jsonl",
                earnings["events"],
                "earnings_event",
            )
            result["earnings"] = {**earnings, "store": earnings_store}
            (runtime / "premium_research_wsh_status.json").write_text(json.dumps({
                "checked_at": premium_strategy_data.now_iso(),
                "metadata_available": earnings.get("metadata_available") is True,
                "blocker": earnings.get("blocker"),
                "detail": earnings.get("detail"),
                "not_order_instruction": True,
                "execution_authorized": False,
            }, indent=2, sort_keys=True) + "\n")
        result["readiness"] = premium_strategy_data.write_readiness(runtime)
        expected = []
        if not args.skip_long_dated:
            expected.append(bool((result.get("long_dated") or {}).get("records")))
        if not args.skip_earnings:
            earnings_result = result.get("earnings") or {}
            expected.append(bool(earnings_result.get("events")) or bool(earnings_result.get("metadata_available")))
        result["ok"] = all(expected) if expected else True
        result["status"] = "COLLECTION_COMPLETE" if result["ok"] else "COLLECTION_PARTIAL"
    except Exception as exc:
        result.update({"status": "COLLECTION_FAILED", "ok": False, "error": exc.__class__.__name__, "detail": str(exc)[:500]})
    finally:
        if ib.isConnected():
            ib.disconnect()
    result["ibkr_errors"] = errors[-30:]
    output = runtime / "premium_research_ibkr_collection_latest.json"
    try:
        output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    except OSError:
        pass
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
