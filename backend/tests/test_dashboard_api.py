"""Kiểm thử API Dashboard với PostgreSQL thật và dữ liệu tổng hợp độc lập."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from app.api import endpoints
from app.config import settings
from app.db.models import ReferenceWeather, SystemConfig, WeatherMeasurement
from app.db.session import get_db, get_db_context
from app.main import app
from app.services import analytics_client, forecast_client
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

client = TestClient(app)
API = "/api/weather"


@pytest.fixture
def dashboard_data() -> Iterator[tuple[str, str, str]]:
    """Cấp mã test riêng và luôn dọn đúng các bản ghi thuộc test đó."""
    suffix = uuid4().hex[:10]
    device_id = f"test_dash_{suffix}"
    source = f"test_dash_ref_{suffix}"
    other_source = f"test_dash_alt_{suffix}"
    try:
        yield device_id, source, other_source
    finally:
        with get_db_context() as db:
            db.query(WeatherMeasurement).filter(
                WeatherMeasurement.device_id == device_id
            ).delete()
            db.query(ReferenceWeather).filter(
                ReferenceWeather.source.in_([source, other_source])
            ).delete()


@pytest.fixture
def preserved_threshold() -> Iterator[None]:
    """Sao lưu và phục hồi nguyên giá trị cùng updated_at dù test thất bại."""
    key = "rain_alert_threshold"
    with get_db_context() as db:
        config = db.get(SystemConfig, key)
        backup = (
            {
                "config_key": key,
                "config_value": config.config_value,
                "updated_at": config.updated_at,
            }
            if config is not None
            else None
        )
    try:
        with get_db_context() as db:
            db.query(SystemConfig).filter(SystemConfig.config_key == key).delete()
        yield
    finally:
        with get_db_context() as db:
            db.query(SystemConfig).filter(SystemConfig.config_key == key).delete()
            if backup is not None:
                db.add(SystemConfig(**backup))


def _add_iot(
    device_id: str,
    timestamps: list[datetime],
    temperature: float = 31.5,
    vary: bool = False,
) -> None:
    """Chèn dữ liệu tổng hợp, có thể dao động nhẹ để tránh kẹt giả."""
    with get_db_context() as db:
        for index, timestamp in enumerate(timestamps):
            delta = index * 0.01 if vary else 0
            db.add(
                WeatherMeasurement(
                    device_id=device_id,
                    timestamp=timestamp,
                    temperature=temperature + delta,
                    humidity=75 + delta,
                    pressure=1008 + delta,
                    rain_raw=2800,
                    rain_detected=0,
                )
            )


def _add_reference(
    source: str,
    timestamp: datetime,
    temperature: float | None = 30.0,
    humidity: float | None = 75.0,
    pressure: float | None = 1008.0,
) -> None:
    """Chèn một mốc tham chiếu riêng cho test, giữ nguyên các biến NULL."""
    with get_db_context() as db:
        db.add(
            ReferenceWeather(
                source=source,
                timestamp=timestamp,
                lat=10.8,
                lon=106.7,
                temperature=temperature,
                humidity=humidity,
                pressure=pressure,
            )
        )


def test_threshold_default_then_post(preserved_threshold: None) -> None:
    """Đọc mặc định khi thiếu cấu hình và đọc lại giá trị được POST lưu."""
    response = client.get(f"{API}/alerts/threshold")
    assert response.status_code == 200
    assert response.json() == {
        "threshold": settings.RAIN_ALERT_THRESHOLD,
        "source": "default",
        "updated_at": None,
    }
    saved = client.post(f"{API}/alerts/threshold", json={"threshold": 0.6})
    assert saved.status_code == 200
    response = client.get(f"{API}/alerts/threshold")
    assert response.status_code == 200
    assert response.json()["threshold"] == 0.6
    assert response.json()["source"] == "db"
    assert response.json()["updated_at"] is not None


@pytest.mark.parametrize("value", ["invalid", "NaN", "Infinity"])
def test_threshold_invalid_uses_default(
    preserved_threshold: None, value: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Cấu hình không hợp lệ dùng mặc định và ghi cảnh báo không dấu."""
    with get_db_context() as db:
        db.add(SystemConfig(config_key="rain_alert_threshold", config_value=value))
    response = client.get(f"{API}/alerts/threshold")
    assert response.status_code == 200
    assert response.json()["source"] == "default"
    assert response.json()["threshold"] == settings.RAIN_ALERT_THRESHOLD
    assert response.json()["updated_at"] is None
    assert "Invalid rain_alert_threshold" in caplog.text


