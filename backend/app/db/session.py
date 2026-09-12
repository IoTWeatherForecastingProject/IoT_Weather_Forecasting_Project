import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

# Base Model for ORM
Base = declarative_base()

# Synchronous Engine for Ingestion Worker and simple endpoints
try:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as e:
    logger.warning("Database engine could not be initialized immediately: %s", e)
    engine = None
    SessionLocal = None


def get_db():
    """Dependency cung cấp session CSDL cho FastAPI endpoints."""
    if SessionLocal is None:
        raise RuntimeError("Database is not configured or reachable.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

