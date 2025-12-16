from pydantic import BaseModel, EmailStr
from typing import Optional


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
    """User profile response - PRESERVED: exact structure"""
    id: str
    email: str
    username: str
    first_name: str
    last_name: str
    role: str
    is_active: bool


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str