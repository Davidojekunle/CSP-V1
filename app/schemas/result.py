from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from app.models import FormTeacherRemarkOptions 
from enum import Enum

class ResultUpdate(BaseModel):
    ca1: Optional[float] = None
    ca2: Optional[float] = None
    exam: Optional[float] = None

class BulkResultItem(BaseModel):
    student_id: str
    ca1: Optional[float] = None
    ca2: Optional[float] = None
    exam: Optional[float] = None

class BulkResultCreate(BaseModel):
    session_id: str
    term_id: str
    class_id: str
    subject_id: str
    results: List[BulkResultItem]

class BulkFormTeacherRemarkItem(BaseModel):
    student_id: str
    remark: FormTeacherRemarkOptions

class BulkFormTeacherRemarkCreate(BaseModel):
    session_id: str
    term_id: str
    class_id: str
    remarks: List[BulkFormTeacherRemarkItem]


class ResultResponse(BaseModel):
    id: str
    student_id: str
    student_name: str
    student_admission_number: str
    class_id: str
    class_name: str
    subject_id: str
    subject_name: str
    subject_code: str
    session_id: str
    session_name: str
    term_id: str
    term_name: str
    ca1: Optional[float]
    ca2: Optional[float]
    exam: Optional[float]
    total: Optional[float]
    grade_letter: Optional[str]
    remark: Optional[str]
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = "N/A"

class ClassResultSummary(BaseModel):
    class_id: str
    class_name: str
    session_name: str
    term_name: str
    subject_name: Optional[str] = None  
    total_students: int
    students_with_results: int
    class_average: float
    highest_score: Optional[float] = None
    lowest_score: Optional[float] = None
    grade_distribution: Dict[str, int]
    students: List[Dict[str, Any]]


class ResultsDashboardStats(BaseModel):
    total_possible_results: int
    total_results_entered: int
    published_results: int
    pending_entry: int
    total_active_classes: int
    completed_classes: int
    data_discrepancy_warning: bool

class ProgressStatus(str, Enum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    NOT_STARTED = "not_started"


class ClassSubjectProgressItem(BaseModel):
    class_id: str
    class_name: str
    subject_id: str
    subject_name: str
    teacher_name: Optional[str] = "N/A"
    total_students_enrolled: int
    students_with_results: int
    status: ProgressStatus

class ResultsEntryProgressResponse(BaseModel):
    items: List[ClassSubjectProgressItem]


class IncompleteStudentInfo(BaseModel):
    student_name: str
    student_id: str
    expected_results: int
    actual_results: int
    missing_subjects: List[str]

class PublicationReadinessResponse(BaseModel):
    is_published: bool
    total_students_in_scope: int
    complete_students: int
    incomplete_students: int
    students_with_no_results: int
    incomplete_details: List[IncompleteStudentInfo]