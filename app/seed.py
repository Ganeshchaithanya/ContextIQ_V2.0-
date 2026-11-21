"""Demo data (clearly synthetic). Dates are relative to 'now' so the demo always behaves the same."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import select

from .db import session_scope
from .models import Budget, LedgerEntry, Obligation, User

DEMO_POLICY = """BrightMart Electronics — Returns, Replacement & Warranty
You may return most items within 30 days of delivery for a full refund to the original payment method.
Items must be unused, in original packaging, with proof of purchase.
Defective items qualify for a 7-day replacement from the date of delivery.
All headphones and speakers carry a 1-year limited warranty.
In-ear earbuds are non-returnable once opened for hygiene reasons.
Customer pays return shipping unless the item arrived defective."""


def ensure_seed() -> None:
    with session_scope() as db:
        if db.get(User, "alex"):
            return
        now = datetime.now(UTC)
        db.add_all([
            User(id="alex", name="Alex Rivera", role="shopper", business_name="Rivera Electronics",
                 work_start_hour=9, work_end_hour=17, monthly_income=4000, pay_day=min(28, (now + timedelta(days=9)).day),
                 available_balance=1450.0, risk_tolerance="moderate", investment_enabled=True,
                 paypal_email="sb-hfln853812063@personal.example.com", uses="both"),
            User(id="brightmart", name="BrightMart", role="merchant", business_name="BrightMart Electronics",
                 paypal_email="merchant@example.com"),
            User(id="novaparts", name="Nova Parts", role="supplier", business_name="Nova Parts Co",
                 paypal_email="billing@novaparts.example"),
        ])
        db.add(Budget(user_id="alex", category="total", limit=1900))
        db.add(Budget(user_id="alex", category="dining", limit=250))
        rng = np.random.default_rng(1)
        month_start = now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
        days_in = max(1, (now - month_start).days)
        # this month: ~1,550 spent so far, spread over the days elapsed
        plan = [("FreshMart", "groceries", 6, 70), ("Cafe Aroma", "dining", 6, 34), ("QuickCab", "transport", 5, 22),
                ("UrbanWear", "clothing", 1, 160), ("Bistro 21", "dining", 2, 55), ("TechKart", "electronics", 1, 420)]
        for payee, cat, n, amt in plan:
            for _ in range(n if amt >= 100 else max(1, round(n * days_in / 20))):  # scale everyday spend to days elapsed
                db.add(LedgerEntry(user_id="alex", payee=payee, description=cat, category=cat, purpose="personal",
                                   amount=round(float(amt * rng.uniform(0.85, 1.15)), 2),
                                   occurred_at=month_start + timedelta(days=float(rng.uniform(0, days_in)))))
        # history: 4 months incl. two subscriptions (monthly) for the detector
        for m in range(1, 5):
            sub_day = now - timedelta(days=28 + 30 * (m - 1))  # renews again in ~2 days
            if sub_day < month_start:
                db.add(LedgerEntry(user_id="alex", payee="StreamFlix", description="monthly plan",
                                   category="entertainment", amount=15.99,
                                   occurred_at=sub_day + timedelta(hours=float(rng.normal(0, 8)))))
                db.add(LedgerEntry(user_id="alex", payee="CloudHost", description="server hosting",
                                   category="software", purpose="business", amount=29.0,
                                   occurred_at=sub_day - timedelta(days=3)))
            for _ in range(12):  # past months only
                db.add(LedgerEntry(user_id="alex", payee=str(rng.choice(["FreshMart", "Cafe Aroma", "QuickCab"])),
                                   category="groceries", amount=round(float(rng.uniform(15, 80)), 2),
                                   occurred_at=month_start - timedelta(days=30 * (m - 1) + float(rng.uniform(1, 29)))))
        db.add_all([
            Obligation(owner_id="alex", kind="bill", title="Electricity bill", amount=140,
                       due_at=now + timedelta(days=3)),
            Obligation(owner_id="alex", kind="bill", title="Internet bill", amount=60, due_at=now + timedelta(days=5)),
            Obligation(owner_id="alex", kind="subscription", title="StreamFlix renewal", amount=15.99,
                       due_at=now + timedelta(days=2)),
            Obligation(owner_id="alex", kind="supplier_payment", title="Nova Parts — PO-1042", amount=1200,
                       due_at=now + timedelta(days=1)),
        ])
        db.flush()
        _seed_cart(db, now)
        from .config import settings
        from .paypal import adapter
        orig = settings.paypal_env
        try:
            settings.paypal_env = "mock"
            adapter._client = None
            _seed_supplier_payment(db)
            _seed_recent_purchase(db, now)
        finally:
            settings.paypal_env = orig
            adapter._client = None


def _seed_supplier_payment(db) -> None:
    """A real business payment to Nova Parts last week, for the
    'supplier says payment wasn't received' demo."""
    from .agents import commerce
    from .config import settings
    from .paypal import mock

    co = commerce.start_checkout(db, "alex", merchant="Nova Parts Co", seller_id="novaparts", channel="invoice",
                                 purpose="business", category="inventory",
                                 items=[{"name": "PO-1041 sensor boards", "unit_price": 38.0, "quantity": 25}],
                                 currency=settings.currency)
    mock.approve(co["order"]["order_id"])
    r = commerce.complete_payment(db, "alex", co["case_id"], co["approval_token"])
    if r.get("gateway") == "step_up":
        commerce.complete_payment(db, "alex", co["case_id"], co["approval_token"], step_up_code=r["step_up_code_demo"])


