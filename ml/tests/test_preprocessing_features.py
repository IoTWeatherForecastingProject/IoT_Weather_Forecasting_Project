"""
Test nhanh ML-01 & ML-02 (khong can pytest, chay truc tiep)
=============================================================
Chay: python ml/tests/test_preprocessing_features.py
"""

import sys
import os
# Force UTF-8 stdout de tranh loi Unicode tren Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Thêm thư mục gốc project vào path
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from ml.preprocessing import (
    TimeSeriesPreprocessor,
    PreprocessingConfig,
    generate_sample_iot_data,
)
from ml.feature_engineering import (
    TemperatureFeatureEngineer,
    FeatureConfig,
)

PASSED = 0
FAILED = 0


def check(condition: bool, name: str) -> None:
    global PASSED, FAILED
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status}: {name}")
    if condition:
        PASSED += 1
    else:
        FAILED += 1


# ============================================================
# TEST GROUP 1 — ML-01: Preprocessing
# ============================================================
print("\n" + "=" * 55)
print("  TEST GROUP 1: ML-01 — Preprocessing")
print("=" * 55)

df_raw = generate_sample_iot_data(n_minutes=1440, missing_rate=0.08, outlier_rate=0.03)
config  = PreprocessingConfig(resample_freq="1min", outlier_method="iqr")
prep    = TimeSeriesPreprocessor(config)

try:
    df_clean = prep.fit_transform(df_raw)

    check(isinstance(df_clean, pd.DataFrame),          "Đầu ra là DataFrame")
    check(isinstance(df_clean.index, pd.DatetimeIndex), "DatetimeIndex sau xử lý")
    check(df_clean["temperature"].isna().sum() == 0,   "Không còn NaN ở temperature")
    check(df_clean["humidity"].isna().sum() == 0,      "Không còn NaN ở humidity")
    check(df_clean["pressure"].isna().sum() == 0,      "Không còn NaN ở pressure")
    check(len(df_clean) > 0,                            "DataFrame không rỗng")

    # Kiểm tra giới hạn vật lý sau xử lý
    check(
        df_clean["temperature"].between(-10, 60).all(),
        "Nhiệt độ trong giới hạn [-10, 60]°C"
    )
    check(
        df_clean["humidity"].between(0, 100).all(),
        "Độ ẩm trong giới hạn [0, 100]%"
    )

    # Báo cáo
    report = prep.get_report()
    check("physical_outliers" in report,    "Báo cáo có physical_outliers")
    check("statistical_outliers" in report, "Báo cáo có statistical_outliers")
    check("final_shape" in report,          "Báo cáo có final_shape")

    # ADF test
    adf_df = prep.run_stationarity_tests(df_clean, cols=["temperature"])
    check(len(adf_df) == 1,                "ADF test chạy được cho 1 cột")
    check("is_stationary" in adf_df.columns, "ADF kết quả có cột is_stationary")

except Exception as e:
    print(f"  ❌ EXCEPTION trong ML-01: {e}")
    FAILED += 1


# ============================================================
# TEST GROUP 2 — ML-02: Feature Engineering
# ============================================================
print("\n" + "=" * 55)
print("  TEST GROUP 2: ML-02 — Feature Engineering")
print("=" * 55)

feat_config = FeatureConfig(
    lag_steps=[1, 2, 3, 6],
    delta_steps=[1, 5],
    rolling_windows=[6, 30],
    forecast_horizons=[10, 30, 60],
)
engineer = TemperatureFeatureEngineer(feat_config)

try:
    df_features = engineer.fit_transform(df_clean)

    check(isinstance(df_features, pd.DataFrame), "Đầu ra là DataFrame")
    check(df_features.isna().sum().sum() == 0,   "Không còn NaN sau dropna")
    check("y_10" in df_features.columns,          "Cột target y_10 tồn tại")
    check("y_30" in df_features.columns,          "Cột target y_30 tồn tại")
    check("y_60" in df_features.columns,          "Cột target y_60 tồn tại")

    # Kiểm tra lag features
    check("T_lag_1" in df_features.columns,       "Lag feature T_lag_1 tồn tại")
    check("T_lag_6" in df_features.columns,       "Lag feature T_lag_6 tồn tại")

    # Kiểm tra delta features
    check("dT_1min" in df_features.columns,       "Delta feature dT_1min tồn tại")
    check("dT_5min" in df_features.columns,       "Delta feature dT_5min tồn tại")

    # Kiểm tra rolling features
    check("T_roll_mean_6m" in df_features.columns,  "Rolling mean 6m tồn tại")
    check("T_roll_std_30m" in df_features.columns,  "Rolling std 30m tồn tại")

    # Kiểm tra cyclic features
    check("hour_sin" in df_features.columns,      "Cyclic hour_sin tồn tại")
    check("hour_cos" in df_features.columns,      "Cyclic hour_cos tồn tại")

    # get_Xy test
    X, y_dict = engineer.get_Xy(df_features)
    check(len(y_dict) == 3,                       "get_Xy trả về 3 target horizons")
    check(len(X) == len(y_dict["y_10"]),           "X và y có cùng số hàng")
    check(X.isna().sum().sum() == 0,              "X không có NaN")

    # Train/val/test split
    X_tr, X_v, X_te, y_tr, y_v, y_te = engineer.train_val_test_split(
        X, y_dict["y_10"]
    )
    total = len(X_tr) + len(X_v) + len(X_te)
    check(total == len(X), "Split: tổng hàng khớp sau khi ghép lại")
    check(len(X_tr) > len(X_te), "Train set lớn hơn test set")

    # Feature names
    feat_names = engineer.get_feature_names()
    check(len(feat_names) > 10, f"Có ít nhất 10 đặc trưng (thực tế: {len(feat_names)})")

except Exception as e:
    print(f"  ❌ EXCEPTION trong ML-02: {e}")
    FAILED += 1


# ============================================================
# KẾT QUẢ
# ============================================================
print("\n" + "=" * 55)
print(f"  KẾT QUẢ: {PASSED} PASS — {FAILED} FAIL")
print("=" * 55)

if FAILED == 0:
    print("  🎉 Tất cả test PASS! ML-01 & ML-02 sẵn sàng sử dụng.")
else:
    print(f"  ⚠️  {FAILED} test thất bại. Kiểm tra lại code.")
    sys.exit(1)
