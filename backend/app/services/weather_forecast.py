"""Shared forecast and actuation path for HTTP requests and scheduled evaluation."""
from datetime import datetime, timedelta, timezone
import json
import logging

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import SystemConfig, WeatherMeasurement
from app.services.alert_service import AlertService
from app.services.forecast_client import ForecastClient
from app.ingestion.validation import usable_measurement
from app.services.rain_threshold import resolve_rain_threshold

logger = logging.getLogger(__name__)
# TV2 requires 90 actual minutes; allow room for sample timing and TV3 lookbacks.
# Keep this constant independent of optional ML imports at API startup.
FORECAST_HISTORY_MINUTES = 120


class NoRecentMeasurements(ValueError):
    def __init__(self, device_id):
        self.device_id = device_id
        super().__init__(f"Khong co du lieu do trong {FORECAST_HISTORY_MINUTES} phut gan nhat.")


class UnusableMeasurements(ValueError):
    pass


def build_forecast(db: Session, device_id=None, mqtt_client=None, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    query = db.query(WeatherMeasurement).filter(
        WeatherMeasurement.timestamp >= now - timedelta(minutes=FORECAST_HISTORY_MINUTES),
        WeatherMeasurement.timestamp <= now,
    )
    if device_id is None:
        latest = query.order_by(desc(WeatherMeasurement.timestamp), desc(WeatherMeasurement.id)).first()
        if latest is not None:
            device_id = latest.device_id
    records = query.filter(WeatherMeasurement.device_id == device_id).order_by(
        WeatherMeasurement.timestamp, WeatherMeasurement.id
    ).all()
    if not records:
        raise NoRecentMeasurements(device_id)
    if not usable_measurement(records[-1]):
        raise UnusableMeasurements("Mau moi nhat ngoai khoang cam bien; kiem tra sensor-health.")
    valid_records = [row for row in records if usable_measurement(row)]
    measurements = [
        {"device_id": r.device_id, "timestamp": r.timestamp,
         "temperature": float(r.temperature), "humidity": float(r.humidity),
         "pressure": float(r.pressure), "rain_raw": r.rain_raw, "rain_detected": r.rain_detected}
        for r in valid_records
    ]
    threshold, _, _ = resolve_rain_threshold(db)
    forecast = ForecastClient.get_forecast(measurements, threshold=threshold)
    forecast.update(
        history_window_minutes=FORECAST_HISTORY_MINUTES,
        history_span_minutes=round((valid_records[-1].timestamp - valid_records[0].timestamp).total_seconds() / 60, 2),
        history_measurements=len(valid_records), rain_alert_threshold=threshold,
    )
    measured_at = records[-1].timestamp
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)
    if (now - measured_at).total_seconds() <= settings.ALERT_MAX_DATA_AGE_SECONDS:
        # Preserve the existing +30m preference when probabilities are tied.
        horizon = max((30, 10, 60), key=lambda h: forecast[f"plus_{h}m"]["rain_probability"])
        AlertService.evaluate_and_trigger(
            device_id=device_id, rain_probability=forecast[f"plus_{horizon}m"]["rain_probability"],
            horizon_minutes=horizon, mqtt_client=mqtt_client, threshold=threshold,
        )
        if mqtt_client is not None and mqtt_client.is_connected():
            snapshot = {
                "type": "rain_forecast",
                "device_id": device_id,
                "horizon_minutes": horizon,
                "probability_pct": round(forecast[f"plus_{horizon}m"]["rain_probability"] * 100),
            }
            try:
                mqtt_client.publish(
                    f"{settings.MQTT_TOPIC_PREFIX}/{device_id}/forecast",
                    json.dumps(snapshot), qos=0, retain=False,
                )
            except Exception:
                logger.exception("[FORECAST] Failed to publish OLED forecast for %s", device_id)
    else:
        logger.info("[ALERT ENGINE] Bo qua actuation vi du lieu tram %s da cu", device_id)
    return forecast
