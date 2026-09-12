"""
==============================================================================
MODULE 4: HUẤN LUYỆN VÀ HIỆU CHUẨN MÔ HÌNH XÁC SUẤT MƯA
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-01, SA-02 (TASK.md)
==============================================================================
"""

import os
import sys
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import brier_score_loss, roc_auc_score, f1_score, classification_report

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from common.preprocessing import TimeSeriesPreprocessor
from rain_classification.features import extract_rain_features


def train_and_calibrate_rain_models(data_path: str = None):
    if data_path is None:
        data_path = BASE_DIR / "data" / "sample" / "sample_weather_data.csv"

    print(f"[TV3 - TRAIN RAIN] Đang nạp dữ liệu từ: {data_path}")
    raw_df = pd.read_csv(data_path)

    preprocessor = TimeSeriesPreprocessor(freq="1min")
    clean_df = preprocessor.clean_and_resample(raw_df)

    feat_df = extract_rain_features(clean_df)

    # Tạo target: Có mưa trong vòng +10m, +30m, +60m tới không (dựa trên cột rain_detected)
    horizons = [10, 30, 60]
    for h in horizons:
        # Nếu trong h phút tới có bất kỳ phút nào rain_detected == 1 -> Target = 1
        future_rain = feat_df["rain_detected"].iloc[::-1].rolling(window=h, min_periods=1).max().iloc[::-1]
        feat_df[f"target_rain_{h}m"] = (future_rain > 0).astype(int)

    feat_df = feat_df.dropna()

    feature_cols = [c for c in feat_df.columns if not c.startswith("target_") and c != "timestamp"]
    X = feat_df[feature_cols]

    split_idx = int(len(feat_df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]

    print(f"[TV3] Tập huấn luyện: {len(X_train)} dòng | Tập kiểm thử: {len(X_test)} dòng")

    calibrated_models = {}

    print("\n" + "="*70)
    print(f"{'Horizon':<10}{'Brier Score (Calibrated)':<28}{'ROC-AUC':<12}{'F1-Score':<10}")
    print("="*70)

    for h in horizons:
        y_train = feat_df[f"target_rain_{h}m"].iloc[:split_idx]
        y_test = feat_df[f"target_rain_{h}m"].iloc[split_idx:]

        # Nếu tập train hoặc test chỉ có 1 class (ví dụ không có mưa), tạo baseline an toàn
        if len(np.unique(y_train)) < 2:
            print(f"+{h}m: Chỉ có 1 lớp trong tập train, bỏ qua.")
            continue

        base_clf = RandomForestClassifier(
            n_estimators=100,
            max_depth=5,
            class_weight="balanced",
            random_state=42
        )

        # Hiệu chuẩn xác suất bằng Platt Scaling (sigmoid) hoặc Isotonic Regression
        calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method="sigmoid", cv=3)
        calibrated_clf.fit(X_train, y_train)

        # Đánh giá trên tập test
        y_prob = calibrated_clf.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)

        brier = brier_score_loss(y_test, y_prob)
        try:
            auc = roc_auc_score(y_test, y_prob)
        except Exception:
            auc = 0.5
        f1 = f1_score(y_test, y_pred, zero_division=0)

        print(f"+{h:<7}m {brier:<28.4f} {auc:<12.4f} {f1:<10.4f}")
        calibrated_models[f"rain_{h}m"] = calibrated_clf

    save_payload = {
        "models": calibrated_models,
        "feature_cols": feature_cols,
        "horizons": horizons
    }
    save_path = BASE_DIR / "saved_models" / "rain_classifier_models.joblib"
    os.makedirs(save_path.parent, exist_ok=True)
    joblib.dump(save_payload, save_path)
    print(f"\n[TV3] Đã lưu mô hình xác suất mưa hiệu chuẩn tại: {save_path}")


if __name__ == "__main__":
    train_and_calibrate_rain_models()

