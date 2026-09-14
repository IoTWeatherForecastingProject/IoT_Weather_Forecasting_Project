import logging
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.config import settings

logger = logging.getLogger("weather_backend.db")

# Base Model for ORM
Base = declarative_base()

engine = None
SessionLocal = None


def init_db_engine():
    """Khởi tạo hoặc làm mới Connection Pool cho Database Engine."""
    global engine, SessionLocal
    try:
        engine = create_engine(
            settings.DATABASE_URL,
            pool_pre_ping=settings.DB_POOL_PRE_PING,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_timeout=settings.DB_POOL_TIMEOUT,
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("Khoi tao Database Connection Pool thanh cong (pre_ping=True, pool_size=%d, pool_recycle=%ds)",
                    settings.DB_POOL_SIZE, settings.DB_POOL_RECYCLE)
        return engine
    except Exception as e:
        logger.error("Loi khoi tao Database Engine: %s", e)
        engine = None
        SessionLocal = None
        return None


# Khởi tạo engine ngay khi nạp module
init_db_engine()


def check_db_connection() -> bool:
    """Kiểm tra sức khỏe kết nối CSDL (ping SELECT 1)."""
    global engine
    if engine is None:
        init_db_engine()
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("Database health check ping failed: %s", e)
        return False


def get_db() -> Generator[Session, None, None]:
    """Dependency cung cấp session CSDL cho FastAPI endpoints (tự động đóng khi hoàn tất request)."""
    global SessionLocal
    if SessionLocal is None:
        init_db_engine()
    if SessionLocal is None:
        raise RuntimeError("Database engine is not initialized or unreachable.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager cung cấp session CSDL an toàn (thread-safe) cho background workers."""
    global SessionLocal
    if SessionLocal is None:
        init_db_engine()
    if SessionLocal is None:
        raise RuntimeError("Database engine is not initialized or unreachable.")
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
