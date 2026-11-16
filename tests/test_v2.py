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


def test_confirmation_lockout_and_buyer_can_decline_before_capture(client):
    row = invoice(client, "headphones")
    path = f"/api/v2/invoices/{row['id']}"
    original = client.get("/api/v2/history").json()
    payload = {"fingerprint": row["fingerprint"], "version": row["version"], "authorized": True}
    assert client.post(path + "/authorize", json=payload | {"authorized": False}).status_code == 409
    first = client.post(path + "/authorize", json=payload).json()
    assert first["gateway"] == "step_up"
    code = first["step_up_code_demo"]
    wrong = "000000" if code != "000000" else "000001"
    for _ in range(5):
        result = client.post(path + "/authorize", json=payload | {"step_up_code": wrong}).json()
        assert not result["ok"]
    result = client.post(path + "/authorize", json=payload | {"step_up_code": code}).json()
    assert result["gateway"] == "deny" and result["step_up_code_demo"] is None
    assert "Too many" in result["reasons"][0]
    assert client.get(path).json()["can_decline"]
    assert client.post(path + "/cancel").json()["ok"]
    assert client.post(path + "/cancel").json()["ok"]
    assert client.get(path).json()["status"] == "cancelled"
    assert client.post(path + "/authorize", json=payload | {"step_up_code": code}).status_code == 409
    assert client.post(path + "/reconcile").status_code == 409
    assert client.post("/api/v2/scan", json={"token": row["qr_token"]}).status_code == 409
    assert client.get("/api/v2/history").json() == original
    assert client.get(path).headers["x-frame-options"] == "DENY"
    unapproved = invoice(client, "cable")
    assert client.post(f"/api/v2/invoices/{unapproved['id']}/cancel").json()["ok"]
    assert client.post("/api/v2/invoices", json={
        "previous_id": unapproved["id"], "items": [{"product_id": "cable", "quantity": 1}],
    }).status_code == 409


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
    restored = client.get("/api/v2/dashboard").json()
    assert restored["finance"]["balance_minor"] == 600000
    assert restored["allocation"]["savings_minor"] == 200000 and restored["flexible_minor"] == 50000
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
    payload = {"fingerprint": row["fingerprint"], "version": row["version"], "authorized": True, "simulated_method": "upi"}
    initial = client.post(f"/api/v2/invoices/{row['id']}/authorize", json=payload).json()
    if initial.get("gateway") == "step_up":
        payload["step_up_code"] = initial["step_up_code_demo"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(f"/api/v2/invoices/{row['id']}/authorize", json=payload), range(2)))
    assert all(result.status_code == 200 and result.json()["ok"] for result in results)
    paid = client.get(f"/api/v2/invoices/{row['id']}").json()
    assert paid["checkout"]["simulated_method"] == "upi"
    assert client.post(f"/api/v2/invoices/{row['id']}/authorize", json=payload | {"simulated_method": "card"}).status_code == 409
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
    assert data["allocation"]["savings_minor"] == 200000
    assert data["flexible_minor"] == 50000
    premium = invoice(client, "premium")["affordability"]
    assert premium["remaining_minor"] == -99900 and premium["alternative"]["id"] == "headphones"
    affordable = invoice(client)["affordability"]
    assert affordable["remaining_minor"] == 0 and affordable["savings_after_minor"] == 50100


def test_purchase_updates_budget_forecast_and_remaining_interests(client):
    from app.storefront import app as shop_app

    quantities = {"items": [{"product_id": "headphones", "quantity": 2}, {"product_id": "cable", "quantity": 1}]}
    with TestClient(shop_app) as shop:
        quote = shop.post("/handoff", headers={"Origin": "http://testserver"}, json=quantities).json()
    token = quote["url"].split("?cart=")[1]
    assert client.post("/api/v2/store-cart/track", json={"token": token}).status_code == 200
    assert client.put("/api/v2/cart", json=quantities).status_code == 200
    row = invoice(client)
    projection = row["affordability"]
    before = client.get("/api/v2/dashboard").json()
    assert before["finance"]["balance_minor"] == 600000
    assert len(client.get("/api/v2/watch").json()) == 2
    assert client.post(f"/api/v2/invoices/{row['id']}/authorize", json={
        "fingerprint": row["fingerprint"], "version": row["version"], "authorized": False,
    }).status_code == 409
    assert client.get("/api/v2/dashboard").json()["flexible_minor"] == 50000

    payment = pay(client, row)
    assert pay(client, row)["replayed"]
    paid = client.get("/api/v2/dashboard").json()
    assert paid["finance"]["balance_minor"] == projection["projected_funds_minor"] == 400100
    assert paid["allocation"]["savings_minor"] == projection["savings_after_minor"] == 50100
    assert paid["flexible_minor"] == projection["remaining_minor"] == 0
    assert client.get("/api/v2/forecast").json()["points"][-1]["balance_minor"] == 50100
    matching = [entry for entry in client.get("/api/v2/history").json() if entry["case_id"] == payment["case_id"]]
    assert len(matching) == 1 and matching[0]["amount_minor"] == row["total_minor"]
    assert {item["product_id"]: item["quantity"] for item in client.get("/api/v2/cart").json()["items"]} == {"headphones": 1, "cable": 1}
    assert {item["title"]: item["quantity"] for item in client.get("/api/v2/watch").json()} == {"Everyday headphones": 1, "USB-C charging cable": 1}


