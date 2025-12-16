from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from typing import List, Dict
from pydantic import EmailStr

from app.core.config import settings

# Email configuration - PRESERVED from original
conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)


async def send_password_reset_email(
    email: List[EmailStr],
    first_name: str,
    token: str
):
    """
    Send password reset email.
    PRESERVED: Exact same HTML template and logic.
    """
    reset_link = f"http://yourappfrontend.com/reset-password?token={token}"
    html = f"""
    Hello {first_name},
    Please use the following link to reset your password:
    {reset_link}
    This link will expire in 1 hour.
    """
    
    message = MessageSchema(
        subject="Password Reset Request",
        recipients=email,
        body=html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    await fm.send_message(message)


async def send_welcome_email(recipient_email: EmailStr, user_details: Dict):
    """
    Sends a welcome email to a new user with their credentials.
    PRESERVED: The email content and structure are identical to the original.
    """
    if not settings.EMAIL_ENABLED:
        print(f"Email sending is disabled. Would send to {recipient_email}.")
        return

    first_name = user_details.get("first_name", "User")
    username = user_details.get("username")
    password = user_details.get("password")

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

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
        print(f"Welcome email sent to {recipient_email}")
    except Exception as e:
        print(f"Failed to send welcome email to {recipient_email}: {e}")


async def send_result_notification_email(
    recipient_email: EmailStr,
    student_name: str,
    term_details: str
):
    """
    Sends an email to a student notifying them that their results have been published.
    """
    if not settings.EMAIL_ENABLED:
        print(f"Email sending disabled. Would notify {recipient_email} about results.")
        return

    html = f"""
    <html>
        <body>
            <h2>Dear {student_name},</h2>
            <p>
                We are pleased to inform you that your results for <strong>{term_details}</strong>
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

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
        print(f"Result notification sent to {recipient_email}")
    except Exception as e:
        print(f"Failed to send result notification to {recipient_email}: {e}")


async def send_payment_receipt_email(
    recipient_email: EmailStr,
    student_name: str,
    receipt_details: Dict,
    pdf_attachment: bytes
):
    """
    Sends a payment receipt email with invoice PDF attached.
    """
    if not settings.EMAIL_ENABLED:
        print(f"Email sending disabled. Would send receipt to {recipient_email}.")
        return

    html = f"""
    
        
            Payment Receipt - Crowners Portal
            Dear {student_name},
            Thank you for your payment. Your payment has been successfully processed.
            
            Payment Details:
            
                Invoice Number: {receipt_details.get('invoice_number')}
                Amount Paid: ₦{receipt_details.get('amount_paid_this_time'):,.2f}
                Total Invoice Amount: ₦{receipt_details.get('total_amount'):,.2f}
                Total Paid: ₦{receipt_details.get('paid_amount'):,.2f}
                Balance Due: ₦{receipt_details.get('balance_due'):,.2f}
            
            
            Please find your invoice attached to this email.
            Thank you!
        
    
    """
    
    message = MessageSchema(
        subject=f"Payment Receipt - Invoice {receipt_details.get('invoice_number')}",
        recipients=[recipient_email],
        body=html,
        subtype=MessageType.html,
        attachments=[{
            "file": pdf_attachment,
            "filename": f"invoice_{receipt_details.get('invoice_number')}.pdf",
            "content_type": "application/pdf"
        }]
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
        print(f"Payment receipt sent to {recipient_email}")
    except Exception as e:
        print(f"Failed to send payment receipt to {recipient_email}: {e}")


# Create a singleton instance for easy importing
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


email_service = EmailService()