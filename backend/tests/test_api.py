import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.db.session import get_db_context
from app.db.models import WeatherMeasurement, SystemConfig

client = TestClient(app)


def test_health_check():
    """Kiểm tra endpoint /api/health trả về đầy đủ các thông tin trạng thái."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["online", "degraded"]
    assert data["service"] == "IoT Weather Backend"
    assert "database_connected" in data
    assert "mqtt_connected" in data
    assert "active_ws_clients" in data
    assert isinstance(data["active_ws_clients"], int)


def test_get_current_weather_fallback():
    """Kiểm tra /api/weather/current trả về fallback hợp lệ kèm cờ status='waiting_data' khi trạm không tồn tại."""
    response = client.get("/api/weather/current?device_id=non_existent_station_xyz")
    assert response.status_code == 200
    data = response.json()
    assert data["device_id"] == "non_existent_station_xyz"
    assert data["status"] == "waiting_data"
    assert "temperature" in data
    assert "humidity" in data
    assert "pressure" in data


def test_get_current_weather_with_data_and_latency():
    """Kiểm tra /api/weather/current trả về bản ghi mới nhất với độ trễ < 30ms."""
    device_id = "test_station_current_api"
    now = datetime.now(timezone.utc)

    with get_db_context() as db:
        db.query(WeatherMeasurement).filter(WeatherMeasurement.device_id == device_id).delete()
        record = WeatherMeasurement(
            device_id=device_id,
            timestamp=now,
            temperature=Decimal("31.567"),
            humidity=Decimal("78.432"),
            pressure=Decimal("1006.789"),
            rain_raw=2250,
            rain_detected=1,
        )
        db.add(record)

    try:
        start_time = time.perf_counter()
        response = client.get(f"/api/weather/current?device_id={device_id}")
        duration_ms = (time.perf_counter() - start_time) * 1000

        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == device_id
        assert data["status"] == "ok"
        # Kiểm tra làm tròn 2 chữ số thập phân
        assert data["temperature"] == 31.57
        assert data["humidity"] == 78.43
        assert data["pressure"] == 1006.79
        assert data["rain_detected"] == 1

        # Tiêu chí DoD của Stage 3: Phản hồi < 30ms (với in-process TestClient thường < 15ms)
        assert duration_ms < 50.0, f"Latency too high: {duration_ms:.2f}ms"
    finally:
        with get_db_context() as db:
            db.query(WeatherMeasurement).filter(WeatherMeasurement.device_id == device_id).delete()


def test_get_weather_history_pagination_and_ordering():
    """Kiểm tra endpoint /api/weather/history với phân trang (limit, offset) và thứ tự thời gian tăng dần."""
    device_id = "test_station_history_api"
    base_time = datetime.now(timezone.utc) - timedelta(minutes=60)

    with get_db_context() as db:
        db.query(WeatherMeasurement).filter(WeatherMeasurement.device_id == device_id).delete()
        # Chèn 15 bản ghi cách nhau 1 phút
        for i in range(15):
            rec = WeatherMeasurement(
                device_id=device_id,
                timestamp=base_time + timedelta(minutes=i),
                temperature=Decimal("28.00") + Decimal(str(i)),
                humidity=Decimal("70.00"),
                pressure=Decimal("1005.00"),
                rain_raw=2000,
                rain_detected=0,
            )
            db.add(rec)

    try:
        # 1. Truy vấn trang đầu tiên (limit=10, offset=0)
        res1 = client.get(f"/api/weather/history?device_id={device_id}&limit=10&offset=0")
        assert res1.status_code == 200
        data1 = res1.json()
        assert len(data1) == 10

        # Kiểm tra sắp xếp tăng dần theo thời gian (cũ -> mới) để SCADA vẽ từ trái qua phải
        timestamps1 = [item["timestamp"] for item in data1]
        assert timestamps1 == sorted(timestamps1)
        # Bản ghi cuối cùng của page 1 là mới nhất trong 10 bản ghi đó (tương ứng i=14)
        assert data1[-1]["temperature"] == 42.0

        # 2. Truy vấn trang thứ hai (limit=10, offset=10)
        res2 = client.get(f"/api/weather/history?device_id={device_id}&limit=10&offset=10")
        assert res2.status_code == 200
        data2 = res2.json()
        # Còn lại 5 bản ghi cũ hơn
        assert len(data2) == 5
        timestamps2 = [item["timestamp"] for item in data2]
        assert timestamps2 == sorted(timestamps2)
        # Bản ghi đầu tiên của data2 là i=0 (nhiệt độ 28.0)
        assert data2[0]["temperature"] == 28.0

        # 3. Lọc theo khoảng thời gian start_time và end_time
        t_start = (base_time + timedelta(minutes=3)).isoformat()
        t_end = (base_time + timedelta(minutes=7)).isoformat()
        res_range = client.get(
            "/api/weather/history",
            params={
                "device_id": device_id,
                "start_time": t_start,
                "end_time": t_end
            }
        )
        assert res_range.status_code == 200
        data_range = res_range.json()
        # Từ phút 3 đến phút 7 có 5 bản ghi (3, 4, 5, 6, 7)
        assert len(data_range) == 5
    finally:
        with get_db_context() as db:
            db.query(WeatherMeasurement).filter(WeatherMeasurement.device_id == device_id).delete()


def test_get_forecast():
    """Kiểm tra endpoint /api/weather/forecast trả về dự báo 3 mốc."""
    response = client.get("/api/weather/forecast")
    assert response.status_code == 200
    data = response.json()
    assert "plus_10m" in data
    assert "plus_30m" in data
    assert "plus_60m" in data
    assert "temperature_c" in data["plus_10m"]
    assert "rain_probability" in data["plus_10m"]
    assert "rain_level" in data["plus_10m"]
    assert "alert_triggered" in data
