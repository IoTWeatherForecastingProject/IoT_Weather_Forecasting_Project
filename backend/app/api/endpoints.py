import logging
import math
from typing import List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from sqlalchemy.exc import ProgrammingError

from app.config import settings
from app.db.session import get_db
from app.db.models import WeatherMeasurement, SystemConfig, ReferenceWeather
from app.schemas.weather import (
    WeatherMeasurementResponse,
    ForecastResponse,
    ThresholdUpdateRequest,
    ThresholdResponse,
    SensorHealthResponse,
    BenchmarkResponse
)
from app.services import analytics_client
from app.services.forecast_client import ForecastClient
from app.services.alert_service import AlertService

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


def resolve_rain_threshold(db: Session) -> Tuple[float, str, Optional[datetime]]:
    """Trả (threshold, source, updated_at); dùng chung cho GET ngưỡng và /forecast."""
    config = (
        db.query(SystemConfig)
        .filter(SystemConfig.config_key == "rain_alert_threshold")
        .first()
    )
    if config is not None:
        try:
            threshold = float(config.config_value)
            if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
                raise ValueError("threshold outside [0, 1]")
        except (TypeError, ValueError):
            logger.warning("[CONFIG] Invalid rain_alert_threshold; using default")
        else:
            return threshold, "db", config.updated_at
    return settings.RAIN_ALERT_THRESHOLD, "default", None


@router.get(
    "/forecast",
    response_model=ForecastResponse,
    summary="Dự báo thời tiết ngắn hạn bằng AI Inference Engine",
    description="Lấy cửa sổ trượt 30 điểm đo gần nhất từ CSDL truyền vào mô hình AI để dự báo nhiệt độ và xác suất mưa tại +10m, +30m, +60m. Tự động kích hoạt cơ chế phản hồi khép kín nếu xác suất mưa >= ngưỡng."
)
def get_weather_forecast(
    device_id: Optional[str] = Query(None, description="Mã định danh trạm quan trắc (vd: station01)"),
    db: Session = Depends(get_db)
):
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
    current_threshold, _, _ = resolve_rain_threshold(db)

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


@router.get(
    "/alerts/threshold",
    response_model=ThresholdResponse,
    summary="Đọc ngưỡng kích hoạt cảnh báo mưa",
    description=(
        "Đọc rain_alert_threshold từ system_config. Nếu chưa có hoặc giá trị "
        "không hợp lệ, trả ngưỡng mặc định RAIN_ALERT_THRESHOLD; source cho biết "
        "nguồn cấu hình và updated_at là thời điểm cập nhật trên DB."
    ),
)
def get_alert_threshold(db: Session = Depends(get_db)) -> ThresholdResponse:
    """Lấy ngưỡng từ DB, dùng cấu hình mặc định khi thiếu hoặc không hợp lệ."""
    threshold, source, updated_at = resolve_rain_threshold(db)
    return ThresholdResponse(threshold=threshold, source=source, updated_at=updated_at)


@router.get(
    "/sensor-health",
    response_model=SensorHealthResponse,
    summary="Kiểm tra sức khỏe cảm biến của trạm",
    description=(
        "Phân tích các bản ghi có timestamp UTC trong [now - window_minutes, now] "
        "(10–1440 phút); bản ghi có timestamp tương lai bị bỏ qua. "
        "Trả OK, WARNING, FAULT hoặc UNKNOWN nếu không có dữ liệu; "
        "bao gồm dị thường, cảm biến kẹt giá trị và dấu hiệu đọng nước cảm biến mưa. "
        "Trả 503 khi bộ phát hiện dị thường không khả dụng."
    ),
)
def get_sensor_health(
    device_id: str = Query(..., min_length=1, description="Mã trạm quan trắc"),
    window_minutes: int = Query(
        360, ge=10, le=1440, description="Cửa sổ kiểm tra theo phút, chuẩn UTC"
    ),
    db: Session = Depends(get_db),
) -> SensorHealthResponse:
    """Lọc dữ liệu theo timestamp UTC rồi kiểm tra sức khỏe cảm biến."""
    if not analytics_client.HAS_ANOMALY:
        raise HTTPException(503, detail="anomaly detector unavailable")
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=window_minutes)
    records = (
        db.query(WeatherMeasurement)
        .filter(
            WeatherMeasurement.device_id == device_id,
            WeatherMeasurement.timestamp >= start,
            WeatherMeasurement.timestamp <= now,
        )
        .order_by(WeatherMeasurement.timestamp)
        .all()
    )
    measurements = [
        {
            "timestamp": record.timestamp,
            "temperature": float(record.temperature),
            "humidity": float(record.humidity),
            "pressure": float(record.pressure),
            "rain_raw": record.rain_raw,
            "rain_detected": record.rain_detected,
        }
        for record in records
    ]
    return SensorHealthResponse(
        **analytics_client.sensor_health(measurements),
        device_id=device_id,
        window_minutes=window_minutes,
        n_records=len(records),
    )


