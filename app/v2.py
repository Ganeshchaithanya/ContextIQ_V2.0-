"""Session-scoped V2 application using the existing commerce and evidence services."""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from starlette.responses import JSONResponse

from . import briefcase, finance
from .agents import commerce
from .config import settings
from .db import SessionLocal
from .models import Case, CaseEvent, Evidence, LedgerEntry, Obligation, OutboundNotice, PolicySnapshot, User, now, _id
from .paypal import mock, payments
from .security import crypto
from .v2_models import DemoSession, InvoiceSnapshot, Observation, PaymentIncident, Personalization, PlanningRecord, PriceWatch, ProviderCheckout, PurchaseItem

router = APIRouter(prefix="/api/v2")
WRITE_LOCK = threading.RLock()
RATE = defaultdict(deque)
NEW_DEMO_REQUESTS = deque()
BUSINESS_BILL_KINDS = ("supplier_payment", "recurring_supplier_payment")
RECURRING_BILL_KINDS = ("subscription", "recurring_supplier_payment")
PURCHASE_WINDOWS = {"replacement": 7, "return": 30, "warranty": 365}
POLICY = """BrightMart fictional demo store. Prices include all taxes. Unused products may be returned within 30 days of delivery. Defective products qualify for free replacement within 7 days of delivery. Headphones, computers and accessories carry a 365-day warranty. Opened in-ear earbuds are excluded from change-of-mind returns. A merchant must review and approve each request. Delivery events are simulated."""
CATALOG = [
    {"id": "premium", "name": "Studio Pro headphones", "price_minor": 349900, "category": "electronics", "description": "Over-ear wireless headphones. 40-hour demo battery specification.", "image": "https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=600&auto=format&fit=crop"},
    {"id": "headphones", "name": "Everyday headphones", "price_minor": 199900, "category": "electronics", "description": "Comfortable on-ear sound for classes, music and daily calls.", "image": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&auto=format&fit=crop"},
    {"id": "cable", "name": "USB-C charging cable", "price_minor": 29900, "category": "electronics", "description": "A durable 1.5-metre braided cable.", "image": "https://images.unsplash.com/photo-1600490722773-35753aea6332?w=600&auto=format&fit=crop"},
    {"id": "mouse", "name": "Wireless mouse", "price_minor": 89900, "category": "electronics", "description": "Quiet clicks and a compact shape for everyday work.", "image": "https://images.unsplash.com/photo-1527814050087-3793815479db?w=600&auto=format&fit=crop"},
    {"id": "laptop", "name": "Workday laptop", "price_minor": 5500000, "category": "electronics", "description": "Fictional 14-inch laptop with 16 GB memory and 512 GB storage.", "image": "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=600&auto=format&fit=crop"},
    {"id": "components", "name": "Electronics component pack", "price_minor": 200000, "category": "inventory", "description": "A demo inventory kit for your electronics shop.", "image": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=600&auto=format&fit=crop"},
]


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def fail(code, message):
    raise HTTPException(code, message)


def db_dep():
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


def session(request: Request, db=Depends(db_dep)):
    record = db.get(DemoSession, getattr(request.state, "session_hash", ""))
    if not record or aware(record.expires_at) <= now():
        fail(401, "Your demo session has expired. Start a new demo.")
    return record


def same_origin(request):
    origin = request.headers.get("origin")
    if settings.hosted_demo:
        return not origin or origin in (settings.public_base_url.rstrip("/"), settings.app_url)
    return not origin or origin == str(request.base_url).rstrip("/")


async def access_control(request, call_next):
    path = request.url.path
    if not settings.hosted_demo and os.getenv("CONTEXTIQ_LEGACY_TEST_AUTH") == "1":
        return await call_next(request)
    if not (path.startswith("/api/") or path.startswith("/a2a") or path == "/console"):
        return await call_next(request)
    if path == "/api/webhooks/paypal":
        if settings.paypal_env == "mock" or settings.hosted_demo:
            return JSONResponse({"detail": "Webhook unavailable in this demo"}, status_code=404)
        return await call_next(request)
    if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request):
        return JSONResponse({"detail": "Cross-origin action rejected"}, status_code=403)
    if path in ("/api/config", "/api/v2/session"):
        return await call_next(request)
    token = request.cookies.get("ciq_session", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with SessionLocal() as db:
        current = db.get(DemoSession, token_hash)
        if not current or aware(current.expires_at) <= now():
            return JSONResponse({"detail": "Start your private demo first"}, status_code=401)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), current.csrf):
            return JSONResponse({"detail": "Refresh the page before trying again"}, status_code=403)
        ticks = RATE[token_hash]
        cutoff = time.monotonic() - 60
        while ticks and ticks[0] < cutoff:
            ticks.popleft()
        if len(ticks) >= 180:
            return JSONResponse({"detail": "Please wait a moment before trying again"}, status_code=429)
        ticks.append(time.monotonic())
        request.state.session_hash = token_hash
        request.scope["headers"] = [(k, v) for k, v in request.scope["headers"] if k.lower() != b"x-user-id"] + [(b"x-user-id", current.buyer_id.encode())]
    if not path.startswith("/api/v2/"):
        safe = path.startswith("/api/cases") or path in ("/api/profile", "/api/budget", "/api/whatif", "/api/obligations", "/api/home", "/api/cart/watch", "/api/insights", "/api/recommendations", "/api/features")
        if request.method != "GET" or not safe:
            return JSONResponse({"detail": "Use the session-scoped V2 workflow"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


class SessionIn(BaseModel):
    persona: Literal["student", "salaried", "shopkeeper"] = "student"


def seed_workspace(db, persona):
    ident = _id()
    buyer_id, seller_id = f"buyer-{ident}", f"seller-{ident}"
    names = {"student": "Priya", "salaried": "Arjun", "shopkeeper": "Kavya"}
    balance = {"student": 600000, "salaried": 5800000, "shopkeeper": 9500000}[persona]
    db.add_all([User(id=buyer_id, name=names[persona], uses="personal", available_balance=balance / 100,
                     monthly_income=0, pay_day=1, balance_source="fictional_demo"),
                User(id=seller_id, name="BrightMart", role="merchant", business_name="BrightMart Electronics")])
    profile = {"language": "en", "occupation": persona, "configuration": "separate" if persona == "shopkeeper" else "personal",
               "override": "auto", "workspace": "personal", "name": names[persona], "onboarded": False,
               "features": ["budget", "purchases", "goals", "emi"], "context_consent": False,
               "location_consent": False, "voice_enabled": False, "learning_enabled": False,
               "news_enabled": False, "work_start": 9, "work_end": 18, "cart": [], "persona": persona}
    if persona == "shopkeeper":
        profile.update(business_type="Kirana shop", workspace="business", features=["budget", "purchases", "goals", "emi", "business"])
    db.add(Personalization(user_id=buyer_id, data=profile))
    # The opening entry and dated expenses reconcile exactly to the chosen persona's funds.
    seed_date = now() - timedelta(days=35)
    db.add(LedgerEntry(user_id=buyer_id, payee="Demo opening funds", description="Fictional opening funds", category="opening",
                       amount=-(balance + 185000) / 100, amount_minor=-(balance + 185000), currency="INR", source="demo_seed", occurred_at=seed_date))
    for offset, payee, category, amount in [(25, "Groceries", "groceries", 62000), (19, "Metro travel", "transport", 28000), (12, "Cafe", "dining", 35000), (4, "Books & supplies", "education", 60000)]:
        db.add(LedgerEntry(user_id=buyer_id, payee=payee, description=payee, category=category, amount=amount / 100,
                           amount_minor=amount, currency="INR", source="demo_seed", occurred_at=now() - timedelta(days=offset)))
    title, bill_amount = ("Hostel fee", 3500) if persona == "student" else ("Home rent", 15000)
    db.add(Obligation(owner_id=buyer_id, kind="bill", title=title, amount=bill_amount, due_at=now() + timedelta(days=6)))
    if persona == "shopkeeper":
        db.add(LedgerEntry(user_id=buyer_id, payee="Demo business opening", description="Fictional shop funds", category="opening",
                           purpose="business", amount=-58000, amount_minor=-5800000, currency="INR", source="demo_seed", occurred_at=seed_date))
        for title, amount, days, category in [("Counter sales", -8500, 3, "sales"), ("Packaging and bags", 1500, 1, "operating")]:
            db.add(LedgerEntry(user_id=buyer_id, payee=title, description=title, category=category, purpose="business",
                               amount=amount, amount_minor=amount * 100, currency="INR", source="demo_seed", occurred_at=now() - timedelta(days=days)))
        db.add(Obligation(owner_id=buyer_id, kind="supplier_payment", title="Rice, dal and cooking oil restock", amount=12000, due_at=now() + timedelta(days=2)))
        db.add(PlanningRecord(user_id=buyer_id, kind="receivable", title="Monthly grocery account", purpose="business",
                              data={"amount_minor": 240000, "due": (now() + timedelta(days=5)).date().isoformat(), "status": "open", "contact": "Fictional local customer"}))
        db.add(PlanningRecord(user_id=buyer_id, kind="supplier", title="Neighbourhood Staples Wholesale", purpose="business",
                              data={"status": "open", "contact": "Fictional supplier", "notes": "Rice, dal and cooking oil"}))
    goal_title = "New weighing scale for the shop" if persona == "shopkeeper" else "A laptop for what's next"
    db.add(PlanningRecord(user_id=buyer_id, kind="goal", title=goal_title, purpose="business" if persona == "shopkeeper" else "personal",
                          data={"target_minor": 500000 if persona == "shopkeeper" else 5500000, "saved_minor": 0, "contribution_minor": 200000, "horizon": "medium", "target_date": (now() + timedelta(days=365)).date().isoformat(), "priority": "normal"}))
    db.flush()
    return ident, buyer_id, seller_id


@router.post("/session")
def create_session(body: SessionIn, request: Request, response: Response, db=Depends(db_dep)):
    if not same_origin(request):
        fail(403, "Cross-origin action rejected")
    if settings.paypal_env != "mock":
        fail(409, "The public demonstration requires mock payment mode")
    previous = request.cookies.get("ciq_session", "")
    existing = db.get(DemoSession, hashlib.sha256(previous.encode()).hexdigest())
    if existing and aware(existing.expires_at) > now():
        return {"csrf": existing.csrf, "demo": True}
    if settings.hosted_demo:
        with WRITE_LOCK:
            stamp = time.monotonic()
            while NEW_DEMO_REQUESTS and NEW_DEMO_REQUESTS[0] <= stamp - 60:
                NEW_DEMO_REQUESTS.popleft()
            if len(NEW_DEMO_REQUESTS) >= 30:
                fail(429, "The demo is busy. Try again in a minute.")
            NEW_DEMO_REQUESTS.append(stamp)
    ident, buyer_id, seller_id = seed_workspace(db, body.persona)
    token = secrets.token_urlsafe(32)
    current = DemoSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), workspace_id=ident,
                          buyer_id=buyer_id, seller_id=seller_id, csrf=secrets.token_urlsafe(24), expires_at=now() + timedelta(days=7))
    db.add(current)
    response.set_cookie("ciq_session", token, httponly=True, samesite="strict", secure=settings.hosted_demo or request.url.scheme == "https", max_age=604800)
    return {"csrf": current.csrf, "demo": True}


