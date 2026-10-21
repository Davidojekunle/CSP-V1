# scripts/migrate_sqlite_to_postgres.py
"""
Copy all data from the legacy SQLite database into PostgreSQL / Supabase.

Prerequisite: the target schema exists (run `alembic upgrade head` first).

Usage:
    python scripts/migrate_sqlite_to_postgres.py                     # uses MIGRATION_DATABASE_URL / DATABASE_URL
    python scripts/migrate_sqlite_to_postgres.py --target "postgresql://..." --source school_management.db
    python scripts/migrate_sqlite_to_postgres.py --truncate          # empty target tables first (re-run safe)
    python scripts/migrate_sqlite_to_postgres.py --dry-run           # read + validate only, write nothing

Rows are read through the SQLModel table definitions, so SQLite's 0/1 booleans,
date strings and enum names are converted to proper Postgres types. Everything
runs in one transaction: either all tables are copied or nothing is.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import create_engine, func, inspect, select, text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import app.models  # noqa: E402,F401  (registers all tables)
from app.core.config import settings, to_sync_database_url  # noqa: E402

BATCH_SIZE = 1000


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=settings.SQLITE_DB_PATH, help="SQLite file (default: %(default)s)")
    parser.add_argument("--target", default=settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL,
                        help="Target Postgres URL (default: MIGRATION_DATABASE_URL or DATABASE_URL)")
    parser.add_argument("--truncate", action="store_true", help="TRUNCATE target tables before copying")
    parser.add_argument("--dry-run", action="store_true", help="Read and validate source data without writing")
    return parser.parse_args()


def main():
    args = parse_args()
    if not os.path.exists(args.source):
        sys.exit(f"Source SQLite file not found: {args.source}")
    target_url = to_sync_database_url(args.target)
    if not target_url.startswith("postgresql"):
        sys.exit("Target must be a PostgreSQL URL (set MIGRATION_DATABASE_URL or pass --target).")

    connect_args = {"sslmode": "require"} if settings.db_ssl_required(args.target) else {}
    if settings.uses_transaction_pooler(args.target):
        connect_args["prepare_threshold"] = None  # no server-side prepared statements through PgBouncer

    source = create_engine(f"sqlite:///{args.source}")
    target = create_engine(target_url, connect_args=connect_args)

    tables = SQLModel.metadata.sorted_tables  # parents before children
    source_tables = set(inspect(source).get_table_names())
    target_tables = set(inspect(target).get_table_names())
    missing = [t.name for t in tables if t.name not in target_tables]
    if missing:
        sys.exit(f"Target is missing tables {missing}. Run `alembic upgrade head` against it first.")

    print(f"Source: {args.source}")
    print(f"Target: {target.url.render_as_string(hide_password=True)}")

    counts = {}
    with source.connect() as src, target.begin() as dst:
        if args.truncate and not args.dry_run:
            names = ", ".join(f'"{t.name}"' for t in tables)
            dst.execute(text(f"TRUNCATE {names} CASCADE"))
            print("Truncated target tables")

        for table in tables:
            if table.name not in source_tables:
                print(f"  {table.name:24} not in source, skipped")
                continue
            src_columns = {c["name"] for c in inspect(source).get_columns(table.name)}
            columns = [c for c in table.columns if c.name in src_columns]
            dropped = sorted(src_columns - {c.name for c in table.columns})
            if dropped:
                print(f"  {table.name:24} ignoring source-only columns {dropped}")

            existing = dst.execute(select(func.count()).select_from(table)).scalar_one()
            if existing and not args.truncate and not args.dry_run:
                raise SystemExit(f"Target table {table.name} already has {existing} rows. Use --truncate to replace them.")

            copied = 0
            result = src.execution_options(stream_results=True).execute(select(*columns))
            while True:
                rows = result.fetchmany(BATCH_SIZE)
                if not rows:
                    break
                payload = [dict(row._mapping) for row in rows]
                if not args.dry_run:
                    dst.execute(table.insert(), payload)
                copied += len(payload)
            counts[table.name] = copied
            print(f"  {table.name:24} {copied:>7} rows")

        if args.dry_run:
            dst.rollback()
            print("\nDry run: nothing written.")
            return

        # Verify inside the same transaction before committing
        for name, copied in counts.items():
            table = SQLModel.metadata.tables[name]
            in_target = dst.execute(select(func.count()).select_from(table)).scalar_one()
            if in_target != copied:
                raise SystemExit(f"Row count mismatch for {name}: copied {copied}, target has {in_target}. Rolled back.")

    print(f"\nDone: {sum(counts.values())} rows across {len(counts)} tables committed.")


if __name__ == "__main__":
    main()
