"""
==============================================================================
MODULE 4: ĐỐI CHUẨN TRẠM KHÍ TƯỢNG MỞ (OPENWEATHER BENCHMARK)
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-04 (TASK.md)
==============================================================================
"""

import logging
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)


class WeatherBenchmarkCrawler:
    def __init__(self, lat: float = 10.762622, lon: float = 106.660172, api_key: Optional[str] = None):
        """
        Mặc định tọa độ TP. Hồ Chí Minh.
        Nếu không có OpenWeather API Key, crawler tự động chuyển sang Open-Meteo API (Open & Free).
        """
        self.lat = lat
        self.lon = lon
        self.api_key = api_key

    def fetch_open_meteo(self) -> Dict[str, Any]:
        """Lấy dữ liệu thời tiết thực tế từ Open-Meteo API (Không cần API key)."""
        url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current=temperature_2m,relative_humidity_2m,surface_pressure,precipitation&timezone=Asia%2FBangkok"
        try:
            res = requests.get(url, timeout=5.0)
            if res.status_code == 200:
                data = res.json().get("current", {})
                return {
                    "source": "Open-Meteo",
                    "temperature": data.get("temperature_2m"),
                    "humidity": data.get("relative_humidity_2m"),
                    "pressure": data.get("surface_pressure"),
                    "precipitation": data.get("precipitation", 0.0),
                    "status": "success"
                }
        except Exception as e:
            logger.error("[BENCHMARK] Loi goi Open-Meteo API: %s", e)
        return {"status": "failed", "source": "Open-Meteo"}

    @staticmethod
    def calculate_sensor_bias(iot_data: Dict[str, float], benchmark_data: Dict[str, float]) -> Dict[str, float]:
        """
        Tính toán độ lệch (Bias) giữa cảm biến IoT giá rẻ và trạm chuẩn:
        Bias = IoT_value - Benchmark_value
        """
        bias = {}
        if "temperature" in iot_data and "temperature" in benchmark_data:
            bias["temp_bias_c"] = round(float(iot_data["temperature"]) - float(benchmark_data["temperature"]), 2)

        if "humidity" in iot_data and "humidity" in benchmark_data:
            bias["hum_bias_percent"] = round(float(iot_data["humidity"]) - float(benchmark_data["humidity"]), 2)

        if "pressure" in iot_data and "pressure" in benchmark_data:
            bias["press_bias_hpa"] = round(float(iot_data["pressure"]) - float(benchmark_data["pressure"]), 2)

        return bias