@router.get("/session")
def get_session(request: Request, db=Depends(db_dep)):
    token_hash = hashlib.sha256(request.cookies.get("ciq_session", "").encode()).hexdigest()
    current = db.get(DemoSession, token_hash)
    if not current or aware(current.expires_at) <= now():
        fail(401, "Start your demo")
    return {"csrf": current.csrf, "demo": True}


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    language: Literal["en", "hi", "kn"] = "en"
    occupation: Literal["student", "salaried", "shopkeeper", "freelancer", "homemaker", "investor", "other"] = "student"
    configuration: Literal["personal", "business", "separate", "unified"] = "personal"
    override: Literal["auto", "personal", "business"] = "auto"
    features: list[Literal["budget", "purchases", "goals", "emi", "business", "investments"]] = ["budget", "purchases"]
    context_consent: bool = False
    location_consent: bool = False
    voice_enabled: bool = False
    learning_enabled: bool = False
    work_start: int = Field(default=9, ge=0, le=23)
    work_end: int = Field(default=18, ge=0, le=23)
    income_frequency: str = Field(default="", max_length=30)
    business_type: str = Field(default="", max_length=100)


@router.get("/profile")
def profile(current=Depends(session), db=Depends(db_dep)):
    return db.get(Personalization, current.buyer_id).data


@router.put("/profile")
def save_profile(body: ProfileIn, current=Depends(session), db=Depends(db_dep)):
    record = db.get(Personalization, current.buyer_id)
    record.data = record.data | body.model_dump() | {"onboarded": True}
    user = db.get(User, current.buyer_id)
    user.name = body.name
    user.setup_done = True
    user.uses = "both" if body.configuration in ("unified", "separate") else body.configuration
    return record.data


def workspace(profile, activity="", hour=None):
    config = profile.get("configuration", "personal")
    if config != "separate":
        return "all" if config == "unified" else config
    override = profile.get("override", "auto")
    if override != "auto":
        return override
    if not profile.get("context_consent"):
        return profile.get("workspace", "personal")
    if activity in ("supplier", "merchant", "business"):
        return "business"
    if activity == "personal":
        return "personal"
    hour = hour if hour is not None else (now() + timedelta(hours=5, minutes=30)).hour
    return "business" if profile.get("work_start", 9) <= hour < profile.get("work_end", 18) else "personal"


def bill_rows(db, user_id):
    bill_purposes = {}
    for plan in db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == user_id, PlanningRecord.kind == "emi")):
        bill_purposes.update({row["bill_id"]: plan.purpose for row in plan.data.get("schedule", [])})
    rows = db.scalars(select(Obligation).where(Obligation.owner_id == user_id, Obligation.kind.in_(("bill", "subscription", "emi", *BUSINESS_BILL_KINDS))))
    return [{"id": row.id, "title": row.title, "amount_minor": finance.minor(row.amount), "due": aware(row.due_at).date().isoformat(),
             "status": row.status, "purpose": bill_purposes.get(row.id, "business" if row.kind in BUSINESS_BILL_KINDS else "personal"), "kind": row.kind} for row in rows]


