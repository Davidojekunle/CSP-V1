# app/services/academic_service.py
"""
Service layer for managing academic structures (sessions, terms, classes, subjects).
"""
from sqlmodel import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from typing import List, Optional
from datetime import datetime, date

from typing import Tuple
from app.models import (
    AcademicSession, Term, TermName, Class, Subject, ClassSubject, User, UserRole, Enrollment, StudentProfile, Result
)
from app.schemas.academic import (
    AcademicSessionCreate, AcademicSessionUpdate, TermCreate, TermUpdate,
    ClassCreate, ClassUpdate, SubjectCreate, SubjectUpdate, ClassSubjectAssign
) # Assuming schemas are in app.schemas.academic

# --- Helper functions preserved from original file ---
def _parse_date(date_string: str) -> date:
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

def _validate_date_range(start_date: date, end_date: date):
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")

# --- Service Functions for Academic Sessions ---

async def create_academic_session(session_data: AcademicSessionCreate, db: AsyncSession) -> AcademicSession:
    if (await db.execute(select(AcademicSession).where(AcademicSession.name == session_data.name))).scalars().first():
        raise HTTPException(status_code=400, detail="Academic session name already exists")
    
    start_date = _parse_date(session_data.start_date)
    end_date = _parse_date(session_data.end_date)
    _validate_date_range(start_date, end_date)
    
    if session_data.is_current:
        # Unset other current sessions
        current_sessions = (await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))).scalars().all()
        for s in current_sessions:
            s.is_current = False
            db.add(s)
    
    new_session = AcademicSession(
        name=session_data.name,
        start_date=start_date,
        end_date=end_date,
        is_current=session_data.is_current
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return new_session

async def get_all_academic_sessions(db: AsyncSession) -> List[dict]:
    """
    PERFORMANCE: This fetches sessions and counts terms efficiently.
    """
    sessions_db = (await db.execute(select(AcademicSession).order_by(AcademicSession.start_date.desc()))).scalars().all()
    terms_counts = dict((await db.execute(select(Term.session_id, func.count(Term.id)).group_by(Term.session_id))).all())
    response = []
    for s in sessions_db:
        response.append({
            "id": s.id, "name": s.name, "is_current": s.is_current,
            "start_date": str(s.start_date), "end_date": str(s.end_date),
            "terms_count": terms_counts.get(s.id, 0)
        })
    return response

# --- Service Functions for Terms ---

async def create_term(term_data: TermCreate, db: AsyncSession) -> tuple[Term, AcademicSession]:
    academic_session = await db.get(AcademicSession, term_data.session_id)
    if not academic_session:
        raise HTTPException(status_code=404, detail="Academic session not found")
    if (await db.execute(select(Term).where(and_(Term.session_id == term_data.session_id, Term.name == term_data.name)))).scalars().first():
        raise HTTPException(status_code=400, detail="Term already exists in this session")

    start_date = _parse_date(term_data.start_date)
    end_date = _parse_date(term_data.end_date)
    _validate_date_range(start_date, end_date)
    if not (academic_session.start_date <= start_date and end_date <= academic_session.end_date):
        raise HTTPException(status_code=400, detail="Term dates must be within the academic session's date range.")
    
    if term_data.is_current:
        if not academic_session.is_current:
             raise HTTPException(status_code=400, detail="Cannot set term as current because its session is not current.")
        current_terms = (await db.execute(select(Term).where(Term.is_current == True))).scalars().all()
        for t in current_terms:
            t.is_current = False
            db.add(t)

    new_term = Term(
        session_id=term_data.session_id, name=term_data.name,
        start_date=start_date, end_date=end_date, is_current=term_data.is_current
    )
    db.add(new_term)
    await db.commit()
    await db.refresh(new_term)
    return new_term, academic_session


# --- Service Functions for Classes ---

async def get_all_classes(db: AsyncSession, is_active: Optional[bool]) -> List[dict]:
    """
    PERFORMANCE: Uses subqueries and a single main query to avoid N+1.
    """
    current_session = (await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))).scalars().first()
    if not current_session:
        raise HTTPException(status_code=404, detail="No active academic session found")

    students_subquery = select(func.count(Enrollment.id)).where(
        Enrollment.class_id == Class.id,
        Enrollment.session_id == current_session.id,
        Enrollment.is_active == True
    ).correlate(Class).as_scalar()

    subjects_subquery = select(func.count(ClassSubject.id)).where(
        ClassSubject.class_id == Class.id
    ).correlate(Class).as_scalar()

    query = select(
        Class, User.first_name, User.last_name,
        students_subquery.label("students_count"),
        subjects_subquery.label("subjects_count")
    ).outerjoin(User, Class.form_teacher_id == User.id)

    if is_active is not None:
        query = query.where(Class.is_active == is_active)

    results = (await db.execute(query.order_by(Class.level, Class.arm))).all()
    
    # Process results into the required dictionary shape for the response model
    response_data = []
    for class_obj, first_name, last_name, students_count, subjects_count in results:
        response_data.append({
            "id": class_obj.id, "name": class_obj.name, "level": class_obj.level, "arm": class_obj.arm,
            "form_teacher_id": class_obj.form_teacher_id,
            "form_teacher_name": f"{first_name} {last_name}" if first_name else None,
            "is_active": class_obj.is_active, "promotion_type": class_obj.promotion_type,
            "students_count": students_count, "subjects_count": subjects_count,
        })
    return response_data

