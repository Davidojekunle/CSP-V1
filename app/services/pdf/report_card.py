import logging
import zipfile
from io import BytesIO
from typing import Tuple

from anyio.to_thread import run_sync
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.services.pdf.generator import SchoolReportGenerator
from app.services import result_service
from app.models import Class, Enrollment, UserRole

logger = logging.getLogger(__name__)


class ReportCardService:
    """
    Report card orchestration. Data is loaded on the event loop; PDF rendering
    (CPU-bound, and it downloads student photos) runs in a worker thread so it
    doesn't block other requests.
    """

    def __init__(self):
        self.generator = SchoolReportGenerator()

    def _render_detailed(self, report_data: dict) -> Tuple[bytes, str]:
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

    async def generate_detailed_student_report(self, student_id: str, session_id: str, term_id: str, db_session: AsyncSession) -> Tuple[bytes, str]:
        try:
            report_data = await result_service.get_data_for_detailed_report(
                student_id, session_id, term_id, db_session
            )
            return await run_sync(self._render_detailed, report_data)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Detailed report card generation failed")
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")

    async def generate_cumulative_report(self, student_id: str, session_id: str, user_role: UserRole, db_session: AsyncSession) -> Tuple[bytes, str]:
        """
        Orchestrates generating a student's final cumulative report for a session.
        """
        try:
            report_data = await result_service.get_data_for_cumulative_report(
                student_id, session_id, user_role, db_session
            )

            def render():
                return self.generator.generate_final_cumulative_report_card(
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

            pdf_buffer = await run_sync(render)
            student_data = report_data["student_data"]
            session_info = report_data["session_info"]
            filename = f"Cumulative_Report_{student_data['admission_number']}_{session_info['session_name'].replace('/', '_')}.pdf"
            return pdf_buffer.getvalue(), filename

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Cumulative report generation failed")
            raise HTTPException(status_code=500, detail=f"An unexpected server error occurred during cumulative report generation: {e}")

    async def generate_bulk_class_reports(self, class_id: str, session_id: str, term_id: str, db_session: AsyncSession) -> Tuple[bytes, str]:
        student_ids = (await db_session.execute(
            select(Enrollment.student_id).where(Enrollment.class_id == class_id, Enrollment.term_id == term_id)
        )).scalars().all()
        if not student_ids:
            raise HTTPException(status_code=404, detail="No students found in this class for the specified term.")

        reports = await result_service.get_data_for_class_reports(list(student_ids), session_id, term_id, db_session)
        class_obj = await db_session.get(Class, class_id)

        def build_zip() -> bytes:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for report_data in reports:
                    try:
                        pdf_content, pdf_filename = self._render_detailed(report_data)
                        zip_file.writestr(pdf_filename, pdf_content)
                    except Exception:
                        logger.exception("Skipping report card for %s", report_data["student_data"].get("admission_number"))
            return zip_buffer.getvalue()

        zip_content = await run_sync(build_zip)
        zip_filename = f"Report_Cards_{class_obj.name.replace(' ', '_')}.zip"
        return zip_content, zip_filename


# Create a single instance to be used by the application
report_card_service = ReportCardService()
