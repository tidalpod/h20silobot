"""Database models for Water Bill Tracker"""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Date,
    ForeignKey, Text, Enum, Boolean, Index
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class BillStatus(PyEnum):
    CURRENT = "current"
    DUE_SOON = "due_soon"  # Within 7 days
    OVERDUE = "overdue"
    PAID = "paid"
    UNKNOWN = "unknown"


class Property(Base):
    """Property/Account being tracked"""
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True)
    address = Column(String(255), nullable=False)
    bsa_account_number = Column(String(50), unique=True, nullable=False)
    parcel_number = Column(String(50), nullable=True)
    tenant_name = Column(String(255), nullable=True)
    owner_name = Column(String(255), nullable=True)

    # Tracking
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    bills = relationship("WaterBill", back_populates="property", order_by="desc(WaterBill.statement_date)")

    def __repr__(self):
        return f"<Property {self.address} ({self.bsa_account_number})>"

    @property
    def latest_bill(self):
        """Get the most recent bill"""
        return self.bills[0] if self.bills else None

    @property
    def status_emoji(self):
        """Get status emoji for display"""
        if not self.latest_bill:
            return "⚪"
        status = self.latest_bill.status
        return {
            BillStatus.CURRENT: "🟢",
            BillStatus.DUE_SOON: "🟡",
            BillStatus.OVERDUE: "🔴",
            BillStatus.PAID: "✅",
            BillStatus.UNKNOWN: "⚪"
        }.get(status, "⚪")


class WaterBill(Base):
    """Individual water bill record"""
    __tablename__ = "water_bills"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)

    # Bill details
    amount_due = Column(Numeric(10, 2), nullable=False)
    previous_balance = Column(Numeric(10, 2), nullable=True)
    current_charges = Column(Numeric(10, 2), nullable=True)
    late_fees = Column(Numeric(10, 2), default=0)
    payments_received = Column(Numeric(10, 2), default=0)

    # Dates
    statement_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    last_payment_date = Column(Date, nullable=True)

    # Usage (if available)
    water_usage_gallons = Column(Integer, nullable=True)
    billing_period_start = Column(Date, nullable=True)
    billing_period_end = Column(Date, nullable=True)

    # Status
    status = Column(Enum(BillStatus), default=BillStatus.UNKNOWN)

    # Tracking
    scraped_at = Column(DateTime, default=datetime.utcnow)
    raw_data = Column(Text, nullable=True)  # Store raw scraped data for debugging

    # Relationships
    property = relationship("Property", back_populates="bills")

    # Indexes
    __table_args__ = (
        Index("ix_water_bills_property_date", "property_id", "statement_date"),
    )

    def __repr__(self):
        return f"<WaterBill ${self.amount_due} due {self.due_date}>"

    def calculate_status(self) -> BillStatus:
        """Calculate bill status based on due date and amount"""
        if self.amount_due <= 0:
            return BillStatus.PAID

        if not self.due_date:
            return BillStatus.UNKNOWN

        today = datetime.now().date()
        days_until_due = (self.due_date - today).days

        if days_until_due < 0:
            return BillStatus.OVERDUE
        elif days_until_due <= 7:
            return BillStatus.DUE_SOON
        else:
            return BillStatus.CURRENT


class ScrapingLog(Base):
    """Log of scraping attempts for monitoring"""
    __tablename__ = "scraping_logs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    success = Column(Boolean, default=False)
    properties_scraped = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # JSON details

    def __repr__(self):
        status = "✓" if self.success else "✗"
        return f"<ScrapingLog {status} {self.started_at}>"


class TelegramUser(Base):
    """Telegram users authorized to use the bot"""
    __tablename__ = "telegram_users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    is_admin = Column(Boolean, default=False)
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TelegramUser {self.username or self.telegram_id}>"
