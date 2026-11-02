"""SYS-02: script kiểm thử MQTT -> worker -> sensor-health, không phải pytest.

Cần broker, PostgreSQL và backend đang chạy. Mỗi lần chạy dùng trạm riêng;
báo cáo chỉ phản ánh dữ liệu tổng hợp từ simulator, không phải đo phần cứng.
"""

import argparse
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from simulate_iot_device import (
    connect_mqtt,
    history_samples,
    make_sample,
    publish_sample,
)

SCENARIOS = ("normal", "spike", "frozen", "stuck-wet", "unplugged", "offline")
CASES = {
    "normal": (40, 60, "40 phut binh thuong", "OK, khong anomaly"),
    "spike": (10, 60, "10 phut binh thuong + 62 C / 880 hPa", "FAULT, OUT_OF_RANGE"),
    "frozen": (35, 60, "35 phut BME280 giu nguyen gia tri", "WARNING, frozen temperature/pressure"),
    "stuck-wet": (370, 400, "370 phut mua ket uot, do am kho", "WARNING, rain_drift=true"),
    "unplugged": (5, 60, "5 phut binh thuong + BME280 null", "FAULT, OUT_OF_RANGE"),
    "offline": (30, 60, "30 phut binh thuong, dung tu 20 phut truoc", "FAULT, STALE_DATA"),
}
DEFAULT_REPORT = Path(__file__).resolve().parents[1] / "docs/reports/sys02_sensor_fault_results.md"
logger = logging.getLogger(__name__)


def scenario_samples(scenario, now, device_id):
    """Dùng chu kỳ 10 giây, phủ đủ cửa sổ frozen 30 phút và drift 360 phút."""
    minutes = CASES[scenario][0]
    state = {"device_id": device_id, "seed": 2}
    end = now - timedelta(minutes=20) if scenario == "offline" else now
    if scenario in ("spike", "unplugged"):
        end -= timedelta(seconds=10)
    history_scenario = scenario if scenario in ("frozen", "stuck-wet") else "normal"
    samples = list(history_samples(history_scenario, minutes, 10, state, end))
    if scenario in ("spike", "unplugged"):
        # Spike ở bước thứ 5 là 62°C/880 hPa theo hành vi cờ cũ của simulator.
        samples.append(make_sample(scenario, 5, state, now))
    return samples


def matches_expectation(scenario, data):
    """Đánh giá sau khi API đã thấy đủ các bản ghi được publish."""
    kinds = {a["type"] for a in data.get("anomalies", [])}
    if scenario == "normal":
        return data.get("status") == "OK" and data.get("anomalies") == []
    if scenario == "frozen":
        return (data.get("status") == "WARNING"
                and {"temperature", "pressure"}.issubset(data.get("frozen_sensors", [])))
    if scenario == "stuck-wet":
        return data.get("status") == "WARNING" and data.get("rain_drift") is True
    expected = "STALE_DATA" if scenario == "offline" else "OUT_OF_RANGE"
    return data.get("status") == "FAULT" and expected in kinds


def poll_health(http, device_id, window_minutes, expected_count, timeout=30):
    """Poll tối đa 30 giây; chưa đủ mẫu thì không kết luận về detector."""
    import httpx

    deadline = time.monotonic() + timeout
    last_detail = "No response"
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            response = http.get("/api/weather/sensor-health", params={
                "device_id": device_id, "window_minutes": window_minutes,
            }, timeout=min(5, max(0.01, remaining)))
            response.raise_for_status()
            data = response.json()
            received = data.get("n_records", 0)
            if received >= expected_count:
                return data
            last_detail = f"n_records={received}/{expected_count}"
        except (httpx.HTTPError, ValueError) as exc:
            last_detail = str(exc)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.5, remaining))
    raise TimeoutError(f"Ingestion/API timeout after {timeout}s: {last_detail}")


def run_case(scenario, args, http, epoch):
    """Đo từ trước publish đến khi API thấy đủ dữ liệu và trả kết quả đánh giá."""
    device_id = f"sys02-{scenario}-{epoch}"
    started = time.monotonic()
    mqtt_client = None
    data_description, expected = CASES[scenario][2:]
    passed = False
    actual = ""
    try:
        mqtt_client = connect_mqtt(args.broker, args.port, args.username, args.password, device_id)
        samples = scenario_samples(scenario, datetime.now(UTC), device_id)
        print(f"[{scenario}] Publish {len(samples)} mau -> weather/{device_id}/data", flush=True)
        for sample in samples:
            publish_sample(mqtt_client, sample)
            time.sleep(0.005)
        data = poll_health(http, device_id, CASES[scenario][1], len(samples))
        passed = matches_expectation(scenario, data)
        kinds = sorted({a["type"] for a in data.get("anomalies", [])})
        actual = (f"{data.get('status')}; anomalies={','.join(kinds) or 'none'}; "
                  f"frozen={','.join(data.get('frozen_sensors', [])) or 'none'}; "
                  f"rain_drift={data.get('rain_drift')}; n_records={data.get('n_records')}")
    except Exception as exc:
        logger.exception("Kich ban %s khong hoan tat", scenario)
        actual = f"{type(exc).__name__}: {exc}"
    finally:
        if mqtt_client is not None:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
    elapsed = time.monotonic() - started
    print(f"[{scenario}] {'PASS' if passed else 'FAIL'} ({elapsed:.2f}s): {actual}", flush=True)
    return {
        "scenario": scenario, "device_id": device_id, "data": data_description,
        "expected": expected, "actual": actual, "passed": passed, "elapsed": elapsed,
    }


def write_report(path, results, started_at):
    """Ghi bảng Markdown; giữ cả các lỗi kết nối để không nhầm với kết quả PASS."""
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

    lines = [
        "# SYS-02 — Kết quả kiểm thử chịu lỗi cảm biến", "",
        f"Thời gian chạy (UTC): {started_at.isoformat()}", "",
        "Ghi chú: dữ liệu tổng hợp từ simulator; không phải kết quả đo phần cứng thật.",
        ("Thời gian phát hiện tính từ trước kết nối/publish đến lúc API có đủ mẫu; "
         "poll sau publish tối đa 30 giây."), "",
        "| Kịch bản | Dữ liệu | Kỳ vọng | Thực tế | PASS/FAIL | Thời gian |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        cells = [result["scenario"], result["data"], result["expected"], result["actual"],
                 "PASS" if result["passed"] else "FAIL", f"{result['elapsed']:.2f} s"]
        lines.append("| " + " | ".join(cell(value) for value in cells) + " |")
    lines.extend(["", "Mã trạm riêng cho lần chạy:", ""])
    lines.extend(f"- `{result['device_id']}`" for result in results)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    import httpx

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="SYS-02 sensor fault tolerance (requires running services)")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--username", default="weather_admin")
    parser.add_argument("--password", default="weather_secure_pass_2026")
    parser.add_argument("--only", choices=SCENARIOS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    started_at = datetime.now(UTC)
    # Epoch nano giây tránh trùng dữ liệu khi chạy lại nhiều lần trong cùng giây.
    epoch = time.time_ns()
    scenarios = (args.only,) if args.only else SCENARIOS
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=5.0) as http:
        results = [run_case(scenario, args, http, epoch) for scenario in scenarios]
    print(f"\n{'Kich ban':<14}{'Ket qua':<10}{'Phat hien (s)':<16}Thuc te")
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{result['scenario']:<14}{status:<10}{result['elapsed']:<16.2f}{result['actual']}")
    write_report(args.report, results, started_at)
    print(f"Bao cao: {args.report}")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
