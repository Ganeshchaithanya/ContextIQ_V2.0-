import os
import tempfile
import uuid
from pathlib import Path
from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

os.environ["PAYPAL_ENV"] = "mock"
os.environ["CONTEXTIQ_LEGACY_TEST_AUTH"] = "0"
os.environ["CONTEXTIQ_WORKER_MODE"] = "off"
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(tempfile.gettempdir()) / f"operations-{uuid.uuid4().hex}.db").as_posix()
os.environ["CONTEXTIQ_MOCK_STORE"] = str(Path(tempfile.gettempdir()) / f"provider-{uuid.uuid4().hex}.json")
os.environ["GROQ_API_KEY"] = os.environ["ANTHROPIC_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from app.main import app, _apply_webhook
from app.db import SessionLocal, init_db
from app.config import settings
from app.models import AgentRun, Approval, Case, OutboxEntry, Participant, WebhookInboxEntry, WorkerHeartbeat
from app.outbox import claim, dead_letters, dispatch_pending, on, publish


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as client:
        session = client.post("/api/v2/session", json={"persona": "freelancer"}).json()
        client.headers["x-csrf-token"] = session["csrf"]
        with SessionLocal.begin() as db:
            db.execute(delete(OutboxEntry))
        yield client


def test_health_and_operator_metrics_are_separate(client, monkeypatch):
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").status_code == 200
    assert client.get("/api/metrics").status_code == 401
    monkeypatch.setattr(settings, "admin_token", "operator-test-only")
    response = client.get("/api/metrics", headers={"Authorization": "Bearer operator-test-only"})
    assert response.status_code == 200 and "outbox" in response.json()
    monkeypatch.setattr(settings, "worker_mode", "external")
    with SessionLocal.begin() as db:
        db.execute(delete(WorkerHeartbeat))
        db.add(WorkerHeartbeat(id="scheduler", at=datetime.now(UTC) - timedelta(minutes=5)))
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503


def test_logout_requires_csrf_and_revokes_the_session(client):
    assert client.delete("/api/v2/session", headers={"x-csrf-token": "forged"}).status_code == 403
    assert client.get("/api/v2/profile").status_code == 200
    assert client.delete("/api/v2/session").status_code == 200
    assert client.get("/api/v2/profile").status_code == 401


def test_job_is_rolled_back_with_its_transaction(client):
    with SessionLocal() as db:
        publish(db, topic="test.rollback", aggregate_id="rollback", payload={})
        db.rollback()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OutboxEntry)) == 0


def test_only_one_consumer_claims_and_crashed_lease_is_recoverable(client):
    with SessionLocal.begin() as db:
        publish(db, topic="test.lease", aggregate_id="lease", payload={}, dedupe_key="test-lease")
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    winner, = [row for row in claims if row]
    assert claim() is None
    with SessionLocal.begin() as db:
        db.get(OutboxEntry, winner["id"]).lease_until = datetime.now(UTC) - timedelta(seconds=1)
    retry = claim()
    assert retry["id"] == winner["id"] and retry["token"] != winner["token"] and retry["attempts"] == 2


def test_missing_handler_retries_and_dead_letters_instead_of_losing_job(client):
    with SessionLocal.begin() as db:
        row = publish(db, topic="no-such-handler", aggregate_id="missing", payload={})
        row.max_attempts = 2
        ident = row.id
    assert dispatch_pending() == 0
    with SessionLocal.begin() as db:
        row = db.get(OutboxEntry, ident)
        assert row.published_at is None and row.error == "LookupError"
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert dispatch_pending() == 0
    assert any(row["id"] == ident for row in dead_letters())


