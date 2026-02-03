"""Web application configuration"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class WebConfig:
    """Web-specific configuration"""

    # Web App
    secret_key: str = os.getenv("WEB_SECRET_KEY", "change-me-in-production")
    host: str = os.getenv("WEB_HOST", "0.0.0.0")
    port: int = int(os.getenv("WEB_PORT", "8000"))
    debug: bool = os.getenv("WEB_DEBUG", "false").lower() == "true"

    # Session
    session_cookie_name: str = "h2o_session"
    session_max_age: int = 60 * 60 * 24 * 7  # 7 days

    # Twilio
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_phone_number: str = os.getenv("TWILIO_PHONE_NUMBER", "")

    # Email (SendGrid)
    sendgrid_api_key: str = os.getenv("SENDGRID_API_KEY", "")
    email_from: str = os.getenv("EMAIL_FROM", "")

    # SMTP fallback
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    # Database (shared with bot)
    database_url: str = os.getenv("DATABASE_URL", "")

    @property
    def has_twilio(self) -> bool:
        """Check if Twilio is configured"""
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_phone_number)

    @property
    def has_sendgrid(self) -> bool:
        """Check if SendGrid is configured"""
        return bool(self.sendgrid_api_key and self.email_from)

    @property
    def has_smtp(self) -> bool:
        """Check if SMTP is configured"""
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    def validate(self) -> list[str]:
        """Validate required configuration"""
        errors = []
        if self.secret_key == "change-me-in-production":
            errors.append("WEB_SECRET_KEY should be set to a secure random value")
        if not self.database_url:
            errors.append("DATABASE_URL is required")
        return errors


web_config = WebConfig()
