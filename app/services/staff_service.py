import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, and_
from fastapi import HTTPException
from typing import List, Dict, Any, Optional
from app.schemas.staff import   BehavioralTraitsCreate, FormClassOverviewResponse, BehavioralTraitsResponse, BulkFormTeacherRemarkCreate
from collections import defaultdict
from app.models import FormTeacherRemark, BehavioralTraits, InvoiceStatus, Invoice
from app.services.pdf.report_card import report_card_service
from fastapi.responses import Response


from app.models import (
    User, UserRole, AcademicSession, Term, Class, Subject, ClassSubject, Enrollment, Result, StaffProfile, StudentProfile
)
from app.services import user_service

async def get_staff_dashboard_data(staff_user: User, db: AsyncSession) -> dict:
    """
    PERFORMANCE: Aggregates all data for the staff dashboard using optimized queries
    to prevent N+1 issues.
    """
    current_session_result = await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))
    current_session = current_session_result.scalars().first()
    current_term_result = await db.execute(select(Term).where(Term.is_current == True))
    current_term = current_term_result.scalars().first()
    if not current_session or not current_term:
        raise HTTPException(status_code=400, detail="No current academic session or term is set.")
        
    # --- THIS IS THE FIX ---
    # 1. Define all variables with default values at the top.
    assigned_classes_list = []
    results_summary = {"total_classes": 0, "total_students": 0, "results_entered": 0, "results_pending": 0}
    user_info_response = await user_service.build_user_response(staff_user, db)

    # 2. Query for assigned subjects.
    assigned_subjects_query = select(Class, Subject).join(
        ClassSubject, Class.id == ClassSubject.class_id
    ).join(
        Subject, Subject.id == ClassSubject.subject_id
    ).where(ClassSubject.teacher_id == staff_user.id).order_by(Class.name, Subject.name)
    assigned_subjects_result = await db.execute(assigned_subjects_query)
    assigned_subjects = assigned_subjects_result.all()

    # 3. Only run the complex logic if assignments exist.
    if assigned_subjects:
        teacher_class_ids = list({cls.id for cls, sub in assigned_subjects})
        
        # Perform bulk queries
        enrollment_counts_query = select(Enrollment.class_id, func.count(Enrollment.id)).where(
            Enrollment.class_id.in_(teacher_class_ids),
            Enrollment.session_id == current_session.id,
            Enrollment.is_active == True
        ).group_by(Enrollment.class_id)
        enrollment_counts_result = await db.execute(enrollment_counts_query)
        enrollment_map = dict(enrollment_counts_result.all())

        results_counts_query = select(Result.class_id, Result.subject_id, func.count(Result.id)).where(
            Result.class_id.in_(teacher_class_ids),
            Result.session_id == current_session.id,
            Result.term_id == current_term.id
        ).group_by(Result.class_id, Result.subject_id)
        results_counts_result = await db.execute(results_counts_query)
        results_map = {(row[0], row[1]): row[2] for row in results_counts_result.all()}

        all_student_ids_query = select(Enrollment.student_id).where(
            Enrollment.class_id.in_(teacher_class_ids),
            Enrollment.session_id == current_session.id,
            Enrollment.is_active == True
        ).distinct()
        all_student_ids_result = await db.execute(all_student_ids_query)
        total_unique_students = len(all_student_ids_result.all())

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


async def get_my_classes(staff_user: User, db: AsyncSession) -> List[dict]:
    """
    PERFORMANCE: Fetches assigned classes and their stats for a teacher
    using efficient, grouped queries.
    """
    result_session = await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))
    current_session = result_session.scalars().first()
    result_term = await db.execute(select(Term).where(Term.is_current == True))
    current_term = result_term.scalars().first()
    if not current_session or not current_term:
        return []

    # 1. Get all assignments with joined data
    result_cs = await db.execute(select(ClassSubject, Class, Subject)
        .join(Class).join(Subject)
        .where(ClassSubject.teacher_id == staff_user.id)
        .order_by(Class.name, Subject.name)
    )
    class_subjects = result_cs.all()

    class_ids = [cs.class_id for cs, _, __ in class_subjects]
    if not class_ids: return []

    # 2. Get all student counts in one query
    student_counts_query = select(Enrollment.class_id, func.count(Enrollment.id)).where(
        Enrollment.class_id.in_(class_ids),
        Enrollment.session_id == current_session.id,
        Enrollment.is_active == True
    ).group_by(Enrollment.class_id)
    result_counts = await db.execute(student_counts_query)
    student_counts_map = dict(result_counts.all())

    # 3. Get all result counts in one query
    results_counts_query = select(Result.class_id, Result.subject_id, func.count(Result.id)).where(
        Result.class_id.in_(class_ids),
        Result.session_id == current_session.id,
        Result.term_id == current_term.id
    ).group_by(Result.class_id, Result.subject_id)
    result_results = await db.execute(results_counts_query)
    results_counts_map = {(r[0], r[1]): r[2] for r in result_results.all()}

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

