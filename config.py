"""Configuration management for Water Bill Bot"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Telegram
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Database
    database_url: str = os.getenv("DATABASE_URL", "")

    # BSA Online
    bsa_username: str = os.getenv("BSA_USERNAME", "")
    bsa_password: str = os.getenv("BSA_PASSWORD", "")
    bsa_municipality_uid: str = os.getenv("BSA_MUNICIPALITY_UID", "305")

    # Encryption
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")

    # Scraping
    scrape_interval_hours: int = int(os.getenv("SCRAPE_INTERVAL_HOURS", "24"))
    headless_browser: bool = os.getenv("HEADLESS_BROWSER", "true").lower() == "true"

    # Blue Deer Notification Settings
    water_bill_threshold: float = float(os.getenv("WATER_BILL_THRESHOLD", "100"))  # Alert when bill exceeds this
    recert_reminder_days: int = int(os.getenv("RECERT_REMINDER_DAYS", "30"))  # Days before recert to remind
    admin_telegram_id: int = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))  # Primary admin to receive alerts

    # BSA URLs
    @property
    def bsa_base_url(self) -> str:
        return "https://bsaonline.com"

    @property
    def bsa_municipality_url(self) -> str:
        return f"{self.bsa_base_url}/?uid={self.bsa_municipality_uid}"

    def validate(self) -> list[str]:
        """Validate required configuration"""
        errors = []
        if not self.telegram_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        if not self.database_url:
            errors.append("DATABASE_URL is required")
        return errors


config = Config()
