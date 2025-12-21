# app/services/payment_service.py
"""High-level service for payment logic, including manual and webhook processing."""
import json
from typing import Dict
from sqlmodel import Session, select
from fastapi import HTTPException
from datetime import datetime

from app.models import Invoice, Payment, PaymentStatus, InvoiceStatus, User, PaymentMethod
from app.schemas.payment import ManualPaymentRequest
from app.services.payment.paystack import paystack_service
from app.services.email.sender import send_payment_receipt_email # Assuming this exists
from app.services.pdf.invoice import invoice_pdf_service
# Import your PDF service to attach receipts
# from app.services.pdf.invoice import invoice_pdf_service

def _update_payment_and_invoice(payment: Payment, verified_data: Dict, db: Session):
    """
    Updates a Payment record with verified data from Paystack and updates the
    corresponding Invoice. This function is the single source of truth for
    processing a successful payment.
    """
    # 1. Update the Payment object
    payment.status = PaymentStatus.successful
    payment.paystack_response = json.dumps(verified_data)
    payment.gateway_response = verified_data.get("gateway_response")
    
    # Safely get the payment channel/method
    channel = verified_data.get("channel")
    try:
        payment.payment_method = PaymentMethod(channel) if channel else None
    except ValueError:
        payment.payment_method = channel # Store as string if not a valid enum member
        
    payment.paid_at = datetime.utcnow()
    db.add(payment)

    # 2. Update the corresponding Invoice object
    invoice = db.get(Invoice, payment.invoice_id)
    if not invoice:
        print(f"CRITICAL ERROR: Invoice ID {payment.invoice_id} not found for payment {payment.id}")
        return

    invoice.paid_amount += payment.amount
    invoice.balance_due = invoice.total_amount - invoice.paid_amount

    # Use a small tolerance for floating point comparisons
    if invoice.balance_due <= 0.01:
        invoice.status = InvoiceStatus.paid
        invoice.balance_due = 0.0  # Normalize to zero
    else:
        invoice.status = InvoiceStatus.partial
        
    db.add(invoice)


async def process_successful_webhook_payment(webhook_data: dict, db: Session):
    """
    Processes a 'charge.success' event from a Paystack webhook.
    This is designed to be run in the background.
    """
    reference = webhook_data.get("data", {}).get("reference")
    if not reference:
        print(f"Webhook Error: No reference found.")
        return

    payment = db.exec(select(Payment).where(Payment.paystack_reference == reference)).first()
    if not payment or payment.status == PaymentStatus.successful:
        print(f"Webhook Info: Payment not found or already processed for reference {reference}.")
        return

    # Security: Always re-verify the transaction with Paystack's API
    verification = paystack_service.verify_transaction(reference)
    if not verification.get("status") or verification["data"]["status"] != "success":
        payment.status = PaymentStatus.failed
        db.add(payment)
        db.commit()
        return

    # Update payment and invoice records
    _update_payment_and_invoice(payment, verification["data"]["amount"] / 100, db)
    
    # --- Send Receipt Email ---
    # ... (Email sending logic would go here, called as a background task if possible)
    print(f"Webhook Success: Payment for {reference} processed.")


def record_manual_payment(payment_data: ManualPaymentRequest, admin_user: User, db: Session) -> tuple[Payment, Invoice]:
    """Records a manual (offline) payment made by an admin.
    
    Returns:
        A tuple containing the created Payment object and the updated Invoice object.
    """
    invoice = db.get(Invoice, payment_data.invoice_id)
    if not invoice or invoice.status in [InvoiceStatus.paid, InvoiceStatus.cancelled]:
        raise HTTPException(status_code=400, detail=f"Invoice is not available for payment (status: {invoice.status.value})")
    
    if payment_data.amount <= 0 or payment_data.amount > invoice.balance_due:
        raise HTTPException(status_code=400, detail="Invalid payment amount.")

    payment_reference = f"MANUAL_{payment_data.payment_method.value.upper()}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
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
    
    _update_invoice_status_from_payment(invoice, payment.amount, db)
    
    db.commit()
    db.refresh(payment)
    db.refresh(invoice) # Also refresh the invoice to get its latest state
    
    return payment, invoice

def _update_invoice_status_from_payment(invoice: Invoice, amount_paid: float, db: Session):
    """Helper to update an invoice's amounts and status after a payment."""
    invoice.paid_amount += amount_paid
    invoice.balance_due = invoice.total_amount - invoice.paid_amount
    
    if invoice.balance_due <= 0.01:
        invoice.status = InvoiceStatus.paid
        invoice.balance_due = 0.0
    else:
        invoice.status = InvoiceStatus.partial
    db.add(invoice)