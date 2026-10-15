-- SK Store migration 002: product variants (color / size / age).
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
