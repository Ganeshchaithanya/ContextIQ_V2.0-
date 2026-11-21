"""Database-backed transactional jobs with expiring leases and at-least-once delivery."""
from datetime import UTC, datetime, timedelta
import logging
import secrets
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from .db import SessionLocal
from .models import OutboxEntry

log = logging.getLogger(__name__)
BATCH_SIZE = 10
_HANDLERS = {}

def on(topic):
    def register(fn):
        if fn not in _HANDLERS.setdefault(topic, []):
            _HANDLERS[topic].append(fn)
        return fn
    return register

def publish(db, *, topic, aggregate_id, payload, aggregate_type="case", dedupe_key=None):
    # sqlite3's legacy transaction mode otherwise RELEASEs a first SAVEPOINT as
    # an independent commit. Force a real outer transaction before the savepoint.
    if db.bind.dialect.name == "sqlite":
        connection = db.connection()
        if not connection.connection.dbapi_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
    if dedupe_key:
        existing = db.scalar(select(OutboxEntry).where(OutboxEntry.dedupe_key == dedupe_key))
        if existing:
            return existing
    entry = OutboxEntry(topic=topic, aggregate_id=aggregate_id, aggregate_type=aggregate_type,
                        payload=payload, dedupe_key=dedupe_key)
    try:
        with db.begin_nested():
            db.add(entry)
            db.flush()
    except IntegrityError:
        if not dedupe_key:
            raise
        return db.scalar(select(OutboxEntry).where(OutboxEntry.dedupe_key == dedupe_key))
    return entry

def claim():
    stamp = datetime.now(UTC)
    with SessionLocal.begin() as db:
        eligible = (OutboxEntry.published_at.is_(None), OutboxEntry.available_at <= stamp,
                    OutboxEntry.attempts < OutboxEntry.max_attempts,
                    or_(OutboxEntry.lease_until.is_(None), OutboxEntry.lease_until <= stamp))
        candidates = list(db.scalars(select(OutboxEntry.id).where(*eligible).order_by(OutboxEntry.available_at).limit(20)))
        for ident in candidates:
            token = secrets.token_hex(16)
            won = db.execute(update(OutboxEntry).where(OutboxEntry.id == ident, *eligible).values(
                lease_token=token, lease_until=stamp + timedelta(seconds=180), attempts=OutboxEntry.attempts + 1)).rowcount
            if won:
                row = db.get(OutboxEntry, ident)
                return {"id": ident, "token": token, "topic": row.topic, "payload": dict(row.payload), "attempts": row.attempts}
    return None

def dispatch_pending(limit=BATCH_SIZE, stop=None):
    processed = 0
    for _ in range(limit):
        if stop is not None and stop.is_set():
            break
        job = claim()
        if not job:
            break
        failure = None
        try:
            handlers = _HANDLERS.get(job["topic"])
            if not handlers:
                raise LookupError("No registered handler for job topic")
            for handler in handlers:
                handler({**job["payload"], "_job_id": job["id"]})
        except Exception as exc:
            failure = type(exc).__name__  # Never persist exception messages containing upstream secrets.
            log.warning("job_failed", extra={"job_id": job["id"], "error_type": failure})
        with SessionLocal.begin() as db:
            values = {"lease_token": None, "lease_until": None, "error": failure}
            if failure:
                values["available_at"] = datetime.now(UTC) + timedelta(seconds=min(300, 2 ** job["attempts"]))
            else:
                values["published_at"] = datetime.now(UTC)
            owned = db.execute(update(OutboxEntry).where(OutboxEntry.id == job["id"],
                OutboxEntry.lease_token == job["token"]).values(**values)).rowcount
            processed += bool(owned and not failure)
    return processed

def dead_letters(limit=100):
    with SessionLocal() as db:
        rows = db.scalars(select(OutboxEntry).where(OutboxEntry.published_at.is_(None),
            OutboxEntry.attempts >= OutboxEntry.max_attempts,
            or_(OutboxEntry.lease_until.is_(None), OutboxEntry.lease_until < datetime.now(UTC)))
            .order_by(OutboxEntry.created_at.desc()).limit(limit))
        return [{"id": row.id, "topic": row.topic, "aggregate_id": row.aggregate_id,
                 "attempts": row.attempts, "error": row.error} for row in rows]
