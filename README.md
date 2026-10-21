# Crowners School Management API

FastAPI + SQLModel (async SQLAlchemy) backend for the school dashboard: users, enrollment,
results and report cards, fees, invoices and Paystack payments.

## Quick start (local)

```bash
python -m venv venv && venv\Scripts\activate        # Windows (source venv/bin/activate elsewhere)
pip install -r requirements-dev.txt
copy .env.example .env                               # then edit; for SQLite set:
#   DATABASE_URL=sqlite+aiosqlite:///school_management.db
#   ENVIRONMENT=development
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

## Production / Supabase

See [docs/deployment/supabase.md](docs/deployment/supabase.md): connection strings,
migrations (`alembic upgrade head`), the one-time SQLite → Supabase data import, and
running the Docker image.

## Tests

```bash
pytest -o addopts=""
```

`tests/regression/` holds the API contract tests and regression tests for fixed bugs.

## Layout

- `app/api/v1/`: routers (URL paths and response shapes are the frontend contract)
- `app/services/`: business logic and queries
- `app/models/`: SQLModel tables; `indexes.py` declares the secondary indexes
- `alembic/versions/`: schema migrations
- `scripts/`: one-off operational scripts (data import, admin creation)
