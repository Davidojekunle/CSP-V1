# app/schemas/dashboard.py
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# From admin.py
class FeeCollectionOverviewResponse(BaseModel):
    paid_amount: float
    pending_amount: float
    overdue_amount: float

class StaffDashboardStatsResponse(BaseModel):
    total_staff_and_admins: int
    administrators: int
    active_staff_and_admins: int
    new_this_month: int

class StudentDashboardStatsResponse(BaseModel):
    total_students: int
    active_students: int
    inactive_students: int
    new_this_month: int
    male_students: int
    female_students: int

class AdminDashboardStatsResponse(BaseModel):
    totalUsers: int
    activeUsers: int
    totalStudents: int
    totalStaff: int
    totalAdmins: int
    newStudentsLast30Days: int
    newStaffLast30Days: int
    unenrolledStudents: int

# From student_staff_dashboard.py
class GuardianInfo(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

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

class ResultsSummary(BaseModel):
    average_score: float
    context_period: Optional[str] = "N/A"
    total_released_results: int

class FinancialSummary(BaseModel):
    current_bill: float
    pending_payments: int

class StudentDashboardResponse(BaseModel):
    user_info: StudentInfo
    current_enrollment: Optional[Dict[str, Any]]
    results_summary: ResultsSummary
    financial_summary: FinancialSummary
    available_reports: List[Dict[str, Any]]

class SessionEnrollmentStats(BaseModel):
    session_id: str
    session_name: str
    total_students: int
    active_students: int