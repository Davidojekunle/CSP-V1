from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status, UploadFile, File
from sqlmodel import Session, select
from typing import List, Optional, Dict, Any

from app.core.database import get_session
from app.core.auth import get_current_admin

from app.models import User, UserRole
from app.models import User, UserRole, ActivityAction 

from app.schemas.user import UserResponse, UserCreate, UserUpdate, UserBasicInfoResponse
from app.schemas.student import StudentProfileUpdate
from app.schemas.staff import StaffProfileUpdate
from app.schemas.common import UserIdsRequest


from app.services import user_service, activity_log_service
from app.services.email.sender import send_welcome_email 

router = APIRouter()

# PRESERVED: GET /admin/users (via prefix)
# PRESERVED: response_model is a dict to match your original complex response
@router.get("/users", response_model=Dict[str, Any])
async def get_all_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    role: Optional[UserRole] = Query(None),
    is_active: Optional[bool] = Query(None, alias="isActive"), # Use alias for frontend compatibility if needed
    search: Optional[str] = Query(None),
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """OPTIMIZED: Get all users with eager loading"""
    users, total_count = user_service.get_all_users(
        session=session, skip=skip, limit=limit, role=role, is_active=is_active, search=search
    )

    # The user_service.build_user_response ensures the response shape is identical
    user_responses = [user_service.build_user_response(user, session) for user in users]

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
    session: Session = Depends(get_session)
):
    """Get user by ID with profile information"""
    user = user_service.get_user_by_id(user_id=user_id, session=session)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # CRITICAL: We call the exact same response builder function
    return user_service.build_user_response(user, session)

@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks, # <-- RE-ENABLE this
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Creates a new user and their corresponding profile in a single, atomic transaction.
    """
    try:
        new_user = user_service.create_user_with_profile(user_data, session)
        
        # LOG ACTIVITY
        log_details = f"Created new {new_user.role.value}: {new_user.first_name} {new_user.last_name}"
        await activity_log_service.log_activity(
            session=session,
            actor=current_admin,
            action=ActivityAction.USER_CREATED,
            details=log_details,
            target_id=new_user.id,
            target_type="User"
        )
        # Commit the log entry along with the user creation
        session.commit()

        # SEND WELCOME EMAIL IN THE BACKGROUND
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

        return user_service.build_user_response(new_user, session)
    except HTTPException as e:
        session.rollback() # Rollback if any part fails
        raise e
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")
    
@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user_details(
    user_id: str,
    user_data: UserUpdate,
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Update user information"""
    updated_user = user_service.update_user(user_id=user_id, user_data=user_data, session=session)
    
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # TODO: Add activity logging here
    
    # CRITICAL: We call the exact same response builder function
    return user_service.build_user_response(updated_user, session)

@router.post("/users/{user_id}/activate", response_model=Dict[str, str])
async def activate_user(
    user_id: str,
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Reactivate deactivated user"""
    user = user_service.set_user_active_status(user_id=user_id, is_active=True, session=session)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # TODO: Log activity
    
    return {"message": f"User {user.username} activated successfully"}


# A simple schema for the password reset request body


# PRESERVED: POST /admin/users/{user_id}/reset-password
@router.post("/users/{user_id}/reset-password", response_model=Dict[str, str])
async def reset_user_password_by_admin(
    user_id: str,
    new_password: str = Query(...), # <-- CORRECTED: Accept as a query parameter
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Reset user password (admin only)"""
    user = user_service.reset_user_password(
        user_id=user_id, new_password=new_password, session=session
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # TODO: Log activity
    
    return {"message": f"Password reset successfully for user {user.username}"}


@router.put("/users/{user_id}/student-profile", response_model=Dict[str, str])
async def update_student_profile_details(
    user_id: str,
    profile_data: StudentProfileUpdate,
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    profile = user_service.update_student_profile(user_id, profile_data, session)
    if not profile:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    return {"message": "Student profile updated successfully."}


# PRESERVED: PUT /admin/users/{user_id}/staff-profile
@router.put("/users/{user_id}/staff-profile", response_model=Dict[str, str])
async def update_staff_profile_details(
    user_id: str,
    profile_data: StaffProfileUpdate,
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    profile = user_service.update_staff_profile(user_id, profile_data, session)
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
    current_admin: User = Depends(get_current_admin), # Corrected dependency
    session: Session = Depends(get_session)
):
    """
    Get all students with filtering, now including enrollment status.
    """
    # Call the new, specialized service function
    students, total_count = user_service.get_all_students(
        db=session,
        skip=skip,
        limit=limit,
        search=search,
        is_active=is_active,
        enrolled=enrolled
    )
    
    # CRITICAL: Reuse the exact same response builder to preserve the API contract
    student_responses = [user_service.build_user_response(student, session) for student in students]
    
    return {
        "users": student_responses, # The key must be "users" to match your original contract
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
    session: Session = Depends(get_session)
):
    """Get all staff members. This is a specialized view of the main user list."""
    return await get_all_users(
        skip=skip,
        limit=limit,
        role=UserRole.staff, # <-- This is the key filter
        is_active=None, # The original endpoint did not filter by active status for staff
        search=search,
        current_admin=current_admin,
        session=session
    )

# PRESERVED: POST /admin/users/{user_id}/upload-profile-picture
@router.post("/users/{user_id}/upload-profile-picture", response_model=Dict[str, str])
async def upload_profile_picture(
    user_id: str,
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    user = await user_service.update_user_profile_picture(user_id, file, session)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"message": "Profile picture updated successfully.", "profile_picture_url": user.profile_picture_url}


# PRESERVED: DELETE /admin/users/{user_id}/profile-picture
@router.delete("/users/{user_id}/profile-picture", response_model=Dict[str, str])
async def delete_profile_picture(
    user_id: str,
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    user = await user_service.delete_user_profile_picture(user_id, session)
    if not user:
        raise HTTPException(status_code=404, detail="User not found or has no profile picture.")
    return {"message": "Profile picture deleted successfully."}


@router.delete("/users/{user_id}", response_model=Dict[str, str])
async def deactivate_user_delete(
    user_id: str,
    current_admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """Deactivate user (soft delete) - handles the DELETE method."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user = user_service.set_user_active_status(user_id=user_id, is_active=False, session=session)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # TODO: Log activity
    
    return {"message": f"User {user.username} deactivated successfully"}

@router.post("/users/by-ids", response_model=List[UserBasicInfoResponse])
async def get_users_by_ids(
    request_data: UserIdsRequest,
    db: Session = Depends(get_session)
):
    """
    Efficiently fetches basic information for a list of user IDs.
    """
    if not request_data.user_ids:
        return []

    users = db.exec(select(User).where(User.id.in_(request_data.user_ids))).all()
    
    return users