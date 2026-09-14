import json
import time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
import pytest

from app.config import settings
from app.db.session import get_db_context
from app.db.models import WeatherMeasurement
from app.ingestion.mqtt_worker import MQTTIngestionWorker


def test_mqtt_broker_rejects_anonymous():
    """Kiểm tra Broker từ chối kết nối ẩn danh (allow_anonymous false)."""
    rc_result = []

    def on_connect(client, userdata, flags, rc):
        rc_result.append(rc)

    client = mqtt.Client(client_id="test_anon_client")
    client.on_connect = on_connect
    client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=10)
    client.loop(timeout=2)
    client.disconnect()

    assert len(rc_result) > 0
    # rc=5 là Connection refused: not authorized
    assert rc_result[0] in [4, 5]


def test_mqtt_broker_accepts_valid_credentials():
    """Kiểm tra Broker chấp nhận kết nối khi cung cấp user/pass chính xác."""
    rc_result = []

    def on_connect(client, userdata, flags, rc):
        rc_result.append(rc)

    client = mqtt.Client(client_id="test_auth_client")
    client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
    client.on_connect = on_connect
    client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=10)
    client.loop(timeout=2)
    client.disconnect()

    assert len(rc_result) > 0
    assert rc_result[0] == 0


def test_mqtt_worker_payload_validation():
    """Kiểm tra logic parse và validate dữ liệu cảm biến của worker."""
    # 1. Payload hợp lệ
    valid_payload = json.dumps({
        "device_id": "station_valid",
        "temperature": 32.5,
        "humidity": 78.2,
        "pressure": 1008.5,
        "rain_raw": 2400,
        "rain_detected": 1
    }).encode("utf-8")

    data = MQTTIngestionWorker._parse_and_validate_payload(valid_payload)
    assert data is not None
    assert data["device_id"] == "station_valid"
    assert data["temperature"] == 32.5
    assert data["humidity"] == 78.2
    assert data["pressure"] == 1008.5
    assert data["rain_detected"] == 1
    assert data["timestamp"].tzinfo is not None

    # 2. Payload rác / không phải JSON
    bad_payload = b"not a json string at all"
    data = MQTTIngestionWorker._parse_and_validate_payload(bad_payload)
    assert data is None

    # 3. Payload có giá trị bất thường (clamp độ ẩm > 100%)
    extreme_payload = json.dumps({
        "device_id": "station_extreme",
        "temperature": 95.0,  # Vượt ngưỡng bình thường nhưng vẫn ép kiểu float
        "humidity": 125.0,    # Sẽ được clamp về 100.0%
        "pressure": "invalid_press"  # Fallback về mặc định
    }).encode("utf-8")

    data = MQTTIngestionWorker._parse_and_validate_payload(extreme_payload)
    assert data is not None
    assert data["humidity"] == 100.0
    assert data["pressure"] == 1013.25


def test_mqtt_worker_db_ingestion():
    """Kiểm tra MQTT worker ghi nhận dữ liệu vào CSDL PostgreSQL và gọi broadcast callback."""
    received_broadcast = []

    def mock_broadcast(payload):
        received_broadcast.append(payload)

    worker = MQTTIngestionWorker(broadcast_callback=mock_broadcast)
    test_device_id = "test_ingestion_station"

    payload_dict = {
        "device_id": test_device_id,
        "temperature": 29.8,
        "humidity": 65.5,
        "pressure": 1009.2,
        "rain_raw": 2800,
        "rain_detected": 0
    }

    # Tạo mock MQTT message
    class MockMsg:
        topic = "weather/station01/data"
        payload = json.dumps(payload_dict).encode("utf-8")

    # Gọi trực tiếp handler _on_message
    worker._on_message(None, None, MockMsg())

    # Kiểm tra callback broadcast đã được kích hoạt
    assert len(received_broadcast) == 1
    assert received_broadcast[0]["device_id"] == test_device_id
    assert received_broadcast[0]["temperature"] == 29.8

    # Kiểm tra CSDL đã có bản ghi
    with get_db_context() as db:
        record = (
            db.query(WeatherMeasurement)
            .filter(WeatherMeasurement.device_id == test_device_id)
            .order_by(WeatherMeasurement.timestamp.desc())
            .first()
        )
        assert record is not None
        assert float(record.temperature) == 29.8
        assert float(record.humidity) == 65.5

        # Cleanup dữ liệu test
        db.query(WeatherMeasurement).filter(WeatherMeasurement.device_id == test_device_id).delete()
