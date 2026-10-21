# app/models/indexes.py
"""
Secondary indexes for the query patterns the API uses most.
Postgres does not index foreign keys automatically, so every frequently
filtered FK / filter combination is declared here. Kept in sync with the
Alembic migration `0003_query_indexes`.
"""
from sqlalchemy import Index

from .academic import Class, ClassSubject, Enrollment, Term
from .activity_log import ActivityLog
from .finance import FeeAssignment, Invoice, InvoiceItem, Payment
from .result import FormTeacherRemark, Result
from .student import StudentProfile
from .user import User

QUERY_INDEXES = [
    # Results: report cards, broadsheets, entry progress, publication checks
    Index("ix_results_student_session_term", Result.student_id, Result.session_id, Result.term_id),
    Index("ix_results_class_session_term", Result.class_id, Result.session_id, Result.term_id),
    Index("ix_results_class_subject_term", Result.class_id, Result.subject_id, Result.term_id),
    # Enrollments
    Index("ix_enrollments_student_active", Enrollment.student_id, Enrollment.is_active),
    Index("ix_enrollments_session_class_active", Enrollment.session_id, Enrollment.class_id, Enrollment.is_active),
    Index("ix_enrollments_class_term", Enrollment.class_id, Enrollment.term_id),
    # Finance
    Index("ix_invoices_student_session_term", Invoice.student_id, Invoice.session_id, Invoice.term_id),
    Index("ix_invoices_session_term_status", Invoice.session_id, Invoice.term_id, Invoice.status),
    Index("ix_invoices_status_due_date", Invoice.status, Invoice.due_date),
    Index("ix_invoice_items_invoice_id", InvoiceItem.invoice_id),
    Index("ix_payments_invoice_status", Payment.invoice_id, Payment.status),
    Index("ix_payments_created_at", Payment.created_at),
    Index("ix_fee_assignments_session_term", FeeAssignment.session_id, FeeAssignment.term_id),
    # Academic structure
    Index("ix_class_subjects_class_id", ClassSubject.class_id),
    Index("ix_class_subjects_teacher_id", ClassSubject.teacher_id),
    Index("ix_class_subjects_subject_id", ClassSubject.subject_id),
    Index("ix_classes_form_teacher_id", Class.form_teacher_id),
    Index("ix_terms_session_id", Term.session_id),
    Index("ix_student_profiles_current_class_id", StudentProfile.current_class_id),
    Index("ix_form_teacher_remarks_student_term", FormTeacherRemark.student_id, FormTeacherRemark.term_id),
    # Users list filters/sorting
    Index("ix_users_role_name", User.role, User.last_name, User.first_name),
    Index("idx_user_reset_token", User.reset_password_token),  # created by migration add_user_auth_indexes
    Index("ix_activity_logs_actor_id", ActivityLog.actor_id),
    Index("ix_activity_logs_timestamp", ActivityLog.timestamp),
]