async def get_students_in_class(class_id: str, session_id: Optional[str], db: AsyncSession) -> List[dict]:
    """Gets all students enrolled in a specific class for a given session."""
    if not await db.get(Class, class_id):
        raise HTTPException(status_code=404, detail="Class not found")

    target_session_id = session_id
    if not target_session_id:
        current_session = (await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))).scalars().first()
        if not current_session:
            raise HTTPException(status_code=400, detail="No active academic session found and no session_id provided")
        target_session_id = current_session.id
    
    academic_session = await db.get(AcademicSession, target_session_id)
    if not academic_session:
        raise HTTPException(status_code=404, detail="Academic session not found")

    # PERFORMANCE: Single query with joins to get all data at once
    query = select(User, StudentProfile, Enrollment).join(
        StudentProfile, User.id == StudentProfile.user_id
    ).join(
        Enrollment, User.id == Enrollment.student_id
    ).where(
        User.role == UserRole.student,
        Enrollment.class_id == class_id,
        Enrollment.session_id == target_session_id
    ).order_by(User.last_name, User.first_name)
    
    results = (await db.execute(query)).all()
    
    # PRESERVE RESPONSE SHAPE: Build the list of dictionaries exactly as the original endpoint did
    student_list = []
    for user, profile, enrollment in results:
        student_list.append({
            "id": user.id,
            "admission_number": profile.admission_number,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone,
            "date_of_birth": str(user.date_of_birth),
            "gender": user.gender.value,
            "enrollment_date": str(enrollment.enrolled_at),
            "is_active": enrollment.is_active,
            "session_name": academic_session.name,
            "guardian_name": profile.guardian_name,
            "guardian_phone": profile.guardian_phone,
            "guardian_email": profile.guardian_email,
        })
    return student_list

# --- Service Functions for Updating Sessions and Terms ---

