
from sqlmodel import select

from fastapi import HTTPException
from sqlmodel import Session
from typing import Tuple
from io import BytesIO
import zipfile
import re
from collections import defaultdict, Counter

# Use correct import paths for the new structure
from app.services.pdf.generator import SchoolReportGenerator
from app.utils.grade_calculator import calculate_detailed_grade, _get_rank_suffix
from app.services import result_service
from app.models import (Class, Enrollment, UserRole, User, StudentProfile, AcademicSession,
                         Term, Result, TermName, FormTeacherRemark, Subject)


class ReportCardService:
    def __init__(self):
        self.generator = SchoolReportGenerator()

    def generate_detailed_student_report(self, student_id: str, session_id: str, term_id: str, db_session: Session) -> Tuple[bytes, str]:
        try:
            # 1. Get all necessary data from the result_service
            report_data = result_service.get_data_for_detailed_report(
                student_id, session_id, term_id, db_session
            )
            
            # 2. Pass the prepared data to the generator
            pdf_buffer = self.generator.generate_detailed_report_card(
                student_data=report_data["student_data"],
                results_data=report_data["results_data"],
                session_info=report_data["session_info"],
                summary_data=report_data["summary_data"],
                form_teacher_remark=report_data["form_teacher_remark"],
                class_obj=report_data["class_obj"]
            )
            
            filename = f"Report_Card_{report_data['student_data']['admission_number']}.pdf"
            return pdf_buffer.getvalue(), filename
        except HTTPException as he:
            raise he # Re-raise known errors
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")
        
    def generate_cumulative_report(self, student_id: str, session_id: str, user_role: UserRole, db_session: Session) -> Tuple[bytes, str]:
        """
        Orchestrates generating a student's final cumulative report for a session.
        """
        try:
            # 1. Get all necessary data from the result_service in a structured dictionary.
            report_data = result_service.get_data_for_cumulative_report(
                student_id, session_id, user_role, db_session
            )

            # 2. Pass the prepared data to the generator using explicit keyword arguments.
            #    This makes the code readable and ensures the correct data goes to the correct place.
            pdf_buffer = self.generator.generate_final_cumulative_report_card(
                student_data=report_data["student_data"],
                session_info=report_data["session_info"],
                results_data=report_data["results_data"],
                overall_average=report_data["overall_average"],
                form_teacher_remark=report_data["form_teacher_remark"],
                principal_remark=report_data["principal_remark"],
                principal_info=report_data["principal_info"],
                grades_summary=report_data["grades_summary"],
                class_obj=report_data["class_obj"]
            )
            
            # 3. Create a dynamic filename based on the fetched data.
            student_data = report_data["student_data"]
            session_info = report_data["session_info"]
            filename = f"Cumulative_Report_{student_data['admission_number']}_{session_info['session_name'].replace('/', '_')}.pdf"
            
            return pdf_buffer.getvalue(), filename
            
        except HTTPException as he:
            # Re-raise known application errors (like 404s or 403s from the service)
            raise he
        except Exception as e:
            # Catch any unexpected errors during PDF generation
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"An unexpected server error occurred during cumulative report generation: {e}")

    def get_data_for_cumulative_report(student_id: str, session_id: str, user_role: UserRole, db: Session) -> dict:
        """
        Fetches and processes all data required to generate a cumulative (final session) report card.
        """
        student = db.get(User, student_id)
        if not student: raise HTTPException(status_code=404, detail="Student not found")
        
        student_profile = db.exec(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
        academic_session = db.get(AcademicSession, session_id)
        if not academic_session: raise HTTPException(status_code=404, detail="Session not found")

        terms_in_session = db.exec(select(Term).where(Term.session_id == session_id)).all()
        term_map = {term.name: term for term in terms_in_session}
        if not all(t in term_map for t in [TermName.first, TermName.second, TermName.third]):
            raise HTTPException(status_code=400, detail="All three terms must exist for this session to generate a cumulative report.")

        third_term_obj = term_map[TermName.third]
        
        enrollment = db.exec(select(Enrollment).where(Enrollment.student_id == student_id, Enrollment.session_id == session_id)).first()
        if not enrollment: raise HTTPException(status_code=404, detail="Student enrollment for this session not found.")

        class_obj = db.get(Class, enrollment.class_id)
        
        # Authorization for students
        if user_role == UserRole.student:
            is_published = db.exec(select(Result).where(Result.student_id == student_id, Result.term_id == third_term_obj.id, Result.is_published == True)).first()
            if not is_published:
                raise HTTPException(status_code=403, detail="Cumulative report is not available until Third Term results are published.")

        # Fetch results for the student for the entire session
        student_session_results = db.exec(select(Result).where(Result.student_id == student_id, Result.session_id == session_id)).all()
        
        # Fetch all third-term results for the whole class to calculate ranks
        all_class_third_term_results = db.exec(select(Result).where(Result.class_id == class_obj.id, Result.term_id == third_term_obj.id)).all()

        # --- Rank Calculation Logic (preserved from original) ---
        results_by_subject = defaultdict(list)
        for res in all_class_third_term_results:
            if res.total is not None:
                results_by_subject[res.subject_id].append({'student_id': res.student_id, 'total': res.total})
        
        subject_averages = {sub_id: sum(s['total'] for s in scores) / len(scores) for sub_id, scores in results_by_subject.items() if scores}
        subject_ranks = defaultdict(dict)
        for sub_id, scores in results_by_subject.items():
            sorted_scores = sorted(scores, key=lambda x: x['total'], reverse=True)
            for rank, score_data in enumerate(sorted_scores, 1):
                subject_ranks[sub_id][score_data['student_id']] = f"{rank}{_get_rank_suffix(rank)}"

        # --- Data Aggregation Logic (preserved from original) ---
        subjects_data = {}
        term_id_to_name_map = {term.id: term.name for term in terms_in_session}
        for res in student_session_results:
            if res.subject_id not in subjects_data:
                subject_obj = db.get(Subject, res.subject_id)
                subjects_data[res.subject_id] = {
                    "subject_name": subject_obj.name, TermName.first: 0.0, TermName.second: 0.0, TermName.third: 0.0,
                    'ca1': '-', 'ca2': '-', 'exam': '-', 'total': '-'
                }
            
            term_name = term_id_to_name_map.get(res.term_id)
            if term_name and res.total is not None:
                subjects_data[res.subject_id][term_name] = res.total
            
            if res.term_id == third_term_obj.id:
                subjects_data[res.subject_id].update({
                    'ca1': res.ca1, 'ca2': res.ca2, 'exam': res.exam, 'total': res.total
                })

        # --- Final Cumulative Calculation Logic (preserved from original) ---
        final_cumulative_results = []
        total_of_cumulative_scores = 0.0
        for subject_id, subject_info in subjects_data.items():
            cumulative_total = (subject_info[TermName.first] * 0.20) + (subject_info[TermName.second] * 0.30) + (subject_info[TermName.third] * 0.50)
            final_grade, _ = calculate_detailed_grade(cumulative_total)
            total_of_cumulative_scores += cumulative_total
            
            final_cumulative_results.append({
                **subject_info, "cumulative_total": cumulative_total, "final_grade": final_grade,
                "class_average": subject_averages.get(subject_id, 0.0),
                "subject_position": subject_ranks.get(subject_id, {}).get(student_id, 'N/A')
            })

        overall_cumulative_average = total_of_cumulative_scores / len(final_cumulative_results) if final_cumulative_results else 0.0
        
        remark_obj = db.exec(select(FormTeacherRemark).where(FormTeacherRemark.student_id == student_id, FormTeacherRemark.term_id == third_term_obj.id)).first()
        form_teacher_remark = remark_obj.remark_text if remark_obj else "No final remark provided."

        # --- Promotion/Graduation Remark Logic (preserved from original) ---
        principal_remark = "Promoted"
        current_class_name = class_obj.name.upper()
        if "SS3" in current_class_name:
            principal_remark = "Graduated and certified."
        elif "JSS3" in current_class_name:
            principal_remark = "Promoted to SS1"
        else:
            match = re.search(r'\d+', current_class_name)
            if match:
                current_level = int(match.group())
                next_level = current_level + 1
                next_class_name = re.sub(r'\d+', str(next_level), current_class_name.split(' ')[0])
                principal_remark = f"Promoted to {next_class_name}"

        principal_info = {"name": "OMADA DAVID MR.", "title": "DIRECTOR/PRINCIPAL"}
        
        grade_counts = Counter(res['final_grade'] for res in final_cumulative_results if res['final_grade'])
        grades_summary = ", ".join([f"{count}({grade})" for grade, count in sorted(grade_counts.items())])

        # --- Return a structured dictionary for the orchestration service ---
        return {
            "student_data": {
                'student_name': f"{student.first_name} {student.last_name}",
                'admission_number': student_profile.admission_number if student_profile else "N/A",
                'username': student.username, 'gender': student.gender.value,
                'email': student.email, 'phone': student.phone,
                'profile_picture_url': student.profile_picture_url
            },
            "session_info": {'session_name': academic_session.name, 'class_name': class_obj.name},
            "results_data": final_cumulative_results,
            "overall_average": overall_cumulative_average,
            "form_teacher_remark": form_teacher_remark,
            "principal_remark": principal_remark,
            "principal_info": principal_info,
            "grades_summary": grades_summary,
            "class_obj": class_obj
        }

    def generate_bulk_class_reports(self, class_id: str, session_id: str, term_id: str, db_session: Session) -> Tuple[bytes, str]:
        enrollments = db_session.exec(select(Enrollment).where(Enrollment.class_id == class_id, Enrollment.term_id == term_id)).all()
        if not enrollments:
            raise HTTPException(status_code=404, detail="No students found in this class for the specified term.")
        
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for enrollment in enrollments:
                try:
                    # Reuse our single-student generation logic for each student
                    pdf_content, pdf_filename = self.generate_detailed_student_report(
                        student_id=enrollment.student_id,
                        session_id=session_id,
                        term_id=term_id,
                        db_session=db_session
                    )
                    zip_file.writestr(pdf_filename, pdf_content)
                except Exception as e:
                    print(f"Skipping PDF for student {enrollment.student_id} due to error: {str(e)}")
        
        zip_buffer.seek(0)
        class_obj = db_session.get(Class, class_id)
        zip_filename = f"Report_Cards_{class_obj.name.replace(' ', '_')}.zip"
        return zip_buffer.getvalue(), zip_filename

# Create a single instance to be used by the application
report_card_service = ReportCardService()