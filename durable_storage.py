"""Durable storage contract helpers for Stock Ultimus."""

from __future__ import annotations

import hashlib
import json
from typing import Any


DURABLE_STORAGE_CONTRACT_VERSION = "durable_storage_contract_v1"
REQUIRED_TABLES = (
    "stock_ultimus_decision_journal",
    "stock_ultimus_outcome_journal",
    "stock_ultimus_audit_events",
)
TABLE_BY_KIND = {
    "decision": "stock_ultimus_decision_journal",
    "outcome": "stock_ultimus_outcome_journal",
    "audit": "stock_ultimus_audit_events",
}
SUPABASE_MODES = {"supabase"}
DURABLE_MODES = {"supabase", "postgres", "managed_postgres", "render_disk_encrypted"}


SUPABASE_SCHEMA_SQL = """
-- Stock Ultimus durable storage contract v1.
-- Server-side only: do not expose service_role keys to clients.

create table if not exists public.stock_ultimus_decision_journal (
  id text primary key,
  tenant_id text not null default 'personal',
  account_scope text not null default 'default',
  ticker text,
  strategy text,
  decision_state text,
  recorded_at timestamptz not null default now(),
  payload_hash text,
  payload jsonb not null
);

create table if not exists public.stock_ultimus_outcome_journal (
  id text primary key,
  tenant_id text not null default 'personal',
  account_scope text not null default 'default',
  ticker text,
  strategy text,
  outcome text,
  recorded_at timestamptz not null default now(),
  payload_hash text,
  payload jsonb not null
);

create table if not exists public.stock_ultimus_audit_events (
  event_id text primary key,
  tenant_id text not null default 'personal',
  account_scope text not null default 'default',
  event_type text not null,
  actor text,
  source text,
  recorded_at timestamptz not null default now(),
  payload_hash text,
  payload jsonb not null
);

create index if not exists stock_ultimus_decision_journal_recorded_at_idx
  on public.stock_ultimus_decision_journal (recorded_at desc);
create index if not exists stock_ultimus_decision_journal_tenant_account_idx
  on public.stock_ultimus_decision_journal (tenant_id, account_scope, recorded_at desc);

create index if not exists stock_ultimus_outcome_journal_recorded_at_idx
  on public.stock_ultimus_outcome_journal (recorded_at desc);
create index if not exists stock_ultimus_outcome_journal_tenant_account_idx
  on public.stock_ultimus_outcome_journal (tenant_id, account_scope, recorded_at desc);

create index if not exists stock_ultimus_audit_events_recorded_at_idx
  on public.stock_ultimus_audit_events (recorded_at desc);
create index if not exists stock_ultimus_audit_events_tenant_account_idx
  on public.stock_ultimus_audit_events (tenant_id, account_scope, recorded_at desc);

alter table public.stock_ultimus_decision_journal enable row level security;
alter table public.stock_ultimus_outcome_journal enable row level security;
alter table public.stock_ultimus_audit_events enable row level security;

revoke all on table public.stock_ultimus_decision_journal from anon, authenticated;
revoke all on table public.stock_ultimus_outcome_journal from anon, authenticated;
revoke all on table public.stock_ultimus_audit_events from anon, authenticated;

grant select, insert, update, delete on table public.stock_ultimus_decision_journal to service_role;
grant select, insert, update, delete on table public.stock_ultimus_outcome_journal to service_role;
grant select, insert, update, delete on table public.stock_ultimus_audit_events to service_role;
""".strip()


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def table_for_kind(kind: str) -> str:
    key = str(kind or "").strip().lower()
    if key not in TABLE_BY_KIND:
        raise ValueError(f"unsupported durable storage kind: {kind}")
    return TABLE_BY_KIND[key]


