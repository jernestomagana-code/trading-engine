#!/usr/bin/env python3
"""Daily dry-run review of Stock Ultimus outcomes.

This operator helper summarizes the V32 decision/outcome journals and highlights
records that still need manual follow-up. It never places orders.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate daily Stock Ultimus outcomes.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect journals without writing anything.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum pending decisions to show.")
    return parser.parse_args()


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_outcome_eval", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def safe_upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def outcome_key(item: dict[str, Any]) -> str | None:
    value = item.get("decision_id") or item.get("id")
    return str(value) if value else None


def build_evaluation(app, *, limit: int) -> dict[str, Any]:
    decisions = app._v32_load_decision_journal()
    outcomes = app._v32_load_outcomes_journal()
    performance = app._v32_strategy_performance_payload(decisions, outcomes)
    closed_outcomes = {"WIN", "LOSS", "BREAKEVEN", "EXPIRED", "CANCELLED"}
    outcome_ids = {outcome_key(item) for item in outcomes if outcome_key(item)}

    open_decisions = [
        item for item in decisions
        if outcome_key(item) and outcome_key(item) not in outcome_ids
    ]
    entry_ready_open = [
        item for item in open_decisions
        if safe_upper(item.get("final_state")) == "ENTRY_READY"
    ]
    closed = [
        item for item in outcomes
        if safe_upper(item.get("outcome")) in closed_outcomes
    ]
    pending_preview = []
    for item in open_decisions[-max(1, limit):]:
        pending_preview.append({
            "decision_id": outcome_key(item),
            "ticker": item.get("ticker"),
            "strategy": item.get("strategy"),
            "final_state": item.get("final_state"),
            "generated_at": item.get("generated_at"),
            "main_blocker": item.get("main_blocker"),
            "next_required_action": item.get("next_required_action"),
        })

    return {
        "engine": "DAILY_OUTCOME_EVALUATION",
        "evaluation_version": "daily_outcome_evaluation_v1",
        "mode": "dry_run",
        "summary": {
            "decisions": len(decisions),
            "outcomes": len(outcomes),
            "closed_outcomes": len(closed),
            "open_decisions_without_outcome": len(open_decisions),
            "entry_ready_open_without_outcome": len(entry_ready_open),
        },
        "pending_manual_followup": pending_preview,
        "strategy_performance": {
            "strategy_performance_version": performance.get("strategy_performance_version"),
            "summary": performance.get("summary"),
            "review_policy": performance.get("review_policy"),
        },
        "next_required_actions": [
            "Registrar follow-up u outcome solo despues de revision manual.",
            "Usar /v32_record_followup o /v32_record_outcome para evidencia, no para operar.",
            "Revisar parametros solo cuando exista muestra suficiente y regla versionada.",
        ],
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def print_human(payload: dict[str, Any]) -> None:
    summary = payload.get("summary") or {}
    print("Stock Ultimus daily outcome evaluation")
    print(f"Modo: {payload.get('mode')}")
    print(
        "Resumen: "
        f"decisions={summary.get('decisions')} | outcomes={summary.get('outcomes')} | "
        f"closed={summary.get('closed_outcomes')} | pending={summary.get('open_decisions_without_outcome')}"
    )
    print(f"ENTRY_READY pendientes de outcome: {summary.get('entry_ready_open_without_outcome')}")
    print("\nPendientes manuales:")
    for item in payload.get("pending_manual_followup") or []:
        print(
            "- "
            f"{item.get('ticker')} | {item.get('strategy')} | {item.get('final_state')} | "
            f"decision_id={item.get('decision_id')} | next={item.get('next_required_action')}"
        )
    if not payload.get("pending_manual_followup"):
        print("- Sin pendientes detectados.")
    print("\nSiguientes acciones:")
    for action in payload.get("next_required_actions") or []:
        print(f"- {action}")
    print("\nNota: esto no autoriza ordenes; toda ejecucion es manual.")


def main() -> int:
    args = parse_args()
    if not args.dry_run:
        print("Por seguridad, este comando requiere --dry-run.", file=sys.stderr)
        return 2
    app = load_app_module()
    payload = build_evaluation(app, limit=args.limit)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
