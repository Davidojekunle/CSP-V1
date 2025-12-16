# app/services/bulk_upload_service.py
"""
Service for handling bulk data uploads from files (CSV/Excel).
Contains heavy processing logic extracted from admin.py.
"""
import pandas as pd
import io
from fastapi import UploadFile, HTTPException
from sqlmodel import Session
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


def _parse_file(file: UploadFile) -> pd.DataFrame:
    """Reads an UploadFile into a Pandas DataFrame."""
    try:
        content = file.file.read()
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        elif file.filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Use CSV or Excel.")
        return df
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read or parse file: {str(e)}")


async def process_student_upload(file: UploadFile, session: Session) -> Dict:
    """
    Processes a student bulk upload file, creating users and profiles.
    Returns a detailed report of successes and failures.
    """
    required_columns = [
        "first_name", "last_name", "email", "phone", "gender", "date_of_birth",
        "enrollment_date", "guardian_name", "guardian_phone", "guardian_email"
    ]
    df = _parse_file(file)
    
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {missing_cols}")

    successes, failures = [], []
    email_tasks = []

    for idx, row in df.iterrows():
        try:
            # --- Data Validation (identical to original) ---
            email = str(row["email"]).strip()
            phone = str(row["phone"]).strip()
            if not email or not phone:
                raise ValueError("Email and phone are required.")

            password = str(row.get("password", "")).strip() or _generate_random_password()
            gender_str = str(row["gender"]).strip().lower()
            if gender_str not in GENDER_MAP:
                raise ValueError(f"Invalid gender '{gender_str}'. Must be male, female, or other.")

            # --- Prepare Data Transfer Objects (DTOs) ---
            student_profile_dto = StudentProfileCreate(
                guardian_name=str(row["guardian_name"]),
                guardian_phone=str(row["guardian_phone"]),
                guardian_email=str(row["guardian_email"]),
                enrollment_date=pd.to_datetime(row["enrollment_date"]).date()
            )

            user_create_dto = UserCreate(
                email=email, phone=phone, password=password, role=UserRole.student,
                first_name=str(row["first_name"]), last_name=str(row["last_name"]),
                gender=GENDER_MAP[gender_str],
                date_of_birth=pd.to_datetime(row["date_of_birth"]).date(),
                student_profile_data=student_profile_dto
            )
            
            # --- Use the existing user_service to create the user ---
            # This demonstrates service-to-service calls and reusability
            new_user = user_service.create_user_with_profile(user_create_dto, session)
            
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
            session.rollback()
            failures.append({
                "row": idx + 2, # Account for header row
                "email": row.get("email", "N/A"),
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

# app/services/bulk_upload_service.py

# ... (keep all existing imports and functions)

async def process_staff_upload(file: UploadFile, session: Session) -> Dict:
    """
    Processes a staff/admin bulk upload file, creating users and profiles.
    Returns a detailed report of successes and failures.
    """
    required_columns = [
        "first_name", "last_name", "email", "phone", "gender", "date_of_birth",
        "role", "job_title", "employment_date"
    ]
    df = _parse_file(file)
    
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {missing_cols}")

    successes, failures = [], []
    email_tasks = []

    for idx, row in df.iterrows():
        try:
            # --- Data Validation (identical to original) ---
            email = str(row["email"]).strip()
            phone = str(row["phone"]).strip()
            if not email or not phone:
                raise ValueError("Email and phone are required.")
            
            role_str = str(row["role"]).strip().lower()
            if role_str not in ['staff', 'admin']:
                raise ValueError(f"Invalid role '{role_str}'. Must be 'staff' or 'admin'")

            password = str(row.get("password", "")).strip() or _generate_random_password()
            gender_str = str(row["gender"]).strip().lower()
            if gender_str not in GENDER_MAP:
                raise ValueError(f"Invalid gender '{gender_str}'. Must be male, female, or other.")
                
            # --- Prepare Data Transfer Objects (DTOs) ---
            staff_profile_dto = StaffProfileCreate(
                job_title=str(row["job_title"]),
                employment_date=pd.to_datetime(row["employment_date"]).date(),
                qualifications=str(row.get("qualifications", "")).strip() or None,
                address=str(row.get("address", "")).strip() or None,
                emergency_contact_name=str(row.get("emergency_contact_name", "")).strip() or None,
                emergency_contact_phone=str(row.get("emergency_contact_phone", "")).strip() or None
            )

            user_create_dto = UserCreate(
                email=email, phone=phone, password=password, role=UserRole(role_str),
                first_name=str(row["first_name"]), last_name=str(row["last_name"]),
                gender=GENDER_MAP[gender_str],
                date_of_birth=pd.to_datetime(row["date_of_birth"]).date(),
                staff_profile_data=staff_profile_dto
            )
            
            # --- Use the existing user_service to create the user ---
            new_user = user_service.create_user_with_profile(user_create_dto, session)
            
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
            session.rollback()
            failures.append({
                "row": idx + 2, # Account for header row
                "email": row.get("email", "N/A"),
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