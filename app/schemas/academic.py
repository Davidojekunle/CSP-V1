# app/schemas/academic.py
"""
Pydantic schemas for all academic structure models.
PRESERVED: All field names and types are identical to the original API contract.
"""
from pydantic import BaseModel
from typing import List, Optional
from app.models import TermName, PromotionType # Import enums from your models

# --- Schemas for Academic Sessions ---

class AcademicSessionCreate(BaseModel):
    name: str
    start_date: str
    end_date: str
    is_current: bool = False

class AcademicSessionUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_current: Optional[bool] = None

class AcademicSessionResponse(BaseModel):
    id: str
    name: str
    start_date: str
    end_date: str
    is_current: bool
    terms_count: int = 0

# --- Schemas for Terms ---

class TermCreate(BaseModel):
    session_id: str
    name: TermName
    start_date: str
    end_date: str
    is_current: bool = False

class TermUpdate(BaseModel):
    name: Optional[TermName] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_current: Optional[bool] = None

class TermResponse(BaseModel):
    id: str
    session_id: str
    session_name: str
    name: TermName
    start_date: str
    end_date: str
    is_current: bool

# --- Schemas for Classes ---

class ClassCreate(BaseModel):
    name: str
    level: str
    arm: str
    form_teacher_id: Optional[str] = None
    promotion_type: PromotionType = PromotionType.promote

class ClassUpdate(BaseModel):
    name: Optional[str] = None
    level: Optional[str] = None
    arm: Optional[str] = None
    form_teacher_id: Optional[str] = None
    promotion_type: Optional[PromotionType] = None
    is_active: Optional[bool] = None

class ClassResponse(BaseModel):
    id: str
    name: str
    level: str
    arm: str
    form_teacher_id: Optional[str]
    form_teacher_name: Optional[str]
    is_active: bool
    promotion_type: PromotionType
    students_count: int = 0
    subjects_count: int = 0

class StudentInClassResponse(BaseModel):
    id: str
    admission_number: str
    first_name: str
    last_name: str
    email: str
    phone: str
    date_of_birth: str
    gender: str
    enrollment_date: str
    is_active: bool
    session_name: str
    guardian_name: str
    guardian_phone: str
    guardian_email: str
    
# --- Schemas for Subjects ---

class SubjectCreate(BaseModel):
    code: str
    name: str

class SubjectUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    is_active: Optional[bool] = None

class SubjectResponse(BaseModel):
    id: str
    code: str
    name: str
    is_active: bool
    classes_count: int = 0

# --- Schemas for Class-Subject Assignments ---

class ClassSubjectAssign(BaseModel):
    class_id: str
    subject_id: str
    teacher_id: str

class ClassSubjectUpdate(BaseModel):
    teacher_id: str

class ClassSubjectResponse(BaseModel):
    id: str
    class_id: str
    class_name: str
    subject_id: str
    subject_name: str
    subject_code: str
    teacher_id: str
    teacher_name: str