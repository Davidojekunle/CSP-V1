"""Enable Row Level Security on all tables (Supabase Data API lockdown)

Revision ID: 0004_enable_rls
Revises: 0003_query_indexes
Create Date: 2026-10-21

Supabase exposes every table in the `public` schema through its auto-generated
REST/GraphQL API, reachable with the project's public "anon" key. With RLS
enabled and no policies, those API roles can read nothing. The backend connects
as the table owner (postgres), which bypasses RLS, so the app is unaffected.
On plain PostgreSQL this is harmless.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0004_enable_rls'
down_revision: Union[str, Sequence[str], None] = '0003_query_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "academic_sessions", "activity_logs", "behavioral_traits", "class_subjects", "classes",
    "enrollments", "fee_assignments", "fees", "form_teacher_remarks", "invoice_items",
    "invoices", "payments", "results", "staff_profiles", "student_profiles", "subjects",
    "terms", "users", "alembic_version",
]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    # Belt and braces on Supabase: the API roles get no table privileges at all
    op.execute("""
        DO $$
        DECLARE r text;
        BEGIN
            FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
                END IF;
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