def test_webhook_inbox_and_job_commit_together_and_duplicate_is_acknowledged(client):
    event = {"id": "event-" + uuid.uuid4().hex, "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {}}
    with SessionLocal() as db:
        _apply_webhook(db, event)
        db.rollback()
    with SessionLocal.begin() as db:
        assert db.scalar(select(WebhookInboxEntry).where(WebhookInboxEntry.event_id == event["id"])) is None
        assert _apply_webhook(db, event)["accepted"]
    with SessionLocal.begin() as db:
        assert _apply_webhook(db, event)["duplicate"]
        assert db.scalar(select(func.count()).select_from(OutboxEntry)) == 1
    assert dispatch_pending() == 1
    with SessionLocal() as db:
        assert db.scalar(select(WebhookInboxEntry).where(WebhookInboxEntry.event_id == event["id"])).processed_at


def test_approval_is_atomic_and_refund_is_bound_to_exact_amount(client):
    from app.security.gateway import check, issue_approval
    with SessionLocal.begin() as db:
        case = Case(owner_id="test-buyer", merchant="test-seller", title="Approval test", amount=1000)
        db.add(case)
        db.flush()
        db.add(Participant(case_id=case.id, party_id="test-seller", role="seller"))
        approval = issue_approval(db, user_id="test-seller", case=case, action="refund", amount=10)
        ident, token = case.id, approval.token
    with SessionLocal.begin() as db:
        verdict = check(db, actor="test-seller", action="refund", case=db.get(Case, ident), approval_token=token, amount=11)
        assert verdict.decision == "deny" and not db.get(Approval, token).used
    def approve(_):
        with SessionLocal.begin() as db:
            return check(db, actor="test-seller", action="refund", case=db.get(Case, ident), approval_token=token, amount=10).decision
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(approve, range(16)))
    assert results.count("allow") == 1 and results.count("deny") == 15


def test_unknown_financial_states_fail_closed(client):
    from app.finance_state import InvalidStateTransition, validate_transition
    for before, after in (("typo", "captured"), ("refunded", "captured"), ("captured", "buyer_approved")):
        with pytest.raises(InvalidStateTransition):
            validate_transition(before, after)


def test_capture_evidence_must_match_exact_amount_and_currency(client, monkeypatch):
    from types import SimpleNamespace
    from app.paypal import payments
    from app.paypal.adapter import PayPalError
    provider = {"id": "verified-order", "status": "COMPLETED", "purchase_units": [{"payments": {"captures": [
        {"id": "capture-mismatch", "status": "COMPLETED", "amount": {"value": "11.00", "currency_code": "INR"}}
    ]}}]}
    monkeypatch.setattr(payments, "get_client", lambda: SimpleNamespace(get_order=lambda ident: provider))
    with SessionLocal.begin() as db:
        case = Case(owner_id="test-buyer", title="Capture verification", merchant="Seller", amount=10,
                    currency="INR", payment_state="order_created", paypal_order_id="verified-order")
        db.add(case)
        db.flush()
        with pytest.raises(PayPalError):
            payments.sync_order_state(db, case)
        assert case.payment_state == "order_created" and case.paypal_capture_id is None


def test_telemetry_exports_only_metadata(client, monkeypatch):
    import json
    from app import observability
    monkeypatch.setattr(observability, "destinations", lambda: [("https://telemetry.example/v1/traces", None)])
    with SessionLocal.begin() as db:
        run = AgentRun(user_id="private-user", status="complete", state={"input": {"message": "PRIVATE QUESTION"},
            "result": {"topic": "overview", "routing": "rules", "answer": "PRIVATE BALANCE 123456"}})
        db.add(run)
        db.flush()
        observability.enqueue_agent_trace(db, run)
        job = db.scalar(select(OutboxEntry).where(OutboxEntry.topic == "telemetry.agent"))
        assert job and "PRIVATE" not in json.dumps(job.payload) and "private-user" not in json.dumps(job.payload)


