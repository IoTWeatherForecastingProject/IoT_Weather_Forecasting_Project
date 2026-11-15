import json
import logging
import math
import threading
import time
from datetime import datetime, timezone
import httpx
import paho.mqtt.client as mqtt
from app.config import settings
from app.db.session import get_db_context
from app.db.models import AlertLog

logger = logging.getLogger(__name__)


class AlertService:
    # One uvicorn process: serialize each device across API and monitor threads.
    # Channel-specific cooldowns let a failed channel retry without spamming the other.
    _lock = threading.Lock()
    _in_flight: set[str] = set()
    _last_sent: dict[tuple[str, str], float] = {}

    @classmethod
    def evaluate_and_trigger(
        cls,
        device_id: str,
        rain_probability: float,
        horizon_minutes: int,
        mqtt_client=None,
        threshold: float = None
    ) -> bool:
        """Đánh giá xác suất mưa và kích hoạt vòng lặp điều khiển phản hồi 2 chiều nếu vượt ngưỡng."""
        if threshold is None:
            threshold = settings.RAIN_ALERT_THRESHOLD

        if (not math.isfinite(rain_probability) or not math.isfinite(threshold)
                or not 0 <= rain_probability <= 1 or not 0 <= threshold <= 1
                or rain_probability < threshold):
            return False
        if not device_id or any(char in device_id for char in ("/", "+", "#", "\x00")):
            logger.error("[ALERT ENGINE] Device ID khong hop le cho MQTT topic")
            return False

        telegram_enabled = bool(settings.ENABLE_TELEGRAM_NOTIFICATIONS
                                and settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
        now = time.monotonic()
        with cls._lock:
            if device_id in cls._in_flight:
                return False
            mqtt_due = now - cls._last_sent.get((device_id, "mqtt"), -math.inf) >= settings.ALERT_COOLDOWN_SECONDS
            telegram_due = telegram_enabled and (
                now - cls._last_sent.get((device_id, "telegram"), -math.inf) >= settings.ALERT_COOLDOWN_SECONDS
            )
            if not mqtt_due and not telegram_due:
                return False
            cls._in_flight.add(device_id)

        try:
            mqtt_sent = False
            telegram_sent = False
            mqtt_status = "cooldown" if not mqtt_due else "unavailable"
            telegram_status = "disabled" if not telegram_enabled else "cooldown"
            if mqtt_due and mqtt_client is not None and mqtt_client.is_connected():
                mqtt_sent = cls._publish_alert(mqtt_client, device_id, rain_probability, horizon_minutes)
                mqtt_status = "acknowledged" if mqtt_sent else "failed"
            if telegram_due:
                telegram_sent = cls._send_telegram_alert(device_id, rain_probability, horizon_minutes)
                telegram_status = "sent" if telegram_sent else "failed"

            with cls._lock:
                if mqtt_sent:
                    cls._last_sent[(device_id, "mqtt")] = time.monotonic()
                if telegram_sent:
                    cls._last_sent[(device_id, "telegram")] = time.monotonic()
            cls._log_alert_to_db(
                device_id=device_id, rain_prob=rain_probability, threshold=threshold,
                mqtt_sent=mqtt_sent, telegram_sent=telegram_sent,
                notes=f"+{horizon_minutes}m; mqtt={mqtt_status}; telegram={telegram_status}",
            )
            return mqtt_sent or telegram_sent
        finally:
            with cls._lock:
                cls._in_flight.discard(device_id)

    @staticmethod
    def _publish_alert(mqtt_client, device_id, rain_probability, horizon_minutes) -> bool:
        # Recognize the old default in existing .env files while routing every station correctly.
        template = settings.MQTT_ALERT_TOPIC
        if template == "weather/station01/alert":
            template = "weather/{device_id}/alert"
        topic = template.replace("{device_id}", device_id)
        alert_payload = {
            "type": "rain_warning",
            "device_id": device_id,
            "probability": round(rain_probability, 4),
            "forecast_minutes": horizon_minutes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": {
                "buzzer": True,
                "led_blink": True,
                "oled_message": f"MUA (+{horizon_minutes}m: {int(rain_probability * 100)}%)"
            }
        }
        try:
            info = mqtt_client.publish(topic, json.dumps(alert_payload), qos=1, retain=False)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.warning("[ALERT ENGINE] Publish bi tu choi: rc=%s", info.rc)
                return False
            info.wait_for_publish(timeout=settings.ALERT_MQTT_ACK_TIMEOUT_SECONDS)
            if not info.is_published():
                logger.warning("[ALERT ENGINE] Het thoi gian cho PUBACK: %s", topic)
                return False
            logger.info("[ALERT ENGINE] Broker da ACK canh bao: %s", topic)
            return True
        except Exception as exc:
            logger.error("[ALERT ENGINE] Publish that bai: %s", type(exc).__name__)
            return False

    @staticmethod
    def _send_telegram_alert(device_id: str, rain_prob: float, horizon_minutes: int) -> bool:
        """Gửi thông báo cảnh báo thời tiết tới Telegram."""
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        message_text = (
            f"⚠️ *CẢNH BÁO MƯA CỤC BỘ (IOT WEATHER)* ⚠️\n\n"
            f"📍 *Trạm đo:* `{device_id}`\n"
            f"🌧 *Xác suất mưa:* `{rain_prob * 100:.1f}%`\n"
            f"⏱ *Khung thời gian:* `+{horizon_minutes} phút tới`\n"
            f"🔔 Hãy kiểm tra thời tiết tại trạm. Trạng thái gửi lệnh MQTT được ghi trong nhật ký hệ thống."
        )
        payload = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": message_text,
            "parse_mode": "Markdown"
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.post(url, json=payload)
                return res.status_code == 200 and res.json().get("ok") is True
        except Exception as e:
            # HTTP exceptions may contain the bot token in their URL.
            logger.error("[ALERT ENGINE] Loi gui tin nhan Telegram: %s", type(e).__name__)
            return False

    @staticmethod
    def _log_alert_to_db(device_id: str, rain_prob: float, threshold: float, mqtt_sent: bool, telegram_sent: bool, notes: str):
        try:
            with get_db_context() as db:
                log = AlertLog(
                    device_id=device_id,
                    alert_type="rain_warning",
                    rain_probability=rain_prob,
                    threshold=threshold,
                    mqtt_sent=mqtt_sent,
                    telegram_sent=telegram_sent,
                    notes=notes
                )
                db.add(log)
        except Exception as e:
            logger.error("[ALERT ENGINE] Khong the ghi alert log vao DB: %s", e)

