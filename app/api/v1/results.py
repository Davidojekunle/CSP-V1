from fastapi import APIRouter, Depends, Query, status, HTTPException, BackgroundTasks, Response
from sqlmodel import Session, select, and_
from typing import List, Dict, Optional

from app.core.database import get_session
from app.core.auth import get_current_admin, get_current_staff_or_admin, get_current_active_user
from app.models import User, UserRole, Result, AcademicSession, Term
from app.schemas.result import (BulkResultCreate, ResultResponse, BulkResultItem, ClassResultSummary,
ResultsDashboardStats, ResultsEntryProgressResponse, PublicationReadinessResponse)

from app.services import result_service
from app.services.pdf.report_card import report_card_service

router = APIRouter(
    prefix="/results",
    tags=["Results Management"],
    dependencies=[Depends(get_current_staff_or_admin)]
)


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_create_or_update_results(
    bulk_data: BulkResultCreate,
    db: Session = Depends(get_session)
):
    counts = result_service.bulk_upsert_results(bulk_data, db)
    return {
        "message": f"Processed {len(bulk_data.results)} results: {counts['created']} created, {counts['updated']} updated.",
        "created": counts['created'],
        "updated": counts['updated'],
        "errors": [] 
    }


@router.delete("/{result_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(get_current_admin)])
async def delete_result(result_id: str, db: Session = Depends(get_session)):
    result_service.delete_result(result_id, db)
    return {"message": "Result deleted successfully"}

@router.get("/", response_model=List[ResultResponse])
async def get_results(
    session_id: Optional[str] = Query(None),
    term_id: Optional[str] = Query(None),
    class_id: Optional[str] = Query(None),
    subject_id: Optional[str] = Query(None),
    student_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user = Depends(get_current_active_user),
    session: Session = Depends(get_session),
    db: Session = Depends(get_session)
):
    """Get results with filtering and pagination"""
    
    results_data = result_service.get_filtered_results(
        db, user=current_user['user'], session_id=session_id, term_id=term_id, class_id=class_id,
        subject_id=subject_id, student_id=student_id, skip=skip, limit=limit
    )
    return results_data

@router.get("/class/{class_id}/report", response_model=ClassResultSummary)
async def get_class_performance_report(
    class_id: str, session_id: str = Query(...), term_id: str = Query(...),
    subject_id: Optional[str] = Query(None),
    # Authorization logic would go here in the dependency
    db: Session = Depends(get_session)
):
    report_data = result_service.get_class_performance_report(
        db, class_id, session_id, term_id, subject_id
    )
    return report_data

@router.put(
    "/results/publish",
    summary="Publish Results",
    description="Publish results for a term/session (admin only)."
)
async def publish_results(
    background_tasks : BackgroundTasks,
    session_id: str = Query(..., description="Academic session ID"),
    term_id: str = Query(..., description="Term ID"),
    class_id: Optional[str] = Query(None, description="Filter by class"),
    student_id: Optional[str] = Query(None, description="Filter by student"),
    current_admin=Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    query = select(Result).where(
        Result.session_id == session_id,
        Result.term_id == term_id
    )

    if class_id:
        query = query.where(Result.class_id == class_id)
    if student_id:
        query = query.where(Result.student_id == student_id)

    results = session.exec(query).all()

    if not results:
        raise HTTPException(status_code=404, detail="No results found to publish")

    first_result = results[0]
    if first_result.is_published:
        raise HTTPException(status_code=400, detail="Results are already published")
    
    for result in results:
        result.is_published = True
        session.add(result)

    session.commit()

    
    return {"message": f"Published {len(results)} results successfully"}

# PRESERVED: PUT /results/unpublish
@router.put("/unpublish")
async def unpublish_results(
    session_id: str = Query(...), term_id: str = Query(...),
    db: Session = Depends(get_session)
):
    count = result_service.publish_or_unpublish_results(db, session_id, term_id, publish=False)
    return {"message": f"Unpublished {count} results successfully"}

@router.get("/student/report-card/download", summary="Download Single Term Report Card")
async def download_student_report_card(
    session_id: str = Query(...), term_id: str = Query(...),
    student_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_active_user),
    db_session: Session = Depends(get_session)
):
    user = current_user['user']
    target_student_id = user.id if user.role == UserRole.student else student_id
    if not target_student_id:
        raise HTTPException(status_code=400, detail="Student ID is required.")

    # Call the new, refactored service method
    pdf_content, filename = report_card_service.generate_detailed_student_report(
        student_id=target_student_id,
        session_id=session_id,
        term_id=term_id,
        db_session=db_session
    )
    
    return Response(content=pdf_content, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})
    
@router.get("/student/cumulative-report/download", summary="Download Cumulative Report Card")
async def download_cumulative_report_card(
    session_id: str = Query(...), term_id: str = Query(...),
    student_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_active_user),
    db_session: Session = Depends(get_session)
):
    user = current_user['user']
    target_student_id = user.id if user.role == UserRole.student else student_id
    if not target_student_id:
        raise HTTPException(status_code=400, detail="Student ID is required.")

    pdf_content, filename = report_card_service.generate_cumulative_report(
        student_id=target_student_id, session_id=session_id,
        user_role=user.role, db_session=db_session
    )
    return Response(content=pdf_content, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/class/{class_id}/report-cards/download", summary="Download All Report Cards for a Class", dependencies=[Depends(get_current_admin)])
async def download_bulk_class_report_cards(
    class_id: str, session_id: str = Query(...), term_id: str = Query(...),
    db_session: Session = Depends(get_session)
):
    zip_content, filename = report_card_service.generate_bulk_class_reports(
        class_id=class_id, session_id=session_id, term_id=term_id, db_session=db_session
    )
    return Response(content=zip_content, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={filename}"})

@router.get("/admin/dashboard-stats", response_model=ResultsDashboardStats, dependencies=[Depends(get_current_admin)])
async def get_results_dashboard_stats(
    session_id: str = Query(...),
    term_id: str = Query(...),
    db: Session = Depends(get_session)
):
    """Provides aggregated statistics for the main Results Management dashboard."""
    stats = result_service.get_admin_dashboard_stats(session_id, term_id, db)
    return stats

@router.get("/admin/results-entry-progress", response_model=ResultsEntryProgressResponse, dependencies=[Depends(get_current_admin)])
async def get_results_entry_progress(
    session_id: str = Query(...),
    term_id: str = Query(...),
    db: Session = Depends(get_session)
):
    """
    Provides a detailed breakdown of results entry progress per class-subject.
    """
    progress_items = result_service.get_results_entry_progress(session_id, term_id, db)
    # The schema expects a root key "items"
    return {"items": progress_items}

@router.get("/admin/publication-readiness-check", response_model=PublicationReadinessResponse, dependencies=[Depends(get_current_admin)])
async def get_publication_readiness(
    session_id: str = Query(...),
    term_id: str = Query(...),
    class_id: Optional[str] = Query(None),
    db: Session = Depends(get_session)
):
    """Checks for completeness of results entry before publishing."""
    readiness_data = result_service.check_publication_readiness(session_id, term_id, class_id, db)
    return readiness_data