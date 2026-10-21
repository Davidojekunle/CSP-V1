# app/services/fee_service.py
"""Service layer for Fee and Fee Assignment management."""
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, and_

from app.models import Fee, FeeAssignment, AcademicSession, Term, Class, User, Invoice, InvoiceItem, Enrollment, TargetType, InvoiceStatus, Payment
from app.models.base import PaymentStatus
from app.schemas.fee import FeeCreate, FeeUpdate, FeeAssignmentCreate

async def create_fee(fee_data: FeeCreate, db: AsyncSession) -> Fee:
    result = await db.execute(select(Fee).where(Fee.name == fee_data.name))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Fee with this name already exists")
    
    new_fee = Fee.model_validate(fee_data)
    db.add(new_fee)
    await db.commit()
    await db.refresh(new_fee)
    return new_fee

async def get_all_fees(db: AsyncSession, is_active: Optional[bool]) -> List[Fee]:
    query = select(Fee)
    if is_active is not None:
        query = query.where(Fee.is_active == is_active)
    result = await db.execute(query)
    return result.scalars().all()

async def update_fee(fee_id: str, fee_data: FeeUpdate, db: AsyncSession) -> Fee:
    fee = await db.get(Fee, fee_id)
    if not fee:
        raise HTTPException(status_code=404, detail="Fee not found")
    
    update_data = fee_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fee, key, value)
        
    db.add(fee)
    await db.commit()
    await db.refresh(fee)
    return fee

async def create_fee_assignment(assign_data: FeeAssignmentCreate, db: AsyncSession):
    if not await db.get(Fee, assign_data.fee_id):
        raise HTTPException(status_code=404, detail="Fee not found")
    if not await db.get(AcademicSession, assign_data.session_id) or not await db.get(Term, assign_data.term_id):
        raise HTTPException(status_code=404, detail="Session or term not found")
    
    # Validation for existing assignment
    result = await db.execute(select(FeeAssignment).where(
        FeeAssignment.fee_id == assign_data.fee_id,
        FeeAssignment.session_id == assign_data.session_id,
        FeeAssignment.term_id == assign_data.term_id,
        FeeAssignment.target_type == assign_data.target_type,
        FeeAssignment.target_id == assign_data.target_id
    ))
    existing = result.scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="This exact fee assignment already exists")
        
    new_assignment = FeeAssignment.model_validate(assign_data)
    db.add(new_assignment)
    await db.commit()

def _generate_invoice_number() -> str:

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f") 
    random_part = str(uuid.uuid4())[:8].upper()
    return f"INV-{timestamp}-{random_part}"

def parse_date(date_string: str) -> date:
    """Parse date string to date object"""
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

