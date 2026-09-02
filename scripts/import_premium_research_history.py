#!/usr/bin/env python3
"""Import licensed or operator-provided research history with validation."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import premium_strategy_data


STORE_NAMES = {
    "earnings_event": "premium_research_earnings_events.jsonl",
    "option_observation": "premium_research_option_observations.jsonl",
    "expired_option_observation": "premium_research_expired_option_backfill.jsonl",
    "underlying_observation": "premium_research_underlying_observations.jsonl",
}


def load_records(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    payload = path.read_text()
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in payload.splitlines() if line.strip()]
    decoded = json.loads(payload)
    if isinstance(decoded, list):
        return [row for row in decoded if isinstance(row, dict)]
    if isinstance(decoded, dict) and isinstance(decoded.get("records"), list):
        return [row for row in decoded["records"] if isinstance(row, dict)]
    raise ValueError("Expected CSV, JSON list/records, or JSONL")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--record-type", required=True, choices=sorted(STORE_NAMES))
    parser.add_argument("--runtime-dir", default=os.getenv("STOCK_ULTIMUS_RUNTIME_DIR", str(ROOT / "runtime")))
    parser.add_argument("--source", required=True, help="Licensed dataset or export name; saved on every imported row")
    args = parser.parse_args()
    records = load_records(Path(args.input))
    for row in records:
        row["source"] = args.source
    validation_type = "option_observation" if args.record_type == "expired_option_observation" else args.record_type
    runtime = Path(args.runtime_dir)
    result = premium_strategy_data.append_observations(runtime / STORE_NAMES[args.record_type], records, validation_type)
    result.update({
        "record_type": args.record_type,
        "source": args.source,
        "input_rows": len(records),
        "not_order_instruction": True,
        "execution_authorized": False,
    })
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result["rejected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
