# app/schemas/staff.py
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import date


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





# Note: The other Staff dashboard schemas should already be in app/schemas/dashboard.py
# If not, move StaffDashboardResponse, StaffClassResponse, etc., there.