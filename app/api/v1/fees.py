# app/api/v1/fees.py
"""New, refactored API routes for Fee and Fee Assignment management."""
from fastapi import APIRouter, Depends, Query, status
from sqlmodel import Session, select
from typing import List, Optional

from app.models import ActivityAction, User,InvoiceStatus, InvoiceItem, Payment, AcademicSession, Term, Invoice
from app.core.database import get_session
from app.core.auth import get_current_admin
from app.schemas.fee import FeeCreate, FeeUpdate, FeeResponse, FeeAssignmentCreate, InvoiceGenerateRequest, PaginatedInvoiceResponse, InvoiceResponse
from app.services import fee_service, activity_log_service

router = APIRouter(
    prefix="/fees/admin", # PRESERVED: Matches original prefix="/fees" + "/admin"
    tags=["Admin - Fee Management"],
    dependencies=[Depends(get_current_admin)]
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
