r"""Reproduce baseline identity and balance findings against an isolated mock DB.

Run from the repository root with .venv\Scripts\python.exe docs/vibex/baseline_probe.py.
The output reports observed behavior of the original source for the Phase 0 audit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT / "data").mkdir(exist_ok=True)
database = ROOT / "data" / f"baseline-probe-{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
os.environ["PAYPAL_ENV"] = "mock"
os.environ["GROQ_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import LedgerEntry


def main() -> None:
    with TestClient(app) as client:
        buyer = {"X-User-Id": "alex"}
        seller = {"X-User-Id": "brightmart"}
        buyer_profile = client.get("/api/profile", headers=buyer)
        seller_profile = client.get("/api/profile", headers=seller)
        before = client.get("/api/budget", headers=buyer).json()
        checkout = client.post(
            "/api/checkout",
            headers=buyer,
            json={
                "merchant": "BrightMart Electronics",
                "seller_id": "brightmart",
                "currency": "USD",
                "items": [{"name": "USB cable", "unit_price": 12.5, "quantity": 1}],
            },
        )
        checkout.raise_for_status()
        order = checkout.json()
        case_id = order["case_id"]
        client.post(f"/api/cases/{case_id}/approve-mock", headers=buyer).raise_for_status()
        authorization = {"approval_token": order["approval_token"]}
        response = client.post(f"/api/cases/{case_id}/capture", headers=buyer, json=authorization)
        response.raise_for_status()
        capture = response.json()
        if capture.get("gateway") == "step_up":
            authorization["step_up_code"] = capture["step_up_code_demo"]
            capture = client.post(
                f"/api/cases/{case_id}/capture", headers=buyer, json=authorization
            ).json()
        assert capture.get("ok") and capture.get("capture_id"), capture
        after = client.get("/api/budget", headers=buyer).json()
        with SessionLocal() as db:
            entries = db.scalars(select(LedgerEntry).where(LedgerEntry.case_id == case_id)).all()
            ledger = [{"amount": entry.amount, "user_id": entry.user_id} for entry in entries]
        notices = client.get("/api/notices", headers=buyer).json()
        result = {
            "mode": "mock, isolated temporary database",
            "profile_without_identity_status": client.get("/api/profile").status_code,
            "same_client_buyer_profile": {"status": buyer_profile.status_code, "name": buyer_profile.json()["name"]},
            "same_client_changed_header_profile": {"status": seller_profile.status_code, "name": seller_profile.json()["name"]},
            "captured_amount": order["amount"],
            "capture_ok": capture["ok"],
            "case_ledger_entries": ledger,
            "available_balance_before": before["available_balance"],
            "available_balance_after": after["available_balance"],
            "month_spent_before": before["month_spent"],
            "month_spent_after": after["month_spent"],
            "notice_statuses": sorted({notice["status"] for notice in notices}),
            "public_metrics_status": client.get("/api/metrics").status_code,
        }
        text = json.dumps(result, indent=2, ensure_ascii=False)
        (ROOT / "docs" / "vibex" / "baseline-probe-results.json").write_text(text + "\n", encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
