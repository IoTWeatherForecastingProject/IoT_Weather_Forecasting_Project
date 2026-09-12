import logging
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.session import get_db
from app.db.models import WeatherMeasurement, SystemConfig
from app.schemas.weather import (
    WeatherMeasurementResponse,
    ForecastResponse,
    ThresholdUpdateRequest
)
from app.services.forecast_client import ForecastClient
from app.services.alert_service import AlertService

router = APIRouter(prefix="/api/weather", tags=["Weather"])
logger = logging.getLogger(__name__)


@router.get("/current", response_model=WeatherMeasurementResponse)
def get_current_weather(device_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Lấy bản ghi đo lường mới nhất của trạm thời tiết."""
    query = db.query(WeatherMeasurement)
    if device_id:
        query = query.filter(WeatherMeasurement.device_id == device_id)
    latest = query.order_by(desc(WeatherMeasurement.timestamp)).first()

    if not latest:
        # Nếu chưa có trong DB, trả về dữ liệu mẫu mặc định để Dashboard không crash
        return WeatherMeasurementResponse(
            id=0,
            device_id=device_id or "station01",
            timestamp=datetime.now(timezone.utc),
            temperature=30.5,
            humidity=76.0,
            pressure=1007.5,
            rain_raw=2200,
            rain_detected=0
        )
    return latest


@router.get("/history", response_model=List[WeatherMeasurementResponse])
def get_weather_history(
    device_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=1000, description="Số lượng điểm dữ liệu cần lấy"),
    db: Session = Depends(get_db)
):
    """Lấy lịch sử dữ liệu đo lường phục vụ vẽ biểu đồ SCADA."""
    query = db.query(WeatherMeasurement)
    if device_id:
        query = query.filter(WeatherMeasurement.device_id == device_id)
    records = query.order_by(desc(WeatherMeasurement.timestamp)).limit(limit).all()
    # Đảo ngược lại theo thứ tự thời gian tăng dần để frontend vẽ từ trái sang phải
    return list(reversed(records))


@router.get("/forecast", response_model=ForecastResponse)
def get_weather_forecast(device_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Gọi AI Inference Engine dự báo nhiệt độ và xác suất mưa tại +10m, +30m, +60m."""
    # Lấy cửa sổ trượt 30 bản ghi gần nhất để làm feature lag
    query = db.query(WeatherMeasurement)
    if device_id:
        query = query.filter(WeatherMeasurement.device_id == device_id)
    records = query.order_by(desc(WeatherMeasurement.timestamp)).limit(30).all()

    measurements = [
        {
            "device_id": r.device_id,
            "timestamp": r.timestamp,
            "temperature": float(r.temperature),
            "humidity": float(r.humidity),
            "pressure": float(r.pressure),
            "rain_raw": r.rain_raw,
            "rain_detected": r.rain_detected
        }
        for r in reversed(records)
    ]

    forecast_data = ForecastClient.get_forecast(measurements)

    # Đọc cấu hình ngưỡng hiện tại
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "rain_alert_threshold").first()
    current_threshold = float(cfg.config_value) if cfg else 0.70

    # Kích hoạt Closed-loop alert nếu xác suất mưa >= ngưỡng
    max_prob = max(
        forecast_data["plus_10m"]["rain_probability"],
        forecast_data["plus_30m"]["rain_probability"],
        forecast_data["plus_60m"]["rain_probability"]
    )
    horizon = 30 if forecast_data["plus_30m"]["rain_probability"] == max_prob else (10 if forecast_data["plus_10m"]["rain_probability"] == max_prob else 60)
    
    # Kích hoạt phản hồi 2 chiều
    AlertService.evaluate_and_trigger(
        device_id=forecast_data["device_id"],
        rain_probability=max_prob,
        horizon_minutes=horizon,
        threshold=current_threshold
    )

    return forecast_data


@router.post("/alerts/threshold")
def update_alert_threshold(payload: ThresholdUpdateRequest, db: Session = Depends(get_db)):
    """Cập nhật ngưỡng cảnh báo mưa (Form điều khiển 2 chiều từ Dashboard)."""
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == "rain_alert_threshold").first()
    if not cfg:
        cfg = SystemConfig(config_key="rain_alert_threshold", config_value=str(payload.threshold))
        db.add(cfg)
    else:
        cfg.config_value = str(payload.threshold)
        cfg.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("[CONFIG] Nguoi dung cap nhat nguong canh bao mua moi: %.2f", payload.threshold)
    return {"status": "success", "new_threshold": payload.threshold}

