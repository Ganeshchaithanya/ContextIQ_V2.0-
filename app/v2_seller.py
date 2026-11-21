"""Seller back office for a freelancer or micro-business: customers, invoices, payments, bills and cash forecast.

Every query is scoped to the session's buyer id (the owner); other owners' records return 404.
Money is stored in paise (minor units). Business dates use Indian time (UTC+05:30).
Overdue status and days overdue are computed at read time from the due date and the open balance.
"""
from __future__ import annotations

import calendar
import hashlib
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from .config import settings
from .models import LedgerEntry, User, now
from .v2 import WRITE_LOCK, db_dep, fail, router, session
from .v2_models import Customer, Personalization, PlanningRecord, SellerBill, SellerBillPayment, SellerInvoice, SellerInvoiceLine, SellerPayment

OPEN_STATUSES = ("sent", "part_paid")
MAX_TOTAL_MINOR = 1_000_000_000


def today() -> date:
    return (now() + timedelta(hours=5, minutes=30)).date()


def rupees(minor: int) -> str:
    """Indian digit grouping, e.g. 140000 paise -> '₹1,400.00' and 1400000 paise -> '₹14,000.00'."""
    sign = "-" if minor < 0 else ""
    whole, paise = divmod(abs(minor), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}.{paise:02d}"


def add_months(base: date, months: int) -> date:
    total = base.month - 1 + months
    year, month = base.year + total // 12, total % 12 + 1
    return date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


# ---------- request models ----------

class SettingsIn(BaseModel):
    upi_vpa: str = Field(min_length=5, max_length=80, pattern=r"^[\w.\-]+@[\w.\-]+$")
    payee_name: str = Field(min_length=1, max_length=60)
    opening_balance_minor: int = Field(ge=-100_000_000_000, le=100_000_000_000)


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=120)
    usual_payment_delay_days: int = Field(default=0, ge=0, le=120)


class LineIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=10000)
    unit_price_minor: int = Field(ge=1, le=1_000_000_000)


