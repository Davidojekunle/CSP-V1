# app/services/pdf/invoice.py
"""
Service for orchestrating the generation of Invoice PDFs.
"""
from sqlmodel import select, and_
from io import BytesIO
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pdf.generator import SchoolReportGenerator # Assuming a generic generator, can be specified
from app.models import Invoice, InvoiceItem, Payment, User, StudentProfile, AcademicSession, Term, Enrollment, Class

class InvoicePDFService:
    def __init__(self):
        # We can create a more specific PDF generator for invoices if needed
        self.generator = SchoolReportGenerator() # Re-using for now

    async def _get_invoice_data(self, invoice_id: str, db: AsyncSession) -> dict:
        """Gathers all necessary data for rendering an invoice PDF."""
        invoice = await db.get(Invoice, invoice_id)
        if not invoice:
            return None

        student = await db.get(User, invoice.student_id)
        profile = (await db.execute(select(StudentProfile).where(StudentProfile.user_id == invoice.student_id))).scalars().first()
        ac_session = await db.get(AcademicSession, invoice.session_id)
        term = await db.get(Term, invoice.term_id)
        
        enrollment = (await db.execute(select(Enrollment).where(
            Enrollment.student_id == invoice.student_id,
            Enrollment.session_id == invoice.session_id,
        ))).scalars().first()
        class_obj = await db.get(Class, enrollment.class_id) if enrollment else None

        items = (await db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))).scalars().all()
        payments = (await db.execute(select(Payment).where(Payment.invoice_id == invoice.id, Payment.status == "successful"))).scalars().all()

        return {
            "invoice_number": invoice.invoice_number,
            "student_name": f"{student.first_name} {student.last_name}",
            "admission_number": profile.admission_number if profile else "N/A",
            "class_name": class_obj.name if class_obj else "N/A",
            "session_name": ac_session.name,
            "term_name": term.name.value,
            "created_at": invoice.created_at.strftime('%Y-%m-%d'),
            "due_date": invoice.due_date.strftime('%Y-%m-%d'),
            "total_amount": invoice.total_amount,
            "paid_amount": invoice.paid_amount,
            "balance_due": invoice.balance_due,
            "status": invoice.status.value,
            "items": [{"description": i.description, "amount": i.amount} for i in items],
            "payments": [{
                "amount": p.amount, "status": p.status.value,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                "payment_method": p.payment_method.value if p.payment_method else "N/A"
            } for p in payments]
        }
        
    async def generate_invoice_pdf(self, invoice_id: str, db: AsyncSession) -> BytesIO:
        """Generates the invoice PDF and returns it as an in-memory BytesIO buffer."""
        invoice_data = await self._get_invoice_data(invoice_id, db)
        if not invoice_data:
            raise ValueError("Could not find data for the specified invoice.")

        # This assumes your generator has a method for invoices.
        # If not, you'd create one in generator.py similar to the report card method.
        # For now, we'll simulate it.
        
        # return self.generator.generate_invoice_pdf(invoice_data) # Ideal case
        
        # --- Placeholder PDF generation ---
        from reportlab.platypus import SimpleDocTemplate, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer)
        styles = getSampleStyleSheet()
        story = [Paragraph(f"Invoice: {invoice_data['invoice_number']}", styles['h1']),
                 Paragraph(f"Student: {invoice_data['student_name']}", styles['Normal']),
                 Paragraph(f"Balance Due: NGN {invoice_data['balance_due']}", styles['Normal'])]
        doc.build(story)
        buffer.seek(0)
        return buffer

# Create a singleton instance
invoice_pdf_service = InvoicePDFService()