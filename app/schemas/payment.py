from app.models import PaymentMethod
from pydantic import BaseModel
from typing import Optional

class ManualPaymentRequest(BaseModel):
    invoice_id: str
    amount: float
    payment_method: PaymentMethod
    receipt_number: Optional[str] = None
    notes: Optional[str] = None