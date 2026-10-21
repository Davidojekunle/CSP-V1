# app/api/v1/payments.py
"""API routes for payment processing."""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.auth import get_current_admin, get_current_student
from app.models import User
from app.schemas.payment import ManualPaymentRequest, PaymentInitializeRequest
from app.services import payment_service
from app.services.payment.paystack import paystack_service
from app.services.email.sender import email_service
from app.services.pdf.invoice import invoice_pdf_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Payments"])


@router.post("/fees/student/pay/{invoice_id}")
async def initialize_payment(
    invoice_id: str,
    payment_data: Optional[PaymentInitializeRequest] = None,
    current_student: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_session)
):
    """
    Initializes a Paystack payment for a specific invoice.
    The body is optional: without it the full balance is charged.
    """
    return await payment_service.initialize_student_payment(
        invoice_id=invoice_id,
        payment_data=payment_data,
        student=current_student,
        db=db
    )


@router.post("/fees/admin/manual-payment")
async def record_manual_payment(
    payment_data: ManualPaymentRequest,
    background_tasks: BackgroundTasks,
    current_admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session)
):
    payment, invoice = await payment_service.record_manual_payment(payment_data, current_admin, db)

    try:
        student = await db.get(User, invoice.student_id)
        if student and student.email:
            receipt_details = {
                'invoice_number': invoice.invoice_number,
                'amount_paid_this_time': payment.amount,
                'paid_amount': invoice.paid_amount,
                'balance_due': invoice.balance_due
            }
            pdf_buffer = await invoice_pdf_service.generate_invoice_pdf(payment.invoice_id, db)

            background_tasks.add_task(
                email_service.send_payment_receipt_email,
                recipient_email=student.email,
                student_name=student.first_name,
                receipt_details=receipt_details,
                pdf_attachment_bytes=pdf_buffer.getvalue()
            )
    except Exception:
        logger.exception("Failed to queue email receipt for manual payment %s", payment.id)

    return {"message": "Manual payment recorded successfully", "payment_id": payment.id}


@router.post("/fees/admin/verify-payment/{payment_id}")
async def verify_payment(payment_id: str, current_admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_session)):
    """Re-check a pending Paystack payment directly with Paystack."""
    return await payment_service.verify_pending_payment(payment_id, db)


@router.post("/fees/webhooks/paystack")
async def paystack_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    if not paystack_service.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="Signature verification failed")

    event = json.loads(body)
    if event.get("event") == "charge.success":
        background_tasks.add_task(payment_service.process_successful_webhook_payment, event)
    return {"status": "success"}
