from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, TYPE_CHECKING
from datetime import datetime
import uuid

if TYPE_CHECKING:
    from app.models.user import User


class ActivityLog(SQLModel, table=True):
    __tablename__ = "activity_logs"

    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    actor_id: str = Field(foreign_key="users.id")
    actor_username: str
    action: str
    details: str
    target_id: Optional[str] = Field(default=None, index=True)
    target_type: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    actor: "User" = Relationship(back_populates="activities")