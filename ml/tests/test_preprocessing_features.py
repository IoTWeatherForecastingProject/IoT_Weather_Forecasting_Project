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

    # Train/val/test split (unpurged check)
    X_tr_u, X_v_u, X_te_u, _, _, _ = engineer.train_val_test_split(
        X, y_dict["y_10"], purge_boundary=False
    )
    total_u = len(X_tr_u) + len(X_v_u) + len(X_te_u)
    check(total_u == len(X), "Split: tổng hàng khớp khi purge_boundary=False")

    # Train/val/test split (PURGED check - Review P2)
    X_tr, X_v, X_te, y_tr, y_v, y_te = engineer.train_val_test_split(
        X, y_dict["y_10"], purge_boundary=True
    )
    check(len(X_tr) > len(X_te), "Train set lớn hơn test set (khi purge)")
    max_h = max(engineer.config.forecast_horizons)
    # Ranh giới train -> val: thời điểm nhãn cuối cùng của train phải <= thời điểm feature đầu tiên của val
    train_target_max_time = X_tr.index[-1] + pd.Timedelta(minutes=max_h)
    val_feature_min_time  = X_v.index[0]
    check(train_target_max_time <= val_feature_min_time, "Không có rò rỉ nhãn train -> val (Purge gap >= 60m)")

    # Ranh giới val -> test: thời điểm nhãn cuối cùng của val phải <= thời điểm feature đầu tiên của test
    val_target_max_time   = X_v.index[-1] + pd.Timedelta(minutes=max_h)
    test_feature_min_time = X_te.index[0]
    check(val_target_max_time <= test_feature_min_time, "Không có rò rỉ nhãn val -> test (Purge gap >= 60m)")

    # Feature names
    feat_names = engineer.get_feature_names()
    check(len(feat_names) > 10, f"Có ít nhất 10 đặc trưng (thực tế: {len(feat_names)})")

except Exception as e:
    print(f"  ❌ EXCEPTION trong ML-02: {e}")
    FAILED += 1




# ============================================================
# TEST GROUP 10: Regression Tests -- Review Fix #1 & #3
# ============================================================
print("\n" + "=" * 60)
print("  TEST GROUP 10: Regression -- Label Timing & Purge Leakage")
print("=" * 60)

# -- 10.1: Label timing dung khi chuoi co khoang trong ----------
# Tao chuoi 200 phut, xoa 40 phut o giua tao khoang trong.
# y_10 tai t phai = nhiet do tai t+10min (timestamp lookup, khong phai row shift).
try:
    import pandas as pd
    from ml.preprocessing import TimeSeriesPreprocessor, PreprocessingConfig, generate_sample_iot_data
    from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig

    df_200_raw = generate_sample_iot_data(n_minutes=200)
    prep_gap = TimeSeriesPreprocessor(PreprocessingConfig())
    df_200 = prep_gap.fit_transform(df_200_raw)
    # Xoa khoang tu phut 80 den 119 de tao khoang trong 40 phut
    gap_start = df_200.index[80]
    gap_end   = df_200.index[119]
    df_gapped = df_200[(df_200.index < gap_start) | (df_200.index > gap_end)].copy()

    eng_gap = TemperatureFeatureEngineer(FeatureConfig(
        lag_steps=[1, 2, 3, 6, 10, 30],
        delta_steps=[1, 5, 10],
        rolling_windows=[6, 10, 30, 60],
        forecast_horizons=[10, 30, 60],
    ))
    df_gap_feat = eng_gap.fit_transform(df_gapped)

    check(len(df_gap_feat) > 0,
          "[Fix#1] fit_transform tren chuoi co khoang trong khong crash va co ket qua")
    check("y_10" in df_gap_feat.columns and "y_30" in df_gap_feat.columns,
          "[Fix#1] Cot nhan y_10, y_30 ton tai tren chuoi co khoang trong")

    gap_label_nan = df_gap_feat[["y_10", "y_30", "y_60"]].isna().sum().sum()
    check(gap_label_nan == 0,
          "[Fix#1] Khong co NaN trong nhan sau fit_transform (nan=%d)" % gap_label_nan)

    # Timestamp lookup correctness
    valid_rows = [ts for ts in df_gap_feat.index
                  if (ts + pd.Timedelta(minutes=10)) in df_gapped.index]
    if valid_rows:
        t0 = valid_rows[0]
        t_tgt = t0 + pd.Timedelta(minutes=10)
        y10_got = df_gap_feat.loc[t0, "y_10"]
        y10_exp = df_gapped.loc[t_tgt, "temperature"]
        check(abs(y10_got - y10_exp) < 0.01,
              "[Fix#1] y_10 theo timestamp dung (got=%.4f, exp=%.4f)" % (y10_got, y10_exp))

except Exception as e:
    print("  [EXCEPTION] 10.1 label timing gap: %s" % e)
    FAILED += 1

