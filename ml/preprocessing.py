"""
ML-01: Common Time-Series Preprocessing Module
===============================================
Module tiền xử lý dữ liệu chuỗi thời gian dùng chung cho toàn nhóm.

Chức năng:
    - Xử lý missing values (spline / linear interpolation)
    - Khử ngoại lai (IQR fence + Z-score capping)
    - Resampling đồng bộ theo chu kỳ đo chuẩn
    - Kiểm định tính dừng ADF (Augmented Dickey-Fuller)
    - Phân tích tự tương quan ACF / PACF

Tác giả: TV2 — Time-Series AI Engineer
Dự án:   IoT Local Weather Forecasting
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
from statsmodels.tsa.stattools import adfuller, acf, pacf

# Tắt bớt FutureWarning từ statsmodels
warnings.filterwarnings("ignore", category=FutureWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hằng số mặc định của dự án
# ---------------------------------------------------------------------------
# Các cột cảm biến mặc định của trạm IoT (khớp với schema TV1)
DEFAULT_SENSOR_COLS: List[str] = [
    "temperature",   # °C — BME280
    "humidity",      # %RH — BME280
    "pressure",      # hPa — BME280
    "rain_raw",      # Analog/Digital — Rain sensor
]

# Ngưỡng vật lý hợp lệ cho từng cảm biến (min, max)
PHYSICAL_BOUNDS: Dict[str, Tuple[float, float]] = {
    "temperature": (-10.0, 60.0),   # °C, phù hợp khí hậu Việt Nam
    "humidity":    (0.0,  100.0),   # %RH
    "pressure":    (900.0, 1100.0), # hPa
    "rain_raw":    (0.0,  1023.0),  # ADC 10-bit ESP8266
}


# ---------------------------------------------------------------------------
# Dataclass cấu hình tiền xử lý
# ---------------------------------------------------------------------------
@dataclass
class PreprocessingConfig:
    """
    Cấu hình toàn bộ bước tiền xử lý.
    Thay đổi các tham số tại đây để tune pipeline mà không sửa code logic.
    """
    # Resampling
    resample_freq: str = "1min"               # Chu kỳ đo chuẩn (1 phút)

    # Xử lý missing values
    interpolation_method: Literal["spline", "linear", "time"] = "spline"
    spline_order: int = 3                     # Bậc spline khi dùng spline
    max_gap_fill: int = 10                    # Tối đa bao nhiêu điểm liên tiếp được fill
    ffill_limit_after_gap: int = 3            # Forward-fill dự phòng sau khi vẫn còn NaN

    # Khử ngoại lai
    outlier_method: Literal["iqr", "zscore", "physical"] = "iqr"
    iqr_multiplier: float = 1.5               # Hệ số IQR fence (1.5 = tiêu chuẩn)
    zscore_threshold: float = 3.0             # Ngưỡng Z-score
    outlier_action: Literal["cap", "nan"] = "nan"  # "nan" rồi interpolate sau

    # ADF test
    adf_significance: float = 0.05           # Mức ý nghĩa kiểm định tính dừng

    # ACF / PACF
    acf_nlags: int = 60                       # Số lag tự tương quan hiển thị

    # Cột cảm biến cần xử lý
    sensor_cols: List[str] = field(
        default_factory=lambda: list(DEFAULT_SENSOR_COLS)
    )


# ---------------------------------------------------------------------------
# Lớp tiền xử lý chính
# ---------------------------------------------------------------------------
class TimeSeriesPreprocessor:
    """
    Pipeline tiền xử lý chuỗi thời gian khép kín cho dữ liệu IoT thời tiết.

    Ví dụ sử dụng cơ bản:
    ----------------------
    >>> config = PreprocessingConfig(resample_freq="1min")
    >>> preprocessor = TimeSeriesPreprocessor(config)
    >>> df_clean = preprocessor.fit_transform(df_raw)
    >>> report   = preprocessor.get_report()
    """

    def __init__(self, config: Optional[PreprocessingConfig] = None) -> None:
        self.config = config or PreprocessingConfig()
        self._report: Dict = {}   # Lưu báo cáo thống kê sau mỗi bước

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Chạy toàn bộ pipeline tiền xử lý theo thứ tự:
            1. Validate đầu vào
            2. Parse & set DatetimeIndex
            3. Resampling đồng bộ
            4. Khử ngoại lai theo giới hạn vật lý
            5. Khử ngoại lai thống kê (IQR hoặc Z-score)
            6. Interpolate missing values
            7. Forward-fill dự phòng

        Args:
            df: DataFrame thô từ DB (cột 'timestamp' hoặc DatetimeIndex,
                và các cột sensor).

        Returns:
            DataFrame sạch với DatetimeIndex đều đặn theo resample_freq.
        """
        logger.info("=== BẮT ĐẦU PIPELINE TIỀN XỬ LÝ ===")

        # Bước 1: Validate
        df = self._validate_input(df)

        # Bước 2: Set index thời gian
        df = self._set_datetime_index(df)

        # Bước 3: Resampling
        df = self._resample(df)

        # Bước 4: Loại bỏ giá trị ngoài giới hạn vật lý
        df = self._remove_physical_outliers(df)

        # Bước 5: Khử ngoại lai thống kê
        df = self._remove_statistical_outliers(df)

        # Bước 6: Interpolate NaN
        df = self._interpolate_missing(df)

        # Bước 7: Forward-fill dự phòng cuối
        df = self._ffill_remaining(df)

        logger.info("=== PIPELINE HOÀN TẤT ===")
        self._build_report(df)
        return df

    def run_stationarity_tests(
        self,
        df: pd.DataFrame,
        cols: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Chạy kiểm định tính dừng ADF cho từng cột sensor.

        Args:
            df:   DataFrame đã tiền xử lý (DatetimeIndex).
            cols: Danh sách cột cần kiểm định; mặc định dùng sensor_cols.

        Returns:
            DataFrame kết quả ADF: cột ADF_stat, p-value, is_stationary.
        """
        cols = cols or self.config.sensor_cols
        results = []

        for col in cols:
            if col not in df.columns:
                logger.warning("Cột '%s' không có trong DataFrame — bỏ qua.", col)
                continue

            series = df[col].dropna()
            if len(series) < 20:
                logger.warning("Cột '%s' quá ít điểm dữ liệu để ADF test.", col)
                continue

            try:
                adf_stat, p_value, n_lags, n_obs, critical_vals, _ = adfuller(
                    series, autolag="AIC"
                )
                is_stationary = p_value < self.config.adf_significance
                results.append({
                    "column":        col,
                    "adf_statistic": round(adf_stat, 4),
                    "p_value":       round(p_value, 6),
                    "n_lags_used":   n_lags,
                    "n_obs":         n_obs,
                    "critical_1%":   round(critical_vals["1%"], 4),
                    "critical_5%":   round(critical_vals["5%"], 4),
                    "critical_10%":  round(critical_vals["10%"], 4),
                    "is_stationary": is_stationary,
                })
                status = "✅ DỪNG" if is_stationary else "❌ KHÔNG DỪNG"
                logger.info(
                    "ADF '%s': stat=%.4f, p=%.6f → %s",
                    col, adf_stat, p_value, status
                )
            except Exception as exc:
                logger.error("ADF test thất bại cho cột '%s': %s", col, exc)

        result_df = pd.DataFrame(results)
        self._report["adf_results"] = result_df
        return result_df

    def plot_acf_pacf(
        self,
        df: pd.DataFrame,
        col: str = "temperature",
        figsize: Tuple[int, int] = (14, 5),
        save_path: Optional[str] = None,
    ) -> plt.Figure:
        """
        Vẽ đồ thị ACF và PACF cho một cột chuỗi thời gian.

        Args:
            df:        DataFrame đã tiền xử lý.
            col:       Tên cột cần phân tích.
            figsize:   Kích thước figure.
            save_path: Nếu truyền đường dẫn, lưu figure ra file PNG.

        Returns:
            matplotlib Figure object.
        """
        if col not in df.columns:
            raise ValueError(f"Cột '{col}' không tồn tại trong DataFrame.")

        series = df[col].dropna()
        fig, axes = plt.subplots(1, 2, figsize=figsize)
        fig.suptitle(f"ACF & PACF — {col}", fontsize=14, fontweight="bold")

        plot_acf(series, lags=self.config.acf_nlags, ax=axes[0], alpha=0.05)
        axes[0].set_title("Autocorrelation Function (ACF)")
        axes[0].set_xlabel("Lag")

        plot_pacf(series, lags=self.config.acf_nlags // 2, ax=axes[1],
                  alpha=0.05, method="ywm")
        axes[1].set_title("Partial Autocorrelation Function (PACF)")
        axes[1].set_xlabel("Lag")

        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Đã lưu đồ thị ACF/PACF → %s", save_path)

        return fig

    def plot_preprocessing_summary(
        self,
        df_raw: pd.DataFrame,
        df_clean: pd.DataFrame,
        col: str = "temperature",
        figsize: Tuple[int, int] = (14, 7),
        save_path: Optional[str] = None,
    ) -> plt.Figure:
        """
        So sánh trực quan dữ liệu trước và sau tiền xử lý.

        Args:
            df_raw:    DataFrame gốc chưa xử lý.
            df_clean:  DataFrame đã tiền xử lý.
            col:       Cột cần vẽ.
            figsize:   Kích thước figure.
            save_path: Đường dẫn lưu figure.

        Returns:
            matplotlib Figure.
        """
        fig, axes = plt.subplots(2, 1, figsize=figsize, sharex=False)

        # Trước xử lý
        axes[0].plot(df_raw.index if hasattr(df_raw, "index") else range(len(df_raw)),
                     df_raw[col] if col in df_raw.columns else [],
                     color="tomato", linewidth=0.8, label="Raw")
        axes[0].set_title(f"[TRƯỚC] {col} — Dữ liệu thô", fontweight="bold")
        axes[0].set_ylabel("Giá trị")
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)

        # Sau xử lý
        axes[1].plot(df_clean.index, df_clean[col],
                     color="steelblue", linewidth=0.9, label="Clean")
        axes[1].set_title(f"[SAU] {col} — Sau tiền xử lý", fontweight="bold")
        axes[1].set_ylabel("Giá trị")
        axes[1].set_xlabel("Thời gian")
        axes[1].legend()
        axes[1].grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Đã lưu đồ thị so sánh → %s", save_path)

        return fig

    def get_report(self) -> Dict:
        """Trả về báo cáo thống kê tổng hợp sau khi chạy pipeline."""
        return self._report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_input(self, df: pd.DataFrame) -> pd.DataFrame:
        """Kiểm tra DataFrame đầu vào có hợp lệ không."""
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Đầu vào phải là pandas DataFrame.")
        if df.empty:
            raise ValueError("DataFrame đầu vào rỗng.")

        missing_cols = [
            c for c in self.config.sensor_cols if c not in df.columns
        ]
        if missing_cols:
            logger.warning(
                "Các cột sau không có trong DataFrame (sẽ bỏ qua): %s",
                missing_cols
            )
            # Chỉ giữ lại các cột sensor thực sự tồn tại
            self.config.sensor_cols = [
                c for c in self.config.sensor_cols if c in df.columns
            ]

        logger.info(
            "Validate OK — shape: %s, cột sensor: %s",
            df.shape, self.config.sensor_cols
        )
        return df.copy()

    def _set_datetime_index(self, df: pd.DataFrame) -> pd.DataFrame:
        """Parse cột timestamp và set làm DatetimeIndex (UTC-aware → local)."""
        if not isinstance(df.index, pd.DatetimeIndex):
            # Tìm cột timestamp phổ biến từ schema TV1
            ts_col = next(
                (c for c in ["timestamp", "time", "datetime", "created_at"]
                 if c in df.columns),
                None
            )
            if ts_col is None:
                raise KeyError(
                    "Không tìm thấy cột timestamp. "
                    "DataFrame cần có cột 'timestamp' hoặc DatetimeIndex."
                )
            df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
            df = df.set_index(ts_col)

        # Đảm bảo index được sort
        df = df.sort_index()
        logger.info(
            "DatetimeIndex: từ %s đến %s (%d điểm)",
            df.index.min(), df.index.max(), len(df)
        )
        return df

    def _resample(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Resample về chu kỳ đều đặn.
        Dùng mean aggregation — phù hợp cảm biến liên tục như BME280.
        """
        n_before = len(df)
        sensor_df = df[self.config.sensor_cols]
        df_resampled = sensor_df.resample(self.config.resample_freq).mean()

        n_after = len(df_resampled)
        self._report["n_before_resample"] = n_before
        self._report["n_after_resample"] = n_after
        self._report["resample_freq"] = self.config.resample_freq

        logger.info(
            "Resample (%s): %d → %d điểm (thêm %d khoảng trống mới)",
            self.config.resample_freq, n_before, n_after,
            df_resampled[self.config.sensor_cols[0]].isna().sum()
        )
        return df_resampled

    def _remove_physical_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        """Xóa (→ NaN) các giá trị vi phạm giới hạn vật lý của cảm biến."""
        outlier_counts: Dict[str, int] = {}

        for col in self.config.sensor_cols:
            if col not in PHYSICAL_BOUNDS or col not in df.columns:
                continue

            lo, hi = PHYSICAL_BOUNDS[col]
            mask = (df[col] < lo) | (df[col] > hi)
            count = int(mask.sum())

            if count > 0:
                df.loc[mask, col] = np.nan
                logger.info(
                    "Physical bounds '%s' [%.1f, %.1f]: loại %d điểm",
                    col, lo, hi, count
                )
            outlier_counts[col] = count

        self._report["physical_outliers"] = outlier_counts
        return df

    def _remove_statistical_outliers(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Khử ngoại lai thống kê theo phương pháp đã cấu hình:
            - 'iqr':     IQR fence Q1 - k*IQR, Q3 + k*IQR
            - 'zscore':  |z| > threshold
            - 'physical': chỉ dùng giới hạn vật lý (đã làm ở bước trên)
        """
        outlier_counts: Dict[str, int] = {}

        for col in self.config.sensor_cols:
            if col not in df.columns:
                continue

            series = df[col].dropna()
            if len(series) < 4:
                continue

            if self.config.outlier_method == "iqr":
                q1, q3 = series.quantile(0.25), series.quantile(0.75)
                iqr = q3 - q1
                lo = q1 - self.config.iqr_multiplier * iqr
                hi = q3 + self.config.iqr_multiplier * iqr
                mask = (df[col] < lo) | (df[col] > hi)

            elif self.config.outlier_method == "zscore":
                z = np.abs(stats.zscore(df[col].fillna(series.median())))
                mask = z > self.config.zscore_threshold

            else:  # 'physical' → đã xử lý ở bước trước
                continue

            count = int(mask.sum())
            if count > 0:
                if self.config.outlier_action == "nan":
                    df.loc[mask, col] = np.nan
                else:  # "cap"
                    df.loc[mask & (df[col] < lo), col] = lo
                    df.loc[mask & (df[col] > hi), col] = hi

                logger.info(
                    "Stat outlier '%s' (%s): %d điểm → %s",
                    col, self.config.outlier_method, count,
                    self.config.outlier_action
                )
            outlier_counts[col] = count

        self._report["statistical_outliers"] = outlier_counts
        return df

    def _interpolate_missing(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Nội suy các khoảng NaN.
        - Dùng spline bậc 3 cho chuỗi mượt (temperature, pressure, humidity)
        - limit=max_gap_fill: không fill khoảng gap quá dài
        """
        missing_before: Dict[str, int] = {}
        missing_after: Dict[str, int] = {}

        for col in self.config.sensor_cols:
            if col not in df.columns:
                continue

            n_missing = int(df[col].isna().sum())
            missing_before[col] = n_missing

            if n_missing == 0:
                missing_after[col] = 0
                continue

            try:
                if self.config.interpolation_method == "spline":
                    df[col] = df[col].interpolate(
                        method="spline",
                        order=self.config.spline_order,
                        limit=self.config.max_gap_fill,
                        limit_direction="both",
                    )
                elif self.config.interpolation_method == "time":
                    df[col] = df[col].interpolate(
                        method="time",
                        limit=self.config.max_gap_fill,
                        limit_direction="both",
                    )
                else:  # "linear"
                    df[col] = df[col].interpolate(
                        method="linear",
                        limit=self.config.max_gap_fill,
                        limit_direction="both",
                    )
            except Exception as exc:
                logger.error(
                    "Interpolate '%s' thất bại, fallback linear: %s", col, exc
                )
                df[col] = df[col].interpolate(
                    method="linear",
                    limit=self.config.max_gap_fill,
                    limit_direction="both",
                )

            missing_after[col] = int(df[col].isna().sum())
            logger.info(
                "Interpolate '%s': %d NaN → %d NaN còn lại",
                col, n_missing, missing_after[col]
            )

        self._report["missing_before_interpolate"] = missing_before
        self._report["missing_after_interpolate"] = missing_after
        return df

    def _ffill_remaining(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Forward-fill dự phòng cho NaN còn sót sau khi interpolate
        (thường ở đầu/cuối chuỗi hoặc gap quá dài).
        """
        for col in self.config.sensor_cols:
            if col in df.columns:
                df[col] = df[col].ffill(limit=self.config.ffill_limit_after_gap)
                df[col] = df[col].bfill(limit=self.config.ffill_limit_after_gap)

        remaining_nan = {
            col: int(df[col].isna().sum())
            for col in self.config.sensor_cols
            if col in df.columns
        }
        self._report["remaining_nan_after_ffill"] = remaining_nan
        total_remaining = sum(remaining_nan.values())

        if total_remaining > 0:
            logger.warning(
                "Vẫn còn %d NaN sau toàn bộ pipeline — "
                "xem xét tăng max_gap_fill hoặc kiểm tra dữ liệu đầu vào.",
                total_remaining
            )
        else:
            logger.info("Tất cả NaN đã được xử lý thành công.")

        return df

    def _build_report(self, df: pd.DataFrame) -> None:
        """Thêm thống kê mô tả vào báo cáo cuối."""
        self._report["final_shape"] = df.shape
        self._report["final_stats"] = df[self.config.sensor_cols].describe().to_dict()
        logger.info("Báo cáo tiền xử lý đã sẵn sàng. Gọi .get_report() để xem.")


# ---------------------------------------------------------------------------
# Hàm tiện ích độc lập (dùng nhanh không cần khởi tạo class)
# ---------------------------------------------------------------------------

def load_raw_data_from_csv(filepath: str) -> pd.DataFrame:
    """
    Load dữ liệu thô từ CSV (dùng khi chưa có kết nối DB từ TV1).

    CSV cần có cột: timestamp, temperature, humidity, pressure, rain_raw.

    Args:
        filepath: Đường dẫn file CSV.

    Returns:
        DataFrame thô chưa tiền xử lý.
    """
    try:
        df = pd.read_csv(filepath, parse_dates=["timestamp"])
        logger.info("Đọc CSV thành công: %s — shape %s", filepath, df.shape)
        return df
    except FileNotFoundError:
        raise FileNotFoundError(f"Không tìm thấy file: {filepath}")
    except Exception as exc:
        raise RuntimeError(f"Lỗi đọc CSV '{filepath}': {exc}") from exc


def generate_sample_iot_data(
    n_minutes: int = 1440,
    freq: str = "1min",
    start: str = "2026-10-01 00:00:00",
    noise_level: float = 0.3,
    missing_rate: float = 0.05,
    outlier_rate: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Tạo dữ liệu IoT mẫu để test pipeline (dùng khi chưa có DB thật).

    Args:
        n_minutes:    Số phút dữ liệu.
        freq:         Tần suất mẫu.
        start:        Thời điểm bắt đầu.
        noise_level:  Mức nhiễu Gaussian.
        missing_rate: Tỉ lệ điểm bị thiếu.
        outlier_rate: Tỉ lệ điểm ngoại lai.
        seed:         Random seed.

    Returns:
        DataFrame mẫu với timestamp và các cột sensor.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start=start, periods=n_minutes, freq=freq, tz="UTC")

    t = np.arange(n_minutes)

    # Nhiệt độ: dao động ngày đêm sine ~28°C ± 6°C
    temperature = (
        28.0
        + 6.0 * np.sin(2 * np.pi * t / (60 * 24) - np.pi / 2)
        + rng.normal(0, noise_level, n_minutes)
    )

    # Độ ẩm: nghịch chiều với nhiệt độ
    humidity = (
        75.0
        - 10.0 * np.sin(2 * np.pi * t / (60 * 24) - np.pi / 2)
        + rng.normal(0, 1.0, n_minutes)
    ).clip(30, 100)

    # Khí áp: drift nhẹ + nhiễu
    pressure = (
        1013.0
        + 2.0 * np.sin(2 * np.pi * t / (60 * 24 * 2))
        + rng.normal(0, 0.5, n_minutes)
    )

    # Rain sensor: phần lớn 0, đôi khi có giá trị cao
    rain_raw = rng.choice([0, 200, 600, 900], size=n_minutes,
                          p=[0.85, 0.07, 0.05, 0.03]).astype(float)

    df = pd.DataFrame({
        "timestamp":   idx,
        "temperature": temperature,
        "humidity":    humidity,
        "pressure":    pressure,
        "rain_raw":    rain_raw,
    })

    # Inject missing values
    n_missing = int(n_minutes * missing_rate)
    missing_idx = rng.choice(n_minutes, n_missing, replace=False)
    for col in ["temperature", "humidity", "pressure"]:
        df.loc[missing_idx[: n_missing // 3], col] = np.nan

    # Inject outliers (spike)
    n_outliers = int(n_minutes * outlier_rate)
    outlier_idx = rng.choice(n_minutes, n_outliers, replace=False)
    df.loc[outlier_idx, "temperature"] += rng.choice([-20, 25], size=n_outliers)

    logger.info(
        "Dữ liệu mẫu IoT đã tạo: %d điểm, %.1f%% NaN, %.1f%% outliers",
        n_minutes, missing_rate * 100, outlier_rate * 100
    )
    return df


# ---------------------------------------------------------------------------
# Script chạy thử nhanh (quick smoke test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  ML-01: Common Time-Series Preprocessing — Quick Test")
    print("=" * 60)

    # 1. Tạo dữ liệu mẫu
    df_raw = generate_sample_iot_data(n_minutes=1440, missing_rate=0.05)
    print(f"\n[RAW] shape: {df_raw.shape}, NaN: {df_raw.isna().sum().sum()}")

    # 2. Khởi tạo preprocessor
    config = PreprocessingConfig(
        resample_freq="1min",
        interpolation_method="spline",
        outlier_method="iqr",
        iqr_multiplier=1.5,
    )
    preprocessor = TimeSeriesPreprocessor(config)

    # 3. Chạy pipeline
    df_clean = preprocessor.fit_transform(df_raw)
    print(f"[CLEAN] shape: {df_clean.shape}, NaN: {df_clean.isna().sum().sum()}")

    # 4. ADF test
    print("\n--- Kiểm định tính dừng ADF ---")
    adf_results = preprocessor.run_stationarity_tests(df_clean)
    print(adf_results[["column", "adf_statistic", "p_value", "is_stationary"]])

    # 5. Báo cáo
    report = preprocessor.get_report()
    print(f"\n[REPORT] final_shape: {report['final_shape']}")
    print(f"[REPORT] physical_outliers: {report['physical_outliers']}")
    print(f"[REPORT] statistical_outliers: {report['statistical_outliers']}")
    print(f"[REPORT] remaining_nan: {report['remaining_nan_after_ffill']}")

    print("\n✅ ML-01 preprocessing pipeline OK!")
