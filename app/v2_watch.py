"""Private watchlists, public price reads and explicit BrightMart handoffs."""
import hashlib
from datetime import date, timedelta
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from .db import SessionLocal
from .config import settings
from .models import now
from .price_sources import PriceUnavailable, parse_price, read_public_product
from .security import crypto
from .v2 import CATALOG, CartIn, InvoiceIn, WRITE_LOCK, aware, cart_items, create_invoice, daily_date, db_dep, fail, invoice_view, router, session, workspace
from .v2_models import DemoSession, InvoiceSnapshot, Observation, Personalization, PlanningRecord, PriceSample, PriceWatch

STORE_URL = settings.store_url
CHECK_AFTER = timedelta(hours=4)
WATCH_LIMIT = 25


class ProductURL(BaseModel):
    url: str = Field(min_length=10, max_length=2000)


class SharedCart(BaseModel):
    token: str = Field(min_length=20, max_length=8000)


class PurchasePlanIn(BaseModel):
    target_date: date | None = None
    active: bool | None = None


def purchase_plan_key(watch_id):
    return f"purchase-goal:{watch_id}"


def linked_purchase_plan(db, watch):
    return db.get(PlanningRecord, purchase_plan_key(watch.id))


def update_purchase_plan(plan, watch):
    if plan.data.get("status") != "purchased":
        plan.data = plan.data | {"purchase_quantity": watch.quantity, "price_minor": watch.current_minor,
                                 "target_minor": watch.quantity * watch.current_minor}


def purchase_date(value):
    today = date.fromisoformat(daily_date())
    if value and value < today:
        fail(422, "Choose today or a future purchase date")
    return (value or today + timedelta(days=30)).isoformat()


def verified_cart(db, body, intent=None):
    try:
        payload = crypto.verify_message(db, body.token, consume=False)
        if payload.get("typ") != "brightmart.cart/1" or (intent and payload.get("intent") != intent):
            raise ValueError("Wrong type")
        return CartIn(items=payload["lines"])
    except (ValueError, KeyError, crypto.TokenError):
        fail(422, "This BrightMart cart snapshot is invalid or expired. Share it again from your cart.")


def read_market(url):
    prefix = STORE_URL + "/product/"
    if url.startswith(prefix) and url.removeprefix(prefix).isalnum():
        if settings.hosted_demo:
            sku = url.removeprefix(prefix)
            product = next((item for item in CATALOG if item["id"] == sku), None)
            if not product:
                raise PriceUnavailable("This item is no longer in the BrightMart catalog.")
            return {"title": product["name"], "key": sku, "minor": product["price_minor"],
                    "currency": "INR", "merchant": "BrightMart Electronics"}
        try:
            response = httpx.get(url, timeout=5, follow_redirects=False, trust_env=False)
            response.raise_for_status()
            return parse_price(response.text, "BrightMart Electronics")
        except httpx.HTTPError as exc:
            raise PriceUnavailable("BrightMart could not be reached.") from exc
    return read_public_product(url)


def view(db, row):
    samples = db.scalars(select(PriceSample).where(PriceSample.watch_id == row.id).order_by(PriceSample.checked_at.desc()).limit(12))
    plan = linked_purchase_plan(db, row)
    return {"id": row.id, "title": row.title, "merchant": row.merchant, "source_url": row.source_url, "quantity": row.quantity,
            "currency": row.currency, "current_minor": row.current_minor, "low_minor": row.low_minor,
            "checked_at": aware(row.checked_at).isoformat(), "error": row.error,
            "purchase_plan_id": plan.id if plan else None,
            "history": [{"amount_minor": sample.amount_minor, "at": aware(sample.checked_at).isoformat()} for sample in samples]}


