import os
from datetime import timedelta
from pathlib import Path
import tempfile
import uuid
from urllib.parse import parse_qs, urlparse

os.environ["PAYPAL_ENV"] = "mock"
os.environ["CONTEXTIQ_LEGACY_TEST_AUTH"] = "0"
os.environ.setdefault("CONTEXTIQ_MOCK_STORE", str(Path(tempfile.gettempdir()) / ('ciq-provider-' + uuid.uuid4().hex + '.json')))
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(tempfile.gettempdir()) / ('ciq-seller-' + uuid.uuid4().hex + '.db')).as_posix()}"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.v2_seller import today


def new_session(client, persona):
    """Start a fresh demo session on this client (a different cookie means a different owner)."""
    client.cookies.clear()
    response = client.post("/api/v2/session", json={"persona": persona})
    assert response.status_code == 200, response.text
    client.headers["x-csrf-token"] = response.json()["csrf"]
    return client


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield new_session(client, "salaried")  # salaried persona starts with no seller records


def make_customer(client, name="Test Client Pvt Ltd", delay=0, phone="+91 90000 22222"):
    response = client.post("/api/v2/seller/customers", json={"name": name, "phone": phone, "usual_payment_delay_days": delay})
    assert response.status_code == 200, response.text
    return response.json()


