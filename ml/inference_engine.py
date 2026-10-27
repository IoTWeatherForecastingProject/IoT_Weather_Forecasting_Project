"""
ML-06: Forecast Inference Engine
==================================
Module inference khép kín, độc lập, dễ import cho TV1 nhúng vào REST API.

Giao diện chuẩn bàn giao TV1 → TV3:
    predict_temperature_forecast(recent_data) → TemperatureForecast
    predict_combined_forecast(recent_data)    → CombinedForecast  ← TV1 dùng

Kiến trúc:
    recent_data (DataFrame/dict) 
        → TemperatureInferenceEngine.predict()
        → TemperatureForecast(t10, t30, t60, model_used, latency_ms)

Tính năng:
    - Auto-load model tốt nhất đã train (theo thứ tự ưu tiên: XGBoost → RF → Ridge)
    - Preprocessing pipeline tích hợp sẵn (không cần gọi ML-01 riêng)
    - Feature engineering inline (không cần gọi ML-02 riêng)
    - Fallback graceful: nếu model lỗi → dùng Persistence Baseline
    - Validation đầu vào chặt chẽ (ValueError có message rõ ràng)
    - Thread-safe (dùng được trong FastAPI async context)
    - Đóng gói đầu ra chuẩn JSON-serializable (dataclass + to_dict())

Interface contract với TV1 (FastAPI endpoint BE-05):
    POST /api/weather/forecast
    Body: {"recent_data": [...]}  # list of dicts hoặc DataFrame

Interface contract với TV3 (rain model):
    CombinedForecast chứa slot rain_probability (TV3 điền vào sau)

Tác giả: TV2 — Time-Series AI Engineer
Dự án:   IoT Local Weather Forecasting
"""

from __future__ import annotations

import logging
import time
import warnings
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import joblib
import numpy as np
import pandas as pd

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