def save_watch(db, user_id, source_url, quote, quantity=1):
    watches = list(db.scalars(select(PriceWatch).where(PriceWatch.user_id == user_id, PriceWatch.enabled)))
    previous = next((row for row in watches if row.source_url == source_url and row.currency == quote["currency"] and row.source_key == quote["key"]), None)
    if previous:
        previous.quantity = quantity
        plan = linked_purchase_plan(db, previous)
        if plan:
            update_purchase_plan(plan, previous)
        return previous
    if len(watches) >= WATCH_LIMIT:
        fail(409, f"Remove an item before adding more than {WATCH_LIMIT} watches")
    archived = db.scalars(select(PriceWatch).where(PriceWatch.user_id == user_id, PriceWatch.source_url == source_url,
                            PriceWatch.currency == quote["currency"], PriceWatch.source_key == quote["key"],
                            ~PriceWatch.enabled).order_by(PriceWatch.checked_at.desc()))
    for watch in archived:
        plan = linked_purchase_plan(db, watch)
        if plan and plan.data.get("status") == "paused":
            watch.enabled, watch.quantity = True, quantity
            apply_quote(db, watch, quote)
            update_purchase_plan(plan, watch)
            return watch
    watch = PriceWatch(user_id=user_id, source_url=source_url, title=quote["title"], merchant=quote["merchant"],
                       currency=quote["currency"], source_key=quote["key"], quantity=quantity,
                       current_minor=quote["minor"], low_minor=quote["minor"])
    db.add(watch)
    db.flush()
    db.add(PriceSample(watch_id=watch.id, amount_minor=watch.current_minor))
    return watch


def apply_quote(db, watch, quote):
    watch.checked_at = now()
    if quote["currency"] != watch.currency or quote["key"] != watch.source_key:
        watch.error = "The product or currency on this page changed. Track the new offer separately."
        return
    watch.error = ""
    price, prior = quote["minor"], watch.low_minor
    if price != watch.current_minor:
        db.add(PriceSample(watch_id=watch.id, amount_minor=price))
        watch.current_minor = price
        plan = linked_purchase_plan(db, watch)
        if plan:
            update_purchase_plan(plan, watch)
    if price < prior:
        watch.low_minor = price
        db.add(Observation(id=f"price:{watch.id}:{price}", user_id=watch.user_id, kind="price_low", priority=72,
                           source_id=watch.id, destination=f"#/watch/{watch.id}",
                           data={"title": watch.title, "amount_minor": price, "previous_minor": prior, "currency": watch.currency}))


def read_quote(source):
    try:
        return read_market(source), ""
    except PriceUnavailable as exc:
        return None, str(exc)


def refresh_watch(ident, user_id, minimum_age):
    with SessionLocal() as db:
        watch = db.get(PriceWatch, ident)
        if not watch or not watch.enabled or watch.user_id != user_id:
            fail(404, "Tracked item not found")
        if aware(watch.checked_at) > now() - minimum_age:
            return view(db, watch)
        source, old_timestamp = watch.source_url, watch.checked_at
    quote, error = read_quote(source)
    with WRITE_LOCK, SessionLocal() as db:
        watch = db.get(PriceWatch, ident)
        if not watch or not watch.enabled or watch.user_id != user_id:
            fail(404, "Tracked item not found")
        if watch.checked_at == old_timestamp:
            if quote:
                apply_quote(db, watch, quote)
            else:
                watch.checked_at, watch.error = now(), error
            db.commit()
        return view(db, watch)


@router.get("/watch")
def list_watches(current=Depends(session), db=Depends(db_dep)):
    return [view(db, row) for row in db.scalars(select(PriceWatch).where(PriceWatch.user_id == current.buyer_id, PriceWatch.enabled).order_by(PriceWatch.checked_at.desc()))]


@router.post("/watch")
def track_public_product(body: ProductURL, current=Depends(session), db=Depends(db_dep)):
    try:
        parsed = urlsplit(body.url.strip())
        # Query strings may carry account/session data. Track a public product's canonical path.
        if parsed.username or parsed.password or parsed.query:
            fail(422, "Use a clean public product URL without login details or a query string")
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except ValueError:
        fail(422, "Enter a valid product page URL")
    quote, error = read_quote(url)
    if not quote:
        fail(422, error)
    with WRITE_LOCK:
        row = save_watch(db, current.buyer_id, url, quote)
        db.commit()
        return view(db, row)


@router.post("/watch/{ident}/refresh")
def manual_price_check(ident: str, current=Depends(session)):
    return refresh_watch(ident, current.buyer_id, timedelta(seconds=20))


