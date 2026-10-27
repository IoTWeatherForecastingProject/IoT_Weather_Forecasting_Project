import logging
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.session import get_db
from app.db.models import WeatherMeasurement, SystemConfig
from app.schemas.weather import (
    WeatherMeasurementResponse,
    ForecastResponse,
    ThresholdUpdateRequest
)
from app.services.weather_forecast import build_forecast, NoRecentMeasurements

router = APIRouter(prefix="/api/weather", tags=["Weather"])
logger = logging.getLogger(__name__)


@router.get(
    "/current",
    response_model=WeatherMeasurementResponse,
    summary="Lấy dữ liệu thời tiết tức thời mới nhất",
    description="Truy vấn bản ghi đo lường mới nhất của trạm thời tiết theo device_id. Nếu CSDL chưa có dữ liệu, trả về fallback an toàn có cờ status='waiting_data' để Dashboard không bị vỡ giao diện."
)
def get_current_weather(
    device_id: Optional[str] = Query(None, description="Mã định danh trạm quan trắc (vd: station01)"),
    db: Session = Depends(get_db)
):
    """Lấy bản ghi đo lường mới nhất của trạm thời tiết."""
    query = db.query(WeatherMeasurement)
    if device_id:
        query = query.filter(WeatherMeasurement.device_id == device_id)
    latest = query.order_by(desc(WeatherMeasurement.timestamp)).first()

    if not latest:
        # Nếu chưa có trong DB, trả về dữ liệu mẫu an toàn có cờ waiting_data
        return WeatherMeasurementResponse(
            id=0,
            device_id=device_id or "station01",
            timestamp=datetime.now(timezone.utc),
            temperature=30.50,
            humidity=76.00,
            pressure=1007.50,
            rain_raw=2200,
            rain_detected=0,
            status="waiting_data"
        )
    return latest


@router.get(
    "/history",
    response_model=List[WeatherMeasurementResponse],
    summary="Lấy lịch sử dữ liệu đo lường thời tiết",
    description="Truy vấn chuỗi thời gian các điểm đo lường của trạm thời tiết, hỗ trợ phân trang (limit, offset) và lọc theo khoảng thời gian (start_time, end_time). Dữ liệu được đảo ngược theo thứ tự thời gian tăng dần (cũ đến mới) phục vụ vẽ đồ thị SCADA."
)
def get_weather_history(
    device_id: Optional[str] = Query(None, description="Lọc theo mã trạm quan trắc (vd: station01)"),
    limit: int = Query(50, ge=1, le=1000, description="Số lượng điểm dữ liệu cần lấy (1 - 1000)"),
    offset: int = Query(0, ge=0, description="Vị trí bắt đầu lấy dữ liệu (phục vụ phân trang)"),
    start_time: Optional[datetime] = Query(None, description="Thời gian bắt đầu lọc (chuẩn UTC ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="Thời gian kết thúc lọc (chuẩn UTC ISO-8601)"),
    db: Session = Depends(get_db)
):
    """Lấy lịch sử dữ liệu đo lường phục vụ vẽ biểu đồ SCADA."""
    query = db.query(WeatherMeasurement)
    if device_id:
        query = query.filter(WeatherMeasurement.device_id == device_id)
    if start_time:
        query = query.filter(WeatherMeasurement.timestamp >= start_time)
    if end_time:
        query = query.filter(WeatherMeasurement.timestamp <= end_time)

    records = (
        query.order_by(desc(WeatherMeasurement.timestamp))
        .offset(offset)
        .limit(limit)
        .all()
    )
    # Đảo ngược lại theo thứ tự thời gian tăng dần để frontend vẽ từ trái sang phải
    return list(reversed(records))


@router.get(
    "/forecast",
    response_model=ForecastResponse,
    summary="Dự báo thời tiết ngắn hạn bằng AI Inference Engine",
    description="Lấy dữ liệu của một trạm trong 76 phút gần nhất, theo thứ tự thời gian, để dự báo +10m, +30m, +60m. Khi không truyền device_id, chọn trạm có mẫu mới nhất trong cửa sổ này. Trả 404 nếu không có mẫu; rain_source cho biết xác suất mưa từ model hay heuristic."
)
def get_weather_forecast(
    request: Request,
    device_id: Optional[str] = Query(None, min_length=1, max_length=50, description="Mã trạm; bỏ trống để chọn trạm có dữ liệu mới nhất"),
    db: Session = Depends(get_db)
):
    """Gọi AI Inference Engine dự báo nhiệt độ và xác suất mưa tại +10m, +30m, +60m."""
    worker = getattr(request.app.state, "mqtt_worker", None)
    try:
        return build_forecast(
            db, device_id=device_id, mqtt_client=worker.client if worker else None,
            now=datetime.now(timezone.utc),
        )
    except NoRecentMeasurements as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "no_recent_measurements",
                "device_id": exc.device_id,
                "message": str(exc),
            },
        ) from exc


@router.post(
    "/alerts/threshold",
    summary="Cập nhật ngưỡng kích hoạt cảnh báo mưa",
    description="Cập nhật ngưỡng xác suất mưa (0.0 - 1.0) lưu vào bảng system_config để điều khiển động điều kiện kích hoạt còi và đèn cảnh báo 2 chiều."
)
def update_alert_threshold(
    payload: ThresholdUpdateRequest,
    db: Session = Depends(get_db)
):
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
