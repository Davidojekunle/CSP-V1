# app/schemas/fee.py
"""Pydantic schemas for Fee and Fee Assignment management."""
from pydantic import BaseModel
from typing import Optional, List
from app.models import FeeFrequency, TargetType
from datetime import date, datetime
from app.models import InvoiceStatus, InvoiceGenerationScope


# --- Fee Schemas ---
class FeeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    amount: float
    frequency: FeeFrequency

class FeeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    frequency: Optional[FeeFrequency] = None
    is_active: Optional[bool] = None

class FeeResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    amount: float
    currency: str
    frequency: FeeFrequency
    is_active: bool

# --- Fee Assignment Schemas ---
class FeeAssignmentCreate(BaseModel):
    fee_id: str
    session_id: str
    term_id: str
    target_type: TargetType
    target_id: Optional[str] = None # Class ID or Student ID


class InvoiceItemResponse(BaseModel):
    description: str
    amount: float

class PaymentInInvoiceResponse(BaseModel):
    id: str
    amount: float
    status: str
    paid_at: Optional[datetime]
    payment_method: Optional[str]

class InvoiceResponse(BaseModel):
    id: str
    invoice_number: str
    student_name: str
    session_name: str
    term_name: str
    status: InvoiceStatus
    due_date: date
    total_amount: float
    paid_amount: float
    balance_due: float
    items: List[InvoiceItemResponse]
    payments: List[PaymentInInvoiceResponse]

class PaginatedInvoiceResponse(BaseModel):
    total: int
    invoices: List[InvoiceResponse]
    has_more: bool

class InvoiceGenerateRequest(BaseModel):
    session_id: str
    term_id: str
    scope: InvoiceGenerationScope
    target_ids: Optional[List[str]] = None
    due_date: str # YYYY-MM-DD