def row_from_payload(
    kind: str,
    payload: dict[str, Any],
    *,
    tenant_id: str = "personal",
    account_scope: str = "default",
) -> dict[str, Any]:
    payload = dict(payload or {})
    key = str(kind or "").strip().lower()
    if key == "audit":
        row = {
            "event_id": payload.get("event_id"),
            "tenant_id": tenant_id or "personal",
            "account_scope": account_scope or "default",
            "event_type": payload.get("event_type"),
            "actor": payload.get("actor"),
            "source": payload.get("source"),
            "recorded_at": payload.get("recorded_at"),
            "payload_hash": payload_hash(payload),
            "payload": payload,
        }
    else:
        row = {
            "id": payload.get("decision_id") or payload.get("outcome_id") or payload.get("id"),
            "tenant_id": tenant_id or "personal",
            "account_scope": account_scope or "default",
            "ticker": payload.get("ticker"),
            "strategy": payload.get("strategy"),
            "recorded_at": payload.get("recorded_at") or payload.get("generated_at"),
            "payload_hash": payload_hash(payload),
            "payload": payload,
        }
        if key == "decision":
            row["decision_state"] = payload.get("final_state") or payload.get("decision_state") or payload.get("decision")
        elif key == "outcome":
            row["outcome"] = payload.get("outcome")
        else:
            raise ValueError(f"unsupported durable storage kind: {kind}")
    return {name: value for name, value in row.items() if value is not None}


def payloads_from_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    payloads = []
    for row in rows or []:
        payload = row.get("payload") if isinstance(row, dict) else None
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def assess(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    storage_mode = str(config.get("runtime_storage_mode") or "local_json").strip().lower()
    provider = str(config.get("durable_storage_provider") or storage_mode).strip().lower()
    contract_version = str(config.get("durable_storage_contract_version") or "").strip()
    durable_mode_requested = storage_mode in DURABLE_MODES or truthy(config.get("durable_storage_enabled"))
    supabase_requested = provider in SUPABASE_MODES or storage_mode in SUPABASE_MODES

    checks = [
        {
            "name": "contract_version_declared",
            "ok": (not durable_mode_requested) or contract_version == DURABLE_STORAGE_CONTRACT_VERSION,
            "severity": "blocker",
            "detail": f"Durable storage requires DURABLE_STORAGE_CONTRACT_VERSION={DURABLE_STORAGE_CONTRACT_VERSION}.",
        },
        {
            "name": "required_tables_defined",
            "ok": True,
            "severity": "blocker",
            "detail": "Decision journal, outcome journal, and audit events tables are defined.",
        },
        {
            "name": "rls_enabled_contract",
            "ok": True,
            "severity": "blocker",
            "detail": "Contract enables RLS and grants server-side service_role access only.",
        },
    ]
    if supabase_requested:
        checks.extend([
            {
                "name": "supabase_url_configured",
                "ok": truthy(config.get("supabase_url_present")),
                "severity": "blocker",
                "detail": "Supabase durable mode requires SUPABASE_URL.",
            },
            {
                "name": "supabase_key_configured",
                "ok": truthy(config.get("supabase_key_present")),
                "severity": "blocker",
                "detail": "Supabase durable mode requires SUPABASE_KEY server-side.",
            },
        ])

    blockers = [item for item in checks if item["severity"] == "blocker" and not item["ok"]]
    return {
        "durable_storage_contract_version": DURABLE_STORAGE_CONTRACT_VERSION,
        "status": "READY" if not blockers else "BLOCKED",
        "runtime_storage_mode": storage_mode,
        "durable_storage_provider": provider,
        "durable_mode_requested": durable_mode_requested,
        "supabase_requested": supabase_requested,
        "required_tables": list(REQUIRED_TABLES),
        "blockers": blockers,
        "checks": checks,
        "schema_sql": SUPABASE_SCHEMA_SQL,
        "sensitive_values_excluded": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }


def summary(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "durable_storage_contract_version": contract.get("durable_storage_contract_version"),
        "status": contract.get("status"),
        "runtime_storage_mode": contract.get("runtime_storage_mode"),
        "durable_storage_provider": contract.get("durable_storage_provider"),
        "durable_mode_requested": contract.get("durable_mode_requested"),
        "supabase_requested": contract.get("supabase_requested"),
        "required_tables": contract.get("required_tables"),
        "blocker_count": len(contract.get("blockers") or []),
        "sensitive_values_excluded": True,
        "not_order_instruction": True,
        "execution_authorized": False,
    }
