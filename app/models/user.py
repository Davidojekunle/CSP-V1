from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING
from datetime import date, datetime
import uuid

from app.models.base import UserRole, Gender

if TYPE_CHECKING:
    from app.models.student import StudentProfile
    from app.models.staff import StaffProfile
    from app.models.activity_log import ActivityLog


class User(SQLModel, table=True):
    __tablename__ = "users"
    
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    username: str = Field(unique=True)
    email: str = Field(unique=True)
    phone: str = Field(unique=True)
    password_hash: str
    reset_password_token: Optional[str] = None
    reset_password_expires: Optional[datetime] = None
    role: UserRole
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    profile_picture_url: Optional[str] = None
    gender: Gender
    date_of_birth: date
    is_active: bool = Field(default=True)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

    # Relationships
    activities: List["ActivityLog"] = Relationship(back_populates="actor")
    student_profile: Optional["StudentProfile"] = Relationship(back_populates="user")
    staff_profile: Optional["StaffProfile"] = Relationship(back_populates="user")