# Minimum số bước lịch sử cần thiết (bằng lag lớn nhất + rolling lớn nhất)
MIN_HISTORY_STEPS = 90   # 90 phút


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
    from ml.inference_engine import TemperatureInferenceEngine

    engine = TemperatureInferenceEngine()   # load 1 lần lúc startup

    @app.get("/api/weather/forecast")
    async def get_forecast():
        recent_df = db.get_last_90_minutes()   # DataFrame từ PostgreSQL
        forecast  = engine.predict(recent_df)
        return forecast.to_dict()

    Args:
        model_dir:     Thư mục chứa .joblib model (mặc định: ml/models/).
        model_priority: Danh sách tên model theo thứ tự ưu tiên.
    """

    def __init__(
        self,
        model_dir:      Union[str, Path] = MODEL_DIR,
        model_priority: List[str]        = MODEL_PRIORITY,
    ) -> None:
        self.model_dir      = Path(model_dir)
        self.model_priority = model_priority
        self._models: Dict[int, Any]  = {}   # horizon → model object
        self._model_names: Dict[int, str] = {}
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
                         Cần ít nhất MIN_HISTORY_STEPS = 90 hàng.

        Returns:
            TemperatureForecast với t_plus_10/30/60min, model_used, latency_ms.

        Raises:
            ValueError: Nếu dữ liệu đầu vào không hợp lệ.
        """
        t_start = time.perf_counter()

        try:
            # 1. Validate & chuẩn hóa đầu vào
            df = self._validate_and_normalize(recent_data)

            # 2. Preprocessing nhanh (inline, không cần gọi ML-01)
            df = self._quick_preprocess(df)

            # 3. Feature engineering inline (không cần gọi ML-02)
            X = self._extract_features(df)

            # 4. Predict từng horizon
            preds: Dict[int, float] = {}
            for h in HORIZONS:
                if h in self._models:
                    raw_pred = float(self._models[h].predict(X)[0])
                    # Clamp vật lý: nhiệt độ phải trong [-10, 60]°C
                    preds[h] = float(np.clip(raw_pred, -10.0, 60.0))
                else:
                    # Fallback: Persistence
                    preds[h] = float(df["temperature"].iloc[-1])
                    logger.warning(
                        "Model cho horizon +%dm không có — dùng Persistence.", h
                    )

            latency_ms = (time.perf_counter() - t_start) * 1000
            model_name = self._model_names.get(HORIZONS[0], "Persistence")

            return TemperatureForecast(
                t_plus_10min = round(preds[10], 3),
                t_plus_30min = round(preds[30], 3),
                t_plus_60min = round(preds[60], 3),
                model_used   = model_name,
                latency_ms   = round(latency_ms, 2),
                confidence   = "normal",
            )

        except ValueError as exc:
            # Lỗi validation đầu vào → Persistence fallback
            logger.error("Validation error: %s", exc)
            return self._persistence_fallback(recent_data, str(exc), t_start)

        except Exception as exc:
            # Lỗi không dự đoán được → Persistence fallback + log
            logger.error("Inference error: %s", exc, exc_info=True)
            return self._persistence_fallback(recent_data, str(exc), t_start)

    def predict_combined(
        self,
        recent_data: Union[pd.DataFrame, List[Dict[str, Any]]],
        rain_probability: Optional[Dict[str, float]] = None,
    ) -> CombinedForecast:
        """
        Hàm tổng hợp cho TV1 — gọi predict() và đóng gói cùng rain_probability từ TV3.

        Args:
            recent_data:      Dữ liệu lịch sử (giống predict()).
            rain_probability: {'p_10min': 0.3, 'p_30min': 0.65, 'p_60min': 0.8}
                              Điền bởi TV3, None nếu chưa có.

        Returns:
            CombinedForecast chứa cả nhiệt độ + mưa.
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

        Returns:
            Dict với status, models_loaded, horizons_available.
        """
        return {
            "status":            "ok" if self._models else "degraded",
            "models_loaded":     {
                h: self._model_names.get(h, "None")
                for h in HORIZONS
            },
            "horizons_available": list(self._models.keys()),
            "min_history_steps": MIN_HISTORY_STEPS,
        }

    # ------------------------------------------------------------------
    # Private — preprocessing & feature extraction inline
    # ------------------------------------------------------------------

    def _validate_and_normalize(
        self,
        recent_data: Union[pd.DataFrame, List[Dict]],
    ) -> pd.DataFrame:
        """
        Validate đầu vào và chuẩn hóa thành DataFrame với DatetimeIndex.
        Ném ValueError nếu dữ liệu không đủ hoặc thiếu cột bắt buộc.
        """
        # Chuyển list[dict] → DataFrame
        if isinstance(recent_data, list):
            if len(recent_data) == 0:
                raise ValueError("recent_data rỗng.")
            df = pd.DataFrame(recent_data)
        elif isinstance(recent_data, pd.DataFrame):
            df = recent_data.copy()
        else:
            raise TypeError(
                f"recent_data phải là DataFrame hoặc list[dict], nhận: {type(recent_data)}"
            )

        # Kiểm tra cột bắt buộc
        required = ["temperature"]
        missing  = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(
                f"Thiếu cột bắt buộc: {missing}. "
                f"Cần ít nhất: {required}"
            )

        # Parse timestamp → DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            ts_col = next(
                (c for c in ["timestamp", "time", "datetime", "created_at"]
                 if c in df.columns),
                None
            )
            if ts_col:
                df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
                df = df.set_index(ts_col)
            else:
                # Không có timestamp → tạo index giả (1min interval)
                df.index = pd.date_range(
                    end=pd.Timestamp.utcnow(),
                    periods=len(df), freq="1min"
                )
                logger.warning(
                    "Không có cột timestamp — tạo index giả 1min interval."
                )

        df = df.sort_index()

        # Kiểm tra số hàng tối thiểu
        if len(df) < MIN_HISTORY_STEPS:
            raise ValueError(
                f"Cần ít nhất {MIN_HISTORY_STEPS} bước lịch sử, "
                f"nhận được {len(df)} hàng."
            )

        return df

    def _quick_preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Tiền xử lý nhanh inline (không dùng ML-01 class để tránh overhead):
            - Fill NaN bằng forward fill
            - Clamp giá trị vật lý
        """
        bounds = {
            "temperature": (-10.0, 60.0),
            "humidity":    (0.0,  100.0),
            "pressure":    (900.0, 1100.0),
        }

        for col, (lo, hi) in bounds.items():
            if col in df.columns:
                df[col] = df[col].clip(lo, hi)
                df[col] = df[col].ffill().bfill()

        return df

    def _extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Feature extraction inline — phải khớp với feature set lúc training (ML-02).
        Lấy hàng CUỐI CÙNG (t hiện tại) để làm vector đặc trưng cho inference.

        Returns:
            X: DataFrame 1 hàng × n_features (cùng cột với lúc training).
        """
        T = df["temperature"]
        features: Dict[str, float] = {}

        # [A] Lag features
        for k in [1, 2, 3, 6, 10, 30]:
            if len(T) > k:
                features[f"T_lag_{k}"] = float(T.iloc[-1 - k])
            else:
                features[f"T_lag_{k}"] = float(T.iloc[0])

        # [B] Delta features
        for k in [1, 5, 10]:
            if len(T) > k:
                features[f"dT_{k}min"] = float(T.iloc[-1] - T.iloc[-1 - k])
            else:
                features[f"dT_{k}min"] = 0.0

        # [C] Rolling stats (shift-1 để tránh leakage — dùng [:-1] slice)
        for w in [6, 10, 30, 60]:
            window_data = T.iloc[max(0, -w-1):-1]
            if len(window_data) >= 1:
                features[f"T_roll_mean_{w}m"] = float(window_data.mean())
                features[f"T_roll_std_{w}m"]  = float(window_data.std()) \
                                                  if len(window_data) > 1 else 0.0
            else:
                features[f"T_roll_mean_{w}m"] = float(T.iloc[-1])
                features[f"T_roll_std_{w}m"]  = 0.0

        # [D] Cyclic time encoding
        ts = df.index[-1]
        hour_float = ts.hour + ts.minute / 60.0
        features["hour_sin"] = float(np.sin(2 * np.pi * hour_float / 24.0))
        features["hour_cos"] = float(np.cos(2 * np.pi * hour_float / 24.0))
        dow = float(ts.dayofweek)
        features["dow_sin"]  = float(np.sin(2 * np.pi * dow / 7.0))
        features["dow_cos"]  = float(np.cos(2 * np.pi * dow / 7.0))

        # [E] Context features (humidity, pressure)
        for ctx_col in ["humidity", "pressure"]:
            if ctx_col in df.columns:
                features[ctx_col] = float(df[ctx_col].iloc[-1])
                for k in [1, 6]:
                    if len(df) > k:
                        features[f"{ctx_col}_lag_{k}"] = float(
                            df[ctx_col].iloc[-1 - k]
                        )
                    else:
                        features[f"{ctx_col}_lag_{k}"] = features[ctx_col]
                features[f"d{ctx_col}_1min"] = float(
                    df[ctx_col].iloc[-1] - df[ctx_col].iloc[-2]
                ) if len(df) > 1 else 0.0

        X = pd.DataFrame([features])
        return X

    def _persistence_fallback(
        self,
        recent_data: Any,
        error_msg:   str,
        t_start:     float,
    ) -> TemperatureForecast:
        """
        Fallback về Persistence Baseline khi có lỗi.
        Luôn trả về kết quả (không raise exception) để API không bị crash.
        """
        latency_ms = (time.perf_counter() - t_start) * 1000
        t_current = float("nan")

        try:
            if isinstance(recent_data, pd.DataFrame) and "temperature" in recent_data.columns:
                t_current = float(recent_data["temperature"].iloc[-1])
            elif isinstance(recent_data, list) and len(recent_data) > 0:
                last = recent_data[-1]
                if isinstance(last, dict) and "temperature" in last:
                    t_current = float(last["temperature"])
        except Exception:
            pass

        if np.isnan(t_current):
            t_current = 28.0   # Giá trị mặc định hợp lý cho khí hậu VN

        return TemperatureForecast(
            t_plus_10min = t_current,
            t_plus_30min = t_current,
            t_plus_60min = t_current,
            model_used   = "Persistence (fallback)",
            latency_ms   = round(latency_ms, 2),
            confidence   = "fallback",
            error_msg    = error_msg[:200],   # Truncate
        )

    def _load_models(self) -> None:
        """
        Load model .joblib tốt nhất có thể cho từng horizon.
        Thứ tự ưu tiên: MODEL_PRIORITY = [XGBoost, RF, Lasso, Ridge].
        """
        if not self.model_dir.exists():
            logger.warning(
                "Thư mục model '%s' không tồn tại. "
                "Sẽ dùng Persistence fallback.",
                self.model_dir
            )
            return

        for h in HORIZONS:
            for model_name in self.model_priority:
                path = self.model_dir / f"{model_name}_h{h}min.joblib"
                if path.exists():
                    try:
                        self._models[h]      = joblib.load(path)
                        self._model_names[h] = model_name
                        logger.info(
                            "Loaded +%dmin model: %s ← %s",
                            h, model_name, path.name
                        )
                        break   # Đã tìm được → chuyển sang horizon tiếp
                    except Exception as exc:
                        logger.error(
                            "Lỗi load model '%s': %s — thử model tiếp theo.",
                            path, exc
                        )

        if not self._models:
            logger.warning(
                "Không load được model nào! Engine sẽ dùng Persistence fallback."
            )
        else:
            logger.info(
                "Inference Engine sẵn sàng: %d/%d horizons có model.",
                len(self._models), len(HORIZONS)
            )


