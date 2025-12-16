from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, TYPE_CHECKING
from datetime import date

if TYPE_CHECKING:
    from app.models.user import User


class StaffProfile(SQLModel, table=True):
    __tablename__ = "staff_profiles"
    
    user_id: str = Field(foreign_key="users.id", primary_key=True)
    staff_no: str = Field(unique=True)
    job_title: str
    employment_date: date
    qualifications: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="staff_profile")