def test_price_linked_savings_recalculate_and_release_after_purchase(client, monkeypatch):
    from datetime import UTC, date, datetime, timedelta
    from app import finance, v2_watch
    from app.storefront import app as shop_app
    from app.v2 import daily_date
    from app.v2_models import PriceWatch

    with TestClient(shop_app) as shop:
        shared = shop.post("/handoff", headers={"Origin": "http://testserver"}, json={
            "items": [{"product_id": "cable", "quantity": 2}],
        }).json()["url"].split("?cart=")[1]
    assert client.post("/api/v2/store-cart/track", json={"token": shared}).status_code == 200
    watch, = client.get("/api/v2/watch").json()
    due = date.fromisoformat(daily_date())
    plan = client.post(f"/api/v2/watch/{watch['id']}/plan", json={"target_date": finance.add_months(due, 2).isoformat()}).json()
    goal = lambda: next(row for row in client.get("/api/v2/plans").json() if row["id"] == plan["id"])
    assert goal()["data"]["target_minor"] == 59800 and goal()["data"]["contribution_minor"] == 29900
    assert client.get("/api/v2/dashboard").json()["flexible_minor"] == 20100

    monkeypatch.setattr(v2_watch, "read_market", lambda _: {"key": "cable", "currency": "INR", "minor": 25000})
    with SessionLocal() as db:
        db.get(PriceWatch, watch["id"]).checked_at = datetime.now(UTC) - timedelta(hours=5)
        db.commit()
    assert client.post(f"/api/v2/watch/{watch['id']}/refresh").status_code == 200
    assert goal()["data"]["target_minor"] == 50000 and goal()["data"]["contribution_minor"] == 25000
    assert client.get("/api/v2/dashboard").json()["flexible_minor"] == 25000

    settings_path = f"/api/v2/plans/{plan['id']}/purchase"
    assert client.put(settings_path, json={"target_date": (due + timedelta(days=20)).isoformat()}).status_code == 200
    assert goal()["data"]["contribution_minor"] == 50000
    assert client.put(settings_path, json={"monthly_override_minor": 18000}).status_code == 200
    assert goal()["data"]["contribution_minor"] == 18000
    assert client.put(settings_path, json={"monthly_override_minor": None}).status_code == 200
    assert goal()["data"]["contribution_minor"] == 50000
    assert client.put(settings_path, json={"active": False}).status_code == 200
    assert client.get("/api/v2/dashboard").json()["flexible_minor"] == 50000
    assert client.put(settings_path, json={"active": True}).status_code == 200

    row = invoice(client, "cable", 2)
    assert row["affordability"]["savings_after_minor"] == 190200
    pay(client, row)
    assert goal()["data"]["status"] == "purchased"
    budget = client.get("/api/v2/dashboard").json()
    assert budget["finance"]["balance_minor"] == 540200 and budget["allocation"]["savings_minor"] == 190200
    assert not client.get("/api/v2/watch").json()


