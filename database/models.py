"""Database models for Water Bill Tracker"""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Date,
    ForeignKey, Text, Enum, Boolean, Index, Float
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


class WorkOrderStatus(PyEnum):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CLOSED = "closed"


class WorkOrderPriority(PyEnum):
    EMERGENCY = "emergency"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class WorkOrderCategory(PyEnum):
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    HVAC = "hvac"
    APPLIANCE = "appliance"
    STRUCTURAL = "structural"
    PEST_CONTROL = "pest_control"
    GENERAL = "general"


class LeaseStatus(PyEnum):
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    RENEWED = "renewed"
    TERMINATED = "terminated"


class InvoiceStatus(PyEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class ProjectStatus(PyEnum):
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"


class PaymentStatus(PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class AutopayStatus(PyEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class LeaseBuilderStatus(PyEnum):
    DRAFT = "draft"
    GENERATED = "generated"
    SENT = "sent"
    SIGNED = "signed"
    VOIDED = "voided"


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

    # Entity/Portfolio ownership
    entity = Column(String(100), nullable=True)  # Silo Capital LLC, Silo Partners LLC, etc.

    # Occupancy status
    is_vacant = Column(Boolean, default=False)

    # Public listing fields
    description = Column(Text, nullable=True)  # Property description for public listing
    monthly_rent = Column(Numeric(10, 2), nullable=True)  # Advertised rent for vacant units
    is_listed = Column(Boolean, default=False)  # Show on public website
    featured_photo_url = Column(String(500), nullable=True)  # Main photo URL

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

    # Certificate of Occupancy (CO) inspections
    co_mechanical_date = Column(Date, nullable=True)
    co_mechanical_time = Column(String(10), nullable=True)  # e.g., "09:00 AM"
    co_mechanical_status = Column(String(20), nullable=True)  # "passed" or "failed"
    co_electrical_date = Column(Date, nullable=True)
    co_electrical_time = Column(String(10), nullable=True)
    co_electrical_status = Column(String(20), nullable=True)
    co_plumbing_date = Column(Date, nullable=True)
    co_plumbing_time = Column(String(10), nullable=True)
    co_plumbing_status = Column(String(20), nullable=True)
    co_zoning_date = Column(Date, nullable=True)
    co_zoning_time = Column(String(10), nullable=True)
    co_zoning_status = Column(String(20), nullable=True)
    co_building_date = Column(Date, nullable=True)
    co_building_time = Column(String(10), nullable=True)
    co_building_status = Column(String(20), nullable=True)

    # Rental inspection
    rental_inspection_date = Column(Date, nullable=True)
    rental_inspection_time = Column(String(10), nullable=True)

    # Section 8 inspection time
    section8_inspection_time = Column(String(10), nullable=True)

    # Lease dates (for recertification tracking)
    lease_start_date = Column(Date, nullable=True)
    lease_end_date = Column(Date, nullable=True)

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
    sms_messages = relationship("SMSMessage", back_populates="property", order_by="SMSMessage.created_at")
    photos = relationship("PropertyPhoto", back_populates="property", order_by="PropertyPhoto.display_order")
    work_orders = relationship("WorkOrder", back_populates="property_ref", order_by="desc(WorkOrder.created_at)")
    lease_documents = relationship("LeaseDocument", back_populates="property_ref", order_by="desc(LeaseDocument.created_at)")
    violations = relationship("InspectionViolation", back_populates="property", order_by="desc(InspectionViolation.violation_date)")

    def __repr__(self):
        return f"<Property {self.address} ({self.bsa_account_number})>"

    @property
    def latest_bill(self):
        """Get the most recent bill"""
        return self.bills[0] if self.bills else None

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


class InspectionViolation(Base):
    """Inspection violation record with uploaded PDF"""
    __tablename__ = "inspection_violations"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    description = Column(String(255), nullable=True)
    violation_date = Column(Date, nullable=True)
    file_url = Column(String(500), nullable=True)
    original_filename = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    property = relationship("Property", back_populates="violations")

    def __repr__(self):
        return f"<InspectionViolation {self.id} - {self.description}>"


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


class MessageDirection(PyEnum):
    """SMS message direction"""
    INBOUND = "inbound"    # From tenant to us
    OUTBOUND = "outbound"  # From us to tenant


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
    tenant_portion = Column(Numeric(10, 2), nullable=True)  # Tenant's portion of rent

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
    sms_messages = relationship("SMSMessage", back_populates="tenant", order_by="SMSMessage.created_at")
    work_orders = relationship("WorkOrder", back_populates="tenant_ref", order_by="desc(WorkOrder.created_at)")
    lease_documents = relationship("LeaseDocument", back_populates="tenant_ref", order_by="desc(LeaseDocument.created_at)")
    bank_accounts = relationship("TenantBankAccount", back_populates="tenant_ref", order_by="desc(TenantBankAccount.linked_at)")
    rent_payments = relationship("RentPayment", back_populates="tenant_ref", order_by="desc(RentPayment.initiated_at)")
    autopay = relationship("TenantAutopay", back_populates="tenant_ref", uselist=False)

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


# =============================================================================
# SMS Conversation Models
# =============================================================================

class SMSMessage(Base):
    """SMS message for bidirectional conversation tracking"""
    __tablename__ = "sms_messages"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)

    # Phone numbers (E.164 format: +12481234567)
    from_number = Column(String(20), nullable=False)
    to_number = Column(String(20), nullable=False)

    # Message content
    body = Column(Text, nullable=False)
    direction = Column(Enum(MessageDirection), nullable=False)

    # Twilio tracking
    twilio_sid = Column(String(50), nullable=True)  # Twilio message SID
    status = Column(String(20), default="sent")  # sent, delivered, failed, received

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="sms_messages")
    property = relationship("Property", back_populates="sms_messages")

    # Indexes for fast conversation lookups
    __table_args__ = (
        Index("ix_sms_messages_tenant", "tenant_id"),
        Index("ix_sms_messages_from_number", "from_number"),
        Index("ix_sms_messages_created", "created_at"),
    )

    def __repr__(self):
        return f"<SMSMessage {self.direction.value} {self.from_number} -> {self.to_number}>"


# =============================================================================
# Property Photos
# =============================================================================

class PropertyPhoto(Base):
    """Photos for property listings"""
    __tablename__ = "property_photos"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)

    # Photo details
    url = Column(String(500), nullable=False)  # URL or file path
    caption = Column(String(255), nullable=True)
    display_order = Column(Integer, default=0)  # For ordering photos
    is_primary = Column(Boolean, default=False)  # Main photo for listings
    is_starred = Column(Boolean, default=False)  # Featured/favorite photos

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    property = relationship("Property", back_populates="photos")

    def __repr__(self):
        return f"<PropertyPhoto {self.id} for Property {self.property_id}>"


