"""
==============================================================================
MODULE 3 & 4: UNIFIED FORECAST INFERENCE ENGINE
Phụ trách: TV2 (Đóng gói chính) & TV3 (Hợp nhất mô hình mưa)
Các Task: ML-06 (TASK.md)
==============================================================================
"""

import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, Union
try:
    import joblib
except ImportError:
    joblib = None

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from common.preprocessing import TimeSeriesPreprocessor
from temperature_forecasting.features import extract_temperature_features
from rain_classification.features import (
    DEFAULT_FFILL_LIMIT,
    DEFAULT_FREQ,
    RAIN_STATE_FEATURES,
    extract_rain_features,
    resample_to_grid,
)

logger = logging.getLogger(__name__)

# Đường dẫn lưu models
TEMP_MODEL_PATH = BASE_DIR / "saved_models" / "temp_forecast_models.joblib"
RAIN_MODEL_PATH = BASE_DIR / "saved_models" / "rain_classifier_models.joblib"

HORIZONS = (10, 30, 60)
DEFAULT_RAIN_ALERT_THRESHOLD = 0.70

_temp_payload = None
_rain_payload = None


def _load_models():
    global _temp_payload, _rain_payload
    if _temp_payload is None and TEMP_MODEL_PATH.exists():
        try:
            _temp_payload = joblib.load(TEMP_MODEL_PATH)
        except Exception as e:
            logger.error("[INFERENCE ENGINE] Khong the nap temp model: %s", e)

    if _rain_payload is None and RAIN_MODEL_PATH.exists():
        try:
            _rain_payload = joblib.load(RAIN_MODEL_PATH)
        except Exception as e:
            logger.error("[INFERENCE ENGINE] Khong the nap rain model: %s", e)


def _heuristic_rain_probs(clean_df: pd.DataFrame, cur_hum: float) -> Dict[int, float]:
    """Heuristic tụt áp + độ ẩm cao, chỉ dùng cho horizon không có dự báo hợp lệ từ model."""
    delta_p = 0.0
    if len(clean_df) >= 10 and "pressure" in clean_df.columns:
        delta_p = float(clean_df["pressure"].iloc[-1] - clean_df["pressure"].iloc[0])
    base_p = 0.15
    if delta_p < -0.8:
        base_p += 0.45
    if cur_hum > 80:
        base_p += 0.25
    base_p = min(max(base_p, 0.05), 0.95)
    return {
        10: round(min(max(base_p * 0.7, 0.05), 0.95), 2),
        30: round(base_p, 2),
        60: round(min(max(base_p * 1.2, 0.05), 0.95), 2),
    }


def _rain_model_probs(df: pd.DataFrame) -> Dict[int, Tuple[Optional[float], Optional[str]]]:
    """
    Xác suất mưa từ model cho từng horizon: {h: (prob, None)} hoặc {h: (None, lý do)}.

    Feature được dựng bằng đúng pipeline lúc train (resample_to_grid + extract_rain_features,
    bin (t-1m, t], ffill có giới hạn, không nội suy). Mỗi horizon xử lý độc lập: một model
    từ chối dự đoán (thiếu lịch sử, thiếu cột) không ảnh hưởng các horizon khác.
    """
    if _rain_payload is None:
        return {h: (None, "chua nap duoc artifact model mua") for h in HORIZONS}

    feature_cols = _rain_payload["feature_cols"]
    freq = _rain_payload.get("freq", DEFAULT_FREQ)
    try:
        grid = resample_to_grid(df, freq=freq,
                                ffill_limit=_rain_payload.get("ffill_limit_steps", DEFAULT_FFILL_LIMIT))
        feat = extract_rain_features(
            grid, freq=freq, include_rain_state=any(c in RAIN_STATE_FEATURES for c in feature_cols))
        X_rain = feat.reindex(columns=feature_cols).iloc[[-1]]
    except Exception as e:
        return {h: (None, f"khong dung duoc feature mua: {e}") for h in HORIZONS}

    out: Dict[int, Tuple[Optional[float], Optional[str]]] = {}
    for h in HORIZONS:
        model = _rain_payload["models"].get(f"rain_{h}m")
        if model is None:
            reason = (_rain_payload.get("calibration", {}).get(f"rain_{h}m") or {}).get("reason")
            out[h] = (None, f"artifact khong co model +{h}m" + (f" ({reason})" if reason else ""))
            continue
        try:
            # predict_proba trả về mảng 2 cột [P(no_rain), P(rain)]
            out[h] = (float(model.predict_proba(X_rain)[0, 1]), None)
        except Exception as e:
            out[h] = (None, str(e))
    return out