async def update_staff_profile(staff_user: User, profile_data: dict, db: AsyncSession) -> StaffProfile:
    """Updates the profile for the currently logged-in staff member."""
    profile_result = await db.execute(select(StaffProfile).where(StaffProfile.user_id == staff_user.id))
    profile = profile_result.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Staff profile not found.")
    
    for key, value in profile_data.items():
        setattr(profile, key, value)
    
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile

async def get_students_for_my_class(staff_user: User, class_id: str, db: AsyncSession) -> List[dict]:
    """
    Fetches students for a class, but only if the staff member is assigned to teach
    at least one subject in that class.
    """
    # 1. Authorization: Verify the teacher is assigned to this class.
    assignment_result = await db.execute(select(ClassSubject).where(
        ClassSubject.class_id == class_id,
        ClassSubject.teacher_id == staff_user.id
    ))
    assignment = assignment_result.scalars().first()
    if not assignment:
        raise HTTPException(status_code=403, detail="You are not assigned to teach in this class.")

    current_session_result = await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))
    current_session = current_session_result.scalars().first()
    if not current_session: raise HTTPException(status_code=400, detail="No current academic session set.")

    # 2. PERFORMANCE: Fetch all enrolled students and their results status in bulk.
    enrolled_students_query = select(User, StudentProfile, Enrollment).join(StudentProfile).join(Enrollment).where(
        Enrollment.class_id == class_id,
        Enrollment.session_id == current_session.id,
        Enrollment.is_active == True
    ).order_by(User.last_name, User.first_name)
    enrolled_students_result = await db.execute(enrolled_students_query)
    enrolled_students = enrolled_students_result.all()

    student_ids = [user.id for user, _, __ in enrolled_students]
    if not student_ids: return []

    # Check which students have a result for the teacher's specific subject in this class
    results_for_subject_query = select(Result.student_id).where(
        Result.student_id.in_(student_ids),
        Result.class_id == class_id,
        Result.subject_id == assignment.subject_id, # Check against the first found assignment
        Result.session_id == current_session.id
    )
    students_with_results_result = await db.execute(results_for_subject_query)
    students_with_results = set(students_with_results_result.scalars().all())
    
    # 3. Assemble response
    response_list = []
    for user, profile, enrollment in enrolled_students:
        response_list.append({
            "id": user.id,
            "name": f"{user.first_name} {user.last_name}",
            "admission_number": profile.admission_number,
            "enrollment_status": enrollment.is_active,
            "has_results": user.id in students_with_results
        })
    return response_list


async def get_results_for_my_class_subject(staff_user: User, class_id: str, subject_id: str, db: AsyncSession) -> List[dict]:
    """
    Fetches the marksheet for a specific class and subject, but only if the
    staff member is assigned to teach it.
    """
    # 1. Authorization: Verify this specific assignment.
    assignment_result = await db.execute(select(ClassSubject).where(
        ClassSubject.class_id == class_id,
        ClassSubject.subject_id == subject_id,
        ClassSubject.teacher_id == staff_user.id
    ))
    assignment = assignment_result.scalars().first()
    if not assignment:
        raise HTTPException(status_code=403, detail="You are not assigned to teach this subject in this class.")

    current_session_result = await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))
    current_session = current_session_result.scalars().first()
    current_term_result = await db.execute(select(Term).where(Term.is_current == True))
    current_term = current_term_result.scalars().first()
    if not current_session or not current_term:
        raise HTTPException(status_code=400, detail="No current academic session or term set.")

    # 2. Get all enrolled students for the class
    enrolled_students_result = await db.execute(select(User, StudentProfile).join(StudentProfile).join(Enrollment).where(
        Enrollment.class_id == class_id,
        Enrollment.session_id == current_session.id,
        Enrollment.is_active == True
    ).order_by(User.last_name, User.first_name))
    enrolled_students = enrolled_students_result.all()
    
    if not enrolled_students: return []
    student_ids = [user.id for user, _ in enrolled_students]

    # 3. Get all existing results for this context in one query
    results_result = await db.execute(select(Result).where(
        Result.student_id.in_(student_ids),
        Result.class_id == class_id,
        Result.subject_id == subject_id,
        Result.session_id == current_session.id,
        Result.term_id == current_term.id
    ))
    results_map = {res.student_id: res for res in results_result.scalars().all()}

    # 4. Assemble the response marksheet
    marksheet = []
    for user, profile in enrolled_students:
        result = results_map.get(user.id)
        marksheet.append({
            "id": result.id if result else None,
            "student_id": user.id,
            "student_name": f"{user.first_name} {user.last_name}",
            "student_admission_number": profile.admission_number,
            "ca1": result.ca1 if result else None,
            "ca2": result.ca2 if result else None,
            "exam": result.exam if result else None,
            "total": result.total if result else None,
            "grade_letter": result.grade_letter if result else None,
            "remark": result.remark if result else None,
        })
    return marksheet
