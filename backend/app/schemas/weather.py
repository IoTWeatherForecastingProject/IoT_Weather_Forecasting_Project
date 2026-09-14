from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


class WeatherMeasurementCreate(BaseModel):
    """Schema tiếp nhận dữ liệu đo lường thời tiết từ cảm biến."""
    device_id: str = Field(..., description="Mã định danh trạm quan trắc (vd: station01)", examples=["station01"])
    timestamp: Optional[datetime] = Field(None, description="Thời gian ghi nhận chuẩn UTC ISO-8601")
    temperature: float = Field(..., description="Nhiệt độ đo được (°C)", examples=[31.25])
    humidity: float = Field(..., description="Độ ẩm không khí tương đối (%)", examples=[78.4])
    pressure: float = Field(..., description="Áp suất khí quyển (hPa)", examples=[1005.8])
    rain_raw: Optional[int] = Field(None, description="Giá trị ADC thô từ cảm biến mưa", examples=[2200])
    rain_detected: int = Field(0, description="Cờ phát hiện mưa (1: có mưa, 0: không mưa)", examples=[0])

    @field_validator("temperature", "humidity", "pressure", mode="before")
    @classmethod
    def round_floats(cls, v):
        if v is not None:
            return round(float(v), 2)
        return v


class WeatherMeasurementResponse(BaseModel):
    """Schema trả về dữ liệu đo lường thời tiết cho client / SCADA Dashboard."""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="ID định danh bản ghi trong CSDL", examples=[1])
    device_id: str = Field(..., description="Mã định danh trạm quan trắc", examples=["station01"])
    timestamp: datetime = Field(..., description="Thời gian ghi nhận chuẩn UTC ISO-8601")
    temperature: float = Field(..., description="Nhiệt độ đo được (°C)", examples=[31.25])
    humidity: float = Field(..., description="Độ ẩm không khí (%)", examples=[78.4])
    pressure: float = Field(..., description="Áp suất khí quyển (hPa)", examples=[1005.8])
    rain_raw: Optional[int] = Field(None, description="Giá trị ADC thô từ cảm biến mưa", examples=[2200])
    rain_detected: int = Field(..., description="Cờ phát hiện mưa (1: có mưa, 0: không mưa)", examples=[0])
    status: str = Field("ok", description="Trạng thái bản ghi ('ok' hoặc 'waiting_data')", examples=["ok"])

    @field_validator("temperature", "humidity", "pressure", mode="before")
    @classmethod
    def round_floats(cls, v):
        if v is not None:
            return round(float(v), 2)
        return v


class ForecastHorizon(BaseModel):
    """Schema kết quả dự báo tại một mốc thời gian cụ thể."""
    temperature_c: float = Field(..., description="Nhiệt độ dự báo (°C)", examples=[30.5])
    rain_probability: float = Field(..., description="Xác suất mưa dự báo (0.0 đến 1.0)", examples=[0.72])
    rain_level: str = Field(..., description="Mức độ mưa (Low, Medium, High)", examples=["High"])

    @field_validator("temperature_c", "rain_probability", mode="before")
    @classmethod
    def round_floats(cls, v):
        if v is not None:
            return round(float(v), 2)
        return v


class ForecastResponse(BaseModel):
    """Schema phản hồi kết quả dự báo thời tiết đa khung thời gian (+10m, +30m, +60m)."""
    device_id: str = Field(..., description="Mã định danh trạm quan trắc", examples=["station01"])
    generated_at: datetime = Field(..., description="Thời điểm tạo dự báo chuẩn UTC")
    current_temperature: float = Field(..., description="Nhiệt độ hiện tại (°C)", examples=[31.2])
    current_humidity: float = Field(..., description="Độ ẩm hiện tại (%)", examples=[78.0])
    current_pressure: float = Field(..., description="Áp suất hiện tại (hPa)", examples=[1006.5])
    plus_10m: ForecastHorizon = Field(..., description="Dự báo tại mốc +10 phút")
    plus_30m: ForecastHorizon = Field(..., description="Dự báo tại mốc +30 phút")
    plus_60m: ForecastHorizon = Field(..., description="Dự báo tại mốc +60 phút")
    alert_triggered: bool = Field(..., description="Cờ kích hoạt cảnh báo mưa 2 chiều", examples=[True])
    alert_message: Optional[str] = Field(None, description="Nội dung thông báo cảnh báo", examples=["Cảnh báo xác suất mưa cao trong 30-60 phút tới!"])

    @field_validator("current_temperature", "current_humidity", "current_pressure", mode="before")
    @classmethod
    def round_floats(cls, v):
        if v is not None:
            return round(float(v), 2)
        return v


class ThresholdUpdateRequest(BaseModel):
    """Schema cập nhật ngưỡng kích hoạt cảnh báo mưa từ Dashboard."""
    threshold: float = Field(..., ge=0.0, le=1.0, description="Ngưỡng kích hoạt cảnh báo mưa (0.0 đến 1.0)", examples=[0.70])


class HealthCheckResponse(BaseModel):
    """Schema kiểm tra sức khỏe hệ thống Backend."""
    status: str = Field("online", description="Trạng thái tổng thể hệ thống ('online' hoặc 'degraded')", examples=["online"])
    service: str = Field("IoT Weather Backend", description="Tên dịch vụ", examples=["IoT Weather Backend"])
    database_connected: bool = Field(..., description="Trạng thái kết nối CSDL PostgreSQL", examples=[True])
    mqtt_connected: bool = Field(..., description="Trạng thái kết nối MQTT Broker", examples=[True])
    active_ws_clients: int = Field(0, description="Số lượng client WebSocket đang kết nối", examples=[2])