def test_automatic_horizon_can_reach_a_year_and_fixed_date_is_editable(monkeypatch):
    from datetime import UTC, date, datetime, timedelta
    from app import finance, v2_watch
    from app.storefront import app as shop_app
    from app.v2 import daily_date
    from app.v2_models import PriceWatch

    with TestClient(app) as buyer, TestClient(shop_app) as shop:
        session = buyer.post("/api/v2/session", json={"persona": "shopkeeper"}).json()
        buyer.headers["x-csrf-token"] = session["csrf"]
        token = shop.post("/handoff", headers={"Origin": "http://testserver"}, json={
            "items": [{"product_id": "laptop", "quantity": 1}],
        }).json()["url"].split("?cart=")[1]
        assert buyer.post("/api/v2/store-cart/track", json={"token": token}).status_code == 200
        watch, = buyer.get("/api/v2/watch").json()
        plan_id = buyer.post(f"/api/v2/watch/{watch['id']}/plan", json={}).json()["id"]
        plan = lambda: next(p["data"] for p in buyer.get("/api/v2/plans").json() if p["id"] == plan_id)
        today = date.fromisoformat(daily_date())
        assert plan()["target_date"] == finance.add_months(today, 11).isoformat()
        assert plan()["contribution_minor"] == 500000
        assert buyer.get("/api/v2/dashboard").json()["flexible_minor"] == 4600000

        monkeypatch.setattr(v2_watch, "read_market", lambda _: {"key": "laptop", "currency": "INR", "minor": 6000000})
        with SessionLocal() as db:
            db.get(PriceWatch, watch["id"]).checked_at = datetime.now(UTC) - timedelta(hours=5)
            db.commit()
        assert buyer.post(f"/api/v2/watch/{watch['id']}/refresh").status_code == 200
        assert plan()["target_date"] == finance.add_months(today, 12).isoformat()
        assert buyer.get("/api/v2/dashboard").json()["finance"]["balance_minor"] == 6500000
        assert buyer.put(f"/api/v2/plans/{plan_id}/purchase", json={
            "target_date": finance.add_months(today, 18).isoformat(),
        }).status_code == 200
        assert plan()["date_mode"] == "fixed" and plan()["contribution_minor"] == 333334


def test_cart_plans_share_savings_and_tara_adjusts_when_budget_changes():
    from app.storefront import app as shop_app

    with TestClient(app) as trader, TestClient(shop_app) as shop:
        session = trader.post("/api/v2/session", json={"persona": "shopkeeper"}).json()
        trader.headers["x-csrf-token"] = session["csrf"]
        handoff = shop.post("/handoff?intent=plan", headers={"Origin": "http://testserver"}, json={
            "items": [{"product_id": "laptop", "quantity": 1}, {"product_id": "cable", "quantity": 2}],
        }).json()["url"]
        assert "#/budget/goals?cart=" in handoff
        body = {"token": handoff.split("?cart=")[1]}
        assert trader.post("/api/v2/store-cart/checkout", json=body).status_code == 422
        result = trader.post("/api/v2/store-cart/plan", json=body).json()
        assert len(result["plan_ids"]) == 2
        assert trader.post("/api/v2/store-cart/plan", json=body).json() == result
        planned = [p for p in trader.get("/api/v2/plans").json() if p["id"] in result["plan_ids"]]
        assert len(planned) == 2
        assert all(p["purpose"] == "business" and p["data"]["date_mode"] == "automatic"
                   and p["data"]["contribution_minor"] > 0 for p in planned)
        assert sum(p["data"]["contribution_minor"] for p in planned) == 500000
        assert trader.get("/api/v2/invoices").json() == []
        before = trader.get("/api/v2/dashboard").json()
        ready, = [task for task in before["suggestions"] if task["kind"] == "purchase_ready"]
        assert ready["data"]["amount_minor"] == 59800

        assert trader.post("/api/v2/business", json={
            "kind": "supplier_invoice", "title": "Extra stock", "amount_minor": 5400000,
        }).status_code == 200
        after = trader.get("/api/v2/dashboard").json()
        assert after["focus"]["kind"] == "budget_shortfall"
        assert after["focus"]["data"]["amount_minor"] == 100000
        assert not any(task["kind"] == "purchase_ready" for task in after["suggestions"])
        assert after["finance"]["balance_minor"] == before["finance"]["balance_minor"]


def test_workspace_allocates_after_bills_and_limits_savings_to_recorded_funds():
    with TestClient(app) as trader:
        session = trader.post("/api/v2/session", json={"persona": "shopkeeper"}).json()
        trader.headers["x-csrf-token"] = session["csrf"]
        baseline = trader.get("/api/v2/dashboard").json()
        assert baseline["workspace"] == "business" and baseline["flexible_minor"] == 5100000
        assert baseline["allocation"]["committed_minor"] == 1200000
        assert baseline["allocation"]["savings_minor"] == 200000
        payable = trader.post("/api/v2/business", json={
            "kind": "supplier_invoice", "title": "Stock invoice", "amount_minor": 5175000,
        }).json()
        new_plan = trader.get("/api/v2/dashboard").json()
        assert new_plan["allocation"]["committed_minor"] == 6375000
        assert new_plan["allocation"]["savings"][0]["requested_minor"] == 200000
        assert new_plan["allocation"]["savings_minor"] == 125000 and new_plan["flexible_minor"] == 0
        assert trader.post(f"/api/v2/business/{payable['id']}/settle", json={"confirmed": True}).status_code == 200
        settled = trader.get("/api/v2/dashboard").json()
        assert settled["allocation"]["committed_minor"] == 1200000
        assert settled["finance"]["balance_minor"] == 1325000 and settled["flexible_minor"] == 0
        goal, = [p for p in trader.get("/api/v2/plans").json() if p["kind"] == "goal"]
        assert goal["data"]["saved_minor"] == 0


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


