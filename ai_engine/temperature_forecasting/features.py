"""
==============================================================================
MODULE 3: FEATURE ENGINEERING CHO DỰ BÁO NHIỆT ĐỘ
Phụ trách: TV2 (Time-Series AI Engineer)
Các Task: ML-02 (TASK.md)
==============================================================================
"""

import numpy as np
import pandas as pd


def extract_temperature_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Trích xuất các đặc trưng chuỗi thời gian cho bài toán hồi quy nhiệt độ:
    - Lag features: t-1, t-2, t-3, t-6 (phút/bước)
    - Difference: Chênh lệch delta nhiệt độ, áp suất, độ ẩm
    - Rolling stats: Rolling mean và Rolling std trong cửa sổ 15m, 30m, 60m
    - Cyclic Time: Mã hóa Sine/Cosine cho giờ trong ngày
    """
    data = df.copy()

    # 1. Lags của nhiệt độ, độ ẩm và áp suất
    for col in ["temperature", "humidity", "pressure"]:
        if col in data.columns:
            for lag in [1, 2, 3, 5, 10]:
                data[f"{col}_lag_{lag}"] = data[col].shift(lag)

    # 2. Chênh lệch (Delta T, Delta P, Delta H)
    if "temperature" in data.columns:
        data["temp_diff_5m"] = data["temperature"] - data["temperature"].shift(5)
        data["temp_diff_10m"] = data["temperature"] - data["temperature"].shift(10)
    if "pressure" in data.columns:
        data["press_diff_10m"] = data["pressure"] - data["pressure"].shift(10)
    if "humidity" in data.columns:
        data["hum_diff_10m"] = data["humidity"] - data["humidity"].shift(10)

    # 3. Rolling Statistics
    if "temperature" in data.columns:
        data["temp_roll_mean_15m"] = data["temperature"].rolling(window=15, min_periods=1).mean()
        data["temp_roll_std_15m"] = data["temperature"].rolling(window=15, min_periods=1).std().fillna(0)
        data["temp_roll_mean_30m"] = data["temperature"].rolling(window=30, min_periods=1).mean()
        data["temp_roll_mean_60m"] = data["temperature"].rolling(window=60, min_periods=1).mean()

    # 4. Cyclic Time Encoding (Giờ trong ngày theo hàm Sin/Cos)
    if isinstance(data.index, pd.DatetimeIndex):
        hours = data.index.hour + data.index.minute / 60.0
        data["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
        data["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)
    elif "timestamp" in data.columns:
        ts = pd.to_datetime(data["timestamp"])
        hours = ts.dt.hour + ts.dt.minute / 60.0
        data["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
        data["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)

    return data