def observations(db, user_id):
    active = set()
    tracked_bills = [bill | {"destination": f"#/budget/bills/{bill['id']}"} for bill in bill_rows(db, user_id)]
    supplier_invoices = db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == user_id, PlanningRecord.kind == "supplier_invoice"))
    tracked_bills.extend({"id": row.id, "title": row.title, "purpose": "business", "status": "open",
                          "amount_minor": row.data["amount_minor"], "due": row.data["due"],
                          "destination": f"#/budget/business/{row.id}"}
                         for row in supplier_invoices if row.data.get("status") == "open" and row.data.get("due"))
    for bill in tracked_bills:
        if bill["status"] != "open":
            continue
        ident = f"bill:{bill['id']}"
        active.add(ident)
        row = db.get(Observation, ident)
        due_days = (datetime.fromisoformat(bill["due"]).date() - now().date()).days
        if not row:
            row = Observation(id=ident, user_id=user_id, kind="bill", priority=80, source_id=bill["id"], destination=bill["destination"], data=bill)
            db.add(row)
        row.priority = 95 if due_days <= 1 else max(20, 80 - due_days)
        row.data = bill | {"days": due_days}
        row.resolved = False
    for incident in db.scalars(select(PaymentIncident).where(PaymentIncident.user_id == user_id)):
        ident = f"incident:{incident.id}"
        active.add(ident)
        row = db.get(Observation, ident)
        if not row:
            row = Observation(id=ident, user_id=user_id, kind="payment", priority=100, source_id=incident.id,
                              destination=f"#/activity/issues/{incident.id}", data={})
            db.add(row)
        row.priority = 100 if incident.status == "checking" else 65
        row.data = {"status": incident.status}
    for item in db.scalars(select(PurchaseItem).where(PurchaseItem.buyer_id == user_id)):
        state_id = f"item:{item.id}:{item.state}:{item.request}"
        active.add(state_id)
        if not db.get(Observation, state_id):
            db.add(Observation(id=state_id, user_id=user_id, kind="purchase", priority=70 if item.request else 45,
                               source_id=item.id, destination=f"#/purchases/item/{item.id}",
                               data={"title": item.name, "status": item.request or item.state}))
        if not item.delivered_at or item.request or item.refunded_quantity >= item.quantity:
            continue
        age = (now().date() - aware(item.delivered_at).date()).days
        case = db.get(Case, item.case_id)
        for kind, duration in PURCHASE_WINDOWS.items():
            days_left = duration - age
            if not 0 <= days_left <= (7 if kind == "replacement" else 3):
                continue
            ident = f"{kind}:{item.id}"
            active.add(ident)
            row = db.get(Observation, ident)
            if not row:
                row = Observation(id=ident, user_id=user_id, kind=kind, priority=60 if kind == "replacement" else 55, source_id=item.id,
                                  destination=f"#/purchases/item/{item.id}", data={})
                db.add(row)
            row.data = {"title": item.name, "days": days_left, "purpose": case.purpose}
    watched_ids = select(PriceWatch.id).where(PriceWatch.user_id == user_id, PriceWatch.enabled)
    active.update(db.scalars(select(Observation.id).where(Observation.kind == "price_low", Observation.source_id.in_(watched_ids))))
    db.flush()
    records = list(db.scalars(select(Observation).where(Observation.user_id == user_id).order_by(Observation.priority.desc(), Observation.created_at)))
    for row in records:
        row.resolved = row.id not in active
    return [{"id": row.id, "kind": row.kind, "priority": row.priority, "destination": row.destination,
             "data": row.data, "read": row.read} for row in records if not row.resolved]


def daily_date():
    return (now() + timedelta(hours=5, minutes=30)).date().isoformat()


def daily_task_key(user_id, suggestion_id):
    return hashlib.sha256(f"daily:{user_id}:{daily_date()}:{suggestion_id}".encode()).hexdigest()


def reminder_priority(note, today):
    """Rank active issues and recorded deadlines ahead of routine suggestions."""
    kind, data = note["kind"], note["data"]
    if kind == "payment" and data.get("status") == "checking":
        return 100
    if kind in PURCHASE_WINDOWS:
        return {0: 94, 1: 87, 2: 79}.get(data["days"], note["priority"])
    if kind not in {"bill", "receivable"} or not data.get("due"):
        return note["priority"]
    days = (datetime.fromisoformat(data["due"]).date() - today).days
    if kind == "bill":
        if days < 0:
            return 98
        return {0: 96, 1: 90, 2: 81, 3: 78}.get(days, max(20, 74 - days))
    if days < 0:
        return 89
    return {0: 85, 1: 80}.get(days, note["priority"])


def daily_suggestions(db, user_id, purpose, notes, plans):
    eligible = [note for note in notes if purpose == "all" or note["data"].get("purpose", purpose) in (purpose, "all")]
    for plan in plans:
        if purpose != "all" and plan.purpose != purpose:
            continue
        data = plan.data
        if plan.kind == "receivable" and data.get("status") == "open" and data.get("amount_minor"):
            eligible.append({"id": f"receivable:{plan.id}", "kind": "receivable", "priority": 61,
                             "destination": f"#/budget/business/{plan.id}",
                             "data": {"title": plan.title, "amount_minor": data["amount_minor"], "due": data.get("due")}})
        if plan.kind == "goal" and data.get("status") not in ("paused", "purchased") and data["saved_minor"] < data["target_minor"]:
            eligible.append({"id": f"goal:{plan.id}", "kind": "goal", "priority": 18,
                             "destination": f"#/budget/goals/{plan.id}",
                             "data": {"title": plan.title, "amount_minor": data["target_minor"] - data["saved_minor"]}})
    today = datetime.fromisoformat(daily_date()).date()
    ranked = sorted(eligible, key=lambda note: (-reminder_priority(note, today), note["data"].get("due") or ""))
    result, destinations = [], set()
    for note in ranked:
        if note["destination"] in destinations:
            continue
        destinations.add(note["destination"])
        done = db.get(PlanningRecord, daily_task_key(user_id, note["id"]))
        result.append(note | {"completed": bool(done and done.data.get("completed"))})
        if len(result) >= 3:
            break
    return result


class DailyTaskIn(BaseModel):
    id: str = Field(min_length=5, max_length=160)
    completed: bool


@router.put("/daily-tasks")
def set_daily_task(body: DailyTaskIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        user_id = current.buyer_id
        plans = list(db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == user_id)))
        prefs = db.get(Personalization, user_id).data
        relevant = daily_suggestions(db, user_id, workspace(prefs), observations(db, user_id), plans)
        if body.id not in {note["id"] for note in relevant}:
            fail(404, "Today's task is not available")
        key = daily_task_key(user_id, body.id)
        record = db.get(PlanningRecord, key)
        if not record:
            record = PlanningRecord(id=key, user_id=user_id, kind="daily_task", title=body.id)
            db.add(record)
        record.data = {"date": daily_date(), "completed": body.completed}
        db.commit()
    return {"ok": True}


@router.get("/dashboard")
def dashboard(activity: str = "", hour: int | None = None, days: int = 30, current=Depends(session), db=Depends(db_dep)):
    prefs = db.get(Personalization, current.buyer_id).data
    purpose = workspace(prefs, activity, hour)
    financial = finance.summary(db, current.buyer_id, purpose, days=min(max(days, 7), 90))
    bills = [row for row in bill_rows(db, current.buyer_id) if purpose == "all" or row["purpose"] == purpose]
    plans = list(db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == current.buyer_id)))
    allocation = finance.spending_allocation(financial["balance_minor"], purpose, bills, plans)
    notes = observations(db, current.buyer_id)
    suggestions = daily_suggestions(db, current.buyer_id, purpose, notes, plans)
    return {"profile": prefs, "workspace": purpose, "finance": financial, "bills": bills,
            "committed_minor": allocation["committed_minor"],
            "allocated_minor": allocation["reserved_minor"] + allocation["savings_minor"],
            "flexible_minor": allocation["flexible_minor"], "allocation": allocation,
            "observations": notes, "suggestions": suggestions, "task_date": daily_date(),
            "focus": next((note for note in suggestions if not note["completed"]), None),
            "demo": True, "provider": "mock", "as_of": now().isoformat()}


@router.get("/history")
def history(current=Depends(session), db=Depends(db_dep)):
    return [{"id": row.id, "payee": row.payee, "description": row.description, "amount_minor": row.amount_minor,
             "currency": row.currency, "purpose": row.purpose, "category": row.category, "date": row.occurred_at.isoformat(),
             "case_id": row.case_id, "source": row.source} for row in reversed(finance.entries(db, current.buyer_id))]


class LedgerIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    amount_minor: int = Field(gt=0, le=100000000)
    direction: Literal["income", "expense"]
    purpose: Literal["personal", "business"] = "personal"
    category: str = Field(default="general", max_length=40)
    request_id: str = Field(min_length=8, max_length=80)


