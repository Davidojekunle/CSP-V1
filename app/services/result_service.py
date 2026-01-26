# app/services/result_service.py
from sqlmodel import Session, select, and_, or_
from fastapi import HTTPException
from typing import Any, List, Optional
from collections import Counter
from datetime import datetime, date, timedelta
from sqlalchemy import case, distinct, func
from collections import defaultdict, Counter

from app.models import FormTeacherRemark, Enrollment, UserRole
from app.models import (Result, User, StudentProfile, Class, Subject,
                         AcademicSession, Term, ClassSubject,
                           Enrollment, TermName)
from app.schemas.result import BulkResultCreate, BulkResultItem, ResultResponse, ResultsEntryProgressResponse

from app.utils.grade_calculator import calculate_detailed_grade 


def _calculate_total(ca1: Optional[float], ca2: Optional[float], exam: Optional[float]) -> Optional[float]:
    scores = [s for s in [ca1, ca2, exam] if s is not None]
    return sum(scores) if scores else None

def bulk_upsert_results(data: BulkResultCreate, db: Session) -> dict:
    student_ids = [res.student_id for res in data.results]
    
    existing_results = db.exec(select(Result).where(
        Result.student_id.in_(student_ids),
        Result.subject_id == data.subject_id,
        Result.session_id == data.session_id,
        Result.term_id == data.term_id
    )).all()
    existing_map = {res.student_id: res for res in existing_results}

    created_count, updated_count = 0, 0
    
    for item in data.results:
        total = _calculate_total(item.ca1, item.ca2, item.exam)
        grade, remark = (None, None)
        if total is not None:
            grade, remark = calculate_detailed_grade(total)

        if item.student_id in existing_map:
            # Update
            result = existing_map[item.student_id]
            result.ca1, result.ca2, result.exam = item.ca1, item.ca2, item.exam
            result.total, result.grade_letter, result.remark = total, grade, remark
            db.add(result)
            updated_count += 1
        else:
            # Create
            new_result = Result(
                student_id=item.student_id, class_id=data.class_id,
                subject_id=data.subject_id, session_id=data.session_id,
                term_id=data.term_id, ca1=item.ca1, ca2=item.ca2, exam=item.exam,
                total=total, grade_letter=grade, remark=remark
            )
            db.add(new_result)
            created_count += 1
            
    db.commit()
    return {"created": created_count, "updated": updated_count}

def build_result_response(result: Result, session: Session) -> ResultResponse:
    """Build result response with related data"""
    # Get student info
    student = session.get(User, result.student_id)
    student_profile = session.exec(
        select(StudentProfile).where(StudentProfile.user_id == result.student_id)
    ).first()
    
    # Get class info
    class_obj = session.get(Class, result.class_id)
    
    # Get subject info
    subject = session.get(Subject, result.subject_id)
    
    # Get session info
    academic_session = session.get(AcademicSession, result.session_id)
    
    # Get term info
    term = session.get(Term, result.term_id)
    
    return ResultResponse(
        id=result.id,
        student_id=result.student_id,
        student_name=f"{student.first_name} {student.last_name}" if student else "Unknown",
        student_admission_number=student_profile.admission_number if student_profile else "N/A",
        class_id=result.class_id,
        class_name=class_obj.name if class_obj else "Unknown",
        subject_id=result.subject_id,
        subject_name=subject.name if subject else "Unknown",
        subject_code=subject.code if subject else "N/A",
        session_id=result.session_id,
        session_name=academic_session.name if academic_session else "Unknown",
        term_id=result.term_id,
        term_name=term.name if term else "Unknown",
        ca1=result.ca1,
        ca2=result.ca2,
        exam=result.exam,
        total=result.total,
        grade_letter=result.grade_letter,
        remark=result.remark
    )

