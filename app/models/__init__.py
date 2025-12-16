# app/models/__init__.py
"""
This file makes it easy to import all database models from a single location.
It also ensures that Alembic can discover all models for migration generation.
"""

# Import all base enums so they are accessible via app.models
from .base import (
    UserRole, StudentStatus, Gender, InvoiceStatus, FeeFrequency,
    TargetType, TermName, PaymentStatus, PaymentMethod, PromotionType,
    ActivityAction, TraitGrade, FormTeacherRemarkOptions, InvoiceGenerationScope
)

# Import all table models
from .academic import AcademicSession, Class, ClassSubject, Enrollment, Subject, Term
from .activity_log import ActivityLog
from .finance import Fee, FeeAssignment, Invoice, InvoiceItem, Payment
from .result import BehavioralTraits, FormTeacherRemark, Result
from .staff import StaffProfile
from .student import StudentProfile
from .user import User

# The __all__ variable defines the public API of the module.
# When a user writes `from app.models import *`, this is the list of names
# that will be imported into their namespace. It's good practice for clarity.
__all__ = [
    # Enums
    "UserRole", "StudentStatus", "Gender", "InvoiceStatus", "FeeFrequency",
    "TargetType", "TermName", "PaymentStatus", "PaymentMethod", "PromotionType",
    "ActivityAction", "TraitGrade", "FormTeacherRemarkOptions", "InvoiceGenerationScope",
    
    # Table Models
    "AcademicSession", "Class", "ClassSubject", "Enrollment", "Subject", "Term",
    "ActivityLog",
    "Fee", "FeeAssignment", "Invoice", "InvoiceItem", "Payment",
    "BehavioralTraits", "FormTeacherRemark", "Result",
    "StaffProfile",
    "StudentProfile",
    "User",
]