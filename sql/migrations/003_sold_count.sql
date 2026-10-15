-- 003_sold_count.sql — display "sold" counter for social proof (admin-settable)
alter table public.products
  add column if not exists sold_count integer not null default 0
  check (sold_count >= 0);
