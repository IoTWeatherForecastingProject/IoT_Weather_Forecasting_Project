import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    ALLOWED_ORIGINS: list[str] = ["*"]

    # Database settings
    DATABASE_URL: str = "postgresql://weather_admin:weather_secure_pass_2026@localhost:5432/weather_db"
    ASYNC_DATABASE_URL: str = "postgresql+asyncpg://weather_admin:weather_secure_pass_2026@localhost:5432/weather_db"

    # MQTT settings
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_CLIENT_ID: str = "fastapi_backend_worker"
    MQTT_USERNAME: str = "weather_admin"
    MQTT_PASSWORD: str = "weather_secure_pass_2026"
    MQTT_DATA_TOPIC: str = "weather/+/data"
    MQTT_ALERT_TOPIC: str = "weather/station01/alert"

    # Alert & Closed-loop actuation
    RAIN_ALERT_THRESHOLD: float = 0.70
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    ENABLE_TELEGRAM_NOTIFICATIONS: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

