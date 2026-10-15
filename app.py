"""SK STORE — Flask e-commerce app (public site + admin portal).

Config: env vars only (see .env.example). Supabase is the database —
same tables as the old Streamlit app, zero migration needed.
"""
import hmac
import json
import os
import re
from datetime import datetime, timezone

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_wtf.csrf import CSRFProtect, CSRFError

from lib import config, db, emailer, storage, variant_suggest
from lib import share as share_lib
from lib.utils import (cod_fee_for, format_price, is_new, profit_after_cod,
                      profit_per_unit, sale_price, youtube_id)

try:
    from lib import diagnostics
except ImportError:
    diagnostics = None


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB uploads
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # CSRF protection on every POST form (AJAX sends the token via FormData)
    CSRFProtect(app)

    # template helpers available everywhere
    app.jinja_env.globals.update(
        format_price=format_price,
        sale_price=sale_price,
        is_new=is_new,
        profit_per_unit=profit_per_unit,
        profit_after_cod=profit_after_cod,
        cod_fee_for=cod_fee_for,
        store_name=config.STORE_NAME,
        app_url=config.APP_URL,
        share_url_for=share_lib.share_url_for,
    )

    # ---------------- shared helpers ----------------
    def setting(key, default=""):
        try:
            return db.get_setting(key, default)
        except Exception:
            return default

    def _cod_pct():
        """Courier COD deduction % (editable in Settings, default 4)."""
        try:
            return float(setting("cod_fee_pct", "4") or 4)
        except (TypeError, ValueError):
            return 4.0

    def _delivery_fee_setting():
        """Delivery fee charged to the customer (used as COD-fee base)."""
        try:
            return float(setting("delivery_fee", "200") or 200)
        except (TypeError, ValueError):
            return 200.0

    @app.context_processor
    def inject_common():
        cart = session.get("cart", {})
        wa = ""
        try:
            wa = db.get_setting("whatsapp_number", "") or ""
        except Exception:
            wa = ""
        wa = re.sub(r"\D", "", wa)
        if wa.startswith("0"):
            wa = "92" + wa[1:]
        fb = ""
        try:
            fb = (db.get_setting("facebook_url", "") or "").strip()
        except Exception:
            fb = ""
        if fb and not fb.startswith(("http://", "https://")):
            fb = "https://" + fb
        return {
            "cart_count": sum(int(q) for q in cart.values()),
            "whatsapp_number": wa,
            "facebook_url": fb,
            "supabase_ok": config.supabase_configured(),
            "footer_email": config.GMAIL_USER or "",
        }

    def admin_required(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("admin_authed"):
                return redirect(url_for("admin_login", next=request.path))
            return fn(*a, **kw)

        return wrapper

    def cart_items():
        """[{key, product, qty, variant, unit_price, variant_label}]; prunes dead entries.

        Cart key = "product_id" ya "product_id|variant_id".
        """
        cart = session.get("cart", {})
        items = []
        changed = False
        for key, qty in list(cart.items()):
            pid, _, vid = key.partition("|")
            try:
                p = db.get_product(pid)
            except Exception:
                p = None
            if not p or not p.get("is_active"):
                del cart[key]
                changed = True
                continue
            variant = None
            if vid:
                try:
                    variant = db.get_variant(vid)
                except Exception:
                    variant = None
                if not variant or str(variant.get("product_id")) != str(pid):
                    del cart[key]
                    changed = True
                    continue
            unit = sale_price(p)
            label_parts = []
            if variant:
                if variant.get("color"):
                    label_parts.append(str(variant["color"]))
                if variant.get("size_label"):
                    label_parts.append(str(variant["size_label"]))
                try:
                    po = float(variant.get("price_override") or 0)
                    if po > 0:
                        unit = round(po, 2)
                except (TypeError, ValueError):
                    pass
            items.append({
                "key": key, "product": p, "qty": int(qty),
                "variant": variant, "unit_price": unit,
                "variant_label": " / ".join(label_parts),
            })
        if changed:
            session["cart"] = cart
        return items

    def delivery_fee_for(subtotal):
        try:
            fee = float(setting("delivery_fee", "200") or 200)
            free_over = float(setting("free_delivery_over", "5000") or 5000)
        except ValueError:
            fee, free_over = 200.0, 5000.0
        return 0.0 if subtotal >= free_over else fee, fee, free_over

    def delivery_fee_for_city(subtotal, city, weight_grams):
        """City-wise delivery fee.

        Returns (fee, free_applied, slabs, rate_used).
        Rate = per 0.5kg slab for the city (fallback: default rate setting).
        Parcel weight = product weights + packaging weight setting.
        Free when subtotal >= free_delivery_over (same as before).
        """
        import math
        try:
            free_over = float(setting("free_delivery_over", "5000") or 5000)
        except ValueError:
            free_over = 5000.0
        try:
            packaging = int(float(setting("packaging_weight_grams", "100") or 100))
        except ValueError:
            packaging = 100
        total_grams = max(0, int(weight_grams or 0)) + packaging
        slabs = max(1, math.ceil(total_grams / 500))
        rate = db.get_delivery_rate_for_city(city)
        if rate is None:
            try:
                rate = float(setting("default_delivery_rate", "250") or 250)
            except ValueError:
                rate = 250.0
        if subtotal >= free_over:
            return 0.0, True, slabs, rate
        return float(rate) * slabs, False, slabs, float(rate)

    # ================= PUBLIC =================
    @app.route("/")
    def index():
        try:
            banners_top = db.get_banners(placement="top")
        except Exception:
            try:
                banners_top = db.get_banners()
            except Exception:
                banners_top = []
        try:
            banners_mid = db.get_banners(placement="middle")
        except Exception:
            banners_mid = []
        try:
            banners_bot = db.get_banners(placement="bottom")
        except Exception:
            banners_bot = []

        try:
            cats = db.get_categories()
        except Exception:
            cats = []
        q = (request.args.get("q") or "").strip()
        cat_id = (request.args.get("cat") or "").strip() or None
        try:
            products = db.get_products(category_id=cat_id, search=q or None)
        except Exception:
            products = []

        try:
            new_days = int(setting("new_badge_days", "7") or 7)
        except ValueError:
            new_days = 7

        filtering = bool(q or cat_id)
        new_items, disc_items = [], []
        if not filtering:
            new_items = [p for p in products if is_new(p.get("created_at"), new_days)][:6]
            disc_items = [p for p in products
                          if sale_price(p) < float(p.get("price") or 0)][:6]
        return render_template(
            "index.html", banners_top=banners_top, banners_mid=banners_mid,
            banners_bot=banners_bot, cats=cats, products=products,
            new_items=new_items, disc_items=disc_items, new_days=new_days,
            q=q, cat_id=cat_id, filtering=filtering,
        )

    @app.route("/product/<pid>")
    def product_detail(pid):
        try:
            p = db.get_product(pid)
        except Exception:
            p = None
        if not p or not p.get("is_active"):
            abort(404)
        try:
            others = [x for x in db.get_products() if x["id"] != pid]
        except Exception:
            others = []
        pcat = p.get("category_id")
        same = [x for x in others if pcat and x.get("category_id") == pcat][:4]
        related = same or [x for x in others
                            if float(x.get("discount_price") or 0) > 0
                            or float(x.get("discount_percent") or 0) > 0][:4]
        try:
            prod_banners = db.get_banners(placement="product")
        except Exception:
            prod_banners = []
        try:
            reviews = db.get_reviews(pid)
        except Exception:
            reviews = []
        avg = (sum(float(r.get("rating") or 0) for r in reviews) / len(reviews)) if reviews else 0
        try:
            new_days = int(setting("new_badge_days", "7") or 7)
        except ValueError:
            new_days = 7
        # ---- variants ----
        try:
            variants = db.list_variants(pid)
        except Exception:
            variants = []
        colors, sizes = [], []
        for v in variants:
            if v.get("color") and v["color"] not in colors:
                colors.append(v["color"])
            if v.get("size_label") and v["size_label"] not in sizes:
                sizes.append(v["size_label"])
        size_dim = "Size"
        if variants:
            try:
                cat = p.get("categories")
                cat_name = cat.get("name") if isinstance(cat, dict) else ""
                sug = variant_suggest.suggest_variants(p.get("name"), cat_name)
                size_dim = variant_suggest.size_dimension_label(sug.get("types"))
            except Exception:
                pass
        variants_json = [
            {"id": v.get("id"), "color": v.get("color") or "",
             "size": v.get("size_label") or "",
             "stock": int(v.get("stock") or 0),
             "price": float(v.get("price_override") or 0) or sale_price(p)}
            for v in variants
        ]
        return render_template(
            "product.html", p=p, related=related, prod_banners=prod_banners,
            reviews=reviews, avg=avg, new_days=new_days,
            variants=variants, colors=colors, sizes=sizes,
            size_dim=size_dim, variants_json=variants_json,
        )

    @app.route("/product/<pid>/review", methods=["POST"])
    def post_review(pid):
        try:
            p = db.get_product(pid)
        except Exception:
            p = None
        if not p:
            abort(404)
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        comment = (request.form.get("comment") or "").strip()
        try:
            rating = int(request.form.get("rating") or 0)
        except ValueError:
            rating = 0
        if not (1 <= rating <= 5):
            flash("⭐ Please tap the stars to select a rating first.", "error")
        elif not name:
            flash("Name is required.", "error")
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Please enter a valid email.", "error")
        else:
            try:
                db.create_review({"product_id": pid, "name": name, "email": email,
                                  "rating": rating, "comment": comment})
                flash("🎉 Thank you! Your review has been posted.", "success")
            except Exception as e:
                flash(f"Could not post review: {e}", "error")
        return redirect(url_for("product_detail", pid=pid) + "#reviews")

    # ---- cart ----
    @app.route("/cart")
    def cart():
        items = cart_items()
        subtotal = sum(it["unit_price"] * it["qty"] for it in items)
        weight_grams = sum(
            int((it["product"].get("weight_grams") or 0)) * it["qty"] for it in items
        )
        # Delivery is city-based: exact fee is shown at checkout once the
        # customer picks a city. Cart shows subtotal + parcel weight only.
        return render_template("cart.html", items=items, subtotal=subtotal,
                               fee=None, delivery_fee=None,
                               free_over=None, weight_grams=weight_grams)

    @app.route("/cart/add/<pid>", methods=["POST"])
    def cart_add(pid):
        try:
            qty = max(1, min(99, int(request.form.get("qty", 1))))
        except ValueError:
            qty = 1
        try:
            p = db.get_product(pid)
        except Exception:
            p = None
        variant_id = (request.form.get("variant_id") or "").strip()
        try:
            variants = db.list_variants(pid)
        except Exception:
            variants = []
        variant = None
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        def _fail(msg, gone=False):
            if is_ajax:
                return jsonify({"success": False, "message": msg}), 400
            flash(msg, "error")
            return redirect(url_for("index") if gone
                            else url_for("product_detail", pid=pid))

        if not p or not p.get("is_active"):
            return _fail("This product is no longer available.", gone=True)

        if variants:
            # variant wala product: selection lazmi
            variant = next((v for v in variants
                            if str(v.get("id")) == variant_id), None)
            if not variant:
                return _fail("⚠️ Please select a color and size first.")
            stock = int(variant.get("stock") or 0)
        else:
            stock = int(p.get("stock") or 0)
        if stock <= 0:
            return _fail("Out of stock.")
        cart = session.get("cart", {})
        key = f"{pid}|{variant['id']}" if variant else pid
        cart[key] = min(stock, cart.get(key, 0) + qty)
        session["cart"] = cart
        if is_ajax:
            count = sum(int(q) for q in cart.values())
            label = ""
            if variant:
                label = " — " + " / ".join(
                    x for x in [variant.get("color"), variant.get("size_label")] if x)
            return jsonify({"success": True,
                            "message": f"✅ Added to cart{label}",
                            "cart_count": count})
        flash("✅ Added to cart", "success")
        return redirect(request.form.get("next") or url_for("cart"))

    @app.route("/cart/update", methods=["POST"])
    def cart_update():
        key = request.form.get("key", "")
        try:
            qty = int(request.form.get("qty", 1))
        except ValueError:
            qty = 1
        cart = session.get("cart", {})
        if key in cart:
            if qty <= 0:
                del cart[key]
            else:
                pid, _, vid = key.partition("|")
                stock = 99
                try:
                    if vid:
                        v = db.get_variant(vid)
                        stock = int((v or {}).get("stock") or 0)
                    else:
                        pr = db.get_product(pid)
                        stock = int((pr or {}).get("stock") or 99)
                except Exception:
                    pass
                cart[key] = min(max(1, qty), max(1, stock))
            session["cart"] = cart
        return redirect(url_for("cart"))

    @app.route("/cart/remove/<key>", methods=["POST"])
    def cart_remove(key):
        cart = session.get("cart", {})
        cart.pop(key, None)
        session["cart"] = cart
        return redirect(url_for("cart"))

    # ---- checkout ----
    @app.route("/checkout", methods=["GET", "POST"])
    def checkout():
        items = cart_items()
        if not items:
            flash("Your cart is empty.", "error")
            return redirect(url_for("index"))
        line_items, subtotal = [], 0.0
        for it in items:
            p, qty = it["product"], it["qty"]
            price = it["unit_price"]
            subtotal += price * qty
            v = it.get("variant") or {}
            line_items.append({
                "product_id": p["id"], "name": p["name"],
                "variant_id": v.get("id"),
                "variant_label": it.get("variant_label") or None,
                "color": v.get("color"),
                "size_label": v.get("size_label"),
                "price": price, "qty": qty,
                "image": (p.get("images") or [None])[0]})
        # City-wise delivery fee: parcel weight + customer city decide the fee.
        # fee_by_city drives the live JS update on the checkout page.
        weight_grams = sum(
            int((it["product"].get("weight_grams") or 0)) * it["qty"] for it in items
        )
        cities = db.get_delivery_rates(active_only=True)
        fee_by_city = {}
        for c in cities:
            f, _, _, _ = delivery_fee_for_city(subtotal, c["city"], weight_grams)
            fee_by_city[c["city"]] = f
        def_fee, _, _, _ = delivery_fee_for_city(subtotal, None, weight_grams)
        fee_by_city["__default__"] = def_fee
        # No city typed yet on first load: show the default-rate fee.
        fee, _, _, _ = delivery_fee_for_city(subtotal, None, weight_grams)
        total = subtotal + fee

        # Prepay methods: active AND account details filled (empty = hidden).
        # Hidden entirely when 005 migration hasn't run (no payment columns).
        pay_cols_ok = db.orders_payment_columns_ok()
        pay_methods = ([m for m in db.get_payment_methods(active_only=True)
                        if (m.get("account_number") or "").strip()]
                       if pay_cols_ok else [])

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            email = (request.form.get("email") or "").strip()
            phone = (request.form.get("phone") or "").strip()
            address = (request.form.get("address") or "").strip()
            # City: free text typed by the customer (no dropdown).
            city = (request.form.get("city") or "").strip()
            country = (request.form.get("country") or "Pakistan").strip()
            # Recompute fee for the submitted city (server is the authority).
            fee, _, _, _ = delivery_fee_for_city(subtotal, city, weight_grams)
            total = subtotal + fee
            errors = []
            if not name:
                errors.append("Name is required.")
            if len(re.sub(r"\D", "", phone)) < 10:
                errors.append("Please enter a valid phone number (at least 10 digits).")
            if not address:
                errors.append("Address is required.")
            if not city:
                errors.append("City is required.")
            if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                errors.append("Email format is not valid.")
            if country != "Pakistan":
                # professional out-of-Pakistan message
                return render_template(
                    "checkout.html", items=line_items, subtotal=subtotal,
                    fee=fee, total=total, errors=errors,
                    intl_blocked=True, pay_methods=pay_methods, cities=cities, weight_grams=weight_grams, fee_by_city=fee_by_city,
                    form={"name": name, "email": email, "phone": phone,
                          "address": address, "city": city, "country": country},
                ), 200
            for it in line_items:
                try:
                    if it.get("variant_id"):
                        v = db.get_variant(it["variant_id"])
                        vstock = int((v or {}).get("stock") or 0)
                    else:
                        vstock = None
                        p = db.get_product(it["product_id"])
                        pstock = int((p or {}).get("stock") or 0)
                except Exception:
                    vstock, pstock = None, 0
                avail = vstock if vstock is not None else pstock
                if avail < it["qty"]:
                    vlab = f" ({it['variant_label']})" if it.get("variant_label") else ""
                    errors.append(f"Not enough stock for '{it['name']}'{vlab} (available: {avail}).")
            if errors:
                return render_template(
                    "checkout.html", items=line_items, subtotal=subtotal,
                    fee=fee, total=total, errors=errors, pay_methods=pay_methods, cities=cities, weight_grams=weight_grams, fee_by_city=fee_by_city,
                    form={"name": name, "email": email, "phone": phone,
                          "address": address, "city": city, "country": country},
                )
            # ---- payment method: COD (default) or a prepay method ----
            pay_choice = (request.form.get("payment_method") or "cod").strip()
            pay_method_label, pay_tid, pay_slip_path, pay_status = "COD", None, None, "N/A"
            if pay_choice != "cod":
                pm = next((m for m in pay_methods if m["id"] == pay_choice), None)
                if not pm:
                    errors.append("Invalid payment method selected.")
                else:
                    pay_tid = (request.form.get("payment_tid") or "").strip()
                    if len(pay_tid) < 6:
                        errors.append("Transaction ID (TID) is required for advance payment.")
                    slip = request.files.get("payment_slip")
                    if not slip or not slip.filename:
                        errors.append("Payment slip screenshot is required for advance payment.")
                    if errors:
                        return render_template(
                            "checkout.html", items=line_items, subtotal=subtotal,
                            fee=fee, total=total, errors=errors, pay_methods=pay_methods, cities=cities, weight_grams=weight_grams, fee_by_city=fee_by_city,
                            form={"name": name, "email": email, "phone": phone,
                                  "address": address, "city": city, "country": country},
                        )
                    try:
                        pay_slip_path = storage.upload_slip(slip)
                    except Exception as e:
                        return render_template(
                            "checkout.html", items=line_items, subtotal=subtotal,
                            fee=fee, total=total,
                            errors=[f"Payment slip upload failed: {e}"],
                            pay_methods=pay_methods, cities=cities, weight_grams=weight_grams, fee_by_city=fee_by_city,
                            form={"name": name, "email": email, "phone": phone,
                                  "address": address, "city": city, "country": country},
                        )
                    pay_method_label = pm.get("title") or pm.get("method_type") or "Prepaid"
                    pay_status = "Pending Verification"
            # Any payment error above must stop the order (invalid method, TID, slip).
            if errors:
                return render_template(
                    "checkout.html", items=line_items, subtotal=subtotal,
                    fee=fee, total=total, errors=errors, pay_methods=pay_methods, cities=cities, weight_grams=weight_grams, fee_by_city=fee_by_city,
                    form={"name": name, "email": email, "phone": phone,
                          "address": address, "city": city, "country": country},
                )
            order_data = {
                "customer_name": name,
                "customer_email": email or None,
                "phone": phone, "address": address, "city": city,
                "country": country, "items": line_items,
                "subtotal": subtotal, "delivery_fee": fee, "total": total,
                "status": "Pending",
            }
            # Payment fields only when the orders table has them (005 ran).
            # Without 005, COD orders still save; prepay stays hidden above.
            if pay_cols_ok:
                order_data.update({
                    "payment_method": pay_method_label,
                    "payment_tid": pay_tid,
                    "payment_slip_path": pay_slip_path,
                    "payment_status": pay_status,
                })
            try:
                resp = db.create_order(order_data)
                order = resp.data[0]
            except Exception as e:
                return render_template(
                    "checkout.html", items=line_items, subtotal=subtotal,
                    fee=fee, total=total, errors=[f"Order could not be saved. Please try again. ({e})"],
                    pay_methods=pay_methods, cities=cities, weight_grams=weight_grams, fee_by_city=fee_by_city,
                    form={"name": name, "email": email, "phone": phone,
                          "address": address, "city": city, "country": country},
                )
            for it in line_items:  # stock ghatana (variant ya product level)
                try:
                    if it.get("variant_id"):
                        v = db.get_variant(it["variant_id"])
                        db.update_variant_stock(
                            it["variant_id"],
                            max(0, int((v or {}).get("stock") or 0) - it["qty"]))
                    else:
                        p = db.get_product(it["product_id"])
                        db.update_product(it["product_id"],
                                          {"stock": max(0, int((p or {}).get("stock") or 0) - it["qty"])})
                except Exception:
                    pass
            cust_ok, cust_msg = emailer.send_customer_confirmation(order)
            adm_ok, adm_msg = emailer.send_admin_alert(order)
            session["cart"] = {}
            session["last_order"] = order["order_number"]
            return render_template(
                "order.html", order=order, email=email,
                cust_ok=cust_ok, cust_msg=cust_msg, adm_ok=adm_ok,
            )

        return render_template("checkout.html", items=line_items,
                               subtotal=subtotal, fee=fee, total=total,
                               errors=[], form={}, pay_methods=pay_methods, cities=cities, weight_grams=weight_grams, fee_by_city=fee_by_city)

    @app.route("/order/<order_number>")
    def order_success(order_number):
        try:
            order = db.get_order_by_number(order_number)
        except Exception:
            order = None
        if not order:
            abort(404)
        return render_template("order.html", order=order, email=order.get("customer_email"),
                               cust_ok=True, cust_msg="", adm_ok=True)

    # ---- tracking ----
    @app.route("/track", methods=["GET", "POST"])
    def track():
        order, searched, number = None, False, ""
        if request.method == "POST":
            number = (request.form.get("order_number") or "").strip()
        else:
            number = (request.args.get("o") or "").strip()
        if number:
            searched = True
            try:
                order = db.get_order_by_number(number)
            except Exception:
                order = None
        steps = ["Pending", "Confirmed", "Shipped", "Delivered"]
        return render_template("track.html", order=order, searched=searched,
                               number=number, steps=steps)

    # ---- share page (OG tags + JS redirect) ----
    @app.route("/share/<slug>")
    def share_page(slug):
        sb = db.client()
        p = None
        if sb:
            try:
                rows = sb.table("products").select("*").eq("slug", slug).execute().data or []
                if rows:
                    p = rows[0]
            except Exception:
                p = None
            if not p:
                try:
                    p = db.get_product(slug)
                except Exception:
                    p = None
        if not p or not p.get("is_active", True):
            abort(404)
        return render_template("share.html", p=p)

    # ================= ADMIN =================
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("admin_authed"):
            return redirect(url_for("admin_dashboard"))
        error = ""
        if request.method == "POST":
            u = request.form.get("username", "")
            pw = request.form.get("password", "")
            if config.ADMIN_PASS and hmac.compare_digest(u, config.ADMIN_USER) \
                    and hmac.compare_digest(pw, config.ADMIN_PASS):
                session["admin_authed"] = True
                nxt = request.args.get("next") or url_for("admin_dashboard")
                return redirect(nxt)
            error = "❌ Ghalat User ID ya Password."
        return render_template("admin/login.html", error=error)

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("admin_authed", None)
        return redirect(url_for("index"))

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        try:
            products = db.get_products(active_only=False)
        except Exception:
            products = []
        try:
            orders = db.get_orders()
        except Exception:
            orders = []
        pending = [o for o in orders if o.get("status") == "Pending"]
        revenue = sum(float(o.get("total") or 0) for o in orders
                      if o.get("status") != "Cancelled")
        return render_template("admin/dashboard.html", products=products,
                               orders=orders, pending=pending, revenue=revenue)

    # ---- products ----
    @app.route("/admin/products")
    @admin_required
    def admin_products():
        try:
            products = db.get_products(active_only=False)
        except Exception:
            products = []
        try:
            vstats = db.variant_stats([p["id"] for p in products])
        except Exception:
            vstats = {}
        return render_template("admin/products.html", products=products,
                               vstats=vstats,
                               cod_pct=_cod_pct(),
                               dfee=_delivery_fee_setting())

    @app.route("/admin/api/suggest-variants")
    @admin_required
    def admin_api_suggest_variants():
        """Smart variant suggester (rule-based keyword matcher)."""
        name = request.args.get("name", "")
        category = request.args.get("category", "")
        try:
            return jsonify(variant_suggest.suggest_variants(name, category))
        except Exception as e:
            return jsonify({"types": [], "colors": [], "sizes": [],
                            "note": f"Suggestion failed: {e}"})

    def _product_form_data(pid=None):
        """Common data for new/edit product form."""
        try:
            cats = db.get_categories()
        except Exception:
            cats = []
        p = None
        if pid:
            try:
                p = db.get_product(pid)
            except Exception:
                p = None
        return cats, p

    @app.route("/admin/products/new", methods=["GET", "POST"])
    @admin_required
    def admin_product_new():
        return _handle_product_save(None)

    @app.route("/admin/products/<pid>/edit", methods=["GET", "POST"])
    @admin_required
    def admin_product_edit(pid):
        return _handle_product_save(pid)

    def _handle_product_save(pid):
        cats, p = _product_form_data(pid)
        if pid and not p:
            abort(404)
        ex = p or {}
        if request.method == "POST":
            return _save_product(pid, ex, cats)
        try:
            ex_variants = db.list_variants(pid) if pid else []
        except Exception:
            ex_variants = []
        return render_template("admin/product_form.html", p=ex, cats=cats,
                               is_new=(pid is None), ex_variants=ex_variants,
                               variants_ok=db.variants_table_ok(),
                               cod_pct=_cod_pct(),
                               dfee=_delivery_fee_setting())

    def _save_product(pid, ex, cats):
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        tags_raw = (request.form.get("tags") or "").strip()
        try:
            price = float(request.form.get("price") or 0)
            discount_price = float(request.form.get("discount_price") or 0)
            buy_price = float(request.form.get("buy_price") or 0)
            delivery_exp = float(request.form.get("delivery_expense") or 0)
            packing_exp = float(request.form.get("packing_expense") or 0)
            stock = int(request.form.get("stock") or 0)
            sold_count = int(request.form.get("sold_count") or 0)
            weight_grams = int(float(request.form.get("weight_grams") or 0))
            if sold_count < 0: sold_count = 0
            if weight_grams < 0: weight_grams = 0
        except ValueError:
            flash("Please enter digits only in number fields.", "error")
            return render_template("admin/product_form.html", p={**ex, **request.form},
                                   cats=cats, is_new=(pid is None))
        is_active = bool(request.form.get("is_active"))
        cat_choice = request.form.get("category") or ""
        new_cat_name = (request.form.get("new_category") or "").strip()
        vchoice = request.form.get("video_choice") or "none"
        youtube_link = (request.form.get("youtube_url") or "").strip()
        keep_images = request.form.getlist("keep_images")
        try:
            pre_urls = json.loads(request.form.get("uploaded_images_json") or "[]")
            if not isinstance(pre_urls, list):
                pre_urls = []
            pre_urls = [str(u).strip() for u in pre_urls if str(u).strip()]
        except Exception:
            pre_urls = []
        pre_video_url = (request.form.get("uploaded_video_url") or "").strip()

        errs = []
        if not name:
            errs.append("Product name is required.")
        if price <= 0:
            errs.append("Price must be greater than 0.")
        if buy_price <= 0:
            errs.append("Buy price must be greater than 0.")
        if discount_price > 0 and discount_price >= price:
            errs.append("Discount price must be lower than the actual price.")
        if vchoice == "youtube" and youtube_link and "youtu" not in youtube_link:
            errs.append("The YouTube link doesn't look valid.")
        tag_words = [w for w in tags_raw.replace(",", " ").split() if w]
        if not (3 <= len(tag_words) <= 500):
            errs.append(f"Tags must have 3–500 words (currently {len(tag_words)}).")
        if cat_choice == "__new__" and not new_cat_name:
            errs.append("Please enter the new category name.")
        new_files = [f for f in request.files.getlist("images")
                     if f and f.filename]
        total_imgs = len(keep_images) + len(pre_urls) + len(new_files)
        if total_imgs < 2:
            errs.append(f"Minimum 2 images required (currently {total_imgs}).")
        if total_imgs > 6:
            errs.append(f"Maximum 6 images allowed (currently {total_imgs}).")
        if errs:
            for e in errs:
                flash(e, "error")
            return render_template("admin/product_form.html", p={**ex, **request.form},
                                   cats=cats, is_new=(pid is None))

        # category resolve
        try:
            if cat_choice == "__new__":
                res = db.add_category(new_cat_name)
                data = getattr(res, "data", None)
                category_id = data[0]["id"] if data else None
                if not category_id:
                    match = [c for c in db.get_categories()
                             if c["name"].strip().lower() == new_cat_name.lower()]
                    category_id = match[0]["id"] if match else None
            elif cat_choice:
                category_id = cat_choice
            else:
                category_id = ex.get("category_id")
        except Exception as e:
            flash(f"Could not save category: {e}", "error")
            return render_template("admin/product_form.html", p={**ex, **request.form},
                                   cats=cats, is_new=(pid is None))

        # uploads (pre-uploaded URLs from file-select + Save-time fallback files)
        urls = list(keep_images) + pre_urls
        for f in new_files:
            try:
                urls.append(storage.upload_image(f))
            except Exception as e:
                flash(f"Image upload failed ({f.filename}): {e}", "error")
                return render_template("admin/product_form.html", p={**ex, **request.form},
                                       cats=cats, is_new=(pid is None))
        video_url, yt_url = ex.get("video_url"), ex.get("youtube_url")
        if vchoice == "upload":
            vf = request.files.get("video_file")
            if pre_video_url and not (vf and vf.filename):
                video_url = pre_video_url
                yt_url = None
            if vf and vf.filename:
                ext = (vf.filename.rsplit(".", 1)[-1].lower()
                       if "." in vf.filename else "")
                if ext not in ("mp4", "webm", "mov", "m4v"):
                    flash(f"❌ '.{ext}' format is not supported — please select MP4, WebM or MOV.",
                          "error")
                    return render_template("admin/product_form.html", p={**ex, **request.form},
                                           cats=cats, is_new=(pid is None))
                try:
                    video_url = storage.upload_video(vf)
                except Exception as e:
                    flash(f"Video upload failed: {e}", "error")
                    return render_template("admin/product_form.html", p={**ex, **request.form},
                                           cats=cats, is_new=(pid is None))
                yt_url = None
        elif vchoice == "youtube":
            yt_url = youtube_link or None
            video_url = None
        elif vchoice == "none":
            video_url, yt_url = None, None

        norm_tags = ", ".join(t.strip() for t in tags_raw.split(",") if t.strip())
        old_slug = (ex.get("slug") or "").strip()
        if old_slug:
            slug = old_slug
        else:
            try:
                taken = {str(x.get("slug") or "").strip()
                         for x in db.get_products(active_only=False) if x.get("slug")}
            except Exception:
                taken = set()
            slug = share_lib.unique_slug(share_lib.slugify(name), taken)

        data = {
            "name": name, "description": description, "slug": slug,
            "tags": norm_tags, "price": price,
            "discount_price": discount_price if discount_price > 0 else None,
            "buy_price": buy_price, "delivery_expense": delivery_exp,
            "packing_expense": packing_exp, "category_id": category_id,
            "images": urls, "video_url": video_url, "youtube_url": yt_url,
            "stock": stock, "sold_count": sold_count, "is_active": is_active,
        }
        # weight_grams only when the column exists (006 ran); otherwise the
        # product still saves without it.
        if db.products_weight_column_ok():
            data["weight_grams"] = weight_grams
        try:
            if pid:
                db.update_product(pid, data)
                saved = dict(ex); saved.update(data); saved["id"] = pid
                flash("✅ Product updated!", "success")
            else:
                res = db.create_product(data)
                rows = getattr(res, "data", None) or []
                saved = dict(data); saved["id"] = rows[0]["id"] if rows else None
                flash("✅ Product added — now live on the site!", "success")
        except Exception as e:
            flash(f"Could not save: {e}", "error")
            return render_template("admin/product_form.html", p={**ex, **request.form},
                                   cats=cats, is_new=(pid is None))

        # ---- variants (optional JSON from the Variants panel) ----
        saved_pid = pid or saved.get("id")
        vraw = (request.form.get("variants_json") or "").strip()
        if vraw and saved_pid:
            try:
                vrows = json.loads(vraw)
                if isinstance(vrows, list):
                    db.save_variants(saved_pid, vrows)
                    if vrows:
                        flash(f"🎨 {len([r for r in vrows if r.get('color') or r.get('size_label')])} variants saved!",
                              "success")
            except (ValueError, TypeError):
                flash("⚠️ Could not understand the variants format — product was saved, please check variants again.",
                      "error")
            except Exception as e:
                flash(f"⚠️ Could not save variants: {e}", "error")

        # share link (legacy GitHub trigger best-effort; /share/<slug> always works)
        share_lib.trigger_share_build("upsert", share_lib.build_product_payload(saved))
        surl = share_lib.share_url_for(saved)
        flash(f"🔗 Share link: {surl} — paste it on Facebook, the preview is generated automatically.",
              "success")
        return redirect(url_for("admin_products"))

    @app.route("/admin/products/<pid>/delete", methods=["POST"])
    @admin_required
    def admin_product_delete(pid):
        try:
            p = db.get_product(pid)
        except Exception:
            p = None
        if p:
            for u in list(p.get("images") or []):
                storage.delete_by_url(u)
            if p.get("video_url"):
                storage.delete_by_url(p["video_url"])
            try:
                db.delete_product(pid)
                share_lib.trigger_share_build(
                    "delete", {"id": pid, "slug": (p.get("slug") or "").strip()})
                flash("Product deleted.", "success")
            except Exception as e:
                flash(f"Could not delete: {e}", "error")
        return redirect(url_for("admin_products"))

    # ---- orders ----
    @app.route("/admin/orders", methods=["GET", "POST"])
    @admin_required
    def admin_orders():
        try:
            orders = db.get_orders()
        except Exception:
            orders = []
        fstatus = request.args.get("status", "All")
        if request.method == "POST":
            oid = request.form.get("order_id", "")
            new_status = request.form.get("status", "")
            tracking = (request.form.get("tracking_id") or "").strip() or None
            notify = bool(request.form.get("notify"))
            if oid and new_status in db.ORDER_STATUSES:
                try:
                    db.update_order(oid, {"status": new_status, "tracking_id": tracking})
                    flash("✅ Order updated!", "success")
                    if notify:
                        o = next((x for x in orders if x["id"] == oid), None)
                        if o:
                            ok, msg = emailer.send_status_update(
                                dict(o, status=new_status, tracking_id=tracking))
                            flash(("📧 Email sent to customer." if ok
                                   else f"Email failed: {msg}"),
                                  "success" if ok else "error")
                except Exception as e:
                    flash(f"Update failed: {e}", "error")
            return redirect(url_for("admin_orders", status=fstatus))
        if fstatus != "All":
            orders = [o for o in orders if o.get("status") == fstatus]
        # Signed URLs for private payment slips (1-hour, admin-only view).
        for o in orders:
            if o.get("payment_slip_path"):
                o["slip_url"] = storage.get_slip_url(o["payment_slip_path"])
        return render_template("admin/orders.html", orders=orders,
                               statuses=db.ORDER_STATUSES, fstatus=fstatus)

    # ---- verify prepayment (admin checked TID in own banking app) ----
    @app.route("/admin/orders/<oid>/verify-payment", methods=["POST"])
    @admin_required
    def admin_verify_payment(oid):
        o = db.get_order(oid)
        if not o:
            flash("Order not found.", "error")
            return redirect(url_for("admin_orders"))
        if (o.get("payment_status") or "") != "Pending Verification":
            flash("This order has no payment awaiting verification.", "error")
            return redirect(url_for("admin_orders"))
        try:
            db.update_order(oid, {"payment_status": "Verified", "status": "Confirmed"})
            flash("✅ Payment verified — order Confirmed!", "success")
            ok, msg = emailer.send_status_update(
                dict(o, status="Confirmed", payment_status="Verified"))
            flash(("📧 Confirmation email sent to customer." if ok
                   else f"Email failed: {msg}"), "success" if ok else "error")
        except Exception as e:
            flash(f"Verification failed: {e}", "error")
        return redirect(url_for("admin_orders"))

    # ---- print order slip ----
    @app.route("/admin/orders/<oid>/print")
    @admin_required
    def admin_order_print(oid):
        o = db.get_order(oid)
        if not o:
            flash("Order not found.", "error")
            return redirect(url_for("admin_orders"))
        return render_template("admin/order_print.html", o=o)

    # ---- bulk print (multiple slips, one print dialog) ----
    @app.route("/admin/orders/bulk-print")
    @admin_required
    def admin_orders_bulk_print():
        ids = [i for i in (request.args.get("ids", "") or "").split(",") if i]
        orders = [db.get_order(i) for i in ids]
        orders = [o for o in orders if o]
        if not orders:
            flash("No orders selected.", "error")
            return redirect(url_for("admin_orders"))
        return render_template("admin/order_bulk_print.html", orders=orders)

    # ---- bulk actions: delete / status ----
    @app.route("/admin/orders/bulk", methods=["POST"])
    @admin_required
    def admin_orders_bulk():
        from flask import request as _rq
        ids = _rq.form.getlist("order_ids")
        action = (_rq.form.get("bulk_action") or "").strip()
        if not ids:
            flash("⚠️ No orders selected.", "error")
            return redirect(url_for("admin_orders"))
        if action == "delete":
            n = sum(1 for i in ids if db.delete_order(i))
            flash(f"🗑️ {n} order(s) deleted.", "success" if n else "error")
        elif action in db.ORDER_STATUSES:
            n = db.bulk_order_status(ids, action)
            flash(f"✅ {n} order(s) marked as {action}.", "success" if n else "error")
        else:
            flash("⚠️ Unknown bulk action.", "error")
        return redirect(url_for("admin_orders"))

    # ---- banners ----
    @app.route("/admin/banners", methods=["GET", "POST"])
    @admin_required
    def admin_banners():
        try:
            products = db.get_products(active_only=True)
        except Exception:
            products = []
        try:
            banners = db.get_banners(active_only=False)
        except Exception:
            banners = []
        prod_names = {p["id"]: p["name"] for p in products}
        if request.method == "POST":
            action = request.form.get("action", "create")
            if action == "create":
                title = (request.form.get("title") or "").strip()
                if not title:
                    flash("Title is required.", "error")
                else:
                    img_url = None
                    f = request.files.get("image")
                    if f and f.filename:
                        try:
                            img_url = storage.upload_image(f)
                        except Exception as e:
                            flash(f"Image upload failed: {e}", "error")
                            return redirect(url_for("admin_banners"))
                    prod = request.form.get("product_id") or ""
                    try:
                        db.create_banner({
                            "banner_type": request.form.get("banner_type") or "new",
                            "placement": request.form.get("placement") or "top",
                            "title": title,
                            "subtitle": (request.form.get("subtitle") or "").strip(),
                            "title_color": request.form.get("title_color") or "#1c1a15",
                            "subtitle_color": request.form.get("subtitle_color") or "#5b5346",
                            "image_url": img_url,
                            "product_id": prod or None,
                            "sort_order": int(request.form.get("sort_order") or 0),
                            "is_active": True,
                        })
                        flash("✅ Banner added!", "success")
                    except Exception as e:
                        flash(f"Could not save banner: {e}", "error")
            elif action == "edit":
                bid = request.form.get("banner_id", "")
                title = (request.form.get("title") or "").strip()
                if not title:
                    flash("Title is required.", "error")
                else:
                    old = next((b for b in banners if b["id"] == bid), None)
                    edata = {
                        "banner_type": request.form.get("banner_type") or "new",
                        "placement": request.form.get("placement") or "top",
                        "title": title,
                        "subtitle": (request.form.get("subtitle") or "").strip(),
                        "title_color": request.form.get("title_color") or "#1c1a15",
                        "subtitle_color": request.form.get("subtitle_color") or "#5b5346",
                        "product_id": request.form.get("product_id") or None,
                        "sort_order": int(request.form.get("sort_order") or 0),
                        "is_active": bool(request.form.get("is_active")),
                    }
                    f = request.files.get("image")
                    if f and f.filename:
                        try:
                            edata["image_url"] = storage.upload_image(f)
                            if old and old.get("image_url"):
                                storage.delete_by_url(old["image_url"])
                        except Exception as e:
                            flash(f"Image upload failed: {e}", "error")
                            return redirect(url_for("admin_banners"))
                    try:
                        db.update_banner(bid, edata)
                        flash("✅ Banner updated!", "success")
                    except Exception as e:
                        flash(f"Update failed: {e}", "error")
            elif action == "toggle":
                bid = request.form.get("banner_id", "")
                old = next((b for b in banners if b["id"] == bid), None)
                if old:
                    try:
                        db.update_banner(bid, {"is_active": not old.get("is_active")})
                    except Exception as e:
                        flash(f"Toggle failed: {e}", "error")
            elif action == "delete":
                bid = request.form.get("banner_id", "")
                old = next((b for b in banners if b["id"] == bid), None)
                if old:
                    if old.get("image_url"):
                        storage.delete_by_url(old["image_url"])
                    try:
                        db.delete_banner(bid)
                        flash("Banner deleted.", "success")
                    except Exception as e:
                        flash(f"Delete failed: {e}", "error")
            return redirect(url_for("admin_banners"))
        edit_id = request.args.get("edit")
        edit_banner = next((b for b in banners if b["id"] == edit_id), None) if edit_id else None
        return render_template("admin/banners.html", banners=banners,
                               products=products, prod_names=prod_names,
                               edit_banner=edit_banner)

    # ---- reviews ----
    @app.route("/admin/reviews", methods=["GET", "POST"])
    @admin_required
    def admin_reviews():
        try:
            reviews = db.get_all_reviews()
        except Exception:
            reviews = []
        if request.method == "POST":
            rid = request.form.get("review_id", "")
            action = request.form.get("action", "")
            r = next((x for x in reviews if x["id"] == rid), None)
            if action == "toggle" and r:
                try:
                    db.update_review(rid, {"is_approved": not r.get("is_approved")})
                    flash("Review visibility updated.", "success")
                except Exception as e:
                    flash(f"Failed: {e}", "error")
            elif action == "delete" and r:
                try:
                    db.delete_review(rid)
                    flash("Review deleted.", "success")
                except Exception as e:
                    flash(f"Failed: {e}", "error")
            elif action == "reply" and r:
                reply = (request.form.get("reply_text") or "").strip()
                if not reply:
                    flash("Reply is empty.", "error")
                else:
                    try:
                        db.update_review(rid, {
                            "reply_text": reply,
                            "reply_at": datetime.now(timezone.utc).isoformat()})
                        rmail = (r.get("email") or "").strip()
                        pname = (r.get("products") or {}).get("name", "")
                        if rmail:
                            ok, msg = emailer.send_review_reply(
                                rmail, r.get("name"), pname, reply)
                            flash(("✅ Reply posted on the site and emailed!" if ok
                                   else f"⚠️ Reply posted, but email failed: {msg}"),
                                  "success" if ok else "error")
                        else:
                            flash("✅ Reply posted on the site (customer did not provide an email).",
                                  "success")
                    except Exception as e:
                        flash(f"Failed: {e}", "error")
            return redirect(url_for("admin_reviews"))
        return render_template("admin/reviews.html", reviews=reviews)

    # ---- delivery rates (city-wise, per 0.5kg slab) ----
    @app.route("/admin/delivery-rates", methods=["GET", "POST"])
    @admin_required
    def admin_delivery_rates():
        if not db.delivery_rates_table_ok():
            flash("Run sql/migrations/006_delivery_rates.sql in Supabase first "
                  "(delivery_rates table missing).", "error")
            return render_template("admin/delivery_rates.html", rates=[],
                                   edit_rate=None, default_rate="250",
                                   packaging_weight="100")
        rates = db.get_delivery_rates(active_only=False)
        if request.method == "POST":
            action = request.form.get("action", "create")
            if action == "settings":
                dflt = (request.form.get("default_delivery_rate") or "").strip()
                pack = (request.form.get("packaging_weight_grams") or "").strip()
                try:
                    if float(dflt) < 0 or int(float(pack)) < 0:
                        raise ValueError
                except ValueError:
                    flash("Default rate and packaging weight must be 0 or more.", "error")
                    return redirect(url_for("admin_delivery_rates"))
                db.set_setting("default_delivery_rate", dflt)
                db.set_setting("packaging_weight_grams", str(int(float(pack))))
                flash("✅ Delivery settings saved!", "success")
            elif action == "delete":
                try:
                    db.delete_delivery_rate(request.form.get("rate_id", ""))
                    flash("Delivery rate deleted.", "success")
                except Exception as e:
                    flash(f"Delete failed: {e}", "error")
            elif action == "toggle":
                rid = request.form.get("rate_id", "")
                r = next((x for x in rates if x["id"] == rid), None)
                if r:
                    try:
                        db.update_delivery_rate(rid, {"is_active": not r.get("is_active")})
                        flash("Delivery rate updated.", "success")
                    except Exception as e:
                        flash(f"Update failed: {e}", "error")
            else:  # create / edit
                city = (request.form.get("city") or "").strip()
                errs = []
                if not city:
                    errs.append("City is required.")
                try:
                    rate = float(request.form.get("rate") or 0)
                    if rate < 0:
                        raise ValueError
                except ValueError:
                    errs.append("Rate must be 0 or more.")
                    rate = 0
                try:
                    sort_order = int(request.form.get("sort_order") or 0)
                except ValueError:
                    sort_order = 0
                if errs:
                    for e in errs:
                        flash(e, "error")
                    return redirect(url_for("admin_delivery_rates"))
                data = {"city": city, "rate": rate, "sort_order": sort_order,
                        "is_active": bool(request.form.get("is_active"))}
                try:
                    if action == "edit":
                        db.update_delivery_rate(request.form.get("rate_id", ""), data)
                        flash("✅ Delivery rate updated!", "success")
                    else:
                        db.create_delivery_rate(data)
                        flash("✅ Delivery rate added!", "success")
                except Exception as e:
                    flash(f"Could not save: {e} (same city twice?)", "error")
            return redirect(url_for("admin_delivery_rates"))
        edit_id = request.args.get("edit")
        edit_rate = next((r for r in rates if r["id"] == edit_id), None) if edit_id else None
        return render_template("admin/delivery_rates.html", rates=rates,
                               edit_rate=edit_rate,
                               default_rate=setting("default_delivery_rate", "250"),
                               packaging_weight=setting("packaging_weight_grams", "100"))

    # ---- payment methods (prepayment: Easypaisa / Bank Transfer) ----
    @app.route("/admin/payment-methods", methods=["GET", "POST"])
    @admin_required
    def admin_payment_methods():
        if not db.payment_methods_table_ok():
            flash("Run sql/migrations/005_payment_methods.sql in Supabase first "
                  "(payment_methods table missing).", "error")
            return render_template("admin/payment_methods.html", methods=[],
                                   edit_method=None)
        methods = db.get_payment_methods(active_only=False)
        if request.method == "POST":
            action = request.form.get("action", "create")
            if action == "delete":
                mid = request.form.get("method_id", "")
                try:
                    db.delete_payment_method(mid)
                    flash("Payment method deleted.", "success")
                except Exception as e:
                    flash(f"Delete failed: {e}", "error")
            elif action == "toggle":
                mid = request.form.get("method_id", "")
                m = next((x for x in methods if x["id"] == mid), None)
                if m:
                    try:
                        db.update_payment_method(mid, {"is_active": not m.get("is_active")})
                        flash("Payment method updated.", "success")
                    except Exception as e:
                        flash(f"Update failed: {e}", "error")
            else:  # create / edit
                mtype = request.form.get("method_type") or "bank"
                title = (request.form.get("title") or "").strip()
                bank_name = (request.form.get("bank_name") or "").strip()
                acct = (request.form.get("account_number") or "").strip()
                iban = (request.form.get("iban") or "").strip().upper()
                errs = []
                if mtype not in ("easypaisa", "bank"):
                    errs.append("Invalid method type.")
                if not title:
                    errs.append("Title is required.")
                if not acct:
                    errs.append("Account / mobile number is required.")
                if mtype == "bank" and not iban:
                    errs.append("IBAN is required for bank transfer.")
                if errs:
                    for e in errs:
                        flash(e, "error")
                    return redirect(url_for("admin_payment_methods"))
                try:
                    sort_order = int(request.form.get("sort_order") or 0)
                except ValueError:
                    sort_order = 0
                data = {
                    "method_type": mtype,
                    "title": title,
                    "bank_name": bank_name or None,
                    "account_number": acct,
                    "iban": iban or None,
                    "sort_order": sort_order,
                    "is_active": bool(request.form.get("is_active")),
                }
                try:
                    if action == "edit":
                        db.update_payment_method(request.form.get("method_id", ""), data)
                        flash("✅ Payment method updated!", "success")
                    else:
                        db.create_payment_method(data)
                        flash("✅ Payment method added!", "success")
                except Exception as e:
                    flash(f"Could not save: {e}", "error")
            return redirect(url_for("admin_payment_methods"))
        edit_id = request.args.get("edit")
        edit_method = next((m for m in methods if m["id"] == edit_id), None) if edit_id else None
        return render_template("admin/payment_methods.html", methods=methods,
                               edit_method=edit_method)

    # ---- settings ----
    @app.route("/admin/settings", methods=["GET", "POST"])
    @admin_required
    def admin_settings():
        if request.method == "POST":
            dfee = (request.form.get("delivery_fee") or "").strip()
            ffree = (request.form.get("free_delivery_over") or "").strip()
            ndays = (request.form.get("new_badge_days") or "").strip()
            wa = (request.form.get("whatsapp_number") or "").strip()
            fb = (request.form.get("facebook_url") or "").strip()
            cod = (request.form.get("cod_fee_pct") or "").strip()
            try:
                float(dfee); float(ffree); int(ndays); float(cod)
                if not 0 <= float(cod) <= 100:
                    raise ValueError("COD fee % must be 0–100")
            except ValueError:
                flash("Please enter numbers only (COD fee % must be 0–100).", "error")
                return redirect(url_for("admin_settings"))
            try:
                db.set_setting("delivery_fee", dfee)
                db.set_setting("free_delivery_over", ffree)
                db.set_setting("new_badge_days", ndays)
                db.set_setting("whatsapp_number", wa)
                db.set_setting("facebook_url", fb)
                db.set_setting("cod_fee_pct", cod)
                flash("✅ Settings saved!", "success")
            except Exception as e:
                flash(f"Could not save: {e}", "error")
            return redirect(url_for("admin_settings"))
        return render_template(
            "admin/settings.html",
            delivery_fee=setting("delivery_fee", "200"),
            free_delivery_over=setting("free_delivery_over", "5000"),
            new_badge_days=setting("new_badge_days", "7"),
            whatsapp_number=setting("whatsapp_number", ""),
            facebook_url=setting("facebook_url", ""),
            cod_fee_pct=setting("cod_fee_pct", "4"),
        )

    # ---- instant media upload (product form: upload on file select) ----
    @app.route("/admin/upload-media", methods=["POST"])
    @admin_required
    def admin_upload_media():
        f = request.files.get("file")
        kind = (request.form.get("kind") or "image").strip()
        if not f or not f.filename:
            return jsonify({"ok": False, "error": "No file received."}), 400
        try:
            url = storage.upload_video(f) if kind == "video" else storage.upload_image(f)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "url": url})

    # ---- system check ----
    @app.route("/admin/system")
    @admin_required
    def admin_system():
        results = []
        ran = request.args.get("run") == "1"
        if ran:
            if diagnostics:
                try:
                    results = diagnostics.run_checks()
                except Exception as e:
                    results = [{"name": "System Check", "ok": False,
                                "hint": f"Check crashed: {e}"}]
            else:
                results = [{"name": "System Check", "ok": False,
                            "hint": "Could not import lib/diagnostics.py."}]
        ok_n = sum(1 for r in results if r.get("ok"))
        return render_template("admin/system.html", results=results, ran=ran,
                               ok_n=ok_n, total=len(results))

    @app.route("/admin/test-email", methods=["POST"])
    @admin_required
    def admin_test_email():
        from lib import emailer
        ok, detail = emailer.test_smtp()
        flash(("✅ SMTP login OK — " if ok else "❌ Email test FAILED — ") + detail,
              "success" if ok else "error")
        return redirect(url_for("admin_system", run=1))

    @app.errorhandler(CSRFError)
    def csrf_expired(e):
        # Friendly page instead of scary "Bad Request / CSRF token missing".
        # Happens on stale tabs, double-submits or expired sessions.
        return render_template("csrf_error.html"), 400

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def too_large(e):
        flash("File is too large (max 200MB).", "error")
        return redirect(request.referrer or url_for("index"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
