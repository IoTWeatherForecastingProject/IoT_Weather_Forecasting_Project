"""Pure TV3 provider checks retained alongside TV1 isolated API tests."""
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from app.services import analytics_client

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

def test_bias_available_without_requests() -> None:
    """Khi chỉ cài dependencies backend (không có requests) bias vẫn khả dụng."""
    code = (
        "import sys; sys.modules['requests'] = None; "
        "from app.services import analytics_client; "
        "assert analytics_client.HAS_BIAS and analytics_client.HAS_ANOMALY"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