class InvoiceIn(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    issue_date: date | None = None
    due_date: date | None = None
    lines: list[LineIn] = Field(min_length=1, max_length=50)


class PaymentIn(BaseModel):
    amount_minor: int = Field(gt=0, le=1_000_000_000)
    method: Literal["upi", "bank", "cash", "cheque"] = "upi"
    reference: str = Field(default="", max_length=80)
    received_on: date | None = None
    request_id: str | None = Field(default=None, min_length=8, max_length=80)


class BillIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount_minor: int = Field(gt=0, le=1_000_000_000)
    due_date: date
    recurrence: Literal["none", "monthly"] = "none"


class BillPaymentIn(BaseModel):
    confirmed: bool
    request_id: str = Field(min_length=8, max_length=80)


# ---------- shared helpers ----------

def owned(db, model, ident: str, owner: str, message: str):
    row = db.scalar(select(model).where(model.id == ident, model.owner_id == owner).with_for_update())
    if not row or row.owner_id != owner:
        fail(404, message)
    return row


def seller_settings(db, owner: str) -> dict:
    row = db.get(Personalization, owner)
    stored = (row.data if row else {}).get("seller", {})
    return {"upi_vpa": stored.get("upi_vpa", settings.seller_upi_vpa),
            "payee_name": stored.get("payee_name", settings.seller_payee_name),
            "opening_balance_minor": stored.get("opening_balance_minor", 0)}


def customers_by_id(db, owner: str) -> dict:
    return {c.id: c for c in db.scalars(select(Customer).where(Customer.owner_id == owner))}


def open_invoices(db, owner: str) -> list:
    rows = db.scalars(select(SellerInvoice).where(SellerInvoice.owner_id == owner, SellerInvoice.status.in_(OPEN_STATUSES)))
    return [row for row in rows if row.total_minor > row.amount_paid_minor]


def open_state(row, as_of: date):
    """Return (balance_minor, days_overdue, is_open). days_overdue is 0 when not yet past due."""
    balance = row.total_minor - row.amount_paid_minor
    is_open = row.status in OPEN_STATUSES and balance > 0
    days = max(0, (as_of - row.due_date).days) if is_open else 0
    return balance, days, is_open


def next_invoice_number(db, owner: str) -> str:
    count = db.scalar(select(func.count()).select_from(SellerInvoice).where(SellerInvoice.owner_id == owner)) or 0
    return f"INV-{count + 1:04d}"


def customer_view(row, outstanding_minor: int) -> dict:
    return {"id": row.id, "name": row.name, "phone": row.phone, "email": row.email,
            "usual_payment_delay_days": row.usual_payment_delay_days, "outstanding_minor": outstanding_minor}


def invoice_view(db, row, customer, as_of: date, detail: bool = False) -> dict:
    balance, days, _ = open_state(row, as_of)
    data = {"id": row.id, "number": row.number, "customer": {"id": customer.id, "name": customer.name},
            "issue_date": row.issue_date.isoformat(), "due_date": row.due_date.isoformat(), "status": row.status,
            "currency": row.currency, "total_minor": row.total_minor, "paid_minor": row.amount_paid_minor,
            "balance_minor": balance, "overdue": days > 0, "days_overdue": days}
    if detail:
        data["lines"] = [{"id": line.id, "description": line.description, "quantity": line.quantity,
                          "unit_price_minor": line.unit_price_minor, "amount_minor": line.amount_minor}
                         for line in db.scalars(select(SellerInvoiceLine).where(SellerInvoiceLine.invoice_id == row.id))]
        data["payments"] = [{"id": p.id, "amount_minor": p.amount_minor, "method": p.method, "reference": p.reference,
                             "received_on": p.received_on.isoformat()}
                            for p in db.scalars(select(SellerPayment).where(SellerPayment.invoice_id == row.id))]
        data["share_text"] = (f"{seller_settings(db, row.owner_id)['payee_name']}\nInvoice {row.number}\n"
                              f"Client: {customer.name}\nDue: {row.due_date.isoformat()}\n"
                              + "\n".join(f"{line['description']} — {line['quantity']} × {rupees(line['unit_price_minor'])}"
                                          for line in data["lines"])
                              + f"\nTotal: {rupees(row.total_minor)}\nBalance: {rupees(balance)}")
    return data


def bill_view(row) -> dict:
    return {"id": row.id, "name": row.name, "amount_minor": row.amount_minor, "due_date": row.due_date.isoformat(),
            "recurrence": row.recurrence, "paid": row.paid}


def bill_offsets(due: date, recurrence: str, as_of: date, horizon: int) -> list[int]:
    """Day offsets (from as_of) on which a bill falls due within the horizon."""
    end = as_of + timedelta(days=horizon)
    if recurrence == "none":
        candidates = [max(due, as_of)]
    else:
        candidates = [as_of] if due < as_of else []
        k = max(0, (as_of.year - due.year) * 12 + as_of.month - due.month)
        while True:
            occurrence = add_months(due, k)
            k += 1
            if occurrence >= end:
                break
            if occurrence >= as_of:
                candidates.append(occurrence)
    return [(d - as_of).days for d in candidates if d < end]


def sync_business_ledger(db, owner):
    """Bring existing and new seller records into the same ledger as purchases and budgets."""
    profile = db.get(Personalization, owner)
    if not profile:
        return
    if profile.data.get("persona") != "freelancer" and "seller" not in profile.data:
        if not db.scalar(select(SellerPayment.id).where(SellerPayment.owner_id == owner).limit(1)) and not db.scalar(
                select(SellerBillPayment.id).where(SellerBillPayment.owner_id == owner).limit(1)):
            return
    # Acquire a write lock before reading posted entries on SQLite and PostgreSQL.
    db.execute(update(Personalization).where(Personalization.user_id == owner).values(data=Personalization.data))
    db.refresh(profile)
    prefix = f"studio:{owner}:"
    posted = {row.settlement_key: row for row in db.scalars(select(LedgerEntry).where(
        LedgerEntry.user_id == owner, LedgerEntry.settlement_key.startswith(prefix)))}
    opening_key = prefix + "opening"
    opening_minor = -seller_settings(db, owner)["opening_balance_minor"]
    opening = posted.get(opening_key)
    if opening:
        opening.amount_minor, opening.amount = opening_minor, opening_minor / 100
    else:
        db.add(LedgerEntry(user_id=owner, payee="Business opening balance", description="Starting business cash",
            category="opening", purpose="business", currency="INR", amount_minor=opening_minor,
            amount=opening_minor / 100, source="studio_opening", settlement_key=opening_key,
            occurred_at=datetime.combine(today() - timedelta(days=3650), time.min, UTC)))
    for payment in db.scalars(select(SellerPayment).where(SellerPayment.owner_id == owner)):
        key = prefix + "receipt:" + payment.id
        if key not in posted:
            invoice = db.get(SellerInvoice, payment.invoice_id)
            customer = db.get(Customer, invoice.customer_id)
            db.add(LedgerEntry(user_id=owner, payee=customer.name, description=f"Receipt for {invoice.number}",
                category="sales", purpose="business", currency="INR", amount_minor=-payment.amount_minor,
                amount=-payment.amount_minor / 100, source="owner_confirmed_receipt", settlement_key=key,
                occurred_at=datetime.combine(payment.received_on, time.min, UTC)))
    for payment in db.scalars(select(SellerBillPayment).where(SellerBillPayment.owner_id == owner)):
        key = prefix + "bill:" + payment.id
        if key not in posted:
            bill = db.get(SellerBill, payment.bill_id)
            db.add(LedgerEntry(user_id=owner, payee=bill.name, description=f"Bill paid: {bill.name}",
                category="operating", purpose="business", currency="INR", amount_minor=payment.amount_minor,
                amount=payment.amount_minor / 100, source="owner_confirmed_bill", settlement_key=key,
                occurred_at=datetime.combine(payment.paid_on, time.min, UTC)))
    db.flush()
    if profile.data.get("persona") == "freelancer":
        total = db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_minor), 0)).where(
            LedgerEntry.user_id == owner, LedgerEntry.purpose == "business", LedgerEntry.currency == "INR"))
        db.get(User, owner).available_balance = -total / 100


