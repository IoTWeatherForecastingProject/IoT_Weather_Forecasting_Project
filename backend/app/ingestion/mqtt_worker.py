import json
import logging
import hashlib
from collections import OrderedDict
from sqlalchemy.dialects.postgresql import insert
from typing import Callable, Optional, Dict, Any

import paho.mqtt.client as mqtt

from app.config import settings
from app.db.session import get_db_context
from app.db.models import WeatherMeasurement
from app.ingestion.validation import parse_telemetry

logger = logging.getLogger("weather_backend.mqtt_worker")

# Định nghĩa các mã phản hồi kết nối MQTT v3.1.1
MQTT_RC_CODES = {
    0: "Connection accepted",
    1: "Connection refused: unacceptable protocol version",
    2: "Connection refused: identifier rejected",
    3: "Connection refused: server unavailable",
    4: "Connection refused: bad user name or password",
    5: "Connection refused: not authorized",
}


class MQTTIngestionWorker:
    """
    Worker chạy ngầm tiếp nhận dòng dữ liệu (stream) từ các trạm quan trắc IoT:
    - Xác thực bảo mật MQTT (Username/Password)
    - Tự động kết nối lại (Auto-reconnect với Exponential Backoff 1-30s)
    - Khử trùng và chuẩn hóa dữ liệu cảm biến (Validation & Sanitization)
    - Chuẩn hóa Timestamp UTC ISO-8601
    - Ghi vào CSDL PostgreSQL an toàn đa luồng (Thread-safe session pool)
    - Kích hoạt callback phát broadcast WebSocket thời gian thực
    """

    def __init__(self, broadcast_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.broadcast_callback = broadcast_callback
        self.client = mqtt.Client(
            client_id=settings.MQTT_CLIENT_ID,
            clean_session=True
        )

        # Cấu hình chứng thực
        if settings.MQTT_USERNAME and settings.MQTT_PASSWORD:
            self.client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

        # Cấu hình Exponential Backoff cho auto-reconnect: 1s -> 30s
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        # Đăng ký callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        self._is_running = False
        self._recent_packets = OrderedDict()

    @property
    def is_connected(self) -> bool:
        """Kiểm tra trạng thái kết nối socket với MQTT Broker."""
        return self.client.is_connected()

    def _on_connect(self, client, userdata, flags, rc):
        status_msg = MQTT_RC_CODES.get(rc, f"Unknown code {rc}")
        if rc == 0:
            logger.info("[MQTT WORKER] Ket noi MQTT Broker thanh cong! [%s]", status_msg)
            client.subscribe(settings.MQTT_DATA_TOPIC, qos=settings.MQTT_QOS)
            logger.info("[MQTT WORKER] Da dang ky theo doi topic: '%s' (QoS %d)",
                        settings.MQTT_DATA_TOPIC, settings.MQTT_QOS)
        else:
            logger.error("[MQTT WORKER] Ket noi MQTT Broker bi tu choi! Code %d: %s", rc, status_msg)

    def _on_disconnect(self, client, userdata, rc):
        if rc == 0:
            logger.info("[MQTT WORKER] Ngat ket noi chu dong voi MQTT Broker thanh cong.")
        else:
            logger.warning(
                "[MQTT WORKER] Mat ket noi voi MQTT Broker ngoai y muon! Code %d. Client dang tu dong ket noi lai...",
                rc
            )

    @staticmethod
    def _parse_and_validate_payload(payload_bytes: bytes) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(payload_bytes.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("payload_must_be_object")
            return parse_telemetry(data)
        except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
            logger.warning("[MQTT WORKER] Bo mau khong hop le: %s", exc)
            return None

    def _on_message(self, client, userdata, msg):
        clean_data = self._parse_and_validate_payload(msg.payload)
        if clean_data is None:
            return
        expected = f"{settings.MQTT_TOPIC_PREFIX}/{clean_data['device_id']}/data"
        if msg.topic != expected:
            logger.warning("[MQTT WORKER] Topic khong khop device_id")
            return
        packet = (msg.topic, getattr(msg, "mid", None), hashlib.sha256(msg.payload).digest())
        if getattr(msg, "dup", False) and packet in self._recent_packets:
            return
        try:
            with get_db_context() as db:
                statement = insert(WeatherMeasurement).values(**clean_data).on_conflict_do_nothing(
                    index_elements=["message_key"]
                ).returning(WeatherMeasurement.id)
                inserted = db.execute(statement).scalar_one_or_none()
            if inserted is None:
                return
        except Exception:
            logger.exception("[MQTT WORKER] Khong luu duoc mau; khong phat WebSocket")
            return
        self._recent_packets[packet] = None
        self._recent_packets.move_to_end(packet)
        if len(self._recent_packets) > 1024:
            self._recent_packets.popitem(last=False)
        if self.broadcast_callback:
            payload = {key: value for key, value in clean_data.items() if key != "message_key"}
            payload["timestamp"] = payload["timestamp"].isoformat()
            try:
                self.broadcast_callback(payload)
            except Exception:
                logger.exception("[MQTT WORKER] Callback WebSocket that bai")

    def start(self):
        try:
            logger.info("[MQTT WORKER] Dang khoi dong MQTT client ket noi toi %s:%d (Client ID: %s)",
                        settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, settings.MQTT_CLIENT_ID)
            self.client.connect_async(
                settings.MQTT_BROKER_HOST,
                settings.MQTT_BROKER_PORT,
                keepalive=settings.MQTT_KEEPALIVE
            )
            self.client.loop_start()
            self._is_running = True
        except Exception as e:
            logger.error("[MQTT WORKER] Khong the khoi dong MQTT Worker: %s", e)

    def stop(self):
        logger.info("[MQTT WORKER] Dang dung MQTT client loop...")
        self._is_running = False
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("[MQTT WORKER] Da dung MQTT Worker hoan tat.")
