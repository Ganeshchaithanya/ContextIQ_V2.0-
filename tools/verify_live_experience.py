"""Opt-in smoke test of a deployed fictional demo; never executes real payments.

Usage: python tools/verify_live_experience.py https://context-iq-v2-0.vercel.app
Creates a fresh private demo session. Prints assertions only, never session/token data.
"""
import json
import sys
from urllib.parse import parse_qs, urlsplit

import httpx

base = sys.argv[1].rstrip("/")
assert urlsplit(base).scheme == "https"
results = []

with httpx.Client(base_url=base, timeout=60, follow_redirects=True) as client:
    def call(method, path, body=None, expected=200):
        response = client.request(method, "/api/v2" + path, json=body)
        assert response.status_code == expected, (path, response.status_code)
        return response.json()

    session = call("POST", "/session", {"persona": "freelancer"})
    client.headers["x-csrf-token"] = session["csrf"]
    profile = call("GET", "/profile")
    call("PUT", "/profile", {**profile, "configuration": "business"})
    before = call("GET", "/dashboard")
    for days in (7, 30, 90):
        finance = call("GET", f"/dashboard?days={days}")["finance"]
        value = finance["opening_minor"]
        for row in finance["chart"]:
            value += row["income_minor"] - row["expense_minor"]
            assert value == row["balance_minor"]
        assert value == finance["balance_minor"]
    results.append("PASS: 7/30/90-day live ledger reconciliation")

    call("PUT", "/privacy", {"allow_model_questions": False})
    call("PUT", "/profile", {"name": "Meera", "configuration": "business"})
    assert call("GET", "/transparency")["model_questions_enabled"] is False
    answer = call("POST", "/ask", {"message": "How is my financial condition?"})
    assert answer["analysis"]["records"] and answer["analysis"]["calculations"]
    observation = call("GET", "/transparency")
    assert observation["last_analysis"]["run_id"] == answer["run_id"]
    assert observation["last_analysis"]["routing"] == "rules"
    results.append("PASS: persisted privacy opt-out, Tara calculations and observable run evidence")

    invoice = call("POST", "/invoices", {"purpose": "business", "items": [{"product_id": "cable", "quantity": 1}]})
    payment_url = invoice["payment_url"]
    assert urlsplit(payment_url).scheme == "https"
    assert parse_qs(urlsplit(payment_url).fragment.split("?", 1)[1])["code"] == [invoice["qr_token"]]
    assert call("POST", "/scan", {"token": payment_url})["invoice"]["id"] == invoice["id"]
    results.append("PASS: live QR link targets app code entry and verifies in its owning workspace")

    payload = {"fingerprint": invoice["fingerprint"], "version": invoice["version"], "authorized": True,
               "simulated_method": "upi", "simulated_instrument": "google_pay"}
    payment = call("POST", f"/invoices/{invoice['id']}/authorize", payload)
    if payment.get("gateway") == "step_up":
        payload["step_up_code"] = payment["step_up_code_demo"]
        payment = call("POST", f"/invoices/{invoice['id']}/authorize", payload)
    assert payment["ok"]
    assert call("POST", f"/invoices/{invoice['id']}/authorize", payload)["replayed"]
    after = call("GET", "/dashboard")
    assert after["finance"]["balance_minor"] == before["finance"]["balance_minor"] - invoice["total_minor"]
    assert after["finance"]["chart"][-1]["balance_minor"] == after["finance"]["balance_minor"]
    for key in ("committed_minor", "reserved_minor", "savings_minor", "flexible_minor"):
        assert call("GET", "/transparency")["impact"][key] == after["allocation"][key]
    assert len([row for row in call("GET", "/history") if row["case_id"] == payment["case_id"]]) == 1
    results.append("PASS: human-confirmed simulated UPI, replay protection, dynamic cash/chart/allocation")
    with httpx.Client(base_url=base, timeout=60) as other:
        other.headers["x-csrf-token"] = other.post("/api/v2/session", json={"persona": "freelancer"}).json()["csrf"]
        assert other.post("/api/v2/scan", json={"token": payment_url}).status_code == 404
        assert other.get("/api/v2/transparency").json()["impact"]["saved_analyses"] == 0
    results.append("PASS: cross-workspace invoice denial and analysis isolation")
    assert client.get("/api/metrics").status_code in (401, 404)
    results.append("PASS: operator metrics inaccessible without operator authentication")

print(json.dumps({"site": base, "results": results,
                  "limits": ["No real money moved", "No physical phone camera or visual browser test"]}, indent=2))
