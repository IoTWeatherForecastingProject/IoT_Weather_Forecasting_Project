"""Run from project root: backend/.venv/Scripts/python.exe backend/scripts/migrate.py."""
from pathlib import Path
import sys
from sqlalchemy import create_engine

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.config import Settings
from app.services.schema_migrations import apply_migrations


if __name__ == "__main__":
    config = Settings(_env_file=BACKEND / ".env")
    engine = create_engine(config.DATABASE_URL)
    try:
        print({"applied": apply_migrations(engine)})
    finally:
        engine.dispose()
