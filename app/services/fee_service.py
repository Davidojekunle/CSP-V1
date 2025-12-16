# app/services/fee_service.py
"""Service layer for Fee and Fee Assignment management."""
from sqlmodel import Session, select, and_
from fastapi import HTTPException
from typing import List, Optional
from sqlalchemy import func, or_

from app.models import Fee, FeeAssignment, AcademicSession, Term, Class, User, Invoice, InvoiceItem, Enrollment, Fee, TargetType, InvoiceStatus, Payment, UserRole
from app.schemas.fee import FeeCreate, FeeUpdate, FeeAssignmentCreate
from datetime import date, datetime
import uuid

def create_fee(fee_data: FeeCreate, db: Session) -> Fee:
    if db.exec(select(Fee).where(Fee.name == fee_data.name)).first():
        raise HTTPException(status_code=400, detail="Fee with this name already exists")
    
    new_fee = Fee.model_validate(fee_data)
    db.add(new_fee)
    db.commit()
    db.refresh(new_fee)
    return new_fee

def get_all_fees(db: Session, is_active: Optional[bool]) -> List[Fee]:
    query = select(Fee)
    if is_active is not None:
        query = query.where(Fee.is_active == is_active)
    return db.exec(query).all()

def update_fee(fee_id: str, fee_data: FeeUpdate, db: Session) -> Fee:
    fee = db.get(Fee, fee_id)
    if not fee:
        raise HTTPException(status_code=404, detail="Fee not found")
    
    update_data = fee_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fee, key, value)
        
    db.add(fee)
    db.commit()
    db.refresh(fee)
    return fee

def create_fee_assignment(assign_data: FeeAssignmentCreate, db: Session):
    if not db.get(Fee, assign_data.fee_id):
        raise HTTPException(status_code=404, detail="Fee not found")
    if not db.get(AcademicSession, assign_data.session_id) or not db.get(Term, assign_data.term_id):
        raise HTTPException(status_code=404, detail="Session or term not found")
    
    # Validation for existing assignment
    existing = db.exec(select(FeeAssignment).where(
        FeeAssignment.fee_id == assign_data.fee_id,
        FeeAssignment.session_id == assign_data.session_id,
        FeeAssignment.term_id == assign_data.term_id,
        FeeAssignment.target_type == assign_data.target_type,
        FeeAssignment.target_id == assign_data.target_id
    )).first()
    if existing:
        raise HTTPException(status_code=400, detail="This exact fee assignment already exists")
        
    new_assignment = FeeAssignment.model_validate(assign_data)
    db.add(new_assignment)
    db.commit()

def _generate_invoice_number() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"INV-{timestamp}-{str(uuid.uuid4())[:4].upper()}"

def parse_date(date_string: str) -> date:
    """Parse date string to date object"""
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