async def update_academic_session(session_id: str, update_data: AcademicSessionUpdate, db: AsyncSession) -> AcademicSession:
    academic_session = await db.get(AcademicSession, session_id)
    if not academic_session:
        raise HTTPException(status_code=404, detail="Academic session not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    if "name" in update_dict and update_dict["name"] != academic_session.name:
        if (await db.execute(select(AcademicSession).where(AcademicSession.name == update_dict["name"], AcademicSession.id != session_id))).scalars().first():
            raise HTTPException(status_code=400, detail="Academic session name already exists")
    
    if update_dict.get("is_current"):
        current_sessions = (await db.execute(select(AcademicSession).where(AcademicSession.is_current == True, AcademicSession.id != session_id))).scalars().all()
        for s in current_sessions:
            s.is_current = False
            db.add(s)

    for field, value in update_dict.items():
        if field in ["start_date", "end_date"] and value:
            setattr(academic_session, field, _parse_date(value))
        else:
            setattr(academic_session, field, value)

    _validate_date_range(academic_session.start_date, academic_session.end_date)
    
    db.add(academic_session)
    await db.commit()
    await db.refresh(academic_session)
    return academic_session

async def set_current_term_and_session(term_id: str, db: AsyncSession) -> tuple[Term, AcademicSession]:
    target_term = await db.get(Term, term_id)
    if not target_term:
        raise HTTPException(status_code=404, detail="Term not found")

    parent_session = await db.get(AcademicSession, target_term.session_id)
    if not parent_session:
        raise HTTPException(status_code=500, detail="Term's parent academic session not found")

    # Unset all other current terms
    for term in (await db.execute(select(Term).where(Term.is_current == True))).scalars().all():
        term.is_current = False
        db.add(term)
    
    # Unset all other current sessions
    for ac_session in (await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))).scalars().all():
        ac_session.is_current = False
        db.add(ac_session)

    # Set the target term and its parent session as current
    target_term.is_current = True
    parent_session.is_current = True
    db.add(target_term)
    db.add(parent_session)
    await db.commit()
    return target_term, parent_session

async def get_all_terms(db: AsyncSession, session_id: Optional[str]) -> List[dict]:
    query = select(Term, AcademicSession).join(AcademicSession)
    if session_id:
        query = query.where(Term.session_id == session_id)
    results = (await db.execute(query.order_by(AcademicSession.start_date.desc(), Term.start_date.asc()))).all()
    
    return [
        {
            "id": t.id, "session_id": t.session_id, "name": t.name,
            "start_date": str(t.start_date), "end_date": str(t.end_date),
            "is_current": t.is_current, "session_name": s.name
        } for t, s in results
    ]

# --- ADD/COMPLETE Service Functions for Classes ---
async def create_class(class_data: ClassCreate, db: AsyncSession) -> tuple[Class, Optional[User]]:
    if (await db.execute(select(Class).where(Class.name == class_data.name))).scalars().first():
        raise HTTPException(status_code=400, detail="Class name already exists")
    
    teacher = None
    if class_data.form_teacher_id:
        teacher = await db.get(User, class_data.form_teacher_id)
        if not teacher or teacher.role not in [UserRole.staff, UserRole.admin]:
            raise HTTPException(status_code=404, detail="Valid form teacher not found")

    new_class = Class.model_validate(class_data)
    db.add(new_class)
    await db.commit()
    await db.refresh(new_class)
    return new_class, teacher


# --- ADD/COMPLETE Service Functions for Subjects ---
async def get_all_subjects(db: AsyncSession, is_active: Optional[bool]) -> List[dict]:
    query = select(Subject)
    if is_active is not None:
        query = query.where(Subject.is_active == is_active)
    subjects = (await db.execute(query.order_by(Subject.name))).scalars().all()
    
    classes_counts = dict((await db.execute(
        select(ClassSubject.subject_id, func.count(ClassSubject.id)).group_by(ClassSubject.subject_id)
    )).all())
    response = []
    for subject in subjects:
        response.append({
            "id": subject.id, "code": subject.code, "name": subject.name,
            "is_active": subject.is_active, "classes_count": classes_counts.get(subject.id, 0)
        })
    return response


# --- Service Functions for Subjects ---

async def create_subject(subject_data: SubjectCreate, db: AsyncSession) -> Subject:
    if (await db.execute(select(Subject).where(Subject.code == subject_data.code.upper()))).scalars().first():
        raise HTTPException(status_code=400, detail="Subject code already exists")
    
    new_subject = Subject(code=subject_data.code.upper(), name=subject_data.name)
    db.add(new_subject)
    await db.commit()
    await db.refresh(new_subject)
    return new_subject

