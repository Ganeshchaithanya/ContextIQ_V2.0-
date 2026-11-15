"""Currency-aware accounting over the existing authoritative ledger."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import event, select

from .models import Case, LedgerEntry


def minor(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@event.listens_for(LedgerEntry, "before_insert")
def normalize_ledger(mapper, connection, entry):
    if entry.amount_minor is None:
        entry.amount_minor = minor(entry.amount)
    if entry.case_id:
        currency = connection.execute(select(Case.currency).where(Case.id == entry.case_id)).scalar()
        entry.currency = currency or entry.currency or "USD"
    entry.currency = entry.currency or "USD"


def entries(db, user_id, purpose=None, currency="INR"):
    query = select(LedgerEntry).where(LedgerEntry.user_id == user_id, LedgerEntry.currency == currency)
    if purpose in ("personal", "business"):
        query = query.where(LedgerEntry.purpose == purpose)
    return list(db.scalars(query.order_by(LedgerEntry.occurred_at, LedgerEntry.id)))


def summary(db, user_id, purpose=None, days=30, currency="INR"):
    rows = entries(db, user_id, purpose, currency)
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    opening = -sum(row.amount_minor for row in rows if row.occurred_at.date() < start)
    period = [row for row in rows if start <= row.occurred_at.date() <= today]
    income = -sum(row.amount_minor for row in period if row.amount_minor < 0)
    expenses = sum(row.amount_minor for row in period if row.amount_minor > 0)
    balance = opening
    chart = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        balance -= sum(row.amount_minor for row in period if row.occurred_at.date() == day)
        chart.append({"date": day.isoformat(), "balance_minor": balance})
    categories = {}
    for row in period:
        if row.amount_minor > 0:
            categories[row.category] = categories.get(row.category, 0) + row.amount_minor
    return {"currency": currency, "opening_minor": opening, "income_minor": income,
            "expense_minor": expenses, "balance_minor": balance, "chart": chart,
            "categories": categories, "period_start": start.isoformat(), "period_end": today.isoformat()}


def spending_allocation(balance, purpose, bills, plans):
    """Plan against recorded cash and obligations without writing ledger entries."""
    scoped = [row for row in plans if purpose == "all" or row.purpose == purpose]
    commitments = [
        {**bill, "destination": f"#/budget/bills/{bill['id']}"}
        for bill in bills
        if bill["status"] == "open" and (purpose == "all" or bill["purpose"] == purpose)
    ]
    commitments += [
        {"title": row.title, "amount_minor": row.data["amount_minor"], "due": row.data.get("due"),
         "destination": f"#/budget/business/{row.id}"}
        for row in scoped if row.kind == "supplier_invoice" and row.data.get("status") == "open"
    ]
    commitments.sort(key=lambda row: row["due"] or "9999-12-31")
    committed = sum(row["amount_minor"] for row in commitments)
    reserves = [{"title": row.title, "amount_minor": row.data.get("amount_minor", 0)}
                for row in scoped if row.kind == "allocation"]
    reserved = sum(row["amount_minor"] for row in reserves)
    remaining = balance - committed - reserved
    goals = sorted((row for row in scoped if row.kind == "goal"),
                   key=lambda row: (row.data.get("target_date") or "9999-12-31", row.id))
    savings = []
    for row in goals:
        target = row.data["target_minor"]
        requested = min(row.data.get("contribution_minor", 0), max(0, target - row.data["saved_minor"]))
        if requested <= 0:
            continue
        contribution = min(requested, max(remaining, 0))
        savings.append({"title": row.title, "requested_minor": requested, "amount_minor": contribution,
                        "destination": f"#/budget/goals/{row.id}"})
        remaining -= contribution
    return {"commitments": commitments, "reserves": reserves, "savings": savings,
            "committed_minor": committed, "reserved_minor": reserved,
            "savings_minor": sum(row["amount_minor"] for row in savings), "flexible_minor": remaining}
