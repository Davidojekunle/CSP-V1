# app/api/v1/invoices.py
"""
Invoice Management Routes.
PRESERVED: All endpoints maintain exact paths, methods, and response structures.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select, and_, or_, func
from typing import List, Optional
from datetime import datetime, date, timedelta
from io import BytesIO
import pandas as pd
import zipfile
from tempfile import NamedTemporaryFile
import os

from app.core.database import get_session
from app.core.auth import get_current_admin, get_current_student, get_current_active_user
from app.models import (
    Invoice, InvoiceItem, Payment, Fee, FeeAssignment, User, StudentProfile,
    Class, AcademicSession, Term, Enrollment, ActivityAction,
    InvoiceStatus, PaymentStatus, TargetType, UserRole
)
from app.schemas.fee import (
    InvoiceGenerateRequest, InvoiceResponse, PaginatedInvoiceResponse,
    InvoiceGenerationScope
)
from app.services.pdf.invoice import InvoicePDFGenerator
from app.services.email.sender import email_service

# Import activity logging (assuming you have this)
try:
    from app.services.activity_log_service import log_activity
except ImportError:
    # Fallback if not yet migrated
    async def log_activity(session, actor, action, details):
        print(f"Activity: {action} by {actor.email}: {details}")

router = APIRouter(prefix="/fees", tags=["Invoice Management"])


# ============================================
# HELPER FUNCTIONS
# ============================================

def generate_invoice_number() -> str:
    """Generate unique invoice number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    import uuid
    return f"INV{timestamp}{str(uuid.uuid4())[:8].upper()}"


def parse_date(date_string: str) -> date:
    """Parse date string to date object"""
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid date format. Use YYYY-MM-DD"
        )


def update_overdue_invoices(session: Session):
    """
    Finds and updates the status of overdue invoices.
    PRESERVED: Exact same automation logic.
    """
    today = date.today()
    
    invoices_to_update = session.exec(
        select(Invoice).where(
            and_(
                Invoice.due_date < today,
                Invoice.balance_due > 0,
                Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.partial])
            )
        )
    ).all()

    if invoices_to_update:
        for invoice in invoices_to_update:
            invoice.status = InvoiceStatus.overdue
            invoice.updated_at = datetime.utcnow()
        session.commit()
        print(f"AUTOMATION: Updated {len(invoices_to_update)} invoice(s) to OVERDUE status.")


async def get_invoice_pdf_bytes(invoice_id: str, session: Session) -> bytes:
    """Helper function to generate invoice PDF as bytes for email attachments."""
    invoice = session.get(Invoice, invoice_id)
    if not invoice:
        return None

    # Fetch all related data
    student = session.get(User, invoice.student_id)
    student_profile = session.exec(
        select(StudentProfile).where(StudentProfile.user_id == invoice.student_id)
    ).first()
    session_obj = session.get(AcademicSession, invoice.session_id)
    term_obj = session.get(Term, invoice.term_id)
    
    enrollment = session.exec(
        select(Enrollment).where(
            and_(
                Enrollment.student_id == invoice.student_id,
                Enrollment.session_id == invoice.session_id,
                Enrollment.term_id == invoice.term_id
            )
        )
    ).first()
    
    class_obj = session.get(Class, enrollment.class_id) if enrollment else None
    items = session.exec(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)).all()
    payments = session.exec(
        select(Payment).where(
            and_(
                Payment.invoice_id == invoice.id,
                Payment.status == PaymentStatus.successful
            )
        )
    ).all()

    invoice_data = {
        "invoice_number": invoice.invoice_number,
        "student_name": f"{student.first_name} {student.last_name}",
        "admission_number": student_profile.admission_number if student_profile else "N/A",
        "class_name": class_obj.name if class_obj else "N/A",
        "session_name": session_obj.name if session_obj else "Unknown",
        "term_name": term_obj.name.value if term_obj else "Unknown",
        "created_at": invoice.created_at.strftime('%Y-%m-%d'),
        "due_date": invoice.due_date.strftime('%Y-%m-%d'),
        "total_amount": invoice.total_amount,
        "paid_amount": invoice.paid_amount,
        "balance_due": invoice.balance_due,
        "status": invoice.status.value,
        "items": [
            {"description": item.description, "amount": item.amount}
            for item in items
        ],
        "payments": [
            {
                "amount": payment.amount,
                "status": payment.status.value,
                "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
                "payment_method": payment.payment_method.value if payment.payment_method else None
            }
            for payment in payments
        ]
    }
    
    pdf_generator = InvoicePDFGenerator()
    pdf_buffer = pdf_generator.generate_invoice_pdf(invoice_data)
    return pdf_buffer.getvalue()


