from alembic import context
from app.db import Base, engine
from app import models, v2_models  # noqa: F401

def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()

supplied = context.config.attributes.get("connection")
if supplied is not None:
    run(supplied)
else:
    with engine.begin() as connection:
        run(connection)
