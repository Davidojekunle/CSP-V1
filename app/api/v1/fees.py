# app/api/v1/fees.py
"""New, refactored API routes for Fee and Fee Assignment management."""
from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List, Optional, Dict

from app.models import ActivityAction, User, InvoiceStatus, Invoice, TargetType, UserRole, PaymentStatus, InvoiceGenerationScope
from app.core.database import get_session
from app.core.auth import get_current_admin, get_current_active_user, get_current_student
from app.schemas.payment import PaymentResponse, PaymentHistoryResponse
from app.schemas.fee import FeeCreate, FeeUpdate, FeeResponse, FeeAssignmentCreate, InvoiceGenerateRequest, PaginatedInvoiceResponse, InvoiceResponse
from app.services import fee_service, activity_log_service, payment_service
from app.schemas.dashboard import FeeDashboardStats # We will create this schema
from datetime import date

from anyio.to_thread import run_sync
from fastapi import Response
from fastapi.responses import StreamingResponse
from app.services.pdf.invoice import invoice_pdf_service
from app.services.pdf import invoice_report

router = APIRouter(
    prefix="/fees/admin", # PRESERVED: Matches original prefix="/fees" + "/admin"
    tags=["Admin - Fee Management"],
    dependencies=[Depends(get_current_admin)]
)

student_router = APIRouter(
    prefix="/fees/student",
    tags=["Student - Fee Management"]
)

# --- Fee Management ---
@router.post("/fees", response_model=FeeResponse, status_code=status.HTTP_201_CREATED)
async def create_fee(fee_data: FeeCreate, db: AsyncSession = Depends(get_session)):
    new_fee = await fee_service.create_fee(fee_data, db)
    return new_fee

@router.get("/fees", response_model=List[FeeResponse])
async def get_all_fees(is_active: Optional[bool] = Query(None), db: AsyncSession = Depends(get_session)):
    fees = await fee_service.get_all_fees(db, is_active)
    return fees

@router.put("/fees/{fee_id}", response_model=FeeResponse)
async def update_fee(fee_id: str, fee_data: FeeUpdate, db: AsyncSession = Depends(get_session)):
    updated_fee = await fee_service.update_fee(fee_id, fee_data, db)
    return updated_fee

# --- Fee Assignment ---
@router.post("/fee-assignments", status_code=status.HTTP_201_CREATED)
async def create_fee_assignment(assign_data: FeeAssignmentCreate, db: AsyncSession = Depends(get_session)):
    await fee_service.create_fee_assignment(assign_data, db)
    return {"message": "Fee assignment created successfully"}