def cash_position(db, owner, as_of):
    from . import finance
    return finance.summary(db, owner, "business")["balance_minor"]


def build_forecast(db, owner: str, horizon: int, delay_days: int = 0, customer_id: str | None = None) -> dict:
    """When customer_id is given, the delay applies only to that customer's open invoices."""
    as_of = today()
    customers = customers_by_id(db, owner)
    inflows, outflows = [0] * horizon, [0] * horizon
    for row in open_invoices(db, owner):
        balance = row.total_minor - row.amount_paid_minor
        customer = customers[row.customer_id]
        shift = delay_days if customer_id is None or row.customer_id == customer_id else 0
        expected = max(row.due_date + timedelta(days=customer.usual_payment_delay_days), as_of) + timedelta(days=shift)
        offset = (expected - as_of).days
        if offset < horizon:
            inflows[offset] += balance
    for bill in db.scalars(select(SellerBill).where(SellerBill.owner_id == owner)):
        if bill.paid:
            continue
        for offset in bill_offsets(bill.due_date, bill.recurrence, as_of, horizon):
            outflows[offset] += bill.amount_minor
    current_cash = cash_position(db, owner, as_of)
    balance = current_cash
    days, min_balance, min_date, first_negative = [], None, None, None
    for i in range(horizon):
        balance += inflows[i] - outflows[i]
        day = as_of + timedelta(days=i)
        days.append({"date": day.isoformat(), "inflow_minor": inflows[i], "outflow_minor": outflows[i], "balance_minor": balance})
        if min_balance is None or balance < min_balance:
            min_balance, min_date = balance, day
        if balance < 0 and first_negative is None:
            first_negative = day
    return {"as_of": as_of.isoformat(), "horizon_days": horizon, "opening_minor": current_cash,
            "days": days, "min_balance_minor": min_balance, "min_balance_date": min_date.isoformat(),
            "first_negative_date": first_negative.isoformat() if first_negative else None,
            "ending_balance_minor": balance, "receipts_minor": sum(inflows), "bills_minor": sum(outflows)}


