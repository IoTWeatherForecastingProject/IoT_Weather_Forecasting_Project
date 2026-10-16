"""Kết nối các hàm phân tích cảm biến với dữ liệu thuần của Backend."""

import logging
import math
import sys
from datetime import datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd
from app.services.forecast_client import AI_ENGINE_PATH

logger = logging.getLogger(__name__)

if str(AI_ENGINE_PATH) not in sys.path:
    sys.path.append(str(AI_ENGINE_PATH))

try:
    from sensor_analytics.anomaly_detector import SensorAnomalyDetector

    HAS_ANOMALY = True
except ImportError as exc:
    HAS_ANOMALY = False
    logger.warning("[ANALYTICS] Anomaly detector unavailable: %s", exc)

try:
    from openweather_benchmark.bias_analysis import align_series

    HAS_BIAS = True
except ImportError as exc:
    HAS_BIAS = False
    logger.warning("[ANALYTICS] Bias analysis unavailable: %s", exc)


def _json_value(value: Any) -> Any:
    """Đổi kiểu numpy/pandas và số không hữu hạn thành dữ liệu JSON hợp lệ."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (float, Decimal)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def sensor_health(records: list[dict]) -> dict:
    """Phân tích cửa sổ đã lọc và trả báo cáo sức khỏe dùng được trong JSON."""
    if not records:
        return {
            "status": "UNKNOWN",
            "checked_at": None,
            "anomalies": [],
            "frozen_sensors": [],
            "rain_drift": False,
            "reason": "no_data",
        }
    result = SensorAnomalyDetector.analyze(pd.DataFrame(records))
    return _json_value(
        {
            "checked_at": None,
            "frozen_sensors": [],
            "rain_drift": False,
            "reason": None,
            **result,
        }
    )


def latest_bias(
    iot_records: list[dict],
    ref_records: list[dict],
    tolerance_minutes: float = 5,
    min_samples: int = 3,
) -> dict | None:
    """Tính sai số IoT trừ tham chiếu tại mốc mới nhất có giá trị đối chuẩn."""
    if not HAS_BIAS or not iot_records or not ref_records:
        return None
    variables = ("temperature", "humidity", "pressure")
    reference = pd.DataFrame(ref_records, columns=["timestamp", *variables])
    reference["timestamp"] = pd.to_datetime(
        reference["timestamp"], utc=True, errors="coerce"
    )
    reference = reference.dropna(subset=["timestamp"])
    reference = reference.dropna(subset=list(variables), how="all")
    if reference.empty:
        return None
    reference = reference.sort_values("timestamp").tail(1)
    aligned = align_series(
        pd.DataFrame(iot_records),
        reference,
        tolerance_minutes=tolerance_minutes,
        min_samples=min_samples,
    )
    if aligned.empty:
        return None
    row = aligned.iloc[-1]
    result = {
        "reference_timestamp": row["timestamp"].isoformat(),
        "n_iot": int(row["n_iot"]),
    }
    fields = ("temp_bias_c", "hum_bias_percent", "press_bias_hpa")
    for variable, field in zip(variables, fields):
        bias = float(row[f"iot_{variable}"] - row[f"ref_{variable}"])
        result[field] = round(bias, 2) if math.isfinite(bias) else None
    return result if any(result[field] is not None for field in fields) else None