def test_background_payment_check_cannot_capture_an_approved_order(client, monkeypatch):
    from app.agents import commerce
    from app.models import Case
    from app.paypal.adapter import get_client
    from app.v2 import refresh_interrupted_payments
    from app.v2_models import DemoSession

    row = invoice(client, "cable")
    monkeypatch.setattr(commerce, "complete_payment", lambda *args: {"ok": False, "pending": True})
    response = client.post(f"/api/v2/invoices/{row['id']}/authorize", json={
        "fingerprint": row["fingerprint"], "version": row["version"], "authorized": True,
    })
    assert response.json()["pending"]
    with SessionLocal() as db:
        saved = db.get(InvoiceSnapshot, row["id"])
        current = db.scalar(select(DemoSession).where(DemoSession.workspace_id == saved.workspace_id))
        case = db.get(Case, saved.case_id)
        refresh_interrupted_payments(db, current)
        assert saved.status == "authorized"
        assert not db.scalar(select(LedgerEntry).where(LedgerEntry.case_id == case.id))
        get_client().capture_order(case.paypal_order_id, request_id=f"fixture-{case.id}")
        refresh_interrupted_payments(db, current)
        db.commit()
        assert saved.status == "paid"
        refresh_interrupted_payments(db, current)
        assert len(list(db.scalars(select(LedgerEntry).where(LedgerEntry.settlement_key == f"capture:{case.id}")))) == 1


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
    replay = client.post("/api/v2/store-cart/checkout", json={"token": payment_token}).json()
    assert replay["id"] == made["id"] and replay["case_id"] is None
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


def test_auto_import_is_idempotent_and_business_bills_recur(client):
    payload = {"title": "Stock order", "amount_minor": 140000, "purpose": "business",
               "due": "2026-11-20", "recurring": True, "import_key": "a" * 64}
    bill = client.post("/api/v2/bills", json=payload).json()
    assert client.post("/api/v2/bills", json=payload).json() == bill | {"replayed": True}
    assert client.post(f"/api/v2/bills/{bill['id']}/record-payment", json={"confirmed": True}).status_code == 200
    rows = [row for row in client.get("/api/v2/bills").json() if row["title"] == "Stock order"]
    assert len(rows) == 2
    upcoming, = [row for row in rows if row["status"] == "open"]
    assert upcoming["purpose"] == "business" and upcoming["due"] == "2026-12-20"


def test_editable_defaults_update_open_bill_and_reserve_without_posting_payments(client):
    draft = {"title": "Stock order", "amount_minor": 140000, "purpose": "personal", "due": "2026-11-20"}
    bill = client.post("/api/v2/bills", json=draft).json()
    reserve = client.post("/api/v2/plans", json={
        "kind": "allocation", "title": "Packaging", "amount_minor": 15000,
    }).json()
    assert client.put(f"/api/v2/plans/{reserve['id']}/reserve", json={"amount_minor": 12000}).status_code == 200
    path = f"/api/v2/bills/{bill['id']}"
    assert client.put(path, json=draft | {"amount_minor": 20000}).status_code == 200
    updated = client.get("/api/v2/dashboard").json()
    assert updated["finance"]["balance_minor"] == 600000
    assert updated["allocation"]["committed_minor"] == 370000
    assert updated["allocation"]["reserved_minor"] == 12000 and updated["flexible_minor"] == 18000
    assert client.post(f"{path}/record-payment", json={"confirmed": True}).status_code == 200
    assert client.put(path, json=draft).status_code == 409


def test_proactive_tara_tip_uses_only_the_predefined_context(client, monkeypatch):
    from app import v2_intelligence

    calls = []

    def choose_hint(system, question, **options):
        calls.append(question)
        return {"choice": 1}

    monkeypatch.setattr(v2_intelligence.llm, "complete", choose_hint)
    v2_intelligence.cached_proactive_tip.cache_clear()
    try:
        path = "/api/v2/guide/tip?kind=bill&urgency=urgent"
        result = client.get(path).json()
        assert result == {"text": v2_intelligence.NEXT_TIPS["bill"][1], "routing": "llm"}
        assert client.get(path).json() == result
        assert len(calls) == 1 and calls[0].startswith("Task: bill. Urgency: urgent.")
        assert client.get("/api/v2/guide/tip?kind=nonexistent").status_code == 422
    finally:
        v2_intelligence.cached_proactive_tip.cache_clear()


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
