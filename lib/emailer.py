"""Gmail order emails (SMTP + App Password from secrets)."""
import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import config
from .utils import format_price


def _clean_password(pw: str) -> str:
    # Gmail App Password "xxxx xxxx xxxx xxxx" (spaces ke saath) dikhata hai —
    # login me spaces nahi chalte, is liye hata do.
    return (pw or "").replace(" ", "").strip()


def _from_header() -> str:
    ef = (config.EMAIL_FROM or "").strip()
    if "<" in ef:
        return ef
    return f"{config.STORE_NAME} <{ef}>"


def _send_via_resend(to_email: str, subject: str, html_body: str):
    """Resend HTTPS API (port 443 — not blocked on Railway). Returns (ok, message)."""
    import json
    import urllib.request
    import urllib.error
    payload = json.dumps({
        "from": _from_header(),
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}",
                 "Content-Type": "application/json",
                 # Cloudflare WAF in front of api.resend.com blocks Python's
                 # default "Python-urllib/x.y" UA (403 + error 1010).
                 "User-Agent": "SKStore/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read().decode("utf-8", "replace")
            if resp.status in (200, 201):
                return True, "sent via Resend"
            return False, f"Resend rejected ({resp.status}): {body[:200]}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if e.code == 401:
            return False, ("Resend: API key invalid (401). Railway me RESEND_API_KEY "
                           "dobara check karo.")
        if e.code == 403:
            return False, ("Resend: domain not verified (403) — resend.com → Domains me "
                           "theskstorepk.com verify karo. " + detail)
        if e.code == 422:
            return False, ("Resend: validation error (422) — " + detail)
        return False, f"Resend HTTP {e.code}: {detail}"
    except Exception as e:  # noqa: BLE001
        return False, f"Resend request failed: {type(e).__name__}: {e}"


def test_smtp():
    """Real provider test (no email sent). Returns (ok, detail)."""
    import socket
    # --- Resend path ---
    if config.resend_configured():
        import json
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            "https://api.resend.com/domains", method="GET",
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}",
                     "User-Agent": "SKStore/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
                domains = data.get("data", []) if isinstance(data, dict) else []
                verified = [d.get("name") for d in domains
                            if d.get("status") == "verified"]
                unverified = [d.get("name") for d in domains
                              if d.get("status") != "verified"]
                msg = (f"Resend API key OK (login → {resp.status}). "
                       f"From: {_from_header()}.")
                if verified:
                    msg += f" Verified domains: {', '.join(verified)}."
                if unverified:
                    msg += (f" ⚠️ NOT verified yet: {', '.join(unverified)} — "
                            "DNS records lagao aur verify karo.")
                return True, msg
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, ("Resend: API key INVALID (401) — Railway me RESEND_API_KEY "
                               "sahi copy karo (re_ se shuru hoti hai).")
            if e.code == 403:
                # Restricted-permission key (e.g. "Sending access"): valid for
                # sending emails, just can't list domains. That's fine.
                return True, ("Resend API key OK (sending permission). "
                              "Note: key ke permissions limited hain is liye domain "
                              "verification status check nahi ho saka — resend.com → "
                              "Domains me khud confirm kar lein. "
                              f"From: {_from_header()}.")
            return False, f"Resend check failed: HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            return False, f"Resend check failed: {type(e).__name__}: {e}"
    # --- Gmail SMTP path (local dev) ---
    if not config.email_configured():
        return False, "RESEND_API_KEY bhi nahi hai aur GMAIL_USER / App Password bhi missing."
    steps = []
    try:
        steps.append("connecting to smtp.gmail.com:587 …")
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=25) as s:
            code, _ = s.ehlo()
            steps.append(f"EHLO → {code}")
            code, _ = s.starttls()
            steps.append(f"STARTTLS → {code}")
            code, _ = s.ehlo()
            steps.append(f"EHLO → {code}")
            steps.append(f"logging in as {config.GMAIL_USER} …")
            code, resp = s.login(config.GMAIL_USER, _clean_password(config.GMAIL_APP_PASSWORD))
            steps.append(f"LOGIN → {code} {resp.decode(errors='replace')[:80]}")
        return True, " | ".join(steps)
    except smtplib.SMTPAuthenticationError as e:
        return False, ("AUTH FAILED (535) — App Password is wrong OR it belongs to a "
                       "different Gmail account than GMAIL_USER. " + " | ".join(steps) +
                       f" | error: {e}")
    except (smtplib.SMTPServerDisconnected, ConnectionError, TimeoutError, OSError, socket.gaierror) as e:
        return False, ("CONNECTION DROPPED — Gmail closed it. Usual causes: (1) Google blocked "
                       "the sign-in from the server's country — check the Gmail inbox for a "
                       "'Suspicious sign-in prevented' alert and myaccount.google.com → Security → "
                       "Recent security activity; (2) too many failed logins caused a temporary "
                       "block — wait 1 hour; (3) wrong GMAIL_USER. " + " | ".join(steps) +
                       f" | error: {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        return False, " | ".join(steps) + f" | unexpected: {type(e).__name__}: {e}"


def _send(to_email: str, subject: str, html_body: str):
    """Returns (ok, message). Never raises. Resend preferred, Gmail SMTP fallback."""
    if not to_email:
        return False, "no recipient"
    if config.resend_configured():
        return _send_via_resend(to_email, subject, html_body)
    if not config.email_configured():
        return False, "Gmail credentials are not configured in secrets"
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{config.STORE_NAME} <{config.GMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=25) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(config.GMAIL_USER, _clean_password(config.GMAIL_APP_PASSWORD))
            s.send_message(msg)
        return True, "sent"
    except smtplib.SMTPAuthenticationError:
        return False, ("Gmail login fail — App Password ghalat hai ya 2-Step Verification OFF hai. "
                       "myaccount.google.com/apppasswords se naya App Password banao.")
    except (smtplib.SMTPServerDisconnected, ConnectionError, TimeoutError, OSError):
        return False, ("Gmail closed the connection — usually because the App Password is wrong/expired "
                       "or the account has a security block. Generate a new App Password, "
                       "paste it without spaces, and keep 2-Step Verification ON.")
    except Exception as e:  # noqa: BLE001 - report, don't crash checkout
        return False, str(e)


def _items_table(order) -> str:
    rows = ""
    for it in order.get("items", []) or []:
        _nm = html.escape(str(it.get("name", "")))
        _vl = (it.get("variant_label") or "").strip()
        if _vl:
            _nm += (f"<br><span style='font-size:12px;color:#8a6d1c'>"
                    f"🎨 {html.escape(_vl)}</span>")
        rows += (
            f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{_nm}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;text-align:center'>{it.get('qty',1)}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #eee;text-align:right'>"
            f"{format_price(it.get('price',0))}</td></tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse'>"
        "<tr><th style='text-align:left;padding:8px'>Item</th>"
        "<th style='padding:8px'>Qty</th>"
        "<th style='text-align:right;padding:8px'>Price</th></tr>"
        f"{rows}</table>"
    )


def _shell(title: str, body: str) -> str:
    return (
        "<div style='font-family:Arial,sans-serif;max-width:600px;margin:auto;"
        "border:1px solid #eee;border-radius:12px;overflow:hidden'>"
        "<div style='background:#0f0f14;color:#f5c451;padding:20px;text-align:center'>"
        f"<h2 style='margin:0'>{config.STORE_NAME} 🛍️</h2></div>"
        f"<div style='padding:24px;color:#222'><h3 style='margin-top:0'>{title}</h3>{body}</div>"
        "<div style='padding:16px;text-align:center;color:#888;font-size:12px'>"
        "Made with ❤ &nbsp;|&nbsp; © Kaleem</div></div>"
    )


def send_customer_confirmation(order: dict):
    if not order.get("customer_email"):
        return False, "customer has no email"
    prepay = (order.get("payment_method") or "COD") != "COD"
    if prepay:
        pay_note = (
            f"Payment method: <b>{order.get('payment_method')}</b> (advance payment).<br>"
            f"Transaction ID: <b>{order.get('payment_tid') or '—'}</b><br>"
            "Your payment is <b>pending verification</b>. We will confirm your "
            "order once the payment is verified."
        )
        total_label = "Total"
    else:
        pay_note = "Payment will be collected as <b>Cash on Delivery</b>."
        total_label = "Total (COD)"
    body = (
        f"<p>Assalam-o-Alaikum <b>{order['customer_name']}</b>,</p>"
        "<p>Thank you for shopping with us! Your order has been received. "
        f"{pay_note}</p>"
        f"<p><b>Order number:</b> {order['order_number']}</p>"
        f"{_items_table(order)}"
        f"<p><b>Delivery fee:</b> {format_price(order.get('delivery_fee', 0))}<br>"
        f"<b>{total_label}:</b> {format_price(order.get('total', 0))}</p>"
        "<p>You can track your order anytime from our website's "
        "<b>Track Order</b> page using your order number.</p>"
    )
    return _send(
        order["customer_email"],
        f"Order confirmed — {order['order_number']} | {config.STORE_NAME}",
        _shell("✅ Order Confirmed", body),
    )


def send_admin_alert(order: dict):
    if not config.ADMIN_NOTIFY_EMAIL:
        return False, "admin email not configured"
    pay_label = order.get("payment_method") or "COD"
    body = (
        "<p><b>New order received!</b></p>"
        f"<p><b>Order:</b> {order['order_number']}<br>"
        f"<b>Customer:</b> {order['customer_name']} ({order['phone']})<br>"
        f"<b>Address:</b> {order['address']}, {order['city']}, {order['country']}<br>"
        f"<b>Payment:</b> {pay_label}"
        + (f" — TID: {order.get('payment_tid') or '—'} "
           f"(⚠️ verify in your banking app, then Verify Payment in admin)"
           if pay_label != "COD" else "")
        + f"<br><b>Total:</b> {format_price(order.get('total', 0))}</p>"
        f"{_items_table(order)}"
        "<p>Open the admin portal → Orders to confirm &amp; ship.</p>"
    )
    return _send(
        config.ADMIN_NOTIFY_EMAIL,
        f"🛒 New order {order['order_number']} — {format_price(order.get('total', 0))}",
        _shell("New Order Alert", body),
    )


def send_status_update(order: dict):
    if not order.get("customer_email"):
        return False, "customer has no email"
    tracking = order.get("tracking_id")
    body = (
        f"<p>Assalam-o-Alaikum <b>{order['customer_name']}</b>,</p>"
        f"<p>Your order <b>{order['order_number']}</b> status is now: "
        f"<b>{order['status']}</b>.</p>"
    )
    if tracking:
        body += f"<p><b>Tracking ID:</b> {tracking}</p>"
    body += "<p>Thank you for shopping with " + config.STORE_NAME + "!</p>"
    return _send(
        order["customer_email"],
        f"Order {order['order_number']} — {order['status']} | {config.STORE_NAME}",
        _shell("📦 Order Update", body),
    )


def send_review_reply(to_email: str, reviewer_name: str, product_name: str, reply_text: str):
    """Review ke jawab ki email customer ko. Returns (ok, message). Never raises."""
    try:
        body = (
            f"<p>Assalam-o-Alaikum <b>{html.escape(reviewer_name or 'Customer')}</b>,</p>"
            f"<p>Aap ne <b>{html.escape(product_name or 'product')}</b> par review diya tha "
            f"— hamara jawab hazir hai:</p>"
            f"<div style='background:#f8f6ef;border-left:4px solid #f5c451;"
            f"padding:12px 16px;border-radius:8px;color:#222'>"
            f"{html.escape(reply_text or '').replace(chr(10), '<br>')}</div>"
            "<p style='margin-top:16px'>Aapke feedback ka shukriya! 🙏</p>"
        )
        return _send(to_email, f"{config.STORE_NAME} — Aapke review ka jawab ⭐",
                     _shell("⭐ Review ka jawab", body))
    except Exception as e:  # noqa: BLE001
        return False, str(e)
