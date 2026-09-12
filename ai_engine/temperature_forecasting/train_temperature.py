"""
==============================================================================
MODULE 3: HUẤN LUYỆN VÀ ĐỐI CHUẨN MÔ HÌNH DỰ BÁO NHIỆT ĐỘ
Phụ trách: TV2 (Time-Series AI Engineer)
Các Task: ML-03, ML-05, ML-06 (TASK.md)
==============================================================================
"""

import os
import sys
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# Thêm path cha vào sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from common.preprocessing import TimeSeriesPreprocessor
from temperature_forecasting.features import extract_temperature_features


def train_and_benchmark_models(data_path: str = None):
    if data_path is None:
        data_path = BASE_DIR / "data" / "sample" / "sample_weather_data.csv"

    print(f"[TV2 - TRAIN TEMP] Đang nạp dữ liệu từ: {data_path}")
    raw_df = pd.read_csv(data_path)

    # 1. Tiền xử lý dữ liệu
    preprocessor = TimeSeriesPreprocessor(freq="1min")
    clean_df = preprocessor.clean_and_resample(raw_df)

    # 2. Tạo đặc trưng
    feat_df = extract_temperature_features(clean_df)

    # 3. Tạo target đa bước: +10m, +30m, +60m
    horizons = [10, 30, 60]
    for h in horizons:
        feat_df[f"target_temp_{h}m"] = feat_df["temperature"].shift(-h)

    # Loại bỏ NaN do shift
    feat_df = feat_df.dropna()

    feature_cols = [c for c in feat_df.columns if not c.startswith("target_") and c != "timestamp"]
    X = feat_df[feature_cols]

    # 4. Chia Train / Test theo thời gian (Time-series split 80% / 20%, KHÔNG shuffle)
    split_idx = int(len(feat_df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]

    print(f"[TV2] Tập huấn luyện: {len(X_train)} dòng | Tập kiểm thử: {len(X_test)} dòng")
    print(f"[TV2] Số lượng đặc trưng: {len(feature_cols)}")

    trained_models = {}

    print("\n" + "="*70)
    print(f"{'Horizon':<10}{'Model':<22}{'MAE (°C)':<12}{'RMSE (°C)':<12}{'R²':<10}")
    print("="*70)

    for h in horizons:
        y_train = feat_df[f"target_temp_{h}m"].iloc[:split_idx]
        y_test = feat_df[f"target_temp_{h}m"].iloc[split_idx:]

        # --- Baseline: Persistence (T_t+k = T_t) ---
        base_pred = X_test["temperature"]
        b_mae = mean_absolute_error(y_test, base_pred)
        b_rmse = np.sqrt(mean_squared_error(y_test, base_pred))
        b_r2 = r2_score(y_test, base_pred)
        print(f"+{h:<7}m {'Persistence Baseline':<22} {b_mae:<12.3f} {b_rmse:<12.3f} {b_r2:<10.3f}")

        # --- Linear Ridge ---
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_train, y_train)
        r_pred = ridge.predict(X_test)
        r_mae = mean_absolute_error(y_test, r_pred)
        r_rmse = np.sqrt(mean_squared_error(y_test, r_pred))
        r_r2 = r2_score(y_test, r_pred)
        print(f"+{h:<7}m {'Ridge Regression':<22} {r_mae:<12.3f} {r_rmse:<12.3f} {r_r2:<10.3f}")

        # --- XGBoost Regressor ---
        xgb = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42)
        xgb.fit(X_train, y_train)
        x_pred = xgb.predict(X_test)
        x_mae = mean_absolute_error(y_test, x_pred)
        x_rmse = np.sqrt(mean_squared_error(y_test, x_pred))
        x_r2 = r2_score(y_test, x_pred)
        print(f"+{h:<7}m {'XGBoost Regressor':<22} {x_mae:<12.3f} {x_rmse:<12.3f} {x_r2:<10.3f}")
        print("-" * 70)

        # Lưu mô hình XGBoost làm mô hình triển khai chính
        trained_models[f"temp_{h}m"] = xgb

    # Lưu danh sách features và model weights
    save_payload = {
        "models": trained_models,
        "feature_cols": feature_cols,
        "horizons": horizons
    }
    model_save_path = BASE_DIR / "saved_models" / "temp_forecast_models.joblib"
    os.makedirs(model_save_path.parent, exist_ok=True)
    joblib.dump(save_payload, model_save_path)
    print(f"\n[TV2] Đã lưu model weights thành công tại: {model_save_path}")


if __name__ == "__main__":
    train_and_benchmark_models()

