"""Supabase data layer. All calls go through the Streamlit backend
using the service_role key from secrets (never exposed to the browser)."""
import random
import re
import string

from supabase import create_client

from . import config

_client = None


def client():
    """Supabase client, or None when secrets are not configured yet."""
    global _client
    if not config.supabase_configured():
        return None
    if _client is None:
        key = config.SUPABASE_SERVICE_KEY or config.SUPABASE_ANON_KEY
        _client = create_client(config.SUPABASE_URL, key)
    return _client


def _ok(resp):
    return resp.data if resp else []


# ---------------- categories ----------------
def get_categories():
    sb = client()
    if not sb:
        return []
    return _ok(sb.table("categories").select("*").order("name").execute())


def add_category(name: str):
    return client().table("categories").insert({"name": name.strip()}).execute()


def delete_category(cat_id: str):
    return client().table("categories").delete().eq("id", cat_id).execute()


# ---------------- products ----------------
def _base_products_query(sb, active_only=True, category_id=None):
    q = sb.table("products").select("*, categories(name)")
    if active_only:
        q = q.eq("is_active", True)
    if category_id:
        q = q.eq("category_id", category_id)
    return q


def get_products(active_only=True, category_id=None, search=None):
    sb = client()
    if not sb:
        return []
    if search:
        # query todne wale characters hatao
        search = re.sub(r"[%(),]", "", search).strip()
    if search:
        # name, description ya tags me se kahin bhi mile
        try:
            q = _base_products_query(sb, active_only, category_id)
            return _ok(
                q.or_(f"name.ilike.%{search}%,description.ilike.%{search}%,"
                      f"tags.ilike.%{search}%")
                 .order("created_at", desc=True)
                 .execute()
            )
        except Exception:
            # purani DB (tags column nahi) — sirf name me dhoondo
            q = _base_products_query(sb, active_only, category_id)
            return _ok(q.ilike("name", f"%{search}%").order("created_at", desc=True).execute())
    q = _base_products_query(sb, active_only, category_id)
    q = q.order("created_at", desc=True)
    return _ok(q.execute())


def get_product(pid: str):
    sb = client()
    if not sb:
        return None
    rows = _ok(sb.table("products").select("*, categories(name)").eq("id", pid).execute())
    return rows[0] if rows else None


def create_product(data: dict):
    return client().table("products").insert(data).execute()


def update_product(pid: str, data: dict):
    return client().table("products").update(data).eq("id", pid).execute()


def delete_product(pid: str):
    return client().table("products").delete().eq("id", pid).execute()


# ---------------- variants ----------------
def variants_table_ok() -> bool:
    """True when the product_variants table exists (002 migration ran)."""
    sb = client()
    if not sb:
        return False
    try:
        sb.table("product_variants").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def list_variants(product_id: str):
    """All variants of a product, ordered by sort. [] when none / table missing."""
    sb = client()
    if not sb or not product_id:
        return []
    try:
        return _ok(sb.table("product_variants").select("*")
                   .eq("product_id", product_id)
                   .order("sort").order("created_at").execute())
    except Exception:
        return []


def get_variant(variant_id: str):
    sb = client()
    if not sb or not variant_id:
        return None
    try:
        rows = _ok(sb.table("product_variants").select("*")
                   .eq("id", variant_id).execute())
        return rows[0] if rows else None
    except Exception:
        return None


def save_variants(product_id: str, rows: list):
    """Delete-then-insert: replaces all variants of a product.

    rows: [{color, size_label, price_override, stock, sku}]. Empty list = no variants.
    """
    sb = client()
    if not sb or not product_id:
        return
    sb.table("product_variants").delete().eq("product_id", product_id).execute()
    clean = []
    for i, r in enumerate(rows or []):
        color = (r.get("color") or "").strip()
        size_label = (r.get("size_label") or "").strip()
        if not color and not size_label:
            continue  # khaali row skip
        try:
            stock = max(0, int(r.get("stock") or 0))
        except (TypeError, ValueError):
            stock = 0
        try:
            po = float(r.get("price_override") or 0)
            po = po if po > 0 else None
        except (TypeError, ValueError):
            po = None
        clean.append({
            "product_id": product_id,
            "color": color or None,
            "size_label": size_label or None,
            "price_override": po,
            "stock": stock,
            "sku": (r.get("sku") or "").strip() or None,
            "sort": i,
        })
    if clean:
        sb.table("product_variants").insert(clean).execute()


def update_variant_stock(variant_id: str, stock: int):
    return client().table("product_variants").update(
        {"stock": max(0, int(stock))}).eq("id", variant_id).execute()


def variant_stock_sum(product_id: str) -> int:
    return sum(int(v.get("stock") or 0) for v in list_variants(product_id))


def variant_stats(product_ids: list) -> dict:
    """{product_id: {"count": n, "stock": s}} — one query for admin lists."""
    sb = client()
    out = {}
    if not sb or not product_ids:
        return out
    try:
        rows = _ok(sb.table("product_variants")
                   .select("product_id,stock").in_("product_id", product_ids).execute())
    except Exception:
        return out
    for r in rows:
        pid = r.get("product_id")
        s = out.setdefault(pid, {"count": 0, "stock": 0})
        s["count"] += 1
        s["stock"] += int(r.get("stock") or 0)
    return out


