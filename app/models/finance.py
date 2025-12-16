from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import date, datetime
import uuid

from app.models.base import (
    FeeFrequency, TargetType, InvoiceStatus,
    PaymentStatus, PaymentMethod
)


class Fee(SQLModel, table=True):
    __tablename__ = "fees"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    description: Optional[str] = None
    amount: float
    currency: str = Field(default="NGN")
    frequency: FeeFrequency
    is_active: bool = Field(default=True)


class FeeAssignment(SQLModel, table=True):
    __tablename__ = "fee_assignments"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    fee_id: str = Field(foreign_key="fees.id")
    session_id: str = Field(foreign_key="academic_sessions.id")
    term_id: str = Field(foreign_key="terms.id")
    target_type: TargetType
    target_id: Optional[str] = None


class Invoice(SQLModel, table=True):
    __tablename__ = "invoices"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    invoice_number: str = Field(unique=True)
    student_id: str = Field(foreign_key="users.id")
    session_id: str = Field(foreign_key="academic_sessions.id")
    term_id: str = Field(foreign_key="terms.id")
    status: InvoiceStatus = Field(default=InvoiceStatus.draft)
    due_date: date
    total_amount: float
    paid_amount: float = Field(default=0.0)
    balance_due: float
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class InvoiceItem(SQLModel, table=True):
    __tablename__ = "invoice_items"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    invoice_id: str = Field(foreign_key="invoices.id")
    fee_id: str = Field(foreign_key="fees.id")
    description: str
    amount: float
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class Payment(SQLModel, table=True):
    __tablename__ = "payments"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    invoice_id: str = Field(foreign_key="invoices.id")
    paystack_reference: str = Field(unique=True)
    amount: float
    status: PaymentStatus = Field(default=PaymentStatus.pending)
    payment_method: Optional[PaymentMethod] = None
    paystack_response: Optional[str] = None
    gateway_response: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)