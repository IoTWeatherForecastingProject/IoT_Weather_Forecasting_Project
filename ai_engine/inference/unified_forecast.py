"""
==============================================================================
MODULE 3 & 4: UNIFIED FORECAST INFERENCE ENGINE
Phụ trách: TV2 (Đóng gói chính) & TV3 (Hợp nhất mô hình mưa)
Các Task: ML-06 (TASK.md)
==============================================================================
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Union
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
from rain_classification.features import extract_rain_features

# Đường dẫn lưu models
TEMP_MODEL_PATH = BASE_DIR / "saved_models" / "temp_forecast_models.joblib"
RAIN_MODEL_PATH = BASE_DIR / "saved_models" / "rain_classifier_models.joblib"

_temp_payload = None
_rain_payload = None


def _load_models():
    global _temp_payload, _rain_payload
    if _temp_payload is None and TEMP_MODEL_PATH.exists():
        try:
            _temp_payload = joblib.load(TEMP_MODEL_PATH)
        except Exception as e:
            print(f"[INFERENCE ENGINE] Không thể nạp temp model: {e}")

    if _rain_payload is None and RAIN_MODEL_PATH.exists():
        try:
            _rain_payload = joblib.load(RAIN_MODEL_PATH)
        except Exception as e:
            print(f"[INFERENCE ENGINE] Không thể nạp rain model: {e}")


def predict_forecast(recent_data: Union[pd.DataFrame, list]) -> Dict[str, Any]:
    """
    HÀM SUY LUẬN HỢP NHẤT DÙNG CHUNG CHO TOÀN BỘ DỰ ÁN
    Đầu vào: DataFrame hoặc danh sách bản ghi đo lường gần nhất (tối thiểu 15-30 mẫu).
    Đầu ra: Dictionary kết quả dự báo nhiệt độ và xác suất mưa tại +10m, +30m, +60m.
    """
    _load_models()

    if isinstance(recent_data, list):
        df = pd.DataFrame(recent_data)
    else:
        df = recent_data.copy()

    if df.empty:
        raise ValueError("recent_data khong duoc de trong")

    # Lấy giá trị hiện tại
    latest_row = df.iloc[-1]
    cur_temp = float(latest_row.get("temperature", 30.0))
    cur_hum = float(latest_row.get("humidity", 75.0))
    cur_press = float(latest_row.get("pressure", 1008.0))
    device_id = str(latest_row.get("device_id", "station01"))

    # Tiền xử lý & Trích xuất đặc trưng
    preprocessor = TimeSeriesPreprocessor(freq="1min")
    clean_df = preprocessor.clean_and_resample(df)

    feat_temp_df = extract_temperature_features(clean_df)
    feat_rain_df = extract_rain_features(clean_df)

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
            print(f"[INFERENCE ENGINE] Lỗi suy luận model nhiệt độ: {e}")

    # Fallback cho nhiệt độ nếu chưa nạp được model weights
    if 10 not in forecast_temps:
        forecast_temps[10] = round(cur_temp - 0.1, 2)
    if 30 not in forecast_temps:
        forecast_temps[30] = round(cur_temp - 0.3, 2)
    if 60 not in forecast_temps:
        forecast_temps[60] = round(cur_temp - 0.6, 2)

    # Dự báo Xác suất Mưa (+10m, +30m, +60m)
    forecast_rain_probs = {}
    if _rain_payload is not None and not feat_rain_df.empty:
        try:
            feature_cols = _rain_payload["feature_cols"]
            X_rain = feat_rain_df[feature_cols].iloc[[-1]]
            for h in [10, 30, 60]:
                model = _rain_payload["models"].get(f"rain_{h}m")
                if model:
                    # predict_proba trả về mảng 2 cột [P(no_rain), P(rain)]
                    prob = float(model.predict_proba(X_rain)[0, 1])
                    forecast_rain_probs[h] = round(prob, 2)
        except Exception as e:
            print(f"[INFERENCE ENGINE] Lỗi suy luận model mưa: {e}")

    # Fallback heuristic cho mưa
    if 10 not in forecast_rain_probs or 30 not in forecast_rain_probs or 60 not in forecast_rain_probs:
        # Tính delta áp suất gần đây
        delta_p = 0.0
        if len(clean_df) >= 10:
            delta_p = float(clean_df["pressure"].iloc[-1] - clean_df["pressure"].iloc[0])
        base_p = 0.15
        if delta_p < -0.8:
            base_p += 0.45
        if cur_hum > 80:
            base_p += 0.25
        base_p = min(max(base_p, 0.05), 0.95)

        forecast_rain_probs[10] = round(min(max(base_p * 0.7, 0.05), 0.95), 2)
        forecast_rain_probs[30] = round(base_p, 2)
        forecast_rain_probs[60] = round(min(max(base_p * 1.2, 0.05), 0.95), 2)

    def get_rain_level(prob: float) -> str:
        if prob >= 0.70:
            return "High"
        elif prob >= 0.30:
            return "Medium"
        return "Low"

    max_prob = max(forecast_rain_probs.values())
    alert_triggered = max_prob >= 0.70

    return {
        "device_id": device_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_temperature": round(cur_temp, 2),
        "current_humidity": round(cur_hum, 2),
        "current_pressure": round(cur_press, 2),
        "plus_10m": {
            "temperature_c": forecast_temps[10],
            "rain_probability": forecast_rain_probs[10],
            "rain_level": get_rain_level(forecast_rain_probs[10])
        },
        "plus_30m": {
            "temperature_c": forecast_temps[30],
            "rain_probability": forecast_rain_probs[30],
            "rain_level": get_rain_level(forecast_rain_probs[30])
        },
        "plus_60m": {
            "temperature_c": forecast_temps[60],
            "rain_probability": forecast_rain_probs[60],
            "rain_level": get_rain_level(forecast_rain_probs[60])
        },
        "alert_triggered": alert_triggered,
        "alert_message": f"Cảnh báo xác suất mưa đạt {int(max_prob*100)}% trong 60 phút tới!" if alert_triggered else None
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # Test doc lap module inference
    sample_csv = BASE_DIR / "data" / "sample" / "sample_weather_data.csv"
    if sample_csv.exists():
        df_test = pd.read_csv(sample_csv).tail(40)
        result = predict_forecast(df_test)
        print("\n--- KET QUA SUY LUAN TEST DOC LAP ---")
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))
