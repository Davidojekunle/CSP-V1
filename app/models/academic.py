from sqlmodel import SQLModel, Field, Column
from typing import Optional
from datetime import date, datetime
import uuid
from sqlalchemy import Enum as SQLAlchemyEnum

from app.models.base import TermName, PromotionType


class Class(SQLModel, table=True):
    __tablename__ = "classes"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    level: str
    arm: str
    form_teacher_id: Optional[str] = Field(foreign_key="users.id")
    is_active: bool = Field(default=True)
    promotion_type: PromotionType = Field(
        default=PromotionType.promote,
        sa_column=Column(SQLAlchemyEnum(PromotionType))
    )
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class Subject(SQLModel, table=True):
    __tablename__ = "subjects"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    code: str = Field(unique=True)
    name: str
    is_active: bool = Field(default=True)


class ClassSubject(SQLModel, table=True):
    __tablename__ = "class_subjects"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    class_id: str = Field(foreign_key="classes.id")
    subject_id: str = Field(foreign_key="subjects.id")
    teacher_id: str = Field(foreign_key="users.id")


class AcademicSession(SQLModel, table=True):
    __tablename__ = "academic_sessions"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(unique=True)
    start_date: date
    end_date: date
    is_current: bool = Field(default=False)


class Term(SQLModel, table=True):
    __tablename__ = "terms"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="academic_sessions.id")
    name: TermName
    start_date: date
    end_date: date
    is_current: bool = Field(default=False)


class Enrollment(SQLModel, table=True):
    __tablename__ = "enrollments"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    student_id: str = Field(foreign_key="users.id")
    class_id: str = Field(foreign_key="classes.id")
    session_id: str = Field(foreign_key="academic_sessions.id")
    term_id: str = Field(foreign_key="terms.id")
    is_active: bool = Field(default=True)
    enrolled_at: date