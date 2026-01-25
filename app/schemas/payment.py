from app.models import PaymentMethod, PaymentStatus
from datetime import date, datetime
from pydantic import BaseModel
from typing import Optional

class ManualPaymentRequest(BaseModel):
    invoice_id: str
    amount: float
    payment_method: PaymentMethod
    receipt_number: Optional[str] = None
    notes: Optional[str] = None

class PaymentResponse(BaseModel):
    id: str
    reference: str
    invoice_number: str
    student_name: str
    amount: float
    status: PaymentStatus
    payment_method: Optional[str]
    paid_at: Optional[datetime]
    created_at: datetime
    invoice_id: str
    student_id: str