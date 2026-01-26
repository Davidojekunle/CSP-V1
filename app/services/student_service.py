# app/services/student_service.py
from sqlmodel import Session, select, func, and_
from fastapi import HTTPException
from datetime import date
from typing import Dict, Any, List

from app.models import (
    User, StudentProfile, StudentStatus, Enrollment, Class, 
    AcademicSession, Term, Result, Invoice, InvoiceStatus
)
from app.schemas.dashboard import (
    StudentDashboardResponse, StudentInfo, GuardianInfo, 
    ResultsSummary, FinancialSummary
)

def _calculate_age(born: date) -> int:
    """Calculates age from a date of birth."""
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

def get_student_dashboard_data(student_user: User, db: Session) -> StudentDashboardResponse:
    """
    AGGREGATOR: Collects all data for the student dashboard.
    PERFORMANCE: Uses database-level functions (avg, sum, count) to minimize I/O.
    """
    # 1. Fetch Student Profile
    student_profile = db.exec(
        select(StudentProfile).where(StudentProfile.user_id == student_user.id)
    ).first()
    if not student_profile:
        raise HTTPException(status_code=404, detail="Student profile not found")

    # 2. Get current academic context
    current_session = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).first()
    current_term = db.exec(select(Term).where(Term.is_current == True)).first()

    # 3. Calculate Academic KPIs (Using DB Aggregates)
    avg_score = 0.0
    context_period = "No results for current period"
    if current_session and current_term:
        avg_query = select(func.avg(Result.total)).where(
            Result.student_id == student_user.id,
            Result.session_id == current_session.id,
            Result.term_id == current_term.id,
            Result.is_published == True,
            Result.total.isnot(None)
        )
        avg_score_result = db.exec(avg_query).one_or_none()
        avg_score = round(avg_score_result or 0.0, 2)
        if avg_score > 0:
            context_period = f"As at {current_term.name.value} {current_session.name}"

    total_released_results = db.exec(select(func.count(Result.id)).where(
        Result.student_id == student_user.id,
        Result.is_published == True
    )).one()

    # 4. Calculate Financial KPIs (Using DB Aggregates)
    financial_query = select(
        func.count(Invoice.id), 
        func.sum(Invoice.balance_due)
    ).where(
        Invoice.student_id == student_user.id,
        Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.partial, InvoiceStatus.overdue])
    )
    inv_count, balance = db.exec(financial_query).first() or (0, 0.0)

    # 5. Determine Enrollment Status Logic
    enrollment_info = None
    if student_profile.status == StudentStatus.graduated:
        enrollment_info = {"class_name": "Graduated", "session_name": "Alumni", "term_name": ""}
    elif current_session:
        enr_query = select(Enrollment, Class).join(Class).where(
            Enrollment.student_id == student_user.id,
            Enrollment.session_id == current_session.id,
            Enrollment.is_active == True
        )
        res = db.exec(enr_query).first()
        if res:
            enr, cls = res
            enrollment_info = {
                "class_id": cls.id, "class_name": cls.name,
                "session_name": current_session.name,
                "term_name": current_term.name.value if current_term else "",
                "enrollment_date": str(enr.enrolled_at)
            }
        else:
            enrollment_info = {"class_name": "Waiting for Placement", "session_name": current_session.name}

    # 6. Assemble Response
    return StudentDashboardResponse(
        user_info=StudentInfo(
            id=student_user.id,
            full_name=f"{student_user.first_name} {student_user.last_name}",
            admission_number=student_profile.admission_number,
            email=student_user.email,
            phone=student_user.phone,
            profile_picture_url=student_user.profile_picture_url,
            status=student_profile.status.value,
            gender=student_user.gender.value,
            age=_calculate_age(student_user.date_of_birth),
            guardian_info=GuardianInfo(
                name=student_profile.guardian_name,
                phone=student_profile.guardian_phone,
                email=student_profile.guardian_email
            )
        ),
        results_summary=ResultsSummary(
            average_score=avg_score,
            context_period=context_period,
            total_released_results=total_released_results
        ),
        financial_summary=FinancialSummary(
            current_bill=float(balance or 0.0),
            pending_payments=inv_count
        ),
        current_enrollment=enrollment_info,
        available_reports=[] # Populated based on total_released_results logic
    )