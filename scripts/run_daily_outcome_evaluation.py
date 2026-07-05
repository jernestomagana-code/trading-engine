#!/usr/bin/env python3
"""Run the daily Stock Ultimus outcome evaluation cycle.

This is a local operator helper. It calls protected read/evaluation endpoints
with the read token, records no secrets, and never touches IBKR or order paths.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC_BASE_URL = "https://trading-engine-p097.onrender.com"
READ_KEYCHAIN_SERVICE = "stock-ultimus-read-access-token"
DEFAULT_OUT = ROOT / "runtime" / "daily_outcome_evaluation_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate V31 pending outcomes and manual reviews.")
    parser.add_argument("--base-url", default=os.getenv("PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL))
    parser.add_argument(
        "--token",
        default=(
            os.getenv("READ_ACCESS_TOKEN")
            or os.getenv("STOCK_ULTIMUS_READ_TOKEN")
            or os.getenv("STOCK_ULTIMUS_READ_ACCESS_TOKEN")
            or ""
        ),
    )
    parser.add_argument("--checkpoints", default=os.getenv("STOCK_ULTIMUS_EVALUATION_CHECKPOINTS", "EOD,PLUS_1D,PLUS_5D"))
    parser.add_argument("--limit", type=int, default=int(os.getenv("STOCK_ULTIMUS_EVALUATION_LIMIT", "100")))
    parser.add_argument("--dry-run", action="store_true", help="Preview without persisting evaluation updates.")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("STOCK_ULTIMUS_READ_TIMEOUT", "45")))
    parser.add_argument("--json-out", default=os.getenv("STOCK_ULTIMUS_DAILY_EVAL_OUT", str(DEFAULT_OUT)))
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def keychain_password(service: str) -> str | None:
    user = os.getenv("USER") or ""
    if not user:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", user, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def request_json(url: str, token: str, timeout: int, method: str = "GET") -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=b"" if method == "POST" else None,
        method=method,
        headers={
            "Accept": "application/json",
            "X-Stock-Ultimus-Read-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:500]}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"detail": str(exc)}


def compact_eval_payload(endpoint: str, checkpoint: str, status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "checkpoint": checkpoint,
        "http_status": status_code,
        "engine": payload.get("engine"),
        "status": payload.get("status"),
        "dry_run": payload.get("dry_run"),
        "found": payload.get("pending_found") or payload.get("manual_reviews_found"),
        "evaluated_count": payload.get("evaluated_count"),
        "not_evaluated_count": payload.get("not_evaluated_count"),
        "saved_count": payload.get("saved_count"),
        "not_order_instruction": payload.get("not_order_instruction"),
        "execution_authorized": payload.get("execution_authorized"),
    }


def main() -> int:
    args = parse_args()
    token = args.token or keychain_password(READ_KEYCHAIN_SERVICE)
    if not token:
        print("Falta READ_ACCESS_TOKEN o token Keychain de lectura.", file=sys.stderr)
        return 2

    base = args.base_url.rstrip("/")
    checkpoints = [item.strip().upper() for item in args.checkpoints.split(",") if item.strip()]
    limit = max(1, min(int(args.limit or 100), 1000))
    dry_run = "true" if args.dry_run else "false"
    evaluations = []

    for checkpoint in checkpoints:
        query = urllib.parse.urlencode({"limit": limit, "checkpoint": checkpoint, "dry_run": dry_run})
        for endpoint in ["/v31_evaluate_pending_outcomes", "/v31_evaluate_manual_reviews"]:
            status_code, payload = request_json(f"{base}{endpoint}?{query}", token, args.timeout, method="POST")
            summary = compact_eval_payload(endpoint, checkpoint, status_code, payload)
            evaluations.append(summary)
            if status_code != 200:
                print(json.dumps(summary, indent=2, sort_keys=True), file=sys.stderr)
                return 1
            if payload.get("not_order_instruction") is not True or payload.get("execution_authorized") is not False:
                print("Guardrail failed for {endpoint} {checkpoint}".format(endpoint=endpoint, checkpoint=checkpoint), file=sys.stderr)
                return 1

    perf_status, perf = request_json(f"{base}/v32_strategy_performance", token, args.timeout)
    learning_status, learning = request_json(f"{base}/v31_manual_review_learning", token, args.timeout)
    answer_status, answer = request_json(f"{base}/gpt_v31_daily_answer?limit=3", token, args.timeout)
    result = {
        "engine": "LOCAL_DAILY_OUTCOME_EVALUATION_RUNNER",
        "run_version": "daily_outcome_evaluation_v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "dry_run": args.dry_run,
        "checkpoints": checkpoints,
        "evaluations": evaluations,
        "strategy_performance": {
            "http_status": perf_status,
            "engine": perf.get("engine"),
            "summary": perf.get("summary") or {},
            "execution_authorized": perf.get("execution_authorized"),
            "not_order_instruction": perf.get("not_order_instruction"),
        },
        "manual_review_learning": {
            "http_status": learning_status,
            "engine": learning.get("engine"),
            "evaluated_count": learning.get("evaluated_count"),
            "needs_more_data": learning.get("needs_more_data"),
            "execution_authorized": learning.get("execution_authorized"),
            "not_order_instruction": learning.get("not_order_instruction"),
        },
        "gpt_daily_answer": {
            "http_status": answer_status,
            "engine": answer.get("engine"),
            "answer_version": answer.get("answer_version"),
            "execution_authorized": answer.get("execution_authorized"),
            "not_order_instruction": answer.get("not_order_instruction"),
        },
        "execution_authorized": False,
        "not_order_instruction": True,
    }

    if not args.no_write:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
