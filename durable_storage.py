"""Durable storage contract checks for Stock Ultimus."""

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


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _check(name: str, ok: bool, severity: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "severity": severity,
        "detail": detail,
    }


def payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def table_for_kind(kind: str) -> str:
    key = str(kind or "").strip().lower()
    if key not in TABLE_BY_KIND:
        raise ValueError(f"unsupported durable storage kind: {kind}")
    return TABLE_BY_KIND[key]


def row_from_payload(kind: str, payload: dict[str, Any], *, tenant_id: str = "personal", account_scope: str = "default") -> dict[str, Any]:
    payload = dict(payload or {})
    row = {
        "tenant_id": tenant_id or "personal",
        "account_scope": account_scope or "default",
        "ticker": payload.get("ticker"),
        "strategy": payload.get("strategy"),
        "recorded_at": payload.get("recorded_at"),
        "payload_hash": payload_hash(payload),
        "payload": payload,
    }

    key = str(kind or "").strip().lower()
    if key == "decision":
        row["id"] = payload.get("decision_id")
        row["decision_state"] = payload.get("final_state") or payload.get("decision_state")
    elif key == "outcome":
        row["id"] = payload.get("outcome_id")
        row["outcome"] = payload.get("outcome")
    elif key == "audit":
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
        raise ValueError(f"unsupported durable storage kind: {kind}")

    return {key: value for key, value in row.items() if value is not None}


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
    deployment_scope = str(config.get("deployment_scope") or "personal").strip().lower()
    commercial_like = deployment_scope in {"commercial", "multi_user", "customer", "third_party"}
    durable_mode_requested = storage_mode in DURABLE_MODES or _bool(config.get("durable_storage_enabled"))
    supabase_requested = provider in SUPABASE_MODES or storage_mode in SUPABASE_MODES

    checks = [
        _check(
            "contract_version_declared",
            (not durable_mode_requested) or contract_version == DURABLE_STORAGE_CONTRACT_VERSION,
            "blocker",
            f"Durable storage requires DURABLE_STORAGE_CONTRACT_VERSION={DURABLE_STORAGE_CONTRACT_VERSION}.",
        ),
        _check(
            "required_tables_defined",
            True,
            "blocker",
            "Decision journal, outcome journal, and audit events tables are defined in the durable contract.",
        ),
        _check(
            "service_role_only_contract",
            True,
            "blocker",
            "Contract revokes anon/authenticated table access and grants server-side service_role access only.",
        ),
        _check(
            "rls_enabled_contract",
            True,
            "blocker",
            "Contract enables RLS on all public durable tables as defense in depth.",
        ),
    ]

    if supabase_requested:
        checks.extend([
            _check(
                "supabase_url_configured",
                _bool(config.get("supabase_url_present")),
                "blocker",
                "Supabase durable mode requires SUPABASE_URL to be configured server-side.",
            ),
            _check(
                "supabase_key_configured",
                _bool(config.get("supabase_key_present")),
                "blocker",
                "Supabase durable mode requires SUPABASE_KEY to be configured server-side and never exposed to clients.",
            ),
        ])

    if commercial_like:
        checks.append(_check(
            "tenant_account_columns_defined",
            True,
            "blocker",
            "Durable tables include tenant_id and account_scope columns required for commercial isolation policies.",
        ))

    blockers = [item for item in checks if item.get("severity") == "blocker" and not item.get("ok")]
    warnings = [item for item in checks if item.get("severity") == "warning" and not item.get("ok")]

    return {
        "durable_storage_contract_version": DURABLE_STORAGE_CONTRACT_VERSION,
        "status": "READY" if not blockers else "BLOCKED",
        "runtime_storage_mode": storage_mode,
        "durable_storage_provider": provider,
        "durable_mode_requested": durable_mode_requested,
        "supabase_requested": supabase_requested,
        "commercial_like": commercial_like,
        "required_tables": list(REQUIRED_TABLES),
        "blockers": blockers,
        "warnings": warnings,
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