# ---------------------------------------------------------------------------
# Hàm helper cấp cao — TV1 import trực tiếp (one-liner)
# ---------------------------------------------------------------------------

# Singleton engine — khởi tạo 1 lần, tái dùng nhiều lần
_engine_instance: Optional[TemperatureInferenceEngine] = None


def get_engine(model_dir: Union[str, Path] = MODEL_DIR) -> TemperatureInferenceEngine:
    """
    Lấy singleton instance của TemperatureInferenceEngine.
    Khởi tạo lần đầu khi được gọi (lazy init).

    TV1 dùng trong FastAPI lifespan:
    ---------------------------------
    from ml.inference_engine import get_engine

    engine = get_engine()

    @app.get("/api/weather/forecast")
    async def forecast(recent_data: list):
        return engine.predict(recent_data).to_dict()
    """
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = TemperatureInferenceEngine(model_dir=model_dir)
    return _engine_instance


def predict_temperature_forecast(
    recent_data: Union[pd.DataFrame, List[Dict]],
    model_dir:   Union[str, Path] = MODEL_DIR,
) -> Dict[str, Any]:
    """
    Hàm cấp cao TV1 có thể gọi trực tiếp — trả về dict sẵn sàng JSON response.

    Args:
        recent_data: DataFrame hoặc list[dict] >= 90 hàng.
        model_dir:   Thư mục chứa model (mặc định: ml/models/).

    Returns:
        Dict JSON-serializable cho FastAPI response.

    Ví dụ (TV1 dùng):
    -----------------
    from ml.inference_engine import predict_temperature_forecast
    result = predict_temperature_forecast(recent_df)
    # result = {
    #   "temperature_forecast": {"t_plus_10min": 29.3, "t_plus_30min": 30.1, ...},
    #   "model_used": "XGBoost",
    #   "latency_ms": 4.5,
    #   "confidence": "normal",
    # }
    """
    engine = get_engine(model_dir)
    return engine.predict(recent_data).to_dict()


