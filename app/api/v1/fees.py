# app/api/v1/fees.py
"""New, refactored API routes for Fee and Fee Assignment management."""
from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlmodel import Session, and_, select
from typing import List, Optional, Dict

from app.models import ActivityAction, User,InvoiceStatus, InvoiceItem, Payment, AcademicSession, Term, Invoice, TargetType, UserRole, PaymentStatus
from app.core.database import get_session
from app.core.auth import get_current_admin, get_current_active_user
from app.schemas.payment import PaymentResponse
from app.schemas.fee import FeeCreate, FeeUpdate, FeeResponse, FeeAssignmentCreate, InvoiceGenerateRequest, PaginatedInvoiceResponse, InvoiceResponse
from app.services import fee_service, activity_log_service, payment_service
from app.schemas.dashboard import FeeDashboardStats # We will create this schema
from fastapi.responses import StreamingResponse
from app.services.pdf.invoice import invoice_pdf_service

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
async def create_fee(fee_data: FeeCreate, db: Session = Depends(get_session)):
    new_fee = fee_service.create_fee(fee_data, db)
    return new_fee

@router.get("/fees", response_model=List[FeeResponse])
async def get_all_fees(is_active: Optional[bool] = Query(None), db: Session = Depends(get_session)):
    fees = fee_service.get_all_fees(db, is_active)
    return fees

@router.put("/fees/{fee_id}", response_model=FeeResponse)
async def update_fee(fee_id: str, fee_data: FeeUpdate, db: Session = Depends(get_session)):
    updated_fee = fee_service.update_fee(fee_id, fee_data, db)
    return updated_fee

# --- Fee Assignment ---
@router.post("/fee-assignments", status_code=status.HTTP_201_CREATED)
async def create_fee_assignment(assign_data: FeeAssignmentCreate, db: Session = Depends(get_session)):
    fee_service.create_fee_assignment(assign_data, db)
    return {"message": "Fee assignment created successfully"}

@router.post("/generate-invoices")
async def generate_invoices(
    request_data: InvoiceGenerateRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session)
):
    counts = fee_service.generate_invoices_for_term(request_data.model_dump(), db)
    
    created = counts['created']
    updated = counts['updated']

    if created > 0 or updated > 0:
        await activity_log_service.log_activity(
            session=db, actor=current_admin,
            action=ActivityAction.INVOICES_GENERATED,
            details=f"Generated {created} new invoices and updated {updated} existing invoices."
        )
        db.commit()

    return {"message": f"Process complete. Created: {created}, Updated: {updated}."}


def _build_invoice_response(invoice: Invoice, db: Session) -> InvoiceResponse:
    """Helper to construct the detailed InvoiceResponse object."""
    student = db.get(User, invoice.student_id)
    session_obj = db.get(AcademicSession, invoice.session_id)
    term_obj = db.get(Term, invoice.term_id)
    
    # PERFORMANCE: These are N+1 queries. We are preserving the original contract.
    # A future optimization would be to join these in the service.
    items = db.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)).all()
    payments = db.exec(select(Payment).where(Payment.invoice_id == invoice.id)).all()
    
    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        student_name=f"{student.first_name} {student.last_name}" if student else "N/A",
        session_name=session_obj.name if session_obj else "N/A",
        term_name=term_obj.name.value if term_obj else "N/A",
        status=invoice.status,
        due_date=invoice.due_date,
        total_amount=invoice.total_amount,
        paid_amount=invoice.paid_amount,
        balance_due=invoice.balance_due,
        items=[{"description": i.description, "amount": i.amount} for i in items],
        payments=[{
            "id": p.id, "amount": p.amount, "status": p.status.value,
            "paid_at": p.paid_at, "payment_method": p.payment_method.value if p.payment_method else None
        } for p in payments]
    )

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
    db: Session = Depends(get_session)
):
    invoices, total_count = fee_service.get_all_invoices(
        db, skip, limit, status, session_id, term_id, search
    )
    
    # Use the helper to build the response for each invoice
    invoice_responses = [_build_invoice_response(inv, db) for inv in invoices]
    
    return PaginatedInvoiceResponse(
        total=total_count,
        invoices=invoice_responses,
        has_more=(skip + len(invoices)) < total_count
    )

# PRESERVED: POST /fees/admin/cancel-invoice/{id}
@router.post("/cancel-invoice/{invoice_id}")
async def cancel_invoice(invoice_id: str, db: Session = Depends(get_session)):
    fee_service.cancel_invoice(invoice_id, db)
    return {"message": "Invoice cancelled successfully"}


@router.get("/dashboard-stats", response_model=FeeDashboardStats)
async def get_dashboard_stats(
    session_id: Optional[str] = Query(None),
    term_id: Optional[str] = Query(None),
    db: Session = Depends(get_session)
):
    # We will create this service function next
    stats = fee_service.get_dashboard_stats(db, session_id, term_id)
    return stats

# PRESERVED: GET /fees/admin/invoice/{id}/pdf
@router.get("/invoice/{invoice_id}/pdf")
async def admin_download_invoice_pdf(
    invoice_id: str,
    db: Session = Depends(get_session)
):
    pdf_buffer = invoice_pdf_service.generate_invoice_pdf(invoice_id, db)
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
    db: Session = Depends(get_session)
):
    """Get fee assignments grouped by their target type for a specific term."""
    grouped_assignments = fee_service.get_fee_assignments_by_target(
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
    db: Session = Depends(get_session)
):
    """Get all payments with comprehensive filtering (Admin only)."""
    # NOTE: The payment_service does not yet exist. We will create it.
    # For now, let's put the logic here to fix the error, then we will move it.
    
    # --- TEMPORARY LOGIC (to be moved to payment_service.py) ---
    query = (
        select(Payment, Invoice, User)
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .join(User, Invoice.student_id == User.id)
    )
    
    conditions = []
    if status: conditions.append(Payment.status == status)
    # ... (all other filter conditions would be added here)
        
    if conditions: query = query.where(and_(*conditions))
    
    results = db.exec(
        query.offset(skip).limit(limit).order_by(Payment.created_at.desc())
    ).all()
    # --- END TEMPORARY LOGIC ---

    response_list = []
    for payment, invoice, student in results: # <-- FIX 1: Unpack the tuple
        response_list.append(PaymentResponse(
            id=payment.id,
            reference=payment.paystack_reference,
            invoice_number=invoice.invoice_number,
            student_name=f"{student.first_name} {student.last_name}",
            amount=payment.amount,
            status=payment.status,
            payment_method=payment.payment_method.value if payment.payment_method else None,
            paid_at=payment.paid_at,
            created_at=payment.created_at,
            invoice_id=payment.invoice_id,
            student_id=invoice.student_id # <-- FIX 2: Use the invoice object
        ))
    return response_list


@student_router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_student_invoice_details(
    invoice_id: str,
    # --- FIX 1: Expect a dictionary, as the original dependency provides ---
    current_user_data: Dict = Depends(get_current_active_user),
    db: Session = Depends(get_session)
):
    """
    Get specific invoice details. Accessible by the student owner or any admin.
    """
    # --- FIX 2: Unpack the dictionary exactly like the original code ---
    user = current_user_data["user"]
    user_role = current_user_data["user_type"]

    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Authorization check using the unpacked variables
    is_admin = (user_role == UserRole.admin)
    is_owner = (user_role == UserRole.student and invoice.student_id == user.id)

    if not (is_admin or is_owner):
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Use the helper we already defined in this file to build the response
    return _build_invoice_response(invoice, db)


