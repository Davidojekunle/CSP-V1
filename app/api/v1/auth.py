from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from datetime import datetime, timedelta
import secrets

from app.core.database import get_session
from app.core.auth import (
    authenticate_user,
    create_access_token,
    get_current_active_user
)
from app.core.security import get_password_hash
from app.core.config import settings
from app.models import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    TokenResponse,
    UserProfileResponse,
    MessageResponse
)
from app.services.email.sender import send_password_reset_email

router = APIRouter()


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session)
):
    """
    Login endpoint to get access token.
    PRESERVED: Exact same logic and response structure.
    """
    user = authenticate_user(form_data.username, form_data.password, session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "user_type": user.role},
        expires_delta=access_token_expires
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_type=user.role,
        user_id=user.id,
        full_name=f"{user.first_name} {user.last_name}"
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    current_user: dict = Depends(get_current_active_user)
):
    """
    Get current user profile.
    PRESERVED: Exact response structure.
    """
    user = current_user["user"]
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        is_active=user.is_active
    )


@router.post('/forgot-password', response_model=MessageResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    """
    Send password reset email.
    PRESERVED: Exact same logic.
    """
    user = session.exec(select(User).where(User.email == request.email)).first()
    if not user:
        return MessageResponse(message="If the email exists, a reset link will be sent")
    
    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    
    # Store the token and expiry in the database
    user.reset_password_token = reset_token
    user.reset_password_expires = datetime.utcnow() + timedelta(hours=2)
    session.add(user)
    session.commit()
    
    background_tasks.add_task(
        send_password_reset_email,
        [request.email],
        user.first_name,
        reset_token
    )
    
    return MessageResponse(message="If the email exists, a reset link will be sent")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: ResetPasswordRequest,
    session: Session = Depends(get_session)
):
    """
    Reset password using token.
    PRESERVED: Exact same logic.
    """
    user = session.exec(
        select(User).where(
            User.reset_password_token == request.token,
            User.reset_password_expires > datetime.utcnow()
        )
    ).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    
    # Update password
    user.password_hash = get_password_hash(request.new_password)
    user.reset_password_token = None
    user.reset_password_expires = None
    user.updated_at = datetime.utcnow()
    session.add(user)
    session.commit()
    
    return MessageResponse(message="Password reset successfully")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    """
    Change user password.
    PRESERVED: Exact same logic.
    """
    from app.core.security import verify_password
    
    user = current_user["user"]
    
    # Verify old password
    if not verify_password(request.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    
    # Update password
    user.password_hash = get_password_hash(request.new_password)
    user.updated_at = datetime.utcnow()
    
    session.add(user)
    session.commit()
    
    return MessageResponse(message="Password changed successfully")


@router.post("/logout", response_model=MessageResponse)
async def logout():
    """
    Logout endpoint (client should remove token).
    PRESERVED: Exact same response.
    """
    return MessageResponse(message="Successfully logged out")