from contextlib import nullcontext
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import text

from app.db.session import engine
from app.services.schema_migrations import apply_migrations, MIGRATIONS


@pytest.mark.parametrize("existing_data", [False, True])
def test_migrations_new_and_existing_schema_preserve_data_and_are_repeatable(existing_data):
    with engine.connect() as db:
        transaction = db.begin()
        try:
            name = "migration_test_" + uuid.uuid4().hex
            db.exec_driver_sql(f'CREATE SCHEMA "{name}"')
            db.exec_driver_sql(f'SET LOCAL search_path TO "{name}"')
            if existing_data:
                db.exec_driver_sql((MIGRATIONS / "001_init_schema.sql").read_text(encoding="utf-8"))
                # Historical duplicates are preserved; only new identities are unique.
                db.exec_driver_sql("INSERT INTO weather_measurements(device_id,temperature,humidity,pressure) "
                                   "VALUES ('old',30,75,1000),('old',30,75,1000)")
            isolated = SimpleNamespace(dialect=engine.dialect, begin=lambda: nullcontext(db))
            expected = sorted(path.name for path in MIGRATIONS.glob("[0-9]*.sql"))
            assert apply_migrations(isolated) == expected
            assert apply_migrations(isolated) == []
            count = db.execute(text("SELECT COUNT(*) FROM weather_measurements")).scalar_one()
            assert count == (2 if existing_data else 0)
            assert db.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == len(expected)
            assert db.execute(text("SELECT COUNT(*) FROM reference_weather")).scalar_one() == 0
            assert db.execute(text("SELECT COUNT(*) FROM forecast_snapshots")).scalar_one() == 0
            assert db.execute(text("SELECT COUNT(*) FROM forecast_test_periods")).scalar_one() == 0
        finally:
            transaction.rollback()


def test_migration_checksum_detects_changed_applied_file(tmp_path):
    directory = tmp_path / "sql"
    directory.mkdir()
    file = directory / "001_test.sql"
    file.write_text("SELECT 1;", encoding="utf-8")
    with engine.connect() as db:
        transaction = db.begin()
        try:
            name = "migration_test_" + uuid.uuid4().hex
            db.exec_driver_sql(f'CREATE SCHEMA "{name}"')
            db.exec_driver_sql(f'SET LOCAL search_path TO "{name}"')
            isolated = SimpleNamespace(dialect=engine.dialect, begin=lambda: nullcontext(db))
            assert apply_migrations(isolated, directory) == ["001_test.sql"]
            file.write_text("SELECT 2;", encoding="utf-8")
            with pytest.raises(RuntimeError, match="Migration"):
                apply_migrations(isolated, directory)
        finally:
            transaction.rollback()
