from datetime import datetime, timedelta
from typing import Literal, Optional
from pydantic import AwareDatetime, BaseModel, Field, ConfigDict, field_validator, model_validator


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
    temperature_c: float | None = Field(..., allow_inf_nan=False, description="Nhiệt độ dự báo (°C)", examples=[30.5])
    temperature_source: Optional[Literal["model", "persistence", "heuristic", "unavailable"]] = Field(
        None, description="Nguồn nhiệt độ tại horizon này; null nếu provider cũ không cung cấp"
    )
    rain_probability: float | None = Field(..., ge=0, le=1, allow_inf_nan=False, description="Xác suất mưa dự báo (0.0 đến 1.0)", examples=[0.72])
    rain_level: Literal["Low", "Medium", "High"] | None
    rain_source: Literal["model", "heuristic", "unavailable"]
    valid_at: AwareDatetime | None = None
    issue: Literal["observations_stale", "observations_unavailable", "model_unavailable", "model_partial"] | None = None
    history_required_minutes: int | None = None
    history_available_minutes: int | None = None

    @model_validator(mode="after")
    def validate_sources(self):
        rain_missing = self.rain_probability is None
        if rain_missing != (self.rain_source == "unavailable") or rain_missing != (self.rain_level is None):
            raise ValueError("Rain forecast values and source must agree")
        if (self.temperature_c is None) != (self.temperature_source == "unavailable"):
            raise ValueError("Temperature forecast value and source must agree")
        return self

    @field_validator("temperature_c", "rain_probability", mode="before")
    @classmethod
    def round_floats(cls, v):
        if isinstance(v, (bool, str)):
            raise ValueError("Forecast values must be numeric")
        if v is not None:
            return float(v)
        return v


class ForecastPayload(BaseModel):
    """Provider boundary, validated before any external result can trigger an alert."""
    device_id: str = Field(..., description="Mã định danh trạm quan trắc", examples=["station01"])
    generated_at: AwareDatetime = Field(..., description="Thời điểm tạo dự báo chuẩn UTC")
    current_temperature: float | None = Field(..., allow_inf_nan=False, description="Nhiệt độ đầu vào (°C)", examples=[31.2])
    current_humidity: float | None = Field(..., allow_inf_nan=False, description="Độ ẩm đầu vào (%)", examples=[78.0])
    current_pressure: float | None = Field(..., allow_inf_nan=False, description="Áp suất đầu vào (hPa)", examples=[1006.5])
    temperature_model: Optional[str] = None
    temperature_confidence: Optional[Literal["normal", "degraded", "fallback"]] = None
    temperature_fallback_reason: Optional[str] = None
    plus_10m: ForecastHorizon = Field(..., description="Dự báo tại mốc +10 phút")
    plus_30m: ForecastHorizon = Field(..., description="Dự báo tại mốc +30 phút")
    plus_60m: ForecastHorizon = Field(..., description="Dự báo tại mốc +60 phút")
    alert_triggered: bool = Field(..., description="Cờ kích hoạt cảnh báo mưa 2 chiều", examples=[True])
    alert_message: Optional[str] = Field(None, description="Nội dung thông báo cảnh báo", examples=["Cảnh báo xác suất mưa cao trong 30-60 phút tới!"])

    @field_validator("current_temperature", "current_humidity", "current_pressure", mode="before")
    @classmethod
    def round_floats(cls, v):
        if isinstance(v, (bool, str)):
            raise ValueError("Forecast values must be numeric")
        if v is not None:
            return round(float(v), 2)
        return v


class ForecastResponse(ForecastPayload):
    """Public forecast including TV1 history and provider diagnostics."""
    history_window_minutes: int = Field(..., description="Cửa sổ thời gian truy vấn lịch sử (phút)")
    history_span_minutes: float = Field(..., description="Khoảng thời gian giữa mẫu đầu và cuối; không bảo đảm chuỗi không bị mất mẫu")
    history_measurements: int = Field(..., description="Số mẫu của một trạm đã truyền vào inference")
    rain_alert_threshold: float = Field(..., description="Ngưỡng dùng thống nhất cho inference và cảnh báo")
    forecast_engine: Literal["local_heuristic", "external", "regional_vvts", "station_inputs"]
    forecast_scope: Literal["station", "VVTS"] = "station"
    forecast_reference_at: AwareDatetime | None = None
    forecast_issue: Literal["model_unavailable", "observations_unavailable", "observations_stale"] | None = None
    fallback_reason: Optional[Literal["standalone_mode", "engine_unavailable", "engine_failed", "invalid_engine_output"]] = None


class ForecastTestPeriodRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=50)
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def validate_period(self):
        if not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=7):
            raise ValueError("Khoảng thử phải dài hơn 0 và không quá 7 ngày")
        return self


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
    alert_monitor_running: bool = Field(False, description="Tác vụ đánh giá cảnh báo định kỳ đang chạy")


class ThresholdResponse(BaseModel):
    """Ngưỡng cảnh báo hiện tại và nguồn cấu hình."""

    threshold: float = Field(description="Ngưỡng xác suất kích hoạt cảnh báo mưa")
    source: Literal["db", "default"] = Field(description="Nguồn lấy cấu hình")
    updated_at: Optional[datetime] = Field(None, description="Lần cập nhật trên DB")


class SensorAnomaly(BaseModel):
    """Dị thường cảm biến, giữ nguyên các chi tiết bổ sung từ bộ phân tích."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(description="Loại dị thường")
    sensor: str = Field(description="Tên cảm biến hoặc đại lượng")
    message: str = Field(description="Mô tả dị thường")


class SensorHealthResponse(BaseModel):
    """Sức khỏe cảm biến trong cửa sổ thời gian UTC của một trạm."""

    device_id: str
    status: Literal["OK", "WARNING", "FAULT", "UNKNOWN"]
    checked_at: Optional[datetime] = Field(
        None, description="Timestamp bản ghi mới nhất đã kiểm tra"
    )
    window_minutes: int
    n_records: int
    anomalies: list[SensorAnomaly] = Field(default_factory=list)
    frozen_sensors: list[str] = Field(default_factory=list)
    rain_drift: bool = False
    reason: Optional[str] = None


class ReferenceWeatherResponse(BaseModel):
    """Một điểm đo tham chiếu phục vụ biểu đồ đối chuẩn."""

    timestamp: datetime
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    pressure: Optional[float] = None


class LatestBiasResponse(BaseModel):
    """Sai số IoT trừ tham chiếu, riêng từng biến đủ ít nhất ba mẫu."""

    temp_bias_c: Optional[float] = None
    hum_bias_percent: Optional[float] = None
    press_bias_hpa: Optional[float] = None
    reference_timestamp: datetime
    n_iot: int = Field(description="Tổng số bản ghi IoT trong khoảng ghép ±5 phút")


class BenchmarkResponse(BaseModel):
    """Chuỗi tham chiếu và sai số tại mốc đối chuẩn mới nhất."""

    device_id: str
    source: str
    hours: int
    reference: list[ReferenceWeatherResponse] = Field(default_factory=list)
    latest_bias: Optional[LatestBiasResponse] = None
