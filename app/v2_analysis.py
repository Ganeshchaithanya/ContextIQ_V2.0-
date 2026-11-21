"""Reproducible explanations built from the current user's authorized records."""
from types import SimpleNamespace

from sqlalchemy import select

from . import finance
from .v2_models import InvoiceSnapshot, PaymentIncident, Personalization, PlanningRecord, PurchaseItem


def money(value):
    return f"₹{value / 100:,.2f}"


def financial_analysis(db, owner, topic):
    from .v2 import bill_rows, now, purchase_budget, workspace

    prefs = db.get(Personalization, owner).data
    scope = workspace(prefs)
    cash = finance.summary(db, owner, scope)
    bills = bill_rows(db, owner)
    plans = list(db.scalars(select(PlanningRecord).where(
        PlanningRecord.user_id == owner, PlanningRecord.kind.in_(("goal", "allocation", "supplier_invoice")))))
    allocation = finance.spending_allocation(cash["balance_minor"], scope, bills, plans,
                                            monthly_surplus=cash["income_minor"] - cash["expense_minor"])
    report = {
        "as_of": now().isoformat(), "scope": scope, "basis": "Recorded demo data and reproducible calculations",
        "metrics": {**{key: cash[key] for key in ("opening_minor", "income_minor", "expense_minor", "balance_minor")},
                    **{key: allocation[key] for key in ("committed_minor", "reserved_minor", "savings_minor", "flexible_minor")}},
        "explanation": [], "calculations": [], "records": [],
        "assumptions": ["Unpaid invoices are expected receipts, not cash already received.",
                        "Savings allocations reserve spending capacity; they do not transfer money."],
        "limitations": ["This is a snapshot of fictional demo records, not a live bank balance.",
                        "Unrecorded income, expenses and obligations are excluded. Re-ask after changing records for a fresh analysis."],
    }
    def record(label, value, detail, destination):
        report["records"].append({"label": label, "value": value, "detail": detail, "destination": destination})

    report["calculations"] = [
        {"label": "Recorded cash · last 30 days", "expression":
         f"{money(cash['opening_minor'])} opening + {money(cash['income_minor'])} money in − {money(cash['expense_minor'])} money out = {money(cash['balance_minor'])}"},
        {"label": "Available to spend", "expression":
         f"{money(cash['balance_minor'])} cash − {money(allocation['committed_minor'])} open commitments − {money(allocation['reserved_minor'])} manual reserves − {money(allocation['savings_minor'])} savings allocation = {money(allocation['flexible_minor'])}"},
    ]
    record("Cash ledger", money(cash["balance_minor"]),
           f"INR {scope} workspace. Period {cash['period_start']} to {cash['period_end']}. Opening cash includes earlier entries.", "#/activity/history")
    record("Spending allocation", money(allocation["flexible_minor"]),
           "Open commitments, manual reserves and planned savings deducted from recorded cash.", "#/budget/allocation")
    for bill in allocation["commitments"]:
        record(bill["title"], money(bill["amount_minor"]), f"Open commitment · due {bill.get('due') or 'date not recorded'}", bill["destination"])
    for reserve in allocation["reserves"]:
        record(reserve["title"], money(reserve["amount_minor"]), "Manual reserve", "#/budget/allocation")
    for saving in allocation["savings"]:
        record(saving["title"], money(saving["amount_minor"]), "Current planned savings allocation", saving["destination"])
    free = allocation["flexible_minor"]
    report["explanation"].append({"title": "Spending capacity", "text":
        (f"Recorded cash does not cover all open commitments and reserves: the shortfall is {money(-free)}. Review commitments before approving another purchase."
         if free < 0 else f"After recorded commitments and reserves, {money(free)} remains available to spend. This excludes unrecorded costs.")})

    if prefs.get("persona") == "freelancer":
        from .v2_seller import build_forecast, receivables_aging
        aging = receivables_aging(SimpleNamespace(buyer_id=owner), db)
        forecast = build_forecast(db, owner, 60)
        delayed = build_forecast(db, owner, 60, 15)
        overdue = [row for row in aging["invoices"] if row["overdue"]]
        due = sum(row["balance_minor"] for row in overdue)
        report["metrics"].update({"receivable_minor": aging["total_outstanding_minor"], "overdue_minor": due,
                                  "open_invoice_count": len(aging["invoices"]), "overdue_invoice_count": len(overdue)})
        report["forecast"] = {key: forecast[key] for key in ("as_of", "opening_minor", "receipts_minor", "bills_minor",
                               "ending_balance_minor", "min_balance_minor", "min_balance_date", "first_negative_date", "horizon_days")}
        report["scenario"] = {"delay_days": 15, "min_balance_minor": delayed["min_balance_minor"],
                              "min_balance_date": delayed["min_balance_date"], "first_negative_date": delayed["first_negative_date"]}
        report["calculations"].append({"label": "60-day business cash forecast", "expression":
            f"{money(forecast['opening_minor'])} business cash + {money(forecast['receipts_minor'])} expected receipts − {money(forecast['bills_minor'])} scheduled business bills = {money(forecast['ending_balance_minor'])} ending cash"})
        report["calculations"].append({"label": "Unpaid client balances", "expression":
            f"Sum of total minus recorded payments on {len(aging['invoices'])} sent or partly paid invoices = {money(aging['total_outstanding_minor'])}; overdue portion = {money(due)}"})
        for row in aging["invoices"]:
            record(f"{row['number']} · {row['customer']['name']}", money(row["balance_minor"]),
                   f"Total {money(row['total_minor'])} − received {money(row['paid_minor'])}; due {row['due_date']}; {row['days_overdue']} days overdue.",
                   f"#/seller/invoices/{row['id']}")
        record("60-day cash forecast", money(forecast["min_balance_minor"]),
               f"Lowest projected day-end balance on {forecast['min_balance_date']}. Full daily series and business bills are available here.", "#/seller/forecast")
        report["assumptions"].extend([
            "The forecast counts sent and partly paid invoices; drafts and cancelled invoices are excluded.",
            "Expected receipt date = due date + the client's recorded usual payment delay, floored at today.",
            "The stress scenario adds 15 days to every open invoice's expected receipt date; it is a scenario, not a prediction.",
            "The forecast includes recorded business bills and their recurrence. Personal obligations, new sales, unrecorded costs and savings reservations are not forecast cash outflows.",
        ])
        report["explanation"].append({"title": "Collection risk", "text":
            f"{money(due)} of {money(aging['total_outstanding_minor'])} owed by clients is overdue. These balances only become spendable cash after you record receiving payment."})
        risk = (f"The baseline first drops below zero on {forecast['first_negative_date']}."
                if forecast["first_negative_date"] else "The baseline stays at or above zero across the recorded 60-day schedule.")
        report["explanation"].append({"title": "Cash-flow outlook", "text":
            f"{risk} Its lowest balance is {money(forecast['min_balance_minor'])} on {forecast['min_balance_date']}. With all receipts 15 days later, the lowest balance is {money(delayed['min_balance_minor'])}. Neither result guarantees future cash."})
        report["next_step"] = (f"Review {overdue[0]['number']} for {overdue[0]['customer']['name']} and confirm when the outstanding {money(overdue[0]['balance_minor'])} can be paid. Review the reminder before sending it."
                               if overdue else "Review upcoming bills and test client delays before committing to new spending.")
    else:
        report["next_step"] = "Review the linked commitments and savings allocations before deciding on additional spending."

    if topic in ("afford", "cart"):
        invoice = db.scalar(select(InvoiceSnapshot).where(InvoiceSnapshot.buyer_id == owner, InvoiceSnapshot.status == "open").order_by(InvoiceSnapshot.created_at.desc()))
        if invoice:
            projected = purchase_budget(db, invoice)
            report["calculations"].append({"label": "Purchase impact · latest open invoice", "expression":
                f"{money(projected['funds_minor'])} {projected['scope']} cash − {money(invoice.total_minor)} invoice = {money(projected['projected_funds_minor'])} cash after purchase; available to spend after recalculated savings = {money(projected['remaining_minor'])}"})
            record(f"Purchase invoice {invoice.id[:8]}", money(invoice.total_minor), "Latest open invoice, not an assumed item or price. Payment needs your approval.", f"#/invoice/{invoice.id}")
        else:
            report["limitations"].append("No open purchase invoice was found. Affordability cannot be concluded without an exact item and price.")
    if topic in ("payment", "empty_payment"):
        incident = db.scalar(select(PaymentIncident).where(PaymentIncident.user_id == owner).order_by(PaymentIncident.created_at.desc()))
        if incident:
            record("Original payment issue", incident.status.replace("_", " "),
                   f"Recorded recovery status for case {incident.case_id}. Open the issue to inspect its verification steps.", f"#/activity/issues/{incident.id}")
        else:
            report["limitations"].append("No payment incident is recorded for this workspace.")
    if topic in ("purchase", "empty_purchase"):
        item = db.scalar(select(PurchaseItem).where(PurchaseItem.buyer_id == owner))
        if item:
            record(item.name, item.state.replace("_", " "), "Recorded purchase state. Delivery and policy evidence are available in its purchase page.", f"#/purchases/item/{item.id}")
        else:
            report["limitations"].append("No completed purchase is recorded for this workspace.")
    if topic in ("goal", "emi", "empty_emi"):
        kind = "emi" if topic in ("emi", "empty_emi") else "goal"
        plan = db.scalar(select(PlanningRecord).where(PlanningRecord.user_id == owner, PlanningRecord.kind == kind))
        if plan and kind == "emi":
            unpaid = [row for row in plan.data["schedule"] if not row["paid"]]
            record(plan.title, money(sum(row["amount_minor"] for row in unpaid)), f"Sum of {len(unpaid)} unpaid scheduled installments; this is scheduled debt, not a new payment.", "#/budget/emi")
        elif plan:
            record(plan.title, money(plan.data["saved_minor"]), f"Recorded saving toward a target of {money(plan.data['target_minor'])}.", f"#/budget/goals/{plan.id}")
    return report


def overview_answer(report):
    m = report["metrics"]
    parts = [f"Your recorded cash is {money(m['balance_minor'])}. After {money(m['committed_minor'])} in open commitments, {money(m['reserved_minor'])} in manual reserves and {money(m['savings_minor'])} in planned savings, your available-to-spend balance is {money(m['flexible_minor'])}."]
    if "receivable_minor" in m:
        parts.append(f"Clients owe {money(m['receivable_minor'])} across {m['open_invoice_count']} open invoices, including {money(m['overdue_minor'])} overdue. This is money to collect, not cash you can spend yet.")
    parts.extend(section["text"] for section in report["explanation"] if section["title"] == "Cash-flow outlook")
    parts.append("Suggested next step: " + report["next_step"])
    return "\n\n".join(parts)
