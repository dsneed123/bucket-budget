# Bucket Budget
Personal finance manager — bucket-based budgeting, purchase value ranking, savings goals, and spending insights.

## Railway Deployment

Required environment variables:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `DATABASE_URL` | PostgreSQL connection URL (set automatically by Railway Postgres plugin) |
| `ALLOWED_HOSTS` | Comma-separated hostnames (e.g. `myapp.up.railway.app`) |
| `DEBUG` | Set to `False` in production |
| `DJANGO_SUPERUSER_EMAIL` | Email for the initial superuser account |
| `DJANGO_SUPERUSER_PASSWORD` | Password for the initial superuser account |

Optional environment variables:

| Variable | Description |
|---|---|
| `CSRF_TRUSTED_ORIGINS` | Additional comma-separated trusted origins for CSRF |
| `EMAIL_HOST` | SMTP host for outgoing email |
| `EMAIL_PORT` | SMTP port (default: `587`) |
| `EMAIL_HOST_USER` | SMTP username |
| `EMAIL_HOST_PASSWORD` | SMTP password |
| `DEFAULT_FROM_EMAIL` | From address for outgoing email |

Railway automatically sets `RAILWAY_ENVIRONMENT` and `RAILWAY_PUBLIC_DOMAIN`, which are used to enable HTTPS enforcement and configure `CSRF_TRUSTED_ORIGINS`.