@router.delete("/fee-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fee_assignment(assignment_id: str, db: AsyncSession = Depends(get_session)):
    await fee_service.delete_fee_assignment(assignment_id, db)
    return


@router.get("/invoice-generation/preview")
async def preview_invoice_generation(
    session_id: str = Query(...), term_id: str = Query(...), due_date: str = Query(...),
    scope: InvoiceGenerationScope = Query(InvoiceGenerationScope.school),
    target_ids: Optional[str] = Query(None, description="Comma-separated class or student ids"),
    db: AsyncSession = Depends(get_session)
):
    """Dry run of /generate-invoices: how many invoices would be created and for how much."""
    ids = [t for t in (target_ids or "").split(",") if t]
    return await fee_service.preview_invoice_generation(
        {"session_id": session_id, "term_id": term_id, "due_date": due_date, "scope": scope.value, "target_ids": ids}, db
    )


@router.get("/invoice-report")
async def download_invoice_report(
    payment_status: str = Query("all"), file_type: str = Query("excel"),
    db: AsyncSession = Depends(get_session)
):
    """Invoice report as Excel (file_type=excel) or PDF (file_type=pdf)."""
    rows = await fee_service.get_invoice_report_rows(payment_status, db)
    stamp = date.today().isoformat()
    if file_type == "pdf":
        content = await run_sync(invoice_report.render_pdf, rows, f"Invoice Report ({payment_status})")
        media, filename = "application/pdf", f"invoice_report_{stamp}.pdf"
    elif file_type == "excel":
        content = await run_sync(invoice_report.render_xlsx, rows)
        media, filename = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"invoice_report_{stamp}.xlsx"
    else:
        raise HTTPException(status_code=400, detail="file_type must be 'excel' or 'pdf'")
    return Response(content=content, media_type=media, headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.post("/generate-invoices")
async def generate_invoices(
    request_data: InvoiceGenerateRequest,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    counts = await fee_service.generate_invoices_for_term(request_data.model_dump(), db)
    
    created = counts['created']
    updated = counts['updated']

    if created > 0 or updated > 0:
        await activity_log_service.log_activity(
            session=db, actor=current_admin,
            action=ActivityAction.INVOICES_GENERATED,
            details=f"Generated {created} new invoices and updated {updated} existing invoices."
        )
        await db.commit()

    return {"message": f"Process complete. Created: {created}, Updated: {updated}."}


async def _build_invoice_response(invoice: Invoice, db: AsyncSession) -> dict:
    """Builds the detailed InvoiceResponse payload for one invoice."""
    return (await fee_service._build_invoice_responses_bulk([invoice], db))[0]

# ... (keep existing router and endpoints)

# --- ADD NEW INVOICE MANAGEMENT ENDPOINTS ---

# PRESERVED: GET /fees/admin/invoices
@router.get("/invoices", response_model=PaginatedInvoiceResponse)
async def get_all_invoices(
    skip: int = Query(0, ge=0), limit: int = Query(15, ge=1, le=500),
    status: Optional[InvoiceStatus] = Query(None),
    session_id: Optional[str] = Query(None),
    term_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_session)
):
    invoices, total_count = await fee_service.get_all_invoices(
        db, skip, limit, status, session_id, term_id, search
    )
    
    # All related rows are fetched in bulk (fixed number of queries per page)
    invoice_responses = await fee_service._build_invoice_responses_bulk(invoices, db)
    
    return PaginatedInvoiceResponse(
        total=total_count,
        invoices=invoice_responses,
        has_more=(skip + len(invoices)) < total_count
    )

# PRESERVED: POST /fees/admin/cancel-invoice/{id}
@router.post("/cancel-invoice/{invoice_id}")
async def cancel_invoice(invoice_id: str, db: AsyncSession = Depends(get_session)):
    await fee_service.cancel_invoice(invoice_id, db)
    return {"message": "Invoice cancelled successfully"}


@router.get("/dashboard-stats", response_model=FeeDashboardStats)
async def get_dashboard_stats(
    session_id: Optional[str] = Query(None),
    term_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_session)
):
    # We will create this service function next
    stats = await fee_service.get_dashboard_stats(db, session_id, term_id)
    return stats

# PRESERVED: GET /fees/admin/invoice/{id}/pdf
@router.get("/invoice/{invoice_id}/pdf")
async def admin_download_invoice_pdf(
    invoice_id: str,
    db: AsyncSession = Depends(get_session)
):
    pdf_buffer = await invoice_pdf_service.generate_invoice_pdf(invoice_id, db)
    filename = f"invoice_{invoice_id}.pdf"
    return StreamingResponse(
        pdf_buffer, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/fee-assignments/by-target", response_model=Dict)
async def get_fee_assignments_by_target(
    session_id: str = Query(...),
    term_id: str = Query(...),
    target_type: Optional[TargetType] = Query(None),
    db: AsyncSession = Depends(get_session)
):
    """Get fee assignments grouped by their target type for a specific term."""
    grouped_assignments = await fee_service.get_fee_assignments_by_target(
        session_id, term_id, target_type, db
    )
    return grouped_assignments

@router.get("/payments", response_model=List[PaymentResponse])
async def get_all_payments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[PaymentStatus] = Query(None),
    search: Optional[str] = Query(None),
    payment_method: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_session)
):
    """Get all payments with comprehensive filtering (Admin only)."""
    payments = await payment_service.get_all_payments(
        db, skip, limit, status, search, payment_method, date_from, date_to
    )
    invoices = {}
    students = {}
    if payments:
        invoices = {i.id: i for i in (await db.execute(
            select(Invoice).where(Invoice.id.in_({p.invoice_id for p in payments}))
        )).scalars().all()}
        students = {u.id: u for u in (await db.execute(
            select(User).where(User.id.in_({i.student_id for i in invoices.values()}))
        )).scalars().all()}

    response_list = []
    for payment in payments:
        invoice = invoices[payment.invoice_id]
        student = students.get(invoice.student_id)
        response_list.append(PaymentResponse(
            id=payment.id,
            reference=payment.paystack_reference,
            invoice_number=invoice.invoice_number,
            student_name=f"{student.first_name} {student.last_name}" if student else "N/A",
            amount=payment.amount,
            status=payment.status,
            payment_method=payment.payment_method.value if payment.payment_method else None,
            paid_at=payment.paid_at,
            created_at=payment.created_at,
            invoice_id=payment.invoice_id,
            student_id=invoice.student_id
        ))
    return response_list


