"""Razorpay test checkout with provider-verified settlement and safe external UPI links."""
import hashlib
import hmac
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import briefcase
from .agents import commerce
from .models import Evidence, PolicySnapshot
from .config import settings
from .v2 import AuthorizeIn, WRITE_LOCK, aware, db_dep, fail, finalize_payment, now, owned_invoice, router, session
from .v2_models import ProviderCheckout

METHODS = {"upi": "UPI", "card": "Credit or debit card", "netbanking": "Net banking"}
DEMO_INSTRUMENTS = {
    "upi": {"upi_qr": "UPI QR", "google_pay": "Google Pay", "phonepe": "PhonePe", "paytm": "Paytm"},
    "card": {"demo_card": "Demo card ending 4242"},
    "netbanking": {"demo_bank": "Demo Business Bank"},
}


def credentials():
    key = os.getenv("RAZORPAY_KEY_ID", "")
    secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    return (key, secret) if key.startswith("rzp_test_") and secret else None


def request_provider(method, path, **kwargs):
    auth = credentials()
    if not auth:
        fail(503, "Razorpay test checkout is not configured")
    try:
        response = httpx.request(method, f"https://api.razorpay.com/v1/{path}", auth=auth, timeout=12, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        fail(502, "Razorpay did not return a usable confirmation. Check the existing order before retrying.")


class CheckoutIn(AuthorizeIn):
    method: Literal["upi", "card", "netbanking"]


class ProviderProof(BaseModel):
    payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=60)
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")


def recorded_demo_method(db, case_id):
    if not case_id:
        return None
    evidence = db.scalar(select(Evidence).where(Evidence.case_id == case_id, Evidence.kind == "invoice_snapshot").limit(1))
    return evidence.content.get("simulated_method", "mock") if evidence else None


def checkout_info(db, invoice_id, case_id):
    existing = db.get(ProviderCheckout, invoice_id)
    return {"methods": METHODS, "gateway_available": credentials() is not None,
            "verification": {"mode": "razorpay_test" if existing else "simulation",
                "provider_reference": existing.payment_id if existing else None,
                "checks": ["Exact invoice approval", "Signed callback", "Server-side capture, order, amount, currency and method match"] if existing else ["Exact invoice approval", "Simulated receipt; no bank settlement verified"],
                "live_money_enabled": False},
            "existing_method": existing.method if existing else None,
            "simulated_method": None if existing else recorded_demo_method(db, case_id),
            "simulated_instrument": None if existing else recorded_demo_instrument(db, case_id),
            "demo_instruments": DEMO_INSTRUMENTS}


def recorded_demo_instrument(db, case_id):
    if not case_id:
        return None
    evidence = db.scalar(select(Evidence).where(Evidence.case_id == case_id, Evidence.kind == "invoice_snapshot").limit(1))
    return evidence.content.get("simulated_instrument") if evidence else None


@router.post("/invoices/{ident}/provider-order")
def create_provider_order(ident: str, body: CheckoutIn, current=Depends(session), db=Depends(db_dep)):
    auth = credentials()
    if not auth:
        fail(503, "UPI, cards and net banking require a configured Razorpay test account")
    with WRITE_LOCK:
        invoice = owned_invoice(db, current, ident)
        if not body.authorized or invoice.fingerprint != body.fingerprint or invoice.version != body.version:
            fail(409, "Review and authorize the exact invoice first")
        if invoice.case_id or invoice.status not in ("open", "provider_checkout"):
            fail(409, "This invoice already has a payment or is no longer payable")
        if aware(invoice.expires_at) <= now():
            fail(409, "This invoice has expired. Check the existing order if you attempted payment.")
        saved = db.get(ProviderCheckout, ident)
        if not saved:
            order = request_provider("POST", "orders", json={"amount": invoice.total_minor, "currency": invoice.currency, "receipt": invoice.id})
            provider_id = order.get("id", "")
            if not re.fullmatch(r"order_[A-Za-z0-9]+", provider_id) or order.get("amount") != invoice.total_minor or order.get("currency") != invoice.currency:
                fail(502, "Razorpay order does not match this invoice")
            saved = ProviderCheckout(invoice_id=invoice.id, order_id=provider_id, method=body.method)
            db.add(saved)
            invoice.status = "provider_checkout"
        elif saved.method != body.method:
            fail(409, "Resume the payment method selected for this order")
        db.commit()
        return {"key": auth[0], "order_id": saved.order_id, "amount": invoice.total_minor,
                "currency": invoice.currency, "method": saved.method, "test": True}


