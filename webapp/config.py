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

    # Site URL (for absolute links in signing emails)
    site_url: str = os.getenv("SITE_URL", "https://bluedeer.space")

    # Database (shared with bot)
    database_url: str = os.getenv("DATABASE_URL", "")

    # Plaid ACH Payments
    plaid_client_id: str = os.getenv("PLAID_CLIENT_ID", "")
    plaid_secret: str = os.getenv("PLAID_SECRET", "")
    plaid_env: str = os.getenv("PLAID_ENV", "sandbox")
    plaid_webhook_url: str = os.getenv("PLAID_WEBHOOK_URL", "")

    # Stripe Payments
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_publishable_key: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # TenantReportX Screening
    tenantreportx_api_url: str = os.getenv("TENANTREPORTX_API_URL", "https://api.tenantreportx.com")
    tenantreportx_api_key: str = os.getenv("TENANTREPORTX_API_KEY", "")
    tenantreportx_account_id: str = os.getenv("TENANTREPORTX_ACCOUNT_ID", "")
    tenantreportx_webhook_secret: str = os.getenv("TENANTREPORTX_WEBHOOK_SECRET", "")
    tenantreportx_applicant_fee: str = os.getenv("TENANTREPORTX_APPLICANT_FEE", "35.00")

    # Cloudflare R2 Object Storage
    r2_account_id: str = os.getenv("R2_ACCOUNT_ID", "")
    r2_access_key_id: str = os.getenv("R2_ACCESS_KEY_ID", "")
    r2_access_key_secret: str = os.getenv("R2_ACCESS_KEY_SECRET", "")
    r2_bucket_name: str = os.getenv("R2_BUCKET_NAME", "")
    r2_public_url: str = os.getenv("R2_PUBLIC_URL", "")

    @property
    def has_r2(self) -> bool:
        """Check if Cloudflare R2 is configured"""
        return bool(self.r2_account_id and self.r2_access_key_id
                     and self.r2_access_key_secret and self.r2_bucket_name
                     and self.r2_public_url)

    @property
    def has_tenantreportx(self) -> bool:
        """Check if TenantReportX is configured"""
        return bool(self.tenantreportx_api_key and self.tenantreportx_account_id)

    @property
    def has_plaid(self) -> bool:
        """Check if Plaid is configured"""
        return bool(self.plaid_client_id and self.plaid_secret)

    @property
    def has_stripe(self) -> bool:
        """Check if Stripe is configured"""
        return bool(self.stripe_secret_key and self.stripe_publishable_key)

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