@router.delete("/watch/{ident}")
def unwatch(ident: str, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = db.get(PriceWatch, ident)
        if not row or row.user_id != current.buyer_id:
            fail(404, "Tracked item not found")
        row.enabled = False
        plan = linked_purchase_plan(db, row)
        if plan and plan.data.get("status") == "active":
            plan.data = plan.data | {"status": "paused"}
        db.commit()
        return {"ok": True}


@router.post("/watch/{ident}/plan")
def plan_purchase(ident: str, body: PurchasePlanIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        watch = db.get(PriceWatch, ident)
        if not watch or watch.user_id != current.buyer_id or not watch.enabled:
            fail(404, "Tracked item not found")
        if watch.currency != "INR":
            fail(422, "Purchase savings plans currently use INR prices")
        plan = linked_purchase_plan(db, watch)
        if plan:
            return {"id": plan.id}
        scope = workspace(db.get(Personalization, current.buyer_id).data)
        sku = watch.source_url.removeprefix(f"{STORE_URL}/product/")
        product_id = sku if any(product["id"] == sku for product in CATALOG) else None
        plan = PlanningRecord(id=purchase_plan_key(watch.id), user_id=current.buyer_id, kind="goal",
                              title=watch.title, purpose="business" if scope == "business" else "personal",
                              data={"linked_watch_id": watch.id, "product_id": product_id, "status": "active",
                                    "saved_minor": 0, "target_date": purchase_date(body.target_date)})
        update_purchase_plan(plan, watch)
        db.add(plan)
        db.commit()
        return {"id": plan.id}


@router.put("/plans/{ident}/purchase")
def update_purchase_goal(ident: str, body: PurchasePlanIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        plan = db.get(PlanningRecord, ident)
        if not plan or plan.user_id != current.buyer_id or not plan.data.get("linked_watch_id"):
            fail(404, "Purchase savings plan not found")
        if plan.data["status"] == "purchased":
            fail(409, "This purchase plan is complete")
        data = dict(plan.data)
        if body.target_date:
            data["target_date"] = purchase_date(body.target_date)
        if body.active is not None:
            watch = db.get(PriceWatch, data["linked_watch_id"])
            if body.active and (not watch or not watch.enabled):
                fail(409, "Track this item again to resume automated savings")
            data["status"] = "active" if body.active else "paused"
        plan.data = data
        db.commit()
        return {"id": plan.id}


@router.post("/store-cart/review")
def review_cart(body: SharedCart, current=Depends(session), db=Depends(db_dep)):
    items = cart_items(verified_cart(db, body).items)
    return {"items": items, "total_minor": sum(row["unit_minor"] * row["quantity"] for row in items)}


@router.post("/store-cart/track")
def track_cart(body: SharedCart, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        items = cart_items(verified_cart(db, body, "track").items)
        key = hashlib.sha256(f"{current.workspace_id}:{body.token}".encode()).hexdigest()
        if db.get(PlanningRecord, key):
            return {"ok": True}
        for row in items:
            url = f"{STORE_URL}/product/{row['product_id']}"
            quote = {"title": row["name"], "key": row["product_id"], "minor": row["unit_minor"], "currency": "INR", "merchant": "BrightMart Electronics"}
            save_watch(db, current.buyer_id, url, quote, row["quantity"])
        db.add(PlanningRecord(id=key, user_id=current.buyer_id, kind="store_handoff", title="BrightMart watchlist"))
        db.commit()
    return {"ok": True}


@router.post("/store-cart/checkout")
def checkout_cart(body: SharedCart, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        lines = verified_cart(db, body, "checkout").items
        key = hashlib.sha256(f"{current.workspace_id}:{body.token}".encode()).hexdigest()
        existing = db.get(PlanningRecord, key)
        if existing:
            invoice = db.get(InvoiceSnapshot, existing.data["invoice_id"])
            return invoice_view(db, invoice)
        prefs = db.get(Personalization, current.buyer_id).data
        purpose = "business" if workspace(prefs, "merchant") == "business" else "personal"
        invoice = create_invoice(db, current, InvoiceIn(items=lines, purpose=purpose))
        db.add(PlanningRecord(id=key, user_id=current.buyer_id, kind="store_handoff", title="BrightMart checkout", data={"invoice_id": invoice.id}))
        db.commit()
        return invoice_view(db, invoice)


def price_watch_worker(stop):
    while not stop.wait(60):
        with SessionLocal() as db:
            active_users = select(DemoSession.buyer_id).where(DemoSession.expires_at > now())
            rows = db.execute(select(PriceWatch.id, PriceWatch.user_id).where(
                PriceWatch.enabled, PriceWatch.user_id.in_(active_users), PriceWatch.checked_at <= now() - CHECK_AFTER
            ).order_by(PriceWatch.checked_at).limit(12)).all()
        for ident, user_id in rows:
            if stop.is_set():
                return
            try:
                refresh_watch(ident, user_id, CHECK_AFTER)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Price watch refresh failed")
