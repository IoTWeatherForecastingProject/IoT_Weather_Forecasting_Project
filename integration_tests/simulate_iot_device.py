"""
MODULE 5: IOT HARDWARE SIMULATOR (MOCK STATION).

Giả lập trạm ESP32 phát MQTT và nhận cảnh báo hai chiều, hỗ trợ backfill SYS-02.
Worker subscribe `weather/+/data` (app/config.py), nên mỗi device_id dùng topic
`weather/<device_id>/data` riêng; payload cũng mang cùng device_id.
Hàm sinh mẫu không cần paho hay broker và không sửa state đầu vào.
"""

import argparse
import json
import logging
import math
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from threading import Event

logger = logging.getLogger("MockStation")
SCENARIOS = ("normal", "rain", "spike", "frozen", "stuck-wet", "unplugged")


def make_sample(scenario, step, state, ts) -> dict:
    """Sinh một mẫu xác định từ scenario, bước, state và thời gian; không có I/O."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    rng = random.Random(f"{state.get('seed', 0)}:{step}")
    cur_temp = state.get("temperature", 31.5)
    cur_hum = state.get("humidity", 75.0)
    cur_press = state.get("pressure", 1008.0)

    if scenario == "spike" and step % 5 == 0:
        temp, hum, press = 62.0, cur_hum, 880.0
        rain_raw, rain_detected = 2800, 0
    elif scenario == "rain" or (scenario == "spike" and state.get("simulate_rain")):
        # Giữ cả trường hợp cũ bật đồng thời hai cờ mưa và spike.
        temp = round(max(24.0, cur_temp - 0.2 * step), 2)
        hum = round(min(96.0, cur_hum + 1.5 * step), 2)
        press = round(max(998.0, cur_press - 0.4 * step), 2)
        rain_raw, rain_detected = rng.randint(700, 1100), int(step >= 3)
    else:
        temp = round(cur_temp + rng.uniform(-0.15, 0.15), 2)
        hum = round(min(100.0, max(40.0, cur_hum + rng.uniform(-0.4, 0.4))), 2)
        press = round(cur_press + rng.uniform(-0.1, 0.1), 2)
        rain_raw, rain_detected = rng.randint(2600, 2900), 0
        if scenario == "frozen":
            temp, hum, press = 29.87, 71.3, 1007.42
        elif scenario == "stuck-wet":
            hum = round(rng.uniform(50.0, 60.0), 2)
            press = round(1008.0 + rng.uniform(-0.1, 0.1), 2)
            rain_raw, rain_detected = rng.randint(800, 1000), 1
        elif scenario == "unplugged":
            temp, hum, press = None, None, None

    timestamp = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    return {
        "device_id": state.get("device_id", "station01"),
        "timestamp": timestamp.isoformat(),
        "temperature": temp,
        "humidity": hum,
        "pressure": press,
        "rain_raw": rain_raw,
        "rain_detected": rain_detected,
    }


def history_samples(scenario, minutes, interval, state, end):
    """Sinh lịch sử cách đều từ end - minutes đến end (không vượt quá end)."""
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("interval must be positive and finite")
    if not math.isfinite(minutes) or minutes < 0:
        raise ValueError("minutes must be non-negative and finite")
    start = end - timedelta(minutes=minutes)
    for index in range(int(minutes * 60 / interval) + 1):
        yield make_sample(scenario, index + 1, state, start + timedelta(seconds=index * interval))


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        topic = f"weather/{userdata['device_id']}/alert"
        client.subscribe(topic, qos=1)
        logger.info("Da ket noi MQTT Broker; subscribe %s", topic)
    else:
        logger.error("Ket noi MQTT Broker that bai! [Code: %d]", rc)
    userdata["rc"] = rc
    userdata["connected"].set()


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        logger.warning(
            "*** [MOCK STATION NHAN LENH PHAN HOI 2 CHIEU] ***\n"
            "Topic: %s | Loai: %s | Xac suat: %.2f%%\n"
            "Hanh dong phan cung: [COI BUZZER KEU BIP BIP] [LED CHOP NHAY] [OLED: %s]",
            msg.topic, payload.get("type"), payload.get("probability", 0) * 100,
            payload.get("action", {}).get("oled_message", "ALERT"),
        )
    except (UnicodeError, ValueError, TypeError, AttributeError) as exc:
        logger.error("Loi doc payload canh bao: %s", exc)


def connect_mqtt(broker, port, username, password, device_id):
    """Kết nối và chờ CONNACK trước khi cho phép publish, kể cả khi bị từ chối."""
    import paho.mqtt.client as mqtt

    userdata = {"device_id": device_id, "connected": Event(), "rc": None}
    client = mqtt.Client(client_id=f"mock_{device_id}_{time.time_ns()}", clean_session=True,
                         userdata=userdata)
    if username and password:
        client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(broker, port, keepalive=60)
        client.loop_start()
        if not userdata["connected"].wait(10) or userdata["rc"] != 0:
            raise ConnectionError(f"MQTT connection failed (rc={userdata['rc']})")
    except Exception:
        client.disconnect()
        client.loop_stop()
        raise
    return client


def publish_sample(client, sample):
    """Publish QoS 1 và chờ PUBACK; lỗi hoặc timeout không được tính là đã gửi."""
    topic = f"weather/{sample['device_id']}/data"
    info = client.publish(topic, json.dumps(sample, allow_nan=False), qos=1)
    info.wait_for_publish(timeout=10)
    if not info.is_published():
        raise TimeoutError(f"MQTT publish timed out: {topic}")


def run_simulator(broker: str, port: int, interval: float, simulate_rain: bool = False,
                  simulate_anomaly: bool = False, username: str = "weather_admin",
                  password: str = "weather_secure_pass_2026", *, scenario: str = "normal",
                  device_id: str = "station01", backfill_minutes: float = 0, count: int = 0):
    """Backfill trước rồi phát realtime; giữ nguyên tham số positional và hai cờ cũ."""
    if interval <= 0 or not math.isfinite(interval):
        raise ValueError("interval must be positive and finite")
    if backfill_minutes < 0 or not math.isfinite(backfill_minutes) or count < 0:
        raise ValueError("backfill_minutes and count must be non-negative")
    scenario = "spike" if simulate_anomaly else "rain" if simulate_rain else scenario
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    state = {"device_id": device_id, "seed": random.getrandbits(64), "simulate_rain": simulate_rain}
    client = None
    try:
        logger.info("Dang ket noi toi MQTT Broker %s:%d (User: %s)...", broker, port, username)
        client = connect_mqtt(broker, port, username, password, device_id)
        step = 0
        if backfill_minutes:
            for sample in history_samples(scenario, backfill_minutes, interval, state,
                                          datetime.now(UTC)):
                publish_sample(client, sample)
                step += 1
                time.sleep(0.005)
            logger.info("Da backfill %d mau trong %.1f phut", step, backfill_minutes)
        logger.info("Bat dau phat du lieu moi %s giay (Ctrl+C de dung)", interval)
        sent = 0
        while count == 0 or sent < count:
            step += 1
            sample = make_sample(scenario, step, state, datetime.now(UTC))
            publish_sample(client, sample)
            sent += 1
            logger.info("[MQTT PUB] weather/%s/data -> T: %s C | H: %s %% | P: %s hPa | Rain: %d",
                        device_id, sample["temperature"], sample["humidity"], sample["pressure"],
                        sample["rain_detected"])
            if count == 0 or sent < count:
                time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Dung gia lap IoT Station.")
    except Exception:
        logger.exception("Loi gia lap. Kiem tra broker va docker-compose up -d!")
        return 1
    finally:
        if client is not None:
            client.disconnect()
            client.loop_stop()
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="IoT Weather Station Hardware Simulator")
    parser.add_argument("--broker", default="localhost", help="Dia chi MQTT Broker")
    parser.add_argument("--port", type=int, default=1883, help="Cong MQTT Broker")
    parser.add_argument("--interval", type=float, default=5, help="Chu ky phat du lieu (giay)")
    parser.add_argument("--username", default="weather_admin", help="MQTT Username")
    parser.add_argument("--password", default="weather_secure_pass_2026", help="MQTT Password")
    parser.add_argument("--simulate-rain", action="store_true", help="Bi danh cua --scenario rain")
    parser.add_argument("--simulate-anomaly", action="store_true", help="Bi danh cua --scenario spike")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--device-id", default="station01")
    parser.add_argument("--backfill-minutes", type=float, default=0)
    parser.add_argument("--count", type=int, default=0, help="So mau realtime; 0 = chay vo han")
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be positive and finite")
    if not math.isfinite(args.backfill_minutes) or args.backfill_minutes < 0 or args.count < 0:
        parser.error("--backfill-minutes and --count must be non-negative")
    if not args.device_id.strip() or len(args.device_id) > 50 or any(c in args.device_id for c in "/+#"):
        parser.error("--device-id must be 1-50 characters without /, + or #")
    return run_simulator(**vars(args))


if __name__ == "__main__":
    sys.exit(main())
