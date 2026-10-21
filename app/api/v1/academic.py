# app/api/v1/academic.py
"""
New, refactored API routes for academic structure management.
"""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select
from typing import List, Optional, Dict

from app.core.database import get_session
from app.core.auth import get_current_admin
from app.models import User, Term
from app.schemas.academic import (
    AcademicSessionResponse, AcademicSessionCreate, AcademicSessionUpdate,
    TermResponse, TermCreate, TermUpdate,
    ClassResponse, ClassCreate, ClassUpdate,
    SubjectResponse, SubjectCreate, SubjectUpdate,
    ClassSubjectResponse, ClassSubjectAssign, ClassSubjectUpdate, StudentInClassResponse
)
from app.services import academic_service

router = APIRouter(
    prefix="/admin/academic",
    tags=["Admin - Academic Structure"],
    dependencies=[Depends(get_current_admin)]
)

# --- Academic Sessions ---
@router.post("/sessions", response_model=AcademicSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_academic_session(session_data: AcademicSessionCreate, db: AsyncSession = Depends(get_session)):
    new_session = await academic_service.create_academic_session(session_data, db)
    return AcademicSessionResponse(
        id=new_session.id, name=new_session.name, is_current=new_session.is_current,
        start_date=str(new_session.start_date), end_date=str(new_session.end_date),
        terms_count=0
    )

@router.get("/sessions", response_model=List[AcademicSessionResponse])
async def get_academic_sessions(db: AsyncSession = Depends(get_session)):
    sessions_data = await academic_service.get_all_academic_sessions(db)
    return sessions_data

@router.put("/sessions/{session_id}", response_model=AcademicSessionResponse)
async def update_academic_session(session_id: str, update_data: AcademicSessionUpdate, db: AsyncSession = Depends(get_session)):
    updated_session = await academic_service.update_academic_session(session_id, update_data, db)
    result = await db.execute(select(func.count(Term.id)).where(Term.session_id == updated_session.id))
    terms_count = result.scalar()
    return AcademicSessionResponse(
        id=updated_session.id, name=updated_session.name, is_current=updated_session.is_current,
        start_date=str(updated_session.start_date), end_date=str(updated_session.end_date),
        terms_count=terms_count
    )

@router.post("/sessions/{session_id}/set-current", response_model=Dict[str, str])
async def set_current_session(session_id: str, db: AsyncSession = Depends(get_session)):
    academic_session = await academic_service.set_current_session(session_id, db)
    return {"message": f"Session '{academic_session.name}' is now current."}

# --- Terms ---
@router.post("/terms", response_model=TermResponse, status_code=status.HTTP_201_CREATED)
async def create_term(term_data: TermCreate, db: AsyncSession = Depends(get_session)):
    new_term, academic_session = await academic_service.create_term(term_data, db)
    return TermResponse(
        id=new_term.id, session_id=new_term.session_id, name=new_term.name,
        start_date=str(new_term.start_date), end_date=str(new_term.end_date),
        is_current=new_term.is_current, session_name=academic_session.name
    )

@router.get("/terms", response_model=List[TermResponse])
async def get_terms(session_id: Optional[str] = Query(None), db: AsyncSession = Depends(get_session)):
    terms_data = await academic_service.get_all_terms(db, session_id)
    return terms_data

@router.post("/terms/{term_id}/set-current", response_model=Dict[str, str])
async def set_current_term(term_id: str, db: AsyncSession = Depends(get_session)):
    term, ac_session = await academic_service.set_current_term_and_session(term_id, db)
    return {"message": f"Term '{term.name.value}' in session '{ac_session.name}' is now current."}

@router.put("/terms/{term_id}", response_model=TermResponse)
async def update_term(term_id: str, update_data: TermUpdate, db: AsyncSession = Depends(get_session)):
    term, academic_session = await academic_service.update_term(term_id, update_data, db)
    return TermResponse(
        id=term.id, session_id=term.session_id, name=term.name,
        start_date=str(term.start_date), end_date=str(term.end_date),
        is_current=term.is_current, session_name=academic_session.name
    )

# --- Classes ---
@router.post("/classes", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
async def create_class(class_data: ClassCreate, db: AsyncSession = Depends(get_session)):
    new_class, teacher = await academic_service.create_class(class_data, db)
    return ClassResponse(
        id=new_class.id, name=new_class.name, level=new_class.level, arm=new_class.arm,
        form_teacher_id=new_class.form_teacher_id,
        form_teacher_name=f"{teacher.first_name} {teacher.last_name}" if teacher else None,
        is_active=new_class.is_active, promotion_type=new_class.promotion_type,
        students_count=0, subjects_count=0
    )

@router.get("/classes", response_model=List[ClassResponse])
async def get_classes(is_active: Optional[bool] = Query(None), db: AsyncSession = Depends(get_session)):
    classes_data = await academic_service.get_all_classes(db, is_active)
    return classes_data

@router.put("/classes/{class_id}", response_model=ClassResponse)
async def update_class(class_id: str, update_data: ClassUpdate, db: AsyncSession = Depends(get_session)):
    return await academic_service.update_class(class_id, update_data, db)

# --- Subjects ---
@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(subject_data: SubjectCreate, db: AsyncSession = Depends(get_session)):
    new_subject = await academic_service.create_subject(subject_data, db)
    return SubjectResponse(
        id=new_subject.id, code=new_subject.code, name=new_subject.name,
        is_active=new_subject.is_active, classes_count=0
    )

@router.get("/subjects", response_model=List[SubjectResponse])
async def get_subjects(is_active: Optional[bool] = Query(None), db: AsyncSession = Depends(get_session)):
    subjects_data = await academic_service.get_all_subjects(db, is_active)
    return subjects_data

@router.put("/subjects/{subject_id}", response_model=SubjectResponse)
async def update_subject(subject_id: str, update_data: SubjectUpdate, db: AsyncSession = Depends(get_session)):
    return await academic_service.update_subject(subject_id, update_data, db)

@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(subject_id: str, db: AsyncSession = Depends(get_session)):
    await academic_service.delete_subject(subject_id, db)
    return

# --- Class-Subject Assignments ---
@router.post("/class-subjects", response_model=ClassSubjectResponse, status_code=status.HTTP_201_CREATED)
async def assign_subject_to_class(assignment_data: ClassSubjectAssign, db: AsyncSession = Depends(get_session)):
    # The service function returns a dictionary with all the necessary objects
    result = await academic_service.assign_subject_to_class(assignment_data, db)
    
    # --- THIS IS THE FIX ---
    # We need to unpack the dictionary from the service and build the flat response
    # that ClassSubjectResponse expects.
    assignment = result['assignment']
    class_obj = result['class_obj']
    subject = result['subject']
    teacher = result['teacher']
    
    return ClassSubjectResponse(
        id=assignment.id,
        class_id=assignment.class_id,
        class_name=class_obj.name,
        subject_id=assignment.subject_id,
        subject_name=subject.name,
        subject_code=subject.code,
        teacher_id=assignment.teacher_id,
        teacher_name=f"{teacher.first_name} {teacher.last_name}"
    )

@router.get("/class-subjects", response_model=List[ClassSubjectResponse])
async def get_class_subjects(class_id: Optional[str] = Query(None), subject_id: Optional[str] = Query(None), teacher_id: Optional[str] = Query(None), db: AsyncSession = Depends(get_session)):
    assignments_data = await academic_service.get_all_class_subject_assignments(db, class_id, subject_id, teacher_id)
    return assignments_data

@router.delete("/class-subjects/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_subject_from_class(assignment_id: str, db: AsyncSession = Depends(get_session)):
    await academic_service.delete_class_subject_assignment(assignment_id, db)
    return

# --- Students in Classes ---
@router.get("/classes/{class_id}/students", response_model=List[StudentInClassResponse])
async def get_students_by_class(
    class_id: str,
    session_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_session)
):
    """Get all students enrolled in a specific class for a session."""
    students_data = await academic_service.get_students_in_class(class_id, session_id, db)
    return students_data