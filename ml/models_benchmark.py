"""
ML-03: Temperature Forecasting & Model Benchmark
=================================================
Xây dựng và so sánh các mô hình dự báo nhiệt độ đa bước tại các mốc
+10 phút, +30 phút, +60 phút từ dữ liệu IoT thời tiết.

Mô hình được đánh giá:
    [0] Persistence Baseline   — T(t+k) = T(t)  (ngưỡng tối thiểu phải vượt qua)
    [1] Ridge Regression        — L2 regularization
    [2] Lasso Regression        — L1 regularization (feature selection tự động)
    [3] Random Forest Regressor — Ensemble cây quyết định
    [4] XGBoost Regressor       — Gradient Boosting (model chính TV2)

Chỉ số đánh giá:
    - MAE  (Mean Absolute Error)         — sai số trung bình (°C)
    - RMSE (Root Mean Square Error)      — phạt nặng sai số lớn (°C)
    - R²   (Coefficient of Determination) — mức giải thích phương sai

Tác giả: TV2 — Time-Series AI Engineer
Dự án:   IoT Local Weather Forecasting
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.linear_model import Ridge, Lasso
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

warnings.filterwarnings("ignore", category=UserWarning)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------
HORIZONS: List[int] = [10, 30, 60]   # +10min, +30min, +60min
MODEL_SAVE_DIR = Path(__file__).parent / "models"
MODEL_SAVE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Dataclass cấu hình Benchmark
# ---------------------------------------------------------------------------
@dataclass
class BenchmarkConfig:
    """Cấu hình huấn luyện & đánh giá benchmark."""

    # Ridge / Lasso
    ridge_alpha: float = 1.0
    lasso_alpha: float = 0.01

    # Random Forest
    rf_n_estimators: int = 200
    rf_max_depth: Optional[int] = None     # None = không giới hạn độ sâu
    rf_min_samples_leaf: int = 2
    rf_n_jobs: int = -1                    # Dùng tất cả CPU cores
    rf_random_state: int = 42

    # XGBoost
    xgb_n_estimators: int = 300
    xgb_max_depth: int = 6
    xgb_learning_rate: float = 0.05
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8
    xgb_reg_lambda: float = 1.0           # L2 regularization
    xgb_early_stopping_rounds: int = 20
    xgb_n_jobs: int = -1
    xgb_random_state: int = 42

    # Horizons cần huấn luyện
    horizons: List[int] = field(default_factory=lambda: [10, 30, 60])

    # Lưu model sau khi train
    save_models: bool = True
    model_dir: str = str(MODEL_SAVE_DIR)


# ---------------------------------------------------------------------------
# Lớp Benchmark chính
# ---------------------------------------------------------------------------
class TemperatureBenchmark:
    """
    Pipeline đánh giá chuẩn (benchmark) các mô hình dự báo nhiệt độ.

    Ví dụ sử dụng:
    --------------
    >>> benchmark = TemperatureBenchmark(BenchmarkConfig())
    >>> results   = benchmark.run(X_train, X_val, X_test, y_dict, df_raw)
    >>> benchmark.print_report()
    >>> benchmark.plot_benchmark_bars()
    >>> best_model, best_name = benchmark.get_best_model(horizon=10)
    """

    def __init__(self, config: Optional[BenchmarkConfig] = None) -> None:
        self.config = config or BenchmarkConfig()
        # results[horizon][model_name] = {mae, rmse, r2, y_pred}
        self._results: Dict[int, Dict[str, Dict]] = {}
        self._trained_models: Dict[int, Dict[str, object]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        X_train: pd.DataFrame,
        X_val:   pd.DataFrame,
        X_test:  pd.DataFrame,
        y_dict:  Dict[str, pd.Series],
        df_features: Optional[pd.DataFrame] = None,
    ) -> Dict[int, pd.DataFrame]:
        """
        Chạy toàn bộ benchmark cho tất cả horizon.

        Args:
            X_train, X_val, X_test: Ma trận đặc trưng (split theo thời gian).
            y_dict: {'y_10': Series, 'y_30': Series, 'y_60': Series}
                    (chỉ số của Series phải khớp với X_train/val/test).
            df_features: DataFrame đầy đủ (dùng cho Persistence Baseline).

        Returns:
            Dict[horizon → DataFrame bảng benchmark]
        """
        logger.info("=" * 60)
        logger.info("BẮT ĐẦU BENCHMARK — horizons: %s", self.config.horizons)
        logger.info("=" * 60)

        summary_tables: Dict[int, pd.DataFrame] = {}

        for h in self.config.horizons:
            key = f"y_{h}"
            if key not in y_dict:
                logger.warning("Không tìm thấy target '%s' — bỏ qua horizon +%dm.", key, h)
                continue

            logger.info("\n>>> HORIZON +%d PHÚT <<<", h)

            # Lấy y tương ứng với từng split
            y_series = y_dict[key]
            y_train = y_series.loc[X_train.index]
            y_val   = y_series.loc[X_val.index]
            y_test  = y_series.loc[X_test.index]

            horizon_results: Dict[str, Dict] = {}
            trained: Dict[str, object] = {}

            # [0] Persistence Baseline
            pb_res, pb_model = self._eval_persistence(
                X_train, X_val, X_test, y_train, y_val, y_test, horizon=h
            )
            horizon_results["Persistence"] = pb_res
            trained["Persistence"] = pb_model

            # [1] Ridge Regression
            ridge_res, ridge_model = self._train_eval_sklearn(
                Ridge(alpha=self.config.ridge_alpha),
                X_train, X_val, X_test, y_train, y_val, y_test,
                name="Ridge", scale=True
            )
            horizon_results["Ridge"] = ridge_res
            trained["Ridge"] = ridge_model

            # [2] Lasso Regression
            lasso_res, lasso_model = self._train_eval_sklearn(
                Lasso(alpha=self.config.lasso_alpha, max_iter=5000),
                X_train, X_val, X_test, y_train, y_val, y_test,
                name="Lasso", scale=True
            )
            horizon_results["Lasso"] = lasso_res
            trained["Lasso"] = lasso_model

            # [3] Random Forest
            rf_res, rf_model = self._train_eval_sklearn(
                RandomForestRegressor(
                    n_estimators=self.config.rf_n_estimators,
                    max_depth=self.config.rf_max_depth,
                    min_samples_leaf=self.config.rf_min_samples_leaf,
                    n_jobs=self.config.rf_n_jobs,
                    random_state=self.config.rf_random_state,
                ),
                X_train, X_val, X_test, y_train, y_val, y_test,
                name="RandomForest", scale=False
            )
            horizon_results["RandomForest"] = rf_res
            trained["RandomForest"] = rf_model

            # [4] XGBoost (với early stopping dùng val set)
            xgb_res, xgb_model = self._train_eval_xgboost(
                X_train, X_val, X_test, y_train, y_val, y_test, horizon=h
            )
            horizon_results["XGBoost"] = xgb_res
            trained["XGBoost"] = xgb_model

            self._results[h]         = horizon_results
            self._trained_models[h]  = trained

            # Lưu bảng kết quả
            summary_tables[h] = self._build_summary_df(horizon_results, h)

            # Lưu model nếu được cấu hình
            if self.config.save_models:
                self._save_models(trained, horizon=h)

        return summary_tables

    def print_report(self) -> None:
        """In bảng benchmark ra console theo từng horizon."""
        if not self._results:
            logger.warning("Chưa có kết quả. Chạy .run() trước.")
            return

        for h in sorted(self._results.keys()):
            print(f"\n{'=' * 65}")
            print(f"  BẢNG BENCHMARK — DỰ BÁO NHIỆT ĐỘ +{h} PHÚT")
            print(f"{'=' * 65}")
            df = self._build_summary_df(self._results[h], h)
            # Highlight best (thấp nhất MAE) bằng dấu *
            best_idx = df["MAE_test (°C)"].idxmin()
            print(df.to_string(index=True))
            print(f"\n  >> Model tốt nhất theo MAE test: [{best_idx}] "
                  f"(MAE = {df.loc[best_idx, 'MAE_test (°C)']:.4f} °C)")

    def get_best_model(
        self,
        horizon: int,
        metric: str = "MAE_test (°C)"
    ) -> Tuple[object, str]:
        """
        Trả về model tốt nhất và tên của nó tại một horizon cụ thể.

        Args:
            horizon: 10, 30 hoặc 60.
            metric:  Tên cột metric để so sánh (mặc định: MAE test).

        Returns:
            (model_object, model_name)
        """
        if horizon not in self._results:
            raise ValueError(f"Horizon {horizon} chưa được huấn luyện.")

        df = self._build_summary_df(self._results[horizon], horizon)
        best_name = df[metric].idxmin()
        best_model = self._trained_models[horizon][best_name]
        logger.info(
            "Best model @+%dm: [%s] — %s = %.4f",
            horizon, best_name, metric, df.loc[best_name, metric]
        )
        return best_model, best_name

    def get_all_results(self) -> Dict[int, Dict[str, Dict]]:
        """Trả về toàn bộ dict kết quả thô (dùng cho export/logging)."""
        return self._results

    def plot_benchmark_bars(
        self,
        figsize: Tuple[int, int] = (16, 10),
        save_path: Optional[str] = None,
    ) -> plt.Figure:
        """
        Vẽ biểu đồ cột so sánh MAE/RMSE/R² của tất cả model theo từng horizon.

        Args:
            figsize:   Kích thước figure.
            save_path: Đường dẫn lưu PNG.

        Returns:
            matplotlib Figure.
        """
        if not self._results:
            raise RuntimeError("Chưa có kết quả. Chạy .run() trước.")

        horizons = sorted(self._results.keys())
        n_h = len(horizons)
        metrics = ["MAE_test (°C)", "RMSE_test (°C)", "R²_test"]
        metric_labels = ["MAE (°C) ↓", "RMSE (°C) ↓", "R² ↑"]

        fig = plt.figure(figsize=figsize)
        gs  = gridspec.GridSpec(n_h, 3, figure=fig, hspace=0.5, wspace=0.35)

        colors = sns.color_palette("Set2", 5)

        for r, h in enumerate(horizons):
            df = self._build_summary_df(self._results[h], h)
            models = df.index.tolist()
            x = np.arange(len(models))

            for c, (metric, mlabel) in enumerate(zip(metrics, metric_labels)):
                ax = fig.add_subplot(gs[r, c])
                bars = ax.bar(x, df[metric], color=colors[:len(models)],
                              edgecolor="white", width=0.6)

                # Đánh dấu giá trị tốt nhất
                if "↓" in mlabel:
                    best_i = df[metric].values.argmin()
                else:
                    best_i = df[metric].values.argmax()
                bars[best_i].set_edgecolor("gold")
                bars[best_i].set_linewidth(2.5)

                # Ghi giá trị lên đỉnh cột
                for bar in bars:
                    val = bar.get_height()
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        val * 1.01 if val >= 0 else val * 0.99,
                        f"{val:.3f}",
                        ha="center", va="bottom", fontsize=7.5
                    )

                ax.set_xticks(x)
                ax.set_xticklabels(models, rotation=25, ha="right", fontsize=8)
                ax.set_title(f"+{h}min — {mlabel}", fontsize=9, fontweight="bold")
                ax.grid(axis="y", alpha=0.3, linestyle="--")
                ax.spines[["top", "right"]].set_visible(False)

        fig.suptitle(
            "Model Benchmark — Temperature Forecasting (TV2)",
            fontsize=13, fontweight="bold", y=1.01
        )

        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Đã lưu biểu đồ benchmark → %s", save_path)

        return fig

    def plot_prediction_vs_actual(
        self,
        X_test:  pd.DataFrame,
        y_test:  pd.Series,
        horizon: int = 10,
        n_samples: int = 200,
        save_path: Optional[str] = None,
    ) -> plt.Figure:
        """
        Vẽ đồ thị Actual vs Predicted của từng model tại một horizon.

        Args:
            X_test:    Test features.
            y_test:    Test ground-truth.
            horizon:   Horizon cần vẽ (10, 30 hoặc 60).
            n_samples: Số điểm vẽ (lấy n_samples cuối để nhìn rõ hơn).
            save_path: Đường dẫn lưu PNG.

        Returns:
            matplotlib Figure.
        """
        if horizon not in self._trained_models:
            raise ValueError(f"Horizon {horizon} chưa huấn luyện.")

        models = self._trained_models[horizon]
        n_models = len(models)
        fig, axes = plt.subplots(n_models, 1, figsize=(14, 3.5 * n_models),
                                 sharex=True)
        if n_models == 1:
            axes = [axes]

        idx = y_test.index[-n_samples:]
        y_true_plot = y_test.loc[idx]

        for ax, (name, model) in zip(axes, models.items()):
            if name == "Persistence":
                # Persistence: lấy T(t) tại thời điểm test
                y_pred = X_test.loc[idx, "T_lag_1"] if "T_lag_1" in X_test.columns \
                         else y_true_plot.shift(horizon).fillna(method="bfill")
            elif hasattr(model, "predict"):
                y_pred = pd.Series(
                    model.predict(X_test.loc[idx]),
                    index=idx
                )
            else:
                continue

            mae = mean_absolute_error(y_true_plot, y_pred)
            ax.plot(idx, y_true_plot.values, label="Actual", color="steelblue",
                    linewidth=1.2, alpha=0.9)
            ax.plot(idx, y_pred.values if hasattr(y_pred, 'values') else y_pred,
                    label=f"{name} (MAE={mae:.3f}°C)",
                    color="tomato", linewidth=1.0, linestyle="--", alpha=0.85)
            ax.set_title(f"[+{horizon}min] {name}", fontsize=10, fontweight="bold")
            ax.set_ylabel("Nhiệt độ (°C)")
            ax.legend(loc="upper right", fontsize=8)
            ax.grid(True, alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)

        axes[-1].set_xlabel("Thời gian")
        plt.suptitle(
            f"Actual vs Predicted — +{horizon} phút",
            fontsize=12, fontweight="bold"
        )
        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Đã lưu đồ thị dự báo → %s", save_path)

        return fig

    def plot_feature_importance(
        self,
        horizon: int = 10,
        top_n: int = 15,
        save_path: Optional[str] = None,
    ) -> plt.Figure:
        """
        Vẽ biểu đồ feature importance của Random Forest và XGBoost.

        Args:
            horizon:   Horizon cần phân tích.
            top_n:     Số đặc trưng quan trọng nhất hiển thị.
            save_path: Đường dẫn lưu PNG.

        Returns:
            matplotlib Figure.
        """
        if horizon not in self._trained_models:
            raise ValueError(f"Horizon {horizon} chưa huấn luyện.")

        tree_models = {
            name: mdl
            for name, mdl in self._trained_models[horizon].items()
            if name in ("RandomForest", "XGBoost")
        }

        if not tree_models:
            logger.warning("Không có model cây nào để vẽ feature importance.")
            return None

        fig, axes = plt.subplots(1, len(tree_models),
                                 figsize=(8 * len(tree_models), 6))
        if len(tree_models) == 1:
            axes = [axes]

        colors = {"RandomForest": "steelblue", "XGBoost": "darkorange"}

        for ax, (name, model) in zip(axes, tree_models.items()):
            # Lấy feature importance từ model (RF dùng .feature_importances_,
            # XGBoost dùng gain-based importance)
            if hasattr(model, "feature_importances_"):
                importances = model.feature_importances_
                feat_names = model.feature_names_in_ \
                    if hasattr(model, "feature_names_in_") else \
                    [f"f{i}" for i in range(len(importances))]
            else:
                logger.warning("Model '%s' không có feature_importances_.", name)
                continue

            imp_series = pd.Series(importances, index=feat_names).nlargest(top_n)

            ax.barh(imp_series.index[::-1], imp_series.values[::-1],
                    color=colors.get(name, "gray"), edgecolor="white", alpha=0.85)
            ax.set_title(f"Feature Importance — {name} (+{horizon}min)",
                         fontsize=11, fontweight="bold")
            ax.set_xlabel("Importance Score")
            ax.grid(axis="x", alpha=0.3)
            ax.spines[["top", "right"]].set_visible(False)

        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Đã lưu feature importance → %s", save_path)

        return fig

    def export_results_json(self, save_path: str) -> None:
        """
        Xuất kết quả benchmark ra JSON (dùng để nhúng vào báo cáo).

        Args:
            save_path: Đường dẫn file .json.
        """
        export = {}
        for h, model_results in self._results.items():
            export[f"horizon_{h}min"] = {}
            for model_name, metrics in model_results.items():
                export[f"horizon_{h}min"][model_name] = {
                    k: round(float(v), 6)
                    for k, v in metrics.items()
                    if k not in ("y_pred_test", "y_pred_val")
                }
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False)
        logger.info("Đã xuất kết quả → %s", save_path)

    # ------------------------------------------------------------------
    # Private — các phương thức huấn luyện & đánh giá
    # ------------------------------------------------------------------

    def _eval_persistence(
        self,
        X_train, X_val, X_test,
        y_train, y_val, y_test,
        horizon: int,
    ) -> Tuple[Dict, str]:
        """
        Persistence Baseline: T(t+k) = T(t).
        Dùng giá trị hiện tại (T_lag_1 hoặc temperature) làm dự báo.
        Đây là ngưỡng tối thiểu (lower bound) mà bất kỳ ML model nào cũng phải vượt qua.
        """
        # Lấy cột nhiệt độ hiện tại — ưu tiên T_lag_1 (= T(t) sau shift)
        # hoặc temperature nếu cột đó tồn tại
        current_col = None
        for candidate in ["T_lag_1", "temperature"]:
            if candidate in X_test.columns:
                current_col = candidate
                break

        if current_col is None:
            logger.warning("Persistence: không tìm thấy cột T hiện tại, dùng y shift.")
            y_pred_test = y_test.shift(horizon).fillna(y_test.iloc[0])
            y_pred_val  = y_val.shift(horizon).fillna(y_val.iloc[0])
        else:
            y_pred_test = X_test[current_col].values
            y_pred_val  = X_val[current_col].values

        metrics = self._compute_metrics(y_test, y_pred_test, y_val, y_pred_val)
        logger.info(
            "  [Persistence Baseline] MAE_test=%.4f | RMSE_test=%.4f | R²_test=%.4f",
            metrics["mae_test"], metrics["rmse_test"], metrics["r2_test"]
        )
        return metrics, "PersistenceBaseline"

    def _train_eval_sklearn(
        self,
        estimator,
        X_train, X_val, X_test,
        y_train, y_val, y_test,
        name: str,
        scale: bool = True,
    ) -> Tuple[Dict, object]:
        """
        Huấn luyện một sklearn estimator (Ridge, Lasso, RF) và đánh giá.

        Args:
            estimator: sklearn estimator đã khởi tạo.
            scale:     True = thêm StandardScaler vào pipeline (cần thiết cho linear models).
        """
        if scale:
            model = Pipeline([
                ("scaler", StandardScaler()),
                ("reg", estimator),
            ])
        else:
            model = estimator

        try:
            model.fit(X_train, y_train)
        except Exception as exc:
            logger.error("Lỗi khi fit model '%s': %s", name, exc)
            raise

        y_pred_test = model.predict(X_test)
        y_pred_val  = model.predict(X_val)

        metrics = self._compute_metrics(y_test, y_pred_test, y_val, y_pred_val)
        logger.info(
            "  [%s] MAE_test=%.4f | RMSE_test=%.4f | R²_test=%.4f",
            name, metrics["mae_test"], metrics["rmse_test"], metrics["r2_test"]
        )
        return metrics, model

    def _train_eval_xgboost(
        self,
        X_train, X_val, X_test,
        y_train, y_val, y_test,
        horizon: int,
    ) -> Tuple[Dict, object]:
        """
        Huấn luyện XGBoost với Early Stopping trên validation set.
        Early stopping giúp tránh overfitting tự động.
        """
        model = XGBRegressor(
            n_estimators=self.config.xgb_n_estimators,
            max_depth=self.config.xgb_max_depth,
            learning_rate=self.config.xgb_learning_rate,
            subsample=self.config.xgb_subsample,
            colsample_bytree=self.config.xgb_colsample_bytree,
            reg_lambda=self.config.xgb_reg_lambda,
            early_stopping_rounds=self.config.xgb_early_stopping_rounds,
            n_jobs=self.config.xgb_n_jobs,
            random_state=self.config.xgb_random_state,
            verbosity=0,
        )
        try:
            model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False,
            )
        except Exception as exc:
            logger.error("Lỗi khi fit XGBoost horizon +%dm: %s", horizon, exc)
            raise

        y_pred_test = model.predict(X_test)
        y_pred_val  = model.predict(X_val)

        best_iter = model.best_iteration if hasattr(model, "best_iteration") else \
                    self.config.xgb_n_estimators
        logger.info(
            "  [XGBoost] best_iter=%d | MAE_test=%.4f | RMSE_test=%.4f | R²_test=%.4f",
            best_iter,
            mean_absolute_error(y_test, y_pred_test),
            np.sqrt(mean_squared_error(y_test, y_pred_test)),
            r2_score(y_test, y_pred_test),
        )

        metrics = self._compute_metrics(y_test, y_pred_test, y_val, y_pred_val)
        metrics["xgb_best_iteration"] = best_iter
        return metrics, model

    @staticmethod
    def _compute_metrics(
        y_test,  y_pred_test,
        y_val,   y_pred_val,
    ) -> Dict:
        """
        Tính đầy đủ MAE, RMSE, R² trên cả val và test set.
        Tách val/test để phát hiện overfitting (val tốt nhưng test kém).
        """
        def _rmse(y_true, y_pred) -> float:
            return float(np.sqrt(mean_squared_error(y_true, y_pred)))

        return {
            # Validation metrics
            "mae_val":  float(mean_absolute_error(y_val, y_pred_val)),
            "rmse_val": _rmse(y_val, y_pred_val),
            "r2_val":   float(r2_score(y_val, y_pred_val)),
            # Test metrics (số liệu chính trong báo cáo)
            "mae_test":  float(mean_absolute_error(y_test, y_pred_test)),
            "rmse_test": _rmse(y_test, y_pred_test),
            "r2_test":   float(r2_score(y_test, y_pred_test)),
            # Giữ y_pred để vẽ đồ thị sau
            "y_pred_test": y_pred_test,
            "y_pred_val":  y_pred_val,
        }

    @staticmethod
    def _build_summary_df(horizon_results: Dict[str, Dict], horizon: int) -> pd.DataFrame:
        """Tạo DataFrame bảng tóm tắt từ dict kết quả."""
        rows = []
        for model_name, metrics in horizon_results.items():
            rows.append({
                "Model":            model_name,
                "MAE_val (°C)":     round(metrics["mae_val"],  4),
                "RMSE_val (°C)":    round(metrics["rmse_val"], 4),
                "R²_val":           round(metrics["r2_val"],   4),
                "MAE_test (°C)":    round(metrics["mae_test"], 4),
                "RMSE_test (°C)":   round(metrics["rmse_test"],4),
                "R²_test":          round(metrics["r2_test"],  4),
            })
        df = pd.DataFrame(rows).set_index("Model")
        return df

    def _save_models(self, trained: Dict[str, object], horizon: int) -> None:
        """Lưu tất cả model vào thư mục model_dir theo từng horizon."""
        save_dir = Path(self.config.model_dir)
        save_dir.mkdir(exist_ok=True)

        for name, model in trained.items():
            if name == "Persistence":
                continue  # Persistence không cần lưu (không có state)
            save_path = save_dir / f"{name}_h{horizon}min.joblib"
            try:
                joblib.dump(model, save_path)
                logger.info("Đã lưu model: %s", save_path)
            except Exception as exc:
                logger.error("Lỗi lưu model '%s': %s", name, exc)


# ---------------------------------------------------------------------------
# Hàm tiện ích: load model đã lưu
# ---------------------------------------------------------------------------

def load_trained_model(model_name: str, horizon: int, model_dir: str = str(MODEL_SAVE_DIR)):
    """
    Load model đã được lưu bằng .joblib.

    Args:
        model_name: Tên model ('Ridge', 'Lasso', 'RandomForest', 'XGBoost').
        horizon:    Horizon dự báo (10, 30, 60).
        model_dir:  Thư mục chứa model.

    Returns:
        Model object đã load.
    """
    path = Path(model_dir) / f"{model_name}_h{horizon}min.joblib"
    if not path.exists():
        raise FileNotFoundError(f"Model không tìm thấy: {path}")
    model = joblib.load(path)
    logger.info("Đã load model: %s", path)
    return model


# ---------------------------------------------------------------------------
# Script chạy thử nhanh
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from ml.preprocessing import (
        TimeSeriesPreprocessor, PreprocessingConfig, generate_sample_iot_data
    )
    from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig

    print("=" * 65)
    print("  ML-03: Temperature Forecasting & Benchmark — Quick Test")
    print("=" * 65)

    # 1. Tạo dữ liệu (14 ngày)
    print("\n[1/5] Tạo dữ liệu mẫu 14 ngày...")
    df_raw = generate_sample_iot_data(n_minutes=60 * 24 * 14, seed=42)

    # 2. Preprocessing
    print("[2/5] Tiền xử lý...")
    prep     = TimeSeriesPreprocessor(PreprocessingConfig())
    df_clean = prep.fit_transform(df_raw)

    # 3. Feature Engineering
    print("[3/5] Feature Engineering...")
    feat_cfg = FeatureConfig(
        lag_steps=[1, 2, 3, 6, 10, 30],
        delta_steps=[1, 5, 10],
        rolling_windows=[6, 10, 30, 60],
        forecast_horizons=[10, 30, 60],
    )
    engineer    = TemperatureFeatureEngineer(feat_cfg)
    df_features = engineer.fit_transform(df_clean)
    X, y_dict   = engineer.get_Xy(df_features)

    # 4. Train/Val/Test split (theo thời gian, không shuffle)
    X_train, X_val, X_test, _, _, _ = engineer.train_val_test_split(
        X, y_dict["y_10"]
    )
    # Lấy y theo đúng index của từng split
    y_train_dict = {k: v.loc[X_train.index] for k, v in y_dict.items()}
    y_val_dict   = {k: v.loc[X_val.index]   for k, v in y_dict.items()}
    y_test_dict  = {k: v.loc[X_test.index]  for k, v in y_dict.items()}

    print(f"     Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

    # 5. Chạy benchmark
    print("[4/5] Đang huấn luyện & benchmark tất cả model...")
    bench_cfg = BenchmarkConfig(
        rf_n_estimators=100,     # Giảm để chạy nhanh khi test
        xgb_n_estimators=150,
        horizons=[10, 30, 60],
        save_models=True,
    )
    benchmark = TemperatureBenchmark(bench_cfg)
    results   = benchmark.run(X_train, X_val, X_test, y_dict)

    # 6. In báo cáo
    print("\n[5/5] KẾT QUẢ BENCHMARK:")
    benchmark.print_report()

    # 7. Model tốt nhất tại +10min
    best_model, best_name = benchmark.get_best_model(horizon=10)
    print(f"\n>> Model tốt nhất @+10min: {best_name}")

    # 8. Vẽ biểu đồ (save PNG)
    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)

    print("\nVẽ biểu đồ benchmark...")
    benchmark.plot_benchmark_bars(
        save_path=str(out_dir / "benchmark_bars.png")
    )
    benchmark.plot_feature_importance(
        horizon=10,
        save_path=str(out_dir / "feature_importance_h10.png")
    )

    # 9. Export JSON
    benchmark.export_results_json(str(out_dir / "benchmark_results.json"))

    print("\n✅ ML-03 Benchmark pipeline OK!")
    print(f"   - Biểu đồ: {out_dir / 'benchmark_bars.png'}")
    print(f"   - JSON:    {out_dir / 'benchmark_results.json'}")
    print(f"   - Models:  {Path(bench_cfg.model_dir)}/")
