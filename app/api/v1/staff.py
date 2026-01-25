from fastapi import APIRouter, Depends
from sqlmodel import Session
from typing import List

from app.core.database import get_session
from app.core.auth import get_current_staff # Ensure this dependency exists
from app.models import User
from app.schemas.staff import  StaffProfileUpdate # Add other schemas
from app.schemas.dashboard import StudentDashboardResponse, StaffClassResponse, StaffDashboardStatsResponse, StaffDashboardResponse
from app.schemas.user import UserResponse
from app.services import staff_service, user_service

router = APIRouter(
    prefix="/staff",
    tags=["Staff"],
    dependencies=[Depends(get_current_staff)]
)

# PRESERVED: GET /staff/dashboard
@router.get("/dashboard", response_model=StaffDashboardResponse)
async def get_staff_dashboard(current_user: User = Depends(get_current_staff), db: Session = Depends(get_session)):
    # This logic is already moved from our previous step, just confirming its home
    dashboard_data = staff_service.get_staff_dashboard_data(staff_user=current_user, db=db)
    return dashboard_data

# PRESERVED: GET /staff/my-classes
@router.get("/my-classes", response_model=List[StaffClassResponse])
async def get_my_classes(current_user: User = Depends(get_current_staff), db: Session = Depends(get_session)):
    classes_data = staff_service.get_my_classes(staff_user=current_user, db=db)
    return classes_data

# PRESERVED: GET /staff/me/profile
@router.get("/me/profile", response_model=UserResponse)
async def get_my_staff_profile(current_user: User = Depends(get_current_staff), db: Session = Depends(get_session)):
    # The user_service has the generic, reusable response builder
    return user_service.build_user_response(current_user, db)

# PRESERVED: PUT /staff/me/profile
@router.put("/me/profile", response_model=UserResponse)
async def update_my_staff_profile(
    profile_data: StaffProfileUpdate,
    current_user: User = Depends(get_current_staff),
    db: Session = Depends(get_session)
):
    staff_service.update_staff_profile(staff_user=current_user, profile_data=profile_data.model_dump(exclude_unset=True), db=db)
    # Return the full user object, which will be freshly loaded by the response builder
    return user_service.build_user_response(current_user, db)
