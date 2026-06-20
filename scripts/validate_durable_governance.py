#!/usr/bin/env python3
"""Validate durable storage and audit-governance helpers without live secrets."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import audit_log
import durable_storage


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_sql_contract() -> None:
    sql_path = Path("supabase/durable_storage_contract_v1.sql")
    require(sql_path.exists(), "missing durable storage SQL contract")
    sql = sql_path.read_text().strip()
    require(sql == durable_storage.SUPABASE_SCHEMA_SQL.strip(), "SQL file does not match durable_storage.SUPABASE_SCHEMA_SQL")
    lowered = sql.lower()
    for table in durable_storage.REQUIRED_TABLES:
        require(f"create table if not exists public.{table}" in lowered, f"missing table {table}")
        require(f"alter table public.{table} enable row level security" in lowered, f"missing RLS for {table}")
        require(f"revoke all on table public.{table} from anon, authenticated" in lowered, f"missing anon/auth revoke for {table}")
        require(f"grant select, insert, update, delete on table public.{table} to service_role" in lowered, f"missing service_role grant for {table}")


def validate_rows() -> None:
    decision = {
        "decision_id": "DEC-TEST",
        "ticker": "SPY",
        "strategy": "NAKED_PUT",
        "final_state": "WAIT_OPTIONS_DATA",
        "recorded_at": "2026-06-19T00:00:00+00:00",
        "not_order_instruction": True,
    }
    row = durable_storage.row_from_payload("decision", decision, tenant_id="personal", account_scope="default")
    require(row["id"] == "DEC-TEST", "decision id not mapped")
    require(row["decision_state"] == "WAIT_OPTIONS_DATA", "decision state not mapped")
    require(row["payload_hash"], "payload hash missing")
    require(durable_storage.payloads_from_rows([row]) == [decision], "payload extraction failed")

    audit = {
        "event_id": "AUD-TEST",
        "event_type": "DECISION_SERVED",
        "actor": "system",
        "source": "test",
        "recorded_at": "2026-06-19T00:00:00+00:00",
        "payload": {"ticker": "SPY"},
    }
    audit_row = durable_storage.row_from_payload("audit", audit)
    require(audit_row["event_id"] == "AUD-TEST", "audit event id not mapped")


def validate_audit_redaction() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.json"
        event = audit_log.append_event(
            "TEST_EVENT",
            {"ticker": "SPY", "token": "secret", "nested": {"api_key": "secret"}},
            path=path,
        )
        require(event["payload"]["token"] == "[REDACTED]", "token not redacted")
        require(event["payload"]["nested"]["api_key"] == "[REDACTED]", "nested api key not redacted")
        events = json.loads(path.read_text())
        require(len(events) == 1, "audit event was not written")
        require(events[0]["not_order_instruction"] is True, "audit event missing no-order guardrail")


def validate_assessment() -> None:
    blocked = durable_storage.assess({
        "runtime_storage_mode": "supabase",
        "durable_storage_provider": "supabase",
        "durable_storage_enabled": True,
        "supabase_url_present": True,
        "supabase_key_present": True,
    })
    require(blocked["status"] == "BLOCKED", "missing contract version should block durable mode")
    ready = durable_storage.assess({
        "runtime_storage_mode": "supabase",
        "durable_storage_provider": "supabase",
        "durable_storage_enabled": True,
        "durable_storage_contract_version": durable_storage.DURABLE_STORAGE_CONTRACT_VERSION,
        "supabase_url_present": True,
        "supabase_key_present": True,
    })
    require(ready["status"] == "READY", "valid durable mode should be ready")
    require(ready["not_order_instruction"] is True, "durable assessment missing no-order guardrail")


def main() -> int:
    validate_sql_contract()
    validate_rows()
    validate_audit_redaction()
    validate_assessment()
    print("Durable governance validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
