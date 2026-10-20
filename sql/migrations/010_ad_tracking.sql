-- 010_advance... ad tracking: orders.ad_source + ad_visits (SK Store Ads Report)
-- Run in Supabase SQL Editor. Safe to re-run.
alter table public.orders add column if not exists ad_source text;

create table if not exists public.ad_visits (
  id bigint generated always as identity primary key,
  source text not null,
  created_at timestamptz not null default now()
);
create index if not exists ad_visits_source_idx on public.ad_visits (source);
create index if not exists ad_visits_created_idx on public.ad_visits (created_at);
