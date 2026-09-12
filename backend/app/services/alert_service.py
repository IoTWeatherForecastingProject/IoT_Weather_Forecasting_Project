import json
import logging
from datetime import datetime, timezone
import httpx
from app.config import settings
from app.db.session import SessionLocal
from app.db.models import AlertLog

logger = logging.getLogger(__name__)


class AlertService:
    @staticmethod
    def evaluate_and_trigger(
        device_id: str,
        rain_probability: float,
        horizon_minutes: int,
        mqtt_client=None,
        threshold: float = None
    ) -> bool:
        """Đánh giá xác suất mưa và kích hoạt vòng lặp điều khiển phản hồi 2 chiều nếu vượt ngưỡng."""
        if threshold is None:
            threshold = settings.RAIN_ALERT_THRESHOLD

        if rain_probability < threshold:
            return False

        logger.warning(
            "[ALERT ENGINE] Xac suat mua %.2f%% vuot nguong %.2f%% tai moc +%dm! Kich hoat phan hoi 2 chieu.",
            rain_probability * 100, threshold * 100, horizon_minutes
        )

        mqtt_sent = False
        telegram_sent = False

        # 1. Bắn lệnh MQTT xuống trạm IoT
        if mqtt_client and mqtt_client.is_connected():
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
                mqtt_client.publish(
                    settings.MQTT_ALERT_TOPIC,
                    json.dumps(alert_payload),
                    qos=1
                )
                mqtt_sent = True
                logger.info("[ALERT ENGINE] Da publish lenh canh bao toi MQTT topic: %s", settings.MQTT_ALERT_TOPIC)
            except Exception as e:
                logger.error("[ALERT ENGINE] Loi khi publish MQTT alert: %s", e)

        # 2. Gửi thông báo Telegram Bot
        if settings.ENABLE_TELEGRAM_NOTIFICATIONS and settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
            telegram_sent = AlertService._send_telegram_alert(device_id, rain_probability, horizon_minutes)

        # 3. Ghi log cảnh báo vào CSDL
        AlertService._log_alert_to_db(
            device_id=device_id,
            rain_prob=rain_probability,
            threshold=threshold,
            mqtt_sent=mqtt_sent,
            telegram_sent=telegram_sent,
            notes=f"Kich hoat tai moc +{horizon_minutes} phut"
        )

        return True

    @staticmethod
    def _send_telegram_alert(device_id: str, rain_prob: float, horizon_minutes: int) -> bool:
        """Gửi thông báo cảnh báo thời tiết tới Telegram."""
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        message_text = (
            f"⚠️ *CẢNH BÁO MƯA CỤC BỘ (IOT WEATHER)* ⚠️\n\n"
            f"📍 *Trạm đo:* `{device_id}`\n"
            f"🌧 *Xác suất mưa:* `{rain_prob * 100:.1f}%`\n"
            f"⏱ *Khung thời gian:* `+{horizon_minutes} phút tới`\n"
            f"🔔 *Hành động:* Trạm IoT đã tự động kích hoạt còi và đèn cảnh báo ngoài trời."
        )
        payload = {
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": message_text,
            "parse_mode": "Markdown"
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.post(url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.error("[ALERT ENGINE] Loi gui tin nhan Telegram: %s", e)
            return False

    @staticmethod
    def _log_alert_to_db(device_id: str, rain_prob: float, threshold: float, mqtt_sent: bool, telegram_sent: bool, notes: str):
        if SessionLocal is None:
            return
        try:
            db = SessionLocal()
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
            db.commit()
            db.close()
        except Exception as e:
            logger.error("[ALERT ENGINE] Khong the ghi alert log vao DB: %s", e)

