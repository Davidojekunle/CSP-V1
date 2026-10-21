# app/api/v1/users.py
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status, UploadFile, File
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any

from app.core.database import get_session
from app.core.auth import get_current_admin
from app.models import User, UserRole, ActivityAction 
from app.schemas.user import UserResponse, UserCreate, UserUpdate, UserBasicInfoResponse
from app.schemas.student import StudentProfileUpdate
from app.schemas.staff import StaffProfileUpdate
from app.schemas.common import UserIdsRequest

from app.services import user_service, activity_log_service
from app.services.email.sender import send_welcome_email 

router = APIRouter()

# PRESERVED: GET /admin/users
@router.get("/users", response_model=Dict[str, Any])
async def get_all_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    role: Optional[UserRole] = Query(None),
    is_active: Optional[bool] = Query(None, alias="isActive"),
    search: Optional[str] = Query(None),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """OPTIMIZED: Get all users with eager loading"""
    # ADDED: await
    users, total_count = await user_service.get_all_users(

        session=db, skip=skip, limit=limit, role=role, is_active=is_active, search=search
    )

    # ADDED: await inside list comprehension
    user_responses = await user_service.build_user_responses(users, db)

    return {
        "users": user_responses,
        "total": total_count,
        "skip": skip,
        "limit": limit,
        "has_more": skip + limit < total_count
    }

# PRESERVED: GET /admin/users/{user_id}
@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: str,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """Get user by ID with profile information"""
    # ADDED: await
    user = await user_service.get_user_by_id(user_id=user_id, session=db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # ADDED: await
    return await user_service.build_user_response(user, db)

@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """Creates a new user and profile in an atomic transaction."""
    try:
        # ADDED: await
        new_user = await user_service.create_user_with_profile(user_data, db)
        
        log_details = f"Created new {new_user.role.value}: {new_user.first_name} {new_user.last_name}"
        await activity_log_service.log_activity(
            session=db,
            actor=current_admin,
            action=ActivityAction.USER_CREATED,
            details=log_details,
            target_id=new_user.id,
            target_type="User"
        )
        await db.commit()

        user_details_for_email = {
            "first_name": new_user.first_name,
            "username": new_user.username,
            "password": user_data.password
        }
        background_tasks.add_task(
            send_welcome_email,
            recipient_email=new_user.email,
            user_details=user_details_for_email
        )

        return await user_service.build_user_response(new_user, db)
    except HTTPException as e:
        await db.rollback()
        raise e
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")
    
@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user_details(
    user_id: str,
    user_data: UserUpdate,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """Update user information"""
    # ADDED: await
    updated_user = await user_service.update_user(user_id=user_id, user_data=user_data, session=db)
    
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    return await user_service.build_user_response(updated_user, db)

@router.post("/users/{user_id}/activate", response_model=Dict[str, str])
async def activate_user(
    user_id: str,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """Reactivate deactivated user"""
    # ADDED: await
    user = await user_service.set_user_active_status(user_id=user_id, is_active=True, session=db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": f"User {user.username} activated successfully"}

@router.post("/users/{user_id}/reset-password", response_model=Dict[str, str])
async def reset_user_password_by_admin(
    user_id: str,
    new_password: str = Query(...),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """Reset user password (admin only)"""
    # ADDED: await
    user = await user_service.reset_user_password(
        user_id=user_id, new_password=new_password, session=db
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {"message": f"Password reset successfully for user {user.username}"}

@router.put("/users/{user_id}/student-profile", response_model=Dict[str, str])
async def update_student_profile_details(
    user_id: str,
    profile_data: StudentProfileUpdate,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    # ADDED: await
    profile = await user_service.update_student_profile(user_id, profile_data, db)
    if not profile:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    return {"message": "Student profile updated successfully."}

@router.put("/users/{user_id}/staff-profile", response_model=Dict[str, str])
async def update_staff_profile_details(
    user_id: str,
    profile_data: StaffProfileUpdate,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    # ADDED: await
    profile = await user_service.update_staff_profile(user_id, profile_data, db)
    if not profile:
        raise HTTPException(status_code=404, detail="Staff profile not found.")
    return {"message": "Staff profile updated successfully."}

@router.get("/students", response_model=Dict[str, Any], tags=["Admin - User Management"])
async def get_all_students(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    enrolled: Optional[bool] = Query(None),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """Get all students with filtering, including enrollment status."""
    # ADDED: await
    students, total_count = await user_service.get_all_students(
        db=db, skip=skip, limit=limit, search=search, is_active=is_active, enrolled=enrolled
    )
    
    # ADDED: await inside comprehension
    student_responses = await user_service.build_user_responses(students, db)
    
    return {
        "users": student_responses,
        "total": total_count,
        "skip": skip,
        "limit": limit,
        "has_more": skip + limit < total_count
    }

# PRESERVED: GET /admin/staff
@router.get("/staff", response_model=Dict[str, Any], tags=["Admin - User Management"])
async def get_all_staff(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """Get all staff members."""
    # Logic: Redirect to get_all_users but with role=staff. Already correctly awaited inside get_all_users call.
    return await get_all_users(
        skip=skip, limit=limit, role=UserRole.staff, search=search, current_admin=current_admin, db=db, is_active=None
    )

# PRESERVED: POST /admin/users/{user_id}/upload-profile-picture
@router.post("/users/{user_id}/upload-profile-picture", response_model=Dict[str, str])
async def upload_profile_picture(
    user_id: str,
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.update_user_profile_picture(user_id, file, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"message": "Profile picture updated successfully.", "profile_picture_url": user.profile_picture_url}

# PRESERVED: DELETE /admin/users/{user_id}/profile-picture
@router.delete("/users/{user_id}/profile-picture", response_model=Dict[str, str])
async def delete_profile_picture(
    user_id: str,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.delete_user_profile_picture(user_id, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found or has no profile picture.")
    return {"message": "Profile picture deleted successfully."}

@router.delete("/users/{user_id}", response_model=Dict[str, str])
async def deactivate_user_delete(
    user_id: str,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    """Deactivate user (soft delete)."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    # ADDED: await
    user = await user_service.set_user_active_status(user_id=user_id, is_active=False, session=db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": f"User {user.username} deactivated successfully"}

@router.post("/users/by-ids", response_model=List[UserBasicInfoResponse])
async def get_users_by_ids(
    request_data: UserIdsRequest,
    db: AsyncSession = Depends(get_session)
):
    """Efficiently fetches basic information for a list of user IDs."""
    if not request_data.user_ids:
        return []

    # Execute statement and get scalars
    result = await db.execute(select(User).where(User.id.in_(request_data.user_ids)))
    users = result.scalars().all()
    
    return users