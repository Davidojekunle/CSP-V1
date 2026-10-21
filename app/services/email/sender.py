import logging
import os
import tempfile
from functools import lru_cache
from html import escape
from typing import Dict, List, Optional

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from pydantic import EmailStr

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache()
def _mailer() -> Optional[FastMail]:
    """Built lazily so the app can start without mail settings."""
    if not settings.EMAIL_ENABLED:
        return None
    if not all([settings.MAIL_USERNAME, settings.MAIL_PASSWORD, settings.MAIL_FROM, settings.MAIL_SERVER]):
        logger.warning("EMAIL_ENABLED is set but MAIL_* settings are incomplete; emails will not be sent.")
        return None
    return FastMail(ConnectionConfig(
        MAIL_USERNAME=settings.MAIL_USERNAME,
        MAIL_PASSWORD=settings.MAIL_PASSWORD,
        MAIL_FROM=settings.MAIL_FROM,
        MAIL_PORT=settings.MAIL_PORT,
        MAIL_SERVER=settings.MAIL_SERVER,
        MAIL_STARTTLS=settings.MAIL_STARTTLS,
        MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True
    ))


async def _send(message: MessageSchema, description: str):
    fm = _mailer()
    if fm is None:
        logger.info("Email disabled; skipped %s", description)
        return
    try:
        await fm.send_message(message)
        logger.info("Sent %s", description)
    except Exception:
        logger.exception("Failed to send %s", description)


async def send_password_reset_email(
    email: List[EmailStr],
    first_name: str,
    token: str
):
    """Send password reset email."""
    reset_link = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
    html = f"""
    Hello {escape(first_name or '')},
    Please use the following link to reset your password:
    <a href="{reset_link}">{reset_link}</a>
    This link will expire in 2 hours.
    """

    message = MessageSchema(
        subject="Password Reset Request",
        recipients=email,
        body=html,
        subtype=MessageType.html
    )
    await _send(message, "password reset email")


async def send_welcome_email(recipient_email: EmailStr, user_details: Dict):
    """
    Sends a welcome email to a new user with their credentials.
    """
    first_name = escape(user_details.get("first_name", "User") or "User")
    username = escape(str(user_details.get("username")))
    password = escape(str(user_details.get("password")))

    html = f"""
    <html>
        <body>
            <h2>Welcome to Crowners Portal, {first_name}!</h2>
            <p>Your account has been successfully created.</p>
            <p>Here are your login credentials:</p>
            <ul>
                <li><strong>Username:</strong> {username}</li>
                <li><strong>Password:</strong> {password}</li>
            </ul>
            <p>Please log in and change your password at your earliest convenience.</p>
            <p>Thank you!</p>
        </body>
    </html>
    """

    message = MessageSchema(
        subject="Welcome to Crowners Portal!",
        recipients=[recipient_email],
        body=html,
        subtype=MessageType.html
    )
    await _send(message, "welcome email")


async def send_result_notification_email(
    recipient_email: EmailStr,
    student_name: str,
    term_details: str
):
    """
    Sends an email to a student notifying them that their results have been published.
    """
    html = f"""
    <html>
        <body>
            <h2>Dear {escape(student_name or '')},</h2>
            <p>
                We are pleased to inform you that your results for <strong>{escape(term_details or '')}</strong>
                have been published.
            </p>
            <p>
                You can now log in to the student portal to view your report card and performance summary.
            </p>
            <p>Thank you!</p>
        </body>
    </html>
    """

    message = MessageSchema(
        subject="Your Results Have Been Published!",
        recipients=[recipient_email],
        body=html,
        subtype=MessageType.html
    )
    await _send(message, "result notification")


async def send_payment_receipt_email(
    recipient_email: EmailStr,
    student_name: str,
    receipt_details: dict,
    pdf_attachment_bytes: bytes
):
    """
    Sends an email with a payment receipt and the invoice PDF attached,
    using a temporary file to comply with fastapi-mail's attachment requirements.
    """
    if _mailer() is None:
        logger.info("Email disabled; skipped payment receipt")
        return

    html_body = f"""
    <html><body>
        <h2>Dear {escape(student_name or '')},</h2>
        <p>Thank you for your payment. Your payment has been successfully processed.</p>
        <h3>Payment Summary:</h3>
        <ul>
            <li><strong>Invoice Number:</strong> {receipt_details.get('invoice_number', 'N/A')}</li>
            <li><strong>Amount Paid:</strong> NGN {receipt_details.get('amount_paid_this_time', 0):,}</li>
            <li><strong>Total Paid on Invoice:</strong> NGN {receipt_details.get('paid_amount', 0):,}</li>
            <li><strong>Remaining Balance:</strong> NGN {receipt_details.get('balance_due', 0):,}</li>
        </ul>
        <p>Your updated invoice is attached for your records.</p>
        <p>Thank you!</p>
    </body></html>
    """

    # fastapi-mail attaches from a file path; delete=False so it survives the with-block
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        tmp_file.write(pdf_attachment_bytes)
        temp_file_path = tmp_file.name

    try:
        message = MessageSchema(
            subject=f"Payment Receipt for Invoice {receipt_details.get('invoice_number', 'N/A')}",
            recipients=[recipient_email],
            body=html_body,
            subtype=MessageType.html,
            attachments=[temp_file_path]
        )
        await _send(message, "payment receipt")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


class EmailService:
    @staticmethod
    async def send_payment_receipt_email(*args, **kwargs):
        return await send_payment_receipt_email(*args, **kwargs)

    @staticmethod
    async def send_welcome_email(*args, **kwargs):
        return await send_welcome_email(*args, **kwargs)

    @staticmethod
    async def send_result_notification_email(*args, **kwargs):
        return await send_result_notification_email(*args, **kwargs)


# Create a singleton instance for easy importing
email_service = EmailService()