async def _get_form_class_for_teacher(staff_user: User, db: AsyncSession) -> Class:
    """Helper to find and authorize the form teacher's class."""
    form_class_result = await db.execute(select(Class).where(Class.form_teacher_id == staff_user.id).order_by(Class.created_at, Class.name, Class.id))
    form_class = form_class_result.scalars().first()
    if not form_class:
        raise HTTPException(status_code=403, detail="You are not assigned as a Form Teacher to any class.")
    return form_class

async def get_form_class_overview(staff_user: User, db: AsyncSession) -> dict:
    """
    PERFORMANCE: Gathers a comprehensive overview for a Form Teacher's class
    using a minimal number of bulk queries.
    """
    form_class = await _get_form_class_for_teacher(staff_user, db)
    result_session = await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))
    current_session = result_session.scalars().first()
    result_term = await db.execute(select(Term).where(Term.is_current == True))
    current_term = result_term.scalars().first()
    if not current_session or not current_term:
        raise HTTPException(status_code=400, detail="No current academic session or term is set.")

    # 1. Get all enrolled students in the form class
    result_students = await db.execute(select(User, StudentProfile).join(StudentProfile).join(Enrollment).where(
        Enrollment.class_id == form_class.id,
        Enrollment.session_id == current_session.id,
        Enrollment.is_active == True
    ).order_by(User.last_name, User.first_name))
    enrolled_students = result_students.all()
    if not enrolled_students:
        return {
            "class_id": form_class.id, "class_name": form_class.name,
            "session_name": current_session.name, "term_name": current_term.name.value,
            "students": []
        }
    
    student_ids = [user.id for user, _ in enrolled_students]

    # 2. Bulk fetch all related data (results, invoices, remarks)
    result_results = await db.execute(select(Result).where(Result.student_id.in_(student_ids), Result.session_id == current_session.id, Result.term_id == current_term.id))
    all_results = result_results.scalars().all()
    result_invoices = await db.execute(select(Invoice.student_id, func.sum(Invoice.balance_due).label("total_due"), func.count(Invoice.id).label("invoice_count")).where(
        Invoice.student_id.in_(student_ids), Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.partial, InvoiceStatus.overdue])
    ).group_by(Invoice.student_id))
    pending_invoices = result_invoices.all()
    result_remarks = await db.execute(select(FormTeacherRemark).where(
        FormTeacherRemark.student_id.in_(student_ids), FormTeacherRemark.session_id == current_session.id, FormTeacherRemark.term_id == current_term.id
    ))
    all_remarks = result_remarks.scalars().all()

    # 3. Process into efficient lookup maps
    academic_map = defaultdict(lambda: {"total_score": 0.0, "subjects_taken": 0})
    for r in all_results:
        if r.total is not None:
            academic_map[r.student_id]["total_score"] += r.total
            academic_map[r.student_id]["subjects_taken"] += 1
    
    financial_map = {row.student_id: {"balance": row.total_due, "count": row.invoice_count} for row in pending_invoices}
    remarks_map = {remark.student_id: remark.remark_text for remark in all_remarks}

    # 4. Assemble final response in memory
    student_summaries = []
    for user, profile in enrolled_students:
        acad_data = academic_map[user.id]
        fin_data = financial_map.get(user.id, {"balance": 0.0, "count": 0})
        
        student_summaries.append({
            "student_id": user.id, "full_name": f"{user.first_name} {user.last_name}",
            "admission_number": profile.admission_number, "profile_picture_url": user.profile_picture_url,
            "overall_average": round(acad_data["total_score"] / acad_data["subjects_taken"], 2) if acad_data["subjects_taken"] > 0 else None,
            "subjects_taken": acad_data["subjects_taken"],
            "outstanding_balance": float(fin_data["balance"]),
            "pending_invoices_count": fin_data["count"],
            "form_teacher_remark": remarks_map.get(user.id)
        })

    return {
        "class_id": form_class.id, "class_name": form_class.name,
        "session_name": current_session.name, "term_name": current_term.name.value,
        "students": student_summaries
    }