# =============================================================================
# Maintenance / Work Order Models
# =============================================================================

class Vendor(Base):
    """Maintenance vendors/contractors"""
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    specialty = Column(String(100), nullable=True)
    company = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    work_orders = relationship("WorkOrder", back_populates="vendor_ref")
    invoices = relationship("Invoice", back_populates="vendor_ref")
    projects = relationship("Project", back_populates="vendor_ref")

    def __repr__(self):
        return f"<Vendor {self.name}>"


class WorkOrder(Base):
    """Maintenance work orders"""
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # Work order details
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(Enum(WorkOrderCategory), default=WorkOrderCategory.GENERAL)
    priority = Column(Enum(WorkOrderPriority), default=WorkOrderPriority.NORMAL)
    status = Column(Enum(WorkOrderStatus), default=WorkOrderStatus.NEW)
    unit_area = Column(String(100), nullable=True)

    # Scheduling
    scheduled_date = Column(Date, nullable=True)
    completed_date = Column(Date, nullable=True)

    # Cost tracking
    estimated_cost = Column(Numeric(10, 2), nullable=True)
    actual_cost = Column(Numeric(10, 2), nullable=True)

    # Resolution
    resolution_notes = Column(Text, nullable=True)

    # Tenant submission flag
    submitted_by_tenant = Column(Boolean, default=False)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    property_ref = relationship("Property", back_populates="work_orders")
    tenant_ref = relationship("Tenant", back_populates="work_orders")
    vendor_ref = relationship("Vendor", back_populates="work_orders")
    project = relationship("Project", back_populates="work_orders")
    photos = relationship("WorkOrderPhoto", back_populates="work_order", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_work_orders_status", "status"),
        Index("ix_work_orders_property", "property_id"),
        Index("ix_work_orders_priority", "priority"),
    )

    def __repr__(self):
        return f"<WorkOrder {self.id}: {self.title}>"


