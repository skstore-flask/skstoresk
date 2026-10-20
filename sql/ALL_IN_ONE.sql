-- ============================================================
-- SK STORE — ALL-IN-ONE SQL (ek hi dafa chalao)
-- Supabase Dashboard -> SQL Editor -> New query -> ye poora
-- code paste karo -> Run.
--
-- Kya karta hai: base tables + saari migrations (002-008).
-- Kya NAHI karta: koi data DELETE nahi karta. Products,
-- orders, categories — sab mehfooz rehte hain.
-- Dobara chalana SAFE hai (IF NOT EXISTS / ON CONFLICT).
-- ============================================================

-- ============================================================
-- SK STORE — Supabase database schema
-- HOW TO RUN: Supabase Dashboard → SQL Editor → New query →
-- paste this whole file → Run. Bas ek dafa chalana hai.
-- ============================================================

-- ---------- tables ----------
create table if not exists public.categories (
  id uuid primary key default gen_random_uuid(),
  name text unique not null,
  created_at timestamptz not null default now()
);

create table if not exists public.products (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  description text not null default '',
  price numeric not null check (price >= 0),
  discount_percent numeric not null default 0
    check (discount_percent >= 0 and discount_percent <= 90),
  discount_price numeric check (discount_price is null or discount_price >= 0),
  buy_price numeric not null default 0 check (buy_price >= 0),
  delivery_expense numeric not null default 0 check (delivery_expense >= 0),
  packing_expense numeric not null default 0 check (packing_expense >= 0),
  tags text not null default '',
  category_id uuid references public.categories(id) on delete set null,
  images text[] not null default '{}',
  video_url text,
  youtube_url text,
  stock integer not null default 0 check (stock >= 0),
  sold_count integer not null default 0 check (sold_count >= 0),
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists products_active_idx
  on public.products (is_active, created_at desc);

create table if not exists public.banners (
  id uuid primary key default gen_random_uuid(),
  banner_type text not null
    check (banner_type in ('new', 'discount', 'announcement')),
  placement text not null default 'top'
    check (placement in ('top', 'middle', 'bottom', 'product')),
  title text not null,
  subtitle text not null default '',
  title_color text not null default '#1c1a15',
  subtitle_color text not null default '#5b5346',
  image_url text,
  link_url text,
  product_id uuid references public.products(id) on delete set null,
  is_active boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists public.reviews (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete cascade,
  name text not null,
  email text,
  rating int not null check (rating between 1 and 5),
  comment text not null default '',
  reply_text text,
  reply_at timestamptz,
  is_approved boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.orders (
  id uuid primary key default gen_random_uuid(),
  order_number text unique not null,
  customer_name text not null,
  customer_email text,
  phone text not null,
  address text not null,
  city text not null,
  country text not null default 'Pakistan',
  items jsonb not null default '[]'::jsonb,
  subtotal numeric not null default 0,
  delivery_fee numeric not null default 0,
  total numeric not null default 0,
  status text not null default 'Pending'
    check (status in ('Pending','Confirmed','Shipped','Delivered','Cancelled')),
  tracking_id text,
  created_at timestamptz not null default now()
);
create index if not exists orders_number_idx on public.orders (order_number);
create index if not exists orders_created_idx on public.orders (created_at desc);

create table if not exists public.settings (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);

insert into public.settings (key, value) values
  ('delivery_fee', '200'),
  ('free_delivery_over', '5000'),
  ('new_badge_days', '7'),
  ('store_name', 'SK Store'),
  ('site_theme', 'dark-gold')
on conflict (key) do nothing;

-- ---------- storage buckets (product images & videos) ----------
insert into storage.buckets (id, name, public)
values ('product-images', 'product-images', true),
       ('product-videos', 'product-videos', true)
on conflict (id) do update set public = true;

-- public read access so site visitors can see images/videos
drop policy if exists "sk public read images" on storage.objects;
create policy "sk public read images"
  on storage.objects for select
  using (bucket_id = 'product-images');

drop policy if exists "sk public read videos" on storage.objects;
create policy "sk public read videos"
  on storage.objects for select
  using (bucket_id = 'product-videos');

-- NOTE: uploads/deletes happen through the Streamlit backend using the
-- service_role key (kept in Streamlit secrets), which bypasses RLS.

-- ============================================================
-- MIGRATION (purani database ke liye — ek dafa chalao):
-- Naye columns add karo + purane discount_percent ko discount_price me badlo.
-- ============================================================
alter table public.products
  add column if not exists discount_price numeric
    check (discount_price is null or discount_price >= 0),
  add column if not exists buy_price numeric not null default 0
    check (buy_price >= 0),
  add column if not exists delivery_expense numeric not null default 0
    check (delivery_expense >= 0),
  add column if not exists packing_expense numeric not null default 0
    check (packing_expense >= 0);

update public.products
set discount_price = round(price * (1 - discount_percent / 100), 2)
where discount_price is null
  and coalesce(discount_percent, 0) > 0;

-- banners: placement column (purane banners 'top' par rahenge)
alter table public.banners
  add column if not exists placement text not null default 'top'
    check (placement in ('top', 'middle', 'bottom', 'product'));

-- products: tags column (search ke liye)
alter table public.products
  add column if not exists tags text not null default '';

-- products: slug column (short product-name share links, e.g. /share/manual-vegetable-chopper.html)
alter table public.products
  add column if not exists slug text;

update public.products
set slug = nullif(trim(both '-' from lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))), '')
where slug is null;

-- duplicate slugs ho jayen to id ka tukra jor do
update public.products p
set slug = p.slug || '-' || left(p.id::text, 8)
where p.slug is not null and exists (
  select 1 from public.products q where q.slug = p.slug and q.id < p.id
);

create unique index if not exists products_slug_uidx on public.products (slug);

-- ============ 002: variants ============
-- Products WITHOUT variants keep working exactly as today (product-level stock/price).
create table if not exists public.product_variants (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete cascade,
  color text,
  size_label text,
  price_override numeric,
  stock int not null default 0,
  sku text,
  sort int not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists idx_variants_product on public.product_variants(product_id);

-- ============ 003: sold_count ============
alter table public.products
  add column if not exists sold_count integer not null default 0
  check (sold_count >= 0);

-- ============ 004: banner colors ============
alter table public.banners
  add column if not exists title_color text not null default '#1c1a15';
alter table public.banners
  add column if not exists subtitle_color text not null default '#5b5346';

-- ============ 005: payment methods ============
-- ---------- payment_methods table ----------
create table if not exists public.payment_methods (
  id uuid primary key default gen_random_uuid(),
  method_type text not null check (method_type in ('easypaisa', 'bank')),
  title text not null,
  bank_name text,
  account_number text,
  iban text,
  is_active boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now()
);

-- Seed Easypaisa + Meezan Bank rows (admin fills in the numbers).
-- Empty account details = method stays hidden at checkout until filled.
insert into public.payment_methods (method_type, title, bank_name, account_number, iban, sort_order)
values
  ('easypaisa', 'Easypaisa', 'Easypaisa', '', '', 1),
  ('bank', 'Meezan Bank', 'Meezan Bank', '', '', 2)
on conflict do nothing;

-- ---------- orders: payment columns ----------
alter table public.orders
  add column if not exists payment_method text not null default 'COD',
  add column if not exists payment_tid text,
  add column if not exists payment_slip_path text,
  add column if not exists payment_status text not null default 'N/A';

-- ---------- payment-slips bucket (PRIVATE — no public read policy) ----------
-- Slips may show the customer's own account details, so they stay private.
-- Admin views them via signed URLs (1-hour expiry).
insert into storage.buckets (id, name, public)
values ('payment-slips', 'payment-slips', false)
on conflict (id) do update set public = false;

-- ============ 006: delivery rates ============

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

-- ============ 007: whatsapp timestamp ============
alter table public.orders add column if not exists whatsapp_sent_at timestamptz;

-- ============ 008: variant images ============

alter table public.product_variants add column if not exists image_url text;

-- ============ 009: per-product advance payment required ============
alter table public.products
  add column if not exists advance_required boolean not null default false;

-- ===== 010: Ad tracking (orders.ad_source + ad_visits) =====
alter table public.orders add column if not exists ad_source text;

create table if not exists public.ad_visits (
  id bigint generated always as identity primary key,
  source text not null,
  created_at timestamptz not null default now()
);
create index if not exists ad_visits_source_idx on public.ad_visits (source);
create index if not exists ad_visits_created_idx on public.ad_visits (created_at);
