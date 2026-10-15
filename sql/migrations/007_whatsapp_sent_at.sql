-- 007_whatsapp_sent_at.sql — WhatsApp Confirm (V0) timestamp.
-- Run once in Supabase SQL Editor. Safe to re-run (idempotent).
-- The WhatsApp Confirm button stamps this when it opens the customer chat.
-- It NEVER changes the order status — the admin marks status manually
-- after reading the customer's reply.

alter table public.orders add column if not exists whatsapp_sent_at timestamptz;
