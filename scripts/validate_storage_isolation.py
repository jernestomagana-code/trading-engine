#!/usr/bin/env python3
"""Validate storage durability and tenant/account isolation gates."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import storage_isolation  # noqa: E402


FIXTURE = ROOT / "fixtures" / "storage_isolation_cases.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    fixture = json.loads(FIXTURE.read_text())
    require(
        fixture.get("fixture_version") == "storage_isolation_cases_v1",
        f"unexpected storage isolation fixture version: {fixture}",
    )
    for case in fixture.get("cases") or []:
        result = storage_isolation.assess(case.get("config") or {})
        expected = case.get("expected") or {}
        require(result.get("isolation_version") == storage_isolation.ISOLATION_VERSION, f"{case.get('name')} wrong version: {result}")
        for key, expected_value in expected.items():
            if key == "expected_blockers":
                blocker_names = {item.get("name") for item in result.get("blockers") or []}
                for blocker in expected_value:
                    require(blocker in blocker_names, f"{case.get('name')} missing blocker {blocker}: {result}")
            else:
                require(result.get(key) == expected_value, f"{case.get('name')} wrong {key}: expected {expected_value}, got {result.get(key)}")
        require(result.get("execution_authorized") is False, f"{case.get('name')} must not authorize execution: {result}")
        require(result.get("not_order_instruction") is True, f"{case.get('name')} must preserve no-order flag: {result}")
        require(result.get("sensitive_values_excluded") is True, f"{case.get('name')} must preserve redaction flag: {result}")

    print("Validated storage durability and tenant/account isolation gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