def predict_combined_forecast(
    recent_data:      Union[pd.DataFrame, List[Dict]],
    rain_probability: Optional[Dict[str, float]] = None,
    model_dir:        Union[str, Path] = MODEL_DIR,
) -> Dict[str, Any]:
    """
    Hàm tổng hợp TV1 dùng — kết hợp nhiệt độ (TV2) + mưa (TV3).

    Args:
        recent_data:      DataFrame/list[dict] >= 90 hàng.
        rain_probability: {'p_10min': float, 'p_30min': float, 'p_60min': float}
                          (TV3 tính toán và truyền vào).
        model_dir:        Thư mục chứa model.

    Returns:
        Dict JSON-serializable chứa cả nhiệt độ + xác suất mưa.
    """
    engine = get_engine(model_dir)
    return engine.predict_combined(recent_data, rain_probability).to_dict()


# ---------------------------------------------------------------------------
# Script chạy thử nhanh
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys, json as _json
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from ml.preprocessing import generate_sample_iot_data

    print("=" * 65)
    print("  ML-06: Forecast Inference Engine — Quick Test")
    print("=" * 65)

    # 1. Khởi tạo engine
    print("\n[1/4] Khởi tạo TemperatureInferenceEngine...")
    engine = TemperatureInferenceEngine()
    hc = engine.health_check()
    print(f"  Health: {hc}")

    # 2. Tạo dữ liệu giả 2 giờ (120 điểm) — mô phỏng 120 bản ghi từ DB
    print("\n[2/4] Tạo dữ liệu đầu vào giả (120 phút)...")
    df_sample = generate_sample_iot_data(n_minutes=120, seed=7)
    df_sample = df_sample.set_index("timestamp")
    print(f"  Shape: {df_sample.shape}")

    # 3. Predict từ DataFrame
    print("\n[3/4] Predict từ DataFrame...")
    forecast = engine.predict(df_sample)
    print(f"  Model: {forecast.model_used}")
    print(f"  +10min: {forecast.t_plus_10min:.2f}°C")
    print(f"  +30min: {forecast.t_plus_30min:.2f}°C")
    print(f"  +60min: {forecast.t_plus_60min:.2f}°C")
    print(f"  Latency: {forecast.latency_ms:.1f}ms")
    print(f"  Confidence: {forecast.confidence}")

    # 4. CombinedForecast (với rain_probability giả từ TV3)
    print("\n[4/4] predict_combined_forecast (kết hợp TV3)...")
    rain_prob_from_tv3 = {
        "p_10min": 0.12,
        "p_30min": 0.35,
        "p_60min": 0.58,
    }
    combined = engine.predict_combined(df_sample, rain_prob_from_tv3)
    print(_json.dumps(combined.to_dict(), indent=2, ensure_ascii=False))

    # 5. Test fallback: ít data
    print("\n[5/4] Test fallback khi data quá ít...")
    tiny_df = generate_sample_iot_data(n_minutes=5, seed=1)
    tiny_df = tiny_df.set_index("timestamp")
    fallback = engine.predict(tiny_df)
    print(f"  Confidence: {fallback.confidence}")
    print(f"  Error msg: {fallback.error_msg}")

    print("\n✅ ML-06 Inference Engine OK!")
