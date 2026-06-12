-- Stock Ultimus - Allow Render backend to persist intraday futures data.
-- Execute in Supabase SQL Editor after creating the intraday futures tables.

alter table public.intraday_futures_alert_events disable row level security;
alter table public.intraday_futures_price_points disable row level security;
alter table public.intraday_futures_outcomes disable row level security;
