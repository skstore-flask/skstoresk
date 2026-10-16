-- 008_variant_images.sql — Per-variant photo (Daraz-style variant images).
-- Run once in Supabase SQL Editor. Safe to re-run (idempotent).
-- Each product variant (color/size/age combo) can carry its own photo,
-- shown on the product page when the customer selects that variant.
-- If this migration has NOT run yet, variants still save — just without photos.

alter table public.product_variants add column if not exists image_url text;
