#!/usr/bin/env python3
"""Build free CANSLIM candidates from SEC companyfacts and local runtime bars."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import canslim_free_engine as engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build free Stock Ultimus CANSLIM candidates.")
    parser.add_argument("--runtime-dir", default=os.getenv("STOCK_ULTIMUS_RUNTIME_DIR", "runtime"))
    parser.add_argument("--output", default=str(engine.DEFAULT_OUTPUT))
    parser.add_argument("--sec-cache-dir", default=str(engine.DEFAULT_SEC_CACHE))
    parser.add_argument("--universe", default=os.getenv("CANSLIM_UNIVERSE") or os.getenv("IBKR_OPTION_SYMBOLS") or "")
    parser.add_argument("--max-symbols", type=int, default=int(os.getenv("CANSLIM_MAX_SYMBOLS", "50")))
    parser.add_argument("--minimum-score", type=float, default=float(os.getenv("CANSLIM_MIN_SCORE", "70")))
    parser.add_argument("--refresh-sec", action="store_true", help="Refresh SEC cache instead of using cached JSON.")
    parser.add_argument("--sec-user-agent", default=engine.sec_user_agent())
    parser.add_argument("--timeout", type=int, default=int(os.getenv("CANSLIM_SEC_TIMEOUT_SECONDS", "20")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_dir = Path(args.runtime_dir)
    cache_dir = Path(args.sec_cache_dir)
    output = Path(args.output)
    universe = engine.parse_universe(args.universe)[: max(1, args.max_symbols)]
    runtime_data = engine.load_runtime_jsons(runtime_dir)
    errors: dict[str, str] = {}

    try:
        ticker_map = engine.load_sec_ticker_map(
            cache_dir,
            user_agent=args.sec_user_agent,
            refresh=args.refresh_sec,
        )
    except Exception as exc:
        ticker_map = {}
        errors["_ticker_map"] = str(exc)

    companyfacts_by_ticker = {}
    for ticker in universe:
        if ticker in engine.NON_COMPANY_SYMBOLS:
            errors[ticker] = "NON_COMPANY_SYMBOL_SKIPPED"
            continue
        cik = ticker_map.get(ticker)
        if not cik:
            errors[ticker] = "NO_SEC_CIK"
            continue
        facts, error = engine.load_companyfacts(
            ticker,
            cik,
            cache_dir,
            user_agent=args.sec_user_agent,
            refresh=args.refresh_sec,
            timeout=args.timeout,
        )
        if error:
            errors[ticker] = error
            continue
        if facts:
            companyfacts_by_ticker[ticker] = facts

    payload = engine.build_payload(
        universe=universe,
        companyfacts_by_ticker=companyfacts_by_ticker,
        runtime_data=runtime_data,
        errors=errors,
        minimum_score=args.minimum_score,
    )
    engine.write_payload(payload, output)
    print(json.dumps({
        "status": "OK",
        "output": str(output),
        "candidate_count": payload.get("candidate_count"),
        "pass_count": payload.get("pass_count"),
        "errors": len(errors),
        "free_data_only": True,
        "not_order_instruction": True,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
