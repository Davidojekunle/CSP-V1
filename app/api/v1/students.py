# app/api/v1/students.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.auth import get_current_student
from app.models import User
from app.schemas.dashboard import StudentDashboardResponse
from app.services import student_service

router = APIRouter(prefix="/student", tags=["Student Dashboard"])

# PRESERVED: GET /dashboard/student/dashboard
@router.get("/dashboard", response_model=StudentDashboardResponse)
async def get_student_dashboard(
    current_user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_session)
):
    """
    Returns aggregated dashboard data for the logged-in student.
    Matches the original response contract exactly.
    """
    return await student_service.get_student_dashboard_data(current_user, db)