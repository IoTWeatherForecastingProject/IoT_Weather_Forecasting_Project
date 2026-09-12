import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

logger = logging.getLogger(__name__)

# Thêm thư mục ai_engine vào sys.path để import dễ dàng
AI_ENGINE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "ai_engine"
if str(AI_ENGINE_PATH) not in sys.path:
    sys.path.append(str(AI_ENGINE_PATH))

try:
    from inference.unified_forecast import predict_forecast as ai_predict_forecast
    HAS_AI_ENGINE = True
except ImportError as e:
    logger.warning("[FORECAST CLIENT] Chua the import ai_engine (%s). Su dung fallback heuristic.", e)
    HAS_AI_ENGINE = False


class ForecastClient:
    @staticmethod
    def get_forecast(recent_measurements: list[dict]) -> dict:
        """Nhận danh sách các bản ghi thời tiết gần nhất và sinh kết quả dự báo (+10m, +30m, +60m)."""
        if not recent_measurements:
            # Dữ liệu mặc định nếu chưa có bản ghi nào
            cur_temp, cur_hum, cur_press = 30.0, 75.0, 1008.0
        else:
            latest = recent_measurements[-1]
            cur_temp = float(latest.get("temperature", 30.0))
            cur_hum = float(latest.get("humidity", 75.0))
            cur_press = float(latest.get("pressure", 1008.0))

        # Nếu đã có ai_engine module hoàn chỉnh
        if HAS_AI_ENGINE:
            try:
                df = pd.DataFrame(recent_measurements)
                return ai_predict_forecast(df)
            except Exception as e:
                logger.error("[FORECAST CLIENT] Loi khi chay AI inference engine: %s. Chuyen sang fallback.", e)

        # Fallback Heuristic dự báo tạm thời khi TV2 & TV3 đang huấn luyện mô hình
        # Tính xu hướng tụt áp và tăng ẩm để ước lượng xác suất mưa
        delta_p = 0.0
        delta_h = 0.0
        if len(recent_measurements) >= 5:
            delta_p = float(recent_measurements[-1]["pressure"]) - float(recent_measurements[0]["pressure"])
            delta_h = float(recent_measurements[-1]["humidity"]) - float(recent_measurements[0]["humidity"])

        # Ước lượng xác suất mưa đơn giản
        base_rain_prob = 0.15
        if delta_p < -1.0 or cur_press < 1005:  # Tụt áp
            base_rain_prob += 0.35
        if delta_h > 5.0 or cur_hum > 80:     # Tăng ẩm mạnh
            base_rain_prob += 0.30

        base_rain_prob = min(max(base_rain_prob, 0.05), 0.95)

        def get_level(p):
            return "High" if p >= 0.70 else "Medium" if p >= 0.30 else "Low"

        p10 = min(max(base_rain_prob * 0.7, 0.05), 0.95)
        p30 = base_rain_prob
        p60 = min(max(base_rain_prob * 1.2, 0.05), 0.95)

        return {
            "device_id": recent_measurements[-1].get("device_id", "station01") if recent_measurements else "station01",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "current_temperature": round(cur_temp, 2),
            "current_humidity": round(cur_hum, 2),
            "current_pressure": round(cur_press, 2),
            "plus_10m": {
                "temperature_c": round(cur_temp - 0.1, 2),
                "rain_probability": round(p10, 2),
                "rain_level": get_level(p10)
            },
            "plus_30m": {
                "temperature_c": round(cur_temp - 0.3, 2),
                "rain_probability": round(p30, 2),
                "rain_level": get_level(p30)
            },
            "plus_60m": {
                "temperature_c": round(cur_temp - 0.7, 2),
                "rain_probability": round(p60, 2),
                "rain_level": get_level(p60)
            },
            "alert_triggered": max(p10, p30, p60) >= 0.70,
            "alert_message": "Canh bao xac suat mua cao trong 60 phut toi!" if max(p10, p30, p60) >= 0.70 else None
        }