async def generate_invoices_for_term(req: dict, db: AsyncSession) -> dict:
    due_date = parse_date(req['due_date']) # Assuming _parse_date exists
    
    # 1. Get all relevant fee assignments and fees
    result = await db.execute(select(FeeAssignment).where(
        FeeAssignment.session_id == req['session_id'], FeeAssignment.term_id == req['term_id']
    ))
    fee_assignments = result.scalars().all()
    if not fee_assignments:
        raise HTTPException(status_code=404, detail="No fee assignments found for this term.")
    
    fee_ids = {fa.fee_id for fa in fee_assignments}
    result = await db.execute(select(Fee).where(Fee.id.in_(list(fee_ids)), Fee.is_active == True))
    fees_map = {fee.id: fee for fee in result.scalars().all()}

    # 2. Get target students via their enrollments
    enrollment_query = select(Enrollment).where(
        Enrollment.session_id == req['session_id'], Enrollment.is_active == True
    )
    if req['scope'] == 'classes':
        enrollment_query = enrollment_query.where(Enrollment.class_id.in_(req['target_ids']))
    elif req['scope'] == 'students':
        enrollment_query = enrollment_query.where(Enrollment.student_id.in_(req['target_ids']))
    
    result = await db.execute(enrollment_query)
    enrollments = result.scalars().all()
    if not enrollments:
        raise HTTPException(status_code=404, detail=f"No active enrollments found for the scope.")

    # Prefetch existing invoices and their items for everyone in scope (2 queries instead of 2 per student)
    student_ids = list({e.student_id for e in enrollments})
    existing_invoices = {}
    for inv in (await db.execute(select(Invoice).where(
        Invoice.student_id.in_(student_ids),
        Invoice.session_id == req['session_id'],
        Invoice.term_id == req['term_id']
    ).order_by(Invoice.created_at))).scalars().all():
        existing_invoices.setdefault(inv.student_id, inv)
    existing_fee_ids = defaultdict(set)
    if existing_invoices:
        for item in (await db.execute(select(InvoiceItem).where(
            InvoiceItem.invoice_id.in_([inv.id for inv in existing_invoices.values()])
        ))).scalars().all():
            existing_fee_ids[item.invoice_id].add(item.fee_id)

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

        existing_invoice = existing_invoices.get(enrollment.student_id)

        if not existing_invoice:
            # CREATE new invoice (id is generated client-side, so no flush is needed)
            total = sum(fee.amount for fee in applicable_fees)
            new_invoice = Invoice(
                invoice_number=_generate_invoice_number(), student_id=enrollment.student_id,
                session_id=req['session_id'], term_id=req['term_id'], status=InvoiceStatus.issued,
                due_date=due_date, total_amount=total, balance_due=total
            )
            db.add(new_invoice)
            for fee in applicable_fees:
                db.add(InvoiceItem(invoice_id=new_invoice.id, fee_id=fee.id, description=fee.name, amount=fee.amount))
            # A student can have several enrollments in a session; don't invoice them twice
            existing_invoices[enrollment.student_id] = new_invoice
            existing_fee_ids[new_invoice.id] = {fee.id for fee in applicable_fees}
            created_count += 1
        else:
            # UPDATE existing invoice (add missing fees)
            if existing_invoice.status == InvoiceStatus.cancelled: continue

            fees_to_add = [fee for fee in applicable_fees if fee.id not in existing_fee_ids[existing_invoice.id]]

            if fees_to_add:
                amount_to_add = sum(fee.amount for fee in fees_to_add)
                for fee in fees_to_add:
                    db.add(InvoiceItem(invoice_id=existing_invoice.id, fee_id=fee.id, description=fee.name, amount=fee.amount))
                existing_fee_ids[existing_invoice.id].update(fee.id for fee in fees_to_add)

                existing_invoice.total_amount += amount_to_add
                existing_invoice.balance_due += amount_to_add
                if existing_invoice.status == InvoiceStatus.paid:
                    existing_invoice.status = InvoiceStatus.partial
                db.add(existing_invoice)
                updated_count += 1

    await db.commit()
    return {"created": created_count, "updated": updated_count}


async def _update_overdue_invoices(db: AsyncSession):
    """
    Transitions issued/partial invoices past their due date to overdue,
    with a single UPDATE statement.
    """
    result = await db.execute(update(Invoice).where(
        Invoice.due_date < date.today(),
        Invoice.balance_due > 0,
        Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.partial])
    ).values(status=InvoiceStatus.overdue))
    if result.rowcount:
        await db.commit()

async def get_all_invoices(
    db: AsyncSession, skip: int, limit: int,
    status: Optional[InvoiceStatus], session_id: Optional[str],
    term_id: Optional[str], search: Optional[str]
) -> tuple[List[Invoice], int]:
    """
    PERFORMANCE: Fetches a paginated list of all invoices with filtering and search.
    """
    await _update_overdue_invoices(db) # Ensure statuses are current before querying

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

    result_count = await db.execute(count_query)
    total_count = result_count.scalar_one()
    result_invoices = await db.execute(base_query.order_by(Invoice.created_at.desc(), Invoice.id).offset(skip).limit(limit))
    invoices = result_invoices.scalars().all()
    
    return invoices, total_count


