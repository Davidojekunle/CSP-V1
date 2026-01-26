# app/schemas/staff.py
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import date
from app.models import TraitGrade, FormTeacherRemarkOptions

class GuardianInfo(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class ResultsSummary(BaseModel):
    average_score: float
    context_period: Optional[str] = "N/A"
    total_released_results: int

class FinancialSummary(BaseModel):
    current_bill: float
    pending_payments: int

class StudentInfo(BaseModel):
    id: str
    full_name: str
    admission_number: str
    email: str
    phone: str
    profile_picture_url: Optional[str] = None
    status: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    guardian_info: GuardianInfo

class StaffProfileCreate(BaseModel):
    job_title: str
    employment_date: date
    qualifications: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

class StaffProfileUpdate(BaseModel):
    job_title: Optional[str] = None
    qualifications: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

class StaffStudentResponse(BaseModel):
    id: str
    name: str
    admission_number: str
    enrollment_status: bool
    has_results: bool

class StaffResultResponse(BaseModel):
    id: Optional[str]
    student_id: str
    student_name: str
    student_admission_number: str
    ca1: Optional[float]
    ca2: Optional[float]
    exam: Optional[float]
    total: Optional[float]
    grade_letter: Optional[str]
    remark: Optional[str]

class BehavioralTraitsBase(BaseModel):
    neatness: Optional[TraitGrade] = None
    reliability: Optional[TraitGrade] = None
    sense_of_responsibility: Optional[TraitGrade] = None
    relationship_with_students: Optional[TraitGrade] = None
    self_control: Optional[TraitGrade] = None
    obedience: Optional[TraitGrade] = None
    initiative: Optional[TraitGrade] = None
    punctuality: Optional[TraitGrade] = None
    attentiveness: Optional[TraitGrade] = None
    spirit_of_cooperation: Optional[TraitGrade] = None
    affective_domain_remarks: Optional[str] = None

class BehavioralTraitsCreate(BehavioralTraitsBase):
    student_id: str
    class Config:
         orm_mode = True

class BehavioralTraitsResponse(BehavioralTraitsBase):
    id: str  # <-- FIX: Was UUID
    student_id: str  # <-- FIX: Was UUID
    session_id: str  # <-- FIX: Was UUID
    term_id: str  # <-- FIX: Was UUID

    model_config = ConfigDict(from_attributes=True)


class FormClassStudentSummary(BaseModel):
    """A summary of a single student for the Form Teacher's overview."""
    student_id: str
    full_name: str
    admission_number: str
    profile_picture_url: Optional[str] = None
    
    # Academic Summary
    overall_average: Optional[float] = None
    subjects_taken: int = 0
    
    # Financial Summary
    outstanding_balance: float = 0.0
    pending_invoices_count: int = 0

    form_teacher_remark: Optional[str] = None

class FormClassOverviewResponse(BaseModel):
    """The main response model for the Form Teacher's dashboard overview."""
    class_id: str
    class_name: str
    session_name: str
    term_name: str
    students: List[FormClassStudentSummary]


class BulkFormTeacherRemarkItem(BaseModel):
    student_id: str
    remark: FormTeacherRemarkOptions

class BulkFormTeacherRemarkCreate(BaseModel):
    session_id: str
    term_id: str
    class_id: str
    remarks: List[BulkFormTeacherRemarkItem]
# Note: The other Staff dashboard schemas should already be in app/schemas/dashboard.py
# If not, move StaffDashboardResponse, StaffClassResponse, etc., there.