@router.post("/history")
def add_entry(body: LedgerIn, current=Depends(session), db=Depends(db_dep)):
    key = f"manual:{current.buyer_id}:{body.request_id}"
    with WRITE_LOCK:
        existing = db.scalar(select(LedgerEntry).where(LedgerEntry.settlement_key == key))
        if existing:
            return {"id": existing.id}
        amount = body.amount_minor * (-1 if body.direction == "income" else 1)
        row = LedgerEntry(user_id=current.buyer_id, payee=body.title, description=body.title, amount=amount / 100,
                          amount_minor=amount, currency="INR", purpose=body.purpose, category=body.category,
                          source="user_entered", settlement_key=key)
        db.add(row)
        db.commit()
        return {"id": row.id}


@router.post("/notifications/{ident}/read")
def mark_read(ident: str, current=Depends(session), db=Depends(db_dep)):
    row = db.get(Observation, ident)
    if not row or row.user_id != current.buyer_id:
        fail(404, "Notification not found")
    row.read = True
    return {"ok": True}


@router.get("/catalog")
def catalog(current=Depends(session)):
    return {"products": CATALOG, "policy": POLICY, "merchant": "BrightMart Electronics", "demo": True}


class CartLine(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=100)


class CartIn(BaseModel):
    items: list[CartLine] = Field(max_length=30)


def cart_items(lines):
    products = {product["id"]: product for product in CATALOG}
    result = []
    for line in lines:
        product = products.get(line.product_id)
        if not product:
            fail(422, "Product is unavailable")
        result.append({"id": _id(), "product_id": product["id"], "name": product["name"], "unit_minor": product["price_minor"],
                       "quantity": line.quantity, "description": product["description"]})
    return result


@router.get("/cart")
def get_cart(current=Depends(session), db=Depends(db_dep)):
    data = db.get(Personalization, current.buyer_id).data.get("cart", [])
    return {"items": data, "total_minor": sum(row["unit_minor"] * row["quantity"] for row in data)}


@router.put("/cart")
def set_cart(body: CartIn, current=Depends(session), db=Depends(db_dep)):
    prefs = db.get(Personalization, current.buyer_id)
    items = cart_items(body.items)
    prefs.data = prefs.data | {"cart": items}
    return {"items": items, "total_minor": sum(row["unit_minor"] * row["quantity"] for row in items)}


class InvoiceIn(BaseModel):
    kind: Literal["itemized", "payment"] = "itemized"
    items: list[CartLine] = Field(default=[], max_length=30)
    amount_minor: int | None = Field(default=None, gt=0, le=100000000)
    description: str = Field(default="Payment request", min_length=1, max_length=100)
    purpose: Literal["personal", "business"] = "personal"
    previous_id: str | None = None


def create_invoice(db, current, body):
    version = 1
    if body.previous_id:
        old = owned_invoice(db, current, body.previous_id)
        if old.case_id or db.get(ProviderCheckout, old.id):
            fail(409, "An authorized invoice cannot be revised")
        old.status = "superseded"
        version = old.version + 1
    items = cart_items(body.items)
    if body.kind == "payment":
        if body.amount_minor is None:
            fail(422, "Enter the exact requested amount")
        items = [{"id": _id(), "product_id": "payment", "name": body.description, "unit_minor": body.amount_minor, "quantity": 1, "description": "Amount-based payment request"}]
    if not items:
        fail(422, "Add at least one item")
    total = sum(row["unit_minor"] * row["quantity"] for row in items)
    if total > 100000000:
        fail(422, "Demo invoice limit exceeded")
    fingerprint = hashlib.sha256(json.dumps({"items": items, "total": total, "currency": "INR", "version": version, "seller": current.seller_id}, sort_keys=True).encode()).hexdigest()
    row = InvoiceSnapshot(workspace_id=current.workspace_id, buyer_id=current.buyer_id, seller_id=current.seller_id,
                          kind=body.kind, items=items, total_minor=total, purpose=body.purpose, policy=POLICY,
                          version=version, previous_id=body.previous_id, fingerprint=fingerprint, expires_at=now() + timedelta(minutes=15))
    db.add(row)
    db.flush()
    row.qr_token = crypto.sign_message({"typ": "ciq.invoice/2", "invoice": row.id, "workspace": current.workspace_id, "fingerprint": fingerprint}, ttl=900)
    return row


def owned_invoice(db, current, ident):
    row = db.get(InvoiceSnapshot, ident)
    if not row or row.workspace_id != current.workspace_id:
        fail(404, "Invoice not found")
    return row


def purchase_budget(db, row):
    prefs = db.get(Personalization, row.buyer_id).data
    scope = "all" if prefs.get("configuration") == "unified" else row.purpose
    funds = finance.summary(db, row.buyer_id, scope)["balance_minor"]
    plans = list(db.scalars(select(PlanningRecord).where(
        PlanningRecord.user_id == row.buyer_id, PlanningRecord.kind.in_(("allocation", "goal", "supplier_invoice")))))
    bills = bill_rows(db, row.buyer_id)
    current = finance.spending_allocation(funds, scope, bills, plans)
    payable = row.status in ("open", "authorized", "provider_checkout")
    projected_funds = funds - (row.total_minor if payable else 0)
    items = purchased_totals(row.items)
    projected = finance.spending_allocation(projected_funds, scope, bills, plans, items, row.purpose) if payable else current
    planned = next((plan for plan in plans if plan.kind == "goal" and plan.purpose == row.purpose
                    and plan.data.get("status") == "active" and plan.data.get("product_id") in items), None)
    hard_budget = funds - current["committed_minor"] - current["reserved_minor"]
    return {"scope": scope, "funds_minor": funds, "projected_funds_minor": projected_funds,
            "bills_minor": current["committed_minor"], "allocated_minor": current["reserved_minor"],
            "flexible_before_minor": current["flexible_minor"], "savings_before_minor": current["savings_minor"],
            "savings_after_minor": projected["savings_minor"], "remaining_minor": projected["flexible_minor"],
            "purchase_plan_id": planned.id if payable and planned else None,
            "alternative": next((p for p in CATALOG if p["id"] == "headphones" and p["price_minor"] <= hard_budget), None)
            if payable and projected["flexible_minor"] < 0 and any(i.get("product_id") == "premium" for i in row.items) else None}


def invoice_view(db, row):
    from .v2_checkout import checkout_info
    return {"id": row.id, "version": row.version, "kind": row.kind, "items": row.items, "total_minor": row.total_minor,
            "currency": row.currency, "purpose": row.purpose, "merchant": "BrightMart Electronics", "policy": row.policy,
            "status": row.status, "fingerprint": row.fingerprint, "qr_token": row.qr_token, "expires_at": aware(row.expires_at).isoformat(),
            "case_id": row.case_id, "checkout": checkout_info(db, row.id, row.case_id),
            "affordability": purchase_budget(db, row)}


