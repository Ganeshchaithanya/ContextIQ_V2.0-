import os
from pathlib import Path
import tempfile
import uuid

os.environ["PAYPAL_ENV"] = "mock"
os.environ["CONTEXTIQ_LEGACY_TEST_AUTH"] = "0"
os.environ.setdefault("CONTEXTIQ_MOCK_STORE", str(Path(tempfile.gettempdir()) / ('ciq-provider-' + uuid.uuid4().hex + '.json')))
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(tempfile.gettempdir()) / ('ciq-v2-' + uuid.uuid4().hex + '.db')).as_posix()}"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.db import SessionLocal
from app.models import LedgerEntry
from app.v2_models import InvoiceSnapshot
from app.v2 import workspace


@pytest.fixture
def client():
    with TestClient(app) as client:
        response = client.post("/api/v2/session", json={"persona": "student"})
        assert response.status_code == 200, response.text
        client.headers["x-csrf-token"] = response.json()["csrf"]
        yield client


def invoice(client, product="headphones", quantity=1):
    response = client.post("/api/v2/invoices", json={"items": [{"product_id": product, "quantity": quantity}]})
    assert response.status_code == 200, response.text
    return response.json()


def pay(client, row, interrupted=False):
    payload = {"fingerprint": row["fingerprint"], "version": row["version"], "authorized": True, "simulate_interruption": interrupted}
    result = client.post(f"/api/v2/invoices/{row['id']}/authorize", json=payload)
    assert result.status_code == 200, result.text
    data = result.json()
    if data.get("gateway") == "step_up":
        payload["step_up_code"] = data["step_up_code_demo"]
        result = client.post(f"/api/v2/invoices/{row['id']}/authorize", json=payload)
        assert result.status_code == 200, result.text
        data = result.json()
    assert data["ok"], data
    return data


def test_partial_refunds_repeated_equal_amounts_and_delivery_window(client):
    row = invoice(client, "cable", 2)
    result = pay(client, row)
    ident = result["item_ids"][0]
    original = client.post(f"/api/v2/purchases/{ident}/action", json={"action": "deliver", "quantity": 1, "days_ago": 2}).json()
    updated = client.post(f"/api/v2/purchases/{ident}/action", json={"action": "deliver", "quantity": 2, "days_ago": 0}).json()
    assert original["delivered_at"] == updated["delivered_at"]
    assert updated["replacement_days"] == 5
    assert client.post(f"/api/v2/purchases/{ident}/action", json={"action": "ship"}).status_code == 409
    for request_id in ("refund-first", "refund-second"):
        body = {"quantity": 1, "confirmed": True, "request_id": request_id}
        refund = client.post(f"/api/v2/purchases/{ident}/refund", json=body)
        assert refund.status_code == 200, refund.text
        if refund.json().get("gateway") == "step_up":
            body["step_up_code"] = refund.json()["step_up_code_demo"]
            refund = client.post(f"/api/v2/purchases/{ident}/refund", json=body)
        assert refund.json()["ok"], refund.text
        assert client.post(f"/api/v2/purchases/{ident}/refund", json=body).json()["replayed"]
    item = client.get(f"/api/v2/purchases/{ident}").json()
    assert item["refunded_quantity"] == 2 and item["state"] == "refunded"
    assert client.get("/api/v2/dashboard").json()["finance"]["balance_minor"] == 600000
    merchant = client.get("/api/v2/merchant").json()
    assert merchant["sales_minor"] == merchant["refunds_minor"] == 59800
    assert "balance_minor" not in str(merchant)


def test_emi_minor_unit_rounding_and_business_scope(client):
    plan = client.post("/api/v2/plans", json={"kind": "emi", "title": "Inventory", "principal_minor": 10000,
                                            "months": 3, "annual_rate": 0, "purpose": "business"}).json()
    assert plan["data"]["total_minor"] == 10000
    assert sum(row["amount_minor"] for row in plan["data"]["schedule"]) == 10000
    bill_id = plan["data"]["schedule"][0]["bill_id"]
    bill = next(row for row in client.get("/api/v2/bills").json() if row["id"] == bill_id)
    assert bill["purpose"] == "business"
    assert client.post(f"/api/v2/bills/{bill_id}/record-payment", json={"confirmed": True}).status_code == 200
    assert next(row for row in client.get("/api/v2/history").json() if row["description"] == "Payment recorded by user")["purpose"] == "business"


