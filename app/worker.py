"""Run with python -m app.worker, or embed the same leased consumer in the demo API."""
import logging
import os
import signal
import threading
from datetime import UTC, datetime, timedelta
from sqlalchemy import func, select
from .db import SessionLocal, init_db
from .models import Case, OutboxEntry, RateWindow, WebhookInboxEntry, WorkerHeartbeat
from .outbox import dispatch_pending, on, publish


def schedule():
    from .v2_models import DemoSession, PriceWatch
    from .v2_watch import CHECK_AFTER
    stamp = datetime.now(UTC)
    bucket = int(stamp.timestamp()) // 60
    with SessionLocal.begin() as db:
        beat = db.get(WorkerHeartbeat, "scheduler")
        if beat is None:
            beat = WorkerHeartbeat(id="scheduler")
            db.add(beat)
        beat.at = stamp
        if db.scalar(select(func.count()).select_from(OutboxEntry).where(
                OutboxEntry.published_at.is_(None), OutboxEntry.attempts < OutboxEntry.max_attempts)) >= 1000:
            return  # Admission control affects optional refreshes, never payment evidence.
        sessions = list(db.scalars(select(DemoSession).where(DemoSession.expires_at > stamp)))
        for session in sessions:
            publish(db, topic="workspace.refresh", aggregate_id=session.token_hash,
                    aggregate_type="workspace", payload={"session": session.token_hash},
                    dedupe_key=f"workspace:{session.token_hash}:{bucket}")
        users = [session.buyer_id for session in sessions]
        watches = db.scalars(select(PriceWatch).where(PriceWatch.enabled,
            PriceWatch.user_id.in_(users), PriceWatch.checked_at <= stamp - CHECK_AFTER).limit(12))
        for watch in watches:
            publish(db, topic="watch.refresh", aggregate_id=watch.id, aggregate_type="watch",
                    payload={"id": watch.id, "user_id": watch.user_id}, dedupe_key=f"watch:{watch.id}:{bucket}")
        from sqlalchemy import delete
        db.execute(delete(RateWindow).where(RateWindow.expires_at < stamp - timedelta(minutes=5)))


@on("workspace.refresh")
def refresh_workspace(payload):
    from .v2 import WRITE_LOCK, aware, observations, refresh_interrupted_payments
    from .v2_models import DemoSession
    with WRITE_LOCK, SessionLocal.begin() as db:
        session = db.get(DemoSession, payload["session"])
        if session and aware(session.expires_at) > datetime.now(UTC):
            refresh_interrupted_payments(db, session)
            observations(db, session.buyer_id)


@on("watch.refresh")
def refresh_price(payload):
    from .v2_watch import CHECK_AFTER, refresh_watch
    refresh_watch(payload["id"], payload["user_id"], CHECK_AFTER)


def payment_follow_up(payload):
    from .briefcase import add_event
    with SessionLocal.begin() as db:
        case = db.get(Case, payload["case_id"])
        if case:
            add_event(db, case, "background_follow_up_recorded", "worker",
                      {"payment_state": case.payment_state}, external_id="job:" + payload["_job_id"])


for _topic in ("captured", "refunded", "partially_refunded", "failed", "disputed", "verification_pending"):
    on("payment." + _topic)(payment_follow_up)


@on("webhook.process")
def process_webhook(payload):
    from .main import process_inbox_entry
    with SessionLocal.begin() as db:
        entry = db.get(WebhookInboxEntry, payload["inbox_id"])
        if entry and not entry.processed_at:
            process_inbox_entry(db, entry)


@on("tara.resume")
def resume_agent(payload):
    from .agent_runs import resume
    resume(payload)


@on("telemetry.agent")
def export_agent_trace(payload):
    from .observability import export_trace
    export_trace(payload)


def run(stop):
    next_schedule = 0
    import time
    while not stop.is_set():
        try:
            if time.monotonic() >= next_schedule:
                schedule()
                next_schedule = time.monotonic() + 30
            dispatch_pending(stop=stop)
        except Exception:
            logging.getLogger(__name__).exception("worker_cycle_failed")
        stop.wait(1)


if __name__ == "__main__":
    init_db()
    stop = threading.Event()
    for event in (signal.SIGTERM, signal.SIGINT):
        signal.signal(event, lambda *_: stop.set())
    run(stop)
