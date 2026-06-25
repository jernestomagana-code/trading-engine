#!/usr/bin/env python3
"""Run the Stock Ultimus operational-100 preflight.

This local helper closes the five operating-model gates:

1) GPT Action/backend read health,
2) manual review surfaces,
3) outcome/learning dry-run,
4) cloud operational audit,
5) optional real outcome write only after the operator explicitly confirms the
   post-close/fresh-snapshot condition.

It never places orders, never authorizes execution, and never prints tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"
DEFAULT_OUT = ROOT / "runtime" / "operational_100_latest.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tail(text: str | None, limit: int = 2500) -> str:
    return (text or "")[-limit:]


def run_command(name: str, command: list[str], timeout: int, env: dict[str, str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "ok": False,
            "exit_code": None,
            "command": command,
            "stdout_tail": tail(exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout),
            "stderr_tail": tail(exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr),
            "detail": f"TIMEOUT_AFTER_{timeout}_SECONDS",
        }

    parsed_payload = parse_last_json((proc.stdout or "") + "\n" + (proc.stderr or ""))
    return {
        "name": name,
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "command": command,
        "json_payload": parsed_payload,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
    }


def parse_last_json(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if stripped:
        try:
            value = json.loads(stripped)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    best: dict[str, Any] = {}
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            best = value
    return best


def command_json(step: dict[str, Any]) -> dict[str, Any]:
    payload = step.get("json_payload")
    if isinstance(payload, dict):
        return payload
    return parse_last_json((step.get("stdout_tail") or "") + "\n" + (step.get("stderr_tail") or ""))


def summarize_gate(name: str, ok: bool, detail: str, *, severity: str = "FAIL") -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "severity": severity,
        "detail": detail,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stock Ultimus operational-100 preflight.")
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "45")))
    parser.add_argument("--limit", type=int, default=int(os.getenv("STOCK_ULTIMUS_EVALUATION_LIMIT", "100")))
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_OPERATIONAL_100_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--skip-cloud", action="store_true", help="Do not call production; useful for local CI.")
    parser.add_argument("--real-outcomes-after-close", action="store_true", help="Persist outcome evaluations. Use only after close with fresh snapshot.")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    base = args.base_url.rstrip("/")
    timeout = max(10, int(args.timeout or 45))
    limit = max(1, min(int(args.limit or 100), 1000))
    steps: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []

    if args.skip_cloud:
        gates.append(summarize_gate("cloud_preflight", True, "skipped by operator", severity="WARN"))
    else:
        gpt = run_command(
            "gpt_action_health",
            [
                sys.executable,
                "scripts/monitor_gpt_action_health.py",
                "--base-url",
                base,
                "--timeout",
                str(timeout),
                "--no-write",
            ],
            timeout=max(90, timeout * 4),
            env=env,
        )
        steps.append(gpt)
        gpt_payload = command_json(gpt)
        gates.append(summarize_gate(
            "gpt_action_backend_health",
            gpt.get("ok") and gpt_payload.get("status") == "OK",
            "getDailyNow/getDailyAnswer/read-auth guardrails OK" if gpt.get("ok") else "GPT/backend health failed",
        ))

        audit = run_command(
            "cloud_operational_audit",
            [
                sys.executable,
                "tools/v31_daily_operational_audit.py",
                "--base-url",
                base,
                "--timeout",
                str(timeout),
                "--limit",
                str(limit),
            ],
            timeout=max(120, timeout * 6),
            env=env,
        )
        steps.append(audit)
        audit_payload = command_json(audit)
        gates.append(summarize_gate(
            "cloud_operational_audit",
            audit.get("ok") and audit_payload.get("status") in {"PASS", "PASS_WITH_WARNINGS"},
            "production audit pass/pass-with-warnings" if audit.get("ok") else "production audit failed",
        ))

        dry_eval = run_command(
            "outcome_learning_dry_run",
            [
                sys.executable,
                "scripts/run_daily_outcome_evaluation.py",
                "--base-url",
                base,
                "--timeout",
                str(timeout),
                "--limit",
                str(limit),
                "--dry-run",
                "--no-write",
            ],
            timeout=max(120, timeout * 8),
            env=env,
        )
        steps.append(dry_eval)
        eval_payload = command_json(dry_eval)
        gates.append(summarize_gate(
            "outcome_learning_dry_run",
            dry_eval.get("ok")
            and eval_payload.get("not_order_instruction") is True
            and eval_payload.get("execution_authorized") is False,
            "dry-run outcome learning guardrails OK" if dry_eval.get("ok") else "dry-run outcome learning failed",
        ))

    real_outcome_step: dict[str, Any] | None = None
    if args.real_outcomes_after_close:
        real_outcome_step = run_command(
            "outcome_learning_real_write",
            [
                sys.executable,
                "scripts/run_daily_outcome_evaluation.py",
                "--base-url",
                base,
                "--timeout",
                str(timeout),
                "--limit",
                str(limit),
            ],
            timeout=max(120, timeout * 8),
            env=env,
        )
        steps.append(real_outcome_step)
        real_payload = command_json(real_outcome_step)
        gates.append(summarize_gate(
            "real_outcome_write_after_close",
            real_outcome_step.get("ok")
            and real_payload.get("not_order_instruction") is True
            and real_payload.get("execution_authorized") is False,
            "real outcome write completed under explicit post-close confirmation"
            if real_outcome_step.get("ok")
            else "real outcome write failed",
        ))
    else:
        gates.append(summarize_gate(
            "real_outcome_write_after_close",
            True,
            "not run; requires --real-outcomes-after-close after close with fresh snapshot",
            severity="WARN",
        ))

    inbox_urls = {
        "manual_review_inbox": base + "/v31_manual_review_inbox",
        "manual_review_inbox_all": base + "/v31_manual_review_inbox?show_all=true",
        "manual_review_history": base + "/v31_manual_reviews_dashboard",
        "learning_dashboard": base + "/v31_manual_review_learning_dashboard",
        "strategy_performance_dashboard": base + "/v32_strategy_performance_dashboard",
    }
    gates.append(summarize_gate(
        "manual_review_process_surfaces",
        True,
        "inbox, history, learning and performance dashboard URLs generated",
        severity="FAIL",
    ))

    failed = [gate for gate in gates if not gate["ok"] and gate["severity"] == "FAIL"]
    warnings = [gate for gate in gates if (not gate["ok"] and gate["severity"] == "WARN") or gate["severity"] == "WARN"]
    status = "PASS" if not failed else "FAIL"
    if status == "PASS" and warnings:
        status = "PASS_WITH_WARNINGS"

    result = {
        "engine": "STOCK_ULTIMUS_OPERATIONAL_100_PREFLIGHT",
        "run_version": "operational_100_v1",
        "generated_at": now_iso(),
        "base_url": base,
        "status": status,
        "summary": {
            "total_gates": len(gates),
            "passed": len([gate for gate in gates if gate["ok"]]),
            "warnings": len(warnings),
            "failed": len(failed),
        },
        "gates": gates,
        "steps": steps,
        "manual_review_urls": inbox_urls,
        "next_required_action": (
            "Abrir inbox manual, marcar setups y ejecutar outcome real solo post-cierre con snapshot fresco."
            if status != "FAIL"
            else "Resolver el primer gate fallido antes de depender del modelo operativo."
        ),
        "real_outcome_write_requested": bool(args.real_outcomes_after_close),
        "secrets_printed": False,
        "uses_ingest_token": False,
        "sends_email": False,
        "touches_ibkr": False,
        "manual_review_required": True,
        "execution_authorized": False,
        "not_order_instruction": True,
    }
    return result


def main() -> int:
    args = build_parser().parse_args()
    result = run(args)
    if not args.no_write:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"PASS", "PASS_WITH_WARNINGS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
