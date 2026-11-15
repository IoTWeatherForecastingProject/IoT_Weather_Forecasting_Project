"""
==============================================================================
MODULE 4: FEATURE ENGINEERING & NHÃN TƯƠNG LAI CHO DỰ BÁO XÁC SUẤT MƯA
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-01 (TASK.md)
==============================================================================

Nguyên tắc chống rò rỉ dữ liệu (data leakage):
- Feature tại thời điểm t chỉ dùng dữ liệu có timestamp <= t.
  Resample dùng bin đóng bên phải (t - freq, t] và gán nhãn bằng mốc t;
  giá trị thiếu chỉ được forward-fill (quá khứ -> hiện tại) có giới hạn,
  không nội suy hay backward-fill.
- Nhãn horizon h tại t: "có mưa trong khoảng (t, t + h]", KHÔNG tính t.
  Nếu không đủ dữ liệu tương lai để kết luận thì nhãn là NaN (không ép về 0).
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_FREQ = "1min"
DEFAULT_FFILL_LIMIT = 2  # số bước tối đa được forward-fill khi mất mẫu

# Cửa sổ (phút) cho các feature chênh lệch theo thời gian
PRESSURE_DIFF_MINUTES = (15, 30, 60)
HUMIDITY_DIFF_MINUTES = (15, 30, 60)
TEMPERATURE_DIFF_MINUTES = (30,)
RAIN_RAW_ROLL_MINUTES = 10

# Lịch sử tối thiểu (phút) để mọi feature tại t đều xác định
MAX_LOOKBACK_MINUTES = max(
    max(PRESSURE_DIFF_MINUTES), max(HUMIDITY_DIFF_MINUTES),
    max(TEMPERATURE_DIFF_MINUTES), RAIN_RAW_ROLL_MINUTES,
)

ATMOSPHERIC_FEATURES: List[str] = (
    ["temperature", "humidity", "pressure", "dew_point_approx"]
    + [f"press_diff_{m}m" for m in PRESSURE_DIFF_MINUTES]
    + [f"hum_diff_{m}m" for m in HUMIDITY_DIFF_MINUTES]
    + [f"temp_diff_{m}m" for m in TEMPERATURE_DIFF_MINUTES]
)
RAIN_STATE_FEATURES: List[str] = ["rain_detected", "rain_raw", f"rain_raw_roll_mean_{RAIN_RAW_ROLL_MINUTES}m"]

SENSOR_MEAN_COLS = ("temperature", "humidity", "pressure", "rain_raw")


def freq_to_timedelta(freq: str) -> pd.Timedelta:
    return pd.Timedelta(pd.tseries.frequencies.to_offset(freq))


def minutes_to_steps(minutes: int, freq: str) -> int:
    """Đổi khoảng thời gian (phút) sang số bước của lưới thời gian đều `freq`."""
    step = freq_to_timedelta(freq)
    ratio = pd.Timedelta(minutes=minutes) / step
    if ratio < 1 or not float(ratio).is_integer():
        raise ValueError(f"{minutes} phut khong chia het cho tan suat {freq}")
    return int(ratio)


def _require_regular_grid(index: pd.Index, freq: str) -> None:
    """Các phép shift/rolling theo số bước chỉ đúng thời gian thực khi lưới đều."""
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("Du lieu phai co DatetimeIndex tren luoi thoi gian deu")
    if len(index) < 2:
        return
    if not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("DatetimeIndex phai tang dan va khong trung lap")
    if not (index.to_series().diff().iloc[1:] == freq_to_timedelta(freq)).all():
        raise ValueError(f"DatetimeIndex khong deu theo tan suat {freq}; hay dung resample_to_grid() truoc")


def resample_to_grid(
    raw_df: pd.DataFrame,
    freq: str = DEFAULT_FREQ,
    time_col: str = "timestamp",
    ffill_limit: int = DEFAULT_FFILL_LIMIT,
) -> pd.DataFrame:
    """
    Chuẩn hóa bản ghi thô (timestamp bất kỳ) về lưới thời gian đều theo kiểu nhân quả.

    - Bin (t - freq, t] gán nhãn t: giá trị tại t chỉ gồm mẫu đo tới t.
    - Cảm biến liên tục: trung bình trong bin. rain_detected: max trong bin.
    - `rain_observed`: rain_detected chưa fill, dùng để tạo nhãn (thiếu = NaN, không phải 0).
    - Các cột feature được forward-fill tối đa `ffill_limit` bước; khoảng trống dài hơn giữ NaN.
    """
    if time_col not in raw_df.columns:
        raise ValueError(f"Thieu cot thoi gian '{time_col}'")

    data = raw_df.copy()
    data[time_col] = pd.to_datetime(data[time_col], utc=True, errors="coerce")
    n_bad_ts = int(data[time_col].isna().sum())
    if n_bad_ts:
        logger.warning("[RAIN FEATURES] Bo %d ban ghi co timestamp khong hop le", n_bad_ts)
    data = data.dropna(subset=[time_col]).sort_values(time_col).set_index(time_col)

    agg: Dict[str, str] = {}
    for col in SENSOR_MEAN_COLS:
        if col in data.columns:
            agg[col] = "mean"
    if "rain_detected" in data.columns:
        agg["rain_detected"] = "max"
    if not agg:
        raise ValueError("Khong co cot cam bien nao de resample")

    numeric = data[list(agg)].apply(pd.to_numeric, errors="coerce")
    grid = numeric.resample(freq, closed="right", label="right").agg(agg)

    if "rain_detected" in grid.columns:
        grid["rain_observed"] = grid["rain_detected"]
    for col in agg:
        grid[col] = grid[col].ffill(limit=ffill_limit)

    return grid


def extract_rain_features(
    df: pd.DataFrame,
    freq: str = DEFAULT_FREQ,
    include_rain_state: bool = True,
) -> pd.DataFrame:
    """
    Trích xuất đặc trưng khí quyển báo hiệu mưa trên lưới thời gian đều (DatetimeIndex).

    - Tốc độ tụt áp suất: press_diff_{15,30,60}m
    - Tốc độ tăng độ ẩm: hum_diff_{15,30,60}m
    - Thay đổi nhiệt độ: temp_diff_30m
    - Điểm sương xấp xỉ: Td ≈ T - (100 - RH) / 5
    - (tùy chọn) Trạng thái cảm biến mưa tại t: rain_detected, rain_raw, trung bình trượt rain_raw

    Mọi feature tại t chỉ dùng các hàng có timestamp <= t. Trả về bản sao df kèm cột feature mới.
    """
    _require_regular_grid(df.index, freq)
    data = df.copy()

    def lagged_diff(col: str, minutes: int) -> pd.Series:
        return data[col] - data[col].shift(minutes_to_steps(minutes, freq))

    if "pressure" in data.columns:
        for m in PRESSURE_DIFF_MINUTES:
            data[f"press_diff_{m}m"] = lagged_diff("pressure", m)
    if "humidity" in data.columns:
        for m in HUMIDITY_DIFF_MINUTES:
            data[f"hum_diff_{m}m"] = lagged_diff("humidity", m)
    if "temperature" in data.columns:
        for m in TEMPERATURE_DIFF_MINUTES:
            data[f"temp_diff_{m}m"] = lagged_diff("temperature", m)
    if "temperature" in data.columns and "humidity" in data.columns:
        data["dew_point_approx"] = data["temperature"] - (100.0 - data["humidity"]) / 5.0

    if include_rain_state and "rain_raw" in data.columns:
        steps = minutes_to_steps(RAIN_RAW_ROLL_MINUTES, freq)
        # min_periods = steps: chỉ tính khi đủ cửa sổ, không tự rút ngắn cửa sổ
        data[f"rain_raw_roll_mean_{RAIN_RAW_ROLL_MINUTES}m"] = data["rain_raw"].rolling(steps, min_periods=steps).mean()

    return data


def select_feature_columns(feat_df: pd.DataFrame, include_rain_state: bool = True) -> List[str]:
    """
    Danh sách feature theo thứ tự cố định. Chỉ bỏ feature khi CỘT CẢM BIẾN NGUỒN không có
    (ví dụ firmware không gửi rain_raw); feature NaN do thiếu lịch sử thì vẫn giữ để mẫu đó
    bị loại, tránh âm thầm đổi bộ feature khi dữ liệu ngắn.
    """
    prefixes = {"press_diff_": ("pressure",), "hum_diff_": ("humidity",), "temp_diff_": ("temperature",),
                "dew_point_approx": ("temperature", "humidity"), "rain_raw": ("rain_raw",)}

    def source_available(col: str) -> bool:
        sources = next((s for p, s in prefixes.items() if col.startswith(p)), (col,))
        return all(s in feat_df.columns and feat_df[s].notna().any() for s in sources)

    candidates = ATMOSPHERIC_FEATURES + (RAIN_STATE_FEATURES if include_rain_state else [])
    cols = [c for c in candidates if c in feat_df.columns and source_available(c)]
    missing_required = [c for c in ATMOSPHERIC_FEATURES + ["rain_detected"] if c in candidates and c not in cols]
    if missing_required:
        raise ValueError(f"Thieu cot cam bien bat buoc de tao feature mua: {missing_required}")
    dropped = [c for c in candidates if c not in cols]
    if dropped:
        logger.info("[RAIN FEATURES] Khong dung feature (khong co cot nguon): %s", dropped)
    return cols


def make_future_rain_labels(rain: pd.Series, horizon_minutes: int, freq: str = DEFAULT_FREQ) -> pd.Series:
    """
    Nhãn tương lai: 1 nếu có mưa trong (t, t + horizon], 0 nếu đã quan sát đủ toàn bộ khoảng
    mà không có mưa, NaN nếu không đủ dữ liệu để kết luận (đuôi chuỗi hoặc mất mẫu).

    `rain` phải là chuỗi rain_detected CHƯA fill (cột `rain_observed`) trên lưới đều.
    Mưa tại chính t không được tính vào nhãn của t.
    """
    _require_regular_grid(rain.index, freq)
    steps = minutes_to_steps(horizon_minutes, freq)

    future = rain.astype(float).shift(-1)  # hàng i chứa giá trị tại t_{i+1}
    indexer = pd.api.indexers.FixedForwardWindowIndexer(window_size=steps)
    any_rain = future.rolling(indexer, min_periods=1).max() > 0
    n_observed = future.rolling(indexer, min_periods=0).count()

    labels = pd.Series(np.nan, index=rain.index, name=f"target_rain_{horizon_minutes}m")
    labels[n_observed == steps] = 0.0
    labels[any_rain] = 1.0  # đã thấy mưa thì nhãn chắc chắn là 1 dù có mẫu thiếu
    return labels


def required_history_minutes(freq: str = DEFAULT_FREQ) -> int:
    """Số phút lịch sử tối thiểu để feature tại mốc mới nhất xác định (gồm cả bin hiện tại)."""
    return int(MAX_LOOKBACK_MINUTES + freq_to_timedelta(freq) / pd.Timedelta(minutes=1))


def build_rain_dataset(
    raw_df: pd.DataFrame,
    horizons: List[int],
    freq: str = DEFAULT_FREQ,
    ffill_limit: int = DEFAULT_FFILL_LIMIT,
    include_rain_state: bool = True,
    feature_cols: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Pipeline đầy đủ: lưới nhân quả -> feature -> nhãn từng horizon."""
    grid = resample_to_grid(raw_df, freq=freq, ffill_limit=ffill_limit)
    feat_df = extract_rain_features(grid, freq=freq, include_rain_state=include_rain_state)
    if feature_cols is None:
        feature_cols = select_feature_columns(feat_df, include_rain_state=include_rain_state)
    labels = pd.DataFrame(
        {h: make_future_rain_labels(grid["rain_observed"], h, freq) for h in horizons}
    ) if "rain_observed" in grid.columns else pd.DataFrame(index=grid.index)
    return {"features": feat_df, "feature_cols": feature_cols, "labels": labels}
