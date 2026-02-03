"""Twilio SMS service for sending notifications"""

import logging
from dataclasses import dataclass
from typing import Optional

from webapp.config import web_config

logger = logging.getLogger(__name__)


@dataclass
class SMSResult:
    """Result of an SMS send attempt"""
    success: bool
    message_sid: Optional[str] = None
    error_message: Optional[str] = None


class TwilioService:
    """Service for sending SMS via Twilio"""

    def __init__(self):
        self.account_sid = web_config.twilio_account_sid
        self.auth_token = web_config.twilio_auth_token
        self.from_number = web_config.twilio_phone_number
        self._client = None

    @property
    def is_configured(self) -> bool:
        """Check if Twilio is configured"""
        return web_config.has_twilio

    @property
    def client(self):
        """Lazy-load Twilio client"""
        if self._client is None and self.is_configured:
            try:
                from twilio.rest import Client
                self._client = Client(self.account_sid, self.auth_token)
            except ImportError:
                logger.warning("Twilio library not installed")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
        return self._client

    async def send_sms(self, to: str, message: str) -> SMSResult:
        """
        Send an SMS message

        Args:
            to: Phone number to send to (E.164 format preferred)
            message: Message content

        Returns:
            SMSResult with success status and message SID or error
        """
        if not self.is_configured:
            return SMSResult(
                success=False,
                error_message="Twilio is not configured"
            )

        if not self.client:
            return SMSResult(
                success=False,
                error_message="Twilio client failed to initialize"
            )

        # Normalize phone number
        to_number = self._normalize_phone(to)
        if not to_number:
            return SMSResult(
                success=False,
                error_message="Invalid phone number"
            )

        try:
            # Send message (synchronous call wrapped in async context)
            sms = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number
            )

            logger.info(f"SMS sent successfully: {sms.sid}")
            return SMSResult(
                success=True,
                message_sid=sms.sid
            )

        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
            return SMSResult(
                success=False,
                error_message=str(e)
            )

    def _normalize_phone(self, phone: str) -> Optional[str]:
        """
        Normalize phone number to E.164 format

        Args:
            phone: Phone number in various formats

        Returns:
            Normalized phone number or None if invalid
        """
        if not phone:
            return None

        # Remove common characters
        digits = ''.join(c for c in phone if c.isdigit() or c == '+')

        if not digits:
            return None

        # Add US country code if missing
        if digits.startswith('+'):
            return digits
        elif digits.startswith('1') and len(digits) == 11:
            return f"+{digits}"
        elif len(digits) == 10:
            return f"+1{digits}"
        else:
            # Try to return as-is with + prefix
            return f"+{digits}"


# Global service instance
twilio_service = TwilioService()
