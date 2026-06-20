#!/usr/bin/env python3
"""Validate production readiness gates do not expose secrets or allow unsafe modes."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import production_readiness  # noqa: E402


FIXTURE = ROOT / "fixtures" / "production_readiness_cases.json"
SENSITIVE_RESPONSE_KEYS = {
    "snapshot_ingest_token",
    "webhook_secret",
    "resend_api_key",
    "supabase_key",
    "admin_debug_token",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def scan_no_sensitive_keys(value, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            require(key_text not in SENSITIVE_RESPONSE_KEYS, f"sensitive key exposed at {path}.{key}")
            scan_no_sensitive_keys(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            scan_no_sensitive_keys(item, f"{path}[{idx}]")


def validate_case(case: dict) -> None:
    result = production_readiness.assess(case.get("config") or {})
    require(
        result.get("readiness_version") == production_readiness.READINESS_VERSION,
        f"{case.get('name')} wrong readiness version: {result}",
    )
    require(result.get("status") == case.get("expected_status"), f"{case.get('name')} wrong status: {result}")
    require(result.get("execution_authorized") is False, f"{case.get('name')} must not authorize execution: {result}")
    require(result.get("not_order_instruction") is True, f"{case.get('name')} must preserve no-order flag: {result}")
    require(result.get("sensitive_values_excluded") is True, f"{case.get('name')} must flag redaction: {result}")
    scan_no_sensitive_keys(result)

    blocker_names = {item.get("name") for item in result.get("blockers") or []}
    for expected in case.get("expected_blockers") or []:
        require(expected in blocker_names, f"{case.get('name')} missing blocker {expected}: {result}")


def main() -> int:
    fixture = json.loads(FIXTURE.read_text())
    require(
        fixture.get("fixture_version") == "production_readiness_cases_v1",
        f"unexpected production readiness fixture version: {fixture}",
    )
    for case in fixture.get("cases") or []:
        validate_case(case)
    print("Validated production readiness gates and redaction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
