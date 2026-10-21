"""Indexes for the API's main query patterns

Revision ID: 0003_query_indexes
Revises: add_user_auth_indexes
Create Date: 2026-10-21

Postgres does not index foreign keys automatically; these cover the filters
used by report cards, broadsheets, enrollment lists, invoices and payments.
Also drops user indexes that duplicated the unique-constraint indexes.
Mirrors app/models/indexes.py.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0003_query_indexes'
down_revision: Union[str, Sequence[str], None] = 'add_user_auth_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = [
    ("ix_results_student_session_term", "results", ["student_id", "session_id", "term_id"]),
    ("ix_results_class_session_term", "results", ["class_id", "session_id", "term_id"]),
    ("ix_results_class_subject_term", "results", ["class_id", "subject_id", "term_id"]),
    ("ix_enrollments_student_active", "enrollments", ["student_id", "is_active"]),
    ("ix_enrollments_session_class_active", "enrollments", ["session_id", "class_id", "is_active"]),
    ("ix_enrollments_class_term", "enrollments", ["class_id", "term_id"]),
    ("ix_invoices_student_session_term", "invoices", ["student_id", "session_id", "term_id"]),
    ("ix_invoices_session_term_status", "invoices", ["session_id", "term_id", "status"]),
    ("ix_invoices_status_due_date", "invoices", ["status", "due_date"]),
    ("ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"]),
    ("ix_payments_invoice_status", "payments", ["invoice_id", "status"]),
    ("ix_payments_created_at", "payments", ["created_at"]),
    ("ix_fee_assignments_session_term", "fee_assignments", ["session_id", "term_id"]),
    ("ix_class_subjects_class_id", "class_subjects", ["class_id"]),
    ("ix_class_subjects_teacher_id", "class_subjects", ["teacher_id"]),
    ("ix_class_subjects_subject_id", "class_subjects", ["subject_id"]),
    ("ix_classes_form_teacher_id", "classes", ["form_teacher_id"]),
    ("ix_terms_session_id", "terms", ["session_id"]),
    ("ix_student_profiles_current_class_id", "student_profiles", ["current_class_id"]),
    ("ix_form_teacher_remarks_student_term", "form_teacher_remarks", ["student_id", "term_id"]),
    ("ix_users_role_name", "users", ["role", "last_name", "first_name"]),
    ("ix_activity_logs_actor_id", "activity_logs", ["actor_id"]),
    ("ix_activity_logs_timestamp", "activity_logs", ["timestamp"]),
]

# Redundant with the unique constraints on users.email / users.username,
# and a composite that cannot serve the email-OR-username login lookup
REDUNDANT_USER_INDEXES = [
    ("idx_user_email", ["email"]),
    ("idx_user_username", ["username"]),
    ("idx_user_email_username_active", ["email", "username", "is_active"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False)
    for name, _ in REDUNDANT_USER_INDEXES:
        op.drop_index(name, table_name="users")


def downgrade() -> None:
    for name, columns in REDUNDANT_USER_INDEXES:
        op.create_index(name, "users", columns, unique=False)
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
