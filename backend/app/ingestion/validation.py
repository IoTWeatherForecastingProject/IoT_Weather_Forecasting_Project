"""Telemetry v1: reject malformed data, preserve finite anomalies for diagnostics."""
from datetime import datetime, timedelta, timezone
import hashlib
import math
import re


def parse_telemetry(data: dict, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    device = data.get("device_id")
    if not isinstance(device, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", device):
        raise ValueError("invalid_device_id")
    clean = {"device_id": device}
    for field, limit in (("temperature", 999.99), ("humidity", 999.99), ("pressure", 9999.99)):
        value = data.get(field)
        if value is None or isinstance(value, bool):
            raise ValueError(f"invalid_{field}")
        value = float(value)
        if not math.isfinite(value) or abs(value) > limit:
            raise ValueError(f"invalid_{field}")
        clean[field] = round(value, 2)
    rain = data.get("rain_detected")
    if rain not in (0, 1, "0", "1"):
        raise ValueError("invalid_rain_detected")
    clean["rain_detected"] = int(rain)
    raw = data.get("rain_raw")
    if raw is not None:
        if isinstance(raw, bool) or not math.isfinite(float(raw)) or float(raw) != int(raw) or not 0 <= int(raw) <= 4095:
            raise ValueError("invalid_rain_raw")
        raw = int(raw)
    clean["rain_raw"] = raw
    clean["message_key"] = None
    if "timestamp" in data:
        value = data["timestamp"]
        if not isinstance(value, str):
            raise ValueError("invalid_timestamp")
        measured_at = datetime.fromisoformat(value)
        if measured_at.tzinfo is None:
            raise ValueError("timestamp_timezone_required")
        measured_at = measured_at.astimezone(timezone.utc)
        if measured_at > now + timedelta(seconds=5):
            raise ValueError("future_timestamp")
        identity = f"{device}\0{measured_at.isoformat()}".encode()
        clean["message_key"] = hashlib.sha256(identity).hexdigest()
    else:
        measured_at = now
    clean["timestamp"] = measured_at
    return clean


def usable_measurement(row) -> bool:
    return (-40 <= float(row.temperature) <= 85 and 0 <= float(row.humidity) <= 100
            and 300 <= float(row.pressure) <= 1100)