# ---------------- banners ----------------
def get_banners(banner_type=None, placement=None, active_only=True):
    sb = client()
    if not sb:
        return []
    q = sb.table("banners").select("*")
    if active_only:
        q = q.eq("is_active", True)
    if banner_type:
        q = q.eq("banner_type", banner_type)
    if placement:
        q = q.eq("placement", placement)
    q = q.order("sort_order").order("created_at", desc=True)
    return _ok(q.execute())


def create_banner(data: dict):
    return client().table("banners").insert(data).execute()


def update_banner(bid: str, data: dict):
    return client().table("banners").update(data).eq("id", bid).execute()


def delete_banner(bid: str):
    return client().table("banners").delete().eq("id", bid).execute()


# ---------------- payment methods (prepayment: Easypaisa / Bank) ----------------
def payment_methods_table_ok() -> bool:
    """True when the payment_methods table exists (005 migration ran)."""
    sb = client()
    if not sb:
        return False
    try:
        sb.table("payment_methods").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def orders_payment_columns_ok() -> bool:
    """True when orders has the payment columns (005 migration ran).

    Checkout degrades gracefully without them: prepay hides, COD still works.
    """
    sb = client()
    if not sb:
        return False
    try:
        sb.table("orders").select("payment_method").limit(1).execute()
        return True
    except Exception:
        return False


def get_payment_methods(active_only=True):
    """All payment methods, ordered by sort_order. [] when table missing."""
    sb = client()
    if not sb:
        return []
    try:
        q = sb.table("payment_methods").select("*")
        if active_only:
            q = q.eq("is_active", True)
        q = q.order("sort_order").order("created_at")
        return _ok(q.execute())
    except Exception:
        return []


def get_payment_method(mid: str):
    sb = client()
    if not sb or not mid:
        return None
    try:
        rows = _ok(sb.table("payment_methods").select("*").eq("id", mid).limit(1).execute())
        return rows[0] if rows else None
    except Exception:
        return None


def create_payment_method(data: dict):
    return client().table("payment_methods").insert(data).execute()


def update_payment_method(mid: str, data: dict):
    return client().table("payment_methods").update(data).eq("id", mid).execute()


def delete_payment_method(mid: str):
    return client().table("payment_methods").delete().eq("id", mid).execute()


# ---------------- orders ----------------
ORDER_STATUSES = ["Pending", "Confirmed", "Shipped", "Delivered", "Cancelled"]


def _gen_order_number():
    return "SK-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def create_order(data: dict):
    sb = client()
    for _ in range(5):
        data["order_number"] = _gen_order_number()
        try:
            return sb.table("orders").insert(data).execute()
        except Exception:
            continue
    raise RuntimeError("Could not generate a unique order number")


def get_orders(limit=200):
    sb = client()
    if not sb:
        return []
    return _ok(sb.table("orders").select("*").order("created_at", desc=True).limit(limit).execute())


def get_order(oid: str):
    """Single order by id. None when missing."""
    sb = client()
    if not sb or not oid:
        return None
    rows = _ok(sb.table("orders").select("*").eq("id", oid).limit(1).execute())
    return rows[0] if rows else None


def get_order_by_number(order_number: str):
    sb = client()
    if not sb:
        return None
    rows = _ok(
        sb.table("orders")
        .select("*")
        .eq("order_number", order_number.strip().upper())
        .execute()
    )
    return rows[0] if rows else None


def update_order(oid: str, fields: dict):
    return client().table("orders").update(fields).eq("id", oid).execute()


def delete_order(oid: str):
    """Delete a single order. Returns True on success."""
    sb = client()
    if not sb or not oid:
        return False
    try:
        sb.table("orders").delete().eq("id", oid).execute()
        return True
    except Exception:
        return False


def bulk_order_status(oids: list, status: str):
    """Set status for multiple orders. Returns count updated."""
    sb = client()
    if not sb or not oids or status not in ORDER_STATUSES:
        return 0
    try:
        sb.table("orders").update({"status": status}).in_("id", oids).execute()
        return len(oids)
    except Exception:
        return 0


# ---------------- settings ----------------
def get_setting(key: str, default=""):
    sb = client()
    if not sb:
        return default
    rows = _ok(sb.table("settings").select("value").eq("key", key).execute())
    return rows[0]["value"] if rows else default


def set_setting(key: str, value: str):
    return (
        client()
        .table("settings")
        .upsert({"key": key, "value": str(value)}, on_conflict="key")
        .execute()
    )


# ---------------- reviews ----------------
def get_reviews(product_id, approved_only=True):
    sb = client()
    if not sb:
        return []
    q = sb.table("reviews").select("*").eq("product_id", product_id)
    if approved_only:
        q = q.eq("is_approved", True)
    q = q.order("created_at", desc=True)
    return _ok(q.execute())


def create_review(data: dict):
    return client().table("reviews").insert(data).execute()


def get_all_reviews():
    sb = client()
    if not sb:
        return []
    return _ok(sb.table("reviews").select("*, products(name)")
               .order("created_at", desc=True).execute())


def update_review(rid: str, data: dict):
    return client().table("reviews").update(data).eq("id", rid).execute()


def delete_review(rid: str):
    return client().table("reviews").delete().eq("id", rid).execute()