def test_sensor_health_no_data(dashboard_data: tuple[str, str, str]) -> None:
    """Không có dữ liệu trả UNKNOWN cùng các trường mặc định đầy đủ."""
    device_id, _, _ = dashboard_data
    response = client.get(f"{API}/sensor-health", params={"device_id": device_id})
    assert response.status_code == 200
    assert response.json() == {
        "device_id": device_id,
        "status": "UNKNOWN",
        "checked_at": None,
        "window_minutes": 360,
        "n_records": 0,
        "anomalies": [],
        "frozen_sensors": [],
        "rain_drift": False,
        "reason": "no_data",
    }


def test_sensor_health_normal(dashboard_data: tuple[str, str, str]) -> None:
    """Ba mươi phút dữ liệu tổng hợp dao động bình thường trả OK."""
    device_id, _, _ = dashboard_data
    now = datetime.now(UTC) - timedelta(seconds=1)
    timestamps = [now - timedelta(minutes=index) for index in range(30, -1, -1)]
    _add_iot(device_id, list(reversed(timestamps)), vary=True)
    response = client.get(f"{API}/sensor-health", params={"device_id": device_id})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "OK"
    assert data["n_records"] == 31
    assert data["anomalies"] == []
    assert datetime.fromisoformat(data["checked_at"]) == now


def test_sensor_health_latest_fault(dashboard_data: tuple[str, str, str]) -> None:
    """Nhiệt độ 120°C ở bản ghi mới nhất trả FAULT và giữ chi tiết value."""
    device_id, _, _ = dashboard_data
    now = datetime.now(UTC)
    _add_iot(device_id, [now - timedelta(minutes=1)])
    _add_iot(device_id, [now], temperature=120)
    response = client.get(f"{API}/sensor-health", params={"device_id": device_id})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "FAULT"
    assert any(
        anomaly["type"] == "OUT_OF_RANGE"
        and anomaly["sensor"] == "temperature"
        and anomaly["value"] == 120
        for anomaly in data["anomalies"]
    )


def test_sensor_health_time_window(dashboard_data: tuple[str, str, str]) -> None:
    """Bỏ bản ghi ngoài cửa sổ bằng timestamp dù trạm có rất ít bản ghi."""
    device_id, _, _ = dashboard_data
    now = datetime.now(UTC)
    _add_iot(device_id, [now - timedelta(minutes=31)], temperature=120)
    _add_iot(device_id, [now - timedelta(minutes=1), now], vary=True)
    response = client.get(
        f"{API}/sensor-health",
        params={
            "device_id": device_id,
            "window_minutes": 30,
        },
    )
    assert response.status_code == 200
    assert response.json()["n_records"] == 2
    assert response.json()["status"] == "OK"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"device_id": ""},
        {"device_id": "test_dash_invalid", "window_minutes": 5},
        {"device_id": "test_dash_invalid", "window_minutes": 1441},
    ],
)
def test_sensor_health_validation(params: dict) -> None:
    """Thiếu mã trạm hoặc cửa sổ ngoài giới hạn trả 422."""
    assert client.get(f"{API}/sensor-health", params=params).status_code == 422


