# app/services/activity_log_service.py
"""
Service for logging user activities.
PRESERVED: The logic is identical to the original log_activity function.
"""
from sqlmodel import Session
from app.models import User, ActivityLog, ActivityAction
from app.core.config import settings

async def log_activity(
    session: Session,
    actor: User,
    action: ActivityAction,
    details: str,
    target_id: str = None,
    target_type: str = None
):
    """
    Creates an activity log entry in the database.
    """
    if not settings.ACTIVITY_LOG_ENABLED:
        return

    activity = ActivityLog(
        actor_id=actor.id,
        actor_username=actor.username,
        action=action.value, # Ensure the string value of the enum is used
        details=details,
        target_id=target_id,
        target_type=target_type
    )
    session.add(activity)
    # The session will be committed by the calling function