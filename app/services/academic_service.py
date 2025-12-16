# app/services/academic_service.py
"""
Service layer for managing academic structures (sessions, terms, classes, subjects).
"""
from sqlmodel import Session, select, func, and_
from fastapi import HTTPException
from typing import List, Optional
from datetime import datetime, date

from typing import Tuple
from app.models import (
    AcademicSession, Term, TermName, Class, Subject, ClassSubject, User, UserRole, Enrollment, StudentProfile
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

def create_academic_session(session_data: AcademicSessionCreate, db: Session) -> AcademicSession:
    if db.exec(select(AcademicSession).where(AcademicSession.name == session_data.name)).first():
        raise HTTPException(status_code=400, detail="Academic session name already exists")
    
    start_date = _parse_date(session_data.start_date)
    end_date = _parse_date(session_data.end_date)
    _validate_date_range(start_date, end_date)
    
    if session_data.is_current:
        # Unset other current sessions
        current_sessions = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).all()
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
    db.commit()
    db.refresh(new_session)
    return new_session

def get_all_academic_sessions(db: Session) -> List[dict]:
    """
    PERFORMANCE: This fetches sessions and counts terms efficiently.
    """
    sessions_db = db.exec(select(AcademicSession).order_by(AcademicSession.start_date.desc())).all()
    response = []
    for s in sessions_db:
        terms_count = db.exec(select(func.count(Term.id)).where(Term.session_id == s.id)).one()
        response.append({
            "id": s.id, "name": s.name, "is_current": s.is_current,
            "start_date": str(s.start_date), "end_date": str(s.end_date),
            "terms_count": terms_count
        })
    return response

# --- Service Functions for Terms ---

def create_term(term_data: TermCreate, db: Session) -> tuple[Term, AcademicSession]:
    academic_session = db.get(AcademicSession, term_data.session_id)
    if not academic_session:
        raise HTTPException(status_code=404, detail="Academic session not found")
    if db.exec(select(Term).where(and_(Term.session_id == term_data.session_id, Term.name == term_data.name))).first():
        raise HTTPException(status_code=400, detail="Term already exists in this session")

    start_date = _parse_date(term_data.start_date)
    end_date = _parse_date(term_data.end_date)
    _validate_date_range(start_date, end_date)
    if not (academic_session.start_date <= start_date and end_date <= academic_session.end_date):
        raise HTTPException(status_code=400, detail="Term dates must be within the academic session's date range.")
    
    if term_data.is_current:
        if not academic_session.is_current:
             raise HTTPException(status_code=400, detail="Cannot set term as current because its session is not current.")
        current_terms = db.exec(select(Term).where(Term.is_current == True)).all()
        for t in current_terms:
            t.is_current = False
            db.add(t)

    new_term = Term(
        session_id=term_data.session_id, name=term_data.name,
        start_date=start_date, end_date=end_date, is_current=term_data.is_current
    )
    db.add(new_term)
    db.commit()
    db.refresh(new_term)
    return new_term, academic_session


# --- Service Functions for Classes ---

def get_all_classes(db: Session, is_active: Optional[bool]) -> List[dict]:
    """
    PERFORMANCE: Uses subqueries and a single main query to avoid N+1.
    """
    current_session = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).first()
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

    results = db.exec(query.order_by(Class.level, Class.arm)).all()
    
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

def get_students_in_class(class_id: str, session_id: Optional[str], db: Session) -> List[dict]:
    """Gets all students enrolled in a specific class for a given session."""
    if not db.get(Class, class_id):
        raise HTTPException(status_code=404, detail="Class not found")

    target_session_id = session_id
    if not target_session_id:
        current_session = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).first()
        if not current_session:
            raise HTTPException(status_code=400, detail="No active academic session found and no session_id provided")
        target_session_id = current_session.id
    
    academic_session = db.get(AcademicSession, target_session_id)
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
    
    results = db.exec(query).all()
    
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

def update_academic_session(session_id: str, update_data: AcademicSessionUpdate, db: Session) -> AcademicSession:
    academic_session = db.get(AcademicSession, session_id)
    if not academic_session:
        raise HTTPException(status_code=404, detail="Academic session not found")

    update_dict = update_data.model_dump(exclude_unset=True)
    if "name" in update_dict and update_dict["name"] != academic_session.name:
        if db.exec(select(AcademicSession).where(AcademicSession.name == update_dict["name"], AcademicSession.id != session_id)).first():
            raise HTTPException(status_code=400, detail="Academic session name already exists")
    
    if update_dict.get("is_current"):
        current_sessions = db.exec(select(AcademicSession).where(AcademicSession.is_current == True, AcademicSession.id != session_id)).all()
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
    db.commit()
    db.refresh(academic_session)
    return academic_session