def test_sensor_health_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bộ phát hiện không import được trả lỗi 503 đúng contract."""
    monkeypatch.setattr(analytics_client, "HAS_ANOMALY", False)
    response = client.get(f"{API}/sensor-health", params={"device_id": "test_dash_off"})
    assert response.status_code == 503
    assert response.json()["detail"] == "anomaly detector unavailable"


def test_sensor_health_json_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """Giữ field phụ, đổi numpy/pandas, NaN và vô cực sang JSON thuần."""
    result = {
        "status": "WARNING",
        "checked_at": pd.Timestamp("2026-10-16T00:00:00Z"),
        "anomalies": [
            {
                "type": "CUSTOM",
                "sensor": "temperature",
                "message": "test",
                "value": np.float64(1.5),
                "samples": np.int64(3),
                "details": [np.bool_(True), np.nan, np.inf, pd.NA, pd.NaT],
            }
        ],
        "rain_drift": np.bool_(False),
        "frozen_sensors": [],
    }
    monkeypatch.setattr(
        analytics_client.SensorAnomalyDetector, "analyze", lambda frame: result
    )
    report = analytics_client.sensor_health([{"timestamp": datetime.now(UTC)}])
    json.dumps(report, allow_nan=False)
    assert report["anomalies"][0]["details"] == [True, None, None, None, None]
    assert type(report["anomalies"][0]["samples"]) is int
    assert type(report["rain_drift"]) is bool


def test_benchmark_no_reference(dashboard_data: tuple[str, str, str]) -> None:
    """Nguồn chưa có tham chiếu trả chuỗi rỗng và sai số null."""
    device_id, source, _ = dashboard_data
    response = client.get(
        f"{API}/benchmark", params={"device_id": device_id, "source": source}
    )
    assert response.status_code == 200
    assert response.json() == {
        "device_id": device_id,
        "source": source,
        "hours": 24,
        "reference": [],
        "latest_bias": None,
    }


def test_benchmark_bias_and_inclusive_tolerance(
    dashboard_data: tuple[str, str, str],
) -> None:
    """Ghép năm mẫu trong khoảng đóng ±5 phút và loại mẫu ngoài khoảng."""
    device_id, source, _ = dashboard_data
    now = datetime.now(UTC) - timedelta(minutes=6)
    _add_reference(source, now)
    _add_iot(
        device_id, [now + timedelta(minutes=offset) for offset in (-5, -2, 0, 2, 5)]
    )
    _add_iot(device_id, [now - timedelta(minutes=6)], temperature=50)
    response = client.get(
        f"{API}/benchmark", params={"device_id": device_id, "source": source}
    )
    assert response.status_code == 200
    bias = response.json()["latest_bias"]
    assert bias["temp_bias_c"] == pytest.approx(1.5)
    assert bias["hum_bias_percent"] == 0
    assert bias["press_bias_hpa"] == 0
    assert bias["n_iot"] == 5
    assert datetime.fromisoformat(bias["reference_timestamp"]) == now


def test_benchmark_two_samples(dashboard_data: tuple[str, str, str]) -> None:
    """Hai mẫu không đủ ghép bất kỳ biến nào nên latest_bias là null."""
    device_id, source, _ = dashboard_data
    now = datetime.now(UTC)
    _add_reference(source, now)
    _add_iot(device_id, [now - timedelta(minutes=1), now])
    response = client.get(
        f"{API}/benchmark", params={"device_id": device_id, "source": source}
    )
    assert response.status_code == 200
    assert response.json()["latest_bias"] is None


def test_latest_bias_minimum_per_variable() -> None:
    """Biến chỉ có hai mẫu là None dù biến khác có đủ ba mẫu để ghép."""
    now = datetime.now(UTC)
    iot = [
        {
            "timestamp": now + timedelta(seconds=index),
            "temperature": 31.5 if index < 2 else None,
            "humidity": 76,
            "pressure": 1007,
        }
        for index in range(3)
    ]
    reference = [
        {"timestamp": now, "temperature": 30, "humidity": 75, "pressure": None}
    ]
    bias = analytics_client.latest_bias(iot, reference)
    assert bias is not None
    assert bias["temp_bias_c"] is None
    assert bias["hum_bias_percent"] == 1
    assert bias["press_bias_hpa"] is None
    assert bias["n_iot"] == 3


def test_benchmark_source_window_and_order(
    dashboard_data: tuple[str, str, str],
) -> None:
    """Lọc đúng source và timestamp; giữ NULL, sắp xếp tham chiếu tăng dần."""
    device_id, source, other_source = dashboard_data
    now = datetime.now(UTC)
    _add_reference(source, now)
    _add_reference(source, now - timedelta(minutes=20), humidity=None)
    _add_reference(source, now - timedelta(hours=2))
    _add_reference(other_source, now, temperature=40)
    response = client.get(
        f"{API}/benchmark",
        params={
            "device_id": device_id,
            "source": source,
            "hours": 1,
        },
    )
    assert response.status_code == 200
    reference = response.json()["reference"]
    assert len(reference) == 2
    assert [row["timestamp"] for row in reference] == sorted(
        row["timestamp"] for row in reference
    )
    assert all(row["temperature"] == 30 for row in reference)
    assert reference[0]["humidity"] is None


def test_benchmark_latest_non_null_reference(
    dashboard_data: tuple[str, str, str],
) -> None:
    """Bỏ mốc mới nhất toàn NULL khi chọn mốc tính bias, vẫn giữ trên series."""
    device_id, source, _ = dashboard_data
    now = datetime.now(UTC)
    valid_time = now - timedelta(minutes=10)
    _add_reference(source, valid_time)
    _add_reference(source, now, temperature=None, humidity=None, pressure=None)
    _add_iot(device_id, [valid_time - timedelta(minutes=index) for index in range(3)])
    response = client.get(
        f"{API}/benchmark", params={"device_id": device_id, "source": source}
    )
    assert response.status_code == 200
    assert len(response.json()["reference"]) == 2
    assert (
        datetime.fromisoformat(response.json()["latest_bias"]["reference_timestamp"])
        == valid_time
    )


def test_benchmark_does_not_fall_back_to_older_match(
    dashboard_data: tuple[str, str, str],
) -> None:
    """Mốc mới nhất không có IoT thì bias null dù mốc cũ ghép được."""
    device_id, source, _ = dashboard_data
    now = datetime.now(UTC)
    older = now - timedelta(minutes=20)
    _add_reference(source, older)
    _add_reference(source, now)
    _add_iot(device_id, [older - timedelta(minutes=index) for index in range(3)])
    response = client.get(
        f"{API}/benchmark", params={"device_id": device_id, "source": source}
    )
    assert response.status_code == 200
    assert response.json()["latest_bias"] is None


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"device_id": ""},
        {"device_id": "test_dash_invalid", "hours": 0},
        {"device_id": "test_dash_invalid", "hours": 169},
        {"device_id": "test_dash_invalid", "source": "x" * 31},
    ],
)
def test_benchmark_validation(params: dict) -> None:
    """Kiểm tra giới hạn mã trạm, nguồn và cửa sổ tham chiếu."""
    assert client.get(f"{API}/benchmark", params=params).status_code == 422


def test_benchmark_unavailable_bias(
    dashboard_data: tuple[str, str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Thiếu thư viện bias vẫn trả series tham chiếu và ghi cảnh báo."""
    device_id, source, _ = dashboard_data
    _add_reference(source, datetime.now(UTC))
    monkeypatch.setattr(analytics_client, "HAS_BIAS", False)
    response = client.get(
        f"{API}/benchmark", params={"device_id": device_id, "source": source}
    )
    assert response.status_code == 200
    assert len(response.json()["reference"]) == 1
    assert response.json()["latest_bias"] is None
    assert "Bias analysis unavailable" in caplog.text


