# app/api/v1/activity_logs.py
"""API routes for viewing activity logs."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List
from datetime import datetime

from app.core.database import get_session
from app.core.auth import get_current_admin
from app.models import ActivityLog
from app.schemas.activity_log import ActivityLogResponse

router = APIRouter(
    prefix="/admin",
    tags=["Admin - Activity Logs"],
    dependencies=[Depends(get_current_admin)]
)

def _time_ago(dt: datetime) -> str:
    # This helper function is preserved from your original admin.py
    diff = datetime.utcnow() - dt
    seconds = diff.total_seconds()
    if seconds < 60: return "just now"
    minutes = seconds / 60
    if minutes < 60: return f"{int(minutes)} mins ago"
    hours = minutes / 60
    if hours < 24: return f"{int(hours)} hrs ago"
    days = hours / 24
    if days < 7: return f"{int(days)} days ago"
    return dt.strftime("%b %d, %Y")

@router.get("/recent-activity", response_model=List[ActivityLogResponse])
async def get_recent_activity(
    limit: int = Query(5, ge=1, le=50),
    db: AsyncSession = Depends(get_session)
):
    """Get the most recent admin activities for the dashboard feed."""
    result = await db.execute(select(ActivityLog).order_by(ActivityLog.timestamp.desc()).limit(limit))
    logs = result.scalars().all()
    
    return [
        ActivityLogResponse(
            id=log.id,
            timestamp=log.timestamp,
            actor_username=log.actor_username,
            action=log.action,
            details=log.details,
            time_ago=_time_ago(log.timestamp) # Use the helper to add the human-friendly time
        ) for log in logs
    ]