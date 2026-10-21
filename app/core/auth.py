"""
Authentication helpers and FastAPI dependencies.
The HTTP endpoints live in app/api/v1/auth.py.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.database import get_session
from app.core.security import verify_password
from app.models import User, UserRole


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


async def authenticate_user(identifier: str, password: str, session: AsyncSession) -> Optional[User]:
    """Authenticate user by email or username and password."""
    result = await session.execute(
        select(User).where(
            or_(User.email == identifier, User.username == identifier),
            User.is_active == True
        )
    )
    user = result.scalars().first()
    # verify_password runs bcrypt in a worker thread, so it must be awaited
    if user and await verify_password(password, user.password_hash):
        return user
    return None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme), session: AsyncSession = Depends(get_session)):
    """Get current user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        user_role: str = payload.get("user_type")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await session.execute(select(User).where(User.email == email, User.is_active == True))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception

    return {"user": user, "user_type": user_role}


def get_current_active_user(current_user: dict = Depends(get_current_user)):
    """Get current active user"""
    if not current_user["user"] or not current_user["user"].is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_staff_or_admin(current_user: dict = Depends(get_current_active_user)) -> dict:
    """
    Dependency that ensures the current user is either a 'staff' or 'admin'.
    Raises a 403 Forbidden error if the role is not permitted.
    """
    if current_user['user_type'] not in [UserRole.staff, UserRole.admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action."
        )
    return current_user


def get_current_admin(current_user: dict = Depends(get_current_active_user)):
    """Get current user if they are an admin"""
    if current_user["user_type"] != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user["user"]


def get_current_staff(current_user: dict = Depends(get_current_active_user)):
    """Get current user if they are staff"""
    if current_user["user_type"] not in [UserRole.staff]:
        raise HTTPException(status_code=403, detail="Staff access required")
    return current_user["user"]


def get_current_student(current_user: dict = Depends(get_current_active_user)):
    """Get current user if they are a student"""
    if current_user["user_type"] != UserRole.student:
        raise HTTPException(status_code=403, detail="Student access required")
    return current_user["user"]
