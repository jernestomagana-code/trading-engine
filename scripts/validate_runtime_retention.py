#!/usr/bin/env python3
"""Validate runtime retention policy bounds and trimming."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime_retention  # noqa: E402


FIXTURE = ROOT / "fixtures" / "runtime_retention_cases.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    fixture = json.loads(FIXTURE.read_text())
    require(
        fixture.get("fixture_version") == "runtime_retention_cases_v1",
        f"unexpected runtime retention fixture version: {fixture}",
    )
    for case in fixture.get("cases") or []:
        result = runtime_retention.policy(case.get("config") or {})
        expected = case.get("expected") or {}
        require(result.get("retention_policy_version") == runtime_retention.RETENTION_POLICY_VERSION, f"{case.get('name')} wrong version: {result}")
        for key, expected_value in expected.items():
            require(result.get(key) == expected_value, f"{case.get('name')} wrong {key}: expected {expected_value}, got {result.get(key)}")
        require(result.get("durable_storage_required_before_commercial") is True, f"{case.get('name')} must require durable storage before commercial use")
        require(result.get("sensitive_values_redacted") is True, f"{case.get('name')} must preserve redaction flag")

    trim_case = fixture.get("trim_case") or {}
    trimmed = runtime_retention.trim_items(trim_case.get("input_items") or [], trim_case.get("max_items"))
    require(trimmed == trim_case.get("expected_items"), f"trim result mismatch: {trimmed}")

    print("Validated runtime retention policy and trimming.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
