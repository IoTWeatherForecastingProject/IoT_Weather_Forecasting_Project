from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, BigInteger, Numeric, String, DateTime,
    SmallInteger, Boolean, Text, Index, desc, UniqueConstraint, text
)
from app.db.session import Base


class WeatherMeasurement(Base):
    __tablename__ = "weather_measurements"

    __table_args__ = (
        Index("idx_weather_device_timestamp", "device_id", desc("timestamp")),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    temperature = Column(Numeric(5, 2), nullable=False)
    humidity = Column(Numeric(5, 2), nullable=False)
    pressure = Column(Numeric(6, 2), nullable=False)
    rain_raw = Column(Integer, nullable=True)
    rain_detected = Column(SmallInteger, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AlertLog(Base):
    __tablename__ = "alert_logs"

    __table_args__ = (
        Index("idx_alert_logs_timestamp", desc("timestamp")),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    alert_type = Column(String(50), nullable=False)
    rain_probability = Column(Numeric(5, 4), nullable=False)
    threshold = Column(Numeric(5, 4), nullable=False)
    mqtt_sent = Column(Boolean, default=False)
    telegram_sent = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)


class SystemConfig(Base):
    __tablename__ = "system_config"

    config_key = Column(String(100), primary_key=True)
    config_value = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))



class ReferenceWeather(Base):
    """Dữ liệu tham chiếu theo đúng cấu trúc của migration 002."""

    __tablename__ = "reference_weather"

    __table_args__ = (
        UniqueConstraint("source", "timestamp", name="uq_reference_source_ts"),
        Index("idx_reference_source_ts", "source", desc("timestamp")),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(String(30), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    lat = Column(Numeric(8, 5), nullable=False)
    lon = Column(Numeric(8, 5), nullable=False)
    temperature = Column(Numeric(5, 2), nullable=True)
    humidity = Column(Numeric(5, 2), nullable=True)
    pressure = Column(Numeric(6, 2), nullable=True)
    precipitation = Column(Numeric(6, 2), nullable=True)
    fetched_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
