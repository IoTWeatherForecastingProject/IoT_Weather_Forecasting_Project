"""Shared forecast and actuation path for HTTP requests and scheduled evaluation."""
from datetime import datetime, timedelta, timezone
import json
import logging
import math

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import WeatherMeasurement
from app.services.alert_service import AlertService
from app.services.forecast_client import ForecastClient
from app.services.forecast_evaluation import record_station_forecast
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
    regional_device = settings.REGIONAL_FORECAST_DEVICE_ID
    if settings.FORECAST_ENGINE_MODE == "regional_vvts" and device_id in (None, regional_device):
        from app.services.regional_forecast import regional_forecast

        threshold, _, _ = resolve_rain_threshold(db)
        forecast = regional_forecast(regional_device, now, threshold)
        publish_display_forecast(mqtt_client, regional_device, forecast)
        return forecast

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
    station_model = settings.FORECAST_ENGINE_MODE == "station_inputs"
    if station_model:
        from app.services.station_input_forecast import station_input_forecast

        forecast = station_input_forecast(measurements, now, threshold)
    else:
        forecast = ForecastClient.get_forecast(measurements, threshold=threshold)
    forecast.update(
        history_window_minutes=FORECAST_HISTORY_MINUTES,
        history_span_minutes=round((valid_records[-1].timestamp - valid_records[0].timestamp).total_seconds() / 60, 2),
        history_measurements=len(valid_records), rain_alert_threshold=threshold,
    )
    if station_model:
        record_station_forecast(db, forecast)
        available = [h for h in (30, 10, 60)
                     if forecast[f"plus_{h}m"]["rain_source"] == "model"
                     and isinstance(forecast[f"plus_{h}m"]["rain_probability"], (int, float))
                     and math.isfinite(forecast[f"plus_{h}m"]["rain_probability"])
                     and 0 <= forecast[f"plus_{h}m"]["rain_probability"] <= 1]
        if available:
            horizon = max(available, key=lambda h: forecast[f"plus_{h}m"]["rain_probability"])
            probability = forecast[f"plus_{horizon}m"]["rain_probability"]
            forecast["alert_triggered"] = probability >= threshold
            if forecast["alert_triggered"]:
                forecast["alert_message"] = f"Du bao mua +{horizon} phut dat nguong."
                AlertService.evaluate_and_trigger(
                    device_id=device_id, rain_probability=probability,
                    horizon_minutes=horizon, mqtt_client=mqtt_client, threshold=threshold,
                )
            publish_forecast(mqtt_client, device_id, horizon, forecast,
                             threshold_reached=forecast["alert_triggered"])
        return forecast

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
        publish_forecast(mqtt_client, device_id, horizon, forecast,
                         threshold_reached=forecast["alert_triggered"])
    else:
        logger.info("[ALERT ENGINE] Bo qua actuation vi du lieu tram %s da cu", device_id)
    return forecast


def publish_forecast(mqtt_client, device_id, horizon, forecast, *, threshold_reached):
    if mqtt_client is None or not mqtt_client.is_connected():
        return
    snapshot = {
        "type": "rain_forecast",
        "device_id": device_id,
        "horizon_minutes": horizon,
        "probability_pct": round(forecast[f"plus_{horizon}m"]["rain_probability"] * 100),
        "threshold_reached": threshold_reached,
    }
    try:
        mqtt_client.publish(
            f"{settings.MQTT_TOPIC_PREFIX}/{device_id}/forecast", json.dumps(snapshot), qos=0, retain=False,
        )
    except Exception:
        logger.exception("[FORECAST] Failed to publish OLED forecast for %s", device_id)


def publish_display_forecast(mqtt_client, device_id, forecast):
    available = [h for h in (30, 10, 60) if forecast[f"plus_{h}m"]["rain_probability"] is not None]
    if available:
        horizon = max(available, key=lambda h: forecast[f"plus_{h}m"]["rain_probability"])
        publish_forecast(mqtt_client, device_id, horizon, forecast, threshold_reached=False)
