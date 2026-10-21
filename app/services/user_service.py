# app/services/user_service.py
"""
Service layer for user management.
Contains all business logic extracted from the original admin.py.
PRESERVED: All logic for username generation and response building is identical.
"""
import re
import random
import string
from datetime import datetime, date
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, and_, or_
from sqlalchemy import func, exists
from fastapi import HTTPException, UploadFile

from app.models import User, UserRole, StudentProfile, StaffProfile, Enrollment, Class
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.core.security import get_password_hash

from app.schemas.student import StudentProfileUpdate
from app.schemas.staff import StaffProfileUpdate
from app.services.image import handler as image_service
# --- Helper functions directly from your admin.py ---

def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
             # Handle cases where datetime might be passed
            return datetime.fromisoformat(value).date()
    raise ValueError("Invalid date format. Must be YYYY-MM-DD string or date object.")

def _generate_random_numbers(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))

async def _generate_student_username(session: AsyncSession) -> str:
    for _ in range(100):
        username = f"CROWNERS{_generate_random_numbers(6)}"
        result = await session.execute(select(User).where(User.username == username))
        if not result.scalars().first():
            return username
    raise HTTPException(status_code=500, detail="Could not generate a unique student username.")

async def _generate_staff_username(first_name: str, last_name: str, session: AsyncSession) -> str:
    first_clean = re.sub(r'[^a-zA-Z]', '', first_name).lower()
    last_clean = re.sub(r'[^a-zA-Z]', '', last_name).lower()
    base_username = f"{first_clean}.{last_clean}"
    
    username = base_username
    for i in range(100):
        result = await session.execute(select(User).where(User.username == username))
        if not result.scalars().first():
            return username
        username = f"{base_username}{i+1}"
    raise HTTPException(status_code=500, detail="Could not generate a unique staff username.")

async def get_all_students(
    db: AsyncSession,
    skip: int,
    limit: int,
    search: Optional[str],
    is_active: Optional[bool],
    enrolled: Optional[bool]
) -> tuple[List[User], int]:
    """
    PERFORMANCE OPTIMIZED: Gets all students with advanced filtering, including
    enrollment status, using an efficient subquery.
    """
    # Start with a base query for users who are students
    query = select(User).where(User.role == UserRole.student)
    
    conditions = []
    
    # Standard filters from get_all_users
    if is_active is not None:
        conditions.append(User.is_active == is_active)
        
    if search:
        search_term = f"%{search.strip()}%"
        conditions.append(or_(
            User.first_name.ilike(search_term),
            User.last_name.ilike(search_term),
            User.username.ilike(search_term),
            User.email.ilike(search_term)
        ))

    # --- THIS IS THE NEW LOGIC ---
    # Replicates the original `exists()` subquery for performance
    if enrolled is not None:
        # Subquery to check for an active enrollment for the user
        enrollment_subquery = select(Enrollment.id).where(
            Enrollment.student_id == User.id,
            Enrollment.is_active == True
        ).correlate(User) # Link subquery to the main User query
        
        if enrolled:
            # Find students where an active enrollment EXISTS
            conditions.append(exists(enrollment_subquery))
        else:
            # Find students where an active enrollment DOES NOT EXIST
            conditions.append(~exists(enrollment_subquery))

    if conditions:
        query = query.where(and_(*conditions))

    # Get total count based on the fully filtered query
    count_query = select(func.count()).select_from(query.subquery())
    result = await db.execute(count_query)
    total_count = result.scalar()

    # Apply pagination and ordering
    paginated_query = query.order_by(User.last_name, User.first_name, User.id).offset(skip).limit(limit)
    result = await db.execute(paginated_query)
    users = result.scalars().all()
    
    return users, total_count

async def _generate_admission_number(session: AsyncSession) -> str:
    """Generate unique admission number with format ADM + current year + random numbers"""
    current_year = datetime.now().year
    for _ in range(100):
        admission_number = f"ADM{current_year}{_generate_random_numbers(4)}"
        result = await session.execute(select(StudentProfile).where(StudentProfile.admission_number == admission_number))
        if not result.scalars().first():
            return admission_number
    raise HTTPException(status_code=500, detail="Could not generate unique admission number.")

async def _generate_staff_number(session: AsyncSession) -> str:
    """Generate unique staff number with format STAFF + current year + random numbers"""
    current_year = datetime.now().year
    for _ in range(100):
        staff_number = f"STAFF{current_year}{_generate_random_numbers(4)}"
        result = await session.execute(select(StaffProfile).where(StaffProfile.staff_no == staff_number))
        if not result.scalars().first():
            return staff_number
    raise HTTPException(status_code=500, detail="Could not generate unique staff number.")

