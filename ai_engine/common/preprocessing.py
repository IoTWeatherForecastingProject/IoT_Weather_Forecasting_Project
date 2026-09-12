"""
==============================================================================
MODULE 3: COMMON TIME-SERIES PREPROCESSING PIPELINE
Phụ trách: TV2 (Time-Series AI Engineer)
Các Task: ML-01 (TASK.md)
==============================================================================
"""

import logging
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.stattools import adfuller
except ImportError:
    adfuller = None

logger = logging.getLogger(__name__)


class TimeSeriesPreprocessor:
    def __init__(self, freq: str = "1min"):
        self.freq = freq

    def clean_and_resample(self, df: pd.DataFrame, time_col: str = "timestamp") -> pd.DataFrame:
        """
        Chuẩn hóa chuỗi thời gian:
        1. Chuyển đổi timestamp sang DatetimeIndex.
        2. Sắp xếp thứ tự thời gian tăng dần và loại bỏ trùng lặp.
        3. Resample theo tần suất cố định và nội suy missing value bằng linear/spline.
        """
        data = df.copy()
        if time_col in data.columns:
            data[time_col] = pd.to_datetime(data[time_col])
            data = data.sort_values(time_col).drop_duplicates(subset=[time_col])
            data = data.set_index(time_col)

        # Resample đồng bộ chu kỳ đo
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        resampled = data[numeric_cols].resample(self.freq).mean()

        # Nội suy giá trị thiếu (Linear Interpolation với giới hạn tối đa 5 bước)
        resampled = resampled.interpolate(method="time", limit=5)
        # Điền các giá trị đầu/cuối bằng forward/backward fill nếu còn sót
        resampled = resampled.bfill().ffill()

        return resampled

    def filter_outliers_iqr(self, series: pd.Series, factor: float = 1.5) -> pd.Series:
        """Loại bỏ ngoại lai bằng phương pháp IQR (Interquartile Range)."""
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - factor * iqr
        upper_bound = q3 + factor * iqr
        return series.clip(lower=lower_bound, upper=upper_bound)

    def filter_outliers_zscore(self, series: pd.Series, threshold: float = 3.0) -> pd.Series:
        """Loại bỏ đột biến ngoại lai bằng 3-Sigma Z-score."""
        mean = series.mean()
        std = series.std()
        if std == 0 or np.isnan(std):
            return series
        z_scores = (series - mean) / std
        return series.mask(z_scores.abs() > threshold, np.nan).interpolate(method="linear")

    @staticmethod
    def test_stationarity(series: pd.Series, name: str = "Series") -> Dict[str, Any]:
        """Kiểm định tính dừng của chuỗi thời gian bằng Augmented Dickey-Fuller (ADF Test)."""
        clean_series = series.dropna()
        if len(clean_series) < 10:
            return {"status": "insufficient_data"}

        if adfuller is None:
            return {"status": "statsmodels_not_installed", "message": "Vui long pip install statsmodels"}

        result = adfuller(clean_series, autolag="AIC")
        p_value = result[1]
        is_stationary = p_value < 0.05

        return {
            "feature": name,
            "adf_statistic": round(result[0], 4),
            "p_value": round(p_value, 5),
            "critical_values": {k: round(v, 4) for k, v in result[4].items()},
            "is_stationary": bool(is_stationary),
            "interpretation": "Chuỗi dừng (Stationary)" if is_stationary else "Chuỗi không dừng (Non-stationary, can lay sai phan)"
        }