@student_router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_student_invoice_details(
    invoice_id: str,
    # --- FIX 1: Expect a dictionary, as the original dependency provides ---
    current_user_data: Dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session)
):
    """
    Get specific invoice details. Accessible by the student owner or any admin.
    """
    # --- FIX 2: Unpack the dictionary exactly like the original code ---
    user = current_user_data["user"]
    user_role = current_user_data["user_type"]

    invoice = await db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Authorization check using the unpacked variables
    is_admin = (user_role == UserRole.admin)
    is_owner = (user_role == UserRole.student and invoice.student_id == user.id)

    if not (is_admin or is_owner):
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Use the helper we already defined in this file to build the response
    return await _build_invoice_response(invoice, db)


@student_router.get("/invoice/{invoice_id}/pdf")
async def download_my_invoice_pdf(
    invoice_id: str,
    current_user_data: Dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session)
):
    """Invoice/receipt PDF for the student who owns it (or any admin)."""
    user, role = current_user_data["user"], current_user_data["user_type"]
    invoice = await db.get(Invoice, invoice_id)
    if not invoice or not (role == UserRole.admin or (role == UserRole.student and invoice.student_id == user.id)):
        raise HTTPException(status_code=404, detail="Invoice not found")
    pdf_buffer = await invoice_pdf_service.generate_invoice_pdf(invoice_id, db)
    return StreamingResponse(
        pdf_buffer, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=invoice_{invoice.invoice_number}.pdf"}
    )


neutral_fee_router = APIRouter(prefix="/fees", tags=["Fee Management"])

@student_router.get("/payment-history", response_model=List[PaymentHistoryResponse])
async def get_my_payment_history(
    current_user: User = Depends(get_current_student), # Use the student-specific dependency
    db: AsyncSession = Depends(get_session)
):
    """Get a list of all successful payments made by the logged-in student."""
    history = await payment_service.get_student_payment_history(student_user=current_user, db=db)
    return history



@neutral_fee_router.get("/invoices/by-student", response_model=List[InvoiceResponse])
async def get_student_invoices(
    student_id: Optional[str] = Query(None),
    status: Optional[InvoiceStatus] = Query(None),
    current_user_data: dict = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_session)
):
    """
    PRESERVED: GET /fees/invoices/by-student
    Logic handles both student and admin roles.
    """
    user = current_user_data["user"]
    user_role = current_user_data["user_type"]
    
    target_student_id = user.id if user_role == UserRole.student else student_id

    if user_role == UserRole.admin and not target_student_id:
         raise HTTPException(status_code=400, detail="Admin must provide student_id")

    return await fee_service.get_invoices_for_student(target_student_id, status, db)