def delete_result(result_id: str, db: Session):
    result = db.get(Result, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    db.delete(result)
    db.commit()


def get_filtered_results(
    db: Session,
    user: User,
    session_id: Optional[str], term_id: Optional[str], class_id: Optional[str],
    subject_id: Optional[str], student_id: Optional[str],
    skip: int, limit: int
) -> List[dict]:
    """
    PERFORMANCE OPTIMIZED: Fetches results with all related data in a single query
    using JOINs to prevent the N+1 problem.
    """
    query = select(
        Result, User, StudentProfile, Class, Subject, AcademicSession, Term
    ).join(
        User, Result.student_id == User.id
    ).join(
        StudentProfile, Result.student_id == StudentProfile.user_id
    ).join(
        Class, Result.class_id == Class.id
    ).join(
        Subject, Result.subject_id == Subject.id
    ).join(
        AcademicSession, Result.session_id == AcademicSession.id
    ).join(
        Term, Result.term_id == Term.id
    )

    conditions = []
    if user.role == UserRole.student:
        student_id = user.id
        conditions.append(Result.is_published == True)
    
    if session_id: conditions.append(Result.session_id == session_id)
    if term_id: conditions.append(Result.term_id == term_id)
    if class_id: conditions.append(Result.class_id == class_id)
    if subject_id: conditions.append(Result.subject_id == subject_id)
    if student_id: conditions.append(Result.student_id == student_id)
    
    if conditions: query = query.where(and_(*conditions))
    
    results = db.exec(query.offset(skip).limit(limit)).all()

    # Build the flat dictionary response required by the schema
    response_list = []
    for res, student, profile, cls, sub, ac_session, term in results:
        # This logic can be expanded to find the teacher name if needed
        response_list.append({
            "id": res.id,
            "student_id": res.student_id,
            "student_name": f"{student.first_name} {student.last_name}",
            "student_admission_number": profile.admission_number,
            "class_id": res.class_id,
            "class_name": cls.name,
            "subject_id": res.subject_id,
            "subject_name": sub.name,
            "subject_code": sub.code,
            "session_id": res.session_id,
            "session_name": ac_session.name,
            "term_id": res.term_id,
            "term_name": term.name.value,
            "ca1": res.ca1, "ca2": res.ca2, "exam": res.exam,
            "total": res.total, "grade_letter": res.grade_letter, "remark": res.remark,
            "is_published": res.is_published
            # teacher_id and teacher_name would require another join
        })
    return response_list


def get_results_entry_progress(session_id: str, term_id: str, db: Session) -> List[dict]:
    """
    PERFORMANCE: Calculates results entry progress using three efficient, grouped queries.
    """
    # 1. Get all assignments
    all_assignments_query = (
        select(
            ClassSubject.class_id,
            Class.name.label("class_name"),
            ClassSubject.subject_id,
            Subject.name.label("subject_name"),
            User.first_name,
            User.last_name
        )
        .select_from(ClassSubject)  # <--- FIX 1: Explicitly start FROM ClassSubject
        .join(Class, ClassSubject.class_id == Class.id)      # <--- FIX 2: Explicit ON clause
        .join(Subject, ClassSubject.subject_id == Subject.id)  # <--- FIX 2: Explicit ON clause
        .outerjoin(User, ClassSubject.teacher_id == User.id) # <--- FIX 2: Explicit ON clause
        .order_by(Class.name, Subject.name)
    )

    # The rest of the function remains exactly the same.
    all_assignments = db.exec(all_assignments_query).all()

    # 2. Get student counts per class
    enrollment_counts_query = select(Enrollment.class_id, func.count(Enrollment.student_id)).where(
        Enrollment.session_id == session_id, Enrollment.is_active == True
    ).group_by(Enrollment.class_id)
    enrollment_map = dict(db.exec(enrollment_counts_query).all())

    # 3. Get entered result counts per class-subject
    results_counts_query = select(Result.class_id, Result.subject_id, func.count(Result.student_id)).where(
        Result.session_id == session_id, Result.term_id == term_id
    ).group_by(Result.class_id, Result.subject_id)
    results_map = {(row[0], row[1]): row[2] for row in db.exec(results_counts_query).all()}

    # 4. Assemble in memory
    progress_items = []
    for assign in all_assignments:
        total_students = enrollment_map.get(assign.class_id, 0)
        if total_students == 0: continue # Skip classes with no students

        entered_students = results_map.get((assign.class_id, assign.subject_id), 0)
        status = "not_started"
        if entered_students > 0:
            status = "completed" if entered_students >= total_students else "in_progress"

        progress_items.append({
            "class_id": assign.class_id, "class_name": assign.class_name,
            "subject_id": assign.subject_id, "subject_name": assign.subject_name,
            "teacher_name": f"{assign.first_name} {assign.last_name}" if assign.first_name else "Unassigned",
            "total_students_enrolled": total_students,
            "students_with_results": entered_students,
            "status": status,
        })
    return progress_items


def build_result_response(result: Result, session: Session) -> ResultResponse:
    """Build result response with related data"""
    # Get student info
    student = session.get(User, result.student_id)
    student_profile = session.exec(
        select(StudentProfile).where(StudentProfile.user_id == result.student_id)
    ).first()
    
    # Get class info
    class_obj = session.get(Class, result.class_id)
    
    # Get subject info
    subject = session.get(Subject, result.subject_id)
    
    # Get session info
    academic_session = session.get(AcademicSession, result.session_id)
    
    # Get term info
    term = session.get(Term, result.term_id)
    
    return ResultResponse(
        id=result.id,
        student_id=result.student_id,
        student_name=f"{student.first_name} {student.last_name}" if student else "Unknown",
        student_admission_number=student_profile.admission_number if student_profile else "N/A",
        class_id=result.class_id,
        class_name=class_obj.name if class_obj else "Unknown",
        subject_id=result.subject_id,
        subject_name=subject.name if subject else "Unknown",
        subject_code=subject.code if subject else "N/A",
        session_id=result.session_id,
        session_name=academic_session.name if academic_session else "Unknown",
        term_id=result.term_id,
        term_name=term.name if term else "Unknown",
        ca1=result.ca1,
        ca2=result.ca2,
        exam=result.exam,
        total=result.total,
        grade_letter=result.grade_letter,
        remark=result.remark
    )

def get_class_performance_report(
    db: Session, class_id: str, session_id: str, term_id: str, subject_id: Optional[str]
) -> dict:
    """
    Generates a performance report for a class, either for a specific subject
    or an overall broadsheet. This is the full implementation.
    """
    class_obj = db.get(Class, class_id)
    academic_session = db.get(AcademicSession, session_id)
    term = db.get(Term, term_id)
    if not all([class_obj, academic_session, term]):
        raise HTTPException(status_code=404, detail="Class, session, or term not found.")

    # --- A: LOGIC FOR OVERALL CLASS BROADSHEET (NO SUBJECT_ID) ---
    if not subject_id:
        all_results = db.exec(select(Result).where(
            Result.class_id == class_id,
            Result.session_id == session_id,
            Result.term_id == term_id
        )).all()

        student_perf_map = defaultdict(lambda: {"total_score": 0.0, "subjects_taken": 0, "grades": []})
        for res in all_results:
            if res.total is not None:
                student_perf_map[res.student_id]["total_score"] += res.total
                student_perf_map[res.student_id]["subjects_taken"] += 1
                if res.grade_letter: student_perf_map[res.student_id]["grades"].append(res.grade_letter)

        ranked_list = []
        student_ids = list(student_perf_map.keys())
        users_map = {u.id: u for u in db.exec(select(User).where(User.id.in_(student_ids))).all()}
        profiles_map = {p.user_id: p for p in db.exec(select(StudentProfile).where(StudentProfile.user_id.in_(student_ids))).all()}

        for student_id, data in student_perf_map.items():
            if data["subjects_taken"] > 0:
                student = users_map.get(student_id)
                profile = profiles_map.get(student_id)
                ranked_list.append({
                    "student_id": student_id,
                    "name": f"{student.first_name} {student.last_name}" if student else "Unknown",
                    "admission_number": profile.admission_number if profile else "N/A",
                    "total": data["total_score"],
                    "average": data["total_score"] / data["subjects_taken"],
                    "subjects_taken": data["subjects_taken"]
                })
        
        ranked_list.sort(key=lambda x: x["average"], reverse=True)
        for i, student_data in enumerate(ranked_list):
            student_data["position"] = i + 1

        overall_avg = sum(s["average"] for s in ranked_list) / len(ranked_list) if ranked_list else 0.0
        all_grades = [grade for stud in student_perf_map.values() for grade in stud['grades']]
        grade_dist = {g: all_grades.count(g) for g in "ABCDF"}

        return {
            "class_id": class_id, "class_name": class_obj.name,
            "session_name": academic_session.name, "term_name": term.name.value,
            "subject_name": None,
            "total_students": len(ranked_list), "students_with_results": len(ranked_list),
            "class_average": round(overall_avg, 2),
            "highest_score": max(s['average'] for s in ranked_list) if ranked_list else None,
            "lowest_score": min(s['average'] for s in ranked_list) if ranked_list else None,
            "grade_distribution": grade_dist, "students": ranked_list
        }

    # --- B: LOGIC FOR SUBJECT-SPECIFIC REPORT (SUBJECT_ID GIVEN) ---
    else:
        subject = db.get(Subject, subject_id)
        if not subject: raise HTTPException(status_code=404, detail="Subject not found")

        results = db.exec(select(Result).where(
            Result.class_id == class_id, Result.subject_id == subject_id,
            Result.session_id == session_id, Result.term_id == term_id
        )).all()
        
        enrolled_students_count = db.exec(select(func.count(Enrollment.id)).where(
            Enrollment.class_id == class_id, Enrollment.session_id == session_id,
            Enrollment.is_active == True
        )).one()
        
        total_scores = [r.total for r in results if r.total is not None]
        class_avg = sum(total_scores) / len(total_scores) if total_scores else 0.0
        
        grade_dist = {g: 0 for g in "ABCDF"}
        for r in results:
            if r.grade_letter and r.grade_letter in grade_dist:
                grade_dist[r.grade_letter] += 1
        
        student_ids = [r.student_id for r in results]
        users_map = {u.id: u for u in db.exec(select(User).where(User.id.in_(student_ids))).all()}
        profiles_map = {p.user_id: p for p in db.exec(select(StudentProfile).where(StudentProfile.user_id.in_(student_ids))).all()}

        students_details = []
        for result in results:
            student = users_map.get(result.student_id)
            profile = profiles_map.get(result.student_id)
            students_details.append({
                "student_id": result.student_id,
                "name": f"{student.first_name} {student.last_name}" if student else "Unknown",
                "admission_number": profile.admission_number if profile else "N/A",
                "ca1": result.ca1, "ca2": result.ca2, "exam": result.exam,
                "total": result.total, "grade": result.grade_letter, "remark": result.remark
            })
            
        students_details.sort(key=lambda x: x["total"] or 0, reverse=True)
        for i, student_data in enumerate(students_details):
            student_data["position"] = i + 1
        
        return {
            "class_id": class_id, "class_name": class_obj.name,
            "session_name": academic_session.name, "term_name": term.name.value,
            "subject_name": subject.name,
            "total_students": enrolled_students_count, "students_with_results": len(results),
            "class_average": round(class_avg, 2),
            "highest_score": max(total_scores) if total_scores else None,
            "lowest_score": min(total_scores) if total_scores else None,
            "grade_distribution": grade_dist, "students": students_details
        }

def publish_or_unpublish_results(
    db: Session, 
    session_id: str, 
    term_id: str, 
    publish: bool,
    class_id: Optional[str] = None,  # Added default value None
) -> tuple[int, List[User]]:
    """
    Sets the is_published flag for a batch of results.
    """
    query = select(Result).where(
        Result.session_id == session_id,
        Result.term_id == term_id
    )
    if class_id:
        query = query.where(Result.class_id == class_id)

    results = db.exec(query).all()
    if not results:
        return 0, []
    
    affected_student_ids = list({res.student_id for res in results})
    
    for result in results:
        result.is_published = publish
        db.add(result)
    
    # Fetch student objects for background email tasks
    students_to_notify = db.exec(select(User).where(User.id.in_(affected_student_ids))).all()
    
    db.commit()
    
    return len(results), students_to_notify


def get_student_available_terms(db: Session, student_id: str, is_student_role: bool) -> List[dict]:
    """
    PERFORMANCE: Fetches all sessions/terms where a student has results,
    using optimized queries to avoid N+1.
    """
    query = select(Result.session_id, Result.term_id).where(
        Result.student_id == student_id
    ).distinct()

    if is_student_role:
        query = query.where(Result.is_published == True)

    term_pairs = db.exec(query).all()
    if not term_pairs:
        return []

    session_ids = {p[0] for p in term_pairs}
    term_ids = {p[1] for p in term_pairs}

    sessions = {s.id: s for s in db.exec(select(AcademicSession).where(AcademicSession.id.in_(session_ids))).all()}
    terms = {t.id: t for t in db.exec(select(Term).where(Term.id.in_(term_ids))).all()}

    available_terms = []
    for sid, tid in term_pairs:
        if sid in sessions and tid in terms:
            available_terms.append({
                "session_id": sid, "session_name": sessions[sid].name,
                "term_id": tid, "term_name": terms[tid].name.value
            })
            
    # Sort chronologically (newest first)
    term_order = {"First": 0, "Second": 1, "Third": 2}
    available_terms.sort(key=lambda x: (x["session_name"], term_order.get(x["term_name"], 99)), reverse=True)
    
    return available_terms


def get_student_performance_summary(db: Session, student_id: str, session_id: str, term_id: str, is_student_role: bool) -> dict:
    """
    PERFORMANCE: Aggregates a comprehensive performance summary for a student
    using a minimal number of efficient queries.
    """
    # 1. Get enrollment and current results
    enrollment = db.exec(select(Enrollment).where(Enrollment.student_id == student_id, Enrollment.session_id == session_id)).first()
    if not enrollment: raise HTTPException(status_code=404, detail="Enrollment not found for specified session.")
    
    results_query = select(Result).where(Result.student_id == student_id, Result.session_id == session_id, Result.term_id == term_id)
    if is_student_role: results_query = results_query.where(Result.is_published == True)
    current_results = db.exec(results_query).all()
    if not current_results: raise HTTPException(status_code=404, detail="No results found for specified term.")

    # 2. Get all class results for ranking
    all_class_results = db.exec(select(Result).where(
        Result.class_id == enrollment.class_id, Result.session_id == session_id, Result.term_id == term_id
    )).all()

    # 3. Calculate overall class position
    student_totals = defaultdict(float)
    for res in all_class_results:
        if res.total is not None: student_totals[res.student_id] += res.total
    
    ranked_students = sorted(student_totals.items(), key=lambda item: item[1], reverse=True)
    class_position = next((i + 1 for i, (s_id, _) in enumerate(ranked_students) if s_id == student_id), None)

    # 4. Calculate KPIs and grade distribution
    current_totals = [r.total for r in current_results if r.total is not None]
    overall_average = sum(current_totals) / len(current_totals) if current_totals else 0.0
    grade_counts = Counter(r.grade_letter for r in current_results if r.grade_letter)
    
    kpis = {
        "overall_average": round(overall_average, 2), "class_position": class_position,
        "total_students_in_class": len(ranked_students), "a_grades": grade_counts.get("A1", 0),
        "total_subjects": len(current_results)
    }
    # For now, comparison KPIs are omitted for simplicity, preserving the core response.
    # ... (prev_average, position_change logic would go here)
    
    return {"kpis": kpis, "grade_distribution": dict(grade_counts), "results": current_results}

# In app/services/result_service.py

# Add these imports at the top if they are missing
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import re


# ADD a helper function for suffixing numbers (e.g., 1st, 2nd, 3rd)
def _get_rank_suffix(rank: int) -> str:
    if 11 <= rank <= 13:
        return 'th'
    return {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')

def _ensure_date(d: Any) -> Optional[date]:
    """Ensures a value is a date object (converts string if needed)."""
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        try:
            return datetime.fromisoformat(d.split('T')[0]).date()
        except:
            return None
    return None


def get_data_for_detailed_report(student_id: str, session_id: str, term_id: str, db: Session) -> dict:
    student = db.get(User, student_id)
    if not student: raise HTTPException(status_code=404, detail="Student not found")
    
    student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
    student_results = db.exec(select(Result).where(
        Result.student_id == student_id, Result.session_id == session_id, Result.term_id == term_id
    )).all()
    
    if not student_results: raise HTTPException(status_code=404, detail="No results found.")

    class_obj = db.get(Class, student_results[0].class_id)
    academic_session = db.get(AcademicSession, session_id)
    term = db.get(Term, term_id)
    
    all_class_results = db.exec(select(Result).where(
        Result.class_id == class_obj.id, Result.session_id == session_id, Result.term_id == term_id
    )).all()
    
    results_by_subject = defaultdict(list)
    student_totals = defaultdict(float)
    for res in all_class_results:
        if res.total is not None:
            results_by_subject[res.subject_id].append({'student_id': res.student_id, 'total': res.total})
            student_totals[res.student_id] += res.total

    subject_averages = {sub_id: sum(s['total'] for s in scores) / len(scores) for sub_id, scores in results_by_subject.items() if scores}
    subject_ranks = defaultdict(dict)
    for sub_id, scores in results_by_subject.items():
        sorted_scores = sorted(scores, key=lambda x: x['total'], reverse=True)
        for rank, score_data in enumerate(sorted_scores, 1):
            subject_ranks[sub_id][score_data['student_id']] = f"{rank}{_get_rank_suffix(rank)}"

    final_results_data = []
    subject_ids = [res.subject_id for res in student_results]
    subject_map = {sub.id: sub for sub in db.exec(select(Subject).where(Subject.id.in_(subject_ids))).all()}
    
    for res in student_results:
        subject = subject_map.get(res.subject_id)
        if not subject: continue
        grade, remark = calculate_detailed_grade(res.total)
        final_results_data.append({
            'subject_name': str(subject.name or "Unknown"), 
            'ca1': res.ca1 or 0, 'ca2': res.ca2 or 0, 'exam': res.exam or 0,
            'total': res.total or 0, 'grade': str(grade), 'remark': str(remark),
            'class_average': subject_averages.get(res.subject_id, 0.0),
            'subject_position': subject_ranks.get(res.subject_id, {}).get(student_id, 'N/A')
        })

    ranked_students = sorted(student_totals.items(), key=lambda item: item[1], reverse=True)
    class_pos = "N/A"
    for rank, (s_id, total) in enumerate(ranked_students, 1):
        if s_id == student_id:
            class_pos = f"{rank}{_get_rank_suffix(rank)}"
            break
            
    num_subjects = len(final_results_data)
    student_average = (student_totals.get(student_id, 0.0) / num_subjects) if num_subjects > 0 else 0.0
    grade_counts = Counter(res['grade'] for res in final_results_data if res['grade'])
    
    remark_obj = db.exec(select(FormTeacherRemark).where(FormTeacherRemark.student_id == student_id, FormTeacherRemark.term_id == term_id)).first()
    
    term_end = _ensure_date(term.end_date if term else None)
    next_start = (term_end + timedelta(days=14)).strftime('%B %d, %Y') if term_end else "TBA"
    next_end = (term_end + timedelta(days=104)).strftime('%B %d, %Y') if term_end else "TBA"
    
    return {
        "student_data": {
            'student_name': f"{str(student.first_name)} {str(student.last_name)}".upper(),
            'admission_number': str(student_profile.admission_number) if student_profile else "N/A",
            'username': str(student.username), 
            'gender': str(student.gender.value) if hasattr(student.gender, 'value') else str(student.gender or "N/A"),
            'email': str(student.email or "N/A"), 'phone': str(student.phone or "N/A"),
            'profile_picture_url': student.profile_picture_url
        },
        "results_data": final_results_data,
        "session_info": {
            'session_name': str(academic_session.name) if academic_session else "N/A", 
            'term_name': str(term.name.value) if term and hasattr(term.name, 'value') else str(term.name or "N/A"),
            'next_term_begins': next_start, 'next_term_ends': next_end
        },
        "summary_data": {
            "overall_average": float(student_average), "class_position": str(class_pos),
            "total_students": int(len(ranked_students)), 
            "grades_summary": ", ".join([f"{count}({grade})" for grade, count in sorted(grade_counts.items())])
        },
        "form_teacher_remark": str(remark_obj.remark_text) if remark_obj else "No remark provided.",
        "class_obj": class_obj
    }



# --- ADD FUNCTION 2 of 3 (for Cumulative Report) ---
def get_data_for_cumulative_report(student_id: str, session_id: str, user_role: UserRole, db: Session) -> dict:
    """
    Fetches and processes all data required to generate a cumulative report card.
    """
    student = db.get(User, student_id)
    if not student: raise HTTPException(status_code=404, detail="Student not found")
    
    student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
    academic_session = db.get(AcademicSession, session_id)
    if not academic_session: raise HTTPException(status_code=404, detail="Session not found")

    terms_in_session = db.exec(select(Term).where(Term.session_id == session_id)).all()
    term_map = {term.name: term for term in terms_in_session}
    if not all(t in term_map for t in [TermName.first, TermName.second, TermName.third]):
        raise HTTPException(status_code=400, detail="All three terms are required to generate this report.")

    third_term_obj = term_map[TermName.third]
    
    enrollment = db.exec(select(Enrollment).where(Enrollment.student_id == student_id, Enrollment.session_id == session_id)).first()
    if not enrollment: raise HTTPException(status_code=404, detail="Student enrollment for this session not found.")

    class_obj = db.get(Class, enrollment.class_id)
    
    if user_role == UserRole.student:
        if not db.exec(select(Result).where(Result.student_id == student_id, Result.term_id == third_term_obj.id, Result.is_published == True)).first():
            raise HTTPException(status_code=403, detail="Cumulative report not available until Third Term results are published.")

    # ... The rest of the complex data fetching and calculation logic from your `_get_student_cumulative_session_data`
    # would be pasted here, ending with a structured dictionary return.
    
    # This is a placeholder for that long logic block
    return {"message": "Cumulative data processing would happen here"}


def get_admin_dashboard_stats(session_id: str, term_id: str, db: Session) -> dict:
    """
    PERFORMANCE: Calculates aggregated stats for the admin results dashboard
    using efficient, grouped queries to prevent N+1 issues.
    """
    # 1. Get term-wide result counts
    results_summary_query = select(
        func.count(Result.id),
        func.count(Result.id).filter(Result.is_published == True)
    ).where(Result.session_id == session_id, Result.term_id == term_id)
    total_results_entered, published_results = db.exec(results_summary_query).one()

    # 2. Pre-fetch counts grouped by class (highly efficient)
    students_per_class_query = select(Enrollment.class_id, func.count(Enrollment.id)).where(
        Enrollment.session_id == session_id, Enrollment.is_active == True
    ).group_by(Enrollment.class_id)
    students_map = dict(db.exec(students_per_class_query).all())

    subjects_per_class_query = select(ClassSubject.class_id, func.count(ClassSubject.id)).group_by(ClassSubject.class_id)
    subjects_map = dict(db.exec(subjects_per_class_query).all())
    
    entered_per_class_query = select(Result.class_id, func.count(Result.id)).where(
        Result.session_id == session_id, Result.term_id == term_id
    ).group_by(Result.class_id)
    entered_map = dict(db.exec(entered_per_class_query).all())

    # 3. Calculate totals in memory (very fast)
    total_possible = 0
    completed_classes = 0
    active_class_ids = students_map.keys()

    for class_id in active_class_ids:
        possible_for_class = students_map.get(class_id, 0) * subjects_map.get(class_id, 0)
        total_possible += possible_for_class
        
        entered_for_class = entered_map.get(class_id, 0)
        if possible_for_class > 0 and entered_for_class >= possible_for_class:
            completed_classes += 1

    return {
        "total_possible_results": total_possible,
        "total_results_entered": total_results_entered,
        "published_results": published_results,
        "pending_entry": max(0, total_possible - total_results_entered),
        "total_active_classes": len(active_class_ids),
        "completed_classes": completed_classes,
        "data_discrepancy_warning": total_results_entered > total_possible
    }

def check_publication_readiness(session_id: str, term_id: str, class_id: Optional[str], db: Session) -> dict:
    """
    PERFORMANCE: Checks if results are ready for publication using a minimal number
    of efficient, bulk queries.
    """
    # 1. Get all enrolled students for the scope
    enrollment_query = select(Enrollment).where(Enrollment.session_id == session_id)
    if class_id:
        enrollment_query = enrollment_query.where(Enrollment.class_id == class_id)
    enrolled_students = db.exec(enrollment_query).all()
    if not enrolled_students:
        raise HTTPException(status_code=404, detail="No enrolled students found for this scope.")

    student_ids = [e.student_id for e in enrolled_students]
    class_ids_in_scope = list({e.class_id for e in enrolled_students})

    # 2. Pre-fetch all necessary data in bulk to avoid N+1 queries
    # Fetch subjects per class
    subjects_per_class_query = select(ClassSubject.class_id, Subject.id, Subject.name).join(Subject).where(
        ClassSubject.class_id.in_(class_ids_in_scope)
    )
    subjects_per_class_list = db.exec(subjects_per_class_query).all()
    
    expected_subjects_map = defaultdict(list)
    subject_id_to_name_map = {}
    for cid, sid, s_name in subjects_per_class_list:
        expected_subjects_map[cid].append(s_name)
        subject_id_to_name_map[sid] = s_name

    # Fetch all results for all students in scope
    results_query = select(Result).where(Result.student_id.in_(student_ids), Result.term_id == term_id)
    all_results = db.exec(results_query).all()
    results_map = defaultdict(list)
    for r in all_results:
        results_map[r.student_id].append(r)
        
    # Fetch all student user objects in one query
    students_user_map = {u.id: u for u in db.exec(select(User).where(User.id.in_(student_ids))).all()}

    # 3. Check publication status
    is_published = any(r.is_published for r in all_results)

    # 4. Process each student in memory
    complete_count, incomplete_count, no_results_count = 0, 0, 0
    incomplete_details = []

    for enrollment in enrolled_students:
        student = students_user_map.get(enrollment.student_id)
        if not student: continue

        expected_subject_names = expected_subjects_map.get(enrollment.class_id, [])
        student_results = results_map.get(enrollment.student_id, [])
        
        actual_count = len(student_results)
        expected_count = len(expected_subject_names)
        
        if actual_count < expected_count:
            incomplete_count += 1
            if actual_count == 0:
                no_results_count += 1
            
            entered_subject_names = {subject_id_to_name_map.get(res.subject_id) for res in student_results}
            missing = sorted(list(set(expected_subject_names) - entered_subject_names))
            
            incomplete_details.append({
                "student_name": f"{student.first_name} {student.last_name}",
                "student_id": student.id,
                "expected_results": expected_count,
                "actual_results": actual_count,
                "missing_subjects": missing
            })
        else:
            complete_count += 1

    return {
        "is_published": is_published,
        "total_students_in_scope": len(enrolled_students),
        "complete_students": complete_count,
        "incomplete_students": incomplete_count,
        "students_with_no_results": no_results_count,
        "incomplete_details": incomplete_details
    }