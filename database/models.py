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


# =============================================================================
# Enums
# =============================================================================


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
    city = Column(String(100), nullable=True)
    state = Column(String(2), nullable=True)
    zip_code = Column(String(10), nullable=True)
    bsa_account_number = Column(String(50), unique=True, nullable=False)
    parcel_number = Column(String(50), nullable=True)
    tenant_name = Column(String(255), nullable=True)
    owner_name = Column(String(255), nullable=True)

    # Property details
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Numeric(3, 1), nullable=True)  # e.g., 2.5 baths
    square_feet = Column(Integer, nullable=True)
    year_built = Column(Integer, nullable=True)
    lot_size = Column(String(50), nullable=True)
    property_type = Column(String(50), nullable=True)  # Single Family, Multi-Family, etc.

    # Occupancy status
    is_vacant = Column(Boolean, default=False)

    # City certification
    has_city_certification = Column(Boolean, default=False)
    city_certification_date = Column(Date, nullable=True)
    city_certification_expiry = Column(Date, nullable=True)

    # Rental license
    has_rental_license = Column(Boolean, default=False)
    rental_license_number = Column(String(50), nullable=True)
    rental_license_issued = Column(Date, nullable=True)
    rental_license_expiry = Column(Date, nullable=True)

    # Section 8 inspection
    section8_inspection_status = Column(String(50), nullable=True)  # scheduled, passed, failed, pending
    section8_inspection_date = Column(Date, nullable=True)
    section8_inspection_notes = Column(Text, nullable=True)

    # Web user ownership (optional - for web app property management)
    web_user_id = Column(Integer, ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True)

    # Tracking
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    bills = relationship("WaterBill", back_populates="property", order_by="desc(WaterBill.statement_date)")
    tenants = relationship("Tenant", back_populates="property_ref", order_by="desc(Tenant.is_primary)")
    notifications = relationship("Notification", back_populates="property")
    taxes = relationship("PropertyTax", back_populates="property", order_by="desc(PropertyTax.tax_year)")
    recertifications = relationship("Recertification", back_populates="property_ref")
    web_user = relationship("WebUser", back_populates="properties")

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
    notifications = relationship("Notification", back_populates="bill")

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


# =============================================================================
# Web Application Models
# =============================================================================

class NotificationChannel(PyEnum):
    """Notification delivery channel"""
    SMS = "sms"
    EMAIL = "email"


class NotificationStatus(PyEnum):
    """Notification delivery status"""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"


class WebUser(Base):
    """Web application users (separate from Telegram users)"""
    __tablename__ = "web_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    # Relationships
    properties = relationship("Property", back_populates="web_user")

    def __repr__(self):
        return f"<WebUser {self.email}>"


class Tenant(Base):
    """Tenants linked to properties"""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    pha_id = Column(Integer, ForeignKey("phas.id", ondelete="SET NULL"), nullable=True)

    # Contact info
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)

    # Status
    is_primary = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_section8 = Column(Boolean, default=False)  # Whether tenant uses Section 8 voucher

    # Dates
    move_in_date = Column(Date, nullable=True)
    move_out_date = Column(Date, nullable=True)
    lease_start_date = Column(Date, nullable=True)  # For recertification calculation
    lease_end_date = Column(Date, nullable=True)

    # Rent info
    current_rent = Column(Numeric(10, 2), nullable=True)
    proposed_rent = Column(Numeric(10, 2), nullable=True)
    voucher_amount = Column(Numeric(10, 2), nullable=True)  # Section 8 voucher amount

    # Notes
    notes = Column(Text, nullable=True)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    property_ref = relationship("Property", back_populates="tenants")
    pha = relationship("PHA", back_populates="tenants")
    notifications = relationship("Notification", back_populates="tenant")
    recertifications = relationship("Recertification", back_populates="tenant")

    # Indexes
    __table_args__ = (
        Index("ix_tenants_property_active", "property_id", "is_active"),
    )

    def __repr__(self):
        return f"<Tenant {self.name} @ Property {self.property_id}>"

    @property
    def recert_eligible_date(self):
        """Calculate when recertification can be submitted (9 months after lease start)"""
        if self.lease_start_date:
            from dateutil.relativedelta import relativedelta
            return self.lease_start_date + relativedelta(months=9)
        return None

    @property
    def days_until_recert(self):
        """Days until recertification is eligible"""
        if self.recert_eligible_date:
            delta = self.recert_eligible_date - datetime.now().date()
            return delta.days
        return None


