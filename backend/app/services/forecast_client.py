import logging
from datetime import datetime, timezone
import pandas as pd
from app.config import settings
from app.schemas.weather import ForecastPayload
from pydantic import ValidationError

logger = logging.getLogger(__name__)

def load_forecast_predictor():
    # Import the adapter only on opt-in; standalone startup needs no ML runtime.
    from app.services.integrated_forecast import predict_forecast
    return predict_forecast


class ForecastClient:
    @staticmethod
    def get_forecast(recent_measurements: list[dict], threshold: float = 0.70) -> dict:
        """Nhận danh sách các bản ghi thời tiết gần nhất và sinh kết quả dự báo (+10m, +30m, +60m)."""
        if not recent_measurements:
            raise ValueError("recent_measurements khong duoc de trong")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold phai nam trong [0, 1]")
        latest = recent_measurements[-1]
        cur_temp = float(latest["temperature"])
        cur_hum = float(latest["humidity"])
        cur_press = float(latest["pressure"])

        fallback_reason = "standalone_mode"
        # External code is loaded only after explicit opt-in, never at startup.
        if settings.FORECAST_ENGINE_MODE == "auto":
            try:
                predictor = load_forecast_predictor()
                df = pd.DataFrame(recent_measurements)
                candidate = predictor(df, threshold=threshold)
                result = ForecastPayload.model_validate(candidate).model_dump(mode="json")
                if result["device_id"] != latest["device_id"]:
                    raise ValueError("Provider returned another device")
                # TV1 owns the alert decision and configured threshold.
                result["alert_triggered"] = max(result[f"plus_{h}m"]["rain_probability"] for h in (10, 30, 60)) >= threshold
                if not result["alert_triggered"]:
                    result["alert_message"] = None
                result.update(forecast_engine="external", fallback_reason=None)
                return result
            except (ImportError, AttributeError):
                fallback_reason = "engine_unavailable"
            except (ValidationError, ValueError, TypeError, KeyError):
                fallback_reason = "invalid_engine_output"
            except Exception as e:
                logger.error("[FORECAST CLIENT] Loi khi chay AI inference engine: %s. Chuyen sang fallback.", e)
                fallback_reason = "engine_failed"
            logger.warning("[FORECAST CLIENT] Using local heuristic: %s", fallback_reason)

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

        p10 = round(min(max(base_rain_prob * 0.7, 0.05), 0.95), 2)
        p30 = round(base_rain_prob, 2)
        p60 = round(min(max(base_rain_prob * 1.2, 0.05), 0.95), 2)
        alert_triggered = max(p10, p30, p60) >= threshold

        return {
            "forecast_engine": "local_heuristic",
            "fallback_reason": fallback_reason,
            "temperature_model": "LocalHeuristic",
            "temperature_confidence": "fallback",
            "temperature_fallback_reason": fallback_reason,
            "device_id": latest.get("device_id", "station01"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "current_temperature": round(cur_temp, 2),
            "current_humidity": round(cur_hum, 2),
            "current_pressure": round(cur_press, 2),
            "plus_10m": {
                "temperature_c": round(cur_temp - 0.1, 2),
                "temperature_source": "heuristic",
                "rain_probability": round(p10, 2),
                "rain_level": get_level(p10),
                "rain_source": "heuristic",
            },
            "plus_30m": {
                "temperature_c": round(cur_temp - 0.3, 2),
                "temperature_source": "heuristic",
                "rain_probability": round(p30, 2),
                "rain_level": get_level(p30),
                "rain_source": "heuristic",
            },
            "plus_60m": {
                "temperature_c": round(cur_temp - 0.7, 2),
                "temperature_source": "heuristic",
                "rain_probability": round(p60, 2),
                "rain_level": get_level(p60),
                "rain_source": "heuristic",
            },
            "alert_triggered": alert_triggered,
            "alert_message": "Canh bao xac suat mua cao trong 60 phut toi!" if alert_triggered else None
        }

