"""
==============================================================================
MODULE 4: PHÁT HIỆN DỊ THƯỜNG VÀ TRÔI CẢM BIẾN (SENSOR ANOMALY & DRIFT)
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-03 (TASK.md)
==============================================================================

Ba nhóm lỗi phần cứng được phát hiện:

1. Bản ghi đơn lẻ (`check_measurement`):
   - MISSING_VALUE: thiếu trường / None / không phải số / NaN.
   - OUT_OF_RANGE: vượt giới hạn vật lý hợp lý.
   - SPIKE: tốc độ thay đổi so với bản ghi trước vượt ngưỡng. Tốc độ tính theo
     khoảng thời gian thực giữa 2 bản ghi, với mẫu số tối thiểu 1 phút để nhiễu
     đo ở chu kỳ 5–10 s không bị khuếch đại thành spike giả.
2. Giá trị bị kẹt (`detect_frozen_values`): BME280 trả về cùng một giá trị
   tuyệt đối trong suốt cửa sổ thời gian (treo I2C, đọc lại buffer cũ).
3. Cảm biến mưa đọng nước (`detect_rain_sensor_drift`): báo ướt liên tục quá
   lâu trong khi độ ẩm đã thấp và áp suất không giảm.

Mọi cửa sổ đều tính theo THỜI GIAN (cột `timestamp`), không theo số dòng,
vì chu kỳ gửi của trạm có thể thay đổi (5–10 s) và có thể mất mẫu.
"""

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

SENSOR_FIELDS = ("temperature", "humidity", "pressure")
UNITS = {"temperature": "°C", "humidity": "%", "pressure": "hPa"}


@dataclass(frozen=True)
class AnomalyConfig:
    # Giới hạn vật lý bình thường tại Việt Nam (áp suất tại trạm, không quy về mực nước biển)
    temp_min: float = 5.0
    temp_max: float = 55.0
    hum_min: float = 10.0
    hum_max: float = 100.0
    press_min: float = 950.0
    press_max: float = 1050.0

    # Ngưỡng tốc độ thay đổi tối đa (đơn vị / phút)
    max_temp_rate_per_min: float = 3.0
    max_hum_rate_per_min: float = 10.0
    max_press_rate_per_min: float = 4.0
    # Khoảng cách 2 bản ghi lớn hơn mức này là mất dữ liệu, không xét spike
    max_gap_minutes: float = 10.0

    # Frozen value: giá trị không đổi (max - min <= tolerance) trong cửa sổ
    frozen_window_minutes: float = 30.0
    frozen_tolerance: float = 0.0
    frozen_min_samples: int = 10
    # Độ ẩm bão hòa (~100%) có thể đứng yên hợp lệ khi mưa/sương mù
    frozen_hum_saturation: float = 99.0

    # Đọng nước cảm biến mưa
    drift_window_minutes: float = 360.0
    drift_max_mean_humidity: float = 65.0
    drift_max_pressure_drop_hpa: float = 0.5

    # Cửa sổ chỉ hợp lệ khi dữ liệu phủ ít nhất tỷ lệ này của chiều dài cửa sổ
    min_window_coverage: float = 0.9

    def bounds(self, field: str) -> tuple:
        return {
            "temperature": (self.temp_min, self.temp_max),
            "humidity": (self.hum_min, self.hum_max),
            "pressure": (self.press_min, self.press_max),
        }[field]

    def max_rate(self, field: str) -> float:
        return {
            "temperature": self.max_temp_rate_per_min,
            "humidity": self.max_hum_rate_per_min,
            "pressure": self.max_press_rate_per_min,
        }[field]


DEFAULT_CONFIG = AnomalyConfig()


