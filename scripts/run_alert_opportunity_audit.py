#!/usr/bin/env python3
"""Run the Stock Ultimus alert/opportunity deep audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import alert_opportunity_audit


DEFAULT_JSON_OUT = ROOT / "runtime" / "alert_opportunity_deep_audit_latest.json"
DEFAULT_CSV_OUT = ROOT / "runtime" / "alert_opportunity_missed_opportunities_latest.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Stock Ultimus alert/opportunity coverage audit.")
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_OUT))
    parser.add_argument("--preview", type=int, default=10)
    parser.add_argument("--recent-days", type=int, default=14)
    return parser.parse_args()


def print_summary(payload: dict, preview: int) -> None:
    summary = payload.get("summary") or {}
    data_quality = payload.get("data_quality") or {}
    freshness = payload.get("freshness") or {}
    print("Stock Ultimus Alert Opportunity Audit")
    print(f"Version: {payload.get('audit_version')} | generated_at={payload.get('generated_at')}")
    print(
        "Decisions={decisions} | ENTRY_READY={entry} | blocked/waiting={blocked} | outcomes={outcomes} | closed={closed}".format(
            decisions=summary.get("decision_count"),
            entry=summary.get("entry_ready_count"),
            blocked=summary.get("blocked_or_waiting_count"),
            outcomes=summary.get("outcome_count"),
            closed=summary.get("closed_outcome_count"),
        )
    )
    print(f"Primary gap: {data_quality.get('primary_gap')}")
    print(f"Unknown source decisions: {data_quality.get('unknown_source_decisions')} ({data_quality.get('unknown_source_pct')}%)")
    print(
        "Recent window: {days}d | recent={recent} | historical={historical} | recent ENTRY_READY={entry}".format(
            days=freshness.get("recent_days"),
            recent=freshness.get("recent_decision_count"),
            historical=freshness.get("historical_decision_count"),
            entry=freshness.get("recent_entry_ready_count"),
        )
    )
    print(f"Undated decisions: {freshness.get('undated_decision_count')}")
    print(f"State counts: {summary.get('state_counts')}")
    print(f"Blocker counts: {summary.get('blocker_counts')}")
    print(f"Source counts: {summary.get('source_counts')}")

    print("\nStrategy coverage:")
    for row in (payload.get("strategy_coverage") or [])[:preview]:
        print(
            "- {strategy}: decisions={decisions}, entry_ready={entry}, closed_outcomes={closed}, review_ready={ready}".format(
                strategy=row.get("strategy"),
                decisions=row.get("decision_count"),
                entry=row.get("entry_ready_count"),
                closed=row.get("closed_outcomes"),
                ready=row.get("parameter_review_ready"),
            )
        )

    print("\nRecommendations:")
    for item in payload.get("recommendations") or []:
        print(f"- {item}")

    missed = payload.get("missed_opportunity_review") or []
    if missed:
        print("\nMissed/opportunity review preview:")
        for row in missed[:preview]:
            print(
                "- {ticker} {strategy} {state} blocker={blocker} source={source}: {question}".format(
                    ticker=row.get("ticker"),
                    strategy=row.get("strategy"),
                    state=row.get("final_state"),
                    blocker=row.get("main_blocker"),
                    source=row.get("signal_source"),
                    question=row.get("audit_question"),
                )
            )

    print("\nManual review only. This audit does not authorize orders.")


def main() -> int:
    args = parse_args()
    runtime_dir = Path(args.runtime_dir)
    payload = alert_opportunity_audit.build_alert_opportunity_audit(runtime_dir, recent_days=args.recent_days)

    json_out = Path(args.json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    csv_out = Path(args.csv_out)
    alert_opportunity_audit.write_csv(csv_out, payload.get("missed_opportunity_review") or [])

    print_summary(payload, args.preview)
    print(f"\nJSON: {json_out}")
    print(f"CSV: {csv_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
