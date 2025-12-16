# app/services/enrollment_service.py
"""Service layer for student enrollment management."""
from sqlmodel import Session, select, func, and_
from sqlalchemy.orm import selectinload

from fastapi import HTTPException
from datetime import date, datetime
from typing import List, Optional


from app.models import (
    Enrollment, User, UserRole, StudentProfile, Class, AcademicSession, Term, PromotionType, StudentStatus
)
from app.schemas.enrollment import EnrollmentCreate, BulkEnrollmentCreate, EnrollmentResponse, EnrollmentTransfer, EnrollmentUpdate, SessionTransitionData # Add more as needed

def _parse_date(date_string: str) -> date:
    # This helper can be moved to a central utils file later
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

def get_enrollments(
    db: Session,
    session_id: Optional[str],
    class_id: Optional[str],
    student_id: Optional[str],
    is_active: Optional[bool],
    skip: int,
    limit: int
) -> tuple[List[dict], int]:
    """
    PERFORMANCE OPTIMIZED: Fetches enrollments and all related data in a single query
    using JOINs to prevent the N+1 problem.
    """
    # Base query joins all necessary tables
    query = select(
        Enrollment, User, StudentProfile, Class, AcademicSession, Term
    ).join(
        User, Enrollment.student_id == User.id
    ).join(
        StudentProfile, Enrollment.student_id == StudentProfile.user_id
    ).join(
        Class, Enrollment.class_id == Class.id
    ).join(
        AcademicSession, Enrollment.session_id == AcademicSession.id
    ).join(
        Term, Enrollment.term_id == Term.id
    )

    conditions = []
    target_session_id = session_id
    if not target_session_id:
        current_session = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).first()
        if current_session:
            target_session_id = current_session.id
    
    if target_session_id: conditions.append(Enrollment.session_id == target_session_id)
    if class_id: conditions.append(Enrollment.class_id == class_id)
    if student_id: conditions.append(Enrollment.student_id == student_id)
    if is_active is not None: conditions.append(Enrollment.is_active == is_active)
    
    if conditions:
        query = query.where(and_(*conditions))

    # The count query must also be based on the filtered query
    count_query = select(func.count()).select_from(query.subquery())
    total_records = db.exec(count_query).one()

    # Apply pagination and execute the main query
    results = db.exec(query.offset(skip).limit(limit)).all()
    
    # PRESERVE RESPONSE SHAPE: Build the list of dictionaries from the single query result
    enrollment_list = []
    for enrollment, user, profile, class_obj, ac_session, term in results:
        enrollment_list.append({
            "id": enrollment.id,
            "student_id": enrollment.student_id,
            "student_name": f"{user.first_name} {user.last_name}",
            "student_admission_number": profile.admission_number,
            "class_id": enrollment.class_id,
            "class_name": class_obj.name,
            "session_id": enrollment.session_id,
            "session_name": ac_session.name,
            "term_id": enrollment.term_id,
            "term_name": term.name.value,
            "is_active": enrollment.is_active,
            "enrolled_at": str(enrollment.enrolled_at),
            "created_at": getattr(enrollment, 'created_at', datetime.utcnow())
        })

    return enrollment_list, total_records

def get_dashboard_summary(db: Session) -> dict:
    """Calculates the stats for the enrollment dashboard summary."""
    current_session = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).first()
    if not current_session:
        return {
            "total_enrollments": 0, "active_students": 0,
            "current_session_name": "N/A (No current session set)",
            "pending_transitions": 0
        }

    session_id = current_session.id
    total_enrollments = db.exec(select(func.count(Enrollment.id)).where(Enrollment.session_id == session_id)).one()
    
    active_students_query = select(func.count(func.distinct(Enrollment.student_id))).where(
        Enrollment.session_id == session_id, Enrollment.is_active == True
    )
    active_students = db.exec(active_students_query).one()

    pending_transitions_query = select(func.count(Enrollment.id)).join(Class).where(
        Enrollment.session_id == session_id,
        Enrollment.is_active == True,
        Class.promotion_type == PromotionType.graduate
    )
    pending_transitions = db.exec(pending_transitions_query).one()

    return {
        "total_enrollments": total_enrollments,
        "active_students": active_students,
        "current_session_name": current_session.name,
        "pending_transitions": pending_transitions
    }

