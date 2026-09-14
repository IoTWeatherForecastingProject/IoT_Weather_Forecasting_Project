import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Optional, Dict, Any

import paho.mqtt.client as mqtt

from app.config import settings
from app.db.session import get_db_context
from app.db.models import WeatherMeasurement

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
        """
        Khử trùng và kiểm tra tính hợp lệ dữ liệu cảm biến:
        - Bắt lỗi JSON parsing
        - Kiểm tra các ngưỡng vật lý (-40°C đến 85°C, 0-100% độ ẩm, 800-1200 hPa)
        - Chuẩn hóa Timestamp UTC
        """
        try:
            payload_str = payload_bytes.decode("utf-8")
            data = json.loads(payload_str)
        except Exception as e:
            logger.error("[MQTT WORKER] Payload khong phai JSON hop le: %s", e)
            return None

        if not isinstance(data, dict):
            logger.error("[MQTT WORKER] Payload khong phai dictionary: %s", type(data))
            return None

        # 1. Device ID
        device_id = str(data.get("device_id", "station01")).strip()[:50]
        if not device_id:
            device_id = "station01"

        # 2. Temperature (-40 đến 85 °C)
        try:
            temp = float(data.get("temperature", 0.0))
            if temp < -40.0 or temp > 85.0:
                logger.warning("[MQTT WORKER] Nhiet do bat thuong: %.2f°C cho trạm %s", temp, device_id)
        except (ValueError, TypeError):
            logger.warning("[MQTT WORKER] Loi gia tri nhiet do, fallback ve 0.0: %s", data.get("temperature"))
            temp = 0.0

        # 3. Humidity (0 đến 100%)
        try:
            hum = float(data.get("humidity", 0.0))
            if hum < 0.0 or hum > 100.0:
                logger.warning("[MQTT WORKER] Do am bat thuong: %.2f%% cho trạm %s (clamp ve 0-100)", hum, device_id)
                hum = max(0.0, min(100.0, hum))
        except (ValueError, TypeError):
            hum = 0.0

        # 4. Pressure (800 đến 1200 hPa)
        try:
            press = float(data.get("pressure", 1013.25))
            if press < 800.0 or press > 1200.0:
                logger.warning("[MQTT WORKER] Ap suat bat thuong: %.2f hPa cho trạm %s", press, device_id)
        except (ValueError, TypeError):
            press = 1013.25

        # 5. Rain values
        rain_raw = data.get("rain_raw")
        if rain_raw is not None:
            try:
                rain_raw = int(rain_raw)
            except (ValueError, TypeError):
                rain_raw = None

        rain_detected = 1 if int(data.get("rain_detected", 0)) else 0

        # 6. Timestamp chuẩn hóa UTC
        record_time = None
        raw_ts = data.get("timestamp")
        if raw_ts:
            try:
                parsed_dt = datetime.fromisoformat(str(raw_ts))
                if parsed_dt.tzinfo is None:
                    record_time = parsed_dt.replace(tzinfo=timezone.utc)
                else:
                    record_time = parsed_dt.astimezone(timezone.utc)
            except Exception:
                record_time = None

        if record_time is None:
            record_time = datetime.now(timezone.utc)

        return {
            "device_id": device_id,
            "timestamp": record_time,
            "temperature": round(temp, 2),
            "humidity": round(hum, 2),
            "pressure": round(press, 2),
            "rain_raw": rain_raw,
            "rain_detected": rain_detected
        }

    def _on_message(self, client, userdata, msg):
        try:
            clean_data = self._parse_and_validate_payload(msg.payload)
            if not clean_data:
                return

            logger.debug("[MQTT WORKER] Nhan packet tu [%s]: %s", msg.topic, clean_data)

            # Lưu vào PostgreSQL an toàn theo luồng (Thread-safe context manager)
            try:
                with get_db_context() as db:
                    record = WeatherMeasurement(
                        device_id=clean_data["device_id"],
                        timestamp=clean_data["timestamp"],
                        temperature=Decimal(str(clean_data["temperature"])),
                        humidity=Decimal(str(clean_data["humidity"])),
                        pressure=Decimal(str(clean_data["pressure"])),
                        rain_raw=clean_data["rain_raw"],
                        rain_detected=clean_data["rain_detected"]
                    )
                    db.add(record)
            except Exception as dbe:
                logger.error("[MQTT WORKER] Loi ghi CSDL cho packet tu '%s': %s", clean_data["device_id"], dbe)

            # Bắn broadcast tới WebSocket client
            if self.broadcast_callback:
                try:
                    broadcast_payload = {
                        "device_id": clean_data["device_id"],
                        "timestamp": clean_data["timestamp"].isoformat(),
                        "temperature": clean_data["temperature"],
                        "humidity": clean_data["humidity"],
                        "pressure": clean_data["pressure"],
                        "rain_raw": clean_data["rain_raw"],
                        "rain_detected": clean_data["rain_detected"]
                    }
                    self.broadcast_callback(broadcast_payload)
                except Exception as bce:
                    logger.warning("[MQTT WORKER] Callback broadcast sinh loi: %s", bce)

        except Exception as e:
            logger.error("[MQTT WORKER] Ngoai le khong mong muon khi xu ly message: %s", e)

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