@router.post("/invoices")
def new_invoice(body: InvoiceIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = create_invoice(db, current, body)
        db.commit()
        return invoice_view(db, row)


@router.get("/invoices")
def invoices(current=Depends(session), db=Depends(db_dep)):
    return [invoice_view(db, row) for row in db.scalars(select(InvoiceSnapshot).where(InvoiceSnapshot.workspace_id == current.workspace_id).order_by(InvoiceSnapshot.created_at.desc()))]


@router.get("/invoices/{ident}")
def invoice(ident: str, current=Depends(session), db=Depends(db_dep)):
    return invoice_view(db, owned_invoice(db, current, ident))


@router.post("/invoices/{ident}/cancel")
def cancel_invoice(ident: str, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = owned_invoice(db, current, ident)
        if row.case_id or db.get(ProviderCheckout, row.id):
            fail(409, "An authorized payment must be resolved through its purchase record")
        row.status = "cancelled"
        db.commit()
        return {"ok": True}


class ScanIn(BaseModel):
    token: str = Field(min_length=1, max_length=10000)


@router.post("/scan")
def scan(body: ScanIn, current=Depends(session), db=Depends(db_dep)):
    raw = body.token.strip()
    if not raw.startswith("ciq1."):
        from .agents.qr import interpret
        from .v2_checkout import upi_handoff
        try:
            details = interpret(raw)
            if isinstance(details.get("amount"), float) and not math.isfinite(details["amount"]):
                fail(422, "The QR amount is invalid")
            uri = upi_handoff(raw) if details["format"] == "UPI payment request" else None
            return {"external": True, "details": details, "execution_available": bool(uri), "upi_uri": uri}
        except (ValueError, TypeError):
            fail(422, "This QR contains an invalid payment amount")
    try:
        signed = crypto.verify_message(db, raw, consume=False)
    except crypto.TokenError as exc:
        fail(422, str(exc))
    row = owned_invoice(db, current, signed.get("invoice", ""))
    if signed.get("fingerprint") != row.fingerprint or row.qr_token != raw:
        fail(422, "Invoice signature does not match")
    if aware(row.expires_at) <= now():
        fail(409, "This invoice has expired. Create a new QR.")
    if row.status != "open":
        fail(409, f"This invoice is {row.status}")
    return {"invoice": invoice_view(db, row)}


class AuthorizeIn(BaseModel):
    fingerprint: str
    version: int
    authorized: bool
    simulated_method: Literal["mock", "upi", "card", "netbanking"] = "mock"
    simulate_interruption: bool = False
    step_up_code: str | None = None


def finalize_payment(db, current, row, result):
    case = db.get(Case, row.case_id)
    if not result.get("ok") or case.payment_state != "captured":
        return result
    first_settlement = row.status != "paid"
    row.status = "paid"
    owned_items = row.items if row.kind == "itemized" else []
    for item in owned_items:
        if not db.get(PurchaseItem, item["id"]):
            db.add(PurchaseItem(id=item["id"], case_id=case.id, buyer_id=current.buyer_id, seller_id=current.seller_id,
                                name=item["name"], quantity=item["quantity"], unit_minor=item["unit_minor"]))
    sale_key = f"sale:{case.id}"
    if not db.scalar(select(LedgerEntry).where(LedgerEntry.settlement_key == sale_key)):
        db.add(LedgerEntry(user_id=current.seller_id, case_id=case.id, payee=db.get(User, current.buyer_id).name,
                          description=case.title, category="sales", purpose="business", amount=-case.amount,
                          currency=case.currency, settlement_key=sale_key))
    if first_settlement and owned_items:
        apply_purchased_quantities(db, current.buyer_id, owned_items, row.purpose)
    incident = db.scalar(select(PaymentIncident).where(PaymentIncident.case_id == case.id))
    if incident:
        incident.status = "recovered"
        incident.steps = result.get("trace", []) + ["Original capture verified. One buyer ledger settlement recorded."]
    db.flush()
    db.get(User, current.buyer_id).available_balance = finance.summary(db, current.buyer_id)["balance_minor"] / 100
    return result | {"case_id": case.id, "status": "paid", "item_ids": [i["id"] for i in owned_items]}


def purchased_totals(items):
    totals = {}
    for item in items:
        sku = item.get("product_id")
        if sku:
            units, amount = totals.get(sku, (0, 0))
            totals[sku] = (units + item["quantity"], amount + item["quantity"] * item["unit_minor"])
    return totals


def apply_purchased_quantities(db, user_id, items, purpose):
    from .v2_watch import linked_purchase_plan, update_purchase_plan

    purchased_products = purchased_totals(items)
    if not purchased_products:
        return
    prefs = db.get(Personalization, user_id)
    cart = []
    for line in prefs.data.get("cart", []):
        remaining = line["quantity"] - purchased_products.get(line["product_id"], (0, 0))[0]
        if remaining > 0:
            cart.append(line | {"quantity": remaining})
    prefs.data = prefs.data | {"cart": cart}
    urls = {f"{settings.store_url}/product/{sku}": purchase for sku, purchase in purchased_products.items()}
    watches = db.scalars(select(PriceWatch).where(PriceWatch.user_id == user_id, PriceWatch.enabled,
                                                PriceWatch.source_url.in_(urls)))
    for watch in watches:
        plan = linked_purchase_plan(db, watch)
        if plan and plan.data.get("status") != "purchased" and plan.purpose != purpose:
            continue
        units, amount = urls[watch.source_url]
        if units >= watch.quantity:
            watch.enabled = False
            if plan:
                plan.data = plan.data | {"status": "purchased"}
        else:
            watch.quantity -= units
            if plan:
                plan.data = plan.data | {"saved_minor": max(0, plan.data["saved_minor"] - amount)}
                update_purchase_plan(plan, watch)


@router.post("/invoices/{ident}/authorize")
def authorize(ident: str, body: AuthorizeIn, current=Depends(session), db=Depends(db_dep)):
    from .v2_checkout import recorded_demo_method
    with WRITE_LOCK:
        row = owned_invoice(db, current, ident)
        if db.get(ProviderCheckout, row.id):
            fail(409, "Use your existing provider checkout for this invoice")
        if not body.authorized or body.fingerprint != row.fingerprint or body.version != row.version:
            fail(409, "Review and authorize the exact current invoice")
        previous_method = recorded_demo_method(db, row.case_id)
        if previous_method and previous_method != body.simulated_method:
            fail(409, "Continue with the method already selected for this payment")
        if row.status == "paid":
            return {"ok": True, "case_id": row.case_id, "status": "paid", "replayed": True}
        if row.status not in ("open", "authorized") or (not row.case_id and aware(row.expires_at) <= now()):
            fail(409, "Invoice is expired, cancelled or superseded. Create a new QR.")
        if settings.paypal_env != "mock":
            fail(409, "This INR demonstration supports the mock provider")
        if not row.case_id:
            checkout = commerce.start_checkout(db, current.buyer_id, merchant="BrightMart Electronics", seller_id=current.seller_id,
                        items=[{"name": item["name"], "quantity": item["quantity"], "unit_price": item["unit_minor"] / 100} for item in row.items],
                        currency="INR", policy_text=row.policy, purpose=row.purpose)
            row.case_id, row.approval_token = checkout["case_id"], checkout["approval_token"]
            row.status = "authorized"
            briefcase.add_evidence(db, db.get(Case, row.case_id), kind="invoice_snapshot", source="merchant", provenance="claimed",
                                  summary=f"Invoice {row.id}, version {row.version}, explicitly authorized",
                                  content={"items": row.items, "fingerprint": row.fingerprint, "simulated_method": body.simulated_method})
            db.commit()
        case = db.get(Case, row.case_id)
        mock.approve(case.paypal_order_id)
        if body.simulate_interruption and not db.scalar(select(PaymentIncident).where(PaymentIncident.case_id == case.id)):
            db.add(PaymentIncident(user_id=current.buyer_id, case_id=case.id, steps=["Demo response interruption requested after provider acceptance."]))
            db.commit()
        # Set the fault only after the gateway can pass step-up, scoped to this order.
        if body.simulate_interruption and (body.step_up_code or case.amount < settings.new_payee_step_up_amount):
            mock.inject_fault(f"capture_timeout_after_commit:{case.paypal_order_id}")
        result = commerce.complete_payment(db, current.buyer_id, case.id, row.approval_token, body.step_up_code)
        incident = db.scalar(select(PaymentIncident).where(PaymentIncident.case_id == case.id))
        if not incident and (result.get("pending") or result.get("healed")):
            incident = PaymentIncident(user_id=current.buyer_id, case_id=case.id, steps=result.get("trace", []))
            db.add(incident)
            db.flush()
        if incident and not result.get("ok") and result.get("trace"):
            incident.steps = result["trace"]
            incident.status = "checking" if result.get("pending") else "needs_review"
        result = finalize_payment(db, current, row, result)
        db.commit()
        return result


@router.post("/invoices/{ident}/reconcile")
def reconcile(ident: str, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = owned_invoice(db, current, ident)
        result = reconcile_authorized(db, current, row)
        db.commit()
        return result


def reconcile_authorized(db, current, row):
    if row.status == "paid":
        return {"ok": True, "status": "paid", "replayed": True}
    if not row.case_id:
        fail(409, "No authorized payment exists")
    case = db.get(Case, row.case_id)
    try:
        state = payments.sync_order_state(db, case)
    except payments.TRANSIENT:
        return {"ok": False, "pending": True, "message": "Provider unavailable. Your payment remains under review."}
    captured = case.payment_state == "captured"
    result = {"ok": captured, "pending": not captured, "trace": [f"Provider status {state['order_status']}"]}
    if captured:
        commerce._after_capture(db, case, current.buyer_id)
    return finalize_payment(db, current, row, result)


def refresh_interrupted_payments(db, current):
    if settings.paypal_env != "mock":
        return
    invoices = db.scalars(select(InvoiceSnapshot).join(PaymentIncident, PaymentIncident.case_id == InvoiceSnapshot.case_id)
                          .where(InvoiceSnapshot.workspace_id == current.workspace_id, InvoiceSnapshot.status == "authorized",
                                 PaymentIncident.status == "checking").order_by(InvoiceSnapshot.created_at))
    for row in invoices:
        reconcile_authorized(db, current, row)


def purchase_view(db, item):
    case = db.get(Case, item.case_id)
    delivered = aware(item.delivered_at) if item.delivered_at else None
    return {"id": item.id, "case_id": item.case_id, "name": item.name, "quantity": item.quantity,
            "unit_minor": item.unit_minor, "currency": case.currency, "state": item.state, "request": item.request,
            "delivered_quantity": item.delivered_quantity, "refunded_quantity": item.refunded_quantity,
            "delivered_at": delivered.isoformat() if delivered else None,
            "replacement_days": max(0, 7 - (now().date() - delivered.date()).days) if delivered else None,
            "return_until": (delivered + timedelta(days=30)).date().isoformat() if delivered else None,
            "warranty_until": (delivered + timedelta(days=365)).date().isoformat() if delivered else None,
            "merchant": case.merchant, "purpose": case.purpose, "payment_state": case.payment_state}


@router.get("/purchases")
def purchases(current=Depends(session), db=Depends(db_dep)):
    return [purchase_view(db, row) for row in db.scalars(select(PurchaseItem).where(PurchaseItem.buyer_id == current.buyer_id))]


def owned_item(db, current, ident):
    item = db.get(PurchaseItem, ident)
    if not item or item.buyer_id != current.buyer_id or item.seller_id != current.seller_id:
        fail(404, "Purchase not found")
    return item


@router.get("/purchases/{ident}")
def purchase(ident: str, current=Depends(session), db=Depends(db_dep)):
    return purchase_view(db, owned_item(db, current, ident))


class LifecycleIn(BaseModel):
    action: Literal["ship", "deliver", "defect", "replacement", "approve_replacement", "return", "warranty"]
    quantity: int = Field(default=1, ge=1, le=100)
    issue: str = Field(default="One earpiece is defective", max_length=500)
    days_ago: int = Field(default=0, ge=0, le=30)


@router.post("/purchases/{ident}/action")
def lifecycle(ident: str, body: LifecycleIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        item = owned_item(db, current, ident)
        case = db.get(Case, item.case_id)
        if body.action in ("ship", "deliver", "approve_replacement") and settings.paypal_env != "mock":
            fail(403, "Seller simulation requires mock mode")
        if body.action == "ship":
            if item.delivered_at or item.refunded_quantity:
                fail(409, "A delivered or refunded item cannot return to shipment")
            item.state = "shipped"
            payments.add_tracking_for_case(db, case, f"DEMO-{item.id}", "OTHER")
        elif body.action == "deliver":
            if body.quantity > item.quantity or body.quantity < item.delivered_quantity:
                fail(422, "Delivered quantity exceeds purchase quantity")
            if item.refunded_quantity:
                fail(409, "A refunded item cannot be marked delivered")
            item.delivered_quantity = max(item.delivered_quantity, body.quantity)
            # The first delivery starts this line's policy window; retries never extend it.
            item.delivered_at = item.delivered_at or now() - timedelta(days=body.days_ago)
            item.state = "delivered" if item.delivered_quantity == item.quantity else "partially_delivered"
            commerce.record_delivery(db, case.id, item.delivered_at, source="demo_merchant")
        elif body.action in ("replacement", "return", "warranty"):
            if not item.delivered_at:
                fail(409, "A delivery record is needed to check this policy window")
            age = (now().date() - aware(item.delivered_at).date()).days
            limit = PURCHASE_WINDOWS[body.action]
            if age > limit:
                fail(409, "The recorded policy window has closed")
            if item.refunded_quantity >= item.quantity:
                fail(409, "This item has already been refunded")
            if item.request == f"{body.action}_requested":
                return purchase_view(db, item)
            item.request = f"{body.action}_requested"
            db.add(OutboundNotice(user_id=current.buyer_id, recipient=current.seller_id, channel="in_app",
                                  notice_type=body.action, subject=f"{item.name} — {body.action}", message=body.issue,
                                  amount=item.unit_minor / 100, status="sent_in_app"))
        elif body.action == "approve_replacement":
            if item.request != "replacement_requested":
                fail(409, "No replacement request is awaiting review")
            item.request = "replacement_approved"
        elif body.action == "defect":
            item.request = "defect_reported"
        briefcase.add_event(db, case, body.action, "demo_merchant" if body.action in ("deliver", "ship", "approve_replacement") else "buyer", {"item_id": item.id, "quantity": body.quantity, "issue": body.issue})
        briefcase.add_evidence(db, case, kind="item_lifecycle", source="demo", provenance="claimed",
                              summary=f"{item.name}: {body.action}", content={"item_id": item.id, "action": body.action, "simulated": True})
        db.commit()
        return purchase_view(db, item)


@router.get("/briefcases/{case_id}")
def case_detail(case_id: str, merchant: bool = False, current=Depends(session), db=Depends(db_dep)):
    case = db.get(Case, case_id)
    if not case or case.owner_id != current.buyer_id or case.counterparty_id != current.seller_id:
        fail(404, "Briefcase not found")
    result = briefcase.view_case(db, case_id, current.seller_id if merchant else current.buyer_id)
    if result and result.get("policy"):
        snapshot = db.scalar(select(PolicySnapshot).where(PolicySnapshot.case_id == case_id))
        if snapshot:
            result["policy"]["original_text"] = snapshot.text
    return result


@router.post("/briefcases/{case_id}/investigate")
def investigate(case_id: str, current=Depends(session), db=Depends(db_dep)):
    case_detail(case_id, False, current, db)
    hosted = db.scalar(select(ProviderCheckout).join(InvoiceSnapshot, InvoiceSnapshot.id == ProviderCheckout.invoice_id).where(InvoiceSnapshot.case_id == case_id))
    if hosted and hosted.payment_id:
        return {"summary": "Razorpay test capture was confirmed for this invoice.", "payment_id": hosted.payment_id,
                "provider_order": hosted.order_id, "method": hosted.method, "payment_state": "captured"}
    return commerce.payment_investigation(db, db.get(Case, case_id))


@router.post("/briefcases/{case_id}/connect")
def connect(case_id: str, current=Depends(session), db=Depends(db_dep)):
    case_detail(case_id, False, current, db)
    from . import a2a
    return a2a.run_session(db, case_id, current.buyer_id)


@router.get("/incidents")
def incidents(current=Depends(session), db=Depends(db_dep)):
    return [{"id": row.id, "case_id": row.case_id, "provider": row.provider, "status": row.status,
             "steps": row.steps, "created_at": row.created_at.isoformat()} for row in db.scalars(select(PaymentIncident).where(PaymentIncident.user_id == current.buyer_id))]


class BillIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    amount_minor: int = Field(gt=0, le=100000000)
    due: str
    purpose: Literal["personal", "business"] = "personal"
    recurring: bool = False
    import_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@router.get("/bills")
def bills(current=Depends(session), db=Depends(db_dep)):
    return sorted(bill_rows(db, current.buyer_id), key=lambda row: row["due"])


@router.get("/merchant")
def merchant_desk(current=Depends(session), db=Depends(db_dep)):
    records = finance.entries(db, current.seller_id, "business")
    cases = db.scalars(select(Case).where(Case.counterparty_id == current.seller_id, Case.owner_id == current.buyer_id))
    return {"sales_minor": -sum(row.amount_minor for row in records if row.amount_minor < 0),
            "refunds_minor": sum(row.amount_minor for row in records if row.amount_minor > 0),
            "orders": [{"id": row.id, "title": row.title, "amount_minor": finance.minor(row.amount), "payment_state": row.payment_state,
                        "items": [{"id": item.id, "name": item.name} for item in db.scalars(select(PurchaseItem).where(PurchaseItem.case_id == row.id))]} for row in cases]}


@router.post("/bills")
def add_bill(body: BillIn, current=Depends(session), db=Depends(db_dep)):
    try:
        due = datetime.fromisoformat(body.due).replace(tzinfo=UTC)
    except ValueError:
        fail(422, "Enter a valid due date")
    with WRITE_LOCK:
        key = hashlib.sha256(f"bill-import:{current.buyer_id}:{body.import_key}".encode()).hexdigest() if body.import_key else None
        previous = db.get(PlanningRecord, key) if key else None
        if previous:
            return {"id": previous.data["bill_id"], "replayed": True}
        if body.purpose == "business":
            kind = "recurring_supplier_payment" if body.recurring else "supplier_payment"
        else:
            kind = "subscription" if body.recurring else "bill"
        row = Obligation(owner_id=current.buyer_id, kind=kind, title=body.title,
                         amount=body.amount_minor / 100, due_at=due)
        db.add(row)
        db.flush()
        if key:
            db.add(PlanningRecord(id=key, user_id=current.buyer_id, kind="bill_import",
                                  title=body.title, data={"bill_id": row.id}))
        db.commit()
        return {"id": row.id}


class ConfirmIn(BaseModel):
    confirmed: bool


@router.post("/bills/{ident}/record-payment")
def record_bill_payment(ident: str, body: ConfirmIn, current=Depends(session), db=Depends(db_dep)):
    if not body.confirmed:
        fail(422, "Confirm the payment record")
    with WRITE_LOCK:
        row = db.get(Obligation, ident)
        if not row or row.owner_id != current.buyer_id:
            fail(404, "Bill not found")
        if row.status == "done":
            return {"ok": True, "replayed": True}
        purpose = next(b["purpose"] for b in bill_rows(db, current.buyer_id) if b["id"] == ident)
        db.add(LedgerEntry(user_id=current.buyer_id, payee=row.title, description="Payment recorded by user", category=row.kind,
                           purpose=purpose, amount=row.amount,
                           currency="INR", settlement_key=f"bill:{ident}", source="user_entered"))
        row.status = "done"
        if row.kind in RECURRING_BILL_KINDS:
            db.add(Obligation(owner_id=current.buyer_id, kind=row.kind, title=row.title, amount=row.amount, due_at=row.due_at + timedelta(days=30)))
        for plan in db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == current.buyer_id, PlanningRecord.kind == "emi")):
            schedule = [entry | {"paid": True} if entry["bill_id"] == ident else entry for entry in plan.data["schedule"]]
            plan.data = plan.data | {"schedule": schedule}
        db.commit()
        return {"ok": True, "provenance": "user_entered"}


class PlanIn(BaseModel):
    kind: Literal["goal", "allocation", "emi"]
    title: str = Field(min_length=1, max_length=100)
    purpose: Literal["personal", "business"] = "personal"
    target_minor: int = Field(default=0, ge=0, le=100000000)
    saved_minor: int = Field(default=0, ge=0, le=100000000)
    contribution_minor: int = Field(default=0, ge=0, le=100000000)
    horizon: Literal["short", "medium", "long"] = "medium"
    target_date: str = ""
    amount_minor: int = Field(default=0, ge=0, le=100000000)
    principal_minor: int = Field(default=0, ge=0, le=100000000)
    annual_rate: Decimal = Field(default=Decimal("0"), ge=0, le=60)
    months: int = Field(default=12, ge=1, le=120)


def plan_data(body):
    data = body.model_dump(mode="json")
    if body.kind == "goal" and (body.target_minor <= 0 or body.saved_minor > body.target_minor):
        fail(422, "Goal savings must fit within a positive target")
    if body.kind == "emi":
        if body.principal_minor <= 0:
            fail(422, "Enter the financed principal")
        principal = Decimal(body.principal_minor)
        rate = body.annual_rate / Decimal(1200)
        payment = principal / body.months if rate == 0 else principal * rate * (1 + rate) ** body.months / ((1 + rate) ** body.months - 1)
        installment = int(payment.quantize(Decimal("1")))
        balance = principal
        amounts = []
        for index in range(body.months):
            interest = (balance * rate).quantize(Decimal("1"))
            amount = int(balance + interest) if index == body.months - 1 else min(installment, int(balance + interest))
            amounts.append(amount)
            balance += interest - amount
        total = sum(amounts)
        data.update({"installment_minor": installment, "total_minor": total, "interest_minor": total - body.principal_minor, "installments_minor": amounts})
    return data


@router.post("/emi/compare")
def compare_emi(body: PlanIn, current=Depends(session)):
    if body.kind != "emi":
        fail(422, "An EMI comparison requires financing terms")
    return plan_data(body)


@router.get("/plans")
def plans(current=Depends(session), db=Depends(db_dep)):
    today = datetime.fromisoformat(daily_date()).date()
    rows = db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == current.buyer_id, PlanningRecord.kind.in_(("goal", "allocation", "emi"))))
    return [{"id": row.id, "kind": row.kind, "title": row.title, "purpose": row.purpose,
             "data": row.data | {"contribution_minor": finance.goal_contribution(row.data, today)}
             if row.kind == "goal" and row.data.get("linked_watch_id") else row.data} for row in rows]


@router.post("/plans")
def create_plan(body: PlanIn, current=Depends(session), db=Depends(db_dep)):
    data = plan_data(body)
    if body.kind == "emi":
        schedule = []
        for index in range(body.months):
            due = now() + timedelta(days=30 * (index + 1))
            amount = data["installments_minor"][index]
            bill = Obligation(owner_id=current.buyer_id, kind="emi", title=f"{body.title} · {index + 1}/{body.months}", amount=amount / 100, due_at=due)
            db.add(bill)
            db.flush()
            schedule.append({"number": index + 1, "due": due.date().isoformat(), "amount_minor": amount, "paid": False, "bill_id": bill.id})
        data["schedule"] = schedule
        data["schedule_basis"] = "User-entered estimate, every 30 days. Verify against the lender agreement."
    row = PlanningRecord(user_id=current.buyer_id, kind=body.kind, title=body.title, purpose=body.purpose, data=data)
    db.add(row)
    db.flush()
    return {"id": row.id, "data": data}


class SavingsIn(BaseModel):
    saved_minor: int = Field(ge=0, le=100000000)


@router.put("/plans/{ident}/savings")
def save_progress(ident: str, body: SavingsIn, current=Depends(session), db=Depends(db_dep)):
    with WRITE_LOCK:
        row = db.get(PlanningRecord, ident)
        if not row or row.user_id != current.buyer_id or row.kind != "goal":
            fail(404, "Goal not found")
        if row.data.get("status") == "purchased":
            fail(409, "This purchase plan is complete")
        if body.saved_minor > row.data["target_minor"]:
            fail(422, "Savings exceed this goal's target")
        row.data = row.data | {"saved_minor": body.saved_minor}
        db.commit()
        return {"ok": True}


@router.get("/forecast")
def forecast(current=Depends(session), db=Depends(db_dep)):
    uid = current.buyer_id
    scope = workspace(db.get(Personalization, uid).data)
    balance = finance.summary(db, uid, scope)["balance_minor"]
    plans = list(db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == uid, PlanningRecord.kind == "supplier_invoice")))
    commitments = finance.spending_allocation(balance, scope, bill_rows(db, uid), plans)["commitments"]
    start = datetime.fromisoformat(daily_date()).date()
    points = []
    for offset in range(31):
        date = (start + timedelta(days=offset)).isoformat()
        due = sum(b["amount_minor"] for b in commitments if b["due"] and b["due"][:10] <= date)
        points.append({"date": date, "balance_minor": balance - due})
    return {"points": points, "basis": "Projection deducts recorded open commitments. Unknown future income and spending are excluded."}


class NoticeIn(BaseModel):
    subject: str = Field(min_length=1, max_length=150)
    message: str = Field(min_length=1, max_length=3000)
    direction: Literal["buyer", "seller"] = "buyer"


@router.get("/notices")
def notices(current=Depends(session), db=Depends(db_dep)):
    rows = db.scalars(select(OutboundNotice).where(OutboundNotice.user_id.in_([current.buyer_id, current.seller_id])).order_by(OutboundNotice.created_at.desc()))
    return [{"id": row.id, "subject": row.subject, "message": row.message, "status": row.status, "channel": row.channel,
             "direction": "sent" if row.user_id == current.buyer_id else "inbox", "created_at": row.created_at.isoformat()} for row in rows]


