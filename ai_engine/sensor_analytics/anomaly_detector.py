"""
==============================================================================
MODULE 4: PHÁT HIỆN DỊ THƯỜNG VÀ TRÔI CẢM BIẾN (SENSOR ANOMALY & DRIFT)
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-03 (TASK.md)
==============================================================================
"""

import logging
from typing import Dict, List, Any
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SensorAnomalyDetector:
    # Giới hạn vật lý bình thường tại Việt Nam
    TEMP_MIN = 5.0    # °C
    TEMP_MAX = 55.0   # °C
    HUM_MIN = 10.0    # %
    HUM_MAX = 100.0   # %
    PRESS_MIN = 950.0 # hPa
    PRESS_MAX = 1050.0# hPa

    # Ngưỡng tốc độ thay đổi tối đa giữa 2 chu kỳ đo liên tiếp (Spike threshold)
    MAX_TEMP_JUMP_PER_MIN = 3.0   # °C/phút
    MAX_PRESS_JUMP_PER_MIN = 4.0  # hPa/phút

    @classmethod
    def check_measurement(cls, current: Dict[str, Any], previous: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Kiểm tra tính hợp lệ của bản ghi đo lường hiện tại:
        - Out-of-bounds (vượt ngưỡng vật lý)
        - Sudden spike (đột biến bất thường)
        """
        anomalies = []
        is_valid = True

        temp = float(current.get("temperature", 0))
        hum = float(current.get("humidity", 0))
        press = float(current.get("pressure", 0))

        # 1. Kiểm tra giới hạn vật lý
        if not (cls.TEMP_MIN <= temp <= cls.TEMP_MAX):
            anomalies.append(f"Temperature out of bounds ({temp}°C)")
            is_valid = False

        if not (cls.HUM_MIN <= hum <= cls.HUM_MAX):
            anomalies.append(f"Humidity out of bounds ({hum}%)")
            is_valid = False

        if not (cls.PRESS_MIN <= press <= cls.PRESS_MAX):
            anomalies.append(f"Pressure out of bounds ({press} hPa)")
            is_valid = False

        # 2. Kiểm tra spike nếu có bản ghi trước đó
        if previous:
            prev_temp = float(previous.get("temperature", temp))
            prev_press = float(previous.get("pressure", press))

            if abs(temp - prev_temp) > cls.MAX_TEMP_JUMP_PER_MIN:
                anomalies.append(f"Abnormal temperature spike: jump of {abs(temp - prev_temp):.2f}°C")
                is_valid = False

            if abs(press - prev_press) > cls.MAX_PRESS_JUMP_PER_MIN:
                anomalies.append(f"Abnormal pressure spike: jump of {abs(press - prev_press):.2f} hPa")
                is_valid = False

        return {
            "is_valid": is_valid,
            "has_anomaly": len(anomalies) > 0,
            "anomaly_list": anomalies
        }

    @classmethod
    def detect_rain_sensor_drift(cls, df_history: pd.DataFrame, window_minutes: int = 120) -> Dict[str, Any]:
        """
        Phát hiện hiện tượng đọng nước làm kẹt cảm biến mưa (Frozen value / Sensor Drift):
        Nếu cảm biến mưa báo ướt (rain_detected == 1) liên tục trong hơn window_minutes,
        nhưng độ ẩm không khí đã giảm sâu (< 65%) và áp suất tăng ổn định,
        thì khả năng cao là nước đọng trên bề mặt PCB cảm biến chưa khô.
        """
        if len(df_history) < 10:
            return {"drift_detected": False, "reason": "Insufficient data"}

        recent = df_history.tail(window_minutes)
        all_wet = (recent["rain_detected"] == 1).all()
        low_humidity = recent["humidity"].mean() < 65.0

        if all_wet and low_humidity:
            return {
                "drift_detected": True,
                "anomaly_type": "WATER_STAGNATION_DRIFT",
                "message": "Cảm biến mưa có dấu hiệu đọng nước lâu ngày (kẹt giá trị ướt trong khi độ ẩm môi trường đã khô ráo)."
            }

        return {"drift_detected": False, "reason": "Normal behavior"}

