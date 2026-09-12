from datetime import datetime, timezone
from sqlalchemy import Column, Integer, BigInteger, Numeric, String, DateTime, SmallInteger, Boolean, Text
from app.db.session import Base


class WeatherMeasurement(Base):
    __tablename__ = "weather_measurements"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    temperature = Column(Numeric(5, 2), nullable=False)
    humidity = Column(Numeric(5, 2), nullable=False)
    pressure = Column(Numeric(6, 2), nullable=False)
    rain_raw = Column(Integer, nullable=True)
    rain_detected = Column(SmallInteger, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
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

