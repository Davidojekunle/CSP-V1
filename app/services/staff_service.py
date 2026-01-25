from sqlmodel import Session, select, func, and_
from fastapi import HTTPException
from typing import List, Dict, Any, Optional

from app.models import (
    User, UserRole, AcademicSession, Term, Class, Subject, ClassSubject, Enrollment, Result, StaffProfile, StudentProfile
)
from app.services import user_service

def get_staff_dashboard_data(staff_user: User, db: Session) -> dict:
    """
    PERFORMANCE: Aggregates all data for the staff dashboard using optimized queries
    to prevent N+1 issues.
    """
    current_session = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).first()
    current_term = db.exec(select(Term).where(Term.is_current == True)).first()
    if not current_session or not current_term:
        raise HTTPException(status_code=400, detail="No current academic session or term is set.")
        
    # --- THIS IS THE FIX ---
    # 1. Define all variables with default values at the top.
    assigned_classes_list = []
    results_summary = {"total_classes": 0, "total_students": 0, "results_entered": 0, "results_pending": 0}
    user_info_response = user_service.build_user_response(staff_user, db)

    # 2. Query for assigned subjects.
    assigned_subjects_query = select(Class, Subject).join(
        ClassSubject, Class.id == ClassSubject.class_id
    ).join(
        Subject, Subject.id == ClassSubject.subject_id
    ).where(ClassSubject.teacher_id == staff_user.id).order_by(Class.name, Subject.name)
    assigned_subjects = db.exec(assigned_subjects_query).all()

    # 3. Only run the complex logic if assignments exist.
    if assigned_subjects:
        teacher_class_ids = list({cls.id for cls, sub in assigned_subjects})
        
        # Perform bulk queries
        enrollment_counts_query = select(Enrollment.class_id, func.count(Enrollment.id)).where(
            Enrollment.class_id.in_(teacher_class_ids),
            Enrollment.session_id == current_session.id,
            Enrollment.is_active == True
        ).group_by(Enrollment.class_id)
        enrollment_map = dict(db.exec(enrollment_counts_query).all())

        results_counts_query = select(Result.class_id, Result.subject_id, func.count(Result.id)).where(
            Result.class_id.in_(teacher_class_ids),
            Result.session_id == current_session.id,
            Result.term_id == current_term.id
        ).group_by(Result.class_id, Result.subject_id)
        results_map = {(row[0], row[1]): row[2] for row in db.exec(results_counts_query).all()}

        all_student_ids_query = select(Enrollment.student_id).where(
            Enrollment.class_id.in_(teacher_class_ids),
            Enrollment.session_id == current_session.id,
            Enrollment.is_active == True
        ).distinct()
        total_unique_students = len(db.exec(all_student_ids_query).all())

        # Assemble the lists
        total_results_entered = 0
        total_potential_results = 0
        for class_obj, subject in assigned_subjects:
            students_count = enrollment_map.get(class_obj.id, 0)
            results_entered = results_map.get((class_obj.id, subject.id), 0)
            
            total_results_entered += results_entered
            total_potential_results += students_count

            assigned_classes_list.append({
                "id": class_obj.id, "name": class_obj.name, "level": class_obj.level, "arm": class_obj.arm,
                "subject_id": subject.id, "subject_name": subject.name, "subject_code": subject.code,
                "students_count": students_count,
                "results_entered": results_entered,
                "results_pending": max(0, students_count - results_entered)
            })
            
        # Overwrite the default results_summary
        results_summary = {
            "total_classes": len(assigned_subjects),
            "total_students": total_unique_students,
            "results_entered": total_results_entered,
            "results_pending": max(0, total_potential_results - total_results_entered)
        }

    # 4. The final return statement now works in all cases.
    return {
        "user_info": user_info_response.model_dump(),
        "assigned_classes": assigned_classes_list,
        "results_summary": results_summary,
        "current_session": current_session,
        "current_term": current_term,
        "recent_activities": []
    }


def get_my_classes(staff_user: User, db: Session) -> List[dict]:
    """
    PERFORMANCE: Fetches assigned classes and their stats for a teacher
    using efficient, grouped queries.
    """
    current_session = db.exec(select(AcademicSession).where(AcademicSession.is_current == True)).first()
    current_term = db.exec(select(Term).where(Term.is_current == True)).first()
    if not current_session or not current_term:
        return []

    # 1. Get all assignments with joined data
    class_subjects = db.exec(select(ClassSubject, Class, Subject)
        .join(Class).join(Subject)
        .where(ClassSubject.teacher_id == staff_user.id)
        .order_by(Class.name, Subject.name)
    ).all()

    class_ids = [cs.class_id for cs, _, __ in class_subjects]
    if not class_ids: return []

    # 2. Get all student counts in one query
    student_counts_query = select(Enrollment.class_id, func.count(Enrollment.id)).where(
        Enrollment.class_id.in_(class_ids),
        Enrollment.session_id == current_session.id,
        Enrollment.is_active == True
    ).group_by(Enrollment.class_id)
    student_counts_map = dict(db.exec(student_counts_query).all())

    # 3. Get all result counts in one query
    results_counts_query = select(Result.class_id, Result.subject_id, func.count(Result.id)).where(
        Result.class_id.in_(class_ids),
        Result.session_id == current_session.id,
        Result.term_id == current_term.id
    ).group_by(Result.class_id, Result.subject_id)
    results_counts_map = {(r[0], r[1]): r[2] for r in db.exec(results_counts_query).all()}

    # 4. Assemble in memory
    response_list = []
    for cs, class_obj, subject in class_subjects:
        students_count = student_counts_map.get(class_obj.id, 0)
        results_entered = results_counts_map.get((class_obj.id, subject.id), 0)
        response_list.append({
            "id": class_obj.id, "name": class_obj.name, "level": class_obj.level, "arm": class_obj.arm,
            "subject_id": subject.id, "subject_name": subject.name, "subject_code": subject.code,
            "students_count": students_count,
            "results_entered": results_entered,
            "results_pending": max(0, students_count - results_entered)
        })
    return response_list

def update_staff_profile(staff_user: User, profile_data: dict, db: Session) -> StaffProfile:
    """Updates the profile for the currently logged-in staff member."""
    profile = db.exec(select(StaffProfile).where(StaffProfile.user_id == staff_user.id)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Staff profile not found.")
    
    for key, value in profile_data.items():
        setattr(profile, key, value)
    
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile