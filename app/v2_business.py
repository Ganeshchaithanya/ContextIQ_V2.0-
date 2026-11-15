"""Small-business records: expected receivables never become cash without confirmation."""
from datetime import datetime
from typing import Literal

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import finance
from .models import LedgerEntry
from .v2 import ConfirmIn, WRITE_LOCK, db_dep, fail, router, session
from .v2_models import PlanningRecord


class BusinessIn(BaseModel):
    kind: Literal["customer", "supplier", "receivable", "supplier_invoice"]
    title: str = Field(min_length=1, max_length=100)
    contact: str = Field(default="", max_length=200)
    amount_minor: int = Field(default=0, ge=0, le=100000000)
    expected_minor: int = Field(default=0, ge=0, le=100000000)
    due: str = ""
    notes: str = Field(default="", max_length=2000)


@router.get("/business")
def business(current=Depends(session), db=Depends(db_dep)):
    rows = list(db.scalars(select(PlanningRecord).where(PlanningRecord.user_id == current.buyer_id,
                PlanningRecord.kind.in_(["customer", "supplier", "receivable", "supplier_invoice"]))))
    totals = finance.summary(db, current.buyer_id, "business")
    return {"finance": totals, "expected_minor": sum(row.data["amount_minor"] for row in rows if row.kind == "receivable" and row.data.get("status") != "settled"),
            "records": [{"id": row.id, "kind": row.kind, "title": row.title, "data": row.data} for row in rows]}


@router.post("/business")
def add_business(body: BusinessIn, current=Depends(session), db=Depends(db_dep)):
    if body.due:
        try:
            datetime.fromisoformat(body.due)
        except ValueError:
            fail(422, "Enter a valid date")
    if body.kind in ("receivable", "supplier_invoice") and not body.amount_minor:
        fail(422, "Enter the invoice amount")
    data = body.model_dump() | {"status": "open", "provenance": "user_entered"}
    data["difference_minor"] = body.amount_minor - body.expected_minor if body.kind == "supplier_invoice" else 0
    row = PlanningRecord(user_id=current.buyer_id, kind=body.kind, title=body.title, purpose="business", data=data)
    db.add(row)
    db.flush()
    return {"id": row.id, "data": data}


@router.post("/business/{ident}/settle")
def settle_business(ident: str, body: ConfirmIn, current=Depends(session), db=Depends(db_dep)):
    if not body.confirmed:
        fail(422, "Confirm that the actual payment was received or paid")
    with WRITE_LOCK:
        row = db.get(PlanningRecord, ident)
        if not row or row.user_id != current.buyer_id or row.kind not in ("receivable", "supplier_invoice"):
            fail(404, "Business invoice not found")
        if row.data.get("status") == "settled":
            return {"ok": True, "replayed": True}
        amount = row.data["amount_minor"] * (-1 if row.kind == "receivable" else 1)
        db.add(LedgerEntry(user_id=current.buyer_id, amount=amount / 100, amount_minor=amount, currency="INR",
                          payee=row.title, description="Business payment recorded by user", purpose="business",
                          category="sales" if amount < 0 else "supplier", source="user_entered", settlement_key=f"business:{ident}"))
        row.data = row.data | {"status": "settled"}
        db.commit()
        return {"ok": True}
