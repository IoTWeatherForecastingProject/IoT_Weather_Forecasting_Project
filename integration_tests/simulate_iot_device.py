"""
==============================================================================
MODULE 5: IOT HARDWARE SIMULATOR (MOCK STATION)
Giả lập trạm đo ESP32/ESP8266 phát dữ liệu qua MQTT và nhận cảnh báo 2 chiều
Dành cho kiểm thử hệ thống không cần thiết bị phần cứng thật.
==============================================================================
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("MockStation")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Da ket noi toi MQTT Broker thanh cong! [Code: %d]", rc)
        client.subscribe("weather/station01/alert", qos=1)
        logger.info("Da subscribe topic nhan lenh phan hoi: weather/station01/alert")
    else:
        logger.error("Ket noi MQTT Broker that bai! [Code: %d]", rc)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        logger.warning(
            "*** [MOCK STATION NHAN LENH PHAN HOI 2 CHIEU] ***\n"
            "Topic: %s | Loai: %s | Xac suat: %.2f%%\n"
            "Hanh dong phan cung: [COI BUZZER KEU BIP BIP] [LED CHOP NHAY] [OLED: %s]",
            msg.topic,
            payload.get("type"),
            payload.get("probability", 0) * 100,
            payload.get("action", {}).get("oled_message", "ALERT")
        )
    except Exception as e:
        logger.error("Loi doc payload canh bao: %s", e)


def run_simulator(broker: str, port: int, interval: int, simulate_rain: bool, simulate_anomaly: bool,
                  username: str = "weather_admin", password: str = "weather_secure_pass_2026"):
    client = mqtt.Client(client_id="mock_esp_weather_station", clean_session=True)
    if username and password:
        client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_message = on_message

    logger.info("Dang ket noi toi MQTT Broker %s:%d (User: %s)...", broker, port, username)
    try:
        client.connect(broker, port, keepalive=60)
        client.loop_start()
    except Exception as e:
        logger.error("Khong the ket noi toi Broker: %s. Hay dam bao docker-compose up -d da chay!", e)
        return

    # Gia tri khoi tao
    cur_temp = 31.5
    cur_hum = 75.0
    cur_press = 1008.0
    step = 0

    logger.info("Bat dau phat stream du lieu cam bien moi %d giay... (Nhan Ctrl+C de dung)", interval)
    try:
        while True:
            step += 1

            if simulate_anomaly and step % 5 == 0:
                # Tao spike dot bien nhiet do bat thuong 60°C de test Anomaly Detector
                temp = 62.0
                hum = cur_hum
                press = 880.0
                rain_raw = 2800
                rain_detected = 0
                logger.warning(">>> BAN DU LIEU ANOMALY / SPIKE (Temp: 62°C, Press: 880 hPa)")
            elif simulate_rain:
                # Mo phong mua: Nhiet do tut, do am tang vot, ap suat ha nhanh
                temp = round(max(24.0, cur_temp - 0.2 * step), 2)
                hum = round(min(96.0, cur_hum + 1.5 * step), 2)
                press = round(max(998.0, cur_press - 0.4 * step), 2)
                rain_raw = random.randint(700, 1100)
                rain_detected = 1 if step >= 3 else 0
            else:
                # Dao dong tu nhien binh thuong
                temp = round(cur_temp + random.uniform(-0.15, 0.15), 2)
                hum = round(min(100.0, max(40.0, cur_hum + random.uniform(-0.4, 0.4))), 2)
                press = round(cur_press + random.uniform(-0.1, 0.1), 2)
                rain_raw = random.randint(2600, 2900)
                rain_detected = 0

            payload = {
                "device_id": "station01",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "temperature": temp,
                "humidity": hum,
                "pressure": press,
                "rain_raw": rain_raw,
                "rain_detected": rain_detected
            }

            client.publish("weather/station01/data", json.dumps(payload), qos=1)
            logger.info("[MQTT PUB] weather/station01/data -> T: %.1f°C | H: %.1f%% | P: %.1f hPa | Rain: %d",
                        temp, hum, press, rain_detected)

            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("Dung gia lap IoT Station.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IoT Weather Station Hardware Simulator")
    parser.add_argument("--broker", default="localhost", help="Dia chi MQTT Broker")
    parser.add_argument("--port", type=int, default=1883, help="Cong MQTT Broker")
    parser.add_argument("--interval", type=int, default=5, help="Chu ky phat du lieu (giay)")
    parser.add_argument("--username", default="weather_admin", help="MQTT Username")
    parser.add_argument("--password", default="weather_secure_pass_2026", help="MQTT Password")
    parser.add_argument("--simulate-rain", action="store_true", help="Kich hoat kich ban mua dong tut ap")
    parser.add_argument("--simulate-anomaly", action="store_true", help="Kich hoat loi dot bien cam bien (Spike)")

    args = parser.parse_args()
    run_simulator(args.broker, args.port, args.interval, args.simulate_rain, args.simulate_anomaly,
                  args.username, args.password)