def make_invoice(client, customer_id, lines, due_offset=14, issue_offset=0):
    body = {"customer_id": customer_id, "lines": lines,
            "issue_date": (today() + timedelta(days=issue_offset)).isoformat(),
            "due_date": (today() + timedelta(days=due_offset)).isoformat()}
    response = client.post("/api/v2/seller/invoices", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def pay(client, invoice_id, amount_minor):
    return client.post(f"/api/v2/seller/invoices/{invoice_id}/payments", json={"amount_minor": amount_minor})


def test_create_customer_and_list(client):
    customer = make_customer(client, "Ananya Iyer", delay=7)
    assert customer["name"] == "Ananya Iyer" and customer["usual_payment_delay_days"] == 7
    names = [row["name"] for row in client.get("/api/v2/seller/customers").json()]
    assert "Ananya Iyer" in names


def test_two_line_invoice_total(client):
    customer = make_customer(client)
    invoice = make_invoice(client, customer["id"], [
        {"description": "Logo design", "quantity": 2, "unit_price_minor": 100000},
        {"description": "Business card print files", "quantity": 1, "unit_price_minor": 25050},
    ])
    assert invoice["total_minor"] == 225050
    assert invoice["balance_minor"] == 225050
    assert invoice["status"] == "draft"
    assert [line["amount_minor"] for line in invoice["lines"]] == [200000, 25050]
    assert invoice["number"].startswith("INV-")


def test_send_moves_draft_to_sent_once(client):
    customer = make_customer(client)
    invoice = make_invoice(client, customer["id"], [{"description": "Poster", "quantity": 1, "unit_price_minor": 50000}])
    sent = client.post(f"/api/v2/seller/invoices/{invoice['id']}/send")
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    assert client.post(f"/api/v2/seller/invoices/{invoice['id']}/send").status_code == 409


def test_partial_then_full_payment(client):
    customer = make_customer(client)
    invoice = make_invoice(client, customer["id"], [{"description": "Brand kit", "quantity": 1, "unit_price_minor": 225050}])
    client.post(f"/api/v2/seller/invoices/{invoice['id']}/send")
    partial = pay(client, invoice["id"], 100000).json()
    assert partial["status"] == "part_paid" and partial["balance_minor"] == 125050
    full = pay(client, invoice["id"], 125050).json()
    assert full["status"] == "paid" and full["balance_minor"] == 0
    assert len(full["payments"]) == 2


def test_overpayment_rejected(client):
    customer = make_customer(client)
    invoice = make_invoice(client, customer["id"], [{"description": "Flyer", "quantity": 1, "unit_price_minor": 50000}])
    client.post(f"/api/v2/seller/invoices/{invoice['id']}/send")
    response = pay(client, invoice["id"], 50001)
    assert response.status_code == 422
    current = client.get(f"/api/v2/seller/invoices/{invoice['id']}").json()
    assert current["paid_minor"] == 0 and current["status"] == "sent"


def test_payment_on_draft_rejected_and_cancel_rules(client):
    customer = make_customer(client)
    invoice = make_invoice(client, customer["id"], [{"description": "Flyer", "quantity": 1, "unit_price_minor": 50000}])
    assert pay(client, invoice["id"], 1000).status_code == 409
    assert client.post(f"/api/v2/seller/invoices/{invoice['id']}/cancel").json()["status"] == "cancelled"


def test_other_owner_gets_404(client):
    customer = make_customer(client, "Owner A Client")
    invoice = make_invoice(client, customer["id"], [{"description": "Flyer", "quantity": 1, "unit_price_minor": 50000}])
    client.post(f"/api/v2/seller/invoices/{invoice['id']}/send")
    new_session(client, "freelancer")  # a different owner in the same client
    assert client.get(f"/api/v2/seller/invoices/{invoice['id']}").status_code == 404
    assert client.post(f"/api/v2/seller/invoices/{invoice['id']}/send").status_code == 404
    assert client.post(f"/api/v2/seller/invoices/{invoice['id']}/payments", json={"amount_minor": 100}).status_code == 404
    assert client.get(f"/api/v2/seller/invoices/{invoice['id']}/reminder").status_code == 404
    assert client.post(f"/api/v2/seller/invoices", json={"customer_id": customer["id"], "lines": [{"description": "x", "unit_price_minor": 100}]}).status_code == 404
    assert "Owner A Client" not in [row["name"] for row in client.get("/api/v2/seller/customers").json()]


def test_aging_buckets_sorted_by_days_overdue(client):
    customer = make_customer(client)
    line = [{"description": "Work", "quantity": 1, "unit_price_minor": 10000}]
    dues = {"fresh": -3, "middle": -20, "old": -40, "not_due": 5}
    numbers = {}
    for key, offset in dues.items():
        invoice = make_invoice(client, customer["id"], line, due_offset=offset, issue_offset=offset - 10)
        client.post(f"/api/v2/seller/invoices/{invoice['id']}/send")
        numbers[key] = invoice["number"]
    aging = client.get("/api/v2/seller/receivables/aging").json()
    assert aging["buckets"]["0-7"]["count"] == 1
    assert aging["buckets"]["8-30"]["count"] == 1
    assert aging["buckets"]["31+"]["count"] == 1
    assert aging["total_outstanding_minor"] == 40000
    order = [row["number"] for row in aging["invoices"]]
    assert order[0] == numbers["old"] and order[1] == numbers["middle"]
    days = [row["days_overdue"] for row in aging["invoices"]]
    assert days == sorted(days, reverse=True)


def test_forecast_first_negative_day(client):
    assert client.put("/api/v2/seller/settings", json={"upi_vpa": "test.pay@okaxis", "payee_name": "Test Studio", "opening_balance_minor": 0}).status_code == 200
    bill = client.post("/api/v2/seller/bills", json={"name": "Rent", "amount_minor": 50000,
                                                     "due_date": (today() + timedelta(days=4)).isoformat()})
    assert bill.status_code == 200
    forecast = client.get("/api/v2/seller/forecast?horizon_days=60").json()
    assert forecast["first_negative_date"] == (today() + timedelta(days=4)).isoformat()
    assert len(forecast["days"]) == 60
    assert client.get("/api/v2/seller/forecast?horizon_days=30").status_code == 200


def test_receipt_retry_and_bill_payment_keep_forecast_cash_consistent(client):
    customer = make_customer(client)
    inv = make_invoice(client, customer["id"], [{"description": "Design", "unit_price_minor": 100000}])
    client.post(f"/api/v2/seller/invoices/{inv['id']}/send")
    payload = {"amount_minor": 40000, "request_id": "receipt-retry-001"}
    for _ in range(2):
        result = client.post(f"/api/v2/seller/invoices/{inv['id']}/payments", json=payload)
        assert result.status_code == 200 and result.json()["paid_minor"] == 40000
    forecast = client.get("/api/v2/seller/forecast?horizon_days=30").json()
    assert forecast["opening_minor"] == 40000 and forecast["receipts_minor"] == 60000
    bill = client.post("/api/v2/seller/bills", json={
        "name": "Hosting", "amount_minor": 10000, "due_date": today().isoformat(),
    }).json()
    body = {"confirmed": True, "request_id": "bill-retry-001"}
    for _ in range(2):
        assert client.post(f"/api/v2/seller/bills/{bill['id']}/record-payment", json=body).status_code == 200
    after = client.get("/api/v2/seller/forecast?horizon_days=30").json()
    assert after["opening_minor"] == 30000 and after["bills_minor"] == 0
    assert client.post(f"/api/v2/seller/invoices/{inv['id']}/payments", json=payload | {"amount_minor": 20000}).status_code == 409


def test_studio_answers_and_recurring_bill_advance(client):
    new_session(client, "freelancer")
    answer = client.post("/api/v2/ask", json={"message": "Who owes me money?"}).json()
    assert answer["topic"] == "studio" and answer["destination"] == "#/seller"
    cash = client.post("/api/v2/ask", json={"message": "What happens if clients pay late?"}).json()
    assert cash["destination"] == "#/seller/forecast" and "15 days" in cash["answer"]
    bill = client.get("/api/v2/seller/bills").json()[0]
    before = client.get("/api/v2/seller/forecast").json()["opening_minor"]
    result = client.post(f"/api/v2/seller/bills/{bill['id']}/record-payment",
                         json={"confirmed": True, "request_id": "monthly-bill-0001"}).json()
    assert result["due_date"] > bill["due_date"] and not result["paid"]
    assert client.get("/api/v2/seller/forecast").json()["opening_minor"] == before - bill["amount_minor"]


def test_what_if_later_payment_never_raises_minimum_balance(client):
    client.put("/api/v2/seller/settings", json={"upi_vpa": "test.pay@okaxis", "payee_name": "Test Studio", "opening_balance_minor": 20000})
    customer = make_customer(client, delay=0)
    invoice = make_invoice(client, customer["id"], [{"description": "Ad film", "quantity": 1, "unit_price_minor": 100000}], due_offset=5)
    client.post(f"/api/v2/seller/invoices/{invoice['id']}/send")
    client.post("/api/v2/seller/bills", json={"name": "Rent", "amount_minor": 30000, "due_date": (today() + timedelta(days=10)).isoformat()})
    on_time = client.get("/api/v2/seller/forecast/what-if?delay_days=0&horizon_days=60").json()
    late = client.get("/api/v2/seller/forecast/what-if?delay_days=20&horizon_days=60").json()
    assert late["scenario"]["min_balance_minor"] <= late["baseline"]["min_balance_minor"]
    assert late["change_in_min_balance_minor"] <= 0
    assert late["baseline"]["min_balance_minor"] == on_time["baseline"]["min_balance_minor"]
    assert late["scenario"]["min_balance_minor"] < late["baseline"]["min_balance_minor"]


def test_delay_scenario_postpones_already_overdue_receipts(client):
    customer = make_customer(client)
    inv = make_invoice(client, customer["id"], [{"description": "Completed work", "unit_price_minor": 100000}],
                       due_offset=-30, issue_offset=-40)
    client.post(f"/api/v2/seller/invoices/{inv['id']}/send")
    client.post("/api/v2/seller/bills", json={
        "name": "Rent", "amount_minor": 50000, "due_date": (today() + timedelta(days=3)).isoformat(),
    })
    result = client.get(f"/api/v2/seller/forecast/what-if?delay_days=15&customer_id={customer['id']}").json()
    assert result["baseline"]["first_negative_date"] is None
    assert result["scenario"]["first_negative_date"] == (today() + timedelta(days=3)).isoformat()


def test_reminder_contains_upi_link_with_balance(client):
    client.put("/api/v2/seller/settings", json={"upi_vpa": "meera.designs@okaxis", "payee_name": "Meera Design Studio", "opening_balance_minor": 0})
    customer = make_customer(client, "Ravi Kumar")
    invoice = make_invoice(client, customer["id"], [{"description": "Logo", "quantity": 1, "unit_price_minor": 225050}])
    client.post(f"/api/v2/seller/invoices/{invoice['id']}/send")
    pay(client, invoice["id"], 25050)  # balance now 2,000.00
    reminder = client.get(f"/api/v2/seller/invoices/{invoice['id']}/reminder?tone=firm").json()
    link = reminder["upi_link"]
    assert link.startswith("upi://pay?")
    query = parse_qs(urlparse(link).query)
    assert query["pa"] == ["meera.designs@okaxis"]
    assert query["am"] == ["2000.00"]
    assert query["cu"] == ["INR"]
    assert query["tn"] == [f"Invoice {invoice['number']}"]
    assert reminder["amount_minor"] == 200000
    assert link in reminder["text"] and "₹2,000.00" in reminder["text"]


def test_freelancer_demo_seed(client):
    seeded = new_session(client, "freelancer")
    customers = seeded.get("/api/v2/seller/customers").json()
    invoices = seeded.get("/api/v2/seller/invoices").json()
    assert len(customers) == 6
    assert len(invoices) == 12
    assert {row["status"] for row in invoices} == {"draft", "sent", "part_paid", "paid"}
    assert any(row["overdue"] for row in invoices)
    assert len(seeded.get("/api/v2/seller/bills").json()) == 5
    assert seeded.get("/api/v2/seller/settings").json()["opening_balance_minor"] == 9000000


def test_customer_specific_what_if_delay_and_404(client):
    client.put("/api/v2/seller/settings", json={"upi_vpa": "test.pay@okaxis", "payee_name": "Test Studio", "opening_balance_minor": 20000})
    late_payer = make_customer(client, "Late Payer Pvt Ltd", delay=0)
    prompt_payer = make_customer(client, "Prompt Payer LLP", delay=0)
    for customer, amount in ((late_payer, 100000), (prompt_payer, 50000)):
        invoice = make_invoice(client, customer["id"], [{"description": "Retainer", "quantity": 1, "unit_price_minor": amount}], due_offset=5)
        client.post(f"/api/v2/seller/invoices/{invoice['id']}/send")
    client.post("/api/v2/seller/bills", json={"name": "Rent", "amount_minor": 30000, "due_date": (today() + timedelta(days=2)).isoformat()})
    baseline = client.get("/api/v2/seller/forecast/what-if?delay_days=0&horizon_days=60").json()
    scoped = client.get(f"/api/v2/seller/forecast/what-if?delay_days=20&horizon_days=60&customer_id={late_payer['id']}")
    assert scoped.status_code == 200, scoped.text
    scoped = scoped.json()
    assert scoped["customer_name"] == "Late Payer Pvt Ltd"
    assert scoped["scenario"]["min_balance_minor"] <= scoped["baseline"]["min_balance_minor"]
    assert scoped["baseline"]["min_balance_minor"] == baseline["baseline"]["min_balance_minor"]
    assert baseline["customer_name"] is None
    assert client.get("/api/v2/seller/forecast/what-if?customer_id=no-such-customer").status_code == 404
    new_session(client, "freelancer")  # another owner must not see this customer
    assert client.get(f"/api/v2/seller/forecast/what-if?delay_days=20&customer_id={late_payer['id']}").status_code == 404
