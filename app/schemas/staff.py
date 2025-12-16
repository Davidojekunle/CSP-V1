# app/schemas/staff.py
from pydantic import BaseModel
from typing import Optional
from datetime import date

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