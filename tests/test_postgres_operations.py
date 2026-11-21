"""Integration checks against the isolated PostgreSQL service started by CI."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import pytest

url = os.getenv("POSTGRES_TEST_URL")
if not url:
    pytest.skip("Set POSTGRES_TEST_URL to an isolated test database", allow_module_level=True)
os.environ["DATABASE_URL"] = url
os.environ["PAYPAL_ENV"] = "mock"
os.environ["CONTEXTIQ_WORKER_MODE"] = "off"
os.environ["CONTEXTIQ_LEGACY_TEST_AUTH"] = "0"
os.environ["GROQ_API_KEY"] = os.environ["ANTHROPIC_API_KEY"] = ""

from sqlalchemy import select, text, update
from app.db import SessionLocal, init_db
from app.models import OutboxEntry
from app.outbox import claim, publish


def test_postgres_migrations_queue_claim_and_crash_recovery():
    init_db()
    init_db()
    with SessionLocal.begin() as db:
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "20261121_01"
        row = publish(db, topic="postgres-test", aggregate_id="isolated-test", payload={}, dedupe_key=uuid.uuid4().hex)
        ident = row.id
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    first, = [row for row in results if row]
    assert first["id"] == ident
    with SessionLocal.begin() as db:
        db.get(OutboxEntry, ident).lease_until = datetime.now(UTC) - timedelta(seconds=1)
    recovered = claim()
    assert recovered["id"] == ident and recovered["token"] != first["token"]
    with SessionLocal.begin() as db:
        db.get(OutboxEntry, ident).published_at = datetime.now(UTC)


def test_postgres_native_agent_checkpoint_and_live_data_equations():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.agent_runs import persistent_graph
    with TestClient(app) as client:
        session = client.post("/api/v2/session", json={"persona": "freelancer"}).json()
        client.headers["x-csrf-token"] = session["csrf"]
        result = client.post("/api/v2/ask", json={"message": "How is my financial condition?"})
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["topic"] == "overview" and data["analysis"]["metrics"]["balance_minor"] > 0
        assert persistent_graph().checkpointer is not None
        assert client.get("/api/v2/ask").json()[-1]["run_id"] == data["run_id"]
        assert client.get("/health/ready").status_code == 200


def test_postgres_sixteen_concurrent_consumers_claim_each_job_once():
    init_db()
    expected = set()
    with SessionLocal.begin() as db:
        # Prior integration scenarios leave synthetic delayed jobs in this isolated CI database.
        db.execute(update(OutboxEntry).values(published_at=datetime.now(UTC)))
        for _ in range(16):
            expected.add(publish(db, topic="contention-test", aggregate_id="isolated-test",
                                 payload={}, dedupe_key=uuid.uuid4().hex).id)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: claim(), range(16)))
    claimed = [row for row in results if row]
    assert len(claimed) == 16
    assert {row["id"] for row in claimed} == expected
    assert len({row["token"] for row in claimed}) == 16
    assert all(row["attempts"] == 1 for row in claimed)
    with SessionLocal.begin() as db:
        for ident in expected:
            db.get(OutboxEntry, ident).published_at = datetime.now(UTC)
