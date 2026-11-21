"""Persisted workspace, commerce and planning records for ContextIQ V2."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import _id, now


class DemoSession(Base):
    __tablename__ = "demo_sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, unique=True, default=_id)
    buyer_id: Mapped[str] = mapped_column(String)
    seller_id: Mapped[str] = mapped_column(String)
    csrf: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Personalization(Base):
    __tablename__ = "personalization"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class InvoiceSnapshot(Base):
    __tablename__ = "invoice_snapshots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    buyer_id: Mapped[str] = mapped_column(String)
    seller_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, default="itemized")
    items: Mapped[list] = mapped_column(JSON)
    total_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String, default="INR")
    purpose: Mapped[str] = mapped_column(String, default="personal")
    policy: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="open")
    qr_token: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String)
    case_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    approval_token: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    buyer_id: Mapped[str] = mapped_column(String, index=True)
    seller_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_minor: Mapped[int] = mapped_column(Integer)
    delivered_quantity: Mapped[int] = mapped_column(Integer, default=0)
    refunded_quantity: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String, default="awaiting_shipment")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request: Mapped[str] = mapped_column(String, default="")


class PaymentIncident(Base):
    __tablename__ = "payment_incidents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String, index=True)
    case_id: Mapped[str] = mapped_column(String, unique=True)
    provider: Mapped[str] = mapped_column(String, default="mock")
    status: Mapped[str] = mapped_column(String, default="checking")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlanningRecord(Base):
    """User-authored goal, allocation or financing schedule, with a validated kind."""
    __tablename__ = "planning_records"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(String, default="personal")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[str] = mapped_column(String)
    destination: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PriceWatch(Base):
    __tablename__ = "v2_price_watches"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(String, index=True)
    source_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String)
    merchant: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    source_key: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    current_minor: Mapped[int] = mapped_column(Integer)
    low_minor: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(String, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PriceSample(Base):
    __tablename__ = "v2_price_samples"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    watch_id: Mapped[str] = mapped_column(String, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProviderCheckout(Base):
    __tablename__ = "v2_provider_checkouts"
    invoice_id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(String, unique=True)
    method: Mapped[str] = mapped_column(String)
    payment_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)


class Customer(Base):
    """A seller's client. Owned by the workspace buyer id; scoped on every query."""
    __tablename__ = "seller_customers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    phone: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, default="")
    usual_payment_delay_days: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SellerInvoice(Base):
    """Seller-issued invoice. Overdue is computed at read time; only stored states live here."""
    __tablename__ = "seller_invoices"
    __table_args__ = (UniqueConstraint("owner_id", "number", name="uq_seller_invoice_number"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    customer_id: Mapped[str] = mapped_column(String, ForeignKey("seller_customers.id"), index=True)
    number: Mapped[str] = mapped_column(String)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String, default="INR")
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | sent | part_paid | paid | cancelled
    total_minor: Mapped[int] = mapped_column(Integer)
    amount_paid_minor: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SellerInvoiceLine(Base):
    __tablename__ = "seller_invoice_lines"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    invoice_id: Mapped[str] = mapped_column(String, ForeignKey("seller_invoices.id"), index=True)
    description: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_minor: Mapped[int] = mapped_column(Integer)
    amount_minor: Mapped[int] = mapped_column(Integer)


class SellerPayment(Base):
    __tablename__ = "seller_payments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    invoice_id: Mapped[str] = mapped_column(String, ForeignKey("seller_invoices.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String, default="upi")
    reference: Mapped[str] = mapped_column(String, default="")
    received_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SellerBill(Base):
    """Recurring or one-off business bill. recurrence is 'none' or 'monthly'."""
    __tablename__ = "seller_bills"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    recurrence: Mapped[str] = mapped_column(String, default="none")
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SellerBillPayment(Base):
    __tablename__ = "seller_bill_payments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    bill_id: Mapped[str] = mapped_column(String, ForeignKey("seller_bills.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    paid_on: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
