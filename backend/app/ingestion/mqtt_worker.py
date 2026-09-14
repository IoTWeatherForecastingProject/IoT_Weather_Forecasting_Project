import json
import logging
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from app.config import settings
from app.db.session import get_db_context
from app.db.models import WeatherMeasurement

logger = logging.getLogger(__name__)


class MQTTIngestionWorker:
    def __init__(self, broadcast_callback=None):
        self.broadcast_callback = broadcast_callback
        self.client = mqtt.Client(client_id=settings.MQTT_CLIENT_ID, clean_session=True)
        if settings.MQTT_USERNAME and settings.MQTT_PASSWORD:
            self.client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
        
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("[MQTT WORKER] Ket noi MQTT Broker thanh cong! Code: %d", rc)
            client.subscribe(settings.MQTT_DATA_TOPIC, qos=1)
            logger.info("[MQTT WORKER] Da subscribe topic: %s", settings.MQTT_DATA_TOPIC)
        else:
            logger.error("[MQTT WORKER] Ket noi MQTT that bai! Return code: %d", rc)

    def _on_disconnect(self, client, userdata, rc):
        logger.warning("[MQTT WORKER] Mat ket noi voi MQTT Broker! Dang thu ket noi lai... Code: %d", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode("utf-8")
            data = json.loads(payload_str)
            logger.debug("[MQTT WORKER] Nhan du lieu tu [%s]: %s", msg.topic, payload_str)

            # Validate các trường tối thiểu
            device_id = data.get("device_id", "unknown_station")
            temp = float(data.get("temperature", 0.0))
            hum = float(data.get("humidity", 0.0))
            press = float(data.get("pressure", 0.0))
            rain_raw = data.get("rain_raw")
            rain_detected = int(data.get("rain_detected", 0))

            # Lưu vào PostgreSQL an toàn theo luồng (Thread-safe)
            try:
                with get_db_context() as db:
                    record = WeatherMeasurement(
                        device_id=device_id,
                        timestamp=datetime.now(timezone.utc),
                        temperature=temp,
                        humidity=hum,
                        pressure=press,
                        rain_raw=rain_raw,
                        rain_detected=rain_detected
                    )
                    db.add(record)
            except Exception as dbe:
                logger.error("[MQTT WORKER] Loi ghi DB: %s", dbe)

            # Bắn broadcast tới WebSocket client
            if self.broadcast_callback:
                clean_payload = {
                    "device_id": device_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "temperature": temp,
                    "humidity": hum,
                    "pressure": press,
                    "rain_raw": rain_raw,
                    "rain_detected": rain_detected
                }
                self.broadcast_callback(clean_payload)

        except Exception as e:
            logger.error("[MQTT WORKER] Loi xu ly message MQTT: %s", e)

    def start(self):
        try:
            logger.info("[MQTT WORKER] Dang khoi dong MQTT client ket noi toi %s:%d", 
                        settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT)
            self.client.connect_async(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            logger.error("[MQTT WORKER] Khong the khoi dong MQTT Worker: %s", e)

    def stop(self):
        logger.info("[MQTT WORKER] Dang dung MQTT client loop...")
        self.client.loop_stop()
        self.client.disconnect()

