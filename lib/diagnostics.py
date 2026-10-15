"""Admin 'System Check': real-time health checks with English fix hints.

Each check returns (name, ok, hint). If any check fails, the hint explains
the fix directly — so Kaleem can resolve it himself.
"""
import importlib
import urllib.request

from . import config, db


def _ok(name):
    return {"name": name, "ok": True, "hint": "", "sql": ""}


def _fail(name, hint, sql=""):
    return {"name": name, "ok": False, "hint": hint, "sql": sql}


SQL_VARIANTS = """create table if not exists public.product_variants (
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
create index if not exists idx_variants_product on public.product_variants(product_id);"""

SQL_SOLD_COUNT = """alter table public.products
  add column if not exists sold_count integer not null default 0
  check (sold_count >= 0);"""

SQL_BANNER_COLORS = """alter table public.banners
  add column if not exists title_color text not null default '#1c1a15';
alter table public.banners
  add column if not exists subtitle_color text not null default '#5b5346';"""


def run_checks():
    """Run all checks. Returns list of {name, ok, hint}."""
    checks = []

    # 1. are code modules importable?
    mods = ["lib.config", "lib.db", "lib.share", "lib.emailer",
            "lib.storage", "lib.utils", "lib.diagnostics"]
    missing = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception:  # noqa: BLE001
            missing.append(m.replace("lib.", "") + ".py")
    if missing:
        checks.append(_fail(
            "Code modules",
            "These modules failed to import: " + ", ".join(missing) +
            " — a file is missing from the deploy."))
    else:
        checks.append(_ok("Code modules"))

    # 2. Supabase connection
    try:
        sb = db.client()
        if not sb:
            raise RuntimeError("client not created")
        sb.table("products").select("id").limit(1).execute()
        checks.append(_ok("Supabase connection"))
    except Exception as e:  # noqa: BLE001
        checks.append(_fail(
            "Supabase connection",
            f"Cannot reach the database ({str(e)[:100]}). "
            "Check SUPABASE_URL / SUPABASE_SERVICE_KEY in Railway Variables."))
        return checks  # no point running further DB checks

    # 3. required columns (catches a missed migration right here)
    needed = ["slug", "tags", "buy_price", "delivery_expense", "packing_expense",
              "discount_price", "category_id", "images", "video_url",
              "youtube_url", "stock", "is_active"]
    missing_cols = []
    for col in needed:
        try:
            sb.table("products").select(col).limit(1).execute()
        except Exception:  # noqa: BLE001
            missing_cols.append(col)
    if missing_cols:
        checks.append(_fail(
            "Database columns",
            "These columns are missing: " + ", ".join(missing_cols) +
            " — run the schema migration in the Supabase SQL Editor."))
    else:
        checks.append(_ok("Database columns"))

    # 3b. variants table (002 migration)
    try:
        if db.variants_table_ok():
            checks.append(_ok("Variants table"))
        else:
            checks.append(_fail(
                "Variants table",
                "The product_variants table is missing — copy the SQL below, run it in the Supabase SQL Editor, then press Run Check Now again.",
                SQL_VARIANTS))
    except Exception as e:  # noqa: BLE001
        checks.append(_fail("Variants table", f"Check failed ({str(e)[:100]})."))

    # 3c. sold_count column (003 migration)
    try:
        sb.table("products").select("sold_count").limit(1).execute()
        checks.append(_ok("Sold count column"))
    except Exception:  # noqa: BLE001
        checks.append(_fail(
            "Sold count column",
            "The sold_count column is missing — copy the SQL below, run it in the Supabase SQL Editor, then press Run Check Now again.",
            SQL_SOLD_COUNT))

    # 3d. banner color columns (004 migration)
    try:
        sb.table("banners").select("title_color").limit(1).execute()
        checks.append(_ok("Banner text colors"))
    except Exception:  # noqa: BLE001
        checks.append(_fail(
            "Banner text colors",
            "The title_color/subtitle_color columns are missing — copy the SQL below, run it in the Supabase SQL Editor, then press Run Check Now again.",
            SQL_BANNER_COLORS))

    # 4. storage buckets
    try:
        raw = sb.storage.list_buckets() or []
        names = set()
        for b in raw:
            names.add(b.get("name") if isinstance(b, dict) else getattr(b, "name", ""))
        miss_b = [b for b in ("product-images", "product-videos") if b not in names]
        if miss_b:
            checks.append(_fail(
                "Storage buckets",
                "These buckets are missing: " + ", ".join(miss_b) +
                " — create them as public buckets in Supabase Storage."))
        else:
            checks.append(_ok("Storage buckets"))
    except Exception as e:  # noqa: BLE001
        checks.append(_fail("Storage buckets", f"Check failed ({str(e)[:100]})."))

    # 5. env vars
    if config.SUPABASE_URL:
        checks.append(_ok("Env: SUPABASE_URL"))
    else:
        checks.append(_fail("Env: SUPABASE_URL", "SUPABASE_URL is missing in Railway Variables."))
    app_url = (config.APP_URL or "").strip()
    if not app_url:
        checks.append(_fail("Env: APP_URL", "APP_URL is missing — set your Railway URL (e.g. https://skstore.up.railway.app)."))
    elif "supabase.co" in app_url:
        checks.append(_fail(
            "Env: APP_URL",
            "APP_URL contains a Supabase URL! It must be your SITE's URL. Fix it now."))
    else:
        checks.append(_ok("Env: APP_URL"))
    if config.ADMIN_PASS:
        checks.append(_ok("Env: ADMIN_PASS"))
    else:
        checks.append(_fail("Env: ADMIN_PASS", "ADMIN_PASS is missing — admin login will not work."))
    if (config.get_secret("GITHUB_TOKEN") or "").strip():
        checks.append(_ok("Auto share pages (token)"))
    else:
        # optional now — /share/<slug> is served by this app itself
        checks.append(_ok("Share pages (/share/<slug> built-in)"))
    if config.resend_configured():
        checks.append(_ok("Email (Resend API)"))
    elif config.email_configured():
        checks.append(_ok("Email (Gmail SMTP — local only; Railway blocks SMTP)"))
    else:
        checks.append(_fail(
            "Email",
            "RESEND_API_KEY missing — order confirmation emails will not be sent. "
            "Railway blocks Gmail SMTP; use Resend (https API)."))

    return checks
