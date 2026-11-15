"""Transactional, checksummed PostgreSQL migrations for existing and fresh databases."""
import hashlib
from pathlib import Path
from sqlalchemy import text

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def apply_migrations(engine, directory=MIGRATIONS):
    if engine.dialect.name != "postgresql":
        raise ValueError("SQL migrations require PostgreSQL")
    applied = []
    with engine.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('weather_schema_migrations'))"))
        db.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations ("
                        "filename VARCHAR(200) PRIMARY KEY, checksum VARCHAR(64) NOT NULL, "
                        "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"))
        for path in sorted(Path(directory).glob("[0-9]*.sql")):
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode()).hexdigest()
            previous = db.execute(text("SELECT checksum FROM schema_migrations WHERE filename=:name"),
                                  {"name": path.name}).scalar_one_or_none()
            if previous is not None:
                if previous != digest:
                    raise RuntimeError(f"Migration da ap dung bi thay doi: {path.name}")
                continue
            db.exec_driver_sql(sql)
            db.execute(text("INSERT INTO schema_migrations(filename,checksum) VALUES (:name,:digest)"),
                       {"name": path.name, "digest": digest})
            applied.append(path.name)
    return applied