def set_current_term_and_session(term_id: str, db: Session) -> tuple[Term, AcademicSession]:
    target_term = db.get(Term, term_id)
    if not target_term:
        raise HTTPException(status_code=404, detail="Term not found")

    parent_session = db.get(AcademicSession, target_term.session_id)
    if not parent_session:
        raise HTTPException(status_code=500, detail="Term's parent academic session not found")

    # Unset all other current terms
    for term in db.exec(select(Term).where(Term.is_current == True)).all():
        term.is_current = False
        db.add(term)
    
    # Unset all other current sessions
    for ac_session in db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).all():
        ac_session.is_current = False
        db.add(ac_session)

    # Set the target term and its parent session as current
    target_term.is_current = True
    parent_session.is_current = True
    db.add(target_term)
    db.add(parent_session)
    db.commit()
    return target_term, parent_session

def get_all_terms(db: Session, session_id: Optional[str]) -> List[dict]:
    query = select(Term, AcademicSession).join(AcademicSession)
    if session_id:
        query = query.where(Term.session_id == session_id)
    results = db.exec(query.order_by(AcademicSession.start_date.desc(), Term.start_date.asc())).all()
    
    return [
        {
            "id": t.id, "session_id": t.session_id, "name": t.name,
            "start_date": str(t.start_date), "end_date": str(t.end_date),
            "is_current": t.is_current, "session_name": s.name
        } for t, s in results
    ]

# --- ADD/COMPLETE Service Functions for Classes ---
def create_class(class_data: ClassCreate, db: Session) -> tuple[Class, Optional[User]]:
    if db.exec(select(Class).where(Class.name == class_data.name)).first():
        raise HTTPException(status_code=400, detail="Class name already exists")
    
    teacher = None
    if class_data.form_teacher_id:
        teacher = db.get(User, class_data.form_teacher_id)
        if not teacher or teacher.role not in [UserRole.staff, UserRole.admin]:
            raise HTTPException(status_code=404, detail="Valid form teacher not found")

    new_class = Class.model_validate(class_data)
    db.add(new_class)
    db.commit()
    db.refresh(new_class)
    return new_class, teacher


# --- ADD/COMPLETE Service Functions for Subjects ---
def get_all_subjects(db: Session, is_active: Optional[bool]) -> List[dict]:
    query = select(Subject)
    if is_active is not None:
        query = query.where(Subject.is_active == is_active)
    subjects = db.exec(query.order_by(Subject.name)).all()
    
    response = []
    for subject in subjects:
        classes_count = db.exec(select(func.count(ClassSubject.id)).where(ClassSubject.subject_id == subject.id)).one()
        response.append({
            "id": subject.id, "code": subject.code, "name": subject.name,
            "is_active": subject.is_active, "classes_count": classes_count
        })
    return response


# --- Service Functions for Subjects ---

def create_subject(subject_data: SubjectCreate, db: Session) -> Subject:
    if db.exec(select(Subject).where(Subject.code == subject_data.code.upper())).first():
        raise HTTPException(status_code=400, detail="Subject code already exists")
    
    new_subject = Subject(code=subject_data.code.upper(), name=subject_data.name)
    db.add(new_subject)
    db.commit()
    db.refresh(new_subject)
    return new_subject

# --- Service Functions for Class-Subject Assignments ---

def assign_subject_to_class(assign_data: ClassSubjectAssign, db: Session) -> dict:
    class_obj = db.get(Class, assign_data.class_id)
    if not class_obj: raise HTTPException(status_code=404, detail="Class not found")
    
    subject = db.get(Subject, assign_data.subject_id)
    if not subject: raise HTTPException(status_code=404, detail="Subject not found")

    teacher = db.get(User, assign_data.teacher_id)
    if not teacher or teacher.role not in [UserRole.staff, UserRole.admin]:
        raise HTTPException(status_code=404, detail="Valid teacher not found")

    if db.exec(select(ClassSubject).where(and_(ClassSubject.class_id == assign_data.class_id, ClassSubject.subject_id == assign_data.subject_id))).first():
        raise HTTPException(status_code=400, detail="Subject already assigned to this class")

    new_assignment = ClassSubject(**assign_data.model_dump())
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)

    return {
        "assignment": new_assignment,
        "class_obj": class_obj,
        "subject": subject,
        "teacher": teacher
    }

def delete_class_subject_assignment(assignment_id: str, db: Session):
    assignment = db.get(ClassSubject, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(assignment)
    db.commit()

def get_all_class_subject_assignments(db: Session, class_id: Optional[str], subject_id: Optional[str], teacher_id: Optional[str]) -> List[dict]:
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
    
    results = db.exec(query).all()
    
    return [
        {
            "id": cs.id, "class_id": cs.class_id, "class_name": c.name,
            "subject_id": cs.subject_id, "subject_name": s.name, "subject_code": s.code,
            "teacher_id": cs.teacher_id, "teacher_name": f"{u.first_name} {u.last_name}"
        } for cs, c, s, u in results
    ]
# ... We will add more service functions for update, delete, etc. as we go.