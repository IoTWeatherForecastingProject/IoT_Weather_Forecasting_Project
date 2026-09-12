from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class WeatherMeasurementCreate(BaseModel):
    device_id: str = Field(..., example="station01")
    timestamp: Optional[datetime] = None
    temperature: float = Field(..., description="Nhiệt độ đo được (°C)", example=31.25)
    humidity: float = Field(..., description="Độ ẩm không khí (%)", example=78.4)
    pressure: float = Field(..., description="Áp suất khí quyển (hPa)", example=1005.8)
    rain_raw: Optional[int] = Field(None, description="Giá trị ADC thô từ cảm biến mưa")
    rain_detected: int = Field(0, description="1 nếu phát hiện mưa, 0 nếu không")


class WeatherMeasurementResponse(BaseModel):
    id: int
    device_id: str
    timestamp: datetime
    temperature: float
    humidity: float
    pressure: float
    rain_raw: Optional[int] = None
    rain_detected: int

    class Config:
        from_attributes = True


class ForecastHorizon(BaseModel):
    temperature_c: float
    rain_probability: float
    rain_level: str  # "Low", "Medium", "High"


class ForecastResponse(BaseModel):
    device_id: str
    generated_at: datetime
    current_temperature: float
    current_humidity: float
    current_pressure: float
    plus_10m: ForecastHorizon
    plus_30m: ForecastHorizon
    plus_60m: ForecastHorizon
    alert_triggered: bool
    alert_message: Optional[str] = None


class ThresholdUpdateRequest(BaseModel):
    threshold: float = Field(..., ge=0.0, le=1.0, description="Ngưỡng kích hoạt cảnh báo mưa (0.0 đến 1.0)", example=0.70)

