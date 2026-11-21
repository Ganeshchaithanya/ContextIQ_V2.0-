"""CI-only restoration comparison against synthetic PostgreSQL test data."""
import os
import psycopg
from sqlalchemy.engine import make_url

url = make_url(os.environ["POSTGRES_TEST_URL"])
target = url.set(database="contextiq_restore")
with psycopg.connect(url.render_as_string(hide_password=False)) as original, psycopg.connect(target.render_as_string(hide_password=False)) as restored:
    for query in ("SELECT COUNT(*), COALESCE(SUM(amount_minor),0) FROM ledger",
                  "SELECT COUNT(*) FROM agent_runs", "SELECT COUNT(*) FROM checkpoints",
                  "SELECT version_num FROM alembic_version"):
        assert original.execute(query).fetchall() == restored.execute(query).fetchall(), "Restore verification failed"
print("PostgreSQL restore verified: ledger counts and totals, agent runs, checkpoints and schema revision match.")
