# app/api/v1/bulk_uploads.py
"""
New, refactored API routes for bulk data uploads.
"""
from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.core.database import get_session
from app.core.auth import get_current_admin
from app.models import User
from app.services import bulk_upload_service, activity_log_service
from app.services.email.sender import send_welcome_email 
from app.models import ActivityAction

router = APIRouter(
    prefix="/admin/users/bulk-upload", # PRESERVED: Original prefix structure
    tags=["Admin - Bulk Uploads"],
    dependencies=[Depends(get_current_admin)]
)

@router.post("/students", status_code=status.HTTP_207_MULTI_STATUS)
async def bulk_upload_students(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    """
    Handles bulk upload of students from a CSV or Excel file.
    The heavy processing is offloaded to the bulk_upload_service.
    """
    # 1. Delegate all file processing and user creation to the service
    result = await bulk_upload_service.process_student_upload(file=file, session=session)

    # 2. Add email sending to background tasks
    # This is a key performance optimization. The request doesn't wait for emails to send.
    for task_details in result.get("email_tasks", []):
        background_tasks.add_task(
            send_welcome_email,
            **task_details
        )
    
    # 3. Log the summary of the bulk action
    log_details = f"Bulk uploaded {result['success_count']} students. Failed: {result['failure_count']}."
    await activity_log_service.log_activity(
        session, current_admin, ActivityAction.USER_BULK_UPLOAD, log_details
    )
    await session.commit() # Commit the log entry

    # 4. Return the result to the user
    # We remove email_tasks before sending the response as it's not part of the API contract.
    result.pop("email_tasks", None)
    return result

@router.post("/staff", status_code=status.HTTP_207_MULTI_STATUS)
async def bulk_upload_staff(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    """
    Handles bulk upload of staff and admins from a CSV or Excel file.
    The heavy processing is offloaded to the bulk_upload_service.
    """
    # 1. Delegate all processing to the service
    result = await bulk_upload_service.process_staff_upload(file=file, session=session)

    # 2. Add email sending to background tasks
    for task_details in result.get("email_tasks", []):
        background_tasks.add_task(
            send_welcome_email,
            **task_details
        )
    
    # 3. Log the summary of the bulk action
    log_details = f"Bulk uploaded {result['success_count']} staff/admins. Failed: {result['failure_count']}."
    await activity_log_service.log_activity(
        session, current_admin, ActivityAction.USER_BULK_UPLOAD, log_details
    )
    await session.commit()

    # 4. Return the result to the user
    result.pop("email_tasks", None)
    return result