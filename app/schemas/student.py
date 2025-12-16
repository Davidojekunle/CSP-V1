# app/schemas/student.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import date

class StudentProfileCreate(BaseModel):
    guardian_name: str
    guardian_phone: str
    guardian_email: EmailStr
    enrollment_date: date
    address: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_notes: Optional[str] = None

class StudentProfileUpdate(BaseModel):
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    guardian_email: Optional[EmailStr] = None
    address: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_notes: Optional[str] = None