-- Stock Ultimus - Intraday Futures pre-market context persistence
-- Execute in Supabase SQL Editor for the project used by Render.

create table if not exists public.intraday_futures_premarket_context (
    context_id text primary key,
    session_date date,
    updated_at timestamptz,
    updated_by text,
    source text,
    checklist_version text,
    market_context_status text,
    macro_status text,
    volatility_status text,
    reference_alignment text,
    opening_range_status text,
    range_used_status text,
    risk_daily_status text,
    portfolio_status text,
    decision_max_state text,
    notes text,
    raw_payload jsonb
);

create index if not exists idx_intraday_futures_premarket_context_session_date
    on public.intraday_futures_premarket_context(session_date);

create index if not exists idx_intraday_futures_premarket_context_updated_at
    on public.intraday_futures_premarket_context(updated_at desc);

alter table public.intraday_futures_premarket_context disable row level security;