async def cancel_invoice(invoice_id: str, db: AsyncSession) -> Invoice:
    """Cancels an invoice if it has no payments."""
    invoice = await db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.paid:
        raise HTTPException(status_code=400, detail="Cannot cancel a fully paid invoice")
    if invoice.paid_amount > 0:
        raise HTTPException(status_code=400, detail="Cannot cancel an invoice with partial payments")
        
    invoice.status = InvoiceStatus.cancelled
    invoice.updated_at = datetime.utcnow()
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    return invoice

async def get_dashboard_stats(db: AsyncSession, session_id: Optional[str], term_id: Optional[str]) -> dict:
    """Fee dashboard figures, computed with aggregate queries."""
    invoice_conditions = []
    if session_id: invoice_conditions.append(Invoice.session_id == session_id)
    if term_id: invoice_conditions.append(Invoice.term_id == term_id)
    # Financial calculations exclude cancelled/draft invoices
    relevant = and_(*invoice_conditions, Invoice.status.notin_([InvoiceStatus.cancelled, InvoiceStatus.draft]))

    status_counts = {
        (status.value if hasattr(status, "value") else status): count
        for status, count in (await db.execute(
            select(Invoice.status, func.count(Invoice.id)).where(*invoice_conditions).group_by(Invoice.status)
        )).all()
    }
    total_invoiced, total_outstanding = (await db.execute(
        select(func.coalesce(func.sum(Invoice.total_amount), 0.0), func.coalesce(func.sum(Invoice.balance_due), 0.0)).where(relevant)
    )).one()

    paid_base = (
        select(Payment.payment_method, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0.0))
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .where(Payment.status == PaymentStatus.successful, relevant)
    )
    total_paid, payment_methods = 0.0, {}
    for method, count, amount in (await db.execute(paid_base.group_by(Payment.payment_method))).all():
        total_paid += amount
        if method:
            key = method.value if hasattr(method, "value") else method
            payment_methods[key] = payment_methods.get(key, 0) + count

    recent_payments = (await db.execute(
        select(func.count(Payment.id))
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .where(Payment.status == PaymentStatus.successful, relevant,
               Payment.paid_at >= datetime.utcnow() - timedelta(days=8))
    )).scalar_one()

    return {
        "total_invoices": sum(status_counts.values()), "total_invoiced": float(total_invoiced),
        "total_paid": float(total_paid), "total_outstanding": float(total_outstanding),
        "collection_rate": round((total_paid / total_invoiced * 100) if total_invoiced > 0 else 0, 2),
        "status_breakdown": status_counts, "payment_methods": payment_methods,
        "recent_payments": recent_payments
    }


async def get_invoices_for_student(student_id: str, status: Optional[InvoiceStatus], db: AsyncSession) -> List[dict]:
    query = select(Invoice).where(Invoice.student_id == student_id)
    if status:
        query = query.where(Invoice.status == status)
    invoices = (await db.execute(query.order_by(Invoice.created_at.desc()))).scalars().all()
    return await _build_invoice_responses_bulk(invoices, db)

