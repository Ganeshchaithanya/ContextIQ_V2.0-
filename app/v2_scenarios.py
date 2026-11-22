"""Record-grounded cash questions. Parsing proposes a scenario; arithmetic stays deterministic."""
import calendar
import re
from datetime import date, timedelta
from sqlalchemy import select
from .v2_models import SellerBill, Customer


def is_cash_scenario(message):
    return bool(re.search(r"afford|cover|enough|cash|pay.*(?:rent|bill|emi)", message, re.I)
                and re.search(r"\bif\b|until|delay|late|doesn.t pay|does not pay|without", message, re.I))


def cash_scenario(db, owner, message):
    from .v2_seller import today, cash_position, open_invoices, bill_offsets, rupees
    from .v2_analysis import financial_analysis
    start = today()
    end = start + timedelta(days=7)
    if not re.search(r"this week|next (?:7|seven) days", message, re.I):
        return {"topic": "cash_scenario", "answer": "What period should I check? I can calculate recorded bill coverage over the next 7 days for a named client's delayed payment. A different period needs an explicit date range.", "destination": "#/seller/forecast", "evidence": []}
    assumptions = [f"‘This week’ is interpreted as the next 7 days, {start} through {end - timedelta(days=1)}, inclusive.",
                   "Only recorded bills and open invoices are included. No new work, income or unrecorded spending is assumed."]
    lower = message.lower()
    month_match = next(((i, name) for i, name in enumerate(calendar.month_name) if i and name.lower() in lower), None)
    deferred_until = None
    if month_match:
        month, name = month_match
        year_match = re.search(r"\b20\d{2}\b", message)
        year = int(year_match.group()) if year_match else start.year + (month < start.month)
        deferred_until = date(year, month, 1)
        assumptions.append(f"‘Until {name}’ means no receipt before {deferred_until}; the exact payment day is not confirmed.")
    customers = list(db.scalars(select(Customer).where(Customer.owner_id == owner)))
    matched = [c for c in customers if c.name.lower() in lower or
               (len(re.findall(r"\w+", c.name)) and re.findall(r"\w+", c.name.lower())[0] in lower)]
    if len(matched) != 1:
        return {"topic": "cash_scenario", "answer": "Which client should I delay, and until what date? I need one matching customer record to calculate this scenario without assuming a different client's invoice.",
                "destination": "#/seller/forecast", "evidence": [], "sources": []}
    client = matched[0]
    bills = []
    for bill in db.scalars(select(SellerBill).where(SellerBill.owner_id == owner)):
        if not bill.paid:
            for offset in bill_offsets(bill.due_date, bill.recurrence, start, 7):
                bills.append({"title": bill.name, "amount_minor": bill.amount_minor, "date": (start + timedelta(days=offset)).isoformat(), "destination": "#/seller/bills"})
    receipts, deferred, records = 0, 0, []
    for invoice in open_invoices(db, owner):
        customer = next(c for c in customers if c.id == invoice.customer_id)
        outstanding = invoice.total_minor - invoice.amount_paid_minor
        expected = max(invoice.due_date + timedelta(days=customer.usual_payment_delay_days), start)
        if customer.id == client.id:
            deferred += outstanding
            records.append({"label": f"{invoice.number} · {customer.name}", "value": rupees(outstanding), "detail": "Excluded from receipts in this seven-day stress scenario.", "destination": f"#/seller/invoices/{invoice.id}"})
        elif expected < end:
            receipts += outstanding
    opening = cash_position(db, owner, start)
    due = sum(b['amount_minor'] for b in bills)
    # Test bill dates, not only ending balance. Delayed-client receipts never fund the answer.
    conservative = opening - due
    ending = conservative + receipts
    verdict = "Yes" if conservative >= 0 else "Not from recorded cash alone"
    answer = (f"{verdict}. You have {rupees(opening)} recorded business cash and {rupees(due)} in recorded bills due over the next 7 days. "
              f"After paying those bills, cash alone leaves {rupees(conservative)}, without collecting anything from {client.name}. "
              f"I excluded their {rupees(deferred)} outstanding balance from this period. "
              + ("Bills included: " + "; ".join(f"{b['title']} {rupees(b['amount_minor'])} due {b['date']}" for b in bills) + ". " if bills else "No open recorded bills fall in this seven-day period. ")
              + f"Other expected receipts of {rupees(receipts)} would bring the period-end projection to {rupees(ending)}, but collection is uncertain. "
              "This tests bill coverage, not whether all remaining cash is safe to spend; reserves, purchase plans and unrecorded costs still matter. Payment remains your decision.")
    analysis = financial_analysis(db, owner, 'cash_scenario')
    analysis['scenario'] = {"client_id": client.id, "client_name": client.name, "start": start.isoformat(), "end_exclusive": end.isoformat(),
                            "deferred_until": deferred_until.isoformat() if deferred_until else None, "deferred_minor": deferred,
                            "opening_minor": opening, "bills_minor": due, "cash_after_bills_minor": conservative,
                            "other_receipts_minor": receipts, "ending_minor": ending, "cash_alone_covers_bills": conservative >= 0, "bills": bills}
    analysis['assumptions'] = assumptions + analysis['assumptions']
    analysis['calculations'].insert(0, {"label": "Requested client-delay scenario", "expression": f"{rupees(opening)} cash − {rupees(due)} bills = {rupees(conservative)} without {client.name}'s receipt"})
    analysis['records'] = records + [{"label": b['title'], "value": rupees(b['amount_minor']), "detail": f"Due {b['date']}", "destination": b['destination']} for b in bills] + analysis['records']
    analysis['next_step'] = f"Review the {client.name} invoices and confirm their payment date."
    analysis['limitations'].append("This seven-day stress case excludes this client's entire outstanding balance; it does not move invoice dates or alter records.")
    return {"topic": "cash_scenario", "answer": answer, "destination": "#/seller/forecast", "evidence": ["authorized_ledger", "seller_bills"] + [x['destination'] for x in records], "analysis": analysis}
