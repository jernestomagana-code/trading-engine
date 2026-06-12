#!/usr/bin/env python3
"""Validate that runtime fixtures do not contain obvious sensitive data."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "runtime"
SENSITIVE_KEY_RE = re.compile(
    r"(account|acct|balance|buying_power|cash|credential|secret|token|password|api[_-]?key|authorization|cookie|session|net_liquidation|local_path|home_dir)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = {
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    "ibkr_account": re.compile(r"\bDU\d{4,}\b"),
    "user_account": re.compile(r"\bU\d{6,}\b"),
    "long_numeric_identifier": re.compile(r"\b\d{8,}\b"),
    "sensitive_url": re.compile(r"https?://[^\s\"']*(render\.com|supabase\.co)[^\s\"']*", re.IGNORECASE),
    "local_path": re.compile(r"(/[Uu]sers/|/home/|[A-Za-z]:\\)"),
}


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def scan_value(value, path: Path, pointer: str, failures: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            next_pointer = f"{pointer}.{key}" if pointer else str(key)
            if SENSITIVE_KEY_RE.search(str(key)):
                failures.append(f"{rel(path)}:{next_pointer}: sensitive key is not allowed")
            scan_value(item, path, next_pointer, failures)
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            scan_value(item, path, f"{pointer}[{index}]", failures)
        return

    if isinstance(value, str):
        for name, pattern in SENSITIVE_VALUE_PATTERNS.items():
            if pattern.search(value):
                failures.append(f"{rel(path)}:{pointer}: sensitive value pattern {name}")


def validate_file(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{rel(path)}: invalid JSON: {exc}"]

    failures: list[str] = []
    scan_value(data, path, "", failures)
    return failures


def main() -> int:
    failures: list[str] = []
    paths = sorted(FIXTURE_DIR.glob("**/*.json"))
    for path in paths:
        failures.extend(validate_file(path))

    if failures:
        print("\n".join(failures))
        return 1

    print(f"Validated runtime fixture privacy for {len(paths)} JSON files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
