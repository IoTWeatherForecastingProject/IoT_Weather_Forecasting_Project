"""Summarize recorded wet periods for the last seven local calendar days."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import WeatherMeasurement

VIETNAM_TIME = timezone(timedelta(hours=7))
MAX_SAMPLE_GAP = timedelta(seconds=30)


def rain_history(db: Session, device_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(VIETNAM_TIME).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (today - timedelta(days=6)).astimezone(timezone.utc)
    station = db.query(
        WeatherMeasurement.timestamp,
        WeatherMeasurement.rain_detected,
        WeatherMeasurement.temperature,
        WeatherMeasurement.humidity,
        WeatherMeasurement.pressure,
    ).filter(WeatherMeasurement.device_id == device_id)
    previous = station.filter(
        WeatherMeasurement.timestamp >= start - MAX_SAMPLE_GAP,
        WeatherMeasurement.timestamp < start,
    ).order_by(WeatherMeasurement.timestamp.desc(), WeatherMeasurement.id.desc()).first()
    readings = station.filter(
        WeatherMeasurement.timestamp >= start,
        WeatherMeasurement.timestamp <= now,
    ).order_by(WeatherMeasurement.timestamp, WeatherMeasurement.id).yield_per(1000)

    def utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    days = {}
    active = None
    has_readings = False
    for reading in readings:
        timestamp = utc(reading.timestamp)
        wet = reading.rain_detected
        has_readings |= wet in (0, 1)
        if active and (timestamp - active["last_wet_at"] > MAX_SAMPLE_GAP or wet not in (0, 1)):
            active = None
        if wet == 1:
            if active is None:
                day = timestamp.astimezone(VIETNAM_TIME).date().isoformat()
                active = {
                    "first_wet_at": timestamp,
                    "last_wet_at": timestamp,
                    "dry_at": None,
                    "status": "unknown_end",
                    "confirmed_start": (
                        previous is not None and previous.rain_detected == 0
                        and timestamp - utc(previous.timestamp) <= MAX_SAMPLE_GAP
                    ),
                    "temperature": float(reading.temperature),
                    "humidity": float(reading.humidity),
                    "pressure": float(reading.pressure),
                }
                days.setdefault(day, []).append(active)
            active["last_wet_at"] = timestamp
        elif wet == 0 and active:
            active["dry_at"] = timestamp
            active["status"] = "dry"
            active = None
        previous = reading

    if active and now - active["last_wet_at"] <= MAX_SAMPLE_GAP:
        active["status"] = "wet"
    return {
        "has_readings": has_readings,
        "days": [{"date": day, "events": list(reversed(events))}
                 for day, events in reversed(days.items())],
    }
