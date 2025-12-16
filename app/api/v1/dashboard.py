# app/api/v1/dashboard.py
"""
New, refactored API routes for all dashboard statistics.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session
from typing import List

from app.core.database import get_session
from app.core.auth import get_current_admin
from app.models import User
from app.schemas.dashboard import (
    AdminDashboardStatsResponse,
    StudentDashboardStatsResponse,
    StaffDashboardStatsResponse,
    FeeCollectionOverviewResponse,
    SessionEnrollmentStats
)

from app.services import dashboard_service

# The prefix will be applied in the main router, preserving /admin/dashboard/... paths
router = APIRouter(
    tags=["Admin - Dashboard"],
    dependencies=[Depends(get_current_admin)]
)

# PRESERVED: GET /admin/dashboard/stats
@router.get("/dashboard/stats", response_model=AdminDashboardStatsResponse)
async def get_dashboard_stats(session: Session = Depends(get_session)):
    stats = dashboard_service.get_general_dashboard_stats(session)
    return stats

# PRESERVED: GET /admin/dashboard/student-stats
@router.get("/dashboard/student-stats", response_model=StudentDashboardStatsResponse)
async def get_student_dashboard_stats(session: Session = Depends(get_session)):
    stats = dashboard_service.get_student_dashboard_stats(session)
    return stats

# PRESERVED: GET /admin/dashboard/staff-stats
@router.get("/dashboard/staff-stats", response_model=StaffDashboardStatsResponse)
async def get_staff_dashboard_stats(session: Session = Depends(get_session)):
    stats = dashboard_service.get_staff_dashboard_stats(session)
    return stats

# PRESERVED: GET /admin/dashboard/fee-collection-overview
@router.get("/dashboard/fee-collection-overview", response_model=FeeCollectionOverviewResponse)
async def get_fee_collection_overview(session: Session = Depends(get_session)):
    stats = dashboard_service.get_fee_collection_overview(session)
    return stats

@router.get("/enrollment/stats/by-session", response_model=List[SessionEnrollmentStats])
async def get_enrollment_stats_by_session(db: Session = Depends(get_session)):
    """
    Get unique student enrollment counts grouped by academic session.
    """
    stats = dashboard_service.get_enrollment_stats_by_session(db)
    return stats