@router.post("/notices")
def draft_notice(body: NoticeIn, current=Depends(session), db=Depends(db_dep)):
    row = OutboundNotice(user_id=current.buyer_id if body.direction == "buyer" else current.seller_id,
                         recipient=current.seller_id if body.direction == "buyer" else current.buyer_id,
                         channel="in_app", notice_type="message", subject=body.subject, message=body.message, status="draft")
    db.add(row)
    db.flush()
    return {"id": row.id}


@router.post("/notices/{ident}/send")
def send_notice(ident: str, body: ConfirmIn, current=Depends(session), db=Depends(db_dep)):
    row = db.get(OutboundNotice, ident)
    if not row or row.user_id not in (current.buyer_id, current.seller_id):
        fail(404, "Notice not found")
    if not body.confirmed:
        fail(422, "Review and approve the notice first")
    row.status = "sent_in_app"
    return {"ok": True, "status": row.status}


@router.post("/reset")
def reset(body: ConfirmIn, response: Response, current=Depends(session), db=Depends(db_dep)):
    if not body.confirmed:
        fail(422, "Confirm resetting this demo")
    # Revoke this workspace's session. A fresh start uses new identities and seed records.
    db.delete(current)
    response.delete_cookie("ciq_session")
    return {"ok": True}


class RefundIn(BaseModel):
    quantity: int = Field(ge=1, le=100)
    confirmed: bool
    request_id: str = Field(min_length=8, max_length=80)
    step_up_code: str | None = None


@router.post("/purchases/{ident}/refund")
def item_refund(ident: str, body: RefundIn, current=Depends(session), db=Depends(db_dep)):
    if not body.confirmed or settings.paypal_env != "mock":
        fail(403, "A confirmed demo seller refund is required")
    with WRITE_LOCK:
        item = owned_item(db, current, ident)
        operation = f"itemrefund:{item.id}:{body.request_id}"
        if db.scalar(select(LedgerEntry).where(LedgerEntry.settlement_key == operation)):
            return {"ok": True, "replayed": True}
        if body.quantity + item.refunded_quantity > item.quantity:
            fail(422, "Refund quantity exceeds the remaining purchased quantity")
        case = db.get(Case, item.case_id)
        if not case.paypal_capture_id:
            fail(409, "Refund this order through its original payment provider")
        from .security import gateway
        from .models import Approval
        from .paypal.adapter import get_client
        record_id = hashlib.sha256(operation.encode()).hexdigest()[:16]
        record = db.get(PlanningRecord, record_id)
        if record and record.data["quantity"] != body.quantity:
            fail(409, "This refund request already refers to a different quantity")
        if not record:
            approval = gateway.issue_approval(db, user_id=current.seller_id, case=case, action="refund")
            record = PlanningRecord(id=record_id, user_id=current.seller_id, kind="refund_approval", title=operation,
                                    data={"approval_token": approval.token, "quantity": body.quantity, "authorized": False})
            db.add(record)
        else:
            approval = db.get(Approval, record.data["approval_token"])
        if body.step_up_code:
            gateway.pass_step_up(db, approval.token, body.step_up_code)
        amount = item.unit_minor * body.quantity
        if not record.data["authorized"]:
            decision = gateway.check(db, actor=current.seller_id, action="refund", case=case, approval_token=approval.token, amount=amount / 100)
            if not decision.allowed:
                db.commit()
                return {"ok": False, "gateway": decision.decision, "step_up_code_demo": decision.step_up_code}
            record.data = record.data | {"authorized": True}
            # Persist exact authorization before calling the provider. A retry uses the same key.
            db.commit()
        result = get_client().refund_capture(case.paypal_capture_id, request_id=operation, amount=amount / 100, currency=case.currency, note="Demo seller-approved item refund")
        if result.get("status") != "COMPLETED":
            fail(409, "Refund is awaiting provider confirmation")
        item.refunded_quantity += body.quantity
        item.state = "refunded" if item.refunded_quantity == item.quantity else "partially_refunded"
        db.add(LedgerEntry(user_id=current.buyer_id, case_id=case.id, payee=case.merchant, description=f"Refund · {item.name}",
                          category=case.category, purpose=case.purpose, amount=-amount / 100, amount_minor=-amount, currency=case.currency, source="mock_refund", settlement_key=operation))
        db.add(LedgerEntry(user_id=current.seller_id, case_id=case.id, payee="Buyer refund", description=item.name,
                          category="refund", purpose="business", amount=amount / 100, amount_minor=amount, currency=case.currency, source="mock_refund", settlement_key=f"seller:{operation}"))
        briefcase.add_evidence(db, case, kind="item_refund", source="mock_provider", provenance="verified", summary=f"Refund confirmed for {body.quantity} × {item.name}", content=result)
        db.flush()
        items = list(db.scalars(select(PurchaseItem).where(PurchaseItem.case_id == case.id)))
        briefcase.set_payment_state(db, case, "refunded" if all(i.refunded_quantity == i.quantity for i in items) else "partially_refunded", "mock_provider", {"refund_id": result["id"]})
        db.commit()
        return {"ok": True, "refund_id": result["id"], "amount_minor": amount}


class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/ask")
def ask(body: AskIn, current=Depends(session), db=Depends(db_dep)):
    from .v2_intelligence import supervisor
    prefs = db.get(Personalization, current.buyer_id).data
    result = supervisor.invoke({"message": body.message, "db": db, "user_id": current.buyer_id,
                                "workspace_id": current.workspace_id, "language": prefs.get("language", "en")})
    output = {key: result[key] for key in ("topic", "answer", "destination", "evidence", "routing")}
    db.add(PlanningRecord(user_id=current.buyer_id, kind="conversation", title=body.message[:100], data={"question": body.message, **output, "at": now().isoformat()}))
    return output


@router.get("/ask")
def ask_history(current=Depends(session), db=Depends(db_dep)):
    rows = db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == current.buyer_id, PlanningRecord.kind == "conversation"))
    return sorted([row.data for row in rows], key=lambda row: row["at"])[-30:]


def observation_worker(stop):
    while not stop.wait(60):
        with WRITE_LOCK, SessionLocal() as db:
            try:
                for row in db.scalars(select(DemoSession).where(DemoSession.expires_at > now())):
                    refresh_interrupted_payments(db, row)
                    observations(db, row.buyer_id)
                db.commit()
            except Exception:
                db.rollback()
                import logging
                logging.getLogger(__name__).exception("Observation refresh failed")
