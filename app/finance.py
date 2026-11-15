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
