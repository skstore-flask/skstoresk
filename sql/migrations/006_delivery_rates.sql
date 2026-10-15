-- 006_delivery_rates.sql — City-wise delivery rates + product packed weight.
-- Run once in Supabase SQL Editor. Safe to re-run (IF NOT EXISTS / idempotent).
-- Rate = per 0.5kg slab for that city. Fee = rate x ceil((parcel weight) / 500g).
-- Parcel weight = sum of product packed weights + packaging weight setting.

-- ---------- delivery_rates table ----------
create table if not exists public.delivery_rates (
  id uuid primary key default gen_random_uuid(),
  city text not null,
  rate numeric not null default 0 check (rate >= 0),
  is_active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now()
);
create unique index if not exists delivery_rates_city_idx
  on public.delivery_rates (lower(city));

-- Seed with starting rates (admin can edit all of these).
-- These are the store's own account rates, NOT the public Leopards calculator.
insert into public.delivery_rates (city, rate, sort_order) values
  ('Lahore', 200, 1),
  ('Karachi', 450, 2),
  ('Islamabad', 300, 3),
  ('Rawalpindi', 300, 4),
  ('Faisalabad', 250, 5),
  ('Multan', 250, 6),
  ('Hyderabad', 300, 7),
  ('Peshawar', 300, 8),
  ('Quetta', 350, 9)
on conflict (lower(city)) do nothing;

-- ---------- products: packed weight ----------
alter table public.products
  add column if not exists weight_grams int not null default 0
    check (weight_grams >= 0);

-- ---------- settings: default rate + packaging weight ----------
insert into public.settings (key, value) values
  ('default_delivery_rate', '250'),
  ('packaging_weight_grams', '100')
on conflict (key) do nothing;
