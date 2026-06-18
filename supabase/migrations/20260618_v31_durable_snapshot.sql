-- Stock Ultimus V31 canonical snapshot persistence.
-- Execute in the Supabase SQL Editor used by the Render service.

create table if not exists public.stock_ultimus_v31_snapshots (
    snapshot_id text primary key,
    snapshot_version text not null,
    source text,
    generated_at timestamptz,
    received_at timestamptz not null,
    snapshot jsonb not null,
    not_order_instruction boolean not null default true,
    updated_at timestamptz not null default now()
);

alter table public.stock_ultimus_v31_snapshots enable row level security;

revoke all on table public.stock_ultimus_v31_snapshots from anon;
revoke all on table public.stock_ultimus_v31_snapshots from authenticated;
grant all on table public.stock_ultimus_v31_snapshots to service_role;

create index if not exists idx_stock_ultimus_v31_snapshots_updated_at
    on public.stock_ultimus_v31_snapshots(updated_at desc);

comment on table public.stock_ultimus_v31_snapshots is
    'Latest canonical V31 decision-support snapshot. Service-role access only.';

