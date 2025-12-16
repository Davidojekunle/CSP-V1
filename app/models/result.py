from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
import uuid

from app.models.base import TraitGrade


class Result(SQLModel, table=True):
    __tablename__ = "results"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    student_id: str = Field(foreign_key="users.id")
    class_id: str = Field(foreign_key="classes.id")
    subject_id: str = Field(foreign_key="subjects.id")
    session_id: str = Field(foreign_key="academic_sessions.id")
    term_id: str = Field(foreign_key="terms.id")
    ca1: Optional[float] = None
    ca2: Optional[float] = None
    exam: Optional[float] = None
    total: Optional[float] = None
    is_published: bool = Field(default=False)
    grade_letter: Optional[str] = None
    remark: Optional[str] = None


class BehavioralTraits(SQLModel, table=True):
    __tablename__ = "behavioral_traits"

    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    student_id: str = Field(foreign_key="users.id", index=True)
    session_id: str = Field(foreign_key="academic_sessions.id", index=True)
    term_id: str = Field(foreign_key="terms.id", index=True)
    
    neatness: Optional[TraitGrade] = None
    reliability: Optional[TraitGrade] = None
    sense_of_responsibility: Optional[TraitGrade] = None
    relationship_with_students: Optional[TraitGrade] = None
    self_control: Optional[TraitGrade] = None
    obedience: Optional[TraitGrade] = None
    initiative: Optional[TraitGrade] = None
    punctuality: Optional[TraitGrade] = None
    attentiveness: Optional[TraitGrade] = None
    spirit_of_cooperation: Optional[TraitGrade] = None
    affective_domain_remarks: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FormTeacherRemark(SQLModel, table=True):
    __tablename__ = "form_teacher_remarks"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    student_id: str
    class_id: str
    session_id: str
    term_id: str
    teacher_id: Optional[str] = None
    remark_text: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)