def test_checkpoints_resume_without_reclassifying_or_duplicate_conversation(client, monkeypatch):
    from app import v2_intelligence, v2_analysis
    from app.agent_runs import execute, persistent_graph
    from app.v2_models import DemoSession, PlanningRecord
    calls = []
    monkeypatch.setattr(v2_intelligence.llm, "available", lambda: True)
    monkeypatch.setattr(v2_intelligence.llm, "complete", lambda *a, **k: calls.append(1) or {"topic": "balance"})
    with SessionLocal.begin() as db:
        session = list(db.scalars(select(DemoSession)))[-1]
        run = AgentRun(user_id=session.buyer_id, state={"input": {"message": "How much is actually available?",
            "user_id": session.buyer_id, "workspace_id": session.workspace_id, "language": "en"}})
        db.add(run)
        db.flush()
        ident, owner = run.id, run.user_id
    original = v2_analysis.financial_analysis
    monkeypatch.setattr(v2_analysis, "financial_analysis", lambda *a: (_ for _ in ()).throw(RuntimeError("injected crash")))
    with SessionLocal() as db, pytest.raises(RuntimeError, match="injected crash"):
        execute(ident, db)
    snapshot = persistent_graph().get_state({"configurable": {"thread_id": owner + ":" + ident}})
    assert snapshot.next == ("support",) and "db" not in snapshot.values
    monkeypatch.setattr(v2_analysis, "financial_analysis", original)
    with SessionLocal() as db:
        first = execute(ident, db)
        assert execute(ident, db) == first
        assert db.scalar(select(func.count()).select_from(PlanningRecord).where(PlanningRecord.id == ident)) == 1
    assert len(calls) == 1


def test_oidc_rejects_forged_tokens_and_disables_demo_identity(client, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from types import SimpleNamespace
    import jwt
    from app.security import identity
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer", "https://identity.example")
    monkeypatch.setattr(settings, "oidc_audience", "contextiq")
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://identity.example/jwks")
    monkeypatch.setattr(identity, "key_client", lambda url: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())))
    claims = {"iss": settings.oidc_issuer, "aud": settings.oidc_audience, "sub": "test-account",
              "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(minutes=10)}
    valid = jwt.encode(claims, key, algorithm="RS256")
    assert client.post("/api/v2/session", json={}).status_code == 403
    forged = jwt.encode(claims, "attacker-key-that-is-long-enough-for-test", algorithm="HS256")
    assert client.post("/api/v2/auth/exchange", headers={"Authorization": "Bearer " + forged}).status_code == 401
    assert client.post("/api/v2/auth/exchange", headers={"Authorization": "Bearer " + valid}).status_code == 200
    # No fictional funds, clients or invoices are seeded into a verified account.
    assert client.get("/api/v2/dashboard").json()["finance"]["balance_minor"] == 0


def test_migration_reapplication_preserves_existing_records(client):
    from app.models import LedgerEntry
    with SessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(LedgerEntry))
    init_db()
    init_db()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(LedgerEntry)) == count


def test_backup_restore_roundtrip_and_existing_target_protection(tmp_path):
    import sqlite3
    from tools.backup_restore import backup, restore
    source, snapshot, target = (tmp_path / name for name in ("source.db", "backup.db", "restored.db"))
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE payments (id INTEGER PRIMARY KEY, amount_minor INTEGER)")
        db.execute("INSERT INTO payments VALUES (1, 29900)")
    backup("sqlite:///" + source.as_posix(), snapshot)
    restore(snapshot, "sqlite:///" + target.as_posix())
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT amount_minor FROM payments").fetchone()[0] == 29900
    with pytest.raises(ValueError, match="new database"):
        restore(snapshot, "sqlite:///" + target.as_posix())


def test_circuit_allows_only_one_recovery_probe_and_capacity_is_bounded():
    from app.reliability import CircuitBreaker, CircuitOpen, ConcurrencyLimiter, CapacityExceeded
    breaker = CircuitBreaker("isolated-test", failure_threshold=1, recovery_timeout=0, half_open_successes=1)
    with pytest.raises(ValueError):
        with breaker:
            raise ValueError("Dependency failed")
    with breaker:
        with pytest.raises(CircuitOpen):
            with breaker:
                pass
    assert breaker.state == "closed"
    limiter = ConcurrencyLimiter(1)
    with limiter:
        with pytest.raises(CapacityExceeded):
            with limiter:
                pass