def confirm_capture(db, current, invoice, order, payment):
    if payment.get("status") != "captured":
        return {"ok": False, "pending": True}
    if (payment.get("order_id"), payment.get("amount"), payment.get("currency"), payment.get("method")) != (order.order_id, invoice.total_minor, invoice.currency, order.method):
        fail(409, "Provider payment does not match this order, amount, currency or method")
    if not re.fullmatch(r"pay_[A-Za-z0-9]+", payment.get("id", "")):
        fail(409, "Provider did not confirm a valid payment reference")
    if invoice.status == "paid":
        if order.payment_id != payment["id"]:
            fail(409, "This invoice was settled with a different payment reference")
        return {"ok": True, "status": "paid", "case_id": invoice.case_id, "replayed": True}
    items = [{"name": item["name"], "quantity": item["quantity"], "unit_price": item["unit_minor"] / 100} for item in invoice.items]
    case = briefcase.create_case(db, owner_id=current.buyer_id, counterparty_id=current.seller_id,
                                 title=", ".join(item["name"] for item in items)[:120], merchant="BrightMart Electronics",
                                 amount=invoice.total_minor / 100, currency=invoice.currency, channel="online", purpose=invoice.purpose)
    terms = {"return_window_days": 30, "replacement_window_days": 7, "warranty_days": 365, "starts_from": "delivery"} if invoice.kind == "itemized" else {}
    briefcase.record_agreement(db, case, items=items, amount=case.amount, currency=case.currency, payee=case.merchant,
                               terms=terms, approved_by=current.buyer_id)
    if terms:
        db.add(PolicySnapshot(case_id=case.id, merchant=case.merchant, url="", content_hash=hashlib.sha256(invoice.policy.encode()).hexdigest(), text=invoice.policy, extracted=terms))
    if terms:
        briefcase.add_evidence(db, case, kind="policy_snapshot", source="merchant_page", provenance="claimed",
                               summary="BrightMart terms as recorded at checkout", content={"terms": terms, "policy_text": invoice.policy})
    briefcase.set_payment_state(db, case, "order_created", "razorpay_test", {"order": order.order_id})
    briefcase.set_payment_state(db, case, "buyer_approved", "user", {"invoice": invoice.id})
    briefcase.set_payment_state(db, case, "captured", "razorpay_test", {"order": order.order_id, "payment": payment["id"], "method": order.method})
    briefcase.add_evidence(db, case, kind="capture", source="razorpay_test", provenance="verified",
                           summary=f"Razorpay test capture {payment['id']} confirmed",
                           content={"amount_minor": invoice.total_minor, "currency": invoice.currency, "method": order.method, "provider_order_id": order.order_id})
    invoice.case_id, order.payment_id = case.id, payment["id"]
    db.flush()
    commerce._after_capture(db, case, current.buyer_id)
    result = finalize_payment(db, current, invoice, {"ok": True})
    db.commit()
    return result


def existing_checkout(db, current, ident):
    invoice = owned_invoice(db, current, ident)
    order = db.get(ProviderCheckout, ident)
    if not order:
        fail(404, "No Razorpay order exists for this invoice")
    return invoice, order


@router.post("/invoices/{ident}/provider-confirm")
def verify_provider_callback(ident: str, body: ProviderProof, current=Depends(session), db=Depends(db_dep)):
    auth = credentials()
    if not auth:
        fail(503, "Razorpay test checkout is not configured")
    with WRITE_LOCK:
        invoice, order = existing_checkout(db, current, ident)
        expected = hmac.new(auth[1].encode(), f"{order.order_id}|{body.payment_id}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, body.signature):
            fail(403, "Payment signature is invalid")
        payment = request_provider("GET", f"payments/{body.payment_id}")
        if payment.get("id") != body.payment_id:
            fail(409, "Provider returned a different payment reference")
        return confirm_capture(db, current, invoice, order, payment)


@router.post("/invoices/{ident}/provider-status")
def verify_provider_order(ident: str, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        invoice, order = existing_checkout(db, current, ident)
        if invoice.status == "paid":
            return {"ok": True, "status": "paid", "case_id": invoice.case_id}
        payments = request_provider("GET", f"orders/{order.order_id}/payments")
        captured = [payment for payment in payments.get("items", []) if payment.get("status") == "captured"]
        if len(captured) > 1:
            fail(409, "Multiple captured payments require provider review")
        return confirm_capture(db, current, invoice, order, captured[0]) if captured else {"ok": False, "pending": True}


def upi_handoff(raw):
    """Normalize the exact fields in a user's scanned external UPI request."""
    if settings.hosted_demo:
        return None
    url = urlsplit(raw)
    if url.scheme.lower() != "upi" or url.netloc.lower() != "pay" or url.path or url.fragment:
        return None
    values = parse_qs(url.query, max_num_fields=24)
    if any(len(items) != 1 for items in values.values()):
        return None
    fields = {key: value[0] for key, value in values.items()}
    # Preserve signed merchant and provider-specific parameters through the payment app handoff.
    if not re.fullmatch(r"[\w.\-]{2,100}@[A-Za-z0-9.\-]{2,64}", fields.get("pa", ""), flags=re.ASCII) or fields.get("cu", "INR") != "INR":
        return None
    raw_amount = fields.get("am", "")
    if not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", raw_amount):
        return None
    try:
        amount = Decimal(raw_amount)
        if amount <= 0:
            return None
    except InvalidOperation:
        return None
    return "upi://pay?" + url.query
