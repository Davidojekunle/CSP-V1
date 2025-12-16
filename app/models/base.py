# app/models/base.py
from enum import Enum


class UserRole(str, Enum):
    student = "student"
    staff = "staff"
    admin = "admin"


class StudentStatus(str, Enum):
    active = "active"
    graduated = "graduated"
    withdrawn = "withdrawn"
    alumni = "alumni"


class Gender(str, Enum):
    male = "M"
    female = "F"
    other = "Other"


class InvoiceStatus(str, Enum):
    draft = "DRAFT"
    issued = "ISSUED"
    partial = "PARTIAL"
    paid = "PAID"
    overdue = "OVERDUE"
    cancelled = "CANCELLED"

class InvoiceGenerationScope(str, Enum):
    school = "school"
    classes = "classes"
    students = "students"

class FeeFrequency(str, Enum):
    term = "term"
    session = "session"
    one_time = "one_time"




class TargetType(str, Enum):
    school = "SCHOOL"
    class_ = "CLASS"
    student = "STUDENT"


class TermName(str, Enum):
    first = "First"
    second = "Second"
    third = "Third"


class PaymentStatus(str, Enum):
    pending = "PENDING"
    successful = "SUCCESSFUL"
    failed = "FAILED"
    cancelled = "CANCELLED"


class PaymentMethod(str, Enum):
    card = "card"
    bank_transfer = "bank_transfer"
    BANK_TRANSFER = "BANK_TRANSFER"
    ussd = "ussd"
    bank = "bank"
    cash = "cash"
    cheque = "cheque"
    mobile_money = "mobile_money"


class PromotionType(str, Enum):
    promote = "promote"
    requires_placement = "requires_placement"
    graduate = "graduate"


class ActivityAction(str, Enum):
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DEACTIVATED = "user_deactivated"
    USER_REACTIVATED = "user_reactivated"
    INVOICES_GENERATED = "invoices_generated"
    INVOICES_GENERATED_UPPER = "INVOICES_GENERATED"
    PAYMENT_RECORDED = "payment_recorded"
    FEE_CREATED = "fee_created"
    USER_BULK_UPLOAD = "USER_BULK_UPLOAD"


class TraitGrade(str, Enum):
    A = "A"  # Excellent
    B = "B"  # Good
    C = "C"  # Average
    D = "D"  # Fair
    E = "E"  # Poor


class FormTeacherRemarkOptions(str, Enum):
    excellent_conduct = "Excellent conduct and a positive attitude towards learning."
    good_conduct = "Good conduct, but needs to be more focused in class."
    attentive_and_hardworking = "Attentive and hardworking, a pleasure to have in class."
    needs_improvement_in_attendance = "Needs to improve on attendance and punctuality."
    easily_distracted = "Is easily distracted and needs to improve concentration."
    shows_potential = "Shows great potential but needs to apply themselves more."
    respectful_and_cooperative = "Respectful and cooperative with peers and teachers."