def generate_invoices_for_term(req: dict, db: Session) -> dict:
    due_date = parse_date(req['due_date']) # Assuming _parse_date exists
    
    # 1. Get all relevant fee assignments and fees
    fee_assignments = db.exec(select(FeeAssignment).where(
        FeeAssignment.session_id == req['session_id'], FeeAssignment.term_id == req['term_id']
    )).all()
    if not fee_assignments:
        raise HTTPException(status_code=404, detail="No fee assignments found for this term.")
    
    fee_ids = {fa.fee_id for fa in fee_assignments}
    fees_map = {fee.id: fee for fee in db.exec(select(Fee).where(Fee.id.in_(list(fee_ids)), Fee.is_active == True)).all()}

    # 2. Get target students via their enrollments
    enrollment_query = select(Enrollment).where(
        Enrollment.session_id == req['session_id'], Enrollment.is_active == True
    )
    if req['scope'] == 'classes':
        enrollment_query = enrollment_query.where(Enrollment.class_id.in_(req['target_ids']))
    elif req['scope'] == 'students':
        enrollment_query = enrollment_query.where(Enrollment.student_id.in_(req['target_ids']))
    
    enrollments = db.exec(enrollment_query).all()
    if not enrollments:
        raise HTTPException(status_code=404, detail=f"No active enrollments found for the scope.")

    created_count, updated_count = 0, 0
    
    for enrollment in enrollments:
        # Determine applicable fees for this student
        applicable_fees = []
        for assign in fee_assignments:
            fee = fees_map.get(assign.fee_id)
            if not fee: continue
            if (assign.target_type == TargetType.school or
               (assign.target_type == TargetType.class_ and assign.target_id == enrollment.class_id) or
               (assign.target_type == TargetType.student and assign.target_id == enrollment.student_id)):
                applicable_fees.append(fee)
        
        if not applicable_fees: continue

        # Check for an existing invoice to either create or update
        existing_invoice = db.exec(select(Invoice).where(
            Invoice.student_id == enrollment.student_id,
            Invoice.session_id == req['session_id'],
            Invoice.term_id == req['term_id']
        )).first()

        if not existing_invoice:
            # CREATE new invoice
            total = sum(fee.amount for fee in applicable_fees)
            new_invoice = Invoice(
                invoice_number=_generate_invoice_number(), student_id=enrollment.student_id,
                session_id=req['session_id'], term_id=req['term_id'], status=InvoiceStatus.issued,
                due_date=due_date, total_amount=total, balance_due=total
            )
            db.add(new_invoice)
            db.flush() # Get ID for items
            for fee in applicable_fees:
                db.add(InvoiceItem(invoice_id=new_invoice.id, fee_id=fee.id, description=fee.name, amount=fee.amount))
            created_count += 1
        else:
            # UPDATE existing invoice (add missing fees)
            if existing_invoice.status == InvoiceStatus.cancelled: continue
            
            existing_fee_ids = {item.fee_id for item in existing_invoice.items}
            fees_to_add = [fee for fee in applicable_fees if fee.id not in existing_fee_ids]
            
            if fees_to_add:
                amount_to_add = sum(fee.amount for fee in fees_to_add)
                for fee in fees_to_add:
                    db.add(InvoiceItem(invoice_id=existing_invoice.id, fee_id=fee.id, description=fee.name, amount=fee.amount))
                
                existing_invoice.total_amount += amount_to_add
                existing_invoice.balance_due += amount_to_add
                if existing_invoice.status == InvoiceStatus.paid:
                    existing_invoice.status = InvoiceStatus.partial
                db.add(existing_invoice)
                updated_count += 1
                
    db.commit()
    return {"created": created_count, "updated": updated_count}


def _update_overdue_invoices(db: Session):
    """
    Helper to transition issued/partial invoices to overdue status.
    This is preserved from the original logic.
    """
    today = date.today()
    invoices_to_update = db.exec(select(Invoice).where(
        Invoice.due_date < today,
        Invoice.balance_due > 0,
        Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.partial])
    )).all()

    if invoices_to_update:
        for invoice in invoices_to_update:
            invoice.status = InvoiceStatus.overdue
        db.commit()

def get_all_invoices(
    db: Session, skip: int, limit: int,
    status: Optional[InvoiceStatus], session_id: Optional[str],
    term_id: Optional[str], search: Optional[str]
) -> tuple[List[Invoice], int]:
    """
    PERFORMANCE: Fetches a paginated list of all invoices with filtering and search.
    """
    _update_overdue_invoices(db) # Ensure statuses are current before querying

    base_query = select(Invoice)
    count_query = select(func.count(Invoice.id))
    conditions = []
    
    if search:
        base_query = base_query.join(User, Invoice.student_id == User.id)
        count_query = count_query.select_from(Invoice).join(User, Invoice.student_id == User.id)
        search_term = f"%{search.strip()}%"
        search_condition = or_(
            Invoice.invoice_number.ilike(search_term),
            User.first_name.ilike(search_term),
            User.last_name.ilike(search_term),
            (User.first_name + ' ' + User.last_name).ilike(search_term)
        )
        conditions.append(search_condition)
        
    if status: conditions.append(Invoice.status == status)
    if session_id: conditions.append(Invoice.session_id == session_id)
    if term_id: conditions.append(Invoice.term_id == term_id)
    
    if conditions:
        applied_conditions = and_(*conditions)
        base_query = base_query.where(applied_conditions)
        count_query = count_query.where(applied_conditions)

    total_count = db.exec(count_query).one()
    invoices = db.exec(base_query.offset(skip).limit(limit).order_by(Invoice.created_at.desc())).all()
    
    return invoices, total_count


def cancel_invoice(invoice_id: str, db: Session) -> Invoice:
    """Cancels an invoice if it has no payments."""
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(status_code=400, detail="Cannot cancel a fully paid invoice")
    if invoice.paid_amount > 0:
        raise HTTPException(status_code=400, detail="Cannot cancel an invoice with partial payments")
        
    invoice.status = InvoiceStatus.cancelled
    invoice.updated_at = datetime.utcnow()
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice