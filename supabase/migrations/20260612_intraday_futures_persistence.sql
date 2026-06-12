-- Stock Ultimus - Intraday Index Futures durable persistence
-- Execute in Supabase SQL Editor for the project used by Render.

create table if not exists public.intraday_futures_alert_events (
    event_id text primary key,
    received_at timestamptz,
    saved_at timestamptz,
    session_date date,
    strategy text,
    strategy_version text,
    source text,
    engine_layer text,
    ticker text,
    symbol text,
    timeframe text,
    price numeric,
    entry_price numeric,
    stop_price numeric,
    stop_points numeric,
    tp1_price numeric,
    tp2_price numeric,
    rr_ratio numeric,
    event_code integer,
    event text,
    direction_code integer,
    direction text,
    setup_type text,
    instrument_family text,
    target_instrument text,
    range_used_percent numeric,
    vwap numeric,
    previous_day_high numeric,
    previous_day_low numeric,
    previous_day_close numeric,
    construction_status text,
    decision_max_state text,
    warnings text[] default '{}',
    missing_fields text[] default '{}',
    not_order_instruction boolean,
    evaluation_status text,
    paper_outcome boolean default true,
    raw_payload jsonb,
    updated_at timestamptz
);

create table if not exists public.intraday_futures_price_points (
    point_id text primary key,
    received_at timestamptz,
    saved_at timestamptz,
    session_date date,
    ticker text,
    symbol text,
    timeframe text,
    price numeric,
    strategy text,
    strategy_version text,
    source text,
    event_code integer,
    event text,
    raw_payload jsonb
);

create table if not exists public.intraday_futures_outcomes (
    outcome_id text primary key,
    event_id text references public.intraday_futures_alert_events(event_id) on delete cascade,
    evaluation_type text,
    evaluation_status text,
    evaluated_at timestamptz,
    evaluated_by text,
    classification text,
    paper_outcome boolean default true,
    mfe_points numeric,
    mae_points numeric,
    mfe_r numeric,
    mae_r numeric,
    hypothetical_result_r numeric,
    real_trade_result_r numeric,
    screenshot_url text,
    notes text,
    auto_windows jsonb,
    outcome_engine_version text,
    updated_at timestamptz
);

create index if not exists idx_intraday_futures_alert_events_session_date
    on public.intraday_futures_alert_events(session_date);

create index if not exists idx_intraday_futures_alert_events_ticker_received
    on public.intraday_futures_alert_events(ticker, received_at desc);

create index if not exists idx_intraday_futures_alert_events_event_code
    on public.intraday_futures_alert_events(event_code);

create index if not exists idx_intraday_futures_alert_events_evaluation_status
    on public.intraday_futures_alert_events(evaluation_status);

create index if not exists idx_intraday_futures_price_points_ticker_received
    on public.intraday_futures_price_points(ticker, received_at desc);

create index if not exists idx_intraday_futures_price_points_session_date
    on public.intraday_futures_price_points(session_date);

create index if not exists idx_intraday_futures_outcomes_event_id
    on public.intraday_futures_outcomes(event_id);

create index if not exists idx_intraday_futures_outcomes_classification
    on public.intraday_futures_outcomes(classification);

create index if not exists idx_intraday_futures_outcomes_evaluated_at
    on public.intraday_futures_outcomes(evaluated_at desc);
