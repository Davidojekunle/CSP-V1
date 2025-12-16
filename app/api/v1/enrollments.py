# app/api/v1/enrollments.py
"""New, refactored API routes for student enrollment management."""
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlmodel import Session, select
from datetime import datetime
from typing import List, Optional, Dict

from app.core.database import get_session
from app.core.auth import get_current_admin
from app.models import User, StudentProfile, Class, AcademicSession, Term
from app.schemas.enrollment import (
    PaginatedEnrollmentResponse, EnrollmentResponse, DashboardStatsResponse,
      BulkEnrollmentCreate, EnrollmentTransfer,
        SessionTransitionData, EnrollmentUpdate, StudentEnrollmentHistory, ClassEnrollmentSummary, BulkClassUpdateData
)
from app.services import enrollment_service

router = APIRouter(
    prefix="/admin/enrollment", # PRESERVED: Original prefix
    tags=["Admin - Student Enrollment"],
    dependencies=[Depends(get_current_admin)]
)

def _build_enrollment_response(enrollment: dict, db: Session) -> EnrollmentResponse:
    # This helper is needed to fetch related names, preserving the original response shape.
    # We can optimize this later by doing joins in the service layer.
    student = db.get(User, enrollment.student_id)
    student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == enrollment.student_id)).first()
    class_obj = db.get(Class, enrollment.class_id)
    academic_session = db.get(AcademicSession, enrollment.session_id)
    term = db.get(Term, enrollment.term_id)
    
    return EnrollmentResponse(
        id=enrollment.id, student_id=enrollment.student_id,
        student_name=f"{student.first_name} {student.last_name}" if student else "N/A",
        student_admission_number=student_profile.admission_number if student_profile else "N/A",
        class_id=enrollment.class_id, class_name=class_obj.name if class_obj else "N/A",
        session_id=enrollment.session_id, session_name=academic_session.name if academic_session else "N/A",
        term_id=enrollment.term_id, term_name=term.name.value if term else "N/A",
        is_active=enrollment.is_active, enrolled_at=str(enrollment.enrolled_at),
        created_at=getattr(enrollment, 'created_at', datetime.utcnow())
    )

@router.get("/", response_model=PaginatedEnrollmentResponse)
async def get_enrollments(
    session_id: Optional[str] = Query(None), class_id: Optional[str] = Query(None),
    student_id: Optional[str] = Query(None), is_active: Optional[bool] = Query(True), # Default to True
    skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_session)
):
    """
    PERFORMANCE OPTIMIZED: Gets all enrollments with filtering and pagination.
    """
    # The service now does all the heavy lifting and returns data in the correct shape
    enrollment_list, total_records = enrollment_service.get_enrollments(
        db, session_id, class_id, student_id, is_active, skip, limit
    )
    
    return PaginatedEnrollmentResponse(
        total_records=total_records,
        enrollments=enrollment_list # The list of dicts can be directly used
    )


@router.get("/stats/dashboard-summary", response_model=DashboardStatsResponse)
async def get_dashboard_stats(db: Session = Depends(get_session)):
    stats = enrollment_service.get_dashboard_summary(db)
    return stats


@router.post("/bulk", response_model=List[EnrollmentResponse], status_code=status.HTTP_201_CREATED)
async def bulk_enroll_students(bulk_data: BulkEnrollmentCreate, db: Session = Depends(get_session)):
    successful_enrollments, errors = enrollment_service.bulk_enroll_students(bulk_data, db)
    
    responses = [_build_enrollment_response(enr, db) for enr in successful_enrollments]
    
    if errors:
        # PRESERVED: The original endpoint's multi-status error response
        raise HTTPException(
            status_code=status.HTTP_207_MULTI_STATUS,
            detail={
                "message": f"Enrolled {len(responses)} students successfully with some errors",
                "success_count": len(responses),
                "error_count": len(errors),
                "errors": errors,
                "successful_enrollments": responses
            }
        )
    return responses

# PRESERVED: PUT /admin/enrollment/{id}/transfer
@router.put("/{enrollment_id}/transfer", response_model=EnrollmentResponse)
async def transfer_student(enrollment_id: str, transfer_data: EnrollmentTransfer, db: Session = Depends(get_session)):
    updated_enrollment = enrollment_service.transfer_student(enrollment_id, transfer_data, db)
    return _build_enrollment_response(updated_enrollment, db)

# PRESERVED: DELETE /admin/enrollment/{id}
@router.delete("/{enrollment_id}", status_code=status.HTTP_200_OK, response_model=dict)
async def withdraw_student(enrollment_id: str, db: Session = Depends(get_session)):
    enrollment_service.withdraw_student(enrollment_id, db)
    return {"message": "Student withdrawn successfully"}


@router.put("/{enrollment_id}", response_model=EnrollmentResponse)
async def update_enrollment(enrollment_id: str, update_data: EnrollmentUpdate, db: Session = Depends(get_session)):
    updated_enrollment = enrollment_service.update_enrollment(enrollment_id, update_data, db)
    return _build_enrollment_response(updated_enrollment, db)

# PRESERVED: GET /admin/enrollment/student/{id}/history
@router.get("/student/{student_id}/history", response_model=StudentEnrollmentHistory)
async def get_student_enrollment_history(student_id: str, db: Session = Depends(get_session)):
    # This endpoint can be accessed by student/staff/admin, so we'll use a broader dependency if needed.
    # For now, keeping it under admin scope.
    enrollments = enrollment_service.get_student_enrollment_history(student_id, db)
    
    student = db.get(User, student_id)
    student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
    
    return StudentEnrollmentHistory(
        student_id=student.id,
        student_name=f"{student.first_name} {student.last_name}",
        student_admission_number=student_profile.admission_number if student_profile else "N/A",
        enrollments=[_build_enrollment_response(e, db) for e in enrollments]
    )

# PRESERVED: POST /admin/enrollment/session/transition
@router.post("/session/transition", response_model=Dict)
async def transition_students_to_new_session(transition_data: SessionTransitionData, db: Session = Depends(get_session)):
    result = enrollment_service.transition_students_to_new_session(transition_data, db)
    return result


@router.get("/class/{class_id}/summary", response_model=ClassEnrollmentSummary)
async def get_class_enrollment_summary(
    class_id: str,
    session_id: Optional[str] = Query(None),
    term_id: Optional[str] = Query(None),
    db: Session = Depends(get_session)
):
    summary_data = enrollment_service.get_class_enrollment_summary(
        class_id, session_id, term_id, db
    )
    return summary_data

@router.post("/bulk-class-update", response_model=List[EnrollmentResponse])
async def bulk_update_student_classes(
    update_data: BulkClassUpdateData,
    db: Session = Depends(get_session)
):
    successful_updates, failed_updates = enrollment_service.bulk_update_student_classes(update_data, db)
    
    responses = [_build_enrollment_response(enr, db) for enr in successful_updates]
    
    if failed_updates:
        raise HTTPException(
            status_code=status.HTTP_207_MULTI_STATUS,
            detail={
                "message": f"Updated {len(responses)} students successfully with some errors",
                "success_count": len(responses),
                "error_count": len(failed_updates),
                "errors": failed_updates,
                "successful_updates": responses
            }
        )
    return responses