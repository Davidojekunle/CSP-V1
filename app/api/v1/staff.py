from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List

from app.core.database import get_session
from app.core.auth import get_current_staff
from app.models import User, AcademicSession, Term, BehavioralTraits
from app.schemas.staff import  StaffProfileUpdate, StaffStudentResponse, StaffResultResponse, FormClassOverviewResponse, BehavioralTraitsCreate, BehavioralTraitsResponse # Add other schemas
from app.schemas.dashboard import StudentDashboardResponse, StaffClassResponse, StaffDashboardStatsResponse, StaffDashboardResponse
from app.schemas.user import UserResponse
from app.services import staff_service, user_service
from app.services.pdf.report_card import report_card_service
from fastapi.responses import Response


router = APIRouter(
    prefix="/staff",
    tags=["Staff"],
    dependencies=[Depends(get_current_staff)]
)

# PRESERVED: GET /staff/dashboard
@router.get("/dashboard", response_model=StaffDashboardResponse)
async def get_staff_dashboard(current_user: User = Depends(get_current_staff), db: AsyncSession = Depends(get_session)):
    dashboard_data = await staff_service.get_staff_dashboard_data(staff_user=current_user, db=db)
    return dashboard_data

# PRESERVED: GET /staff/my-classes
@router.get("/my-classes", response_model=List[StaffClassResponse])
async def get_my_classes(current_user: User = Depends(get_current_staff), db: AsyncSession = Depends(get_session)):
    classes_data = await staff_service.get_my_classes(staff_user=current_user, db=db)
    return classes_data

# PRESERVED: GET /staff/me/profile
@router.get("/me/profile", response_model=UserResponse)
async def get_my_staff_profile(current_user: User = Depends(get_current_staff), db: AsyncSession = Depends(get_session)):
    return await user_service.build_user_response(current_user, db)

# PRESERVED: PUT /staff/me/profile
@router.put("/me/profile", response_model=UserResponse)
async def update_my_staff_profile(
    profile_data: StaffProfileUpdate,
    current_user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_session)
):
    await staff_service.update_staff_profile(staff_user=current_user, profile_data=profile_data.model_dump(exclude_unset=True), db=db)
    return await user_service.build_user_response(current_user, db)


@router.get("/my-classes/{class_id}/students", response_model=List[StaffStudentResponse])
async def get_my_class_students(
    class_id: str,
    current_user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_session)
):
    students_data = await staff_service.get_students_for_my_class(
        staff_user=current_user, class_id=class_id, db=db
    )
    return students_data

# PRESERVED: GET /staff/my-classes/{class_id}/subject/{subject_id}/results
@router.get("/my-classes/{class_id}/subject/{subject_id}/results", response_model=List[StaffResultResponse])
async def get_my_class_subject_results(
    class_id: str,
    subject_id: str,
    current_user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_session)
):
    results_data = await staff_service.get_results_for_my_class_subject(
        staff_user=current_user, class_id=class_id, subject_id=subject_id, db=db
    )
    return results_data

@router.get("/my-form-class/overview", response_model=FormClassOverviewResponse)
async def get_my_form_class_overview(
    current_user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_session)
):
    overview_data = await staff_service.get_form_class_overview(staff_user=current_user, db=db)
    return overview_data

# PRESERVED: GET /staff/my-form-class/report-cards/download
@router.get("/my-form-class/report-cards/download")
async def download_my_form_class_report_cards(
    current_user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_session)
):
    form_class = await staff_service._get_form_class_for_teacher(current_user, db)
    result_session = await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))
    current_session = result_session.scalars().first()
    result_term = await db.execute(select(Term).where(Term.is_current == True))
    current_term = result_term.scalars().first()
    if not current_session or not current_term:
        raise HTTPException(status_code=400, detail="No current academic session or term is set.")
    zip_content, filename = await report_card_service.generate_bulk_class_reports(
        class_id=form_class.id,
        session_id=current_session.id,
        term_id=current_term.id,
        db_session=db
    )
    return Response(content=zip_content, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={filename}"})


traits_router = APIRouter(
    prefix="/behavioral-traits",
    tags=["Behavioral Traits"],
    dependencies=[Depends(get_current_staff)]
)

@traits_router.post("/", response_model=BehavioralTraitsResponse, status_code=201)
async def create_or_update_traits(
    traits_data: BehavioralTraitsCreate,
    current_user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_session)
):
    traits = await staff_service.create_or_update_behavioral_traits(staff_user=current_user, traits_data=traits_data, db=db)
    return traits


@traits_router.get("/student/{student_id}")
async def get_student_traits(
    student_id: str,
    session_id: str = Query(...),
    term_id: str = Query(...),
    db: AsyncSession = Depends(get_session)
):
    """Saved behavioural traits for a student/term; an empty object if none were recorded yet."""
    traits = (await db.execute(select(BehavioralTraits).where(
        BehavioralTraits.student_id == student_id,
        BehavioralTraits.session_id == session_id,
        BehavioralTraits.term_id == term_id,
    ))).scalars().first()
    if not traits:
        return {}
    return BehavioralTraitsResponse.model_validate(traits, from_attributes=True)
