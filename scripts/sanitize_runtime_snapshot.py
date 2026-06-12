#!/usr/bin/env python3
"""Sanitize runtime snapshots before adding them as fixtures."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SENSITIVE_KEY_RE = re.compile(
    r"(account|acct|balance|buying_power|cash|credential|secret|token|password|api[_-]?key|authorization|cookie|session|net_liquidation|local_path|home_dir)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\bDU\d{4,}\b"),
    re.compile(r"\bU\d{6,}\b"),
    re.compile(r"\b\d{8,}\b"),
    re.compile(r"https?://[^\s\"']*(render\.com|supabase\.co)[^\s\"']*", re.IGNORECASE),
    re.compile(r"(/[Uu]sers/|/home/|[A-Za-z]:\\)"),
]
REDACTED = "REDACTED"


def is_sensitive_key(key: object) -> bool:
    return isinstance(key, str) and bool(SENSITIVE_KEY_RE.search(key))


def sanitize_value(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if is_sensitive_key(key):
                sanitized[key] = REDACTED
            else:
                sanitized[key] = sanitize_value(item)
        return sanitized

    if isinstance(value, list):
        return [sanitize_value(item) for item in value]

    if isinstance(value, str):
        sanitized = value
        for pattern in SENSITIVE_VALUE_PATTERNS:
            sanitized = pattern.sub(REDACTED, sanitized)
        return sanitized

    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to a real runtime JSON snapshot.")
    parser.add_argument("output", type=Path, help="Path for the sanitized JSON fixture.")
    parser.add_argument("--force", action="store_true", help="Overwrite output if it already exists.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"Input does not exist: {args.input}")
        return 1
    if args.output.exists() and not args.force:
        print(f"Output already exists, pass --force to overwrite: {args.output}")
        return 1

    data = json.loads(args.input.read_text())
    sanitized = sanitize_value(data)
    if isinstance(sanitized, dict):
        sanitized["sanitized"] = True
        sanitized["sanitizer"] = "scripts/sanitize_runtime_snapshot.py"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n")
    print(f"Wrote sanitized snapshot: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
