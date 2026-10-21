# app/services/payment_service.py
"""High-level service for payment logic, including manual and webhook processing."""
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, List

import httpx
from fastapi import HTTPException
from sqlalchemy import or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.database import AsyncSessionFactory
from app.models import Invoice, Payment, PaymentStatus, InvoiceStatus, User, PaymentMethod
from app.schemas.payment import ManualPaymentRequest, PaymentInitializeRequest
from app.services.payment.paystack import paystack_service
from app.services.email.sender import send_payment_receipt_email
from app.services.pdf.invoice import invoice_pdf_service

logger = logging.getLogger(__name__)


def _parse_date(date_string: str):
    """Helper function to parse a date string into a datetime object."""
    return datetime.strptime(date_string, "%Y-%m-%d").date()


async def _get_invoice_for_update(invoice_id: str, db: AsyncSession) -> Optional[Invoice]:
    # Row lock on Postgres so concurrent payments can't lose an update to paid_amount
    return (await db.execute(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    )).scalars().first()


def _apply_payment_to_invoice(invoice: Invoice, amount_paid: float, db: AsyncSession):
    """Updates an invoice's amounts and status after a payment."""
    invoice.paid_amount += amount_paid
    invoice.balance_due = invoice.total_amount - invoice.paid_amount

    # Use a small tolerance for floating point comparisons
    if invoice.balance_due <= 0.01:
        invoice.status = InvoiceStatus.paid
        invoice.balance_due = 0.0  # Normalize to zero
    else:
        invoice.status = InvoiceStatus.partial
    invoice.updated_at = datetime.utcnow()
    db.add(invoice)


async def initialize_student_payment(
    invoice_id: str,
    payment_data: Optional[PaymentInitializeRequest],
    student: User,
    db: AsyncSession
) -> dict:
    """
    Handles all logic for initializing a student payment.
    1. Validates the invoice and amount.
    2. Creates a pending Payment record.
    3. Calls Paystack to get an authorization URL.
    4. Returns Paystack's response (plus our payment_id).
    """
    payment_data = payment_data or PaymentInitializeRequest()

    invoice = await db.get(Invoice, invoice_id)
    if not invoice or invoice.student_id != student.id:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    if invoice.status in [InvoiceStatus.paid, InvoiceStatus.cancelled]:
        raise HTTPException(status_code=400, detail=f"Invoice cannot be paid (status: {invoice.status.value})")

    # Determine payment amount
    amount = invoice.balance_due
    if payment_data.amount:
        if 0 < payment_data.amount <= invoice.balance_due:
            amount = payment_data.amount
        else:
            raise HTTPException(status_code=400, detail="Payment amount is invalid or exceeds balance due.")

    # Create pending payment record
    payment_ref = f"PAY_{invoice.invoice_number}_{str(uuid.uuid4())[:8].upper()}"
    payment = Payment(
        invoice_id=invoice.id, paystack_reference=payment_ref,
        amount=amount, status=PaymentStatus.pending
    )
    db.add(payment)
    await db.commit()

    response = None
    try:
        response = await paystack_service.initialize_transaction(
            email=student.email, amount=amount, reference=payment_ref,
            callback_url=payment_data.callback_url or settings.PAYSTACK_CALLBACK_URL,
            metadata={"payment_id": payment.id, "invoice_id": invoice.id}
        )
    except httpx.HTTPError as e:
        logger.error("Paystack initialize failed for %s: %s", payment_ref, e)

    if not response or not response.get("status"):
        payment.status = PaymentStatus.failed
        if response:
            payment.paystack_response = json.dumps(response)
        db.add(payment)
        await db.commit()
        raise HTTPException(status_code=502, detail="Failed to initialize payment with provider.")

    # Same shape the endpoint has always returned (Paystack's response), plus our payment id
    return {**response, "payment_id": payment.id}