async def create_or_update_behavioral_traits(staff_user: User, traits_data: BehavioralTraitsCreate, db: AsyncSession) -> BehavioralTraits:
    await _get_form_class_for_teacher(staff_user, db)  # 403 if not a form teacher at all
    # A teacher can be form teacher of several classes; any of them authorizes
    form_class_ids = select(Class.id).where(Class.form_teacher_id == staff_user.id)
    result_session = await db.execute(select(AcademicSession).where(AcademicSession.is_current == True))
    current_session = result_session.scalars().first()
    result_term = await db.execute(select(Term).where(Term.is_current == True))
    current_term = result_term.scalars().first()
    if not current_session or not current_term:
        raise HTTPException(status_code=400, detail="No current academic session or term set.")

    # Authorization: Check if student is in the form teacher's class
    result_enrollment = await db.execute(select(Enrollment).where(
        Enrollment.student_id == traits_data.student_id,
        Enrollment.class_id.in_(form_class_ids),
        Enrollment.session_id == current_session.id,
        Enrollment.is_active == True
    ))
    enrollment = result_enrollment.scalars().first()
    if not enrollment:
        raise HTTPException(status_code=403, detail="This student is not in your form class for the current session.")

    result_existing = await db.execute(select(BehavioralTraits).where(
        BehavioralTraits.student_id == traits_data.student_id,
        BehavioralTraits.session_id == current_session.id,
        BehavioralTraits.term_id == current_term.id
    ))
    existing = result_existing.scalars().first()
    
    if existing:
        update_dict = traits_data.model_dump(exclude_unset=True, exclude={'student_id'})
        for key, value in update_dict.items():
            setattr(existing, key, value)
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        return existing
    else:
        new_traits = BehavioralTraits(
            **traits_data.model_dump(),
            session_id=current_session.id,
            term_id=current_term.id
        )
        db.add(new_traits)
        await db.commit()
        await db.refresh(new_traits)
        return new_traits   
    
async def bulk_create_or_update_form_teacher_remarks(staff_user: User, bulk_data: BulkFormTeacherRemarkCreate, db: AsyncSession) -> int:
    """
    PERFORMANCE: Creates or updates remarks for multiple students in a class at once,
    using bulk fetching to optimize DB calls.
    """
    # 1. Authorization: Verify the staff member is the form teacher of this class
    result_class = await db.execute(select(Class).where(Class.id == bulk_data.class_id))
    student_class = result_class.scalars().first()
    if not student_class or student_class.form_teacher_id != staff_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You are not the form teacher for this class.")

    # 2. Bulk fetch all existing remarks for these students in one query
    student_ids = [item.student_id for item in bulk_data.remarks]
    result_remarks = await db.execute(select(FormTeacherRemark).where(
        FormTeacherRemark.student_id.in_(student_ids),
        FormTeacherRemark.session_id == bulk_data.session_id,
        FormTeacherRemark.term_id == bulk_data.term_id
    ))
    existing_remarks = result_remarks.scalars().all()
    existing_remarks_map = {remark.student_id: remark for remark in existing_remarks}

    # 3. Process each remark (Update or Create)
    processed_count = 0
    for item in bulk_data.remarks:
        remark = existing_remarks_map.get(item.student_id)
        
        if remark:
            # Update existing
            remark.remark_text = item.remark.value
            remark.teacher_id = staff_user.id
            remark.updated_at = datetime.utcnow()
        else:
            # Create new
            remark = FormTeacherRemark(
                student_id=item.student_id,
                class_id=bulk_data.class_id,
                session_id=bulk_data.session_id,
                term_id=bulk_data.term_id,
                teacher_id=staff_user.id,
                remark_text=item.remark.value
            )
        
        db.add(remark)
        processed_count += 1

    await db.commit()
    return processed_count