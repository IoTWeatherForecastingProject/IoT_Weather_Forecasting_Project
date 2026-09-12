"""
==============================================================================
MODULE 4: FEATURE ENGINEERING CHO DỰ BÁO XÁC SUẤT MƯA
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-01 (TASK.md)
==============================================================================
"""

import numpy as np
import pandas as pd


def extract_rain_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Trích xuất các đặc trưng khí quyển đặc thù báo hiệu khả năng mưa:
    - Tốc độ tụt áp suất khí quyển: Delta P / Delta t (30m, 60m)
    - Tốc độ tăng độ ẩm không khí: Delta H / Delta t (30m, 60m)
    - Tốc độ giảm nhiệt độ đột ngột: Delta T / Delta t
    - Trạng thái tích lũy của cảm biến mưa
    """
    data = df.copy()

    # 1. Tốc độ thay đổi áp suất (Tụt áp báo bão/mưa dông)
    if "pressure" in data.columns:
        data["press_diff_15m"] = data["pressure"] - data["pressure"].shift(15)
        data["press_diff_30m"] = data["pressure"] - data["pressure"].shift(30)
        data["press_diff_60m"] = data["pressure"] - data["pressure"].shift(60)

    # 2. Tốc độ thay đổi độ ẩm (Tăng ẩm nhanh)
    if "humidity" in data.columns:
        data["hum_diff_15m"] = data["humidity"] - data["humidity"].shift(15)
        data["hum_diff_30m"] = data["humidity"] - data["humidity"].shift(30)
        data["hum_diff_60m"] = data["humidity"] - data["humidity"].shift(60)

    # 3. Tốc độ thay đổi nhiệt độ
    if "temperature" in data.columns:
        data["temp_diff_30m"] = data["temperature"] - data["temperature"].shift(30)

    # 4. Trạng thái cảm biến mưa thô
    if "rain_raw" in data.columns:
        data["rain_raw_roll_mean_10m"] = data["rain_raw"].rolling(10, min_periods=1).mean()

    # 5. Điểm sương ước tính (Dew Point Approximation)
    # Td ≈ T - ((100 - RH)/5)
    if "temperature" in data.columns and "humidity" in data.columns:
        data["dew_point_approx"] = data["temperature"] - ((100.0 - data["humidity"]) / 5.0)
        data["temp_dew_spread"] = data["temperature"] - data["dew_point_approx"]

    return data

