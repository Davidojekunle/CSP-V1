# app/api/v1/payments.py
"""New, refactored API routes for payment processing."""
import json
from fastapi import APIRouter, Depends, Request, BackgroundTasks, status, HTTPException
from sqlmodel import Session
import uuid

from app.core.database import get_session
from app.core.auth import get_current_admin, get_current_student
from app.models import User, Payment, PaymentStatus, Invoice
from app.schemas.payment import ManualPaymentRequest
from app.services import payment_service
from app.services.payment.paystack import paystack_service
from app.services.email.sender import email_service
from app.services.pdf.invoice import invoice_pdf_service
router = APIRouter(tags=["Payments"])

@router.post("/fees/student/pay/{invoice_id}", dependencies=[Depends(get_current_student)])
async def initialize_payment(
    invoice_id: str,
    current_student: User = Depends(get_current_student),
    db: Session = Depends(get_session)
):
    invoice = db.get(Invoice, invoice_id)
    if not invoice or invoice.student_id != current_student.id:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    
    payment_ref = f"PAY-{invoice.invoice_number}-{str(uuid.uuid4())[:8]}"
    payment = Payment(invoice_id=invoice.id, paystack_reference=payment_ref, amount=invoice.balance_due, status=PaymentStatus.pending)
    db.add(payment)
    db.commit()
    
    response = paystack_service.initialize_transaction(
        email=current_student.email, amount=invoice.balance_due, reference=payment_ref,
        callback_url=None, # Frontend should provide this
        metadata={"payment_id": payment.id, "invoice_id": invoice.id}
    )
    return response

# PRESERVED: POST /fees/admin/manual-payment -> POST /payments/manual
@router.post("/fees/admin/manual-payment", dependencies=[Depends(get_current_admin)])
async def record_manual_payment(
    payment_data: ManualPaymentRequest,
    background_tasks: BackgroundTasks,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session)
):
    # FIX: Unpack the tuple returned by the service
    payment, invoice = payment_service.record_manual_payment(payment_data, current_admin, db)
    
    try:
        # FIX: Use the `invoice` object directly instead of `payment.invoice`
        student = db.get(User, invoice.student_id)
        if student and student.email:
            receipt_details = {
                'invoice_number': invoice.invoice_number,
                'amount_paid_this_time': payment.amount,
                'paid_amount': invoice.paid_amount,
                'balance_due': invoice.balance_due
            }
            pdf_buffer = invoice_pdf_service.generate_invoice_pdf(payment.invoice_id, db)
            
            background_tasks.add_task(
                email_service.send_payment_receipt_email,
                recipient_email=student.email,
                student_name=student.first_name,
                receipt_details=receipt_details,
                pdf_attachment_bytes=pdf_buffer.getvalue()
            )
    except Exception as e:
        # The error log is now more informative
        print(f"Failed to queue email receipt for manual payment {payment.id}. Error: {e}")

    return {"message": "Manual payment recorded successfully", "payment_id": payment.id}

# PRESERVED: POST /fees/webhooks/paystack-webhook -> POST /payments/webhooks/paystack
@router.post("/fees/webhooks/paystack")
async def paystack_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    if not paystack_service.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="Signature verification failed")
    
    event = json.loads(body)
    if event.get("event") == "charge.success":
        background_tasks.add_task(payment_service.process_successful_webhook_payment, event, db)

    return {"status": "success"}