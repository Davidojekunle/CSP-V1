# app/services/pdf/generator.py
"""
Contains the low-level PDF generation class using ReportLab.
This class should only be concerned with drawing data onto a PDF canvas.
"""
from fastapi import HTTPException, status    
from app.models import TermName, FormTeacherRemark, User, UserRole, Term, StudentProfile, AcademicSession, Class, Result, Enrollment, Subject
from app.utils.grade_calculator import calculate_detailed_grade
# ... etc.
from sqlmodel import Session, select, and_
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
from io import BytesIO
import zipfile
import re
from collections import defaultdict
from collections import Counter

from reportlab.lib import colors
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.pagesizes import landscape, A4 #<-- Import landscape
from reportlab.lib.utils import ImageReader


import os
from io import BytesIO

# ... etc.

class SchoolReportGenerator:
    """Handles the low-level creation of PDF documents for student reports."""
    
    def __init__(self, school_name="GOD'S VISION MODEL COLLEGE"):
        self.school_name = school_name
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
    
    def setup_custom_styles(self):
        # Main Headers
        self.styles.add(ParagraphStyle(name='SchoolHeader', fontSize=18, fontName='Helvetica-Bold', textColor=colors.HexColor("#000080"), alignment=TA_CENTER, spaceAfter=6))
        self.styles.add(ParagraphStyle(name='ReportTitle', fontSize=12, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=12)) # ADJUSTED: Slightly less space after
        self.styles.add(ParagraphStyle(name='StudentName', fontSize=14, fontName='Helvetica-Bold', alignment=TA_LEFT, spaceAfter=8))
        
        # Info text inside boxes
        self.styles.add(ParagraphStyle(name='InfoValue', fontSize=9, fontName='Helvetica', alignment=TA_LEFT, leading=12)) # ADJUSTED: Slightly larger font and leading for readability
        
        # Footer/Analytics text
        self.styles.add(ParagraphStyle(name='AnalyticsHeader', fontSize=9, fontName='Helvetica-Bold', alignment=TA_LEFT, spaceBefore=4, leading=12))
        self.styles.add(ParagraphStyle(name='FooterText', fontSize=8, fontName='Helvetica', leading=10))

    def _get_logo_and_photo(self, photo_url: str):
        # ADJUSTED: Logo size reduced for a more compact header
        logo_path = os.path.join("school_logo.png") # Make sure you have this file
        if os.path.exists(logo_path):
            logo = Image(logo_path, width=1.2*inch, height=1.2*inch)
        else:
            logo = Spacer(1.2*inch, 1.2*inch) 
            print("Warning: school_logo.png not found.")

        # Student photo logic remains the same
        photo = None
        if photo_url:
            try:
                # Use a placeholder if URL fails
                photo = Image(ImageReader(photo_url), width=1*inch, height=1*inch)
            except Exception as e:
                print(f"Warning: Could not load student photo from URL {photo_url}. Error: {e}")
                photo = None

        if not photo:
            placeholder_path = os.path.join("Placeholder-passport.png") # Make sure you have this file
            if os.path.exists(placeholder_path):
                photo = Image(placeholder_path, width=1*inch, height=1*inch)
            else:
                photo = Spacer(1*inch, 1*inch)
        
        return logo, photo

    def _draw_watermark(self, canvas, doc):
        canvas.saveState()
        watermark_path = os.path.join("school_logo.png")
        if not os.path.exists(watermark_path):
            canvas.restoreState()
            return

        canvas.setStrokeAlpha(0.1)
        canvas.setFillAlpha(0.1)
        img_width, img_height = 10*inch, 10*inch # ADJUSTED: Watermark slightly smaller
        page_width, page_height = doc.pagesize
        x_centered = (page_width - img_width) / 2
        y_centered = (page_height - img_height) / 2
        canvas.drawImage(watermark_path, x_centered, y_centered, width=img_width, height=img_height, mask='auto')
        canvas.restoreState()

    # In your SchoolReportGenerator class

    # In your SchoolReportGenerator class

    def generate_detailed_report_card(self, student_data, results_data, session_info, summary_data, form_teacher_remark, class_obj):
        buffer = BytesIO()
        
        page_width, page_height = A4
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []

        # --- Header Block (with Side Logo) ---
        logo, photo = self._get_logo_and_photo(student_data.get('profile_picture_url'))
        
        report_title_str = f"{class_obj.level.upper() if class_obj and class_obj.level else ''}{class_obj.arm.upper() if class_obj and class_obj.arm else ''} - {session_info['term_name'].upper()} TERM {session_info['session_name']} REPORT SHEET"
    
        header_text_content = f"""
        <para align=center>
            <font size={self.styles['SchoolHeader'].fontSize}><b>{self.school_name}</b></font><br/><br/>
            <font size={self.styles['ReportTitle'].fontSize}><b>{report_title_str}</b></font>
        </para>
        """
        header_text_para = Paragraph(header_text_content, self.styles['Normal'])
        
        header_table = Table([
            [logo, header_text_para]
        ], colWidths=[1.5*inch, (page_width - 1*inch - 1.5*inch)])
        
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ]))
        
        elements.append(header_table)
        elements.append(Spacer(1, 0.2*inch))


        # --- Student Info Block (No changes) ---
        student_name_para = Paragraph(student_data['student_name'].upper(), self.styles['StudentName'])
        info_col1_text = f"USERNAME: {student_data['username']}<br/>GENDER: {student_data['gender']}<br/>EMAIL: {student_data['email']}<br/>PHONE: {student_data['phone']}"
        info_col2_text = f"POSITION: {summary_data['class_position']}<br/>NO. IN CLASS: {summary_data['total_students']} Students<br/>NEXT TERM BEGINS: {session_info['next_term_begins']}<br/>NEXT TERM ENDS: {session_info['next_term_ends']}"
        info_col1 = Paragraph(info_col1_text, self.styles['InfoValue'])
        info_col2 = Paragraph(info_col2_text, self.styles['InfoValue'])
        info_table = Table([[student_name_para], [info_col1, info_col2, photo]], colWidths=[3.0*inch, 3.0*inch, 1.3*inch], rowHeights=[0.4*inch, 1.1*inch])
        info_table.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 1, colors.black), ('SPAN', (0, 0), (-1, 0)), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOX', (2, 1), (2, 1), 1, colors.black), ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6), ('TOPPADDING', (0,0), (-1,-1), 6)]))
        elements.append(info_table)
        elements.append(Spacer(1, 0.15*inch))

        # --- Academic Performance Table (No changes) ---
        num_subjects = len(results_data)
        SUBJECT_THRESHOLD = 18
        if num_subjects > SUBJECT_THRESHOLD:
            cell_font_size, cell_leading, cell_padding, header_font_size = 7, 9, 2, 7
        else:
            cell_font_size, cell_leading, cell_padding, header_font_size = 8, 10, 3, 8
        table_header = ['S/N', 'SUBJECT', 'CA1', 'CA2', 'EXAM', 'TOTAL', 'GRADE', 'CLASS AVG', 'POS.', 'REMARK']
        table_data = [table_header]
        compact_text_style = ParagraphStyle(name='CompactPara', fontSize=cell_font_size, fontName='Helvetica', leading=cell_leading)
        for i, res in enumerate(results_data, 1):
            subject_cell = Paragraph(res['subject_name'], compact_text_style)
            remark_cell = Paragraph(res.get('remark', '-'), compact_text_style)
            table_data.append([str(i), subject_cell, res.get('ca1', '-'), res.get('ca2', '-'), res.get('exam', '-'), res.get('total', '-'), res.get('grade', '-'), f"{res.get('class_average', 0.0):.1f}", res.get('subject_position', 'N/A'), remark_cell])
        col_widths = [0.3*inch, 1.8*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.7*inch, 0.5*inch, 1.0*inch]
        grades_table = Table(table_data, colWidths=col_widths)
        grades_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#006400")), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, 0), header_font_size), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (1, 1), (1, -1), 'LEFT'), ('FONTSIZE', (2, 1), (-1, -1), cell_font_size), ('TOPPADDING', (0, 0), (-1, -1), cell_padding), ('BOTTOMPADDING', (0, 0), (-1, -1), cell_padding), ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.black), ('BOX', (0, 0), (-1, -1), 0.25, colors.black), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#E6F3E6")])]))
        elements.append(grades_table)
        elements.append(Spacer(1, 0.15*inch))
        
        # --- Analytics and Remarks Section (FIXED) ---
        
        # FIX: Changed summary_data['summary'] to summary_data['grades_summary']
        grades_summary_para = Paragraph(f"<b>GRADES SUMMARY:</b> {summary_data['grades_summary']}", self.styles['AnalyticsHeader'])
        
        average_score_para = Paragraph(f"<b>AVERAGE SCORE:</b> {summary_data['overall_average']:.1f}", self.styles['AnalyticsHeader'])
        key_to_grades_para = Paragraph("<b>KEY TO GRADES:</b> A1: 75% and Above | B2: 70% - 74% | B3: 65% - 69% | C4: 60% - 64% | C5: 55% - 59% | C6: 50% - 54% | F9: 49% and Below", self.styles['FooterText'])
        teacher_remark_para = Paragraph(f"<b>FORM TEACHER'S REMARK:</b> {form_teacher_remark}", self.styles['AnalyticsHeader'])
        analytics_table = Table([[grades_summary_para, average_score_para], [key_to_grades_para], [teacher_remark_para]], colWidths=[4.5*inch, 2.8*inch])
        analytics_table.setStyle(TableStyle([('SPAN', (0, 1), (1, 1)), ('SPAN', (0, 2), (1, 2)), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 0), ('BOTTOMPADDING', (0,0), (-1,-1), 0)]))
        elements.append(analytics_table)

        doc.build(elements, onFirstPage=self._draw_watermark, onLaterPages=self._draw_watermark)
        buffer.seek(0)
        return buffer

        
    def generate_final_cumulative_report_card(self, student_data, session_info, results_data, overall_average, form_teacher_remark, principal_remark, principal_info, grades_summary, class_obj):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=0.4*inch, leftMargin=0.4*inch, topMargin=0.4*inch, bottomMargin=0.4*inch)
        elements = []

        # --- 1. Header and Student Info ---
        logo, photo = self._get_logo_and_photo(student_data.get('profile_picture_url'))
        header_table = Table([[logo, Paragraph(self.school_name, self.styles['SchoolHeader']), ""]], colWidths=[1*inch, 8*inch, 1*inch])
        header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        elements.append(header_table)
        report_title_str = f"{session_info['class_name'].upper()} - {session_info['session_name']} SESSION CUMULATIVE REPORT SHEET"
        elements.append(Paragraph(report_title_str, self.styles['ReportTitle']))
        student_name_para = Paragraph(student_data['student_name'].upper(), self.styles['StudentName'])
        info_col1 = [Paragraph(f"USERNAME: {student_data['username']}", self.styles['InfoValue']), Paragraph(f"GENDER: {student_data['gender']}", self.styles['InfoValue'])]
        info_col2 = [Paragraph(f"EMAIL: {student_data['email']}", self.styles['InfoValue']), Paragraph(f"PHONE: {student_data['phone']}", self.styles['InfoValue'])]
        info_table = Table([[student_name_para, "", ""], [info_col1, info_col2, photo]], colWidths=[4*inch, 4*inch, 1.2*inch], rowHeights=[0.5*inch, 0.6*inch])
        info_table.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 1, colors.black), ('LINEAFTER', (0, 1), (0, -1), 1, colors.black), ('SPAN', (0, 0), (2, 0)), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOX', (2, 1), (2, 1), 1, colors.black), ('LEFTPADDING', (0,0), (-1,-1), 0)]))
        elements.append(info_table)
        elements.append(Spacer(1, 0.2*inch))

        # --- 2. Main Academic Performance Table ---
        table_header = ['S/N', 'SUBJECT', 'CA1', 'CA2', 'EXAM', 'TOTAL', '1ST\nTERM', '2ND\nTERM', '3RD\nTERM', 'CUM.\nAVG', 'GRADE', 'CLASS\nAVG', 'SUB.\nPOS', 'REMARK']
        table_data = [table_header]
        small_text_style = ParagraphStyle(name='SmallPara', fontSize=8, fontName='Helvetica', leading=10)
        for i, res in enumerate(results_data, 1):
            subject_cell = Paragraph(res['subject_name'], small_text_style)
            remark_cell = Paragraph(calculate_detailed_grade(res['total'])[1] if res.get('total') != '-' else '-', small_text_style)
            table_data.append([str(i), subject_cell, res.get('ca1', '-'), res.get('ca2', '-'), res.get('exam', '-'), res.get('total', '-'), f"{res[TermName.first] * 0.2:.1f}", f"{res[TermName.second] * 0.3:.1f}", f"{res[TermName.third] * 0.5:.1f}", f"{res.get('cumulative_total', 0):.1f}", res.get('final_grade', '-'), f"{res.get('class_average', 0.0):.1f}", res.get('subject_position', 'N/A'), remark_cell])
        col_widths = [0.3*inch, None, 0.4*inch, 0.4*inch, 0.4*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.5*inch, 1*inch]
        grades_table = Table(table_data, colWidths=col_widths)
        grades_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#006400")), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, 0), 7), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (1, 1), (1, -1), 'LEFT'), ('ALIGN', (-1, 1), (-1, -1), 'LEFT'), ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.black), ('BOX', (0, 0), (-1, -1), 0.25, colors.black), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#E6F3E6")])]))
        elements.append(grades_table)
        elements.append(Spacer(1, 0.1*inch))
        
        # --- 3. Analytics and Remarks ---
        key_to_grades = "<b>KEY TO GRADES:</b>   A1: 75% and Above | B2: 70% - 74% | B3: 65% - 69% | C4: 60% - 64% | C5: 55% - 59% | C6: 50% - 54% | F9: 49% and Below"
        analytics_table = Table([[Paragraph(f"<b>GRADES SUMMARY:</b> {grades_summary}", self.styles['AnalyticsHeader']), Paragraph(f"<b>CUMULATIVE AVERAGE SCORE:</b> {overall_average:.1f}", self.styles['AnalyticsHeader'])], [Paragraph(key_to_grades, self.styles['FooterText'])], [Paragraph(f"<b>Form Teacher's Remark:</b> {form_teacher_remark}", self.styles['AnalyticsHeader']), Paragraph(f"<b>Principal's Remark:</b> {principal_remark}", self.styles['AnalyticsHeader'])]], colWidths=[5.5*inch, 5.5*inch])
        analytics_table.setStyle(TableStyle([('SPAN', (0, 1), (1, 1)), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 0)]))
        elements.append(analytics_table)
        elements.append(Spacer(1, 0.2*inch))

        # --- 4. Signature Block ---
        signature_path = os.path.join("principal_signature.png")
        signature_img = Spacer(1.5*inch, 0.6*inch)
        if os.path.exists(signature_path):
            signature_img = Image(signature_path, width=1.5*inch, height=0.6*inch)
        principal_name_para = Paragraph(principal_info['name'], self.styles['InfoValue'])
        principal_title_para = Paragraph(principal_info['title'], self.styles['InfoValue'])
        signature_table = Table([[signature_img], [principal_name_para], [principal_title_para]], colWidths=[3*inch])
        signature_table.setStyle(TableStyle([('ALIGN', (0,0), (0,0), 'LEFT'), ('LEFTPADDING', (0,0), (-1,-1), 0)]))
        elements.append(signature_table)

        doc.build(elements, onFirstPage=self._draw_watermark, onLaterPages=self._draw_watermark)
        buffer.seek(0)
        return buffer
    def generate_student_report_card(self, student_data, results_data, session_info, form_teacher_remark: str):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=inch, leftMargin=inch, topMargin=inch, bottomMargin=inch)
        elements = []
        self._add_header_and_student_info(elements, "STUDENT REPORT CARD", student_data, session_info)
        elements.append(Paragraph("ACADEMIC PERFORMANCE", self.styles['GradeHeader']))
        table_data = [['Subject', 'CA1', 'CA2', 'Exam', 'Total', 'Grade', 'Remark']]
        total_score, count = 0, 0
        for res in results_data['subjects']:
            table_data.append([res['subject_name'], res['ca1'] or '-', res['ca2'] or '-', res['exam'] or '-', res['total'] or '-', res['grade_letter'] or '-', res['remark'] or '-'])
            if res['total'] is not None:
                total_score += res['total']
                count += 1
        average = total_score / count if count else 0
        table = Table(table_data, colWidths=[2.5*inch, 0.6*inch, 0.6*inch, 0.6*inch, 0.6*inch, 0.6*inch, 1.3*inch])
        table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.darkblue), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('ALIGN', (1, 0), (-1, -1), 'CENTER'), ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.black), ('BOX', (0, 0), (-1, -1), 0.25, colors.black), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])]))
        elements.append(table)
        elements.append(Paragraph(f"<b>Term Average:</b> {average:.2f}%", self.styles['Normal']))
        elements.append(Paragraph("FORM TEACHER'S REMARK", self.styles['GradeHeader']))
        elements.append(Paragraph(form_teacher_remark, self.styles['Normal']))
        doc.build(elements)
        buffer.seek(0)
        return buffer

    # services/pdf_service.py -> class PDFReportService

    def _get_student_cumulative_session_data(self, student_id: str, session_id: str, db_session: Session, user_role: UserRole):
        # --- Step 1 & 2: Base Info & Security Check (No Changes) ---
        student = db_session.get(User, student_id)
        if not student: raise HTTPException(status_code=404, detail="Student not found")
        student_profile = db_session.exec(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
        academic_session = db_session.get(AcademicSession, session_id)
        if not academic_session: raise HTTPException(status_code=404, detail="Academic session not found")
        
        terms_in_session = db_session.exec(select(Term).where(Term.session_id == session_id)).all()
        term_map = {term.name: term for term in terms_in_session}
        if not all(t in term_map for t in [TermName.first, TermName.second, TermName.third]):
            raise HTTPException(status_code=400, detail="All three terms are required to generate a cumulative report.")
        
        # --- AFTER ---
        third_term_obj = term_map[TermName.third] # We still need this for later use

        # The query is now based on the session_id and checks if the enrollment is active
        enrollment = db_session.exec(select(Enrollment).where(and_(
            Enrollment.student_id == student_id,
            Enrollment.session_id == session_id
        ))).first()

        if not enrollment:
            # The error message is now more accurate
            raise HTTPException(status_code=404, detail="Active student enrollment for this session not found.")

        class_obj = db_session.get(Class, enrollment.class_id)

        if user_role == UserRole.student:
            third_term_published_check = db_session.exec(select(Result).where(and_(Result.student_id == student_id, Result.term_id == third_term_obj.id, Result.is_published == True))).first()
            if not third_term_published_check:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cumulative report is not available until Third Term results are published.")

        # --- Step 3 & 4: Fetch Results & Calculate Ranks (No Changes) ---
        student_session_results = db_session.exec(select(Result).where(and_(Result.student_id == student_id, Result.session_id == session_id))).all()
        all_class_third_term_results = db_session.exec(select(Result).where(and_(Result.class_id == class_obj.id, Result.term_id == third_term_obj.id))).all()

        results_by_subject = defaultdict(list)
        for res in all_class_third_term_results:
            if res.total is not None:
                results_by_subject[res.subject_id].append({'student_id': res.student_id, 'total': res.total})
        
        subject_averages = {sub_id: sum(s['total'] for s in scores) / len(scores) for sub_id, scores in results_by_subject.items() if scores}
        subject_ranks = defaultdict(dict)
        for sub_id, scores in results_by_subject.items():
            sorted_scores = sorted(scores, key=lambda x: x['total'], reverse=True)
            for rank, score_data in enumerate(sorted_scores, 1):
                suf = 'th' if 11 <= rank <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')
                subject_ranks[sub_id][score_data['student_id']] = f"{rank}{suf}"

        # --- Step 5: Process Student's Data into Final Structure ---
        subjects_data = {}
        term_id_to_name_map = {term.id: term.name for term in terms_in_session}
        for res in student_session_results:
            if res.subject_id not in subjects_data:
                subject_obj = db_session.get(Subject, res.subject_id)
                # --- FIX: Initialize all keys with default values ---
                subjects_data[res.subject_id] = {
                    "subject_name": subject_obj.name, 
                    TermName.first: 0.0, TermName.second: 0.0, TermName.third: 0.0,
                    'ca1': '-', 'ca2': '-', 'exam': '-', 'total': '-' # Add placeholders
                }
            
            term_name = term_id_to_name_map.get(res.term_id)
            if term_name and res.total is not None:
                subjects_data[res.subject_id][term_name] = res.total
            
            if res.term_id == third_term_obj.id:
                subjects_data[res.subject_id]['ca1'] = res.ca1 if res.ca1 is not None else '-'
                subjects_data[res.subject_id]['ca2'] = res.ca2 if res.ca2 is not None else '-'
                subjects_data[res.subject_id]['exam'] = res.exam if res.exam is not None else '-'
                subjects_data[res.subject_id]['total'] = res.total if res.total is not None else '-'

        # --- Step 6: Final Calculations & Remarks (with small improvements) ---
        final_cumulative_results = []
        total_of_cumulative_scores = 0.0
        for subject_id, subject_info in subjects_data.items():
            cumulative_total = (subject_info[TermName.first] * 0.20) + (subject_info[TermName.second] * 0.30) + (subject_info[TermName.third] * 0.50)
            final_grade, _ = calculate_detailed_grade(cumulative_total)
            total_of_cumulative_scores += cumulative_total
            
            final_cumulative_results.append({
                **subject_info,
                "cumulative_total": cumulative_total,
                "final_grade": final_grade,
                "class_average": subject_averages.get(subject_id, 0.0),
                "subject_position": subject_ranks.get(subject_id, {}).get(student_id, 'N/A')
            })

        overall_cumulative_average = total_of_cumulative_scores / len(final_cumulative_results) if final_cumulative_results else 0.0
        remark_obj = db_session.exec(select(FormTeacherRemark).where(and_(FormTeacherRemark.student_id == student_id, FormTeacherRemark.term_id == third_term_obj.id))).first()
        form_teacher_remark = remark_obj.remark_text if remark_obj else "No final remark provided."

        principal_remark = "Graduated"
        current_class_name = class_obj.name.upper()
        if "SS3" in current_class_name:
            principal_remark = "Graduated and certified."
        elif "JSS3" in current_class_name:
            principal_remark = "Promoted to SS1"
        else:
            match = re.search(r'\d+', current_class_name)
            if match:
                current_level = int(match.group())
                next_level = current_level + 1
                # --- FIX: Simplified and more robust class name replacement ---
                next_class_name = re.sub(r'\d+', str(next_level), current_class_name.split(' ')[0])
                principal_remark = f"Promoted to {next_class_name}"

        principal_info = {
            "name": "OMADA DAVID MR.",
            "title": "DIRECTOR/PRINCIPAL"
        }

        # --- Step 7: Assemble Final Data Payload (No Changes) ---
        student_data = {
            'student_name': f"{student.first_name} {student.last_name}",
            'admission_number': student_profile.admission_number if student_profile else "N/A",
            'username': student.username,
            'gender': student.gender.value,
            'email': student.email,
            'phone': student.phone,
            'profile_picture_url': student.profile_picture_url
        }
        session_info = {'session_name': academic_session.name, 'class_name': class_obj.name}
        
        grade_counts = Counter(res['final_grade'] for res in final_cumulative_results if res['final_grade'])
        grades_summary = ", ".join([f"{count}({grade})" for grade, count in sorted(grade_counts.items())])

        return (
            student_data, session_info, final_cumulative_results, overall_cumulative_average, 
            form_teacher_remark, principal_remark, principal_info, grades_summary, class_obj
        )
