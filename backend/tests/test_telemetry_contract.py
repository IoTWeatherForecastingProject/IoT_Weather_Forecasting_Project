from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

from app.db.models import WeatherMeasurement
from app.db.session import get_db_context
from app.ingestion.validation import parse_telemetry
from app.ingestion import mqtt_worker
from app.ingestion.mqtt_worker import MQTTIngestionWorker
from app.config import settings

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
VALID = {"device_id": "contract", "temperature": 31.5, "humidity": 75,
         "pressure": 1008, "rain_raw": 750, "rain_detected": 0}


@pytest.mark.parametrize("field", ["device_id", "temperature", "humidity", "pressure", "rain_detected"])
def test_required_fields_cannot_be_fabricated(field):
    data = dict(VALID)
    data.pop(field)
    with pytest.raises((ValueError, TypeError)):
        parse_telemetry(data, now=NOW)


@pytest.mark.parametrize("field,value", [
    ("temperature", None), ("temperature", True), ("humidity", "broken"),
    ("pressure", float("nan")), ("pressure", float("inf")), ("pressure", 10000),
    ("rain_detected", 0.5), ("rain_detected", 2), ("rain_raw", -1),
    ("rain_raw", 4096), ("rain_raw", 4.2), ("device_id", "bad/id"),
    ("timestamp", None), ("timestamp", "bad"), ("timestamp", "2026-10-27T12:00:00"),
    ("timestamp", (NOW + timedelta(seconds=6)).isoformat()),
])
def test_invalid_values_are_rejected(field, value):
    with pytest.raises((ValueError, TypeError)):
        parse_telemetry({**VALID, field: value}, now=NOW)


def test_timestamp_normalization_and_identity():
    utc = parse_telemetry({**VALID, "timestamp": "2026-10-27T12:00:00Z"}, now=NOW)
    local = parse_telemetry({**VALID, "timestamp": "2026-10-27T19:00:00+07:00"}, now=NOW)
    assert utc["message_key"] == local["message_key"]
    assert utc["timestamp"] == NOW
    uptime = parse_telemetry({**VALID, "timestamp_ms": 15000}, now=NOW)
    assert uptime["timestamp"] == NOW and uptime["message_key"] is None


def test_finite_anomalies_remain_visible():
    result = parse_telemetry({**VALID, "temperature": 95, "humidity": 125}, now=NOW)
    assert result["temperature"] == 95 and result["humidity"] == 125


def test_database_failure_does_not_broadcast(monkeypatch):
    broadcast = Mock()
    worker = MQTTIngestionWorker(broadcast_callback=broadcast)
    connection = Mock(side_effect=RuntimeError("db offline"))
    monkeypatch.setattr(mqtt_worker, "get_db_context", connection)
    worker._on_message(None, None, SimpleNamespace(topic=f"{settings.MQTT_TOPIC_PREFIX}/contract/data", payload=json.dumps(VALID).encode()))
    connection.assert_called_once()
    broadcast.assert_not_called()


def test_topic_device_mismatch_does_not_write(monkeypatch):
    connect = Mock()
    monkeypatch.setattr(mqtt_worker, "get_db_context", connect)
    MQTTIngestionWorker()._on_message(None, None, SimpleNamespace(
        topic=f"{settings.MQTT_TOPIC_PREFIX}/other/data", payload=json.dumps(VALID).encode()))
    connect.assert_not_called()


def test_repeated_utc_sample_is_committed_and_broadcast_once():
    device = "test_identity_" + uuid.uuid4().hex[:10]
    data = {**VALID, "device_id": device, "timestamp": datetime.now(timezone.utc).isoformat()}
    msg = SimpleNamespace(topic=f"{settings.MQTT_TOPIC_PREFIX}/{device}/data", payload=json.dumps(data).encode(), mid=1, dup=False)
    broadcast = Mock()
    worker = MQTTIngestionWorker(broadcast_callback=broadcast)
    try:
        worker._on_message(None, None, msg)
        worker._on_message(None, None, msg)
        # Deduplication survives a new worker, independently of the packet cache.
        MQTTIngestionWorker(broadcast_callback=broadcast)._on_message(None, None, msg)
        with get_db_context() as db:
            assert db.query(WeatherMeasurement).filter_by(device_id=device).count() == 1
        broadcast.assert_called_once()
    finally:
        with get_db_context() as db:
            db.query(WeatherMeasurement).filter_by(device_id=device).delete()
