# app/services/pdf/invoice.py
"""
Invoice PDF generation service.
PRESERVED: All PDF generation logic exactly as original.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.pdfgen import canvas as rl_canvas

from io import BytesIO
from datetime import datetime
from typing import Optional, Dict, Any
import os

# Optional image helper (Pillow)
try:
    from PIL import Image, ImageEnhance
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


def create_faded_logo(
    input_path: str,
    output_path: str,
    opacity: float = 0.08,
    max_size: int = 400
):
    """
    Create a faded PNG from input image. Saves to output_path.
    PRESERVED: Exact same logic as original.
    
    Args:
        input_path: Path to original logo
        output_path: Path to save faded logo
        opacity: 0.0 - 1.0 (0.08 is very faint)
        max_size: longest side in pixels (keeps aspect ratio)
    
    Requires Pillow (PIL).
    """
    if not PIL_AVAILABLE:
        raise RuntimeError(
            "Pillow is not installed. Install with `pip install pillow` to use create_faded_logo()."
        )

    img = Image.open(input_path).convert("RGBA")

    # Resize maintaining aspect ratio if larger than max_size
    w, h = img.size
    scale = 1.0
    if max(w, h) > max_size:
        scale = max_size / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # Create an alpha mask based on the requested opacity
    alpha = img.split()[3]
    alpha = alpha.point(lambda p: int(p * opacity))
    img.putalpha(alpha)

    # Save as PNG
    img.save(output_path, format="PNG")


class InvoicePDFGenerator:
    """
    Invoice PDF generator.
    PRESERVED: All styles and generation logic exactly as original.
    """
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()

    def setup_custom_styles(self):
        """Setup custom paragraph styles for the invoice"""
        self.styles.add(ParagraphStyle(
            name='SchoolHeader',
            fontSize=14,
            textColor=colors.black,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='InvoiceTitle',
            fontSize=12,
            textColor=colors.black,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold',
            spaceAfter=0.2 * inch
        ))

        self.styles.add(ParagraphStyle(
            name='StatusPaid',
            fontSize=10,
            textColor=colors.green,
            alignment=TA_RIGHT,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='SmallText',
            fontSize=8,
            textColor=colors.black,
            alignment=TA_LEFT
        ))

    def generate_invoice_pdf(
        self,
        invoice_data: Dict[str, Any],
        school_info: Optional[Dict[str, str]] = None,
        logo_path: Optional[str] = None,
        watermark_opacity: float = 0.08,
    ) -> BytesIO:
        """
        Generate invoice PDF.
        PRESERVED: Exact same generation logic and layout as original.
        
        Args:
            invoice_data: Invoice data dictionary
            school_info: School information (name, etc.)
            logo_path: Path to school logo for header and watermark
            watermark_opacity: Opacity for watermark (0.0-1.0)
            
        Returns:
            BytesIO buffer containing the PDF
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=0.5 * inch,
            leftMargin=0.5 * inch,
            topMargin=0.6 * inch,
            bottomMargin=0.5 * inch
        )

        # Prepare faded image for watermark fallback if needed
        faded_logo_path = None
        try:
            alpha_supported = hasattr(rl_canvas.Canvas, 'setFillAlpha')
        except Exception:
            alpha_supported = False

        if logo_path and (not alpha_supported):
            base, ext = os.path.splitext(logo_path)
            faded_logo_path = f"{base}.faded.png"
            if not os.path.exists(faded_logo_path):
                try:
                    create_faded_logo(
                        logo_path,
                        faded_logo_path,
                        opacity=watermark_opacity,
                        max_size=400
                    )
                except Exception:
                    faded_logo_path = None
            else:
                faded_logo_path = faded_logo_path

        watermark_image_path = logo_path if alpha_supported else faded_logo_path

        story = []

        # School Header
        school_name = (school_info or {}).get("name", "SCHOOL NAME")
        story.append(Paragraph(school_name.upper(), self.styles['SchoolHeader']))

        # Invoice title
        session_name = invoice_data.get('session_name', '')
        term_name = invoice_data.get('term_name', '')
        invoice_title_text = f"BILL RECEIPT - {session_name} {term_name.upper()} TERM"
        story.append(Paragraph(invoice_title_text, self.styles['InvoiceTitle']))
        story.append(Spacer(1, 0.18 * inch))

        # Student Info (include gender)
        gender_label = invoice_data.get('gender')
        if gender_label in ('M', 'male', 'Male'):
            gender_str = 'Male'
        elif gender_label in ('F', 'female', 'Female'):
            gender_str = 'Female'
        else:
            gender_str = str(gender_label or '')

        student_info_data = [
            ["NAME:", invoice_data.get('student_name', ''), 
             f"RECEIPT NO: {invoice_data.get('invoice_number','')}"],
            ["ADMISSION NO:", invoice_data.get('admission_number', ''), 
             f"RRR: {invoice_data.get('invoice_number','')[:12]}"],
            ["CLASS:", invoice_data.get('class_name', ''), 
             f"STATUS: {invoice_data.get('status','').upper()}"],
            ["GENDER:", gender_str, ""],
        ]

        student_info_table = Table(
            student_info_data,
            colWidths=[1.2 * inch, 3.8 * inch, 2.0 * inch]
        )
        student_info_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('GRID', (0, 0), (2, -1), 0.3, colors.HexColor('#E6E6E6')),
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(student_info_table)
        story.append(Spacer(1, 0.22 * inch))

        # Fees table
        fee_table_data = [['#', 'FEES', 'AMOUNT (NGN)']]
        for idx, item in enumerate(invoice_data.get('items', []), 1):
            fee_table_data.append([
                str(idx),
                item.get('description', '').upper(),
                f"{item.get('amount', 0):,.0f}"
            ])

        fee_table_data.append([
            '',
            'TOTAL',
            f"{invoice_data.get('total_amount', 0):,.0f}"
        ])

        fee_table = Table(
            fee_table_data,
            colWidths=[0.5 * inch, 5 * inch, 1.5 * inch]
        )
        fee_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
            ('ALIGN', (1, 0), (1, 0), 'LEFT'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -2), 0.3, colors.HexColor('#E6E6E6')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
        ]))
        story.append(fee_table)
        story.append(Spacer(1, 0.2 * inch))

        # Footer date
        footer_text = (
            f"Date Generated: "
            f"{datetime.now().strftime('%a, %b %d, %Y at %I:%M %p')}"
        )
        story.append(Paragraph(footer_text, self.styles['SmallText']))

        # onPage callback: draws logo + watermark
        def _on_page(canvas_obj: rl_canvas.Canvas, doc_obj):
            # Small header logo (top-left)
            if logo_path and os.path.exists(logo_path):
                try:
                    logo_w = 50
                    logo_h = 50
                    x = doc_obj.leftMargin
                    y = A4[1] - doc_obj.topMargin + 6
                    canvas_obj.drawImage(
                        logo_path, x, y,
                        width=logo_w, height=logo_h,
                        preserveAspectRatio=True, mask='auto'
                    )
                except Exception:
                    pass

            # Watermark (large, centered)
            if watermark_image_path and os.path.exists(watermark_image_path):
                try:
                    canvas_obj.saveState()
                    if alpha_supported:
                        try:
                            canvas_obj.setFillAlpha(watermark_opacity)
                        except Exception:
                            pass
                    
                    img_w = 320
                    img_h = 320
                    cx = (A4[0] - img_w) / 2
                    cy = (A4[1] - img_h) / 2
                    canvas_obj.drawImage(
                        watermark_image_path, cx, cy,
                        width=img_w, height=img_h,
                        preserveAspectRatio=True, mask='auto'
                    )
                    canvas_obj.restoreState()
                except Exception:
                    pass

        # Build doc with onPage callback
        doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
        buffer.seek(0)
        return buffer