# -- 10.2: Purge nghiem ngat -- khong ro ri nhan, khong force-keep --
# Dung 700 phut du lieu qua generate_sample_iot_data+TimeSeriesPreprocessor
# (du de lag_steps=[1..30]+rolling=[6,10,30,60] con lai hang sau dropna).
try:
    import warnings
    import pandas as pd
    from ml.preprocessing import TimeSeriesPreprocessor, PreprocessingConfig, generate_sample_iot_data
    from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig

    df_700_raw = generate_sample_iot_data(n_minutes=700)
    prep_700 = TimeSeriesPreprocessor(PreprocessingConfig())
    df_700 = prep_700.fit_transform(df_700_raw)

    eng_700 = TemperatureFeatureEngineer(FeatureConfig(
        lag_steps=[1, 2, 3, 6, 10, 30],
        delta_steps=[1, 5, 10],
        rolling_windows=[6, 10, 30, 60],
        forecast_horizons=[10, 30, 60],
    ))
    df_700_feat = eng_700.fit_transform(df_700)
    X_7, y_7 = eng_700.get_Xy(df_700_feat)
    max_h = 60

    with warnings.catch_warnings(record=True) as w_list:
        warnings.simplefilter("always")
        X_tr_7, X_v_7, X_te_7, y_tr_7, y_v_7, y_te_7 = eng_700.train_val_test_split(
            X_7, y_7["y_60"], purge_boundary=True
        )

    # Kiem tra train van co du lieu
    check(len(X_tr_7) > 0, "[Fix#3] Train van co du lieu sau purge")

    # Kiem tra val rong HOAC khong co ro ri nhan
    if len(X_v_7) == 0:
        check(True, "[Fix#3] Val rong sau strict purge (khong force-keep mau vi pham)")
    elif len(X_te_7) > 0:
        val_label_max = X_v_7.index[-1] + pd.Timedelta(minutes=max_h)
        test_start    = X_te_7.index[0]
        check(val_label_max <= test_start,
              "[Fix#3] Nhan cuoi val <= test start (strict purge, khong ro ri)")
    else:
        check(True, "[Fix#3] Purge: test rong voi du lieu nho - hanh vi chap nhan duoc")

    # Strict check: khong con bug force-keep
    if len(X_v_7) > 0 and len(X_te_7) > 0:
        val_last_label = X_v_7.index[-1] + pd.Timedelta(minutes=max_h)
        check(val_last_label <= X_te_7.index[0],
              "[Fix#3] Purge nghiem ngat: nhan val KHONG vuot ranh gioi test")

except Exception as e:
    print("  [EXCEPTION] 10.2 purge strict: %s" % e)
    FAILED += 1


# -- 10.3: Purge nghiem ngat -- khong ep giu mau train khi du lieu ngan --
# Voi 50 hang dac trung, n_train=35 <= max_h=60 -> train_end phai la 0 (tap rong).
# Tuyet doi khong dung max(1, n_train - max_h) de ep giu mau gay ro ri sang test.
try:
    import warnings
    import numpy as np
    import pandas as pd
    from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig

    eng_short = TemperatureFeatureEngineer(FeatureConfig(
        forecast_horizons=[10, 30, 60],
    ))
    rng_50 = pd.date_range("2026-01-01 00:00:00", periods=50, freq="1min", tz="UTC")
    X_50 = pd.DataFrame(
        np.ones((50, 5)),
        index=rng_50,
        columns=[f"feat_{i}" for i in range(5)],
    )
    y_50 = pd.Series(np.arange(50, dtype=float), index=rng_50)

    with warnings.catch_warnings(record=True) as w_list:
        warnings.simplefilter("always")
        X_tr_s, X_v_s, X_te_s, y_tr_s, y_v_s, y_te_s = eng_short.train_val_test_split(
            X_50, y_50, purge_boundary=True
        )

    # 1. Kiem tra train rong (khong con bi ep giu 1 mau boi max(1, ...))
    check(len(X_tr_s) == 0, "[Fix#3-Review2] 50 hang: Train rong sau strict purge (khong ep giu mau vi pham)")
    # 2. Kiem tra val rong
    check(len(X_v_s) == 0, "[Fix#3-Review2] 50 hang: Val rong sau strict purge")
    # 3. Kiem tra test van ton tai
    check(len(X_te_s) > 0, "[Fix#3-Review2] 50 hang: Test set ton tai phan con lai")
    # 4. Kiem tra canh bao ro rang khi tap train bi rong do purge gap
    has_warn = any("Purge gap" in str(w.message) for w in w_list)
    check(has_warn, "[Fix#3-Review2] Phat canh bao khi purge lam train hoac val rong")

except Exception as e:
    print("  [EXCEPTION] 10.3 short data purge: %s" % e)
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