class Notification(Base):
    """Notification log for SMS/Email tracking"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    bill_id = Column(Integer, ForeignKey("water_bills.id", ondelete="SET NULL"), nullable=True)

    # Message details
    channel = Column(Enum(NotificationChannel), nullable=False)
    recipient = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)

    # Status tracking
    status = Column(Enum(NotificationStatus), default=NotificationStatus.PENDING)
    external_id = Column(String(100), nullable=True)  # Twilio SID or SendGrid ID
    sent_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="notifications")
    property = relationship("Property", back_populates="notifications")
    bill = relationship("WaterBill", back_populates="notifications")

    # Indexes
    __table_args__ = (
        Index("ix_notifications_status", "status"),
        Index("ix_notifications_created", "created_at"),
    )

    def __repr__(self):
        return f"<Notification {self.channel.value} to {self.recipient} - {self.status.value}>"


class PropertyTax(Base):
    """Property tax records"""
    __tablename__ = "property_taxes"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)

    # Tax details
    tax_year = Column(Integer, nullable=False)
    amount_due = Column(Numeric(10, 2), nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=True)  # paid, due, delinquent
    parcel_number = Column(String(50), nullable=True)

    # Tracking
    scraped_at = Column(DateTime, default=datetime.utcnow)
    raw_data = Column(Text, nullable=True)

    # Relationships
    property = relationship("Property", back_populates="taxes")

    # Indexes
    __table_args__ = (
        Index("ix_property_taxes_property_year", "property_id", "tax_year"),
    )

    def __repr__(self):
        return f"<PropertyTax {self.tax_year} - ${self.amount_due}>"


# =============================================================================
# PHA & Recertification Models
# =============================================================================

class RecertStatus(PyEnum):
    """Recertification status"""
    PENDING = "pending"          # Not yet eligible
    ELIGIBLE = "eligible"        # 9 months reached, can submit
    SUBMITTED = "submitted"      # Request sent to PHA
    IN_REVIEW = "in_review"      # PHA reviewing
    APPROVED = "approved"        # Rent increase approved
    DENIED = "denied"            # Rent increase denied
    COMPLETED = "completed"      # Process complete


class PHA(Base):
    """Public Housing Authority information"""
    __tablename__ = "phas"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)

    # Contact info
    contact_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    fax = Column(String(20), nullable=True)

    # Address
    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(2), nullable=True)
    zip_code = Column(String(10), nullable=True)

    # Additional info
    website = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    recertifications = relationship("Recertification", back_populates="pha")
    tenants = relationship("Tenant", back_populates="pha")

    def __repr__(self):
        return f"<PHA {self.name}>"


class Recertification(Base):
    """Recertification tracking for rent increases"""
    __tablename__ = "recertifications"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    pha_id = Column(Integer, ForeignKey("phas.id", ondelete="SET NULL"), nullable=True)

    # Rent details
    current_rent = Column(Numeric(10, 2), nullable=True)
    proposed_rent = Column(Numeric(10, 2), nullable=True)
    approved_rent = Column(Numeric(10, 2), nullable=True)

    # Dates
    lease_start_date = Column(Date, nullable=True)
    eligible_date = Column(Date, nullable=True)  # 9 months after lease start
    submitted_date = Column(Date, nullable=True)
    effective_date = Column(Date, nullable=True)  # When new rent starts

    # Status
    status = Column(Enum(RecertStatus), default=RecertStatus.PENDING)

    # Communication tracking
    last_email_sent = Column(DateTime, nullable=True)
    email_count = Column(Integer, default=0)

    # Notes and documents
    notes = Column(Text, nullable=True)
    pha_response = Column(Text, nullable=True)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="recertifications")
    property_ref = relationship("Property", back_populates="recertifications")
    pha = relationship("PHA", back_populates="recertifications")

    # Indexes
    __table_args__ = (
        Index("ix_recertifications_status", "status"),
        Index("ix_recertifications_eligible_date", "eligible_date"),
    )

    def __repr__(self):
        return f"<Recertification {self.tenant_id} - {self.status.value}>"

    @property
    def rent_increase(self):
        """Calculate proposed rent increase amount"""
        if self.current_rent and self.proposed_rent:
            return self.proposed_rent - self.current_rent
        return None

    @property
    def rent_increase_percent(self):
        """Calculate proposed rent increase percentage"""
        if self.current_rent and self.proposed_rent and self.current_rent > 0:
            return ((self.proposed_rent - self.current_rent) / self.current_rent) * 100
        return None