# --- Service Functions for Class-Subject Assignments ---

async def assign_subject_to_class(assign_data: ClassSubjectAssign, db: AsyncSession) -> dict:
    class_obj = await db.get(Class, assign_data.class_id)
    if not class_obj: raise HTTPException(status_code=404, detail="Class not found")
    
    subject = await db.get(Subject, assign_data.subject_id)
    if not subject: raise HTTPException(status_code=404, detail="Subject not found")

    teacher = await db.get(User, assign_data.teacher_id)
    if not teacher or teacher.role not in [UserRole.staff, UserRole.admin]:
        raise HTTPException(status_code=404, detail="Valid teacher not found")

    if (await db.execute(select(ClassSubject).where(and_(ClassSubject.class_id == assign_data.class_id, ClassSubject.subject_id == assign_data.subject_id)))).scalars().first():
        raise HTTPException(status_code=400, detail="Subject already assigned to this class")

    new_assignment = ClassSubject(**assign_data.model_dump())
    db.add(new_assignment)
    await db.commit()
    await db.refresh(new_assignment)

    return {
        "assignment": new_assignment,
        "class_obj": class_obj,
        "subject": subject,
        "teacher": teacher
    }

async def delete_class_subject_assignment(assignment_id: str, db: AsyncSession):
    assignment = await db.get(ClassSubject, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.delete(assignment)
    await db.commit()

async def get_all_class_subject_assignments(db: AsyncSession, class_id: Optional[str], subject_id: Optional[str], teacher_id: Optional[str]) -> List[dict]:
    query = select(ClassSubject, Class, Subject, User).join(
        Class, ClassSubject.class_id == Class.id
    ).join(
        Subject, ClassSubject.subject_id == Subject.id
    ).join(
        User, ClassSubject.teacher_id == User.id
    )
    if class_id: query = query.where(ClassSubject.class_id == class_id)
    if subject_id: query = query.where(ClassSubject.subject_id == subject_id)
    if teacher_id: query = query.where(ClassSubject.teacher_id == teacher_id)

    results = (await db.execute(query.order_by(Class.name, Subject.name))).all()
    
    return [
        {
            "id": cs.id, "class_id": cs.class_id, "class_name": c.name,
            "subject_id": cs.subject_id, "subject_name": s.name, "subject_code": s.code,
            "teacher_id": cs.teacher_id, "teacher_name": f"{u.first_name} {u.last_name}"
        } for cs, c, s, u in results
    ]
# ... We will add more service functions for update, delete, etc. as we go.


# --- Updates / deletes used by the dashboard's edit forms ---

async def set_current_session(session_id: str, db: AsyncSession) -> AcademicSession:
    """Makes a session current. Terms of other sessions stop being current."""
    academic_session = await db.get(AcademicSession, session_id)
    if not academic_session:
        raise HTTPException(status_code=404, detail="Academic session not found")
    for s in (await db.execute(select(AcademicSession).where(AcademicSession.is_current == True, AcademicSession.id != session_id))).scalars().all():
        s.is_current = False
        db.add(s)
    for t in (await db.execute(select(Term).where(Term.is_current == True, Term.session_id != session_id))).scalars().all():
        t.is_current = False
        db.add(t)
    academic_session.is_current = True
    db.add(academic_session)
    await db.commit()
    return academic_session


async def update_term(term_id: str, update_data: TermUpdate, db: AsyncSession) -> Tuple[Term, AcademicSession]:
    term = await db.get(Term, term_id)
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    academic_session = await db.get(AcademicSession, term.session_id)
    update_dict = update_data.model_dump(exclude_unset=True)

    if "name" in update_dict and update_dict["name"] != term.name:
        if (await db.execute(select(Term).where(Term.session_id == term.session_id, Term.name == update_dict["name"], Term.id != term_id))).scalars().first():
            raise HTTPException(status_code=400, detail="Term already exists in this session")
        term.name = update_dict["name"]
    if update_dict.get("start_date"):
        term.start_date = _parse_date(update_dict["start_date"])
    if update_dict.get("end_date"):
        term.end_date = _parse_date(update_dict["end_date"])
    _validate_date_range(term.start_date, term.end_date)
    if not (academic_session.start_date <= term.start_date and term.end_date <= academic_session.end_date):
        raise HTTPException(status_code=400, detail="Term dates must be within the academic session's date range.")

    db.add(term)
    await db.commit()
    if update_dict.get("is_current"):
        term, academic_session = await set_current_term_and_session(term_id, db)
    return term, academic_session


async def update_class(class_id: str, update_data: ClassUpdate, db: AsyncSession) -> dict:
    class_obj = await db.get(Class, class_id)
    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")
    update_dict = update_data.model_dump(exclude_unset=True)

    if "name" in update_dict and update_dict["name"] != class_obj.name:
        if (await db.execute(select(Class).where(Class.name == update_dict["name"], Class.id != class_id))).scalars().first():
            raise HTTPException(status_code=400, detail="Class name already exists")
    if update_dict.get("form_teacher_id"):
        teacher = await db.get(User, update_dict["form_teacher_id"])
        if not teacher or teacher.role not in [UserRole.staff, UserRole.admin]:
            raise HTTPException(status_code=404, detail="Valid form teacher not found")

    for field, value in update_dict.items():
        setattr(class_obj, field, value)
    db.add(class_obj)
    await db.commit()

    teacher = await db.get(User, class_obj.form_teacher_id) if class_obj.form_teacher_id else None
    current_session = (await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))).scalars().first()
    students_count = 0
    if current_session:
        students_count = (await db.execute(select(func.count(Enrollment.id)).where(
            Enrollment.class_id == class_id, Enrollment.session_id == current_session.id, Enrollment.is_active == True
        ))).scalar_one()
    subjects_count = (await db.execute(select(func.count(ClassSubject.id)).where(ClassSubject.class_id == class_id))).scalar_one()
    return {
        "id": class_obj.id, "name": class_obj.name, "level": class_obj.level, "arm": class_obj.arm,
        "form_teacher_id": class_obj.form_teacher_id,
        "form_teacher_name": f"{teacher.first_name} {teacher.last_name}" if teacher else None,
        "is_active": class_obj.is_active, "promotion_type": class_obj.promotion_type,
        "students_count": students_count, "subjects_count": subjects_count,
    }


