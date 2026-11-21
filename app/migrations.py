"""Versioned additive migration preserving legacy units and per-case currencies."""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import inspect, text


def migrate(engine):
    with engine.begin() as connection:
        migrate_connection(connection)


def migrate_connection(connection):
    connection.execute(text("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY)"))

    # --- version 1: ledger currency columns ---
    if not connection.execute(text("SELECT version FROM schema_versions WHERE version=1")).first():
        columns = {column["name"] for column in inspect(connection).get_columns("ledger")}
        for name, sql_type in (("currency", "VARCHAR"), ("amount_minor", "INTEGER"), ("settlement_key", "VARCHAR")):
            if name not in columns:
                connection.execute(text(f"ALTER TABLE ledger ADD COLUMN {name} {sql_type}"))
        rows = connection.execute(text("SELECT l.id, l.amount, c.currency FROM ledger l LEFT JOIN cases c ON c.id=l.case_id WHERE l.amount_minor IS NULL"))
        for row in list(rows):
            minor = int((Decimal(str(row.amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            connection.execute(text("UPDATE ledger SET amount_minor=:minor,currency=:currency WHERE id=:id"),
                               {"minor": minor, "currency": row.currency or "USD", "id": row.id})
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_ledger_settlement ON ledger (settlement_key)"))
        connection.execute(text("INSERT INTO schema_versions(version) VALUES(1)"))

    # --- version 2: webhook inbox table (Kiro audit, 2026-11-21) ---
    if not connection.execute(text("SELECT version FROM schema_versions WHERE version=2")).first():
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS webhook_inbox (
                id          VARCHAR PRIMARY KEY,
                provider    VARCHAR NOT NULL DEFAULT 'paypal',
                event_id    VARCHAR NOT NULL,
                event_type  VARCHAR NOT NULL,
                received_at TIMESTAMP WITH TIME ZONE,
                processed_at TIMESTAMP WITH TIME ZONE,
                raw_payload JSON,
                CONSTRAINT uq_webhook_inbox_provider_event UNIQUE (provider, event_id)
            )
        """))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_webhook_inbox_event_id ON webhook_inbox (event_id)"))
        connection.execute(text("INSERT INTO schema_versions(version) VALUES(2)"))