# --- CRITICAL: Preserving the exact response shape ---
async def build_user_responses(users: List[User], session: AsyncSession) -> List[UserResponse]:
    """
    Build fully structured UserResponse objects for many users with a fixed
    number of queries (instead of up to 3 per user).
    """
    if not users:
        return []
    student_ids = [u.id for u in users if u.role == UserRole.student]
    staff_ids = [u.id for u in users if u.role == UserRole.staff]

    enrolled_ids, student_profiles, class_names, staff_profiles = set(), {}, {}, {}
    if student_ids:
        enrolled_ids = set((await session.execute(
            select(Enrollment.student_id).where(Enrollment.student_id.in_(student_ids), Enrollment.is_active == True)
        )).scalars().all())
        for profile in (await session.execute(select(StudentProfile).where(StudentProfile.user_id.in_(student_ids)))).scalars().all():
            student_profiles.setdefault(profile.user_id, profile)
        class_ids = {p.current_class_id for p in student_profiles.values() if p.current_class_id}
        if class_ids:
            class_names = dict((await session.execute(select(Class.id, Class.name).where(Class.id.in_(class_ids)))).all())
    if staff_ids:
        for profile in (await session.execute(select(StaffProfile).where(StaffProfile.user_id.in_(staff_ids)))).scalars().all():
            staff_profiles.setdefault(profile.user_id, profile)

    responses = []
    for user in users:
        user_dict = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "middle_name": user.middle_name,
            "gender": user.gender,
            "date_of_birth": user.date_of_birth,
            "is_active": user.is_active,
            "profile_picture_url": user.profile_picture_url,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "student_profile": None,
            "staff_profile": None,
            "enrolled": None,
        }

        if user.role == UserRole.student:
            user_dict["enrolled"] = user.id in enrolled_ids
            student_profile = student_profiles.get(user.id)
            if student_profile:
                user_dict["student_profile"] = {
                    "admission_number": student_profile.admission_number,
                    "guardian_name": student_profile.guardian_name,
                    "guardian_phone": student_profile.guardian_phone,
                    "guardian_email": student_profile.guardian_email,
                    "current_class_id": student_profile.current_class_id,
                    "current_class_name": class_names.get(student_profile.current_class_id),
                    "enrollment_date": student_profile.enrollment_date,
                    "address": student_profile.address,
                    "blood_group": student_profile.blood_group,
                    "allergies": student_profile.allergies,
                    "medical_notes": student_profile.medical_notes,
                    "status": student_profile.status,
                }

        elif user.role == UserRole.staff:
            staff_profile = staff_profiles.get(user.id)
            if staff_profile:
                user_dict["staff_profile"] = {
                    "staff_no": staff_profile.staff_no,
                    "job_title": staff_profile.job_title,
                    "employment_date": staff_profile.employment_date,
                    "qualifications": staff_profile.qualifications,
                    "address": staff_profile.address,
                    "emergency_contact_name": staff_profile.emergency_contact_name,
                    "emergency_contact_phone": staff_profile.emergency_contact_phone,
                }

        responses.append(UserResponse.model_validate(user_dict))
    return responses


async def build_user_response(user: User, session: AsyncSession) -> UserResponse:
    """Build and return a fully structured UserResponse with all relationships."""
    return (await build_user_responses([user], session))[0]


# --- Service Functions wrapping the business logic ---

async def get_user_by_id(user_id: str, session: AsyncSession) -> User | None:
    return await session.get(User, user_id)

async def get_all_users(
    session: AsyncSession,
    skip: int,
    limit: int,
    role: UserRole | None = None,
    is_active: bool | None = None,
    search: str | None = None,
):
    """Fetch a filtered, paginated list of users."""
    query = select(User)

    conditions = []
    if role is not None:
        conditions.append(User.role == role)
    if is_active is not None:
        conditions.append(User.is_active == is_active)
    if search:
        search_term = f"%{search.strip()}%"
        conditions.append(
            or_(
                User.first_name.ilike(search_term),
                User.last_name.ilike(search_term),
                User.username.ilike(search_term),
                User.email.ilike(search_term),
            )
        )

    if conditions:
        query = query.where(and_(*conditions))

    result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total_count = result.scalar()

    result = await session.execute(query.order_by(User.created_at, User.id).offset(skip).limit(limit))
    users = result.scalars().all()

    return users, total_count

