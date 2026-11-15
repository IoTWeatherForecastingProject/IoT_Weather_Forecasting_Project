"""
==============================================================================
MODULE 4: HIỆU CHUẨN XÁC SUẤT MƯA (PROBABILITY CALIBRATION)
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-02 (TASK.md)
==============================================================================

Calibrator được fit trên tập calibration riêng (tách theo thời gian, sau tập train),
nên không dùng `CalibratedClassifierCV` (cross-validation mặc định trộn quá khứ/tương lai,
còn `cv="prefit"` / `FrozenEstimator` phụ thuộc phiên bản scikit-learn).
Cài đặt dưới đây chỉ dùng LogisticRegression / IsotonicRegression nên tương thích
scikit-learn >= 1.4 (theo ai_engine/requirements.txt).
"""

from typing import List, Optional

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

_EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1.0 - _EPS)
    return np.log(p / (1.0 - p))


class SigmoidCalibrator:
    """Platt scaling: P_cal = sigmoid(a * logit(p_raw) + b)."""

    method = "sigmoid"

    def __init__(self) -> None:
        self._lr = LogisticRegression(C=1e4)

    def fit(self, p_raw: np.ndarray, y: np.ndarray) -> "SigmoidCalibrator":
        self._lr.fit(_logit(p_raw).reshape(-1, 1), np.asarray(y, dtype=int))
        return self

    def predict(self, p_raw: np.ndarray) -> np.ndarray:
        return self._lr.predict_proba(_logit(p_raw).reshape(-1, 1))[:, 1]


class IsotonicCalibrator:
    """Isotonic regression: ánh xạ đơn điệu không tham số, cần nhiều mẫu hơn Platt."""

    method = "isotonic"

    def __init__(self) -> None:
        self._iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")

    def fit(self, p_raw: np.ndarray, y: np.ndarray) -> "IsotonicCalibrator":
        self._iso.fit(np.asarray(p_raw, dtype=float), np.asarray(y, dtype=float))
        return self

    def predict(self, p_raw: np.ndarray) -> np.ndarray:
        return self._iso.predict(np.asarray(p_raw, dtype=float))


CALIBRATORS = {"sigmoid": SigmoidCalibrator, "isotonic": IsotonicCalibrator}


class CalibratedRainModel:
    """
    Gói mô hình phân loại + calibrator cho một horizon; giao diện `predict_proba` giống sklearn
    để Inference Engine hiện tại (`model.predict_proba(X)[0, 1]`) dùng được không cần sửa.

    Từ chối dự đoán (ValueError) khi thiếu cột hoặc feature có NaN, thay vì để mô hình
    âm thầm suy luận trên dữ liệu không đủ lịch sử.
    """

    classes_ = np.array([0, 1])

    def __init__(self, estimator, feature_cols: List[str], horizon_minutes: int,
                 calibrator: Optional[object] = None) -> None:
        self.estimator = estimator
        self.feature_cols = list(feature_cols)
        self.horizon_minutes = horizon_minutes
        self.calibrator = calibrator

    @property
    def calibration_method(self) -> str:
        return self.calibrator.method if self.calibrator is not None else "none"

    def _prepare(self, X) -> pd.DataFrame:
        if not isinstance(X, pd.DataFrame):
            X = pd.DataFrame(np.asarray(X, dtype=float), columns=self.feature_cols)
        missing = [c for c in self.feature_cols if c not in X.columns]
        if missing:
            raise ValueError(f"Thieu feature cho model mua +{self.horizon_minutes}m: {missing}")
        X = X[self.feature_cols].astype(float)
        nan_cols = X.columns[X.isna().any()].tolist()
        if nan_cols:
            raise ValueError(
                f"Feature co NaN (thieu lich su hoac mat mau) cho model mua +{self.horizon_minutes}m: {nan_cols}"
            )
        return X

    def predict_proba_raw(self, X) -> np.ndarray:
        """Xác suất P(mưa) chưa hiệu chuẩn, mảng 1 chiều."""
        X = self._prepare(X)
        pos_idx = list(self.estimator.classes_).index(1)
        return self.estimator.predict_proba(X)[:, pos_idx]

    def predict_proba(self, X) -> np.ndarray:
        p = self.predict_proba_raw(X)
        if self.calibrator is not None:
            p = self.calibrator.predict(p)
        p = np.clip(p, 0.0, 1.0)
        return np.column_stack([1.0 - p, p])