def predict_forecast(recent_data: Union[pd.DataFrame, list],
                     threshold: float = DEFAULT_RAIN_ALERT_THRESHOLD) -> Dict[str, Any]:
    """
    HÀM SUY LUẬN HỢP NHẤT DÙNG CHUNG CHO TOÀN BỘ DỰ ÁN
    Đầu vào: DataFrame hoặc danh sách bản ghi đo lường gần nhất của MỘT trạm. Model mưa cần
             lịch sử theo thời gian (artifact `min_history_minutes`, khuyến nghị
             `recommended_history_minutes`), không phải theo số bản ghi.
             `threshold`: ngưỡng cảnh báo mưa (lấy từ system_config `rain_alert_threshold`).
    Đầu ra: Dictionary kết quả dự báo nhiệt độ và xác suất mưa tại +10m, +30m, +60m.
            `rain_source` mỗi horizon cho biết xác suất đến từ "model" hay "heuristic".
    """
    _load_models()

    if isinstance(recent_data, list):
        df = pd.DataFrame(recent_data)
    else:
        df = recent_data.copy()

    if df.empty:
        raise ValueError("recent_data khong duoc de trong")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold phai nam trong [0, 1]")

    # Lấy giá trị hiện tại
    latest_row = df.iloc[-1]
    cur_temp = float(latest_row.get("temperature", 30.0))
    cur_hum = float(latest_row.get("humidity", 75.0))
    cur_press = float(latest_row.get("pressure", 1008.0))
    device_id = str(latest_row.get("device_id", "station01"))
    if "device_id" in df.columns and df["device_id"].nunique() > 1:
        logger.warning("[INFERENCE ENGINE] recent_data co nhieu tram; chi dung du lieu cua %s", device_id)
        df = df[df["device_id"].astype(str) == device_id]

    # Tiền xử lý & Trích xuất đặc trưng
    preprocessor = TimeSeriesPreprocessor(freq="1min")
    clean_df = preprocessor.clean_and_resample(df)

    feat_temp_df = extract_temperature_features(clean_df)

    # Dự báo Nhiệt độ (+10m, +30m, +60m)
    forecast_temps = {}
    if _temp_payload is not None and not feat_temp_df.empty:
        try:
            feature_cols = _temp_payload["feature_cols"]
            X_temp = feat_temp_df[feature_cols].iloc[[-1]]
            for h in [10, 30, 60]:
                model = _temp_payload["models"].get(f"temp_{h}m")
                if model:
                    pred = float(model.predict(X_temp)[0])
                    forecast_temps[h] = round(pred, 2)
        except Exception as e:
            logger.error("[INFERENCE ENGINE] Loi suy luan model nhiet do: %s", e)

    # Fallback cho nhiệt độ nếu chưa nạp được model weights
    if 10 not in forecast_temps:
        forecast_temps[10] = round(cur_temp - 0.1, 2)
    if 30 not in forecast_temps:
        forecast_temps[30] = round(cur_temp - 0.3, 2)
    if 60 not in forecast_temps:
        forecast_temps[60] = round(cur_temp - 0.6, 2)

    # Dự báo Xác suất Mưa (+10m, +30m, +60m): giữ kết quả model hợp lệ của từng horizon,
    # chỉ horizon không có dự báo từ model mới dùng heuristic
    forecast_rain_probs = {}
    rain_sources = {}
    heuristic = None
    for h, (prob, reason) in _rain_model_probs(df).items():
        if prob is not None:
            forecast_rain_probs[h] = round(prob, 2)
            rain_sources[h] = "model"
            continue
        if heuristic is None:
            heuristic = _heuristic_rain_probs(clean_df, cur_hum)
        forecast_rain_probs[h] = heuristic[h]
        rain_sources[h] = "heuristic"
        if _rain_payload is not None:
            logger.warning("[INFERENCE ENGINE] Mua +%dm dung heuristic: %s", h, reason)

    def get_rain_level(prob: float) -> str:
        if prob >= 0.70:
            return "High"
        elif prob >= 0.30:
            return "Medium"
        return "Low"

    max_prob = max(forecast_rain_probs.values())
    alert_triggered = max_prob >= threshold

    return {
        "device_id": device_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_temperature": round(cur_temp, 2),
        "current_humidity": round(cur_hum, 2),
        "current_pressure": round(cur_press, 2),
        "plus_10m": {
            "temperature_c": forecast_temps[10],
            "rain_probability": forecast_rain_probs[10],
            "rain_level": get_rain_level(forecast_rain_probs[10]),
            "rain_source": rain_sources[10],
        },
        "plus_30m": {
            "temperature_c": forecast_temps[30],
            "rain_probability": forecast_rain_probs[30],
            "rain_level": get_rain_level(forecast_rain_probs[30]),
            "rain_source": rain_sources[30],
        },
        "plus_60m": {
            "temperature_c": forecast_temps[60],
            "rain_probability": forecast_rain_probs[60],
            "rain_level": get_rain_level(forecast_rain_probs[60]),
            "rain_source": rain_sources[60],
        },
        "alert_triggered": alert_triggered,
        "alert_message": f"Cảnh báo xác suất mưa đạt {int(max_prob*100)}% trong 60 phút tới!" if alert_triggered else None
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    # Test doc lap module inference
    sample_csv = BASE_DIR / "data" / "sample" / "sample_weather_data.csv"
    if sample_csv.exists():
        df_test = pd.read_csv(sample_csv).tail(120)
        result = predict_forecast(df_test)
        print("\n--- KET QUA SUY LUAN TEST DOC LAP ---")
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))
