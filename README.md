# Bucket Budget

Personal finance manager built on bucket-based budgeting — allocate money to categories, rank purchases by value, track savings goals, and surface spending insights.

<!-- Screenshots placeholder — add after first deploy -->
<!-- ![Dashboard](docs/screenshots/dashboard.png) -->
<!-- ![Buckets](docs/screenshots/buckets.png) -->
<!-- ![Insights](docs/screenshots/insights.png) -->

---

## Features

- **Bucket budgeting** — allocate monthly income to named buckets, track spending per category, get alerts near thresholds
- **Transaction management** — import via CSV (remembers column mappings), recurring transactions, receipt uploads, split transactions, vendor tagging
- **Purchase value ranking** — score purchases 1–10 for necessity; surface "want" vs "need" spending breakdowns
- **Savings goals** — multiple goal types (emergency fund, vacation, debt payoff, etc.) with milestones, auto-save rules, and shareable links
- **Banking accounts** — multi-account net worth tracking (checking, savings, credit, cash) with balance history
- **Spending insights** — AI-generated recommendations for budget, savings, and spending quality
- **No-spend streaks** — gamified tracking of consecutive low-spend days
- **User preferences** — dark/midnight/ocean themes, timezone, week-start day, budget rollover settings

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.9, Django 4.2 |
| Database | PostgreSQL (production), SQLite (development) |
| WSGI | Gunicorn |
| Static files | WhiteNoise with compression |
| Auth | Custom email-based user model, django-ratelimit |
| Deployment | Railway (nixpacks build) |

---

## Local Setup

```bash
# 1. Clone
git clone https://github.com/dsneed123/bucket-budget.git
cd bucket-budget

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run migrations
python manage.py migrate

# 5. Create a superuser
python manage.py createsuperuser

# 6. Start the dev server
python manage.py runserver
```

Open http://localhost:8000 in your browser.

### Optional: load demo data

```bash
python manage.py load_demo_data
```

---

## Deployment (Railway)

### One-click deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app)

### Manual deploy

1. Create a new Railway project and connect this repo.
2. Add a **PostgreSQL** plugin — Railway sets `DATABASE_URL` automatically.
3. Set the required environment variables below.

### Required environment variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key — generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DATABASE_URL` | PostgreSQL connection URL (set automatically by Railway Postgres plugin) |
| `ALLOWED_HOSTS` | Comma-separated hostnames e.g. `myapp.up.railway.app` |
| `DEBUG` | Set to `False` in production |
| `DJANGO_SUPERUSER_EMAIL` | Email for the initial superuser account |
| `DJANGO_SUPERUSER_PASSWORD` | Password for the initial superuser account |

### Optional environment variables

| Variable | Description |
|---|---|
| `CSRF_TRUSTED_ORIGINS` | Additional comma-separated trusted origins |
| `EMAIL_HOST` | SMTP host for outgoing email |
| `EMAIL_PORT` | SMTP port (default: `587`) |
| `EMAIL_HOST_USER` | SMTP username |
| `EMAIL_HOST_PASSWORD` | SMTP password |
| `DEFAULT_FROM_EMAIL` | From address (default: `Bucket Budget <noreply@bucketbudget.app>`) |

Railway automatically sets `RAILWAY_ENVIRONMENT` and `RAILWAY_PUBLIC_DOMAIN`, which enable HTTPS enforcement and configure `CSRF_TRUSTED_ORIGINS`.

---

## Architecture

```
bucket-budget/
├── bucket_budget/      # Django project config (settings, urls, wsgi)
├── accounts/           # Custom user model, auth, preferences, no-spend streaks
├── banking/            # Bank accounts, balance snapshots, net worth
├── buckets/            # Budget buckets and monthly allocations
├── transactions/       # Transactions, CSV import, receipts, recurring entries
├── savings/            # Savings goals, milestones, auto-save rules
├── budget/             # Monthly budget summaries and notes
├── insights/           # Analytics, AI recommendations, activity feed
├── rankings/           # Purchase necessity ranking
├── core/               # Dashboard, fiscal month logic, sitemap
├── templates/          # Base templates and error pages (403, 404, 500)
├── static/             # CSS and JS assets
├── requirements.txt
├── railway.toml        # Railway build and start commands
└── Procfile            # Heroku-style WSGI entry point
```

### Request lifecycle

1. Gunicorn receives the request.
2. `ProcessRecurringMiddleware` materializes any due recurring transactions before the view runs.
3. The view queries PostgreSQL and renders a Django template.
4. WhiteNoise serves static assets directly from the WSGI layer (no separate CDN needed).

---

## Contributing

1. Fork the repo and create a feature branch off `main`.
2. Follow the existing Django app structure — one app per domain (accounts, banking, etc.).
3. Run the test suite before opening a PR:

```bash
python manage.py test
```

4. Keep PRs focused — one feature or fix per PR.
5. Open your PR against `main` with a short description of the change and why.