async def process_successful_webhook_payment(webhook_data: dict):
    """
    Processes a 'charge.success' event from a Paystack webhook.
    Runs as a background task, so it opens its own database session
    (the request's session is closed by the time this runs).
    """
    reference = webhook_data.get("data", {}).get("reference")
    if not reference:
        logger.warning("Paystack webhook without a reference")
        return

    async with AsyncSessionFactory() as db:
        payment = (await db.execute(
            select(Payment).where(Payment.paystack_reference == reference).with_for_update()
        )).scalars().first()
        if not payment or payment.status == PaymentStatus.successful:
            logger.info("Webhook: payment not found or already processed for %s", reference)
            return

        # Security: Always re-verify the transaction with Paystack's API
        try:
            verification = await paystack_service.verify_transaction(reference)
        except httpx.HTTPError as e:
            # Leave it pending; Paystack retries webhooks that don't succeed
            logger.error("Paystack verify failed for %s: %s", reference, e)
            raise

        data = verification.get("data") or {}
        expected_kobo = int(round(payment.amount * 100))
        if not verification.get("status") or data.get("status") != "success" or data.get("amount") != expected_kobo:
            logger.warning("Webhook: verification failed for %s (status=%s, amount=%s, expected=%s)",
                           reference, data.get("status"), data.get("amount"), expected_kobo)
            payment.status = PaymentStatus.failed
            payment.paystack_response = json.dumps(verification)
            db.add(payment)
            await db.commit()
            return

        # 1. Update the Payment object
        payment.status = PaymentStatus.successful
        payment.paystack_response = json.dumps(data)
        payment.gateway_response = data.get("gateway_response")
        channel = data.get("channel")
        try:
            payment.payment_method = PaymentMethod(channel) if channel else None
        except ValueError:
            payment.payment_method = None  # Unknown channel; raw value is kept in paystack_response
        payment.paid_at = datetime.utcnow()
        payment.updated_at = datetime.utcnow()
        db.add(payment)

        # 2. Update the corresponding Invoice object
        invoice = await _get_invoice_for_update(payment.invoice_id, db)
        if not invoice:
            logger.critical("Invoice %s not found for payment %s", payment.invoice_id, payment.id)
            await db.commit()
            return
        _apply_payment_to_invoice(invoice, payment.amount, db)
        await db.commit()
        logger.info("Webhook: payment %s processed", reference)

        # 3. Send receipt
        try:
            student = await db.get(User, invoice.student_id)
            if student and student.email:
                pdf_buffer = await invoice_pdf_service.generate_invoice_pdf(invoice.id, db)
                await send_payment_receipt_email(
                    recipient_email=student.email,
                    student_name=student.first_name,
                    receipt_details={
                        'invoice_number': invoice.invoice_number,
                        'amount_paid_this_time': payment.amount,
                        'paid_amount': invoice.paid_amount,
                        'balance_due': invoice.balance_due
                    },
                    pdf_attachment_bytes=pdf_buffer.getvalue()
                )
        except Exception:
            logger.exception("Failed to send receipt for payment %s", reference)


async def record_manual_payment(payment_data: ManualPaymentRequest, admin_user: User, db: AsyncSession) -> tuple[Payment, Invoice]:
    """Records a manual (offline) payment made by an admin.

    Returns:
        A tuple containing the created Payment object and the updated Invoice object.
    """
    invoice = await _get_invoice_for_update(payment_data.invoice_id, db)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if invoice.status in [InvoiceStatus.paid, InvoiceStatus.cancelled]:
        raise HTTPException(status_code=400, detail=f"Invoice is not available for payment (status: {invoice.status.value})")

    if payment_data.amount <= 0 or payment_data.amount > invoice.balance_due:
        raise HTTPException(status_code=400, detail="Invalid payment amount.")

    # Suffix keeps references unique when two payments are recorded in the same second
    payment_reference = (
        f"MANUAL_{payment_data.payment_method.value.upper()}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        f"_{uuid.uuid4().hex[:6].upper()}"
    )

    payment = Payment(
        invoice_id=invoice.id,
        paystack_reference=payment_reference,
        amount=payment_data.amount,
        status=PaymentStatus.successful,
        payment_method=payment_data.payment_method,
        paid_at=datetime.utcnow(),
        paystack_response=json.dumps({"manual": True, "notes": payment_data.notes, "recorded_by": admin_user.id})
    )
    db.add(payment)
    _apply_payment_to_invoice(invoice, payment.amount, db)
    await db.commit()

    return payment, invoice


async def get_all_payments(
    db: AsyncSession,
    skip: int,
    limit: int,
    status: Optional[PaymentStatus],
    search: Optional[str],
    payment_method: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str]
) -> List[Payment]:
    """
    Fetches a list of all payments with comprehensive filtering
    using a single JOIN query.
    """
    query = (
        select(Payment)
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .join(User, Invoice.student_id == User.id)
    )

    conditions = []
    if status: conditions.append(Payment.status == status)
    if payment_method: conditions.append(Payment.payment_method == payment_method)

    if search:
        term = f"%{search.strip()}%"
        conditions.append(or_(
            Payment.paystack_reference.ilike(term),
            Invoice.invoice_number.ilike(term),
            User.first_name.ilike(term),
            User.last_name.ilike(term),
            (User.first_name + ' ' + User.last_name).ilike(term)
        ))

    if date_from:
        conditions.append(func.date(Payment.created_at) >= _parse_date(date_from))
    if date_to:
        conditions.append(func.date(Payment.created_at) <= _parse_date(date_to))

    if conditions:
        query = query.where(and_(*conditions))

    return (await db.execute(
        query.order_by(Payment.created_at.desc(), Payment.id).offset(skip).limit(limit)
    )).scalars().all()


async def get_student_payment_history(student_user: User, db: AsyncSession) -> List[dict]:
    """
    Fetches all successful payments for a student in one query.
    """
    query = (
        select(Payment)
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .where(
            Invoice.student_id == student_user.id,
            Payment.status == PaymentStatus.successful
        )
        .order_by(Payment.paid_at.desc())
    )

    successful_payments = (await db.execute(query)).scalars().all()

    return [
        {
            "payment_id": p.id,
            "reference": p.paystack_reference,
            "amount": p.amount,
            "paid_at": p.paid_at,
            "invoice_id": p.invoice_id
        }
        for p in successful_payments
    ]
