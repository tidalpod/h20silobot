"""Email service for sending notifications via SendGrid or SMTP"""

import logging
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from webapp.config import web_config

logger = logging.getLogger(__name__)


@dataclass
class EmailResult:
    """Result of an email send attempt"""
    success: bool
    message_id: Optional[str] = None
    error_message: Optional[str] = None


class EmailService:
    """Service for sending emails via SendGrid or SMTP"""

    def __init__(self):
        self._sendgrid_client = None

    @property
    def is_configured(self) -> bool:
        """Check if email sending is configured"""
        return web_config.has_sendgrid or web_config.has_smtp

    @property
    def use_sendgrid(self) -> bool:
        """Check if SendGrid should be used"""
        return web_config.has_sendgrid

    @property
    def sendgrid_client(self):
        """Lazy-load SendGrid client"""
        if self._sendgrid_client is None and self.use_sendgrid:
            try:
                from sendgrid import SendGridAPIClient
                self._sendgrid_client = SendGridAPIClient(web_config.sendgrid_api_key)
            except ImportError:
                logger.warning("SendGrid library not installed")
            except Exception as e:
                logger.error(f"Failed to initialize SendGrid client: {e}")
        return self._sendgrid_client

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None
    ) -> EmailResult:
        """
        Send an email

        Args:
            to: Recipient email address
            subject: Email subject
            body: Plain text body
            html_body: Optional HTML body

        Returns:
            EmailResult with success status and message ID or error
        """
        if not self.is_configured:
            return EmailResult(
                success=False,
                error_message="Email service is not configured"
            )

        # Validate email
        if not to or '@' not in to:
            return EmailResult(
                success=False,
                error_message="Invalid email address"
            )

        # Try SendGrid first
        if self.use_sendgrid:
            return await self._send_via_sendgrid(to, subject, body, html_body)

        # Fall back to SMTP
        if web_config.has_smtp:
            return await self._send_via_smtp(to, subject, body, html_body)

        return EmailResult(
            success=False,
            error_message="No email provider available"
        )

    async def _send_via_sendgrid(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str]
    ) -> EmailResult:
        """Send email via SendGrid"""
        if not self.sendgrid_client:
            return EmailResult(
                success=False,
                error_message="SendGrid client failed to initialize"
            )

        try:
            from sendgrid.helpers.mail import Mail, Email, To, Content

            message = Mail(
                from_email=Email(web_config.email_from),
                to_emails=To(to),
                subject=subject
            )

            # Add plain text content
            message.add_content(Content("text/plain", body))

            # Add HTML content if provided
            if html_body:
                message.add_content(Content("text/html", html_body))

            response = self.sendgrid_client.send(message)

            if response.status_code in (200, 201, 202):
                # Extract message ID from headers
                message_id = response.headers.get('X-Message-Id', '')
                logger.info(f"Email sent via SendGrid: {message_id}")
                return EmailResult(
                    success=True,
                    message_id=message_id
                )
            else:
                return EmailResult(
                    success=False,
                    error_message=f"SendGrid returned status {response.status_code}"
                )

        except Exception as e:
            logger.error(f"Failed to send email via SendGrid: {e}")
            return EmailResult(
                success=False,
                error_message=str(e)
            )

    async def _send_via_smtp(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str]
    ) -> EmailResult:
        """Send email via SMTP"""
        try:
            # Create message
            if html_body:
                msg = MIMEMultipart('alternative')
                msg.attach(MIMEText(body, 'plain'))
                msg.attach(MIMEText(html_body, 'html'))
            else:
                msg = MIMEText(body)

            msg['Subject'] = subject
            msg['From'] = web_config.email_from or web_config.smtp_user
            msg['To'] = to

            # Connect and send
            if web_config.smtp_use_tls:
                server = smtplib.SMTP(web_config.smtp_host, web_config.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(web_config.smtp_host, web_config.smtp_port)

            server.login(web_config.smtp_user, web_config.smtp_password)
            server.sendmail(msg['From'], [to], msg.as_string())
            server.quit()

            logger.info(f"Email sent via SMTP to {to}")
            return EmailResult(
                success=True,
                message_id=f"smtp-{to}"
            )

        except Exception as e:
            logger.error(f"Failed to send email via SMTP: {e}")
            return EmailResult(
                success=False,
                error_message=str(e)
            )


# Global service instance
email_service = EmailService()