def forecast_summary(forecast: dict) -> dict:
    return {"min_balance_minor": forecast["min_balance_minor"], "min_balance_date": forecast["min_balance_date"],
            "first_negative_date": forecast["first_negative_date"], "ending_balance_minor": forecast["ending_balance_minor"]}


def reminder_for(db, owner: str, row, tone: str, as_of: date) -> dict:
    balance, days, is_open = open_state(row, as_of)
    if not is_open:
        fail(409, "Nothing is outstanding on this invoice")
    customer = db.get(Customer, row.customer_id)
    cfg = seller_settings(db, owner)
    amount = f"{balance / 100:.2f}"
    tn = quote(f"Invoice {row.number}")
    upi_link = (f"upi://pay?pa={quote(cfg['upi_vpa'], safe='@')}&pn={quote(cfg['payee_name'])}"
                f"&am={amount}&cu=INR&tn={tn}")
    work = db.scalar(select(SellerInvoiceLine.description).where(SellerInvoiceLine.invoice_id == row.id).limit(1)) or "your project"
    due = row.due_date.strftime("%d %b %Y")
    if days:
        timing = f"Payment was due on {due} and is now {days} {'day' if days == 1 else 'days'} overdue."
    elif row.due_date == as_of:
        timing = f"Payment is due today, {due}."
    else:
        timing = f"Payment is due on {due}."
    if tone == "firm":
        request = ("Please pay today or reply with the date you can pay." if days
                   else "Please pay by the due date and let me know once you have paid.")
    else:
        request = ("Please let me know when you can pay. I am happy to help if you need any details." if days
                   else "Please pay by the due date. Let me know if you need any details.")
    text = (f"Hello {customer.name},\n\n"
            f"Invoice {row.number} is for {work}.\n"
            f"The amount still due is {rupees(balance)}.\n"
            f"{timing}\n\n{request}\n\n"
            f"You can pay {rupees(balance)} using your UPI app. Send it to {cfg['upi_vpa']}.\n\n"
            f"Thank you,\n{cfg['payee_name']}")
    digits = "".join(ch for ch in customer.phone if ch.isdigit())
    whatsapp_url = None
    if digits:
        if len(digits) == 10:
            digits = "91" + digits
        whatsapp_url = f"https://wa.me/{digits}?text={quote(text)}"
    return {"invoice_id": row.id, "number": row.number, "tone": tone, "text": text, "upi_link": upi_link,
            "demo_recipient": cfg["upi_vpa"] == settings.seller_upi_vpa,
            "amount_minor": balance, "whatsapp_url": whatsapp_url}


def alert(ident: str, kind: str, priority: int, action: str, detail: str, invoice_id=None, reminder=None) -> dict:
    return {"id": ident, "kind": kind, "priority": priority, "action": action, "detail": detail,
            "invoice_id": invoice_id, "reminder": reminder}


# ---------- settings ----------

@router.get("/seller/settings")
def get_seller_settings(current=Depends(session), db=Depends(db_dep)):
    return seller_settings(db, current.buyer_id)