async def get_fee_assignments_by_target(session_id: str, term_id: str, target_type: Optional[TargetType], db: AsyncSession) -> Dict:
    """
    Fetches fee assignments for a given term and groups them by their target type.
    """
    query = select(FeeAssignment).where(
        FeeAssignment.session_id == session_id,
        FeeAssignment.term_id == term_id
    )
    if target_type:
        query = query.where(FeeAssignment.target_type == target_type)
    
    result_assignments = await db.execute(query)
    assignments = result_assignments.scalars().all()

    # PERFORMANCE: Fetch all related objects (fees, classes, users) in bulk
    fee_ids = {a.fee_id for a in assignments}
    class_ids = {a.target_id for a in assignments if a.target_type == TargetType.class_}
    student_ids = {a.target_id for a in assignments if a.target_type == TargetType.student}

    result_fees = await db.execute(select(Fee).where(Fee.id.in_(fee_ids)))
    fees_map = {f.id: f for f in result_fees.scalars().all()} if fee_ids else {}
    result_classes = await db.execute(select(Class).where(Class.id.in_(class_ids)))
    classes_map = {c.id: c for c in result_classes.scalars().all()} if class_ids else {}
    result_students = await db.execute(select(User).where(User.id.in_(student_ids)))
    students_map = {u.id: u for u in result_students.scalars().all()} if student_ids else {}

    # Group the results in memory (fast)
    grouped = {"school": [], "classes": [], "students": []}
    
    for assign in assignments:
        fee = fees_map.get(assign.fee_id)
        assign_data = {
            "assignment_id": assign.id,
            "fee_name": fee.name if fee else "Unknown Fee",
            "fee_amount": fee.amount if fee else 0.0,
            "target_id": assign.target_id
        }
        
        if assign.target_type == TargetType.school:
            grouped["school"].append(assign_data)
        elif assign.target_type == TargetType.class_:
            class_obj = classes_map.get(assign.target_id)
            assign_data["target_name"] = class_obj.name if class_obj else "Unknown Class"
            grouped["classes"].append(assign_data)
        elif assign.target_type == TargetType.student:
            student = students_map.get(assign.target_id)
            assign_data["target_name"] = f"{student.first_name} {student.last_name}" if student else "Unknown Student"
            grouped["students"].append(assign_data)
            
    return {
        "session_id": session_id,
        "term_id": term_id,
        "assignments_by_target": grouped,
        "total_assignments": len(assignments)
    }

async def _build_invoice_responses_bulk(invoices: List[Invoice], db: AsyncSession) -> List[dict]:
    """
    PERFORMANCE OPTIMIZED: Builds detailed invoice responses by fetching all
    related data in a minimal number of bulk queries, avoiding N+1.
    """
    if not invoices:
        return []

    invoice_ids = [inv.id for inv in invoices]
    student_ids = list({inv.student_id for inv in invoices})
    session_ids = list({inv.session_id for inv in invoices})
    term_ids = list({inv.term_id for inv in invoices})

    # Bulk fetch all related data in one go
    result_students = await db.execute(select(User).where(User.id.in_(student_ids)))
    students_map = {u.id: u for u in result_students.scalars().all()}
    result_sessions = await db.execute(select(AcademicSession).where(AcademicSession.id.in_(session_ids)))
    sessions_map = {s.id: s for s in result_sessions.scalars().all()}
    result_terms = await db.execute(select(Term).where(Term.id.in_(term_ids)))
    terms_map = {t.id: t for t in result_terms.scalars().all()}
    
    # Group items and payments by invoice_id
    result_items = await db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id.in_(invoice_ids)))
    items_map = defaultdict(list)
    for item in result_items.scalars().all():
        items_map[item.invoice_id].append({"description": item.description, "amount": item.amount})
        
    result_payments = await db.execute(select(Payment).where(Payment.invoice_id.in_(invoice_ids)))
    payments_map = defaultdict(list)
    for p in result_payments.scalars().all():
        payments_map[p.invoice_id].append({
            "id": p.id, "amount": p.amount, "status": p.status.value,
            "paid_at": p.paid_at, "payment_method": p.payment_method.value if p.payment_method else None
        })

    # Assemble the final response list in memory
    response_list = []
    for inv in invoices:
        student = students_map.get(inv.student_id)
        session_obj = sessions_map.get(inv.session_id)
        term_obj = terms_map.get(inv.term_id)
        
        response_list.append({
            "id": inv.id, "invoice_number": inv.invoice_number,
            "student_name": f"{student.first_name} {student.last_name}" if student else "N/A",
            "session_name": session_obj.name if session_obj else "N/A",
            "term_name": term_obj.name.value if term_obj else "N/A",
            "status": inv.status, "due_date": inv.due_date,
            "total_amount": inv.total_amount, "paid_amount": inv.paid_amount,
            "balance_due": inv.balance_due,
            "items": items_map.get(inv.id, []),
            "payments": payments_map.get(inv.id, [])
        })
    return response_list