def _seed_cart(db, now) -> None:
    """Two items sitting in Alex's cart; ContextIQ has watched their prices for three weeks."""
    from .models import CartItem, PriceObservation

    for name, merchant, prices in (("Noise-cancelling earbuds", "BrightMart Electronics", [189.0, 189.0, 179.0, 179.0, 149.0]),
                                   ("Mechanical keyboard", "TechKart", [99.0, 104.0, 104.0, 109.0])):
        key = (merchant + "-" + name).lower().replace(" ", "-")
        import re
        key = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
        db.add(CartItem(user_id="alex", merchant=merchant, name=name, product_key=key, currency="USD",
                        added_at=now - timedelta(days=21)))
        for i, p in enumerate(prices):
            db.add(PriceObservation(user_id="alex", product_key=key, title=name, merchant=merchant, price=p,
                                    seen_at=now - timedelta(days=21 - i * (21 // max(1, len(prices) - 1)))))


def _seed_recent_purchase(db, now) -> None:
    """Headphones bought 12 days ago, delivered 10 days ago — so the return window is closing (demo of deadline cards)."""
    from .agents import commerce
    from .config import settings
    from .models import Case
    from .paypal import mock

    co = commerce.start_checkout(db, "alex", merchant="BrightMart Electronics", seller_id="brightmart",
                                 items=[{"name": "SoundWave Headphones", "unit_price": 249.0, "quantity": 1}],
                                 currency=settings.currency, policy_text=DEMO_POLICY, policy_url="/demo-store/#policy")
    mock.approve(co["order"]["order_id"])
    r = commerce.complete_payment(db, "alex", co["case_id"], co["approval_token"])
    if r.get("gateway") == "step_up":
        commerce.complete_payment(db, "alex", co["case_id"], co["approval_token"], step_up_code=r["step_up_code_demo"])
    case = db.get(Case, co["case_id"])
    case.created_at = now - timedelta(days=8)
    from .models import LedgerEntry
    for e in db.scalars(select(LedgerEntry).where(LedgerEntry.case_id == case.id)).all():
        e.occurred_at = now - timedelta(days=8)
    commerce.record_delivery(db, case.id, now - timedelta(days=5))
    case = db.get(Case, co["case_id"])
    case.created_at = now - timedelta(days=8)
    from .models import LedgerEntry
    for e in db.scalars(select(LedgerEntry).where(LedgerEntry.case_id == case.id)).all():
        e.occurred_at = now - timedelta(days=8)
    commerce.record_delivery(db, case.id, now - timedelta(days=5))


FREELANCER_CUSTOMERS = [  # (name, phone, email, usual payment delay in days)
    ("Sharma Textiles Pvt Ltd", "+91 90000 11001", "accounts@sharma-textiles.example", 10),
    ("Kaveri Cafe Co.", "+91 90000 11002", "hello@kaveri-cafe.example", 5),
    ("Bengaluru Fintech Labs", "+91 90000 11003", "finance@blr-fintech.example", 25),
    ("Rangoli Weddings & Events", "+91 90000 11004", "team@rangoli-weddings.example", 0),
    ("Pune Organic Foods LLP", "+91 90000 11005", "billing@puneorganic.example", 15),
    ("Jaipur Handloom Store", "+91 90000 11006", "shop@jaipurhandloom.example", 30),
]
# (number, customer index, issue offset days, due offset days, lines (description, qty, rupees), status, payments (rupees, offset days))
FREELANCER_INVOICES = [
    ("INV-0001", 5, -95, -65, [("Brand identity: logo and colour system", 1, 850), ("Brand guidelines PDF", 1, 250)], "paid", [(1100, -60)]),
    ("INV-0002", 3, -80, -65, [("Wedding invitation suite (print-ready)", 1, 450), ("Save-the-date cards", 2, 60)], "paid", [(570, -50)]),
    ("INV-0003", 0, -50, -35, [("Packaging design: 3 SKUs", 3, 220)], "part_paid", [(200, -30)]),
    ("INV-0004", 2, -40, -10, [("Website UI kit in Figma", 1, 1200), ("Design review sessions", 2, 150)], "sent", []),
    ("INV-0005", 1, -35, -20, [("Cafe menu redesign", 1, 300), ("Menu board illustrations", 4, 35)], "part_paid", [(150, -18)]),
    ("INV-0006", 4, -6, -2, [("Organic store social media kit", 1, 380)], "sent", []),
    ("INV-0007", 1, -20, -5, [("Social media templates (12 posts)", 1, 180)], "paid", [(180, -3)]),
    ("INV-0008", 4, -2, 13, [("Product label design", 2, 95)], "sent", []),
    ("INV-0009", 2, -1, 29, [("Pitch deck redesign (20 slides)", 1, 950)], "sent", []),
    ("INV-0010", 5, 0, 30, [("Jaipur summer catalogue layout", 1, 600)], "draft", []),
    ("INV-0011", 0, 0, 14, [("Festive campaign banners", 5, 40)], "draft", []),
    ("INV-0012", 3, -40, -25, [("Mehendi and haldi signage", 3, 70)], "sent", []),
]
# (name, rupees, due offset days, recurrence)
FREELANCER_BILLS = [
    ("Studio rent (shared workspace)", 25000, 4, "monthly"),
    ("Adobe Creative Cloud", 4230, 6, "monthly"),
    ("Broadband (home office)", 1199, 11, "monthly"),
    ("Laptop EMI", 8500, 3, "monthly"),
    ("GST filing: Q2 return", 6500, 20, "none"),
]


def seed_freelancer_seller(db, owner_id: str) -> None:
    """Fictional back-office data for a freelance designer (Meera Design Studio). Dates are relative to today."""
    from datetime import timedelta as td

    from .models import _id
    from .v2_models import Customer, Personalization, SellerBill, SellerInvoice, SellerInvoiceLine, SellerPayment
    from .v2_seller import today

    as_of = today()
    customer_ids = []
    for name, phone, email, delay in FREELANCER_CUSTOMERS:
        ident = _id()
        customer_ids.append(ident)
        db.add(Customer(id=ident, owner_id=owner_id, name=name, phone=phone, email=email, usual_payment_delay_days=delay))
    for number, index, issue_off, due_off, lines, status, payments in FREELANCER_INVOICES:
        total = sum(qty * rupees * 100 for _, qty, rupees in lines)
        paid = sum(rupees * 100 for rupees, _ in payments)
        invoice_id = _id()
        db.add(SellerInvoice(id=invoice_id, owner_id=owner_id, customer_id=customer_ids[index], number=number,
                             issue_date=as_of + td(days=issue_off), due_date=as_of + td(days=due_off), currency="INR",
                             status=status, total_minor=total, amount_paid_minor=paid))
        for description, qty, rupees in lines:
            db.add(SellerInvoiceLine(invoice_id=invoice_id, description=description, quantity=qty,
                                     unit_price_minor=rupees * 100, amount_minor=qty * rupees * 100))
        for rupees, off in payments:
            db.add(SellerPayment(owner_id=owner_id, invoice_id=invoice_id, amount_minor=rupees * 100, method="upi",
                                 reference="UPI demo payment", received_on=as_of + td(days=off)))
    for name, rupees, due_off, recurrence in FREELANCER_BILLS:
        db.add(SellerBill(owner_id=owner_id, name=name, amount_minor=rupees * 100, due_date=as_of + td(days=due_off),
                          recurrence=recurrence, paid=False))
    db.flush()
    row = db.get(Personalization, owner_id)
    row.data = row.data | {"seller": {"upi_vpa": "meera.designs@okaxis", "payee_name": "Meera Design Studio",
                                      "opening_balance_minor": 9000000}}
