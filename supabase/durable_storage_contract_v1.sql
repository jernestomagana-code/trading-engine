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