@router.get(
    "/benchmark",
    response_model=BenchmarkResponse,
    summary="Đối chuẩn cảm biến với dữ liệu thời tiết tham chiếu",
    description=(
        "Lấy chuỗi reference_weather theo source trong [now - hours, now] (1–168 giờ, "
        "bỏ qua timestamp tương lai), sắp xếp timestamp UTC tăng dần. "
        "Sai số IoT trừ tham chiếu tại mốc mới nhất "
        "có nhiệt độ, độ ẩm hoặc áp suất, dùng trung bình IoT trong ±5 phút và "
        "ít nhất 3 mẫu cho từng biến. Không ghép được biến nào thì latest_bias=null. "
        "Mẫu IoT dùng để tính sai số cũng chỉ lấy timestamp <= now. "
        "Trả 503 nếu chưa chạy migration 002."
    ),
)
def get_benchmark(
    device_id: str = Query(..., min_length=1, description="Mã trạm quan trắc"),
    source: str = Query(
        "open-meteo", max_length=30, description="Nguồn dữ liệu tham chiếu"
    ),
    hours: int = Query(24, ge=1, le=168, description="Cửa sổ tham chiếu theo giờ UTC"),
    db: Session = Depends(get_db),
) -> BenchmarkResponse:
    """Trả chuỗi tham chiếu và sai số ở mốc mới nhất có dữ liệu đối chuẩn."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    try:
        records = (
            db.query(ReferenceWeather)
            .filter(
                ReferenceWeather.source == source,
                ReferenceWeather.timestamp >= start,
                ReferenceWeather.timestamp <= now,
            )
            .order_by(ReferenceWeather.timestamp)
            .all()
        )
    except ProgrammingError as exc:
        db.rollback()
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code != "42P01":
            raise
        raise HTTPException(
            503, detail="reference_weather table missing - run migration 002"
        ) from exc
    reference = [
        {
            "timestamp": record.timestamp,
            **{
                field: float(getattr(record, field))
                if getattr(record, field) is not None
                else None
                for field in ("temperature", "humidity", "pressure")
            },
        }
        for record in records
    ]
    bias = None
    latest = next(
        (
            record
            for record in reversed(reference)
            if any(
                record[field] is not None
                for field in ("temperature", "humidity", "pressure")
            )
        ),
        None,
    )
    if not analytics_client.HAS_BIAS:
        logger.warning(
            "[ANALYTICS] Bias analysis unavailable; returning reference only"
        )
    elif latest is not None:
        tolerance = timedelta(minutes=5)
        iot = (
            db.query(WeatherMeasurement)
            .filter(
                WeatherMeasurement.device_id == device_id,
                WeatherMeasurement.timestamp >= latest["timestamp"] - tolerance,
                WeatherMeasurement.timestamp <= latest["timestamp"] + tolerance,
                WeatherMeasurement.timestamp <= now,
            )
            .order_by(WeatherMeasurement.timestamp)
            .all()
        )
        bias = analytics_client.latest_bias(
            [
                {
                    "timestamp": record.timestamp,
                    "temperature": float(record.temperature),
                    "humidity": float(record.humidity),
                    "pressure": float(record.pressure),
                }
                for record in iot
            ],
            [latest],
            tolerance_minutes=5,
            min_samples=3,
        )
    return BenchmarkResponse(
        device_id=device_id,
        source=source,
        hours=hours,
        reference=reference,
        latest_bias=bias,
    )
