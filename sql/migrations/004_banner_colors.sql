-- 004: banner title/subtitle text colors (admin can pick readable colors)
alter table public.banners
  add column if not exists title_color text not null default '#1c1a15';
alter table public.banners
  add column if not exists subtitle_color text not null default '#5b5346';
