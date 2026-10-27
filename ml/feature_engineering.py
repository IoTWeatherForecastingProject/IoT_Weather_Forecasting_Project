"""
ML-02: Feature Engineering Pipeline cho bài toán Hồi quy Nhiệt độ
===================================================================
Trích xuất các đặc trưng chuỗi thời gian từ dữ liệu IoT thời tiết đã
tiền xử lý (đầu ra của ML-01) để phục vụ các mô hình hồi quy nhiệt độ
đa bước (+10 phút, +30 phút, +60 phút).

Đặc trưng được tạo ra:
    [A] Lag Features:      T(t-1), T(t-2), T(t-3), T(t-6)
    [B] Delta Features:    ΔT(t) = T(t) - T(t-1) — tốc độ thay đổi nhiệt độ
    [C] Rolling Stats:     Rolling mean & std trong cửa sổ 6, 10, 30, 60 phút
    [D] Cyclic Time:       Sine/Cosine encoding giờ trong ngày & tháng trong năm
    [E] Context Features:  Độ ẩm, khí áp, và lag của chúng

Tác giả: TV2 — Time-Series AI Engineer
Dự án:   IoT Local Weather Forecasting
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cấu hình Feature Engineering
# ---------------------------------------------------------------------------

@dataclass
class FeatureConfig:
    """
    Cấu hình toàn bộ pipeline trích xuất đặc trưng.
    Thay đổi ở đây để tune feature set mà không sửa code logic.
    """
    # Cột nhiệt độ chính (target gốc)
    target_col: str = "temperature"

    # Cột ngữ cảnh bổ sung
    context_cols: List[str] = field(
        default_factory=lambda: ["humidity", "pressure"]
    )

    # ---- [A] Lag features ----
    # Danh sách lag (đơn vị: số bước resample, mặc định 1 bước = 1 phút)
    lag_steps: List[int] = field(
        default_factory=lambda: [1, 2, 3, 6, 10, 30]
    )

    # ---- [B] Delta features ----
    delta_steps: List[int] = field(
        default_factory=lambda: [1, 5, 10]
    )   # ΔT_1 = T(t) - T(t-1), ΔT_5 = T(t) - T(t-5), ...

    # ---- [C] Rolling statistics ----
    rolling_windows: List[int] = field(
        default_factory=lambda: [6, 10, 30, 60]
    )   # Đơn vị phút (= số bước với resample 1min)

    # ---- [D] Cyclic encoding ----
    encode_hour: bool = True            # Sine/Cosine giờ trong ngày (0–23)
    encode_day_of_week: bool = True     # Sine/Cosine thứ trong tuần (0–6)
    encode_month: bool = False          # Sine/Cosine tháng trong năm (bật nếu dữ liệu > 1 tháng)

    # ---- [E] Context lag ----
    context_lag_steps: List[int] = field(
        default_factory=lambda: [1, 6]
    )   # Lag của humidity, pressure

    # ---- Target horizons ----
    # Số bước phía trước cần dự báo (dùng để tạo label y)
    forecast_horizons: List[int] = field(
        default_factory=lambda: [10, 30, 60]
    )   # +10min, +30min, +60min


# ---------------------------------------------------------------------------
# Lớp Feature Engineering chính
# ---------------------------------------------------------------------------

class TemperatureFeatureEngineer:
    """
    Pipeline trích xuất đặc trưng hoàn chỉnh cho bài toán hồi quy nhiệt độ.

    Ví dụ sử dụng:
    --------------
    >>> engineer = TemperatureFeatureEngineer(FeatureConfig())
    >>> df_features = engineer.fit_transform(df_clean)
    >>> X, y_dict = engineer.get_Xy(df_features)
    # y_dict = {'y_10': Series, 'y_30': Series, 'y_60': Series}
    """

    def __init__(self, config: Optional[FeatureConfig] = None) -> None:
        self.config = config or FeatureConfig()
        self._feature_names: List[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Trích xuất toàn bộ đặc trưng (features) mà KHÔNG sinh các cột nhãn target tương lai.
        Dùng chung cho cả luồng Huấn luyện (Train) và luồng Dự báo thời gian thực (Inference).

        Args:
            df: DataFrame với DatetimeIndex (đã qua resample 1 phút và tiền xử lý).
                Phải chứa ít nhất cột 'temperature'.

        Returns:
            DataFrame chứa các đặc trưng [A] đến [E].
            Các hàng có NaN ở đầu chuỗi (do lag/rolling lớn nhất) đã được drop.
            Hàng cuối cùng (thời điểm t hiện tại) được giữ nguyên vẹn để phục vụ inference.
        """
        logger.info("=== BẮT ĐẦU TRÍCH XUẤT ĐẶC TRƯNG (transform_features) ===")
        df = df.copy()

        if self.config.target_col not in df.columns:
            raise ValueError(
                f"Cột target '{self.config.target_col}' không có trong DataFrame."
            )

        # [A] Lag features cho nhiệt độ
        df = self._add_lag_features(df)

        # [B] Delta / difference features
        df = self._add_delta_features(df)

        # [C] Rolling statistics
        df = self._add_rolling_stats(df)

        # [D] Cyclic time encoding
        df = self._add_cyclic_time(df)

        # [E] Context features (humidity, pressure và lag của chúng)
        df = self._add_context_features(df)

        # Drop NaN chỉ ở đầu chuỗi (do lag/rolling), giữ lại dòng mới nhất
        n_before = len(df)
        df = df.dropna()
        n_after = len(df)
        logger.info(
            "Drop NaN đầu chuỗi do lag/rolling: %d → %d hàng (bỏ %d hàng đầu)",
            n_before, n_after, n_before - n_after
        )

        # Ghi nhớ tên đặc trưng (loại bỏ target_col và bất kỳ cột nhãn y_*)
        self._feature_names = [
            c for c in df.columns
            if not c.startswith("y_") and c != self.config.target_col
        ]
        logger.info(
            "=== TRÍCH XUẤT ĐẶC TRƯNG HOÀN TẤT === %d đặc trưng: %s",
            len(self._feature_names), self._feature_names
        )
        return df

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Tạo toàn bộ đặc trưng VÀ các nhãn target tương lai (cho training).

        Args:
            df: DataFrame với DatetimeIndex (đầu ra của TimeSeriesPreprocessor).
                Phải chứa ít nhất cột 'temperature'.

        Returns:
            DataFrame bổ sung tất cả cột đặc trưng và các cột target y_10, y_30, y_60.
            Các hàng có NaN (do lag đầu chuỗi + target cuối chuỗi) đã được tự động drop.
        """
        logger.info("=== BẮT ĐẦU FEATURE ENGINEERING (fit_transform) ===")
        # 1. Trích xuất features dùng chung
        df = self.transform_features(df)

        # 2. Sinh các nhãn target y tương lai (shift -h)
        df = self._add_target_labels(df)

        # 3. Drop các hàng cuối cùng bị NaN do target shift(-h)
        n_before = len(df)
        df = df.dropna()
        n_after = len(df)
        logger.info(
            "Drop NaN đuôi chuỗi do target shift(-h): %d → %d hàng (mất %d)",
            n_before, n_after, n_before - n_after
        )

        self._feature_names = [
            c for c in df.columns
            if not c.startswith("y_") and c != self.config.target_col
        ]
        return df

    def get_Xy(
        self,
        df_features: pd.DataFrame,
        horizon: Optional[int] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, pd.Series]]:
        """
        Tách DataFrame đặc trưng thành ma trận X và dict các vector target y.

        Args:
            df_features: DataFrame đầu ra của fit_transform().
            horizon:     Nếu truyền (10, 30 hoặc 60), chỉ trả về y của horizon đó.
                         Nếu None, trả về dict đầy đủ.

        Returns:
            (X, y_dict) trong đó:
                X      — DataFrame các đặc trưng
                y_dict — {'y_10': Series, 'y_30': Series, 'y_60': Series}
        """
        target_cols = [
            c for c in df_features.columns if c.startswith("y_")
        ]
        if not target_cols:
            raise ValueError(
                "Không tìm thấy cột target. Hãy chạy fit_transform() trước."
            )

        X = df_features[self._feature_names].copy()

        if horizon is not None:
            target_name = f"y_{horizon}"
            if target_name not in df_features.columns:
                raise ValueError(
                    f"Horizon '{target_name}' không tồn tại. "
                    f"Các horizon hợp lệ: {target_cols}"
                )
            y_dict = {target_name: df_features[target_name]}
        else:
            y_dict = {col: df_features[col] for col in target_cols}

        return X, y_dict

    def train_val_test_split(
        self,
        X: pd.DataFrame,
        y: Union[pd.Series, Dict[str, pd.Series]],
        train_ratio: float = 0.70,
        val_ratio: float = 0.15,
        purge_boundary: bool = True,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame,
               Any, Any, Any]:
        """
        Chia dữ liệu theo thứ tự thời gian (không shuffle) kèm cơ chế PURGING GAP
        để triệt tiêu hoàn toàn rò rỉ thông tin nhãn (boundary leakage) sang tập tiếp theo.

        Nguyên lý Purging:
            Vì nhãn y_h được tạo bằng T(t + h) với h lên tới max_horizon (60 phút),
            nếu không purge, max_horizon mẫu cuối của tập train sẽ lấy nhãn nằm trong
            khoảng thời gian của tập validation. Tương tự, cuối tập val lấy nhãn của test.
            Khi purge_boundary=True, max_horizon mẫu cuối ở mỗi ranh giới sẽ được loại bỏ.

        Args:
            X:              Ma trận đặc trưng.
            y:              Vector target (pd.Series) hoặc dict {'y_10': Series, ...}.
            train_ratio:    Tỉ lệ tập train (mặc định 0.70).
            val_ratio:      Tỉ lệ tập validation (mặc định 0.15).
            purge_boundary: Bật/tắt loại bỏ mẫu ranh giới để chống rò rỉ (mặc định True).

        Returns:
            (X_train, X_val, X_test, y_train, y_val, y_test)
        """
        n = len(X)
        n_train = int(n * train_ratio)
        n_val   = int(n * (train_ratio + val_ratio))

        max_h = max(self.config.forecast_horizons) if self.config.forecast_horizons else 60

        if purge_boundary:
            # Loại bỏ max_h bước cuối của train và val để nhãn không vắt sang tập sau
            train_end = max(1, n_train - max_h)
            val_end   = max(n_train + 1, n_val - max_h)

            X_train = X.iloc[:train_end]
            X_val   = X.iloc[n_train:val_end]
            X_test  = X.iloc[n_val:]

            if isinstance(y, dict):
                y_train = {k: v.iloc[:train_end] for k, v in y.items()}
                y_val   = {k: v.iloc[n_train:val_end] for k, v in y.items()}
                y_test  = {k: v.iloc[n_val:] for k, v in y.items()}
            else:
                y_train = y.iloc[:train_end]
                y_val   = y.iloc[n_train:val_end]
                y_test  = y.iloc[n_val:]

            logger.info(
                "Time-series split (PURGED %d-step boundary): train=%d (bỏ %d) / val=%d (bỏ %d) / test=%d",
                max_h, len(X_train), n_train - train_end, len(X_val), n_val - val_end, len(X_test)
            )
        else:
            X_train = X.iloc[:n_train]
            X_val   = X.iloc[n_train:n_val]
            X_test  = X.iloc[n_val:]

            if isinstance(y, dict):
                y_train = {k: v.iloc[:n_train] for k, v in y.items()}
                y_val   = {k: v.iloc[n_train:n_val] for k, v in y.items()}
                y_test  = {k: v.iloc[n_val:] for k, v in y.items()}
            else:
                y_train = y.iloc[:n_train]
                y_val   = y.iloc[n_train:n_val]
                y_test  = y.iloc[n_val:]

            logger.info(
                "Time-series split (unpurged): train=%d / val=%d / test=%d",
                len(X_train), len(X_val), len(X_test)
            )

        return X_train, X_val, X_test, y_train, y_val, y_test

    def get_feature_names(self) -> List[str]:
        """Trả về danh sách tên đặc trưng sau khi fit_transform()."""
        if not self._feature_names:
            raise RuntimeError("Gọi fit_transform() trước khi gọi get_feature_names().")
        return self._feature_names

    def get_feature_summary(self, df_features: pd.DataFrame) -> pd.DataFrame:
        """
        Trả về bảng tóm tắt thống kê của tất cả đặc trưng.
        Hữu ích để kiểm tra phân phối đặc trưng trước khi huấn luyện model.

        Returns:
            DataFrame với mean, std, min, max, NaN% cho từng đặc trưng.
        """
        X, _ = self.get_Xy(df_features)
        summary = X.describe().T
        summary["nan_pct"] = (X.isna().sum() / len(X) * 100).round(2)
        return summary

    # ------------------------------------------------------------------
    # Private helpers — tạo từng nhóm đặc trưng
    # ------------------------------------------------------------------

    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [A] Tạo Lag features: T(t-k) với k ∈ lag_steps.
        Ý nghĩa: giá trị nhiệt độ k bước trước hiện tại.
        """
        col = self.config.target_col
        for k in self.config.lag_steps:
            feat_name = f"T_lag_{k}"
            df[feat_name] = df[col].shift(k)
            logger.debug("Đã tạo: %s", feat_name)

        logger.info("[A] Lag features: %d đặc trưng", len(self.config.lag_steps))
        return df

    def _add_delta_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [B] Tạo Delta features: ΔT(t, k) = T(t) - T(t-k).
        Ý nghĩa: tốc độ thay đổi nhiệt độ trong k bước gần nhất.
        """
        col = self.config.target_col
        for k in self.config.delta_steps:
            feat_name = f"dT_{k}min"
            df[feat_name] = df[col] - df[col].shift(k)
            logger.debug("Đã tạo: %s", feat_name)

        logger.info("[B] Delta features: %d đặc trưng", len(self.config.delta_steps))
        return df

    def _add_rolling_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [C] Tạo Rolling statistics: mean và std trên cửa sổ trượt.
        min_periods=1 để tránh NaN ở đầu chuỗi quá nhiều.
        """
        col = self.config.target_col
        count = 0

        for w in self.config.rolling_windows:
            # Rolling mean
            mean_name = f"T_roll_mean_{w}m"
            df[mean_name] = (
                df[col].rolling(window=w, min_periods=max(1, w // 2))
                .mean()
                .shift(1)  # shift(1): tránh data leakage
            )

            # Rolling std — đo mức biến động nhiệt độ gần đây
            std_name = f"T_roll_std_{w}m"
            df[std_name] = (
                df[col].rolling(window=w, min_periods=max(2, w // 2))
                .std()
                .shift(1)
            )

            count += 2
            logger.debug("Đã tạo: %s, %s", mean_name, std_name)

        logger.info(
            "[C] Rolling stats: %d đặc trưng (windows=%s)",
            count, self.config.rolling_windows
        )
        return df

    def _add_cyclic_time(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [D] Mã hóa thời gian tuần hoàn bằng Sine / Cosine.
        Giúp mô hình hiểu được chu kỳ ngày đêm mà không cần nhãn rời rạc.
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            logger.warning("[D] Index không phải DatetimeIndex — bỏ qua cyclic encoding.")
            return df

        count = 0

        if self.config.encode_hour:
            hour = df.index.hour + df.index.minute / 60.0  # float giờ
            df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
            df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
            count += 2

        if self.config.encode_day_of_week:
            dow = df.index.dayofweek.astype(float)
            df["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
            df["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
            count += 2

        if self.config.encode_month:
            month = df.index.month.astype(float)
            df["month_sin"] = np.sin(2 * np.pi * month / 12.0)
            df["month_cos"] = np.cos(2 * np.pi * month / 12.0)
            count += 2

        logger.info("[D] Cyclic time features: %d đặc trưng", count)
        return df

    def _add_context_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [E] Thêm đặc trưng ngữ cảnh từ humidity và pressure:
            - Giá trị hiện tại: H(t), P(t)
            - Lag: H(t-k), P(t-k)
            - Delta: ΔH, ΔP (tốc độ thay đổi — quan trọng cho dự báo mưa, nhưng
              cũng ảnh hưởng nhiệt độ qua hiệu ứng bay hơi)
        """
        count = 0

        for ctx_col in self.config.context_cols:
            if ctx_col not in df.columns:
                logger.warning(
                    "[E] Cột context '%s' không có — bỏ qua.", ctx_col
                )
                continue

            # Giá trị hiện tại đã có sẵn (giữ tên gốc)
            count += 1

            # Lag features của context
            for k in self.config.context_lag_steps:
                feat_name = f"{ctx_col}_lag_{k}"
                df[feat_name] = df[ctx_col].shift(k)
                count += 1

            # Delta của context: ΔX(t) = X(t) - X(t-1)
            delta_name = f"d{ctx_col}_1min"
            df[delta_name] = df[ctx_col] - df[ctx_col].shift(1)
            count += 1

        logger.info("[E] Context features: %d đặc trưng", count)
        return df

    def _add_target_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [F] Tạo các nhãn target y cho từng horizon dự báo.
        y_k = T(t + k): giá trị nhiệt độ thực tế k bước sau thời điểm t.

        Dùng shift âm: y_10 = temperature.shift(-10).
        Các hàng cuối chuỗi sẽ có NaN → sẽ bị drop ở bước dropna().
        """
        col = self.config.target_col

        for h in self.config.forecast_horizons:
            label_name = f"y_{h}"
            df[label_name] = df[col].shift(-h)
            logger.debug(
                "Target '%s': T(t + %d min)", label_name, h
            )

        logger.info(
            "[F] Target labels: %s", [f"y_{h}" for h in self.config.forecast_horizons]
        )
        return df


# ---------------------------------------------------------------------------
# Script chạy thử nhanh
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Import preprocessor từ ML-01
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    from preprocessing import (
        TimeSeriesPreprocessor,
        PreprocessingConfig,
        generate_sample_iot_data,
    )

    print("=" * 60)
    print("  ML-02: Feature Engineering — Quick Test")
    print("=" * 60)

    # 1. Tạo và tiền xử lý dữ liệu mẫu
    df_raw = generate_sample_iot_data(n_minutes=2880)   # 2 ngày dữ liệu
    preprocessor = TimeSeriesPreprocessor(PreprocessingConfig())
    df_clean = preprocessor.fit_transform(df_raw)

    print(f"\n[CLEAN] shape: {df_clean.shape}")

    # 2. Feature engineering
    feat_config = FeatureConfig(
        lag_steps=[1, 2, 3, 6, 10, 30],
        delta_steps=[1, 5, 10],
        rolling_windows=[6, 10, 30, 60],
        forecast_horizons=[10, 30, 60],
    )
    engineer = TemperatureFeatureEngineer(feat_config)
    df_features = engineer.fit_transform(df_clean)

    print(f"\n[FEATURES] shape: {df_features.shape}")
    print(f"[FEATURES] số đặc trưng: {len(engineer.get_feature_names())}")
    print(f"\nDanh sách đặc trưng:")
    for i, name in enumerate(engineer.get_feature_names(), 1):
        print(f"  {i:2d}. {name}")

    # 3. Lấy X, y cho horizon +10min
    X, y_dict = engineer.get_Xy(df_features, horizon=10)
    print(f"\n[X] shape: {X.shape}")
    print(f"[y_10] shape: {y_dict['y_10'].shape}")
    print(f"[y_10] sample:\n{y_dict['y_10'].head()}")

    # 4. Train/Val/Test split
    X_train, X_val, X_test, y_train, y_val, y_test = engineer.train_val_test_split(
        X, y_dict["y_10"]
    )
    print(f"\nSplit: train={len(X_train)}, val={len(X_val)}, test={len(X_test)}")

    # 5. Summary
    summary = engineer.get_feature_summary(df_features)
    print(f"\nFeature Summary (5 đặc trưng đầu):")
    print(summary.head())

    print("\n✅ ML-02 Feature Engineering pipeline OK!")
