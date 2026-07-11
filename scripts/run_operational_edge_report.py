#!/usr/bin/env python3
"""Generate the V32 operational edge report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import operational_edge


DEFAULT_OUT = ROOT / "runtime" / "v32_operational_edge_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stock Ultimus V32 operational edge report.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--recent-days", type=int, default=14)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--preview", type=int, default=5)
    return parser.parse_args()


def print_summary(payload: dict, preview: int) -> None:
    print("Stock Ultimus Operational Edge")
    print(
        "Version: {version} | score={score} | status={status}".format(
            version=payload.get("operational_edge_version"),
            score=payload.get("overall_edge_score"),
            status=payload.get("overall_status"),
        )
    )
    print("Target:", payload.get("target"))

    print("\nCapabilities:")
    for key, item in (payload.get("capabilities") or {}).items():
        print("- {key}: {status} score={score}".format(
            key=key,
            status=item.get("status"),
            score=item.get("score"),
        ))

    print("\nBest opportunities:")
    for row in ((payload.get("summary") or {}).get("best_opportunities") or [])[:preview]:
        print(
            "- {ticker} {strategy} state={state} score={score} blocker={blocker}".format(
                ticker=row.get("ticker"),
                strategy=row.get("strategy"),
                state=row.get("final_state"),
                score=row.get("institutional_score"),
                blocker=row.get("main_blocker"),
            )
        )

    print("\nBest contracts:")
    for row in ((payload.get("summary") or {}).get("best_contracts") or [])[:preview]:
        print(
            "- {ticker} {strategy} {expiration} {strike} dte={dte} delta={delta} spread={spread} score={score}".format(
                ticker=row.get("ticker"),
                strategy=row.get("strategy"),
                expiration=row.get("expiration"),
                strike=row.get("strike"),
                dte=row.get("dte"),
                delta=row.get("delta"),
                spread=row.get("spread_pct"),
                score=row.get("contract_score"),
            )
        )

    print("\nRecommended sequence:")
    for item in payload.get("recommended_sequence") or []:
        print("-", item)

    print("\nManual review only. No autoriza ordenes.")


def main() -> int:
    args = parse_args()
    payload = operational_edge.build_operational_edge_report(
        Path(args.runtime_dir),
        recent_days=args.recent_days,
        top_limit=args.top,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print_summary(payload, args.preview)
    print(f"\nJSON: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
