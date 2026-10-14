"""Central config — reads environment variables, degrades gracefully when missing.

Railway: Variables tab me ye env vars set karo. Local: .env file (python-dotenv optional).
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def get_secret(name, default=""):
    return os.environ.get(name, default) or default


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_ANON_KEY = get_secret("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = get_secret("SUPABASE_SERVICE_KEY")
ADMIN_USER = get_secret("ADMIN_USER", "admin")
ADMIN_PASS = get_secret("ADMIN_PASS", "")
GMAIL_USER = get_secret("GMAIL_USER", "")
GMAIL_APP_PASSWORD = get_secret("GMAIL_APP_PASSWORD", "")
ADMIN_NOTIFY_EMAIL = get_secret("ADMIN_NOTIFY_EMAIL", "")
# Email provider: Resend (HTTPS API — Railway blocks SMTP ports) preferred,
# Gmail SMTP fallback (local dev / non-Railway hosts).
RESEND_API_KEY = get_secret("RESEND_API_KEY", "")
EMAIL_FROM = get_secret("EMAIL_FROM", "orders@theskstorepk.com")
STORE_NAME = get_secret("STORE_NAME", "SK Store")
APP_URL = get_secret("APP_URL", "").rstrip("/")
# Auto share pages (GitHub Actions): PAT with `repo` scope + "owner/repo"
GITHUB_TOKEN = get_secret("GITHUB_TOKEN", "")
GITHUB_REPO = get_secret("GITHUB_REPO", "skstoresk/skstoresk")
# Flask session signing
SECRET_KEY = get_secret("SECRET_KEY", "sk-store-dev-secret-change-me")


def supabase_configured() -> bool:
    return bool(SUPABASE_URL and (SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY))


def email_configured() -> bool:
    return bool(RESEND_API_KEY or (GMAIL_USER and GMAIL_APP_PASSWORD))


def resend_configured() -> bool:
    return bool(RESEND_API_KEY)
