-- 009: per-product Advance Payment Required flag.
-- When true, the customer must pay in advance (Easypaisa / Bank Transfer)
-- before the order is placed; Cash on Delivery is not offered for it.
alter table public.products
  add column if not exists advance_required boolean not null default false;
