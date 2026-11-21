"""Recorded chart, opt-out, QR decoding and stable hosted-signing regressions."""
import os
from pathlib import Path
import tempfile
import uuid

os.environ["DATABASE_URL"] = "sqlite:///" + (Path(tempfile.gettempdir()) / f"experience-{uuid.uuid4().hex}.db").as_posix()
os.environ["PAYPAL_ENV"] = "mock"
os.environ["CONTEXTIQ_WORKER_MODE"] = "off"
os.environ["CONTEXTIQ_LEGACY_TEST_AUTH"] = "0"

import json
import subprocess
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest
import zxingcpp
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.security import crypto


@pytest.fixture
def client():
    with TestClient(app) as client:
        client.headers["x-csrf-token"] = client.post("/api/v2/session", json={"persona": "freelancer"}).json()["csrf"]
        yield client


@pytest.mark.parametrize("days", [7, 30, 90])
def test_chart_reconciles_every_day_and_period(client, days):
    f = client.get(f"/api/v2/dashboard?days={days}").json()["finance"]
    assert len(f["chart"]) == days
    balance = f["opening_minor"]
    for row in f["chart"]:
        assert row["income_minor"] >= 0 and row["expense_minor"] >= 0
        balance += row["income_minor"] - row["expense_minor"]
        assert row["balance_minor"] == balance
    assert balance == f["balance_minor"] == f["opening_minor"] + f["income_minor"] - f["expense_minor"]
    assert sum(row["income_minor"] for row in f["chart"]) == f["income_minor"]
    assert sum(row["expense_minor"] for row in f["chart"]) == f["expense_minor"]


def test_privacy_optout_and_transparency_track_real_runs(client, monkeypatch):
    from app import v2_intelligence
    def forbidden(_):
        raise AssertionError("Question text must not reach a model after opt-out")
    monkeypatch.setattr(v2_intelligence, "classify_with_model", forbidden)
    assert client.put("/api/v2/privacy", json={"allow_model_questions": False}).status_code == 200
    assert client.put("/api/v2/profile", json={"name": "Meera", "configuration": "business"}).json()["allow_model_questions"] is False
    before = client.get("/api/v2/transparency")
    assert before.status_code == 200, before.text
    before = before.json()
    assert before["storage"]["engine"] == "sqlite"
    assert before["model_questions_enabled"] is False
    answer = client.post("/api/v2/ask", json={"message": "xyzzy unfamiliar question"})
    assert answer.status_code == 200, answer.text
    after = client.get("/api/v2/transparency").json()
    assert after["impact"]["saved_analyses"] == before["impact"]["saved_analyses"] + 1
    assert after["last_analysis"]["routing"] == "rules"
    dashboard = client.get("/api/v2/dashboard").json()
    for key in ("committed_minor", "reserved_minor", "savings_minor", "flexible_minor"):
        assert after["impact"][key] == dashboard["allocation"][key]
    financial = client.post("/api/v2/ask", json={"message": "How is my financial condition?"})
    assert financial.status_code == 200
    assert financial.json()["analysis"]["records"]
    assert financial.json()["analysis"]["calculations"]


def test_qr_image_decodes_to_code_entry_and_preserves_ownership(client):
    row = client.post("/api/v2/invoices", json={"items": [{"product_id": "cable", "quantity": 1}]}).json()
    url = row["payment_url"]
    parsed = urlsplit(url)
    assert parsed.fragment.startswith("/scan?code=")
    assert parse_qs(parsed.fragment.split("?", 1)[1])["code"] == [row["qr_token"]]
    js = "const qr=require('./app/static/qrcode.js')(0,'M');qr.addData(JSON.parse(process.argv[1]));qr.make();console.log(JSON.stringify(Array.from({length:qr.getModuleCount()},(_,r)=>Array.from({length:qr.getModuleCount()},(_,c)=>qr.isDark(r,c)?0:255))));"
    modules = json.loads(subprocess.check_output(["node", "-e", js, json.dumps(url)], text=True))
    image = np.repeat(np.repeat(np.pad(np.array(modules, dtype=np.uint8), 4, constant_values=255), 5, axis=0), 5, axis=1)
    decoded = zxingcpp.read_barcodes(image)
    assert len(decoded) == 1 and decoded[0].text == url
    verified = client.post("/api/v2/scan", json={"token": decoded[0].text})
    assert verified.status_code == 200, verified.text
    assert verified.json()["invoice"]["id"] == row["id"]
    with TestClient(app) as other:
        other.headers["x-csrf-token"] = other.post("/api/v2/session", json={"persona": "freelancer"}).json()["csrf"]
        assert other.post("/api/v2/scan", json={"token": url}).status_code == 404
        assert other.get("/api/v2/transparency").json()["impact"]["saved_analyses"] == 0
    assert client.post("/api/v2/scan", json={"token": "https://[invalid"}).status_code == 422
    assert client.post("/api/v2/scan", json={"token": row["qr_token"][:-1] + "!"}).status_code == 422


def test_hosted_signing_survives_restarts_and_rejects_weak_secret(monkeypatch):
    monkeypatch.setattr(settings, "hosted_demo", True)
    monkeypatch.setattr(settings, "server_secret", "a-long-persisted-host-secret-" * 3)
    first = crypto._load_key()
    second = crypto._load_key()
    second.public_key().verify(first.sign(b"restart-test"), b"restart-test")
    monkeypatch.setattr(settings, "server_secret", "a-different-persisted-secret-" * 3)
    assert crypto._load_key().sign(b"restart-test") != first.sign(b"restart-test")
    monkeypatch.setattr(settings, "server_secret", "short")
    with pytest.raises(RuntimeError, match="persistent SERVER_SECRET"):
        crypto._load_key()