def bulk_enroll_students(bulk_data: BulkEnrollmentCreate, db: Session) -> tuple[List[Enrollment], List[str]]:
    """
    Enrolls multiple students in the same class.
    Returns a list of successful enrollments and a list of error messages.
    """
    # --- Validation (identical to original) ---
    class_obj = db.get(Class, bulk_data.class_id)
    if not class_obj or not class_obj.is_active:
        raise HTTPException(status_code=404, detail="Active class not found")
    
    term = db.get(Term, bulk_data.term_id)
    if not term or term.session_id != bulk_data.session_id:
        raise HTTPException(status_code=400, detail="Term does not belong to the specified session")

    enrolled_date = _parse_date(bulk_data.enrolled_at) if bulk_data.enrolled_at else date.today()
    
    created_enrollments, errors = [], []
    
    for student_id in bulk_data.student_ids:
        student = db.get(User, student_id)
        if not student or student.role != UserRole.student:
            errors.append(f"Student ID {student_id}: Not a valid student.")
            continue
        
        # Check for existing active enrollment in any session/term
        if db.exec(select(Enrollment).where(Enrollment.student_id == student_id, Enrollment.is_active == True)).first():
            errors.append(f"Student {student.first_name} {student.last_name}: Already has an active enrollment.")
            continue

        enrollment = Enrollment(
            student_id=student_id, class_id=bulk_data.class_id,
            session_id=bulk_data.session_id, term_id=bulk_data.term_id,
            enrolled_at=enrolled_date, is_active=True
        )
        db.add(enrollment)
        created_enrollments.append(enrollment)
        
        # Update student profile's current class
        student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
        if student_profile:
            student_profile.current_class_id = bulk_data.class_id
            db.add(student_profile)
    
    db.commit()
    for enr in created_enrollments:
        db.refresh(enr)
        
    return created_enrollments, errors


def transfer_student(enrollment_id: str, transfer_data: EnrollmentTransfer, db: Session) -> Enrollment:
    """Transfers a student to a new class by updating their active enrollment."""
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment or not enrollment.is_active:
        raise HTTPException(status_code=404, detail="Active enrollment not found.")

    new_class = db.get(Class, transfer_data.new_class_id)
    if not new_class or not new_class.is_active:
        raise HTTPException(status_code=400, detail="Cannot transfer to an invalid or inactive class.")

    if enrollment.class_id == transfer_data.new_class_id:
        raise HTTPException(status_code=400, detail="Student is already in this class.")

    # Update the enrollment and student profile
    enrollment.class_id = transfer_data.new_class_id
    enrollment.enrolled_at = _parse_date(transfer_data.transfer_date) if transfer_data.transfer_date else date.today()
    db.add(enrollment)
    
    student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == enrollment.student_id)).first()
    if student_profile:
        student_profile.current_class_id = transfer_data.new_class_id
        db.add(student_profile)
        
    db.commit()
    db.refresh(enrollment)
    return enrollment


def withdraw_student(enrollment_id: str, db: Session):
    """Withdraws a student by deactivating their enrollment."""
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
        
    enrollment.is_active = False
    db.add(enrollment)
    
    student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == enrollment.student_id)).first()
    if student_profile and student_profile.current_class_id == enrollment.class_id:
        student_profile.current_class_id = None
        db.add(student_profile)
        
    db.commit()


def update_enrollment(enrollment_id: str, update_data: EnrollmentUpdate, db: Session) -> Enrollment:
    """Updates an enrollment's class or active status."""
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    if update_data.class_id:
        new_class = db.get(Class, update_data.class_id)
        if not new_class or not new_class.is_active:
            raise HTTPException(status_code=400, detail="Cannot assign to an invalid or inactive class.")
        enrollment.class_id = update_data.class_id

    if update_data.is_active is not None:
        enrollment.is_active = update_data.is_active

    db.add(enrollment)
    
    # Also update the student's primary profile if the class changed and is active
    if update_data.class_id and enrollment.is_active:
        student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == enrollment.student_id)).first()
        if student_profile:
            student_profile.current_class_id = update_data.class_id
            db.add(student_profile)
            
    db.commit()
    db.refresh(enrollment)
    return enrollment