async def create_user_with_profile(user_data: UserCreate, session: AsyncSession) -> User:
    """
    Creates a new user and their corresponding profile in a single transaction.
    Logic is identical to the original create_user_with_profile endpoint.
    """
    result = await session.execute(select(User).where(or_(User.email == user_data.email, User.phone == user_data.phone)))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email or phone number already exists")

    username = (await _generate_student_username(session) if user_data.role == UserRole.student
                else await _generate_staff_username(user_data.first_name, user_data.last_name, session))

    new_user = User(
        username=username,
        email=user_data.email,
        phone=user_data.phone,
        password_hash= await get_password_hash(user_data.password),
        role=user_data.role,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        middle_name=user_data.middle_name,
        gender=user_data.gender,
        date_of_birth=_parse_date(user_data.date_of_birth),
    )
    session.add(new_user)
    await session.flush()  # Assigns an ID to new_user before commit

    if user_data.role == UserRole.student:
        if not user_data.student_profile_data:
            raise HTTPException(status_code=400, detail="Student profile data is required")
        
        student_profile = StudentProfile(
            user_id=new_user.id,
            admission_number=await _generate_admission_number(session),
            **user_data.student_profile_data.model_dump()
        )
        session.add(student_profile)

    elif user_data.role == UserRole.staff:
        if not user_data.staff_profile_data:
            raise HTTPException(status_code=400, detail="Staff profile data is required")
        
        staff_profile = StaffProfile(
            user_id=new_user.id,
            staff_no=await _generate_staff_number(session),
            **user_data.staff_profile_data.model_dump()
        )
        session.add(staff_profile)

    await session.commit()
    await session.refresh(new_user)
    return new_user
async def update_user(user_id: str, user_data: UserUpdate, session: AsyncSession) -> User:
    """
    Updates a user's details.
    Logic is identical to the original update_user endpoint.
    """
    user_to_update = await get_user_by_id(user_id, session)
    if not user_to_update:
        return None # Let the route handle the 404

    # Check for conflicts
    if user_data.email or user_data.phone:
        conditions = []
        if user_data.email: conditions.append(User.email == user_data.email)
        if user_data.phone: conditions.append(User.phone == user_data.phone)
        
        result = await session.execute(select(User).where(and_(User.id != user_id, or_(*conditions))))
        existing_user = result.scalars().first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email or phone already exists")

    update_data = user_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "date_of_birth" and value:
            setattr(user_to_update, field, _parse_date(value))
        else:
            setattr(user_to_update, field, value)
    
    user_to_update.updated_at = datetime.utcnow()
    
    session.add(user_to_update)
    await session.commit()
    await session.refresh(user_to_update)
    return user_to_update

async def set_user_active_status(user_id: str, is_active: bool, session: AsyncSession) -> User:
    """
    Sets a user's active status (deactivate or reactivate).
    """
    user = await get_user_by_id(user_id, session)
    if not user:
        return None

    user.is_active = is_active
    user.updated_at = datetime.utcnow()
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

async def reset_user_password(user_id: str, new_password: str, session: AsyncSession) -> User:
    """
    Resets a user's password (admin action).
    """
    user = await get_user_by_id(user_id, session)
    if not user:
        return None

    user.password_hash =await get_password_hash(new_password)
    user.updated_at = datetime.utcnow()
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
async def update_student_profile(user_id: str, profile_data: StudentProfileUpdate, session: AsyncSession) -> StudentProfile:
    """Updates a student's profile."""
    result = await session.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    profile = result.scalars().first()
    if not profile:
        return None

    update_data = profile_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(profile, key, value)
    
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def update_staff_profile(user_id: str, profile_data: StaffProfileUpdate, session: AsyncSession) -> StaffProfile:
    """Updates a staff member's profile."""
    result = await session.execute(select(StaffProfile).where(StaffProfile.user_id == user_id))
    profile = result.scalars().first()
    if not profile:
        return None

    update_data = profile_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(profile, key, value)
    
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def update_user_profile_picture(user_id: str, file: UploadFile, session: AsyncSession) -> User:
    """Handles profile picture upload and updates the user record."""
    user = await get_user_by_id(user_id, session)
    if not user:
        return None

    # First, delete the old picture if it exists
    if user.profile_picture_url:
        # We don't need the current URL for the Cloudinary implementation
        await image_service.delete_profile_picture(user_id)
        
    # Upload the new picture
    image_url = await image_service.upload_profile_picture(file, user_id)
    
    # Save the new URL to the user record
    user.profile_picture_url = image_url
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user_profile_picture(user_id: str, session: AsyncSession) -> User:
    """Handles profile picture deletion."""
    user = await get_user_by_id(user_id, session)
    if not user or not user.profile_picture_url:
        return None # Let the route handle the 404/400
        
    await image_service.delete_profile_picture(user_id)
    
    user.profile_picture_url = None
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
# ... More service functions for create, update, delete will be added here as we refactor more endpoints