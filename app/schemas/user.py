# app/schemas/user.py
from pydantic import BaseModel, EmailStr, field_validator, ValidationInfo
from typing import Optional, List
from datetime import date, datetime
from app.models.base import UserRole, Gender

# Forward-declare profile schemas to avoid circular imports for now
class StudentProfileCreate(BaseModel):
    guardian_name: str
    guardian_phone: str
    guardian_email: EmailStr
    enrollment_date: Optional[date] = None
    address: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_notes: Optional[str] = None

class StaffProfileCreate(BaseModel):
    job_title: str
    employment_date: date
    qualifications: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

# Main User Schemas
class UserBase(BaseModel):
    email: EmailStr
    phone: str
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    gender: Gender
    date_of_birth: date

class UserCreate(UserBase):
    password: str
    role: UserRole
    student_profile_data: Optional[StudentProfileCreate] = None
    staff_profile_data: Optional[StaffProfileCreate] = None

    @field_validator("student_profile_data")
    def validate_student_profile(cls, v, info: ValidationInfo):
        if info.data.get("role") == UserRole.student and not v:
            raise ValueError("Student profile data is required for student users")
        return v

    @field_validator("staff_profile_data")
    def validate_staff_profile(cls, v, info: ValidationInfo):
        if info.data.get("role") == UserRole.staff and not v:
            raise ValueError("Staff profile data is required for staff users")
        return v

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    gender: Optional[Gender] = None
    date_of_birth: Optional[date] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    phone: str
    role: UserRole
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    gender: Gender
    date_of_birth: date
    is_active: bool
    profile_picture_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    student_profile: Optional[dict] = None
    staff_profile: Optional[dict] = None
    enrolled: Optional[bool] = None

    class Config:
        from_attributes = True

class UserBasicInfoResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    username: str
    role: UserRole
    is_active: bool

class AdminPasswordResetRequest(BaseModel):
    new_password: str