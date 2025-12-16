from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, TYPE_CHECKING
from datetime import date, datetime

from app.models.base import StudentStatus

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.academic import Class


class StudentProfile(SQLModel, table=True):
    __tablename__ = "student_profiles"
    
    user_id: str = Field(foreign_key="users.id", primary_key=True)
    admission_number: str = Field(unique=True)
    guardian_name: str
    guardian_phone: str
    guardian_email: str
    current_class_id: Optional[str] = Field(foreign_key="classes.id")
    address: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    medical_notes: Optional[str] = None
    enrollment_date: date
    status: StudentStatus = Field(default=StudentStatus.active, nullable=False)
    graduated_at: Optional[datetime] = None
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="student_profile")
    current_class: Optional["Class"] = Relationship()