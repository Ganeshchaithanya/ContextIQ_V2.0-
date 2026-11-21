"""Adopt existing schemas without deleting data; add reliability tables."""
from alembic import op
from sqlalchemy import inspect, text
from app.db import Base
from app import models, v2_models  # noqa: F401

revision = "20261121_01"
down_revision = None
branch_labels = depends_on = None

def upgrade():
    connection = op.get_bind()
    # Baseline adopts the pre-migration schema. Subsequent changes require a new revision.
    Base.metadata.create_all(connection)
    from app.migrations import migrate_connection
    migrate_connection(connection)
    columns = {column["name"] for column in inspect(connection).get_columns("outbox")}
    for name, sql_type in (("dedupe_key", "VARCHAR"), ("available_at", "TIMESTAMP"),
                           ("lease_until", "TIMESTAMP"), ("lease_token", "VARCHAR")):
        if name not in columns:
            connection.execute(text(f"ALTER TABLE outbox ADD COLUMN {name} {sql_type}"))
    connection.execute(text("UPDATE outbox SET available_at=created_at WHERE available_at IS NULL"))
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_outbox_dedupe ON outbox (dedupe_key)"))

def downgrade():
    raise RuntimeError("Baseline rollback never drops financial records. Roll back application code or restore a verified backup.")
