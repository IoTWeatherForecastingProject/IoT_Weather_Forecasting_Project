"""
ML-06: Forecast Inference Engine
==================================
Module inference khép kín, độc lập, dễ import cho TV1 nhúng vào REST API.

Giao diện chuẩn bàn giao TV1 → TV3:
    predict_forecast(recent_data)             → dict (JSON response cho BE-05)
    predict_temperature_forecast(recent_data) → dict
    predict_combined_forecast(recent_data)    → dict (kết hợp với Model 2 của TV3)

Kiến trúc & Chuẩn hóa:
    - Resampling về lưới 1 phút (1min grid) trước khi trích xuất đặc trưng.
    - Kiểm tra độ dài thời gian thực (ít nhất 90 phút), không chỉ đếm số hàng thô.
    - Dùng chung pipeline đặc trưng TemperatureFeatureEngineer từ ML-02.
    - Đối chiếu và align cột theo feature_schema.json đảm bảo 100% khớp model đã train.
    - Tự động nạp model tốt nhất theo thứ tự ưu tiên (XGBoost → RF → Lasso → Ridge).
    - Cung cấp cơ chế Fallback graceful kèm báo cáo lỗi chi tiết nếu dữ liệu không đạt.

Tác giả: TV2 — Time-Series AI Engineer
Dự án:   IoT Local Weather Forecasting
"""

from __future__ import annotations

import json
import logging
import time
import warnings
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import joblib
import numpy as np
import pandas as pd

from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Đường dẫn model mặc định
# ---------------------------------------------------------------------------
_ML_DIR    = Path(__file__).parent
MODEL_DIR  = _ML_DIR / "models"

# Thứ tự ưu tiên model khi load (từ tốt nhất → fallback)
MODEL_PRIORITY = ["XGBoost", "RandomForest", "Lasso", "Ridge"]
HORIZONS       = [10, 30, 60]

# Độ dài thời gian lịch sử tối thiểu (phút)
MIN_HISTORY_MINUTES = 90


# ---------------------------------------------------------------------------
# Dataclasses đầu ra — JSON-serializable
# ---------------------------------------------------------------------------
@dataclass
class TemperatureForecast:
    """
    Kết quả dự báo nhiệt độ đầu ra của TV2.
    Được TV1 nhúng vào response của /api/weather/forecast.
    """
    t_plus_10min: float          # Nhiệt độ dự báo tại +10 phút (°C)
    t_plus_30min: float          # Nhiệt độ dự báo tại +30 phút (°C)
    t_plus_60min: float          # Nhiệt độ dự báo tại +60 phút (°C)
    model_used:   str            # Tên model đã dùng (VD: "XGBoost")
    latency_ms:   float          # Thời gian inference (milliseconds)
    confidence:   str = "normal" # "normal" | "degraded" | "fallback"
    error_msg:    Optional[str] = None   # Nếu có lỗi → ghi chú

    def to_dict(self) -> Dict[str, Any]:
        """Chuyển về dict JSON-serializable cho TV1."""
        return {
            "temperature_forecast": {
                "t_plus_10min": round(self.t_plus_10min, 2),
                "t_plus_30min": round(self.t_plus_30min, 2),
                "t_plus_60min": round(self.t_plus_60min, 2),
            },
            "model_used":  self.model_used,
            "latency_ms":  round(self.latency_ms, 2),
            "confidence":  self.confidence,
            "error_msg":   self.error_msg,
        }


@dataclass
class CombinedForecast:
    """
    Kết quả dự báo tổng hợp — TV1 dùng để response /api/weather/forecast.
    TV3 sẽ điền rain_probability vào slot riêng.
    """
    temperature:        TemperatureForecast
    rain_probability:   Optional[Dict[str, float]] = None  # Điền bởi TV3
    generated_at:       str = ""                            # ISO timestamp

    def to_dict(self) -> Dict[str, Any]:
        d = self.temperature.to_dict()
        d["rain_probability"] = self.rain_probability or {}
        d["generated_at"]     = self.generated_at
        return d


