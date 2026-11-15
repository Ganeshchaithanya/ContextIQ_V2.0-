"""Currency-aware accounting over the existing authoritative ledger."""
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
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


def purchase_gap(data, bought_quantity=0, bought_minor=0):
    target = max(0, data["purchase_quantity"] - bought_quantity) * data["price_minor"]
    saved = max(0, data["saved_minor"] - bought_minor)
    return max(0, target - saved)


def add_months(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def goal_contribution(data, today, bought_quantity=0, bought_minor=0):
    if data.get("status") in ("paused", "purchased"):
        return 0
    if not data.get("linked_watch_id"):
        return min(data.get("contribution_minor", 0), max(0, data["target_minor"] - data["saved_minor"]))
    remaining = purchase_gap(data, bought_quantity, bought_minor)
    override = data.get("monthly_override_minor")
    if override is not None:
        return min(override, remaining)
    target_date = date.fromisoformat(data["target_date"])
    months = (target_date.year - today.year) * 12 + target_date.month - today.month
    periods = max(1, months + (target_date > add_months(today, months)))
    return (remaining + periods - 1) // periods


def spending_allocation(balance, purpose, bills, plans, purchase=None, purchase_purpose=None, monthly_surplus=0):
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
    reserves = [{"id": row.id, "title": row.title, "amount_minor": row.data.get("amount_minor", 0)}
                for row in scoped if row.kind == "allocation"]
    reserved = sum(row["amount_minor"] for row in reserves)
    remaining = balance - committed - reserved
    goals = sorted((row for row in scoped if row.kind == "goal"),
                   key=lambda row: (row.data.get("target_date") or "9999-12-31", row.id))
    savings = []
    today = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date()
    monthly_headroom = max(0, monthly_surplus)
    for row in goals:
        if row.data.get("status") in ("paused", "purchased"):
            continue
        bought = (purchase or {}).get(row.data.get("product_id"), (0, 0)) if row.purpose == purchase_purpose else (0, 0)
        estimate = None
        if row.data.get("date_mode") == "automatic":
            gap = purchase_gap(row.data, *bought)
            if gap <= 0:
                continue
            override = row.data.get("monthly_override_minor")
            default_pace = monthly_headroom if monthly_surplus > 0 else (gap if remaining >= gap else 0)
            pace = override if override is not None else default_pace
            requested = min(gap, pace, max(remaining, 0))
            if requested:
                periods = (gap + requested - 1) // requested
                if periods <= (date.max.year - today.year) * 12 + 12 - today.month:
                    estimate = add_months(today, periods).isoformat()
        else:
            requested = goal_contribution(row.data, today, *bought)
            if requested <= 0:
                continue
        contribution = min(requested, max(remaining, 0))
        savings.append({"id": row.id, "title": row.title, "requested_minor": requested, "amount_minor": contribution,
                        "estimated_date": estimate,
                        "destination": f"#/budget/goals/{row.id}"})
        remaining -= contribution
        monthly_headroom = max(0, monthly_headroom - contribution)
    return {"commitments": commitments, "reserves": reserves, "savings": savings,
            "committed_minor": committed, "reserved_minor": reserved,
            "savings_minor": sum(row["amount_minor"] for row in savings), "flexible_minor": remaining}