# ============================================
# INVOICE GENERATION ENDPOINTS
# ============================================

@router.post("/admin/generate-invoices")
async def generate_invoices(
    request_data: InvoiceGenerateRequest,
    background_tasks: BackgroundTasks,
    current_admin = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Generate new invoices or update existing ones with newly assigned fees.
    PRESERVED: Exact same logic for create vs update behavior.
    """
    due_date = parse_date(request_data.due_date)
    
    # Get all fee assignments
    fee_assignments = session.exec(
        select(FeeAssignment).where(
            and_(
                FeeAssignment.session_id == request_data.session_id,
                FeeAssignment.term_id == request_data.term_id
            )
        )
    ).all()
    
    if not fee_assignments:
        raise HTTPException(
            status_code=404,
            detail="No fee assignments found for this session/term"
        )
    
    fee_ids = {fa.fee_id for fa in fee_assignments}
    fees_by_id = {
        fee.id: fee
        for fee in session.exec(select(Fee).where(Fee.id.in_(list(fee_ids)))).all()
    }
    
    # Get target enrollments
    enrollment_query = select(Enrollment).where(
        and_(
            Enrollment.session_id == request_data.session_id,
            Enrollment.is_active == True
        )
    )
    
    if request_data.scope == InvoiceGenerationScope.classes:
        enrollment_query = enrollment_query.where(
            Enrollment.class_id.in_(request_data.target_ids)
        )
    elif request_data.scope == InvoiceGenerationScope.students:
        enrollment_query = enrollment_query.where(
            Enrollment.student_id.in_(request_data.target_ids)
        )
    
    enrollments = session.exec(enrollment_query).all()
    
    if not enrollments:
        raise HTTPException(
            status_code=404,
            detail=f"No active enrollments found for the specified {request_data.scope}"
        )
    
    invoices_created = 0
    invoices_updated = 0
    
    for enrollment in enrollments:
        student = session.get(User, enrollment.student_id)
        if not student or not student.is_active:
            continue

        # Determine applicable fees
        applicable_fees = []
        for assignment in fee_assignments:
            fee = fees_by_id.get(assignment.fee_id)
            if not fee or not fee.is_active:
                continue
            
            if (assignment.target_type == TargetType.school or
                (assignment.target_type == TargetType.class_ and 
                 assignment.target_id == enrollment.class_id) or
                (assignment.target_type == TargetType.student and 
                 assignment.target_id == enrollment.student_id)):
                applicable_fees.append(fee)
        
        if not applicable_fees:
            continue

        # Check for existing invoice
        existing_invoice = session.exec(
            select(Invoice).where(
                and_(
                    Invoice.student_id == enrollment.student_id,
                    Invoice.session_id == request_data.session_id,
                    Invoice.term_id == request_data.term_id
                )
            )
        ).first()

        if not existing_invoice:
            # CREATE new invoice
            total_amount = sum(fee.amount for fee in applicable_fees)
            new_invoice = Invoice(
                invoice_number=generate_invoice_number(),
                student_id=enrollment.student_id,
                session_id=request_data.session_id,
                term_id=request_data.term_id,
                status=InvoiceStatus.issued,
                due_date=due_date,
                total_amount=total_amount,
                paid_amount=0.0,
                balance_due=total_amount
            )
            session.add(new_invoice)
            session.flush()

            for fee in applicable_fees:
                session.add(InvoiceItem(
                    invoice_id=new_invoice.id,
                    fee_id=fee.id,
                    description=fee.description or fee.name,
                    amount=fee.amount
                ))
            invoices_created += 1
        else:
            # UPDATE existing invoice
            if existing_invoice.status == InvoiceStatus.cancelled:
                continue

            # Find fees already on invoice
            existing_items = session.exec(
                select(InvoiceItem.fee_id).where(
                    InvoiceItem.invoice_id == existing_invoice.id
                )
            ).all()
            existing_fee_ids = set(existing_items)

            fees_to_add = [
                fee for fee in applicable_fees
                if fee.id not in existing_fee_ids
            ]

            if fees_to_add:
                amount_to_add = 0
                for fee in fees_to_add:
                    session.add(InvoiceItem(
                        invoice_id=existing_invoice.id,
                        fee_id=fee.id,
                        description=fee.description or fee.name,
                        amount=fee.amount
                    ))
                    amount_to_add += fee.amount
                
                existing_invoice.total_amount += amount_to_add
                existing_invoice.balance_due += amount_to_add
                if existing_invoice.status == InvoiceStatus.paid:
                    existing_invoice.status = InvoiceStatus.partial
                
                session.add(existing_invoice)
                invoices_updated += 1
    
    session.commit()
    
    # Log activity
    if invoices_created > 0 or invoices_updated > 0:
        log_details = (
            f"Generated {invoices_created} new invoice(s) and "
            f"updated {invoices_updated} existing invoice(s)."
        )
        await log_activity(
            session=session,
            actor=current_admin,
            action=ActivityAction.INVOICES_GENERATED,
            details=log_details
        )
            
    return {
        "message": f"Process complete. Created: {invoices_created}, Updated: {invoices_updated}."
    }


@router.get("/admin/invoice-generation/preview")
async def preview_invoice_generation(
    session_id: str = Query(...),
    term_id: str = Query(...),
    scope: InvoiceGenerationScope = Query(...),
    target_ids: Optional[str] = Query(None, description="Comma-separated list of IDs"),
    current_admin=Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Preview invoice generation/updates.
    PRESERVED: Returns single list compatible with original frontend response.
    """
    target_list = target_ids.split(",") if target_ids else []

    # Pre-fetch fee data
    fee_assignments = session.exec(
        select(FeeAssignment).where(
            and_(
                FeeAssignment.session_id == session_id,
                FeeAssignment.term_id == term_id
            )
        )
    ).all()
    
    fee_ids = {fa.fee_id for fa in fee_assignments}
    fees_by_id = {
        fee.id: fee
        for fee in session.exec(select(Fee).where(Fee.id.in_(list(fee_ids)))).all()
    } if fee_ids else {}

    # Get targeted enrollments
    enrollment_query = select(Enrollment).where(
        and_(
            Enrollment.session_id == session_id,
            Enrollment.is_active == True
        )
    )
    
    if scope == InvoiceGenerationScope.classes:
        if not target_list:
            raise HTTPException(
                status_code=400,
                detail="target_ids is required for 'classes' scope."
            )
        enrollment_query = enrollment_query.where(Enrollment.class_id.in_(target_list))
    elif scope == InvoiceGenerationScope.students:
        if not target_list:
            raise HTTPException(
                status_code=400,
                detail="target_ids is required for 'students' scope."
            )
        enrollment_query = enrollment_query.where(Enrollment.student_id.in_(target_list))
    
    enrollments = session.exec(enrollment_query).all()
    
    if not enrollments:
        return {
            "message": "No active enrollments found for the specified scope.",
            "scope": scope.value,
            "total_enrollments_in_scope": 0,
            "students_with_existing_invoices_for_term": 0,
            "students_ready_for_invoicing": 0,
            "preview_students_to_be_invoiced": [],
        }

    # Fetch existing invoices
    targeted_student_ids = [e.student_id for e in enrollments]
    existing_invoices_list = session.exec(
        select(Invoice).where(
            and_(
                Invoice.session_id == session_id,
                Invoice.term_id == term_id,
                Invoice.student_id.in_(targeted_student_ids)
            )
        )
    ).all()
    
    invoices_by_student_id = {inv.student_id: inv for inv in existing_invoices_list}
    
    existing_invoice_ids = [inv.id for inv in existing_invoices_list]
    all_invoice_items = session.exec(
        select(InvoiceItem).where(InvoiceItem.invoice_id.in_(existing_invoice_ids))
    ).all() if existing_invoice_ids else []
    
    fee_ids_by_invoice_id = {}
    for item in all_invoice_items:
        fee_ids_by_invoice_id.setdefault(item.invoice_id, set()).add(item.fee_id)

    merged_preview_list = []
    
    for enrollment in enrollments:
        student = session.get(User, enrollment.student_id)
        if not student:
            continue

        # Determine applicable fees
        applicable_fees = []
        for assignment in fee_assignments:
            fee = fees_by_id.get(assignment.fee_id)
            if not fee or not fee.is_active:
                continue
            
            if (assignment.target_type == TargetType.school or
                (assignment.target_type == TargetType.class_ and 
                 assignment.target_id == enrollment.class_id) or
                (assignment.target_type == TargetType.student and 
                 assignment.target_id == enrollment.student_id)):
                applicable_fees.append(fee)
        
        if not applicable_fees:
            continue

        existing_invoice = invoices_by_student_id.get(enrollment.student_id)

        if not existing_invoice:
            # Case 1: CREATE
            merged_preview_list.append({
                "student_id": student.id,
                "student_name": f"{student.first_name} {student.last_name}",
                "class_id": enrollment.class_id,
                "preview_total_amount": sum(f.amount for f in applicable_fees),
                "applicable_fees": [
                    {"name": f.name, "amount": f.amount}
                    for f in applicable_fees
                ]
            })
        else:
            # Case 2: UPDATE
            fees_already_on_invoice = fee_ids_by_invoice_id.get(existing_invoice.id, set())
            fees_to_add = [
                fee for fee in applicable_fees
                if fee.id not in fees_already_on_invoice
            ]
            
            if fees_to_add:
                merged_preview_list.append({
                    "student_id": student.id,
                    "student_name": f"{student.first_name} {student.last_name} (Update)",
                    "class_id": enrollment.class_id,
                    "preview_total_amount": sum(f.amount for f in fees_to_add),
                    "applicable_fees": [
                        {"name": f.name, "amount": f.amount}
                        for f in fees_to_add
                    ]
                })

    return {
        "scope": scope.value,
        "target_ids": target_list,
        "total_enrollments_in_scope": len(enrollments),
        "students_with_existing_invoices_for_term": len(invoices_by_student_id),
        "students_ready_for_invoicing": len(merged_preview_list),
        "overdue_summary": {
            "count_students_with_overdue": 0,
            "total_overdue_amount": 0.0
        },
        "preview_students_to_be_invoiced": merged_preview_list[:20],
        "showing_first": min(20, len(merged_preview_list))
    }


# Continuation of app/api/v1/invoices.py
# Add these endpoints to the router in invoices.py

# ============================================
# INVOICE LISTING ENDPOINTS
# ============================================

@router.get("/admin/invoices", response_model=PaginatedInvoiceResponse)
async def get_all_invoices(
    skip: int = Query(0, ge=0),
    limit: int = Query(15, ge=1, le=500),
    status: Optional[InvoiceStatus] = Query(None),
    session_id: Optional[str] = Query(None),
    term_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_admin=Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Get all invoices with filtering and server-side pagination.
    PRESERVED: Exact same query logic and response structure.
    """
    # Update overdue statuses first
    update_overdue_invoices(session)

    base_query = select(Invoice)
    count_query = select(func.count(Invoice.id))
    conditions = []
    
    if search:
        base_query = base_query.join(User, Invoice.student_id == User.id)
        count_query = count_query.select_from(Invoice).join(
            User, Invoice.student_id == User.id
        )
        search_term = f"%{search.strip()}%"
        
        search_condition = or_(
            Invoice.invoice_number.ilike(search_term),
            User.first_name.ilike(search_term),
            User.last_name.ilike(search_term),
            (User.first_name + ' ' + User.last_name).ilike(search_term)
        )
        conditions.append(search_condition)
        
    if status:
        conditions.append(Invoice.status == status)
    
    if session_id:
        conditions.append(Invoice.session_id == session_id)
    
    if term_id:
        conditions.append(Invoice.term_id == term_id)
    
    if conditions:
        applied_conditions = and_(*conditions)
        base_query = base_query.where(applied_conditions)
        count_query = count_query.where(applied_conditions)

    total_count = session.exec(count_query).one()

    invoices = session.exec(
        base_query.offset(skip).limit(limit).order_by(Invoice.created_at.desc())
    ).all()

    invoice_responses = []
    for invoice in invoices:
        student = session.get(User, invoice.student_id)
        session_obj = session.get(AcademicSession, invoice.session_id)
        term_obj = session.get(Term, invoice.term_id)
        items = session.exec(
            select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
        ).all()
        payments = session.exec(
            select(Payment).where(Payment.invoice_id == invoice.id)
        ).all()
        
        invoice_responses.append(InvoiceResponse(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            student_name=f"{student.first_name} {student.last_name}",
            session_name=session_obj.name if session_obj else "Unknown",
            term_name=term_obj.name.value if term_obj else "Unknown",
            status=invoice.status,
            due_date=invoice.due_date,
            total_amount=invoice.total_amount,
            paid_amount=invoice.paid_amount,
            balance_due=invoice.balance_due,
            items=[
                {"description": item.description, "amount": item.amount}
                for item in items
            ],
            payments=[
                {
                    "id": p.id, "amount": p.amount, "status": p.status,
                    "paid_at": p.paid_at, "payment_method": p.payment_method
                }
                for p in payments
            ]
        ))
    
    return PaginatedInvoiceResponse(
        total=total_count,
        invoices=invoice_responses,
        has_more=(skip + len(invoices)) < total_count
    )


@router.get("/invoices/by-student", response_model=List[InvoiceResponse])
async def get_student_invoices(
    student_id: Optional[str] = Query(None),
    status: Optional[InvoiceStatus] = Query(None),
    current_user_data: dict = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    """
    Fetch invoices for a student.
    PRESERVED: Student gets own invoices, admin can specify student_id.
    """
    user = current_user_data["user"]
    user_role = current_user_data["user_type"]
    
    target_student_id = None

    if user_role == UserRole.student:
        target_student_id = user.id
    elif user_role == UserRole.admin:
        if not student_id:
            raise HTTPException(
                status_code=400,
                detail="Admin must provide a 'student_id' query parameter."
            )
        target_student = session.get(User, student_id)
        if not target_student or target_student.role != UserRole.student:
            raise HTTPException(status_code=404, detail="Student not found.")
        target_student_id = student_id
    else:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access invoices."
        )

    query = select(Invoice).where(Invoice.student_id == target_student_id)
    
    if status:
        query = query.where(Invoice.status == status)
    else:
        query = query.where(Invoice.status != InvoiceStatus.draft)
    
    invoices = session.exec(query.order_by(Invoice.created_at.desc())).all()
    
    invoice_responses = []
    for invoice in invoices:
        student_user = session.get(User, invoice.student_id)
        session_obj = session.get(AcademicSession, invoice.session_id)
        term_obj = session.get(Term, invoice.term_id)
        
        items = session.exec(
            select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
        ).all()
        payments = session.exec(
            select(Payment).where(Payment.invoice_id == invoice.id)
        ).all()
        
        invoice_responses.append(InvoiceResponse(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            student_name=f"{student_user.first_name} {student_user.last_name}",
            session_name=session_obj.name if session_obj else "Unknown",
            term_name=term_obj.name.value if term_obj else "Unknown",
            status=invoice.status,
            due_date=invoice.due_date,
            total_amount=invoice.total_amount,
            paid_amount=invoice.paid_amount,
            balance_due=invoice.balance_due,
            items=[
                {"description": item.description, "amount": item.amount}
                for item in items
            ],
            payments=[
                {
                    "id": p.id, "amount": p.amount, "status": p.status,
                    "paid_at": p.paid_at, "payment_method": p.payment_method
                }
                for p in payments
            ]
        ))
    
    return invoice_responses


@router.get("/student/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice_details(
    invoice_id: str,
    current_user_data: dict = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    """
    Get specific invoice details.
    PRESERVED: Accessible by student owner or any admin.
    """
    user = current_user_data["user"]
    user_role = current_user_data["user_type"]

    invoice = session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    is_admin = (user_role == UserRole.admin)
    is_owner = (user_role == UserRole.student and invoice.student_id == user.id)

    if not (is_admin or is_owner):
        raise HTTPException(status_code=404, detail="Invoice not found")

    student = session.get(User, invoice.student_id)
    session_obj = session.get(AcademicSession, invoice.session_id)
    term_obj = session.get(Term, invoice.term_id)
    
    items = session.exec(
        select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
    ).all()
    
    payments = session.exec(
        select(Payment).where(Payment.invoice_id == invoice.id)
    ).all()
    
    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        student_name=f"{student.first_name} {student.last_name}",
        session_name=session_obj.name,
        term_name=term_obj.name.value,
        status=invoice.status,
        due_date=invoice.due_date,
        total_amount=invoice.total_amount,
        paid_amount=invoice.paid_amount,
        balance_due=invoice.balance_due,
        items=[
            {"description": item.description, "amount": item.amount}
            for item in items
        ],
        payments=[
            {
                "id": payment.id,
                "amount": payment.amount,
                "status": payment.status,
                "paid_at": payment.paid_at,
                "payment_method": payment.payment_method
            }
            for payment in payments
        ]
    )


# ============================================
# PDF DOWNLOAD ENDPOINTS
# ============================================

@router.get("/student/invoice/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: str,
    current_student = Depends(get_current_student),
    session: Session = Depends(get_session)
):
    """
    Download invoice as PDF (Student).
    PRESERVED: Exact same PDF generation logic.
    """
    invoice = session.get(Invoice, invoice_id)
    if not invoice or invoice.student_id != current_student.id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    pdf_bytes = await get_invoice_pdf_bytes(invoice_id, session)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="Failed to generate PDF")
    
    filename = f"invoice_{invoice.invoice_number}.pdf"
    
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/admin/invoice/{invoice_id}/pdf")
async def admin_download_invoice_pdf(
    invoice_id: str,
    current_admin = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Admin download invoice as PDF.
    PRESERVED: Exact same PDF generation logic.
    """
    invoice = session.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    pdf_bytes = await get_invoice_pdf_bytes(invoice_id, session)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="Failed to generate PDF")
    
    filename = f"invoice_{invoice.invoice_number}.pdf"
    
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/admin/generate-bulk-pdfs")
async def generate_bulk_invoice_pdfs(
    session_id: str = Query(...),
    term_id: str = Query(...),
    class_id: Optional[str] = Query(None),
    status: Optional[InvoiceStatus] = Query(None),
    current_admin = Depends(get_current_admin),
    session: Session = Depends(get_session)
):
    """
    Generate ZIP file with multiple invoice PDFs.
    PRESERVED: Exact same bulk generation logic.
    """
    query = select(Invoice).where(
        and_(
            Invoice.session_id == session_id,
            Invoice.term_id == term_id
        )
    )

    if status:
        query = query.where(Invoice.status == status)

    invoices = session.exec(query).all()

    if not invoices:
        raise HTTPException(status_code=404, detail="No invoices found")

    # Filter by class if specified
    if class_id:
        filtered_invoices = []
        for inv in invoices:
            enrollment = session.exec(
                select(Enrollment).where(
                    and_(
                        Enrollment.student_id == inv.student_id,
                        Enrollment.session_id == inv.session_id,
                        Enrollment.term_id == inv.term_id,
                        Enrollment.class_id == class_id
                    )
                )
            ).first()
            if enrollment:
                filtered_invoices.append(inv)
        invoices = filtered_invoices

        if not invoices:
            raise HTTPException(
                status_code=404,
                detail="No invoices found for this class"
            )

    # Create temporary ZIP file
    with NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
        with zipfile.ZipFile(tmp_zip.name, "w") as zip_file:
            for invoice in invoices:
                pdf_bytes = await get_invoice_pdf_bytes(invoice.id, session)
                if pdf_bytes:
                    pdf_filename = f"invoice_{invoice.invoice_number}.pdf"
                    zip_file.writestr(pdf_filename, pdf_bytes)

        zip_filename = (
            f"invoices_{session_id}_{term_id}_"
            f"{datetime.now().strftime('%Y%m%d')}.zip"
        )

        def cleanup():
            os.unlink(tmp_zip.name)

        return StreamingResponse(
            open(tmp_zip.name, "rb"),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={zip_filename}"},
            background=BackgroundTasks(tasks=[cleanup])
        )


# Continue in next part...