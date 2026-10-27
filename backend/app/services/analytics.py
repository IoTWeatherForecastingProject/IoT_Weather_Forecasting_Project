"""Optional TV3 adapters. Missing/unmerged analytics never prevent TV1 startup."""
from datetime import datetime, timedelta, timezone
import json
import logging

import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import WeatherMeasurement, ReferenceWeather
from app.services.optional_providers import load_symbol

logger = logging.getLogger(__name__)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def measurement_dict(row):
    return {"timestamp": utc(row.timestamp), "temperature": float(row.temperature),
            "humidity": float(row.humidity), "pressure": float(row.pressure),
            "rain_raw": row.rain_raw, "rain_detected": row.rain_detected}


def sensor_health(db: Session, device_id: str, window_minutes: int, now=None):
    now = now or datetime.now(timezone.utc)
    rows = db.query(WeatherMeasurement).filter(
        WeatherMeasurement.device_id == device_id,
        WeatherMeasurement.timestamp >= now - timedelta(minutes=window_minutes),
        WeatherMeasurement.timestamp <= now,
    ).order_by(WeatherMeasurement.timestamp, WeatherMeasurement.id).all()
    result = {"device_id": device_id, "window_minutes": window_minutes, "status": "UNKNOWN",
              "checked_at": None, "anomalies": [], "reason": "no_data",
              "analysis_source": "not_integrated"}
    if not rows:
        return result
    last = utc(rows[-1].timestamp)
    result["checked_at"] = last.isoformat()
    if (now - last).total_seconds() > settings.ALERT_MAX_DATA_AGE_SECONDS:
        result["reason"] = "stale_data"
        return result
    if settings.ANALYTICS_ENGINE_MODE == "disabled":
        result["reason"] = "analytics_not_integrated"
        return result
    try:
        detector = load_symbol("sensor_analytics.anomaly_detector", "SensorAnomalyDetector")
        report = detector.analyze(pd.DataFrame([measurement_dict(row) for row in rows]))
        if report["status"] not in ("OK", "WARNING", "FAULT") or not isinstance(report["anomalies"], list):
            raise ValueError("Invalid sensor health report")
        json.dumps(report, allow_nan=False)
        result.update(status=report["status"], anomalies=report["anomalies"],
                      checked_at=report.get("checked_at", last.isoformat()), analysis_source="external",
                      reason="anomalies_detected" if report["anomalies"] else "no_anomalies_detected")
    except (ImportError, AttributeError):
        result.update(reason="analytics_unavailable", analysis_source="unavailable")
    except Exception:
        logger.exception("[ANALYTICS] Sensor health provider failed")
        result.update(reason="analytics_failed", analysis_source="unavailable")
    return result


def benchmark(db: Session, device_id: str, source: str, hours: int, now=None):
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    reference = db.query(ReferenceWeather).filter(
        ReferenceWeather.source == source, ReferenceWeather.timestamp >= start,
        ReferenceWeather.timestamp <= now,
    ).order_by(ReferenceWeather.timestamp).all()
    rows = db.query(WeatherMeasurement).filter(
        WeatherMeasurement.device_id == device_id,
        WeatherMeasurement.timestamp >= start - timedelta(minutes=5),
        WeatherMeasurement.timestamp <= now,
    ).order_by(WeatherMeasurement.timestamp, WeatherMeasurement.id).all()
    columns = ["timestamp", "temperature", "humidity", "pressure"]
    points = [
        {"timestamp": utc(row.timestamp), **{field: float(getattr(row, field))
                                       if getattr(row, field) is not None else None for field in columns[1:]}}
        for row in reference
    ]
    result = {"device_id": device_id, "source": source, "hours": hours, "reference": points,
              "latest_bias": None, "metrics": {}, "reason": "analytics_not_integrated",
              "analysis_source": "not_integrated", "notes": ["Reference data is not a measurement at the IoT sensor."]}
    if not rows or not reference:
        result["reason"] = "no_iot_data" if not rows else "no_reference_data"
        return result
    if settings.ANALYTICS_ENGINE_MODE == "disabled":
        return result
    try:
        build_report = load_symbol("openweather_benchmark.bias_analysis", "build_report")
        iot = pd.DataFrame([measurement_dict(row) for row in rows], columns=columns)
        ref = pd.DataFrame(points, columns=columns)
        report, aligned = build_report(iot, ref, device_id, source)
        latest = None
        if not aligned.empty:
            row = aligned.iloc[-1]
            latest = {"timestamp": row["timestamp"].isoformat(), "n_iot": int(row["n_iot"])}
            for field, key in (("temperature", "temp_bias_c"), ("humidity", "humidity_bias_pct"),
                               ("pressure", "pressure_bias_hpa")):
                error = row[f"iot_{field}"] - row[f"ref_{field}"]
                latest[key] = round(float(error), 4) if pd.notna(error) else None
        values = dict(latest_bias=latest, metrics=report["metrics"],
                      reason=report.get("reason", "matched"), notes=report["meta"]["notes"], analysis_source="external")
        json.dumps(values, allow_nan=False)
        result.update(values)
    except (ImportError, AttributeError):
        result.update(reason="analytics_unavailable", analysis_source="unavailable")
    except Exception:
        logger.exception("[ANALYTICS] Benchmark provider failed")
        result.update(reason="analytics_failed", analysis_source="unavailable")
    return result
