from app.core.database import get_session
from fastapi import Depends, HTTPException, status, APIRouter, BackgroundTasks
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlmodel import Session, select
import os
from sqlalchemy import or_
from app.models import User, UserRole
import secrets
from typing import List
from app.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest, ChangePasswordRequest
from pydantic import EmailStr


load_dotenv()
auth_route = APIRouter()


# Auth configuration
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 *24))

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

# Email configuration
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM")
MAIL_SERVER = os.getenv("MAIL_SERVER")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
MAIL_STARTTLS = os.getenv("MAIL_STARTTLS", "true").lower() in ("true", "1", "t")
MAIL_SSL_TLS = os.getenv("MAIL_SSL_TLS", "false").lower() in ("true", "1", "t")

conf = None

if all([MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM, MAIL_SERVER]):
    conf = ConnectionConfig(
        MAIL_USERNAME=MAIL_USERNAME,
        MAIL_PASSWORD=MAIL_PASSWORD,
        MAIL_FROM=MAIL_FROM,
        MAIL_PORT=MAIL_PORT,
        MAIL_SERVER=MAIL_SERVER,
        MAIL_STARTTLS=MAIL_STARTTLS,
        MAIL_SSL_TLS=MAIL_SSL_TLS,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True
    )

# FIXED FUNCTION: Now accepts first_name as a string
async def send_password_reset_email(email: List[EmailStr], first_name: str, token: str):
    if conf is None:
        # Mail not configured — silently skip
        return

    reset_link = f"http://yourappfrontend.com/reset-password?token={token}"
    html = f"""
    <p>Hello {first_name},</p>
    <p>Please use the following link to reset your password:</p>
    <p><a href="{reset_link}">{reset_link}</a></p>
    <p>This link will expire in 1 hour.</p>
    """

    message = MessageSchema(
        subject="Password Reset Request",
        recipients=email,
        body=html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    await fm.send_message(message)



def get_password_hash(password):
    """Hash a password"""
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)

def authenticate_user(identifier: str, password: str, session: Session):
    """
    Authenticate user by email or username and password.
    """
    user = session.exec(
        select(User).where(
            or_(User.email == identifier, User.username == identifier),
            User.is_active == True
        )
    ).first()
    if user and verify_password(password, user.password_hash):
        return user
    return None

def create_access_token(data: dict, expires_delta: timedelta = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)):
    """Get current user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_role: str = payload.get("user_type")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = session.exec(select(User).where(User.email == email, User.is_active == True)).first()
    if user is None:
        raise credentials_exception
    
    return {"user": user, "user_type": user_role}

def get_current_active_user(current_user: dict = Depends(get_current_user)):
    """Get current active user"""
    if not current_user["user"] or not current_user["user"].is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_staff_or_admin(
    current_user: User = Depends(get_current_active_user)
) -> User:
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
    """Get current user if they are staff or admin"""
    if current_user["user_type"] not in [UserRole.staff]:
        raise HTTPException(status_code=403, detail="Staff access required")
    return current_user["user"]



def get_current_student(current_user: dict = Depends(get_current_active_user)):
    """Get current user if they are a student"""
    if current_user["user_type"] != UserRole.student:
        raise HTTPException(status_code=403, detail="Student access required")
    return current_user["user"]

# Auth endpoints
@auth_route.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    session: Session = Depends(get_session)
):
    """
    Login endpoint to get access token.
    Users can enter either email or username.
    """
    user = authenticate_user(form_data.username, form_data.password, session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "user_type": user.role}, 
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_type": user.role,
        "user_id": user.id,
        "full_name": f"{user.first_name} {user.last_name}"
    }

@auth_route.get("/me")
async def get_current_user_profile(current_user: dict = Depends(get_current_active_user)):
    """Get current user profile"""
    user = current_user["user"]
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "is_active": user.is_active
    }

@auth_route.post('/forgot-password')
async def forgot_password(
    request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    """Send password reset email"""
    user = session.exec(select(User).where(User.email == request.email)).first()
    if not user:
        # Don't reveal if email exists or not for security
        return {"message": "If the email exists, a reset link will be sent"}
    
    # Generate reset token
    reset_token = secrets.token_urlsafe(32)
    
    # Store the token and expiry in the database
    user.reset_password_token = reset_token
    user.reset_password_expires = datetime.utcnow() + timedelta(hours=2)
    session.add(user)
    session.commit()
    
    # FIXED CALL: Now passes user.first_name (a string) instead of the whole user object
    background_tasks.add_task(send_password_reset_email, [request.email], user.first_name, reset_token)
    
    return {"message": "If the email exists, a reset link will be sent"}

@auth_route.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    session: Session = Depends(get_session)
):
    """Reset password using token"""
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
    # Clear reset token
    user.reset_password_token = None
    user.reset_password_expires = None
    user.updated_at = datetime.utcnow()
    session.add(user)
    session.commit()
    
    return {"message": "Password reset successfully"}

@auth_route.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    """Change user password"""
    user = current_user["user"]
    
    # Verify old password
    if not verify_password(request.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    
    # Update password
    user.password_hash = get_password_hash(request.new_password)
    user.updated_at = datetime.utcnow()
    
    session.add(user)
    session.commit()
    
    return {"message": "Password changed successfully"}

@auth_route.post("/logout")
async def logout():
    """Logout endpoint (client should remove token)"""
    return {"message": "Successfully logged out"}