@pytest.mark.parametrize("sqlstate", ["42P01", "42703"])
@pytest.mark.parametrize("code_attribute", ["sqlstate", "pgcode"])
def test_benchmark_programming_error(sqlstate: str, code_attribute: str) -> None:
    """Kiểm tra rollback và mã lỗi của cả psycopg3 lẫn psycopg2."""
    db = MagicMock()
    original = MagicMock(spec=[code_attribute], **{code_attribute: sqlstate})
    error = ProgrammingError("SELECT reference_weather", {}, original)
    db.query.side_effect = error
    app.dependency_overrides[get_db] = lambda: db
    try:
        if sqlstate == "42P01":
            response = client.get(
                f"{API}/benchmark", params={"device_id": "test_dash_missing"}
            )
            assert response.status_code == 503
            assert (
                response.json()["detail"]
                == "reference_weather table missing - run migration 002"
            )
        else:
            with pytest.raises(ProgrammingError):
                client.get(
                    f"{API}/benchmark", params={"device_id": "test_dash_missing"}
                )
        db.rollback.assert_called_once()
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_real_driver_missing_table_sqlstate() -> None:
    """Driver thật trả mã 42P01 khi SELECT bảng không tồn tại, rồi rollback."""
    table_name = f"test_dash_missing_{uuid4().hex}"
    with pytest.raises(ProgrammingError) as exc_info, get_db_context() as db:
        db.execute(text(f"SELECT * FROM {table_name}"))
    original = exc_info.value.orig
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    assert code == "42P01"


@pytest.mark.parametrize("rain_source", ["model", "heuristic"])
def test_forecast_preserves_rain_source(
    dashboard_data: tuple[str, str, str],
    monkeypatch: pytest.MonkeyPatch,
    rain_source: str,
) -> None:
    """Mock predict_forecast và kiểm tra cả ba horizon giữ rain_source."""
    device_id, _, _ = dashboard_data
    forecast = {
        "device_id": device_id,
        "generated_at": datetime.now(UTC),
        "current_temperature": 30,
        "current_humidity": 75,
        "current_pressure": 1008,
        "alert_triggered": False,
        "alert_message": None,
        **{
            f"plus_{minutes}m": {
                "temperature_c": 30,
                "rain_probability": 0.1,
                "rain_level": "Low",
                "rain_source": rain_source,
            }
            for minutes in (10, 30, 60)
        },
    }
    monkeypatch.setattr(forecast_client, "HAS_AI_ENGINE", True)
    predictor = MagicMock(return_value=forecast)
    monkeypatch.setattr(
        forecast_client, "ai_predict_forecast", predictor, raising=False
    )
    monkeypatch.setattr(
        endpoints.AlertService, "evaluate_and_trigger", lambda **kwargs: None
    )
    response = client.get(f"{API}/forecast", params={"device_id": device_id})
    assert response.status_code == 200
    predictor.assert_called_once()
    for minutes in (10, 30, 60):
        assert response.json()[f"plus_{minutes}m"]["rain_source"] == rain_source