@router.put("/seller/settings")
def put_seller_settings(body: SettingsIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = db.get(Personalization, current.buyer_id)
        if not row:
            fail(404, "Seller profile not found")
        row.data = row.data | {"seller": body.model_dump()}
        db.commit()
    return seller_settings(db, current.buyer_id)


# ---------- customers ----------

@router.post("/seller/customers")
def add_customer(body: CustomerIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = Customer(owner_id=current.buyer_id, **body.model_dump())
        db.add(row)
        db.commit()
    return customer_view(row, 0)


@router.get("/seller/customers")
def list_customers(current=Depends(session), db=Depends(db_dep)):
    outstanding = defaultdict(int)
    for row in open_invoices(db, current.buyer_id):
        outstanding[row.customer_id] += row.total_minor - row.amount_paid_minor
    rows = sorted(customers_by_id(db, current.buyer_id).values(), key=lambda c: c.name.lower())
    return [customer_view(row, outstanding[row.id]) for row in rows]


# ---------- invoices ----------

@router.post("/seller/invoices")
def create_invoice(body: InvoiceIn, current=Depends(session), db=Depends(db_dep)):
    owner = current.buyer_id
    with WRITE_LOCK:
        customer = owned(db, Customer, body.customer_id, owner, "Customer not found")
        issue = body.issue_date or today()
        due = body.due_date or issue + timedelta(days=15)
        if due < issue:
            fail(422, "Due date cannot be before the issue date")
        total = sum(line.quantity * line.unit_price_minor for line in body.lines)
        if total > MAX_TOTAL_MINOR:
            fail(422, "Invoice total is too large")
        row = SellerInvoice(owner_id=owner, customer_id=customer.id, number=next_invoice_number(db, owner),
                            issue_date=issue, due_date=due, total_minor=total)
        db.add(row)
        db.flush()
        for line in body.lines:
            db.add(SellerInvoiceLine(invoice_id=row.id, description=line.description, quantity=line.quantity,
                                     unit_price_minor=line.unit_price_minor,
                                     amount_minor=line.quantity * line.unit_price_minor))
        db.commit()
        return invoice_view(db, row, customer, today(), detail=True)


@router.get("/seller/invoices")
def list_invoices(current=Depends(session), db=Depends(db_dep)):
    as_of, owner = today(), current.buyer_id
    customers = customers_by_id(db, owner)
    rows = sorted(db.scalars(select(SellerInvoice).where(SellerInvoice.owner_id == owner)), key=lambda r: r.number)
    return [invoice_view(db, row, customers[row.customer_id], as_of) for row in rows]


@router.get("/seller/invoices/{ident}")
def get_invoice(ident: str, current=Depends(session), db=Depends(db_dep)):
    row = owned(db, SellerInvoice, ident, current.buyer_id, "Invoice not found")
    return invoice_view(db, row, db.get(Customer, row.customer_id), today(), detail=True)


@router.post("/seller/invoices/{ident}/send")
def send_invoice(ident: str, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = owned(db, SellerInvoice, ident, current.buyer_id, "Invoice not found")
        if row.status != "draft":
            fail(409, "Only a draft invoice can be sent")
        row.status = "sent"
        db.commit()
        return invoice_view(db, row, db.get(Customer, row.customer_id), today(), detail=True)


@router.post("/seller/invoices/{ident}/payments")
def record_payment(ident: str, body: PaymentIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = owned(db, SellerInvoice, ident, current.buyer_id, "Invoice not found")
        received = body.received_on or today()
        if received > today() or received < row.issue_date:
            fail(422, "Use a received date from the invoice issue date through today")
        key = hashlib.sha256(f"seller-receipt:{current.buyer_id}:{body.request_id}".encode()).hexdigest() if body.request_id else None
        payload = {"invoice": ident, **body.model_dump(mode="json", exclude={"request_id"})}
        replay = db.get(PlanningRecord, key) if key else None
        if replay:
            if replay.data != payload:
                fail(409, "This receipt request already recorded different payment details")
            return invoice_view(db, row, db.get(Customer, row.customer_id), today(), detail=True)
        reference = body.reference.strip()
        if reference and body.method in ("upi", "bank"):
            db.execute(update(Personalization).where(Personalization.user_id == current.buyer_id).values(data=Personalization.data))
            duplicate = db.scalar(select(SellerPayment.id).where(
                SellerPayment.owner_id == current.buyer_id, SellerPayment.method == body.method,
                func.lower(func.trim(SellerPayment.reference)) == reference.lower()).limit(1))
            if duplicate:
                fail(409, "This payment reference is already recorded. Review the existing receipt before adding another.")
        if row.status not in OPEN_STATUSES:
            fail(409, "Payments can only be recorded on a sent invoice")
        balance = row.total_minor - row.amount_paid_minor
        if body.amount_minor > balance:
            fail(422, f"Payment of {rupees(body.amount_minor)} exceeds the balance of {rupees(balance)}")
        db.add(SellerPayment(owner_id=current.buyer_id, invoice_id=row.id, amount_minor=body.amount_minor,
                             method=body.method, reference=reference, received_on=received))
        if key:
            db.add(PlanningRecord(id=key, user_id=current.buyer_id, kind="seller_receipt", title=row.number, data=payload))
        row.amount_paid_minor += body.amount_minor
        row.status = "paid" if row.amount_paid_minor == row.total_minor else "part_paid"
        db.commit()
        return invoice_view(db, row, db.get(Customer, row.customer_id), today(), detail=True)


@router.post("/seller/invoices/{ident}/cancel")
def cancel_invoice(ident: str, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = owned(db, SellerInvoice, ident, current.buyer_id, "Invoice not found")
        if row.status not in ("draft", "sent") or row.amount_paid_minor:
            fail(409, "Only an unpaid draft or sent invoice can be cancelled")
        row.status = "cancelled"
        db.commit()
        return invoice_view(db, row, db.get(Customer, row.customer_id), today(), detail=True)


@router.get("/seller/invoices/{ident}/reminder")
def invoice_reminder(ident: str, tone: Literal["friendly", "firm"] = "friendly", current=Depends(session), db=Depends(db_dep)):
    row = owned(db, SellerInvoice, ident, current.buyer_id, "Invoice not found")
    return reminder_for(db, current.buyer_id, row, tone, today())


# ---------- bills ----------

@router.post("/seller/bills")
def add_bill(body: BillIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = SellerBill(owner_id=current.buyer_id, **body.model_dump())
        db.add(row)
        db.commit()
    return bill_view(row)


@router.get("/seller/bills")
def list_bills(current=Depends(session), db=Depends(db_dep)):
    rows = db.scalars(select(SellerBill).where(SellerBill.owner_id == current.buyer_id).order_by(SellerBill.due_date))
    return [bill_view(row) for row in rows]


@router.post("/seller/bills/{ident}/record-payment")
def pay_bill(ident: str, body: BillPaymentIn, current=Depends(session), db=Depends(db_dep)):
    if not body.confirmed:
        fail(422, "Confirm that you have paid this bill")
    with WRITE_LOCK:
        row = owned(db, SellerBill, ident, current.buyer_id, "Bill not found")
        key = hashlib.sha256(f"seller-bill:{current.buyer_id}:{body.request_id}".encode()).hexdigest()
        replay = db.get(PlanningRecord, key)
        if replay:
            if replay.data["bill"] != ident:
                fail(409, "This request was already used for a different bill")
            return bill_view(row)
        if row.paid:
            fail(409, "This bill has already been paid")
        db.add(SellerBillPayment(owner_id=current.buyer_id, bill_id=row.id, amount_minor=row.amount_minor,
                                paid_on=today(), due_date=row.due_date))
        db.add(PlanningRecord(id=key, user_id=current.buyer_id, kind="seller_bill_payment", title=row.name, data={"bill": ident}))
        if row.recurrence == "monthly":
            row.due_date = add_months(row.due_date, 1)
        else:
            row.paid = True
        db.commit()
        return bill_view(row)


@router.put("/seller/bills/{ident}")
def update_bill(ident: str, body: BillIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = owned(db, SellerBill, ident, current.buyer_id, "Bill not found")
        if row.paid:
            fail(409, "A paid bill is preserved in the records")
        for key, value in body.model_dump().items():
            setattr(row, key, value)
        db.commit()
        return bill_view(row)


# ---------- receivables, forecast, alerts ----------

@router.get("/seller/receivables/aging")
def receivables_aging(current=Depends(session), db=Depends(db_dep)):
    as_of, owner = today(), current.buyer_id
    customers = customers_by_id(db, owner)
    buckets = {"0-7": {"count": 0, "amount_minor": 0}, "8-30": {"count": 0, "amount_minor": 0},
               "31+": {"count": 0, "amount_minor": 0}}
    rows = []
    for row in open_invoices(db, owner):
        view = invoice_view(db, row, customers[row.customer_id], as_of)
        rows.append(view)
        if not view["overdue"]:
            continue
        key = "0-7" if view["days_overdue"] <= 7 else "8-30" if view["days_overdue"] <= 30 else "31+"
        buckets[key]["count"] += 1
        buckets[key]["amount_minor"] += view["balance_minor"]
    rows.sort(key=lambda v: (-v["days_overdue"], v["due_date"], v["number"]))
    return {"as_of": as_of.isoformat(), "total_outstanding_minor": sum(v["balance_minor"] for v in rows),
            "buckets": buckets, "invoices": rows}


@router.get("/seller/forecast")
def forecast(horizon_days: int = Query(60, ge=30, le=90), current=Depends(session), db=Depends(db_dep)):
    return build_forecast(db, current.buyer_id, horizon_days)


@router.get("/seller/forecast/what-if")
def forecast_what_if(delay_days: int = Query(15, ge=0, le=120), horizon_days: int = Query(60, ge=30, le=90),
                     customer_id: str | None = Query(None, max_length=64),
                     current=Depends(session), db=Depends(db_dep)):
    customer = None
    if customer_id is not None:
        customer = owned(db, Customer, customer_id, current.buyer_id, "Customer not found")
    baseline = build_forecast(db, current.buyer_id, horizon_days, 0)
    scenario = build_forecast(db, current.buyer_id, horizon_days, delay_days,
                              customer_id=customer.id if customer else None)
    return {"delay_days": delay_days, "horizon_days": horizon_days,
            "customer_name": customer.name if customer else None,
            "baseline": forecast_summary(baseline), "scenario": forecast_summary(scenario),
            "change_in_min_balance_minor": scenario["min_balance_minor"] - baseline["min_balance_minor"]}


@router.get("/seller/alerts")
def seller_alerts(current=Depends(session), db=Depends(db_dep)):
    as_of, owner = today(), current.buyer_id
    customers = customers_by_id(db, owner)
    items = []
    for row in open_invoices(db, owner):
        customer = customers[row.customer_id]
        balance, days, _ = open_state(row, as_of)
        days_until = (row.due_date - as_of).days
        if days > 0:
            priority = 90 if days > 30 else 80 if days > 7 else 70
            items.append(alert(f"chase:{row.id}", "overdue", priority, f"Chase {row.number} today",
                               f"{customer.name} owes {rupees(balance)}, {days} days overdue", row.id,
                               reminder_for(db, owner, row, "firm" if days > 7 else "friendly", as_of)))
        elif days_until <= 3:
            items.append(alert(f"remind:{row.id}", "due_soon", 60 if days_until == 0 else 50,
                               f"Remind {customer.name} about {row.number} today" if days_until == 0
                               else f"Remind {customer.name} about {row.number} in {days_until} days",
                               f"{rupees(balance)} due {row.due_date.strftime('%d %b')}", row.id,
                               reminder_for(db, owner, row, "friendly", as_of)))
    for row in db.scalars(select(SellerInvoice).where(SellerInvoice.owner_id == owner, SellerInvoice.status == "draft")):
        items.append(alert(f"send:{row.id}", "draft", 35, f"Send draft {row.number} to {customers[row.customer_id].name}",
                           f"{rupees(row.total_minor)} not yet sent", row.id))
    for bill in db.scalars(select(SellerBill).where(SellerBill.owner_id == owner, SellerBill.paid.is_(False))):
        for offset in bill_offsets(bill.due_date, bill.recurrence, as_of, 6):
            due = as_of + timedelta(days=offset)
            items.append(alert(f"bill:{bill.id}:{due.isoformat()}", "bill_due", 85 if offset <= 2 else 65,
                               f"Pay {bill.name} on {due.strftime('%d %b')}", rupees(bill.amount_minor)))
    cash = build_forecast(db, owner, 60)
    if cash["first_negative_date"]:
        negative = date.fromisoformat(cash["first_negative_date"])
        items.append(alert("cash:first_negative", "cash_gap", 98 if (negative - as_of).days <= 14 else 75,
                           f"Cash goes negative on {negative.strftime('%d %b')}: chase overdue invoices or move bills",
                           f"Lowest projected balance {rupees(cash['min_balance_minor'])}"))
    items.sort(key=lambda a: (-a["priority"], a["id"]))
    return {"as_of": as_of.isoformat(), "alerts": items}


def explain_studio(db, owner, message, topic):
    import re
    from types import SimpleNamespace

    current = SimpleNamespace(buyer_id=owner)
    aging = receivables_aging(current, db)
    cash = build_forecast(db, owner, 60)
    invoices = aging["invoices"]
    destination, evidence = "#/seller", ["seller_invoices"]
    if topic == "blocked":
        answer = "Review and confirm financial decisions on the relevant invoice or bill. Tara can prepare reminders and show the cash impact."
    elif re.search(r"late|delay|what if", message, re.I):
        scenario = build_forecast(db, owner, 60, 15)
        answer = (f"If all open invoices arrive 15 days later, the lowest 60-day balance becomes {rupees(scenario['min_balance_minor'])}, "
                  f"compared with {rupees(cash['min_balance_minor'])} today. Choose one client in Cash forecast to test their delay.")
        destination, evidence = "#/seller/forecast", ["seller_invoices", "seller_bills", "15_day_scenario"]
    elif re.search(r"owe|overdue|unpaid|receivable", message, re.I):
        due = sum(row["balance_minor"] for row in invoices if row["overdue"])
        answer = f"Clients owe {rupees(aging['total_outstanding_minor'])} across {len(invoices)} open invoices. {rupees(due)} is overdue."
        if invoices:
            first = invoices[0]
            answer += f" Review {first['number']} for {first['customer']['name']}, with {rupees(first['balance_minor'])} outstanding."
    elif topic in ("balance", "budget") or re.search(r"cash|forecast|rent|next month", message, re.I):
        answer = (f"Recorded business cash is {rupees(cash['opening_minor'])}. The lowest forecast balance over 60 days is "
                  f"{rupees(cash['min_balance_minor'])} on {cash['min_balance_date']}. "
                  "Expected customer receipts use due dates and their recorded payment delay.")
        destination, evidence = "#/seller/forecast", ["seller_receipts", "seller_bills", "seller_invoices"]
    else:
        actions = seller_alerts(current, db)["alerts"]
        answer = ("Your next action is " + actions[0]["action"] + ". " + actions[0]["detail"]
                  if actions else "Your studio has no urgent follow-ups. Create a customer invoice or review the cash forecast.")
        if actions and actions[0]["invoice_id"]:
            destination = f"#/seller/invoices/{actions[0]['invoice_id']}"
    return {"topic": "studio", "answer": answer, "destination": destination, "evidence": evidence}
