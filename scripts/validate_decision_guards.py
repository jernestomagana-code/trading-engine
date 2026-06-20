#!/usr/bin/env python3
"""Validate shared executable-contract and blocker-priority guards."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import decision_guards  # noqa: E402


FIXTURE = ROOT / "fixtures" / "v31" / "decision_guard_cases.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_executable_option_cases(fixture: dict) -> None:
    for case in fixture.get("executable_option_cases") or []:
        gate = decision_guards.executable_option_gate(case.get("row") or {})
        expected = case.get("expected") or {}
        require(
            gate.get("contract_version") == decision_guards.EXECUTABLE_OPTION_CONTRACT_VERSION,
            f"{case.get('name')} wrong contract version: {gate}",
        )
        require(
            gate.get("executable") == expected.get("executable"),
            f"{case.get('name')} executable mismatch: {gate}",
        )
        if "missing" in expected:
            require(
                gate.get("missing") == expected.get("missing"),
                f"{case.get('name')} missing mismatch: {gate}",
            )
        for field in expected.get("missing_contains") or []:
            require(field in (gate.get("missing") or []), f"{case.get('name')} should include missing {field}: {gate}")


def validate_blocker_priority_cases(fixture: dict) -> None:
    for case in fixture.get("blocker_priority_cases") or []:
        blockers = decision_guards.primary_blockers(
            case.get("final_state"),
            case.get("blocker"),
            case.get("risk_manual") or {},
            case.get("strategy_risk") or {},
        )
        require(
            blockers == case.get("expected_blockers"),
            f"{case.get('name')} blocker priority mismatch: expected {case.get('expected_blockers')}, got {blockers}",
        )


def main() -> int:
    fixture = json.loads(FIXTURE.read_text())
    require(
        fixture.get("fixture_version") == "v31_decision_guard_cases_v1",
        f"unexpected decision guard fixture version: {fixture}",
    )
    validate_executable_option_cases(fixture)
    validate_blocker_priority_cases(fixture)
    print("Validated shared decision guards for executable contracts and blocker priority.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
