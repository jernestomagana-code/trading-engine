#!/usr/bin/env python3
"""Validate durable storage contract and production gates."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import durable_storage  # noqa: E402


FIXTURE = ROOT / "fixtures" / "durable_storage_cases.json"
SQL_FILE = ROOT / "supabase" / "durable_storage_contract_v1.sql"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    fixture = json.loads(FIXTURE.read_text())
    require(
        fixture.get("fixture_version") == "durable_storage_cases_v1",
        f"unexpected durable storage fixture version: {fixture}",
    )

    schema_sql = durable_storage.SUPABASE_SCHEMA_SQL.lower()
    require(SQL_FILE.exists(), f"missing SQL contract file: {SQL_FILE.relative_to(ROOT)}")
    require(
        SQL_FILE.read_text().strip() == durable_storage.SUPABASE_SCHEMA_SQL.strip(),
        "SQL contract file must match durable_storage.SUPABASE_SCHEMA_SQL",
    )
    for table in durable_storage.REQUIRED_TABLES:
        require(table in schema_sql, f"schema SQL missing required table {table}")
        require(f"alter table public.{table} enable row level security" in schema_sql, f"schema SQL missing RLS for {table}")
        require(f"revoke all on table public.{table} from anon, authenticated" in schema_sql, f"schema SQL missing public revoke for {table}")
        require(f"grant select, insert, update, delete on table public.{table} to service_role" in schema_sql, f"schema SQL missing service_role grant for {table}")
    require("tenant_id text not null" in schema_sql, "schema SQL must include tenant_id")
    require("account_scope text not null" in schema_sql, "schema SQL must include account_scope")

    sample_decision = {
        "decision_id": "DEC-1",
        "recorded_at": "2026-06-19T12:00:00+00:00",
        "ticker": "AAPL",
        "strategy": "NAKED_PUT",
        "final_state": "ENTRY_READY",
    }
    row = durable_storage.row_from_payload("decision", sample_decision, tenant_id="tenant-a", account_scope="acct-a")
    require(row.get("id") == "DEC-1", f"decision row missing id: {row}")
    require(row.get("decision_state") == "ENTRY_READY", f"decision row missing state: {row}")
    require(row.get("tenant_id") == "tenant-a", f"decision row missing tenant: {row}")
    require(row.get("account_scope") == "acct-a", f"decision row missing account scope: {row}")
    require(row.get("payload") == sample_decision, f"decision row missing payload: {row}")
    require(len(row.get("payload_hash", "")) == 64, f"decision row missing sha256 hash: {row}")
    require(durable_storage.payloads_from_rows([row]) == [sample_decision], "payload extraction failed")

    sample_audit = {
        "event_id": "AUD-1",
        "recorded_at": "2026-06-19T12:01:00+00:00",
        "event_type": "DECISION_RECORDED",
        "actor": "system",
        "source": "test",
    }
    audit_row = durable_storage.row_from_payload("audit", sample_audit)
    require(audit_row.get("event_id") == "AUD-1", f"audit row missing event_id: {audit_row}")
    require(audit_row.get("event_type") == "DECISION_RECORDED", f"audit row missing event_type: {audit_row}")

    for case in fixture.get("cases") or []:
        result = durable_storage.assess(case.get("config") or {})
        expected = case.get("expected") or {}
        require(
            result.get("durable_storage_contract_version") == durable_storage.DURABLE_STORAGE_CONTRACT_VERSION,
            f"{case.get('name')} wrong version: {result}",
        )
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

    print("Validated durable storage contract, Supabase grants/RLS, and readiness gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
