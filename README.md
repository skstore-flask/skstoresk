# SK STORE — Flask Edition 🛍️

Purani Streamlit site ka **complete rebuild** — ab full HTML/CSS/JS azadi ke saath:
dark luxe theme, animated hero, Ken Burns banner carousel, hover-zoom gallery,
gold buttons, aur mobile-first design. Database wahi Supabase hai — **koi migration nahi**.

## Railway par deploy (Roman Urdu guide)

### 1. GitHub repo banao
```bash
cd sk-store-flask
git init
git add -A
git commit -m "SK Store Flask"
# GitHub par naya repo banao (e.g. skstoresk/skstore-flask), phir:
git remote add origin https://github.com/skstoresk/skstore-flask.git
git push -u origin main
```

### 2. Railway me project banao
1. [railway.app](https://railway.app) par login karo (GitHub se)
2. **New Project → Deploy from GitHub repo** → apna repo select karo
3. Railway khud `Dockerfile` pehchan kar build kar lega (~2-3 min)

### 3. Variables set karo (Settings → Variables)
`.env.example` wali saari values yahan dalo — sab se zaroori:
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `ADMIN_USER`, `ADMIN_PASS`
- `SECRET_KEY` (koi lambi random string)
- `APP_URL` = Railway wali URL (deploy ke baad milegi, phir wapas aa kar set karo)
- `RESEND_API_KEY`, `EMAIL_FROM` (emails ke liye — Railway SMTP block karta hai, is liye Resend HTTPS API; `EMAIL_FROM` default `orders@theskstorepk.com`)
- `GMAIL_USER`, `GMAIL_APP_PASSWORD` (sirf local dev me Gmail SMTP fallback ke liye), `ADMIN_NOTIFY_EMAIL` (admin ko new-order alert kis email par jaye)

⚠️ `APP_URL` me **apni site ki URL** dalni hai — Supabase ka URL nahi!

### 4. Domain lagao (optional)
Railway → Service → Settings → Networking → **Generate Domain**
ya apna domain: **Custom Domain** me domain likho, phir Cloudflare me CNAME record banao.

### 5. Test karo
1. Site kholo → products nazar aane chahiye
2. `/admin` → login karo → **🔧 System Check** → "Abhi Check Karo" dabao
3. Sab ✅ aaye to sab set hai!

## Local chalana
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # phir values bharo
python app.py          # http://localhost:5000
```

## Database
Wahi purana Supabase project — `sql/` nahi hai is repo me kyunke tables pehle se bane hue hain.
Nayi database ho to purane repo (`sk-store/sql/schema.sql`) wali file Supabase SQL Editor me chalao.

## Structure
```
app.py              — saari routes (public + admin)
lib/                — config (env), db, emailer, share, storage, diagnostics, utils
templates/          — Jinja2 (public + admin/)
static/css/style.css — dark luxe theme + animations
static/js/main.js    — carousel, gallery, stars, profit preview
Dockerfile          — Railway deploy (gunicorn, $PORT)
```
