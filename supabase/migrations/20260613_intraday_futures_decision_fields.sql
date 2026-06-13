-- Stock Ultimus - Intraday Index Futures structured decision fields
-- Execute in Supabase SQL Editor for the project used by Render.

alter table public.intraday_futures_alert_events
    add column if not exists decision_engine_version text,
    add column if not exists final_state text,
    add column if not exists main_blocker text,
    add column if not exists blockers text[] default '{}',
    add column if not exists required_missing_fields text[] default '{}',
    add column if not exists decision_explanation text,
    add column if not exists decision jsonb default '{}'::jsonb,
    add column if not exists risk_status text,
    add column if not exists risk jsonb default '{}'::jsonb,
    add column if not exists portfolio_status text,
    add column if not exists portfolio jsonb default '{}'::jsonb,
    add column if not exists contracts_allowed integer,
    add column if not exists premarket_context_applied boolean,
    add column if not exists premarket_context_found boolean,
    add column if not exists premarket_session_date date,
    add column if not exists premarket_blockers text[] default '{}',
    add column if not exists premarket_context jsonb default '{}'::jsonb;

create index if not exists idx_intraday_futures_alert_events_final_state
    on public.intraday_futures_alert_events(final_state);

create index if not exists idx_intraday_futures_alert_events_main_blocker
    on public.intraday_futures_alert_events(main_blocker);

create index if not exists idx_intraday_futures_alert_events_risk_status
    on public.intraday_futures_alert_events(risk_status);

create index if not exists idx_intraday_futures_alert_events_portfolio_status
    on public.intraday_futures_alert_events(portfolio_status);

create index if not exists idx_intraday_futures_alert_events_premarket_found
    on public.intraday_futures_alert_events(premarket_context_found);