def test_concurrent_authorization_settles_once(client):
    from concurrent.futures import ThreadPoolExecutor
    row = invoice(client, "cable")
    payload = {"fingerprint": row["fingerprint"], "version": row["version"], "authorized": True}
    initial = client.post(f"/api/v2/invoices/{row['id']}/authorize", json=payload).json()
    if initial.get("gateway") == "step_up":
        payload["step_up_code"] = initial["step_up_code_demo"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(f"/api/v2/invoices/{row['id']}/authorize", json=payload), range(2)))
    assert all(result.status_code == 200 and result.json()["ok"] for result in results)
    history = client.get("/api/v2/history").json()
    assert len([entry for entry in history if entry["case_id"] == results[0].json()["case_id"]]) == 1


def test_session_isolation_csrf_and_reset(client):
    own = invoice(client)
    before = client.get("/api/v2/profile").json()
    assert client.get("/api/v2/profile", headers={"X-User-Id": "brightmart"}).json() == before
    with TestClient(app) as other:
        assert other.get("/api/v2/dashboard").status_code == 401
        session = other.post("/api/v2/session", json={}).json()
        other.headers["x-csrf-token"] = session["csrf"]
        assert other.get(f"/api/v2/invoices/{own['id']}").status_code == 404
        assert other.post("/api/v2/scan", json={"token": own["qr_token"]}).status_code == 404
        assert other.post("/api/v2/reset", json={"confirmed": True}).status_code == 200
    assert client.get(f"/api/v2/invoices/{own['id']}").status_code == 200
    assert client.post("/api/v2/reset", json={"confirmed": True}, headers={"x-csrf-token": "wrong"}).status_code == 403
    assert client.post("/api/v2/reset", json={"confirmed": True}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/reset").status_code == 403
    assert client.get("/api/users").status_code == 403


def test_business_receivable_only_counts_after_confirmed_record(client):
    before = client.get("/api/v2/business").json()["finance"]["balance_minor"]
    row = client.post("/api/v2/business", json={"title": "Test customer invoice", "kind": "receivable", "amount_minor": 200000}).json()
    expected = client.get("/api/v2/business").json()
    assert expected["expected_minor"] == 200000 and expected["finance"]["balance_minor"] == before
    url = f"/api/v2/business/{row['id']}/settle"
    assert client.post(url, json={"confirmed": False}).status_code == 422
    assert client.post(url, json={"confirmed": True}).json()["ok"]
    assert client.post(url, json={"confirmed": True}).json()["replayed"]
    settled = client.get("/api/v2/business").json()
    assert settled["expected_minor"] == 0 and settled["finance"]["balance_minor"] == before + 200000


def test_seed_reconciliation_and_affordability(client):
    data = client.get("/api/v2/dashboard").json()
    financial = data["finance"]
    assert financial["balance_minor"] == 600000
    assert financial["opening_minor"] + financial["income_minor"] - financial["expense_minor"] == financial["balance_minor"]
    assert financial["chart"][-1]["balance_minor"] == financial["balance_minor"]
    assert invoice(client, "premium")["affordability"]["remaining_minor"] == -99900
    assert invoice(client)["affordability"]["remaining_minor"] == 50100


def test_qr_version_expiry_and_signature(client):
    row = invoice(client)
    assert client.post("/api/v2/scan", json={"token": row["qr_token"]}).json()["invoice"]["id"] == row["id"]
    assert client.post("/api/v2/scan", json={"token": row["qr_token"] + "bad"}).status_code == 422
    revised = client.post("/api/v2/invoices", json={"previous_id": row["id"], "items": [{"product_id": "mouse", "quantity": 2}]}).json()
    assert revised["version"] == 2 and revised["total_minor"] == 179800
    assert client.post("/api/v2/scan", json={"token": row["qr_token"]}).status_code == 409
    amount = client.post("/api/v2/invoices", json={"kind": "payment", "amount_minor": 10000}).json()
    assert client.post("/api/v2/scan", json={"token": amount["qr_token"]}).json()["invoice"]["kind"] == "payment"
    with SessionLocal() as db:
        from datetime import UTC, datetime, timedelta
        record = db.get(InvoiceSnapshot, amount["id"])
        record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    assert client.post(f"/api/v2/invoices/{amount['id']}/authorize", json={"fingerprint": amount["fingerprint"], "version": 1, "authorized": True}).status_code == 409


def test_recovery_single_settlement_and_purchase_lifecycle(client):
    row = invoice(client)
    result = pay(client, row, True)
    assert result["healed"]
    repeat = pay(client, row, True)
    assert repeat["replayed"]
    history = client.get("/api/v2/history").json()
    assert len([entry for entry in history if entry["case_id"] == result["case_id"]]) == 1
    assert client.get("/api/v2/dashboard").json()["finance"]["balance_minor"] == 400100
    issues = client.get("/api/v2/incidents").json()
    assert len(issues) == 1 and issues[0]["status"] == "recovered"
    item = client.get("/api/v2/purchases").json()[0]
    delivered = client.post(f"/api/v2/purchases/{item['id']}/action", json={"action": "deliver", "days_ago": 2}).json()
    assert delivered["replacement_days"] == 5
    request = client.post(f"/api/v2/purchases/{item['id']}/action", json={"action": "replacement"}).json()
    assert request["request"] == "replacement_requested"
    case = client.get(f"/api/v2/briefcases/{result['case_id']}").json()
    assert any(e["kind"] == "invoice_snapshot" for e in case["evidence"])
    seller = client.get(f"/api/v2/briefcases/{result['case_id']}?merchant=true").json()
    assert all(e["kind"] != "classification" for e in seller["evidence"])
    connection = client.post(f"/api/v2/briefcases/{result['case_id']}/connect")
    assert connection.status_code == 200, connection.text


def test_exact_authorization_and_cart(client):
    row = invoice(client)
    assert client.post(f"/api/v2/invoices/{row['id']}/authorize", json={"fingerprint": "changed", "version": 1, "authorized": True}).status_code == 409
    assert client.post(f"/api/v2/invoices/{row['id']}/authorize", json={"fingerprint": row["fingerprint"], "version": 1, "authorized": False}).status_code == 409
    cart = client.put("/api/v2/cart", json={"items": [{"product_id": "cable", "quantity": 2}]}).json()
    assert cart["total_minor"] == 59800
    assert client.get("/api/v2/cart").json()["total_minor"] == 59800
    assert client.put("/api/v2/cart", json={"items": [{"product_id": "cable", "quantity": -1}]}).status_code == 422


def test_separate_store_watchlist_price_alert_and_checkout(client, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from app import v2_watch
    from app.storefront import app as store
    from app.v2_models import PriceWatch

    with TestClient(store) as shop:
        body = {"items": [{"product_id": "headphones", "quantity": 2}]}
        assert shop.post("/handoff", json=body).status_code == 403
        handoff = shop.post("/handoff", json=body, headers={"Origin": "http://testserver"}).json()
        token = handoff["url"].split("?cart=")[1]
        payment = shop.post("/handoff?intent=checkout", json=body, headers={"Origin": "http://testserver"}).json()
        payment_token = payment["url"].split("?cart=")[1]
        assert "/#/purchases/during?" in payment["url"]
        assert '"priceCurrency": "INR"' in shop.get("/product/headphones").text
    review = client.post("/api/v2/store-cart/review", json={"token": token}).json()
    assert review["total_minor"] == 399800
    assert not client.get("/api/v2/watch").json()
    assert client.post("/api/v2/store-cart/track", json={"token": token}).status_code == 200
    assert client.post("/api/v2/store-cart/track", json={"token": token}).status_code == 200
    row, = client.get("/api/v2/watch").json()
    assert row["quantity"] == 2 and row["current_minor"] == 199900
    assert not client.get("/api/v2/cart").json()["items"]
    assert not client.get("/api/v2/invoices").json()
    assert client.post("/api/v2/store-cart/checkout", json={"token": token}).status_code == 422
    made = client.post("/api/v2/store-cart/checkout", json={"token": payment_token}).json()
    assert made["total_minor"] == 399800 and made["status"] == "open"
    assert len(client.get("/api/v2/watch").json()) == 1
    monkeypatch.setattr(v2_watch, "read_market", lambda _: {"key": "headphones", "currency": "INR", "minor": 169900})
    with SessionLocal() as db:
        db.get(PriceWatch, row["id"]).checked_at = datetime.now(UTC) - timedelta(hours=5)
        db.commit()
    fresh = client.post(f"/api/v2/watch/{row['id']}/refresh").json()
    assert fresh["low_minor"] == 169900 and len(fresh["history"]) == 2
    lows = [entry for entry in client.get("/api/v2/dashboard").json()["observations"] if entry["kind"] == "price_low"]
    assert len(lows) == 1 and lows[0]["destination"] == f"#/watch/{row['id']}"


def test_public_product_extraction_and_external_upi_handoff(client):
    from app.price_sources import PriceUnavailable, parse_price, read_public_product
    url = "upi://pay?pa=shop%40bank&pn=Retailer&am=123.45&cu=INR&tr=store001"
    result = client.post("/api/v2/scan", json={"token": url}).json()
    assert result["upi_uri"] == url and result["details"]["amount"] == 123.45
    assert client.post("/api/v2/scan", json={"token": url + "&am=1"}).json()["upi_uri"] is None
    assert not client.get("/api/v2/invoices").json()
    markup = '<script type="application/ld+json">{"@type":"Product","name":"Kirana scale","sku":"scale1","offers":{"@type":"Offer","price":"39.98","priceCurrency":"USD"}}</script>'
    assert parse_price(markup, "shop.example")["minor"] == 3998
    with pytest.raises(PriceUnavailable):
        parse_price(markup + markup.replace("39.98", "35.00"), "shop.example")
    with pytest.raises(PriceUnavailable):
        read_public_product("https://127.0.0.1/product")


def test_razorpay_requires_signed_callback_and_verified_capture(client, monkeypatch):
    import hashlib
    import hmac
    from app import v2_checkout

    row = invoice(client)
    provider = {"order_id": "order_abc", "id": "pay_def", "status": "authorized", "amount": row["total_minor"], "currency": "INR", "method": "upi"}
    monkeypatch.setattr(v2_checkout, "credentials", lambda: ("rzp_test_fixture", "fixture_secret"))
    monkeypatch.setattr(v2_checkout, "request_provider", lambda method, path, **kwargs: {"id": "order_abc", **kwargs["json"]} if method == "POST" else provider.copy())
    url = f"/api/v2/invoices/{row['id']}"
    payload = {"authorized": True, "version": row["version"], "fingerprint": row["fingerprint"], "method": "upi"}
    assert client.post(url + "/provider-order", json=payload).json()["order_id"] == "order_abc"
    assert client.post(url + "/authorize", json=payload).status_code == 409
    callback = {"payment_id": "pay_def", "signature": "0" * 64}
    assert client.post(url + "/provider-confirm", json=callback).status_code == 403
    callback["signature"] = hmac.new(b"fixture_secret", b"order_abc|pay_def", hashlib.sha256).hexdigest()
    assert client.post(url + "/provider-confirm", json=callback).json()["pending"]
    assert not client.get("/api/v2/purchases").json()
    provider["status"] = "captured"
    provider["amount"] += 1
    assert client.post(url + "/provider-confirm", json=callback).status_code == 409
    provider["amount"] -= 1
    result = client.post(url + "/provider-confirm", json=callback).json()
    assert result["ok"] and result["item_ids"]
    assert client.post(url + "/provider-confirm", json=callback).json()["replayed"]
    assert len([record for record in client.get("/api/v2/history").json() if record["case_id"] == result["case_id"]]) == 1


def test_new_kirana_profile_starts_in_business_workspace():
    with TestClient(app) as trader:
        session = trader.post("/api/v2/session", json={"persona": "shopkeeper"}).json()
        trader.headers["x-csrf-token"] = session["csrf"]
        home = trader.get("/api/v2/dashboard").json()
        assert home["profile"]["business_type"] == "Kirana shop"
        assert home["workspace"] == "business" and home["finance"]["balance_minor"] == 6500000
        balance = trader.post("/api/v2/ask", json={"message": "Business balance"}).json()
        assert "₹65,000.00" in balance["answer"]
        assert home["focus"]["data"]["title"] == "Rice, dal and cooking oil restock"
        assert trader.get("/api/v2/business").json()["expected_minor"] == 240000
        restock, receivable, goal = home["suggestions"]
        assert [restock["kind"], receivable["kind"], goal["kind"]] == ["bill", "receivable", "goal"]
        assert receivable["destination"].startswith("#/budget/business/")
        assert goal["destination"].startswith("#/budget/goals/")
        assert trader.put("/api/v2/daily-tasks", json={"id": restock["id"], "completed": True}).status_code == 200
        latest = trader.get("/api/v2/dashboard").json()
        assert latest["suggestions"][0]["completed"] and latest["focus"]["id"] == receivable["id"]
        focus = trader.post("/api/v2/ask", json={"message": "What should I focus on today?"}).json()
        assert focus["destination"] == receivable["destination"]
        assert next(bill for bill in latest["bills"] if bill["id"] == restock["data"]["id"])["status"] == "open"
        assert trader.put("/api/v2/daily-tasks", json={"id": restock["id"], "completed": False}).status_code == 200
        assert trader.get("/api/v2/dashboard").json()["focus"]["id"] == restock["id"]


def test_reminders_rank_critical_tasks_ahead_of_price_lows_and_goals():
    from datetime import date
    from app.v2 import reminder_priority

    today = date(2026, 11, 15)
    cases = [
        ("goal", 18, {}),
        ("bill", 70, {"due": "2026-11-23"}),
        ("price_low", 72, {}),
        ("bill", 95, {"due": "2026-11-16"}),
        ("replacement", 60, {"days": 0}),
        ("bill", 95, {"due": "2026-11-15"}),
        ("bill", 95, {"due": "2026-11-14"}),
        ("payment", 100, {"status": "checking"}),
    ]
    priorities = [reminder_priority({"kind": kind, "priority": priority, "data": data}, today)
                  for kind, priority, data in cases]
    assert all(earlier < later for earlier, later in zip(priorities, priorities[1:]))


def test_preferences_workspace_and_unified(client):
    profile = {"name": "Priya", "language": "kn", "configuration": "unified"}
    assert client.put("/api/v2/profile", json=profile).status_code == 200
    data = client.get("/api/v2/dashboard").json()
    assert data["workspace"] == "all" and data["finance"]["balance_minor"] == 600000
    assert data["profile"]["language"] == "kn"
    prefs = {"configuration": "separate", "override": "auto", "context_consent": True, "work_start": 9, "work_end": 18}
    assert workspace(prefs, hour=10) == "business"
    assert workspace(prefs, hour=21) == "personal"
    assert workspace(prefs | {"override": "personal"}, "supplier", 10) == "personal"


def test_planning_bills_and_notices(client):
    emi = client.post("/api/v2/plans", json={"kind": "emi", "title": "Laptop EMI", "principal_minor": 120000, "months": 12}).json()
    assert emi["data"]["installment_minor"] == 10000
    assert len(emi["data"]["schedule"]) == 12
    bill_id = emi["data"]["schedule"][0]["bill_id"]
    assert client.post(f"/api/v2/bills/{bill_id}/record-payment", json={"confirmed": True}).status_code == 200
    assert client.post(f"/api/v2/bills/{bill_id}/record-payment", json={"confirmed": True}).json()["replayed"]
    assert client.get("/api/v2/dashboard").json()["finance"]["balance_minor"] == 590000
    notice = client.post("/api/v2/notices", json={"subject": "Invoice review", "message": "Please review the recorded invoice."}).json()
    assert client.get("/api/v2/notices").json()[0]["status"] == "draft"
    assert client.post(f"/api/v2/notices/{notice['id']}/send", json={"confirmed": True}).json()["status"] == "sent_in_app"


@pytest.mark.parametrize("language,questions", [
    ("en", ["hello", "what is my balance", "show my budget", "which bills are due", "today's focus", "can I afford headphones", "payment recovery", "purchase warranty", "EMI installments", "savings goal"]),
    ("hi", ["नमस्ते", "मेरे पैसे कितने हैं", "मेरा बजट", "बिल कब देय है", "आज की प्राथमिकता", "हेडफोन खरीद सकता हूँ", "भुगतान की समस्या", "वारंटी दिखाओ", "किस्त कितनी बची", "बचत लक्ष्य"]),
    ("kn", ["ನಮಸ್ಕಾರ", "ನನ್ನ ಹಣ ಎಷ್ಟು", "ನನ್ನ ಬಜೆಟ್", "ಬಿಲ್ ಯಾವಾಗ", "ಇಂದು ಆದ್ಯತೆ", "ಹೆಡ್‌ಫೋನ್ ಖರೀದಿಸಬಹುದೇ", "ಪಾವತಿ ಸಮಸ್ಯೆ", "ವಾರಂಟಿ ವಿವರ", "ಕಂತು ಎಷ್ಟು", "ಉಳಿತಾಯ ಗುರಿ"]),
])
def test_multilingual_record_answers(client, language, questions):
    client.put("/api/v2/profile", json={"name": "Priya", "language": language})
    invoice(client)
    for question in questions:
        response = client.post("/api/v2/ask", json={"message": question})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["topic"] != "fallback", (question, data)
        assert data["answer"] and data["destination"].startswith("#/")
    balance = client.post("/api/v2/ask", json={"message": {"en": "balance", "hi": "पैसे", "kn": "ಹಣ"}[language]}).json()
    assert "₹6,000.00" in balance["answer"]


def test_tara_uses_model_for_unknown_intent_and_keeps_recorded_answers(client, monkeypatch):
    from collections import deque
    from app import v2_intelligence

    monkeypatch.setattr(v2_intelligence, "MODEL_CALLS", deque())
    monkeypatch.setattr(v2_intelligence.llm, "available", lambda: True)
    calls = []

    def classify(system, question, **options):
        calls.append(question)
        assert options["timeout"] == 5 and options["want_json"]
        return {"topic": "balance"} if len(calls) == 1 else {"topic": "execute_transfer"}

    monkeypatch.setattr(v2_intelligence.llm, "complete", classify)
    question = "How much is in my account?"
    response = client.post("/api/v2/ask", json={"message": question}).json()
    assert response["routing"] == "llm" and "₹6,000.00" in response["answer"]
    assert "authorized_ledger" in response["evidence"]
    assert client.post("/api/v2/ask", json={"message": "Send money now"}).json()["topic"] == "blocked"
    assert calls == [question]
    response = client.post("/api/v2/ask", json={"message": "Something else?"}).json()
    assert response["topic"] == "fallback" and response["routing"] == "rules"


def test_hosted_contextiq_accepts_only_configured_frontend_origin(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "hosted_demo", True)
    monkeypatch.setattr(settings, "public_base_url", "https://contextiq.example.com")
    monkeypatch.setattr(settings, "app_url", "https://contextiq.vercel.app")
    allowed = {"Origin": settings.app_url}
    denied = {"Origin": "https://other.vercel.app"}
    payload = {"message": "balance"}

    assert client.post("/api/v2/ask", headers=denied, json=payload).status_code == 403
    assert client.post("/api/v2/ask", headers=allowed | {"X-CSRF-Token": ""}, json=payload).status_code == 403
    assert client.post("/api/v2/ask", headers=allowed, json=payload).status_code == 200
