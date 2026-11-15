import os
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    ALLOWED_ORIGINS: list[str] = ["*"]

    # Database settings
    DATABASE_URL: str = "postgresql://weather_admin:weather_secure_pass_2026@localhost:5432/weather_db"
    ASYNC_DATABASE_URL: str = "postgresql+asyncpg://weather_admin:weather_secure_pass_2026@localhost:5432/weather_db"
    DB_POOL_PRE_PING: bool = True
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800  # 30 minutes
    DB_POOL_TIMEOUT: int = 30    # 30 seconds
    AUTO_MIGRATE: bool = True

    # MQTT settings
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_CLIENT_ID: str = "fastapi_backend_worker"
    MQTT_USERNAME: str = "weather_admin"
    MQTT_PASSWORD: str = "weather_secure_pass_2026"
    MQTT_DATA_TOPIC: str = "weather/+/data"
    MQTT_TOPIC_PREFIX: str = "weather"
    MQTT_ALERT_TOPIC: str = "weather/{device_id}/alert"
    MQTT_KEEPALIVE: int = 60
    MQTT_QOS: int = 1

    # Alert & Closed-loop actuation
    RAIN_ALERT_THRESHOLD: float = 0.70
    # Opt in to the integrated TV2/TV3 runtime; standalone remains available.
    FORECAST_ENGINE_MODE: Literal["auto", "heuristic"] = "heuristic"
    ANALYTICS_ENGINE_MODE: Literal["disabled", "auto"] = "disabled"
    ALERT_COOLDOWN_SECONDS: float = Field(default=180, ge=0)
    ALERT_MQTT_ACK_TIMEOUT_SECONDS: float = Field(default=2, gt=0)
    ALERT_MONITOR_ENABLED: bool = True
    ALERT_EVALUATION_INTERVAL_SECONDS: float = Field(default=30, gt=0)
    ALERT_MAX_DATA_AGE_SECONDS: float = Field(default=120, gt=0)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    ENABLE_TELEGRAM_NOTIFICATIONS: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

