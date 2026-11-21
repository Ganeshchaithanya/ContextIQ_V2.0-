"""Reviewed guidance. Business amounts continue to come from the user's records."""
from datetime import date, timedelta
import re

from fastapi import Depends, Query

from .v2 import daily_date, fail, router, session

REVIEWED_ON = date(2026, 11, 21)
RBI_SAFETY = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=53185"
NPCI_HELP = "https://www.npci.org.in/uploads/UPI_Help_Brand_Guidelines_86c8c28922.pdf"

ARTICLES = (
    {
        "id": "receiving-upi", "title": "Receiving money safely with UPI", "category": "Payment safety",
        "summary": "A request to enter your PIN to receive money is a warning sign.",
        "paragraphs": [
            "Receiving money does not require entering a UPI PIN or scanning another person's QR. A request to do this can be a scam.",
            "Keep your PIN and OTP private. If a transaction looks suspicious, contact your bank using its official contact details.",
        ],
        "source_title": "RBI · Consumer Awareness — Cyber Threats and Frauds", "source_url": RBI_SAFETY,
        "source_type": "Official guidance", "action": "seller/invoices",
        "pattern": r"\b(?:pin|otp|scam|fraud|receive money safely)\b",
    },
    {
        "id": "pending-upi", "title": "A UPI payment is pending or disputed", "category": "Payment safety",
        "summary": "Use the original transaction's status and help options.",
        "paragraphs": [
            "Open the original transaction in your UPI app and check its status. UPI HELP provides transaction status and complaint options through participating payment apps.",
            "Use that transaction's help option to raise a concern. Keep its transaction reference so your bank or payment provider can identify it.",
        ],
        "source_title": "NPCI · UPI HELP guidelines", "source_url": NPCI_HELP,
        "source_type": "Official guidance", "action": "seller/invoices",
        "pattern": r"\bupi\b.*\b(?:pending|failed|dispute|complaint)\b|\b(?:pending|failed|dispute|complaint)\b.*\bupi\b",
    },
    {
        "id": "partial-receipts", "title": "Record a partial client payment", "category": "Invoices",
        "summary": "Record the amount received and keep the remaining invoice balance open.",
        "paragraphs": [
            "Open the sent invoice and choose Add a received payment. Enter the amount received, payment method, reference if available, and date. Confirm receipt in your account before saving.",
            "A partial payment reduces the amount still owed. The invoice stays open until the remaining balance is paid.",
            "The recorded receipt updates business cash, History, Budget and the cash forecast. An unpaid invoice stays in expected receipts.",
        ],
        "source_title": "ContextIQ · Invoice and ledger workflow", "source_url": "#/seller/invoices",
        "source_type": "Application workflow", "action": "seller/invoices",
        "pattern": r"\b(?:partial|part paid|record.*(?:receipt|payment)|add.*received)\b",
    },
    {
        "id": "cash-and-receivables", "title": "Cash available and money clients owe", "category": "Money",
        "summary": "Current cash and expected receipts answer different questions.",
        "paragraphs": [
            "Recorded business cash starts with the configured opening balance, adds confirmed receipts and subtracts recorded expenses and purchases.",
            "Receivables are the unpaid amounts on sent invoices. They enter recorded cash when you save a received payment.",
            "Spending Allocation sets aside open bills, reserves and planned savings. Check Available to spend before deciding on a purchase.",
        ],
        "source_title": "ContextIQ · Shared business ledger and allocation", "source_url": "#/budget/allocation",
        "source_type": "Application workflow", "action": "budget/allocation",
        "pattern": r"\b(?:cash.*receivable|receivable.*cash|available to spend|cash balance|opening balance)\b",
    },
    {
        "id": "cash-forecast", "title": "Understand the 30–90 day cash forecast", "category": "Planning",
        "summary": "See the assumptions behind the projection and test a late payment.",
        "paragraphs": [
            "The forecast starts with recorded business cash. It adds expected open invoice receipts and subtracts upcoming bills, including monthly occurrences.",
            "Expected receipt dates use invoice due dates and each client's usual delay. Already overdue receipts are assumed today. Collection can take longer.",
            "Use What if a client pays late to delay one client's expected receipts. The scenario changes the projection while preserving your saved records.",
        ],
        "source_title": "ContextIQ · Forecast calculations and scenario workflow", "source_url": "#/seller/forecast",
        "source_type": "Application workflow", "action": "seller/forecast",
        "pattern": r"\b(?:forecast|what if|cash projection|payment delay)\b",
    },
    {
        "id": "bill-payments", "title": "Record a bill payment or change its date", "category": "Bills",
        "summary": "Keep paid expenses and future commitments connected.",
        "paragraphs": [
            "Choose Record paid after paying a bill and confirm the action. This records an expense and releases the paid commitment.",
            "For a monthly bill, the next due date moves forward by a calendar month. Future occurrences remain in the forecast.",
            "Use Change date when you have agreed a new due date with the supplier. Saving a date changes the forecast without recording a payment.",
        ],
        "source_title": "ContextIQ · Bill payment and recurring bill workflow", "source_url": "#/seller/bills",
        "source_type": "Application workflow", "action": "seller/bills",
        "pattern": r"\b(?:bill|recurring|monthly)\b",
    },
    {
        "id": "invoice-follow-ups", "title": "Prepare an invoice and payment follow-up", "category": "Invoices",
        "summary": "Review a draft, share it, and follow up on the balance still owed.",
        "paragraphs": [
            "Create a client invoice with its line items and due date. Review the draft, copy its details to share with the client, then choose Mark as sent.",
            "The overdue dashboard shows the remaining amount and days past the due date. Drafts and cancelled invoices are excluded from money owed.",
            "Open an invoice to prepare a Friendly or Firm reminder. Edit the message before copying it or opening WhatsApp. You choose when to send it.",
        ],
        "source_title": "ContextIQ · Draft invoices, aging and reminder workflow", "source_url": "#/seller",
        "source_type": "Application workflow", "action": "seller",
        "pattern": r"\b(?:invoice|reminder|follow.up|aging|overdue)\b",
    },
)


def article_view(article):
    review_due = REVIEWED_ON + timedelta(days=90)
    return {key: value for key, value in article.items() if key != "pattern"} | {
        "reviewed_on": REVIEWED_ON.isoformat(), "review_due": review_due.isoformat(),
        "needs_review": date.fromisoformat(daily_date()) > review_due,
    }


def find_guide(message):
    if re.search(r"\b(?:how much|how many|who owes|focus on today)\b", message, re.I):
        return None
    instructional = re.search(r"\b(?:how|explain|guide|help|what is|what are|why|understand)\b", message, re.I)
    for article in ARTICLES:
        if (instructional or article["source_type"].startswith("Official")) and re.search(article["pattern"], message, re.I):
            return article_view(article)
    return None


@router.get("/knowledge")
def list_knowledge(q: str = Query("", max_length=200), current=Depends(session)):
    terms = re.findall(r"\w+", q.casefold())
    return [article_view(article) for article in ARTICLES if all(
        term in " ".join([article["title"], article["summary"], *article["paragraphs"]]).casefold() for term in terms)]


@router.get("/knowledge/{ident}")
def get_knowledge(ident: str, current=Depends(session)):
    article = next((item for item in ARTICLES if item["id"] == ident), None)
    if not article:
        fail(404, "Guide not found")
    return article_view(article)
