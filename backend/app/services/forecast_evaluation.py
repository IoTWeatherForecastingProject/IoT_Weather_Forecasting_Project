"""Archive station forecasts and compare them with later station observations."""

import itertools
import logging
import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from statistics import median

from app.db.models import ForecastSnapshot, ForecastTestPeriod, WeatherMeasurement
from app.services.rain_history import MAX_SAMPLE_GAP
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
HISTORY_REQUIRED = {10: 30, 30: 60, 60: 60}
TEMPERATURE_WINDOW = timedelta(minutes=1)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def insert_once(db, model, rows):
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert
    db.execute(insert(model).values(rows).on_conflict_do_nothing())


def record_station_forecast(db, forecast):
    reference = forecast["forecast_reference_at"]
    issued = forecast["generated_at"]
    slot = reference.replace(minute=reference.minute // 5 * 5, second=0, microsecond=0)
    rows = []
    for horizon in HISTORY_REQUIRED:
        point = forecast[f"plus_{horizon}m"]
        if not point["valid_at"] or point["valid_at"] <= issued:
            continue
        temperature = point["temperature_c"] if point["temperature_source"] == "model" else None
        probability = point["rain_probability"] if point["rain_source"] == "model" else None
        if temperature is not None and not math.isfinite(temperature):
            temperature = None
        if probability is not None and not 0 <= probability <= 1:
            probability = None
        if temperature is None and probability is None:
            continue
        rows.append({
            "device_id": forecast["device_id"], "slot_at": slot, "issued_at": issued,
            "reference_at": reference, "valid_at": point["valid_at"], "horizon_minutes": horizon,
            "temperature_c": temperature, "baseline_temperature_c": forecast["current_temperature"],
            "rain_probability": probability, "rain_threshold": forecast["rain_alert_threshold"],
        })
    if rows:
        try:
            insert_once(db, ForecastSnapshot, rows)
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            logger.exception("Could not archive forecast for %s", forecast["device_id"])


def _empty_metrics(horizon):
    return {"horizon_minutes": horizon, "forecasts": 0, "pending": 0, "excluded": 0,
                "temperature_samples": 0, "temperature_mae_c": None, "baseline_mae_c": None,
                "rain_samples": 0, "rain_events": 0, "rain_brier": None, "hits": 0, "false_alarms": 0, "misses": 0}


def forecast_evaluation(db, device_id, days=7, now=None):
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    forecasts = db.query(ForecastSnapshot).filter(
        ForecastSnapshot.device_id == device_id,
        ForecastSnapshot.slot_at >= start - timedelta(minutes=10),
        ForecastSnapshot.issued_at >= start, ForecastSnapshot.issued_at <= now,
    ).order_by(ForecastSnapshot.slot_at).all()
    periods = [(utc(row.starts_at), utc(row.ends_at)) for row in db.query(ForecastTestPeriod).filter(
        ForecastTestPeriod.device_id == device_id,
        ForecastTestPeriod.ends_at >= start - timedelta(minutes=70), ForecastTestPeriod.starts_at <= now,
    )]
    metrics = {h: _empty_metrics(h) for h in HISTORY_REQUIRED}
    result = {"device_id": device_id, "days": days, "test_periods": len(periods), "horizons": list(metrics.values())}
    if not forecasts:
        return result

    observations = db.query(WeatherMeasurement.timestamp, WeatherMeasurement.temperature,
                            WeatherMeasurement.rain_detected).filter(
        WeatherMeasurement.device_id == device_id,
        WeatherMeasurement.timestamp > min(utc(point.reference_at) for point in forecasts),
        WeatherMeasurement.timestamp <= now,
    ).order_by(WeatherMeasurement.timestamp, WeatherMeasurement.id).all()
    temperatures = [(utc(t), float(temp)) for t, temp, _ in observations if -40 <= temp <= 85]
    rain = [(utc(t), wet) for t, _, wet in observations if wet in (0, 1)]
    temp_times = [t for t, _ in temperatures]
    rain_times = [t for t, _ in rain]
    sums = {h: [0.0, 0.0, 0.0] for h in metrics}
    for forecast in forecasts:
        horizon = forecast.horizon_minutes
        stats = metrics[horizon]
        stats["forecasts"] += 1
        reference, target = utc(forecast.reference_at), utc(forecast.valid_at)
        evaluation_end = target + TEMPERATURE_WINDOW
        input_start = reference - timedelta(minutes=HISTORY_REQUIRED[horizon] + 5)
        if any(input_start < end and evaluation_end >= start for start, end in periods):
            stats["excluded"] += 1
            continue
        if evaluation_end > now:
            stats["pending"] += 1
            continue
        if forecast.temperature_c is not None:
            left = bisect_left(temp_times, target - TEMPERATURE_WINDOW)
            right = bisect_right(temp_times, evaluation_end)
            if right - left >= 3:
                observed = median(temp for _, temp in temperatures[left:right])
                stats["temperature_samples"] += 1
                sums[horizon][0] += abs(float(forecast.temperature_c) - observed)
                sums[horizon][1] += abs(float(forecast.baseline_temperature_c) - observed)
        if forecast.rain_probability is not None:
            left = bisect_right(rain_times, reference)
            right = bisect_right(rain_times, target)
            readings = rain[left:right]
            observed = any(wet == 1 for _, wet in readings)
            if not observed:
                times = [reference, *rain_times[left:right], target]
                if any(second - first > MAX_SAMPLE_GAP for first, second in itertools.pairwise(times)):
                    continue
            warned = forecast.rain_probability >= forecast.rain_threshold
            stats["rain_samples"] += 1
            stats["rain_events"] += int(observed)
            stats["hits"] += int(warned and observed)
            stats["false_alarms"] += int(warned and not observed)
            stats["misses"] += int(not warned and observed)
            sums[horizon][2] += (float(forecast.rain_probability) - int(observed)) ** 2

    for horizon, stats in metrics.items():
        temp_count, rain_count = stats["temperature_samples"], stats["rain_samples"]
        if temp_count:
            stats["temperature_mae_c"] = round(sums[horizon][0] / temp_count, 3)
            stats["baseline_mae_c"] = round(sums[horizon][1] / temp_count, 3)
        if rain_count:
            stats["rain_brier"] = round(sums[horizon][2] / rain_count, 4)
    return result
