#!/usr/bin/env python3
"""Collect the free earnings calendar for current CANSLIM candidates."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import alpha_vantage_earnings
import premium_strategy_data

KEYCHAIN_SERVICE = "stock-ultimus-alpha-vantage-api-key"


def api_key() -> str:
    value = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
    if value:
        return value
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", os.getenv("USER", ""), "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def tickers(runtime: Path) -> list[str]:
    try:
        payload = json.loads((runtime / "canslim_candidates_latest.json").read_text())
    except Exception:
        return []
    return sorted({
        str(row.get("ticker") or "").upper()
        for row in payload.get("candidates") or []
        if isinstance(row, dict) and row.get("ticker")
        and row.get("canslim_passes") is True
        and float(row.get("canslim_component_coverage_pct") or 0) >= 85
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", default=str(ROOT / "runtime"))
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    runtime = Path(args.runtime_dir)
    symbols = tickers(runtime)
    key = api_key()
    status = {
        "checked_at": premium_strategy_data.now_iso(), "provider": alpha_vantage_earnings.PROVIDER,
        "configured": bool(key), "candidate_count": len(symbols), "optional_wsh": True,
        "not_order_instruction": True, "execution_authorized": False,
    }
    result: dict = {"ok": False, **status}
    try:
        if not key:
            raise RuntimeError("FREE_API_KEY_NOT_CONFIGURED")
        if not symbols:
            raise RuntimeError("NO_FULL_CANSLIM_CANDIDATES")
        collected = alpha_vantage_earnings.fetch_calendar(key, symbols, timeout=args.timeout)
        store = premium_strategy_data.append_observations(
            runtime / "premium_research_earnings_events.jsonl", collected["events"], "earnings_event"
        )
        result.update({"ok": True, "status": "COLLECTION_COMPLETE", "event_count": len(collected["events"]), "store": store})
    except Exception as exc:
        result.update({"status": "COLLECTION_PENDING", "reason": str(exc)[:200]})
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "premium_research_earnings_provider_status.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    premium_strategy_data.write_readiness(runtime)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