async def update_subject(subject_id: str, update_data: SubjectUpdate, db: AsyncSession) -> dict:
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    update_dict = update_data.model_dump(exclude_unset=True)
    if update_dict.get("code"):
        update_dict["code"] = update_dict["code"].upper()
        if update_dict["code"] != subject.code and (await db.execute(
            select(Subject).where(Subject.code == update_dict["code"], Subject.id != subject_id)
        )).scalars().first():
            raise HTTPException(status_code=400, detail="Subject code already exists")
    for field, value in update_dict.items():
        setattr(subject, field, value)
    db.add(subject)
    await db.commit()
    classes_count = (await db.execute(select(func.count(ClassSubject.id)).where(ClassSubject.subject_id == subject_id))).scalar_one()
    return {"id": subject.id, "code": subject.code, "name": subject.name, "is_active": subject.is_active, "classes_count": classes_count}


async def delete_subject(subject_id: str, db: AsyncSession):
    """Deletes a subject that has never been used; subjects with results or class assignments must be deactivated instead."""
    subject = await db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    in_use = (await db.execute(select(ClassSubject.id).where(ClassSubject.subject_id == subject_id).limit(1))).first() or \
        (await db.execute(select(Result.id).where(Result.subject_id == subject_id).limit(1))).first()
    if in_use:
        raise HTTPException(status_code=400, detail="Subject is assigned to classes or has results. Deactivate it instead of deleting.")
    await db.delete(subject)
    await db.commit()
