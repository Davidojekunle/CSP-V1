# app/schemas/enrollment.py
"""Pydantic schemas for student enrollment."""
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# --- Request Schemas ---
class EnrollmentCreate(BaseModel):
    student_id: str
    class_id: str
    session_id: str
    term_id: str
    enrolled_at: Optional[str] = None  # YYYY-MM-DD, defaults to today

class StudentEnrollmentHistory(BaseModel):
    student_id: str
    enrollments: List[dict]  # List of enrollment records
    

class EnrollmentUpdate(BaseModel):
    class_id: Optional[str] = None
    is_active: Optional[bool] = None

class BulkEnrollmentCreate(BaseModel):
    student_ids: List[str]
    class_id: str
    session_id: str
    term_id: str
    enrolled_at: Optional[str] = None

class EnrollmentTransfer(BaseModel):
    new_class_id: str
    transfer_date: Optional[str] = None  # YYYY-MM-DD

class SessionTransitionData(BaseModel):
    new_session_id: str
    new_term_id: str
    class_promotions: List[dict]  # [{"old_class_id": "...", "new_class_id": "..."}]
    transition_date: Optional[str] = None

# --- Response Schemas ---
class EnrollmentResponse(BaseModel):
    id: str
    student_id: str
    student_name: str
    student_admission_number: str
    class_id: str
    class_name: str
    session_id: str
    session_name: str
    term_id: str
    term_name: str
    is_active: bool
    enrolled_at: str
    created_at: datetime

class PaginatedEnrollmentResponse(BaseModel):
    total_records: int
    enrollments: List[EnrollmentResponse]

class DashboardStatsResponse(BaseModel):
    total_enrollments: int
    active_students: int
    current_session_name: Optional[str] = "N/A"
    pending_transitions: int

class ClassEnrollmentSummary(BaseModel):
    class_id: str
    class_name: str
    session_name: str
    term_name: str
    total_students: int
    active_enrollments: int
    inactive_enrollments: int
    students: List[dict]

class BulkClassUpdateData(BaseModel):
    session_id: str
    term_id: str
    student_class_mappings: List[dict]  # e.g., [{"student_id": "...", "new_class_id": "..."}]
    enrollment_date: Optional[str] = None