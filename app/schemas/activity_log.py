# app/schemas/activity_log.py
from pydantic import BaseModel
from datetime import datetime
from app.models import ActivityAction

class ActivityLogResponse(BaseModel):
    id: str
    timestamp: datetime
    actor_username: str
    action: ActivityAction
    details: str
    time_ago: str