# ---------------------------------------------------------------------------
# Inference Engine chính
# ---------------------------------------------------------------------------
class TemperatureInferenceEngine:
    """
    Engine inference nhiệt độ khép kín — TV1 chỉ cần gọi .predict().

    Cách dùng (TV1 import vào FastAPI):
    ------------------------------------
    from ml.inference_engine import get_engine

    engine = get_engine()   # load 1 lần lúc startup

    @app.get("/api/weather/forecast")
    async def get_forecast():
        recent_records = db.get_recent_readings(limit=1000)   # list of dicts từ PostgreSQL
        forecast       = engine.predict(recent_records)
        return forecast.to_dict()

    Args:
        model_dir:            Thư mục chứa .joblib model (mặc định: ml/models/).
        model_priority:       Danh sách tên model theo thứ tự ưu tiên.
        min_history_minutes:  Độ dài thời gian lịch sử tối thiểu (mặc định 90 phút).
    """

    def __init__(
        self,
        model_dir:            Union[str, Path] = MODEL_DIR,
        model_priority:       List[str]        = MODEL_PRIORITY,
        min_history_minutes:  int              = MIN_HISTORY_MINUTES,
    ) -> None:
        self.model_dir           = Path(model_dir)
        self.model_priority      = model_priority
        self.min_history_minutes = min_history_minutes
        self._models: Dict[int, Any]       = {}   # horizon → model object
        self._model_names: Dict[int, str]  = {}
        self._expected_features: List[str] = []

        # Dùng chung pipeline Feature Engineering với lúc train (ML-02)
        self._feature_engineer = TemperatureFeatureEngineer(FeatureConfig())

        # Load models và schema
        self._load_schema()
        self._load_models()

    # ------------------------------------------------------------------
    # Public API — giao diện chuẩn bàn giao TV1
    # ------------------------------------------------------------------

    def predict(
        self,
        recent_data: Union[pd.DataFrame, List[Dict[str, Any]]],
    ) -> TemperatureForecast:
        """
        Dự báo nhiệt độ từ dữ liệu lịch sử gần nhất.

        Args:
            recent_data: DataFrame hoặc list[dict] với các cột:
                         timestamp (ISO string hoặc datetime),
                         temperature (°C), humidity (%RH),
                         pressure (hPa), rain_raw (optional).
                         Cần thời gian trải dài ít nhất min_history_minutes (90 phút).

        Returns:
            TemperatureForecast với t_plus_10/30/60min, model_used, latency_ms.
        """
        t_start = time.perf_counter()

        try:
            # 1. Validate, parse DatetimeIndex và resample về lưới 1 phút
            df_1min = self._prepare_1min_grid(recent_data)

            # 2. Trích xuất đặc trưng dùng chung với pipeline training (ML-02)
            df_feat = self._feature_engineer.transform_features(df_1min)
            if len(df_feat) == 0:
                raise ValueError("Không đủ dữ liệu sau khi trích xuất lag/rolling features.")

            # 3. Lấy hàng mới nhất (t hiện tại) làm vector đặc trưng
            X = df_feat.iloc[[-1]]

            # 4. Đối chiếu schema và căn chỉnh thứ tự cột khớp 100% với model training
            if self._expected_features:
                X = X.reindex(columns=self._expected_features, fill_value=0.0)

            # 5. Predict từng horizon với model đã nạp
            preds: Dict[int, float] = {}
            for h in HORIZONS:
                if h in self._models:
                    raw_pred = float(self._models[h].predict(X)[0])
                    # Clamp vật lý: nhiệt độ phải trong [-10, 60]°C
                    preds[h] = float(np.clip(raw_pred, -10.0, 60.0))
                else:
                    # Fallback cục bộ từng horizon nếu thiếu model horizon đó
                    preds[h] = float(df_1min["temperature"].iloc[-1])
                    logger.warning("Thiếu model horizon +%dm — dùng Persistence.", h)

            latency_ms = (time.perf_counter() - t_start) * 1000
            model_name = self._model_names.get(HORIZONS[0], "Persistence")
            confidence = "normal" if len(self._models) == len(HORIZONS) else "degraded"

            return TemperatureForecast(
                t_plus_10min = round(preds[10], 3),
                t_plus_30min = round(preds[30], 3),
                t_plus_60min = round(preds[60], 3),
                model_used   = model_name,
                latency_ms   = round(latency_ms, 2),
                confidence   = confidence,
            )

        except Exception as exc:
            # Lỗi không dự đoán được hoặc dữ liệu không đủ → Fallback an toàn kèm ghi chú
            logger.error("Inference fallback triggered: %s", exc, exc_info=True)
            return self._persistence_fallback(recent_data, str(exc), t_start)

    def predict_combined(
        self,
        recent_data: Union[pd.DataFrame, List[Dict[str, Any]]],
        rain_probability: Optional[Dict[str, float]] = None,
    ) -> CombinedForecast:
        """
        Hàm tổng hợp cho TV1 — gọi predict() và đóng gói cùng rain_probability từ TV3.
        """
        import datetime
        temp_forecast = self.predict(recent_data)
        return CombinedForecast(
            temperature      = temp_forecast,
            rain_probability = rain_probability,
            generated_at     = datetime.datetime.utcnow().isoformat() + "Z",
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Kiểm tra trạng thái engine — TV1 dùng cho health check endpoint.
        """
        return {
            "status":             "ok" if len(self._models) == len(HORIZONS) else "degraded",
            "models_loaded":      {h: self._model_names.get(h, "None") for h in HORIZONS},
            "horizons_available": list(self._models.keys()),
            "min_history_steps":  self.min_history_minutes,
            "expected_features":  len(self._expected_features),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _prepare_1min_grid(
        self,
        recent_data: Union[pd.DataFrame, List[Dict[str, Any]]],
    ) -> pd.DataFrame:
        """
        Chuẩn hóa dữ liệu IoT thô về lưới 1 phút:
        - Parse và sắp xếp theo DatetimeIndex
        - Kiểm tra khoảng thời gian lịch sử thực tế (>= min_history_minutes)
        - Resample về 1-minute grid và nội suy các khoảng trống
        """
        if isinstance(recent_data, list):
            if len(recent_data) == 0:
                raise ValueError("recent_data rỗng.")
            df = pd.DataFrame(recent_data)
        elif isinstance(recent_data, pd.DataFrame):
            df = recent_data.copy()
        else:
            raise TypeError(f"recent_data phải là DataFrame hoặc list[dict], nhận: {type(recent_data)}")

        if "temperature" not in df.columns:
            raise ValueError("Thiếu cột bắt buộc: 'temperature'.")

        # Parse timestamp
        if not isinstance(df.index, pd.DatetimeIndex):
            ts_col = next(
                (c for c in ["timestamp", "time", "datetime", "created_at"] if c in df.columns),
                None
            )
            if ts_col:
                df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
                df = df.set_index(ts_col)
            else:
                # Không có timestamp → giả lập 1min
                df.index = pd.date_range(end=pd.Timestamp.utcnow(), periods=len(df), freq="1min")
                logger.warning("Không có cột timestamp — giả lập index 1min.")

        df = df.sort_index()
        # Bỏ timestamp trùng
        df = df[~df.index.duplicated(keep="last")]

        # Kiểm tra khoảng thời gian thực tế (Time duration check)
        duration = df.index[-1] - df.index[0]
        min_required_delta = pd.Timedelta(minutes=self.min_history_minutes)
        if duration < min_required_delta:
            raise ValueError(
                f"Lịch sử dữ liệu chỉ dài {duration.total_seconds() / 60:.1f} phút "
                f"(từ {df.index[0]} đến {df.index[-1]}), không đủ tối thiểu {self.min_history_minutes} phút."
            )

        # Đảm bảo các cột ngữ cảnh tối thiểu
        if "humidity" not in df.columns:
            df["humidity"] = 70.0
        if "pressure" not in df.columns:
            df["pressure"] = 1013.25
        if "rain_raw" not in df.columns:
            df["rain_raw"] = 0.0

        # Resample về lưới 1 phút (1min grid)
        # Bất kể cảm biến gửi 5s, 10s hay 1min, toàn bộ được đưa về trung bình 1 phút
        df_1min = df[["temperature", "humidity", "pressure", "rain_raw"]].resample("1min").mean()

        # Nội suy tuyến tính cho các khoảng trống ngắn, sau đó ffill/bfill
        df_1min = df_1min.interpolate(method="linear").ffill().bfill()

        # Giới hạn vật lý an toàn
        df_1min["temperature"] = df_1min["temperature"].clip(-10.0, 60.0)
        df_1min["humidity"]    = df_1min["humidity"].clip(0.0, 100.0)
        df_1min["pressure"]    = df_1min["pressure"].clip(900.0, 1100.0)

        if len(df_1min) < self.min_history_minutes:
            raise ValueError(
                f"Sau khi resample 1min chỉ được {len(df_1min)} bước, cần ít nhất {self.min_history_minutes} bước."
            )

        return df_1min

    def _load_schema(self) -> None:
        """Nạp danh sách đặc trưng từ feature_schema.json nếu có."""
        schema_path = self.model_dir / "feature_schema.json"
        if schema_path.exists():
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._expected_features = data.get("feature_names", [])
                    logger.info("Đã nạp feature schema (%d đặc trưng) từ %s", len(self._expected_features), schema_path)
            except Exception as exc:
                logger.warning("Không thể đọc feature_schema.json: %s", exc)

    def _load_models(self) -> None:
        """
        Nạp model .joblib tốt nhất cho từng horizon.
        Thứ tự ưu tiên: MODEL_PRIORITY = [XGBoost, RandomForest, Lasso, Ridge].
        """
        if not self.model_dir.exists():
            logger.warning("Thư mục model '%s' không tồn tại.", self.model_dir)
            return

        for h in HORIZONS:
            for model_name in self.model_priority:
                path = self.model_dir / f"{model_name}_h{h}min.joblib"
                if path.exists():
                    try:
                        loaded_model = joblib.load(path)
                        self._models[h]      = loaded_model
                        self._model_names[h] = model_name
                        logger.info("Loaded +%dmin model: %s ← %s", h, model_name, path.name)

                        # Nếu chưa có schema từ JSON, lấy trực tiếp từ feature_names_in_ của model
                        if not self._expected_features and hasattr(loaded_model, "feature_names_in_"):
                            self._expected_features = [str(col) for col in loaded_model.feature_names_in_]
                            logger.info("Trích xuất feature schema từ model '%s': %d đặc trưng", model_name, len(self._expected_features))
                        break
                    except Exception as exc:
                        logger.error("Lỗi load model '%s': %s", path, exc)

    def _persistence_fallback(
        self,
        recent_data: Any,
        error_msg:   str,
        t_start:     float,
    ) -> TemperatureForecast:
        """Fallback về Persistence Baseline khi có lỗi hoặc dữ liệu chưa đủ dài."""
        latency_ms = (time.perf_counter() - t_start) * 1000
        t_current = float("nan")

        try:
            if isinstance(recent_data, pd.DataFrame) and "temperature" in recent_data.columns:
                t_current = float(recent_data["temperature"].dropna().iloc[-1])
            elif isinstance(recent_data, list) and len(recent_data) > 0:
                last = recent_data[-1]
                if isinstance(last, dict) and "temperature" in last:
                    t_current = float(last["temperature"])
        except Exception:
            pass

        if np.isnan(t_current):
            t_current = 25.0

        return TemperatureForecast(
            t_plus_10min = round(t_current, 3),
            t_plus_30min = round(t_current, 3),
            t_plus_60min = round(t_current, 3),
            model_used   = "Persistence",
            latency_ms   = round(latency_ms, 2),
            confidence   = "fallback",
            error_msg    = error_msg[:200],
        )


# ---------------------------------------------------------------------------
# Hàm helper cấp cao — TV1 import trực tiếp (one-liner)
# ---------------------------------------------------------------------------
_engine_instance: Optional[TemperatureInferenceEngine] = None


def get_engine(model_dir: Union[str, Path] = MODEL_DIR) -> TemperatureInferenceEngine:
    """Lấy singleton instance của TemperatureInferenceEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = TemperatureInferenceEngine(model_dir=model_dir)
    return _engine_instance


def predict_forecast(
    recent_data: Union[pd.DataFrame, List[Dict[str, Any]]],
    model_dir:   Union[str, Path] = MODEL_DIR,
) -> Dict[str, Any]:
    """
    Hàm API chuẩn bàn giao cho TV1 (Backend / BE-05).
    Được gọi trực tiếp trong endpoint GET /api/weather/forecast.

    Args:
        recent_data: Danh sách các bản ghi cảm biến gần nhất (>= 90 phút).
        model_dir:   Thư mục model.

    Returns:
        Dict JSON-serializable chứa temperature_forecast, model_used, latency_ms, confidence.
    """
    engine = get_engine(model_dir)
    return engine.predict(recent_data).to_dict()


def predict_temperature_forecast(
    recent_data: Union[pd.DataFrame, List[Dict[str, Any]]],
    model_dir:   Union[str, Path] = MODEL_DIR,
) -> Dict[str, Any]:
    """Alias cho predict_forecast()."""
    return predict_forecast(recent_data, model_dir)


def predict_combined_forecast(
    recent_data:      Union[pd.DataFrame, List[Dict[str, Any]]],
    rain_probability: Optional[Dict[str, float]] = None,
    model_dir:        Union[str, Path] = MODEL_DIR,
) -> Dict[str, Any]:
    """Hàm tổng hợp kết hợp nhiệt độ (TV2) và xác suất mưa (TV3) cho TV1."""
    engine = get_engine(model_dir)
    return engine.predict_combined(recent_data, rain_probability).to_dict()