def _to_float(value: Any) -> Optional[float]:
    """Ép kiểu về float; trả None nếu thiếu, không phải số hoặc NaN/inf."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _to_timestamp(value: Any) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _anomaly(kind: str, sensor: str, message: str, **details: Any) -> Dict[str, Any]:
    return {"type": kind, "sensor": sensor, "message": message, **details}


def _prepare_history(df_history: pd.DataFrame) -> pd.DataFrame:
    """Chuẩn hóa timestamp về UTC, sắp xếp tăng dần, bỏ dòng không có timestamp."""
    if "timestamp" not in df_history.columns:
        raise ValueError("df_history phải có cột 'timestamp'")
    df = df_history.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def _recent_window(df: pd.DataFrame, window_minutes: float, cfg: AnomalyConfig) -> Optional[pd.DataFrame]:
    """Cắt cửa sổ (t_last - window, t_last]; trả None nếu dữ liệu không phủ đủ cửa sổ."""
    if df.empty:
        return None
    t_last = df["timestamp"].iloc[-1]
    t_start = t_last - pd.Timedelta(minutes=window_minutes)
    # Cần có ít nhất một mẫu ở gần đầu cửa sổ để biết trạng thái kéo dài suốt cửa sổ
    if df["timestamp"].iloc[0] > t_start + pd.Timedelta(minutes=window_minutes * (1 - cfg.min_window_coverage)):
        return None
    return df[df["timestamp"] > t_start]


class SensorAnomalyDetector:
    @classmethod
    def check_measurement(
        cls,
        current: Dict[str, Any],
        previous: Optional[Dict[str, Any]] = None,
        config: AnomalyConfig = DEFAULT_CONFIG,
    ) -> Dict[str, Any]:
        """
        Kiểm tra một bản ghi đo lường (so với bản ghi liền trước nếu có).

        Trả về:
            is_valid      : False nếu bản ghi không nên dùng cho mô hình
            has_anomaly   : có ít nhất một dị thường
            anomaly_list  : danh sách thông điệp (giữ tương thích bản cũ)
            anomalies     : danh sách dict {type, sensor, message, ...} cho Dashboard
        """
        anomalies: List[Dict[str, Any]] = []
        values: Dict[str, Optional[float]] = {}

        for field in SENSOR_FIELDS:
            val = _to_float(current.get(field))
            values[field] = val
            unit = UNITS[field]
            if val is None:
                anomalies.append(_anomaly("MISSING_VALUE", field, f"{field} missing or not numeric",
                                          value=current.get(field)))
                continue
            lo, hi = config.bounds(field)
            if not (lo <= val <= hi):
                anomalies.append(_anomaly("OUT_OF_RANGE", field,
                                          f"{field} out of bounds ({val}{unit}, expected {lo}-{hi})",
                                          value=val))

        if previous:
            anomalies.extend(cls._check_spikes(current, previous, values, config))

        return {
            "is_valid": not anomalies,
            "has_anomaly": bool(anomalies),
            "anomaly_list": [a["message"] for a in anomalies],
            "anomalies": anomalies,
        }

    @staticmethod
    def _check_spikes(
        current: Dict[str, Any],
        previous: Dict[str, Any],
        values: Dict[str, Optional[float]],
        config: AnomalyConfig,
    ) -> List[Dict[str, Any]]:
        t_cur = _to_timestamp(current.get("timestamp"))
        t_prev = _to_timestamp(previous.get("timestamp"))
        if t_cur is not None and t_prev is not None:
            dt_min = (t_cur - t_prev).total_seconds() / 60.0
            if dt_min <= 0 or dt_min > config.max_gap_minutes:
                # Bản ghi trùng/đảo thứ tự hoặc mất dữ liệu lâu: không so sánh được
                return []
        else:
            # Không có timestamp: coi như 2 bản ghi cách nhau <= 1 phút
            dt_min = 1.0
        # Mẫu số tối thiểu 1 phút: ngưỡng trở thành "bước nhảy tối đa trong 1 phút"
        dt_eff = max(dt_min, 1.0)

        spikes = []
        for field in SENSOR_FIELDS:
            cur, prev = values[field], _to_float(previous.get(field))
            if cur is None or prev is None:
                continue
            rate = abs(cur - prev) / dt_eff
            if rate > config.max_rate(field):
                spikes.append(_anomaly(
                    "SPIKE", field,
                    f"Abnormal {field} spike: jump of {abs(cur - prev):.2f}{UNITS[field]} in {dt_min:.2f} min",
                    value=cur, previous_value=prev, rate_per_min=round(rate, 3),
                ))
        return spikes

    @classmethod
    def detect_frozen_values(
        cls, df_history: pd.DataFrame, config: AnomalyConfig = DEFAULT_CONFIG
    ) -> Dict[str, Any]:
        """
        Phát hiện cảm biến BME280 bị kẹt giá trị: trong `frozen_window_minutes` gần nhất,
        một đại lượng có biên độ dao động <= `frozen_tolerance`.
        Độ ẩm ở mức bão hòa (>= `frozen_hum_saturation`) được bỏ qua vì có thể đứng yên hợp lệ.
        """
        df = _prepare_history(df_history)
        window = _recent_window(df, config.frozen_window_minutes, config)
        if window is None:
            return {"frozen_detected": False, "frozen_sensors": [], "anomalies": [],
                    "reason": "Insufficient history"}

        anomalies = []
        for field in SENSOR_FIELDS:
            if field not in window.columns:
                continue
            series = pd.to_numeric(window[field], errors="coerce").dropna()
            if len(series) < config.frozen_min_samples:
                continue
            spread = float(series.max() - series.min())
            if spread > config.frozen_tolerance:
                continue
            if field == "humidity" and series.iloc[-1] >= config.frozen_hum_saturation:
                continue
            anomalies.append(_anomaly(
                "FROZEN_VALUE", field,
                f"{field} stuck at {series.iloc[-1]}{UNITS[field]} for {config.frozen_window_minutes:.0f} min",
                value=float(series.iloc[-1]), samples=int(len(series)),
            ))

        return {
            "frozen_detected": bool(anomalies),
            "frozen_sensors": [a["sensor"] for a in anomalies],
            "anomalies": anomalies,
            "reason": "Frozen values found" if anomalies else "Normal behavior",
        }

    @classmethod
    def detect_rain_sensor_drift(
        cls, df_history: pd.DataFrame, config: AnomalyConfig = DEFAULT_CONFIG
    ) -> Dict[str, Any]:
        """
        Phát hiện hiện tượng đọng nước làm kẹt cảm biến mưa (Water stagnation drift):
        trong `drift_window_minutes` gần nhất (mặc định 6 giờ),
        - cảm biến mưa báo ướt (rain_detected == 1) ở MỌI mẫu,
        - độ ẩm trung bình < `drift_max_mean_humidity`,
        - áp suất không giảm quá `drift_max_pressure_drop_hpa` (không có dấu hiệu hệ thống mưa).
        Khi đó khả năng cao là nước đọng trên bề mặt PCB cảm biến chưa khô.
        """
        df = _prepare_history(df_history)
        window = _recent_window(df, config.drift_window_minutes, config)
        if window is None or len(window) < 2:
            return {"drift_detected": False, "reason": "Insufficient history"}

        rain = pd.to_numeric(window["rain_detected"], errors="coerce")
        humidity = pd.to_numeric(window["humidity"], errors="coerce").dropna()
        pressure = pd.to_numeric(window["pressure"], errors="coerce").dropna()
        if humidity.empty or len(pressure) < 2:
            return {"drift_detected": False, "reason": "Insufficient history"}

        all_wet = bool((rain == 1).all())
        mean_humidity = float(humidity.mean())
        pressure_change = float(pressure.iloc[-1] - pressure.iloc[0])
        details = {
            "window_minutes": config.drift_window_minutes,
            "mean_humidity": round(mean_humidity, 2),
            "pressure_change_hpa": round(pressure_change, 2),
        }

        if (all_wet
                and mean_humidity < config.drift_max_mean_humidity
                and pressure_change >= -config.drift_max_pressure_drop_hpa):
            return {
                "drift_detected": True,
                "anomaly_type": "WATER_STAGNATION_DRIFT",
                "message": "Cảm biến mưa có dấu hiệu đọng nước lâu ngày (kẹt giá trị ướt trong khi độ ẩm môi trường đã khô ráo).",
                **details,
            }

        return {"drift_detected": False, "reason": "Normal behavior", **details}

    @classmethod
    def analyze(cls, df_history: pd.DataFrame, config: AnomalyConfig = DEFAULT_CONFIG) -> Dict[str, Any]:
        """
        Báo cáo sức khỏe cảm biến tổng hợp cho Backend / Dashboard (SA-05):
        kiểm tra bản ghi mới nhất (so với bản ghi liền trước), frozen value và đọng nước.

        status: "OK" | "WARNING" (frozen / drift — dữ liệu đáng ngờ)
                     | "FAULT" (bản ghi mới nhất không hợp lệ)
        """
        df = _prepare_history(df_history)
        if df.empty:
            return {"status": "UNKNOWN", "anomalies": [], "reason": "No data"}

        records = df.to_dict("records")
        latest = cls.check_measurement(records[-1], records[-2] if len(records) > 1 else None, config)
        frozen = cls.detect_frozen_values(df, config)
        drift = cls.detect_rain_sensor_drift(df, config)

        anomalies = latest["anomalies"] + frozen["anomalies"]
        if drift["drift_detected"]:
            anomalies.append(_anomaly(drift["anomaly_type"], "rain", drift["message"]))

        if not latest["is_valid"]:
            status = "FAULT"
        elif anomalies:
            status = "WARNING"
        else:
            status = "OK"

        if anomalies:
            logger.warning("[ANOMALY] %s: %s", status, "; ".join(a["type"] for a in anomalies))

        return {
            "status": status,
            "checked_at": records[-1]["timestamp"].isoformat(),
            "anomalies": anomalies,
            "latest_valid": latest["is_valid"],
            "frozen_sensors": frozen["frozen_sensors"],
            "rain_drift": drift["drift_detected"],
        }
