#!/usr/bin/env python3
"""Validate audit log redaction and append-only event shape."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import audit_log  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.json"
        event = audit_log.append_event(
            "TEST_EVENT",
            {
                "ticker": "AAPL",
                "account_id": "DU123456",
                "nested": {
                    "snapshot_ingest_token": "super-secret-token",
                    "balance": 1000000,
                    "safe_field": "kept",
                },
                "items": [
                    {"webhook_secret": "also-secret", "decision_id": "DEC-1"},
                ],
            },
            path=path,
            source="test",
        )

        require(event.get("audit_log_version") == audit_log.AUDIT_LOG_VERSION, f"wrong audit version: {event}")
        require(event.get("sensitive_values_redacted") is True, f"redaction flag missing: {event}")
        events = json.loads(path.read_text())
        require(len(events) == 1, f"expected one event: {events}")

        text = json.dumps(events)
        for forbidden in ["DU123456", "super-secret-token", "also-secret", "1000000"]:
            require(forbidden not in text, f"sensitive value leaked into audit log: {forbidden}")
        require("[REDACTED]" in text, f"redacted marker missing: {events}")
        require(events[0]["payload"]["nested"]["safe_field"] == "kept", f"safe field should be preserved: {events}")

    print("Validated audit log redaction and event shape.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