def get_student_enrollment_history(student_id: str, db: Session) -> List[Enrollment]:
    """Fetches all historical enrollments for a single student."""
    student = db.get(User, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    enrollments = db.exec(select(Enrollment).where(Enrollment.student_id == student_id)).all()
    return enrollments


def transition_students_to_new_session(transition_data: SessionTransitionData, db: Session) -> dict:
    """Handles the complex logic of promoting/graduating all students to a new session."""
    old_session = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).first()
    if not old_session:
        raise HTTPException(status_code=404, detail="No active session found to transition from.")

    new_session = db.get(AcademicSession, transition_data.new_session_id)
    new_term = db.get(Term, transition_data.new_term_id)
    if not new_session or not new_term or new_term.session_id != new_session.id:
        raise HTTPException(status_code=404, detail="New session or term is invalid.")

    # Get all active enrollments from the old session
    active_enrollments = db.exec(select(Enrollment).where(
        Enrollment.session_id == old_session.id, Enrollment.is_active == True
    )).all()
    if not active_enrollments:
        raise HTTPException(status_code=404, detail="No active students found in the current session to transition.")

    promo_map = {p["old_class_id"]: p["new_class_id"] for p in transition_data.class_promotions}
    transition_date = _parse_date(transition_data.transition_date) if transition_data.transition_date else date.today()
    
    success, failed = [], []

    for enr in active_enrollments:
        try:
            # Deactivate old enrollment
            enr.is_active = False
            db.add(enr)

            student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == enr.student_id)).first()
            current_class = db.get(Class, enr.class_id)
            if not current_class or not student_profile:
                raise ValueError("Student class or profile not found.")

            # Logic based on promotion type
            if current_class.promotion_type == PromotionType.graduate:
                student_profile.status = StudentStatus.graduated
                student_profile.graduated_at = datetime.utcnow()
                student_profile.current_class_id = None
                success.append({"student_id": enr.student_id, "action": "graduated"})
            
            elif current_class.promotion_type == PromotionType.requires_placement:
                student_profile.current_class_id = None
                success.append({"student_id": enr.student_id, "action": "awaiting_placement"})

            else: # Standard promotion
                new_class_id = promo_map.get(str(enr.class_id))
                if not new_class_id:
                    raise ValueError(f"No promotion mapping found for class {current_class.name}")
                
                new_enrollment = Enrollment(
                    student_id=enr.student_id, class_id=new_class_id,
                    session_id=new_session.id, term_id=new_term.id,
                    is_active=True, enrolled_at=transition_date
                )
                db.add(new_enrollment)
                student_profile.current_class_id = new_class_id
                success.append({"student_id": enr.student_id, "action": "promoted", "new_class_id": new_class_id})

            db.add(student_profile)

        except Exception as e:
            db.rollback() # Rollback changes for this specific student
            failed.append({"student_id": enr.student_id, "error": str(e)})
            db.begin() # Start a new nested transaction for the next student

    # Update session statuses if no errors occurred
    if not failed:
        old_session.is_current = False
        db.add(old_session)
        old_term = db.exec(select(Term).where(Term.session_id == old_session.id, Term.is_current == True)).first()
        if old_term:
            old_term.is_current = False
            db.add(old_term)
        
        new_session.is_current = True
        new_term.is_current = True
        db.add(new_session)
        db.add(new_term)
        message = "Transition complete. New session is now active."
    else:
        message = "Transition finished with errors. Session status was not changed."

    db.commit()
    return {"message": message, "success_count": len(success), "fail_count": len(failed), "success_details": success, "failure_details": failed}


def get_class_enrollment_summary(
    class_id: str,
    session_id: Optional[str],
    term_id: Optional[str],
    db: Session
) -> dict:
    """
    Generates a summary of enrollments for a specific class.
    PERFORMANCE: Fetches all data with joins to minimize queries.
    """
    class_obj = db.get(Class, class_id)
    if not class_obj:
        raise HTTPException(status_code=404, detail="Class not found")

    query = select(Enrollment, User, StudentProfile).join(
        User, Enrollment.student_id == User.id
    ).join(
        StudentProfile, User.id == StudentProfile.user_id
    ).where(Enrollment.class_id == class_id)

    session_name, term_name = "All Sessions", "All Terms"
    if session_id:
        query = query.where(Enrollment.session_id == session_id)
        ac_session = db.get(AcademicSession, session_id)
        if ac_session: session_name = ac_session.name
    if term_id:
        query = query.where(Enrollment.term_id == term_id)
        term = db.get(Term, term_id)
        if term: term_name = term.name.value
        
    enrollment_results = db.exec(query).all()

    total_students = len(enrollment_results)
    active_enrollments = sum(1 for enr, _, __ in enrollment_results if enr.is_active)
    
    student_details = [
        {
            "student_id": enr.student_id,
            "name": f"{user.first_name} {user.last_name}",
            "admission_number": profile.admission_number,
            "enrollment_status": "Active" if enr.is_active else "Inactive",
            "enrolled_at": str(enr.enrolled_at)
        }
        for enr, user, profile in enrollment_results
    ]

    return {
        "class_id": class_id,
        "class_name": class_obj.name,
        "session_name": session_name,
        "term_name": term_name,
        "total_students": total_students,
        "active_enrollments": active_enrollments,
        "inactive_enrollments": total_students - active_enrollments,
        "students": student_details
    }