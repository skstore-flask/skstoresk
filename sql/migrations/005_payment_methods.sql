-- 005_payment_methods.sql — Prepayment methods (Easypaisa / Bank Transfer) + order payment fields.
-- Run once in Supabase SQL Editor. Safe to re-run (IF NOT EXISTS / idempotent).

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
