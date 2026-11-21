"""Back up a database; restore only into an empty, explicitly named target.

Secrets are passed through child-process environment variables, never argv or logs.
"""
import argparse
import os
import sqlite3
import subprocess
from pathlib import Path
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url


def postgres_environment(url):
    env = dict(os.environ)
    for key, value in {"PGHOST": url.host, "PGPORT": url.port or 5432, "PGUSER": url.username,
                       "PGPASSWORD": url.password, "PGDATABASE": url.database,
                       "PGSSLMODE": url.query.get("sslmode", "require")}.items():
        if value is not None:
            env[key] = str(value)
    return env


def backup(source_url, destination):
    url, destination = make_url(source_url), Path(destination)
    if destination.exists():
        raise FileExistsError("Choose a new backup filename")
    if url.drivername.startswith("sqlite"):
        source = Path(url.database).resolve()
        if not source.is_file():
            raise FileNotFoundError("Source database not found")
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
    else:
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", str(destination)],
                       env=postgres_environment(url), check=True, timeout=300, capture_output=True)


def restore(backup_file, target_url):
    url = make_url(target_url)
    if url.drivername.startswith("sqlite"):
        target = Path(url.database)
        if target.exists():
            raise ValueError("Restore target must be a new database file")
        with sqlite3.connect(Path(backup_file).resolve().as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
            src.backup(dst)
    else:
        engine = create_engine(url.set(drivername="postgresql+psycopg"))
        try:
            if inspect(engine).get_table_names():
                raise ValueError("Restore target must be an empty database")
        finally:
            engine.dispose()
        subprocess.run(["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges", str(backup_file)],
                       env=postgres_environment(url), check=True, timeout=300, capture_output=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("file")
    args = parser.parse_args()
    variable = "DATABASE_URL" if args.action == "backup" else "RESTORE_DATABASE_URL"
    url = os.environ.get(variable)
    if not url:
        parser.error(variable + " must be configured")
    try:
        backup(url, args.file) if args.action == "backup" else restore(args.file, url)
    except Exception as exc:
        raise SystemExit("Operation failed: " + type(exc).__name__) from None
    print("Database operation completed. Validate record counts before switching application traffic.")