class WorkOrderPhoto(Base):
    """Photos attached to work orders"""
    __tablename__ = "work_order_photos"

    id = Column(Integer, primary_key=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    caption = Column(String(255), nullable=True)
    uploaded_by_tenant = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    work_order = relationship("WorkOrder", back_populates="photos")

    def __repr__(self):
        return f"<WorkOrderPhoto {self.id} for WO {self.work_order_id}>"


# =============================================================================
# Lease Document Models
# =============================================================================

class LeaseDocument(Base):
    """Lease documents"""
    __tablename__ = "lease_documents"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)

    # Document info
    title = Column(String(255), nullable=False)
    file_url = Column(String(500), nullable=False)
    file_type = Column(String(20), nullable=True)
    file_size = Column(Integer, nullable=True)

    # Lease terms
    lease_start = Column(Date, nullable=True)
    lease_end = Column(Date, nullable=True)
    monthly_rent = Column(Numeric(10, 2), nullable=True)

    # Status
    status = Column(Enum(LeaseStatus), default=LeaseStatus.ACTIVE)
    notes = Column(Text, nullable=True)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    property_ref = relationship("Property", back_populates="lease_documents")
    tenant_ref = relationship("Tenant", back_populates="lease_documents")

    # Indexes
    __table_args__ = (
        Index("ix_lease_documents_status", "status"),
        Index("ix_lease_documents_property", "property_id"),
    )

    def __repr__(self):
        return f"<LeaseDocument {self.id}: {self.title}>"


# =============================================================================
# Tenant Portal Models
# =============================================================================

class TenantVerification(Base):
    """SMS verification codes for tenant portal login"""
    __tablename__ = "tenant_verifications"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    phone = Column(String(20), nullable=False)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant")

    def __repr__(self):
        return f"<TenantVerification {self.phone}>"


# =============================================================================
# Vendor Portal Models
# =============================================================================

class VendorVerification(Base):
    """SMS verification codes for vendor portal login"""
    __tablename__ = "vendor_verifications"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=True)
    phone = Column(String(20), nullable=False)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    vendor = relationship("Vendor")

    def __repr__(self):
        return f"<VendorVerification {self.phone}>"


# =============================================================================
# Invoice & Project Models
# =============================================================================

class Invoice(Base):
    """Vendor invoices for work performed"""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # Invoice details
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)
    file_url = Column(String(500), nullable=True)

    # Status
    status = Column(String(20), default=InvoiceStatus.SUBMITTED.value)

    # Timestamps
    submitted_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)

    # PM notes (approval/rejection reason)
    notes = Column(Text, nullable=True)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    vendor_ref = relationship("Vendor", back_populates="invoices")
    property_ref = relationship("Property")
    work_order_ref = relationship("WorkOrder")
    project_ref = relationship("Project", back_populates="invoices")

    # Indexes
    __table_args__ = (
        Index("ix_invoices_vendor", "vendor_id"),
        Index("ix_invoices_status", "status"),
        Index("ix_invoices_property", "property_id"),
    )

    def __repr__(self):
        return f"<Invoice {self.id}: {self.title} - ${self.amount}>"


