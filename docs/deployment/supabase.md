# Deploying with Supabase

The API runs anywhere that can run a Docker container (Render, Railway, Fly.io, a VM).
Supabase hosts only the PostgreSQL database.

## 1. Create the project and get connection strings

Supabase dashboard → your project → **Connect**. You need two strings:

| Use | Which string | Port |
|---|---|---|
| `DATABASE_URL` (the running app) | **Session pooler** (or Direct if your host has IPv6) | 5432 |
| `MIGRATION_DATABASE_URL` (Alembic, data import) | **Session pooler** or **Direct** | 5432 |

The **Transaction pooler** (port 6543) also works for `DATABASE_URL`; the app detects
port 6543 and disables prepared statements automatically (`DB_TRANSACTION_POOLER`
overrides the detection). Don't use 6543 for migrations.

Paste the strings as Supabase gives them (`postgresql://...`): the app converts them to
the asyncpg driver and turns SSL on for Supabase hosts automatically.

## 2. Configure environment

Copy `.env.example` to `.env` (or set the same variables in your host's dashboard):

- `ENVIRONMENT=production`: no tables auto-created, **no demo accounts** created
- `SECRET_KEY`: long random value, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- `DATABASE_URL`, `MIGRATION_DATABASE_URL`
- `CORS_ORIGINS`, `FRONTEND_URL`, Paystack, Cloudinary and mail settings

Connection budget: each worker process holds up to `DB_POOL_SIZE + DB_MAX_OVERFLOW`
connections (default 5 + 5). With `WEB_CONCURRENCY=2` workers that's up to 20. Keep
`workers × (pool + overflow)` under your plan's pooler/direct connection limit.

## 3. Create the schema

```bash
pip install -r requirements.txt
alembic upgrade head
```

This creates all tables, the query indexes, and enables Row Level Security on every
table. RLS matters on Supabase: without it, the auto-generated REST API (reachable with
the public anon key) could read tables such as `users`. The backend connects as the
table owner, which bypasses RLS, so the API is unaffected.
If you add tables later, enable RLS on them in their migration too.

## 4. Import the existing SQLite data (one time)

```bash
python scripts/migrate_sqlite_to_postgres.py --dry-run   # validate first
python scripts/migrate_sqlite_to_postgres.py             # copy everything
```

It reads `school_management.db` by default (`--source` to change) and writes to
`MIGRATION_DATABASE_URL`. All tables are copied in one transaction, in foreign-key
order, and row counts are verified before committing. If the target already has data,
it stops; `--truncate` replaces it.

## 5. Run the API

```bash
docker build -t crowners-api .
docker run -p 8000:8000 --env-file .env crowners-api
```

Or `docker compose up` (runs `alembic upgrade head` first, then the API).
`GET /health` returns 200 when the database is reachable and 503 when it isn't; point
your platform's health check at it.

## 6. Paystack webhook

Set the webhook URL in the Paystack dashboard to `https://<your-api>/fees/webhooks/paystack`.
Each event's signature is verified, the transaction is re-verified with Paystack, and the
amount must match what was charged before an invoice is marked paid.

## Local development

- SQLite: `DATABASE_URL=sqlite+aiosqlite:///school_management.db` and
  `ENVIRONMENT=development` (creates tables and the demo accounts
  admin@school.com / teacher@school.com / student@school.com).
- Local Postgres: `docker compose --profile local-db up`.
- Tests: `pip install -r requirements-dev.txt && pytest`.
