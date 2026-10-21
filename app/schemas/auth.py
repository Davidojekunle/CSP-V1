from datetime import date
from typing import Optional

from pydantic import BaseModel, EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class TokenResponse(BaseModel):
    """Login response - PRESERVED: exact structure"""
    access_token: str
    token_type: str
    user_type: str
    user_id: str
    full_name: str


class UserProfileResponse(BaseModel):
    """
    User profile response. The first seven fields are the original contract; the
    rest are what the dashboard's "My Profile" page displays.
    """
    id: str
    email: str
    username: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    middle_name: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[date] = None
    age: Optional[int] = None
    profile_picture_url: Optional[str] = None
    student_profile: Optional[dict] = None
    staff_profile: Optional[dict] = None


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str