class Project(Base):
    """Rehab/renovation projects grouping work orders and invoices"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True)

    # Project details
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), default=ProjectStatus.PLANNING.value)
    budget = Column(Numeric(10, 2), nullable=True)

    # Dates
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    completed_date = Column(Date, nullable=True)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    property_ref = relationship("Property")
    vendor_ref = relationship("Vendor", back_populates="projects")
    work_orders = relationship("WorkOrder", back_populates="project")
    invoices = relationship("Invoice", back_populates="project_ref")

    # Indexes
    __table_args__ = (
        Index("ix_projects_property", "property_id"),
        Index("ix_projects_status", "status"),
    )

    def __repr__(self):
        return f"<Project {self.id}: {self.name}>"

    @property
    def total_spent(self):
        """Sum of approved/paid invoice amounts"""
        return sum(
            float(inv.amount) for inv in self.invoices
            if inv.status in (InvoiceStatus.APPROVED.value, InvoiceStatus.PAID.value)
        ) if self.invoices else 0

    @property
    def budget_remaining(self):
        """Budget minus spent"""
        if self.budget:
            return float(self.budget) - self.total_spent
        return None

    @property
    def budget_percent(self):
        """Percentage of budget spent"""
        if self.budget and float(self.budget) > 0:
            return min(100, (self.total_spent / float(self.budget)) * 100)
        return 0


# =============================================================================
# Payment Models (Plaid ACH)
# =============================================================================

class TenantBankAccount(Base):
    """Plaid-linked bank accounts for tenants"""
    __tablename__ = "tenant_bank_accounts"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    # Plaid tokens
    plaid_access_token = Column(String(255), nullable=False)
    plaid_item_id = Column(String(255), nullable=False)
    plaid_account_id = Column(String(255), nullable=False)

    # Display info
    account_name = Column(String(255), nullable=True)
    account_mask = Column(String(4), nullable=True)
    institution_name = Column(String(255), nullable=True)

    # Status
    is_active = Column(Boolean, default=True)
    linked_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant_ref = relationship("Tenant", back_populates="bank_accounts")
    payments = relationship("RentPayment", back_populates="bank_account_ref")

    __table_args__ = (
        Index("ix_tenant_bank_accounts_tenant", "tenant_id"),
    )

    def __repr__(self):
        return f"<TenantBankAccount {self.institution_name} ...{self.account_mask}>"


class RentPayment(Base):
    """Rent payment records"""
    __tablename__ = "rent_payments"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    bank_account_id = Column(Integer, ForeignKey("tenant_bank_accounts.id", ondelete="SET NULL"), nullable=True)

    # Amounts
    amount = Column(Numeric(10, 2), nullable=False)
    late_fee = Column(Numeric(10, 2), default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)

    # Plaid transfer
    plaid_transfer_id = Column(String(255), nullable=True)
    plaid_transfer_status = Column(String(50), nullable=True)

    # Payment info
    payment_month = Column(Date, nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    is_autopay = Column(Boolean, default=False)

    # Timestamps
    initiated_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)

    # Relationships
    tenant_ref = relationship("Tenant", back_populates="rent_payments")
    property_ref = relationship("Property")
    bank_account_ref = relationship("TenantBankAccount", back_populates="payments")

    __table_args__ = (
        Index("ix_rent_payments_tenant", "tenant_id"),
        Index("ix_rent_payments_status", "status"),
        Index("ix_rent_payments_month", "payment_month"),
    )

    def __repr__(self):
        return f"<RentPayment ${self.total_amount} - {self.status.value}>"


class TenantAutopay(Base):
    """Autopay configuration per tenant"""
    __tablename__ = "tenant_autopay"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True)
    bank_account_id = Column(Integer, ForeignKey("tenant_bank_accounts.id", ondelete="SET NULL"), nullable=True)

    # Config
    status = Column(Enum(AutopayStatus), default=AutopayStatus.ACTIVE)
    pay_day = Column(Integer, default=1)
    amount = Column(Numeric(10, 2), nullable=True)  # null = use current_rent

    # Tracking
    last_payment_date = Column(Date, nullable=True)
    next_payment_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant_ref = relationship("Tenant", back_populates="autopay")
    bank_account_ref = relationship("TenantBankAccount")

    def __repr__(self):
        return f"<TenantAutopay tenant={self.tenant_id} status={self.status.value}>"


# =============================================================================
# Lease Builder Models
# =============================================================================

class LeaseBuilder(Base):
    """Lease builder wizard state and data"""
    __tablename__ = "lease_builders"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)

    # Wizard state
    current_step = Column(Integer, default=1)
    status = Column(Enum(LeaseBuilderStatus), default=LeaseBuilderStatus.DRAFT)

    # All lease form data as JSON
    lease_data = Column(Text, nullable=True)

    # Generated document link
    lease_document_id = Column(Integer, ForeignKey("lease_documents.id", ondelete="SET NULL"), nullable=True)
    generated_at = Column(DateTime, nullable=True)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    property_ref = relationship("Property")
    tenant_ref = relationship("Tenant")
    lease_document_ref = relationship("LeaseDocument")

    __table_args__ = (
        Index("ix_lease_builders_status", "status"),
        Index("ix_lease_builders_property", "property_id"),
    )

    def __repr__(self):
        return f"<LeaseBuilder {self.id} step={self.current_step} status={self.status.value}>"


class EntityConfig(Base):
    """Landlord entity configuration for lease auto-fill"""
    __tablename__ = "entity_configs"

    id = Column(Integer, primary_key=True)
    entity_name = Column(String(255), unique=True, nullable=False)
    owner_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    mailing_address = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False)

    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<EntityConfig {self.entity_name}>"
