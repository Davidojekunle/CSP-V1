# app/services/bulk_upload_service.py
"""
Service for handling bulk data uploads from files (CSV/Excel).
Contains heavy processing logic extracted from admin.py.
"""
import io

import pandas as pd
from anyio.to_thread import run_sync
from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Tuple

from app.models import User, UserRole, Gender, StudentProfile, StaffProfile
from app.schemas.user import UserCreate, StudentProfileCreate, StaffProfileCreate
from app.services import user_service  # We'll reuse our user creation logic
from app.core.security import get_password_hash

# --- Helper functions directly from your admin.py ---

GENDER_MAP = {"male": "M", "female": "F", "other": "Other"}

def _generate_random_password(length: int = 8) -> str:
    # Re-using the helper from user_service for consistency if it were there,
    # but defining it here to be self-contained.
    import random, string
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def _read_frame(filename: str, content: bytes) -> pd.DataFrame:
    # Read every cell as text: keeps leading zeros in phone numbers and avoids "8012345678.0"
    if filename.endswith('.csv'):
        return pd.read_csv(io.BytesIO(content), dtype=str)
    if filename.endswith(('.xlsx', '.xls')):
        return pd.read_excel(io.BytesIO(content), dtype=str)
    raise HTTPException(status_code=400, detail="Unsupported file format. Use CSV or Excel.")


async def _parse_file(file: UploadFile) -> pd.DataFrame:
    """Reads an UploadFile into a Pandas DataFrame (parsing runs off the event loop)."""
    try:
        content = await file.read()
        return await run_sync(_read_frame, (file.filename or "").lower(), content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read or parse file: {str(e)}")


def _cell(row, key: str) -> str:
    """Stripped cell text; empty string for missing/blank cells (pandas gives NaN, not '')."""
    value = row.get(key)
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


async def process_student_upload(file: UploadFile, session: AsyncSession) -> Dict:
    """
    Processes a student bulk upload file, creating users and profiles.
    Returns a detailed report of successes and failures.
    """
    required_columns = [
        "first_name", "last_name", "email", "phone", "gender", "date_of_birth",
        "enrollment_date", "guardian_name", "guardian_phone", "guardian_email"
    ]
    df = await _parse_file(file)
    
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {missing_cols}")

    successes, failures = [], []
    email_tasks = []

    for idx, row in df.iterrows():
        try:
            # --- Data Validation (identical to original) ---
            email = _cell(row, "email")
            phone = _cell(row, "phone")
            if not email or not phone:
                raise ValueError("Email and phone are required.")

            password = _cell(row, "password") or _generate_random_password()
            gender_str = _cell(row, "gender").lower()
            if gender_str not in GENDER_MAP:
                raise ValueError(f"Invalid gender '{gender_str}'. Must be male, female, or other.")

            # --- Prepare Data Transfer Objects (DTOs) ---
            student_profile_dto = StudentProfileCreate(
                guardian_name=_cell(row, "guardian_name"),
                guardian_phone=_cell(row, "guardian_phone"),
                guardian_email=_cell(row, "guardian_email"),
                enrollment_date=pd.to_datetime(row["enrollment_date"]).date()
            )

            user_create_dto = UserCreate(
                email=email, phone=phone, password=password, role=UserRole.student,
                first_name=_cell(row, "first_name"), last_name=_cell(row, "last_name"),
                gender=GENDER_MAP[gender_str],
                date_of_birth=pd.to_datetime(row["date_of_birth"]).date(),
                student_profile_data=student_profile_dto
            )
            
            # --- Use the existing user_service to create the user ---
            # This demonstrates service-to-service calls and reusability
            new_user = await user_service.create_user_with_profile(user_create_dto, session)
            
            successes.append({
                "email": new_user.email, "username": new_user.username,
                "name": f"{new_user.first_name} {new_user.last_name}"
            })
            
            # Queue up email task details
            email_tasks.append({
                "recipient_email": new_user.email,
                "user_details": {"first_name": new_user.first_name, "username": new_user.username, "password": password}
            })

        except Exception as e:
            # If user_service.create_user_with_profile raises HTTPException, it rolls back.
            # For other errors, we must explicitly rollback.
            await session.rollback()
            failures.append({
                "row": idx + 2, # Account for header row
                "email": _cell(row, "email") or "N/A",
                "error": str(e)
            })

    return {
        "message": "Student bulk upload process completed.",
        "success_count": len(successes),
        "failure_count": len(failures),
        "successes": successes,
        "failures": failures,
        "email_tasks": email_tasks # Pass tasks back to the route
    }

async def process_staff_upload(file: UploadFile, session: AsyncSession) -> Dict:
    """
    Processes a staff/admin bulk upload file, creating users and profiles.
    Returns a detailed report of successes and failures.
    """
    required_columns = [
        "first_name", "last_name", "email", "phone", "gender", "date_of_birth",
        "role", "job_title", "employment_date"
    ]
    df = await _parse_file(file)
    
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {missing_cols}")

    successes, failures = [], []
    email_tasks = []

    for idx, row in df.iterrows():
        try:
            # --- Data Validation (identical to original) ---
            email = _cell(row, "email")
            phone = _cell(row, "phone")
            if not email or not phone:
                raise ValueError("Email and phone are required.")
            
            role_str = _cell(row, "role").lower()
            if role_str not in ['staff', 'admin']:
                raise ValueError(f"Invalid role '{role_str}'. Must be 'staff' or 'admin'")

            password = _cell(row, "password") or _generate_random_password()
            gender_str = _cell(row, "gender").lower()
            if gender_str not in GENDER_MAP:
                raise ValueError(f"Invalid gender '{gender_str}'. Must be male, female, or other.")
                
            # --- Prepare Data Transfer Objects (DTOs) ---
            staff_profile_dto = StaffProfileCreate(
                job_title=_cell(row, "job_title"),
                employment_date=pd.to_datetime(row["employment_date"]).date(),
                qualifications=_cell(row, "qualifications") or None,
                address=_cell(row, "address") or None,
                emergency_contact_name=_cell(row, "emergency_contact_name") or None,
                emergency_contact_phone=_cell(row, "emergency_contact_phone") or None
            )

            user_create_dto = UserCreate(
                email=email, phone=phone, password=password, role=UserRole(role_str),
                first_name=_cell(row, "first_name"), last_name=_cell(row, "last_name"),
                gender=GENDER_MAP[gender_str],
                date_of_birth=pd.to_datetime(row["date_of_birth"]).date(),
                staff_profile_data=staff_profile_dto
            )
            
            # --- Use the existing user_service to create the user ---
            new_user = await user_service.create_user_with_profile(user_create_dto, session)
            
            successes.append({
                "email": new_user.email, "username": new_user.username,
                "name": f"{new_user.first_name} {new_user.last_name}"
            })
            
            # Queue up email task details
            email_tasks.append({
                "recipient_email": new_user.email,
                "user_details": {"first_name": new_user.first_name, "username": new_user.username, "password": password}
            })

        except Exception as e:
            await session.rollback()
            failures.append({
                "row": idx + 2, # Account for header row
                "email": _cell(row, "email") or "N/A",
                "error": str(e)
            })

    return {
        "message": "Staff bulk upload process completed.",
        "success_count": len(successes),
        "failure_count": len(failures),
        "successes": successes,
        "failures": failures,
        "email_tasks": email_tasks
    }