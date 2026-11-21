"""Persistent LangGraph execution; only serializable data enters checkpoints."""
import hashlib
import os
import sqlite3
import threading
from pathlib import Path
from datetime import UTC, datetime
from sqlalchemy import select
from .db import DATABASE_URL, SessionLocal
from .models import AgentRun
from .v2_models import PlanningRecord

_compiled = None
_lock = threading.Lock()


def persistent_graph():
    global _compiled
    with _lock:
        if _compiled is None:
            from .v2_intelligence import graph
            from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
            serde = JsonPlusSerializer(pickle_fallback=False)
            if DATABASE_URL.startswith("sqlite"):
                from langgraph.checkpoint.sqlite import SqliteSaver
                from .config import DATA_DIR
                digest = hashlib.sha256(DATABASE_URL.encode()).hexdigest()[:12]
                location = os.getenv("CHECKPOINT_SQLITE_PATH", str(DATA_DIR / f"checkpoints-{digest}.db"))
                saver = SqliteSaver(sqlite3.connect(location, check_same_thread=False), serde=serde)
                saver.setup()
            else:
                import psycopg
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool
                from sqlalchemy.engine import make_url
                from langgraph.checkpoint.postgres import PostgresSaver
                url = make_url(DATABASE_URL).set(drivername="postgresql").render_as_string(hide_password=False)
                pool = ConnectionPool(url, min_size=1, max_size=4, timeout=5,
                    kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
                    check=ConnectionPool.check_connection)
                saver = PostgresSaver(pool, serde=serde)
                with pool.connection() as migration_connection:
                    with migration_connection.transaction():
                        migration_connection.execute("SELECT pg_advisory_xact_lock(708921114)")
                        saver.setup()
            _compiled = graph.compile(checkpointer=saver)
        return _compiled


def execute(run_id, db):
    run = db.get(AgentRun, run_id)
    if not run:
        raise LookupError("Agent run missing")
    if run.status == "complete":
        return run.state["result"]
    config = {"configurable": {"thread_id": run.user_id + ":" + run.id}}
    supervisor = persistent_graph()
    snapshot = supervisor.get_state(config)
    initial = run.state["input"]
    if snapshot.values and not snapshot.next and "answer" in snapshot.values:
        result = snapshot.values
    else:
        result = supervisor.invoke(None if snapshot.values else initial,
                                   config=config, context={"db": db}, durability="sync")
    output = {key: result[key] for key in ("topic", "answer", "destination", "evidence", "routing")}
    output.update(sources=result.get("sources", []), analysis=result.get("analysis"), run_id=run.id)
    run.state = {**run.state, "result": output}
    run.status, run.updated_at = "complete", datetime.now(UTC)
    if not db.get(PlanningRecord, run.id):
        db.add(PlanningRecord(id=run.id, user_id=run.user_id, kind="conversation",
               title=initial["message"][:100], data={"question": initial["message"], **output, "at": run.updated_at.isoformat()}))
    from .observability import enqueue_agent_trace
    enqueue_agent_trace(db, run)
    db.commit()
    return output


def resume(payload):
    with SessionLocal() as db:
        execute(payload["run_id"], db)
