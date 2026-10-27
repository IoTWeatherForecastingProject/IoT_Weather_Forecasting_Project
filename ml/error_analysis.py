"""
ML-05: Error Analysis & Diagnostics
====================================
Phân tích toàn diện sai số (residual) của mô hình dự báo nhiệt độ tốt nhất.

Nội dung:
    [1] Residual Analysis       — phân phối phần dư, QQ-plot, histogram
    [2] Horizon Degradation     — MAE/RMSE suy giảm khi horizon tăng +10→+30→+60
    [3] Conditional Error       — sai số theo điều kiện (giờ trong ngày, nhiệt độ cao/thấp)
    [4] Rapid Change Analysis   — sai số khi nhiệt độ biến đổi nhanh (|ΔT| > ngưỡng)
    [5] Autocorrelation of Residuals — kiểm tra phần dư có còn tự tương quan không
    [6] Error Report            — xuất bảng & đồ thị cho báo cáo đồ án

Tác giả: TV2 — Time-Series AI Engineer
Dự án:   IoT Local Weather Forecasting
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
import scipy.stats as stats
import seaborn as sns
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import acf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------
@dataclass
class ErrorAnalysisConfig:
    """Cấu hình cho pipeline phân tích sai số."""
    # Ngưỡng biến đổi nhanh: |ΔT| > threshold → "rapid change"
    rapid_change_threshold: float = 0.5   # °C/phút

    # Số lag kiểm tra ACF phần dư
    acf_nlags: int = 40

    # Bin phân chia nhiệt độ để phân tích conditional error
    temp_bins: List[float] = field(
        default_factory=lambda: [0, 22, 26, 30, 34, 60]
    )
    temp_bin_labels: List[str] = field(
        default_factory=lambda: ["<22°C", "22-26°C", "26-30°C", "30-34°C", ">34°C"]
    )

    # Horizons cần phân tích
    horizons: List[int] = field(default_factory=lambda: [10, 30, 60])


# ---------------------------------------------------------------------------
# Lớp phân tích sai số chính
# ---------------------------------------------------------------------------
class ErrorAnalyzer:
    """
    Pipeline phân tích sai số toàn diện cho bài toán dự báo nhiệt độ.

    Ví dụ sử dụng:
    --------------
    >>> analyzer = ErrorAnalyzer(config)
    >>> report   = analyzer.run(y_true_dict, y_pred_dict, df_test_features)
    >>> analyzer.plot_full_dashboard(save_path="error_dashboard.png")
    """

    def __init__(self, config: Optional[ErrorAnalysisConfig] = None) -> None:
        self.config = config or ErrorAnalysisConfig()
        self._report: Dict = {}
        self._residuals: Dict[int, np.ndarray] = {}   # horizon → residuals

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        y_true_dict: Dict[int, np.ndarray],
        y_pred_dict: Dict[int, np.ndarray],
        df_test:     Optional[pd.DataFrame] = None,
    ) -> Dict:
        """
        Chạy toàn bộ pipeline phân tích sai số.

        Args:
            y_true_dict: {horizon → array giá trị thực tế °C}
            y_pred_dict: {horizon → array giá trị dự báo °C}
            df_test:     DataFrame test có DatetimeIndex (dùng cho conditional analysis).
                         Cần có cột 'temperature'.

        Returns:
            Dict báo cáo tổng hợp.
        """
        logger.info("=== BẮT ĐẦU ERROR ANALYSIS ===")

        # Tính residuals
        for h in self.config.horizons:
            if h not in y_true_dict or h not in y_pred_dict:
                logger.warning("Thiếu dữ liệu cho horizon +%dm — bỏ qua.", h)
                continue
            residuals = np.array(y_true_dict[h]) - np.array(y_pred_dict[h])
            self._residuals[h] = residuals

        # [1] Thống kê phần dư cơ bản
        self._report["residual_stats"]     = self._compute_residual_stats()

        # [2] Phân tích suy giảm theo horizon
        self._report["horizon_degradation"] = self._compute_horizon_degradation(
            y_true_dict, y_pred_dict
        )

        # [3] Conditional error (theo giờ trong ngày, theo bin nhiệt độ)
        if df_test is not None:
            self._report["conditional_error"] = self._compute_conditional_error(
                y_true_dict, y_pred_dict, df_test
            )

        # [4] Rapid change analysis
        if df_test is not None and "temperature" in df_test.columns:
            self._report["rapid_change"] = self._compute_rapid_change_error(
                y_true_dict, y_pred_dict, df_test
            )

        # [5] Durbin-Watson test (phần dư có tự tương quan không)
        self._report["durbin_watson"] = self._compute_durbin_watson()

        logger.info("=== ERROR ANALYSIS HOÀN TẤT ===")
        self._print_summary()
        return self._report

    def plot_full_dashboard(
        self,
        figsize:   Tuple[int, int] = (18, 22),
        save_path: Optional[str]   = None,
    ) -> plt.Figure:
        """
        Vẽ dashboard phân tích sai số toàn diện (6 vùng biểu đồ).

        Layout:
            Row 1: Phân phối residuals (histogram + KDE) — 3 horizon
            Row 2: QQ-Plot                               — 3 horizon
            Row 3: Residual vs Fitted (scatter)          — 3 horizon
            Row 4: ACF của residuals                     — 3 horizon
            Row 5: Horizon Degradation bar               — MAE + RMSE
            Row 6: Conditional error (giờ trong ngày)   — nếu có
        """
        if not self._residuals:
            raise RuntimeError("Chạy .run() trước khi vẽ dashboard.")

        n_h = len(self._residuals)
        n_rows = 5 if "conditional_error" not in self._report else 6
        fig = plt.figure(figsize=figsize)
        gs  = gridspec.GridSpec(n_rows, n_h, figure=fig,
                                hspace=0.55, wspace=0.35)

        horizons = sorted(self._residuals.keys())
        colors   = ["steelblue", "darkorange", "seagreen"]

        for c, (h, color) in enumerate(zip(horizons, colors)):
            res = self._residuals[h]

            # ── Row 0: Histogram + KDE ─────────────────────────────
            ax = fig.add_subplot(gs[0, c])
            ax.hist(res, bins=40, density=True, alpha=0.65,
                    color=color, edgecolor="white", label="Histogram")
            xmin, xmax = res.min(), res.max()
            xs = np.linspace(xmin, xmax, 200)
            from scipy.stats import norm
            mu, sigma = res.mean(), res.std()
            ax.plot(xs, norm.pdf(xs, mu, sigma), "k--", lw=1.5,
                    label=f"Normal μ={mu:.3f}")
            ax.set_title(f"+{h}min — Phân phối Residual", fontsize=9,
                         fontweight="bold")
            ax.set_xlabel("Residual (°C)"); ax.legend(fontsize=7)
            ax.grid(alpha=0.3); ax.spines[["top","right"]].set_visible(False)

            # ── Row 1: QQ-Plot ─────────────────────────────────────
            ax = fig.add_subplot(gs[1, c])
            (osm, osr), (slope, intercept, r) = stats.probplot(res, dist="norm")
            ax.scatter(osm, osr, s=6, alpha=0.5, color=color)
            ax.plot([osm[0], osm[-1]],
                    [slope*osm[0]+intercept, slope*osm[-1]+intercept],
                    "r--", lw=1.5, label=f"R={r:.3f}")
            ax.set_title(f"+{h}min — QQ-Plot", fontsize=9, fontweight="bold")
            ax.set_xlabel("Theoretical Quantiles")
            ax.set_ylabel("Sample Quantiles")
            ax.legend(fontsize=7); ax.grid(alpha=0.3)
            ax.spines[["top","right"]].set_visible(False)

            # ── Row 2: Residual vs Index (time) ────────────────────
            ax = fig.add_subplot(gs[2, c])
            ax.scatter(range(len(res)), res, s=3, alpha=0.3, color=color)
            ax.axhline(0, color="red", lw=1.2, linestyle="--")
            ax.axhline( res.std(), color="gray", lw=0.8, linestyle=":")
            ax.axhline(-res.std(), color="gray", lw=0.8, linestyle=":")
            ax.set_title(f"+{h}min — Residual theo thời gian", fontsize=9,
                         fontweight="bold")
            ax.set_xlabel("Sample index"); ax.set_ylabel("Residual (°C)")
            ax.grid(alpha=0.3); ax.spines[["top","right"]].set_visible(False)

            # ── Row 3: ACF của residuals ───────────────────────────
            ax = fig.add_subplot(gs[3, c])
            nlags = min(self.config.acf_nlags, len(res) // 2 - 1)
            acf_vals = acf(res, nlags=nlags, fft=True)
            ci = 1.96 / np.sqrt(len(res))
            ax.bar(range(nlags + 1), acf_vals, color=color, alpha=0.7,
                   width=0.8, edgecolor="none")
            ax.axhline( ci, color="red", lw=1, linestyle="--", label=f"±{ci:.3f}")
            ax.axhline(-ci, color="red", lw=1, linestyle="--")
            ax.axhline(0,   color="black", lw=0.5)
            ax.set_title(f"+{h}min — ACF Residual", fontsize=9, fontweight="bold")
            ax.set_xlabel("Lag"); ax.set_ylabel("ACF")
            ax.legend(fontsize=7); ax.grid(alpha=0.3)
            ax.spines[["top","right"]].set_visible(False)

        # ── Row 4: Horizon Degradation ─────────────────────────────
        if "horizon_degradation" in self._report:
            ax_mae  = fig.add_subplot(gs[4, 0])
            ax_rmse = fig.add_subplot(gs[4, 1])
            ax_r2   = fig.add_subplot(gs[4, 2])
            deg = self._report["horizon_degradation"]

            h_labels = [f"+{h}m" for h in horizons]
            maes  = [deg[h]["mae"]  for h in horizons]
            rmses = [deg[h]["rmse"] for h in horizons]
            r2s   = [deg[h]["r2"]   for h in horizons]

            for ax_d, vals, ylabel, col in [
                (ax_mae,  maes,  "MAE (°C)",  "steelblue"),
                (ax_rmse, rmses, "RMSE (°C)", "darkorange"),
                (ax_r2,   r2s,   "R²",        "seagreen"),
            ]:
                bars = ax_d.bar(h_labels, vals, color=col, edgecolor="white",
                                width=0.5, alpha=0.85)
                for bar in bars:
                    v = bar.get_height()
                    ax_d.text(bar.get_x() + bar.get_width()/2, v*1.01,
                              f"{v:.4f}", ha="center", va="bottom", fontsize=8)
                ax_d.set_title(f"Horizon Degradation — {ylabel}",
                               fontsize=9, fontweight="bold")
                ax_d.set_xlabel("Forecast Horizon")
                ax_d.set_ylabel(ylabel)
                ax_d.grid(axis="y", alpha=0.3)
                ax_d.spines[["top","right"]].set_visible(False)

        # ── Row 5: Conditional Error theo giờ ─────────────────────
        if "conditional_error" in self._report and n_rows == 6:
            for c, h in enumerate(horizons):
                ax = fig.add_subplot(gs[5, c])
                ce = self._report["conditional_error"].get(f"by_hour_{h}")
                if ce:
                    hours  = sorted(ce.keys())
                    mae_by_hour = [ce[hr] for hr in hours]
                    ax.plot(hours, mae_by_hour, marker="o", markersize=4,
                            color=colors[c], linewidth=1.5)
                    ax.fill_between(hours, mae_by_hour, alpha=0.15, color=colors[c])
                    ax.axhline(np.mean(mae_by_hour), color="red",
                               lw=1, linestyle="--", label="Mean MAE")
                    ax.set_title(f"+{h}min — MAE theo giờ", fontsize=9,
                                 fontweight="bold")
                    ax.set_xlabel("Giờ trong ngày (0-23)")
                    ax.set_ylabel("MAE (°C)")
                    ax.legend(fontsize=7); ax.grid(alpha=0.3)
                    ax.spines[["top","right"]].set_visible(False)

        fig.suptitle("Error Analysis Dashboard — Temperature Forecasting (TV2)",
                     fontsize=14, fontweight="bold", y=1.002)
        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=130, bbox_inches="tight")
            logger.info("Đã lưu Error Dashboard → %s", save_path)
        return fig

    def export_report_json(self, save_path: str) -> None:
        """Xuất báo cáo phân tích sai số ra JSON."""
        export = {}
        for key, val in self._report.items():
            if key == "residual_stats":
                export[key] = val
            elif key == "horizon_degradation":
                export[key] = {str(k): v for k, v in val.items()}
            elif key == "durbin_watson":
                export[key] = {str(k): round(float(v), 4) for k, v in val.items()}
            else:
                # Bỏ qua dữ liệu phức tạp không serializable
                export[key] = "See plot"

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False)
        logger.info("Đã xuất báo cáo → %s", save_path)

    def get_report(self) -> Dict:
        """Trả về toàn bộ dict báo cáo."""
        return self._report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_residual_stats(self) -> Dict:
        """
        Thống kê mô tả phần dư: mean, std, MAE, RMSE, skewness, kurtosis,
        tỷ lệ điểm vượt ngưỡng ±1°C.
        """
        stats_dict = {}
        for h, res in self._residuals.items():
            mae  = float(np.abs(res).mean())
            rmse = float(np.sqrt((res**2).mean()))
            stats_dict[h] = {
                "mean":       round(float(res.mean()), 6),
                "std":        round(float(res.std()),  6),
                "mae":        round(mae,  4),
                "rmse":       round(rmse, 4),
                "r2":         round(float(1 - (res**2).sum() /
                                    max((res - res.mean())**2 + 1e-12).sum()), 4),
                "skewness":   round(float(stats.skew(res)),     4),
                "kurtosis":   round(float(stats.kurtosis(res)), 4),
                "pct_over_1C":round(float((np.abs(res) > 1.0).mean() * 100), 2),
                "pct_over_2C":round(float((np.abs(res) > 2.0).mean() * 100), 2),
                "n_samples":  len(res),
            }
            logger.info(
                "+%dm → MAE=%.4f°C | RMSE=%.4f°C | skew=%.3f | kurt=%.3f",
                h, mae, rmse,
                stats_dict[h]["skewness"], stats_dict[h]["kurtosis"]
            )
        return stats_dict

    def _compute_horizon_degradation(
        self,
        y_true_dict: Dict[int, np.ndarray],
        y_pred_dict: Dict[int, np.ndarray],
    ) -> Dict:
        """
        Tính MAE, RMSE, R² cho từng horizon → thể hiện mức suy giảm
        độ chính xác khi chân trời dự báo tăng.
        """
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        degradation = {}
        for h in self.config.horizons:
            if h not in y_true_dict:
                continue
            yt = np.array(y_true_dict[h])
            yp = np.array(y_pred_dict[h])
            degradation[h] = {
                "mae":  round(float(mean_absolute_error(yt, yp)), 4),
                "rmse": round(float(np.sqrt(mean_squared_error(yt, yp))), 4),
                "r2":   round(float(r2_score(yt, yp)), 4),
            }

        # Log xu hướng suy giảm
        if len(degradation) >= 2:
            hs = sorted(degradation.keys())
            mae_vals = [degradation[h]["mae"] for h in hs]
            pct_degradation = (mae_vals[-1] - mae_vals[0]) / mae_vals[0] * 100
            logger.info(
                "Horizon degradation: MAE tăng %.1f%% từ +%dm đến +%dm",
                pct_degradation, hs[0], hs[-1]
            )
        return degradation

    def _compute_conditional_error(
        self,
        y_true_dict: Dict[int, np.ndarray],
        y_pred_dict: Dict[int, np.ndarray],
        df_test:     pd.DataFrame,
    ) -> Dict:
        """
        Tính MAE theo từng điều kiện:
            - Giờ trong ngày (0–23)
            - Bin nhiệt độ ([<22, 22-26, 26-30, 30-34, >34]°C)
        """
        ce = {}
        n  = len(df_test)

        for h in self.config.horizons:
            if h not in y_true_dict:
                continue
            yt  = np.array(y_true_dict[h])
            yp  = np.array(y_pred_dict[h])
            res = np.abs(yt - yp)
            n_use = min(len(res), n)
            res_trunc = res[:n_use]

            # ── Theo giờ ─────────────────────────────────────────
            if isinstance(df_test.index, pd.DatetimeIndex):
                hours = df_test.index.hour[:n_use]
                by_hour = {}
                for hr in range(24):
                    mask = hours == hr
                    if mask.sum() > 0:
                        by_hour[hr] = round(float(res_trunc[mask].mean()), 4)
                ce[f"by_hour_{h}"] = by_hour

            # ── Theo bin nhiệt độ ─────────────────────────────────
            if "temperature" in df_test.columns:
                temps = df_test["temperature"].values[:n_use]
                bins   = self.config.temp_bins
                labels = self.config.temp_bin_labels
                by_bin = {}
                for i in range(len(bins) - 1):
                    mask = (temps >= bins[i]) & (temps < bins[i+1])
                    if mask.sum() > 0:
                        by_bin[labels[i]] = round(
                            float(res_trunc[mask].mean()), 4
                        )
                ce[f"by_temp_bin_{h}"] = by_bin

        return ce

    def _compute_rapid_change_error(
        self,
        y_true_dict: Dict[int, np.ndarray],
        y_pred_dict: Dict[int, np.ndarray],
        df_test:     pd.DataFrame,
    ) -> Dict:
        """
        Phân tích sai số trong điều kiện nhiệt độ biến đổi nhanh.
        Tiêu chí: |ΔT| = |T(t) - T(t-1)| > rapid_change_threshold.
        """
        thr = self.config.rapid_change_threshold
        rc  = {}

        if "temperature" not in df_test.columns:
            return rc

        delta_T   = df_test["temperature"].diff().abs()
        rapid_mask = delta_T > thr
        n_rapid   = rapid_mask.sum()
        n_total   = len(rapid_mask.dropna())

        rc["threshold_C_per_min"] = thr
        rc["pct_rapid_change"]    = round(float(n_rapid / n_total * 100), 2)
        rc["n_rapid_samples"]     = int(n_rapid)

        for h in self.config.horizons:
            if h not in y_true_dict:
                continue
            yt  = np.array(y_true_dict[h])
            yp  = np.array(y_pred_dict[h])
            n_use = min(len(yt), len(rapid_mask.dropna()))
            mask_np = rapid_mask.dropna().values[:n_use]

            # MAE trong điều kiện bình thường vs biến đổi nhanh
            mae_normal = float(np.abs(yt[:n_use][~mask_np] - yp[:n_use][~mask_np]).mean()) \
                         if (~mask_np).sum() > 0 else float("nan")
            mae_rapid  = float(np.abs(yt[:n_use][mask_np]  - yp[:n_use][mask_np]).mean()) \
                         if mask_np.sum() > 0  else float("nan")

            rc[f"mae_normal_{h}"] = round(mae_normal, 4)
            rc[f"mae_rapid_{h}"]  = round(mae_rapid,  4)

            if not np.isnan(mae_rapid) and not np.isnan(mae_normal) and mae_normal > 0:
                ratio = mae_rapid / mae_normal
                logger.info(
                    "+%dm: MAE_rapid/MAE_normal = %.2fx (rapid=%.4f, normal=%.4f)",
                    h, ratio, mae_rapid, mae_normal
                )
        return rc

    def _compute_durbin_watson(self) -> Dict[int, float]:
        """
        Durbin-Watson test trên phần dư:
        DW ≈ 2 → không tự tương quan
        DW < 1 → tự tương quan dương (mô hình chưa nắm hết xu hướng)
        DW > 3 → tự tương quan âm
        """
        dw_results = {}
        for h, res in self._residuals.items():
            dw = float(durbin_watson(res))
            dw_results[h] = dw
            interpretation = (
                "OK (gần 2)"   if 1.5 < dw < 2.5
                else "CANH BAO: tu tuong quan duong" if dw < 1.5
                else "CANH BAO: tu tuong quan am"
            )
            logger.info(
                "+%dm Durbin-Watson = %.4f → %s", h, dw, interpretation
            )
        return dw_results

    def _print_summary(self) -> None:
        """In bảng tóm tắt ngắn gọn ra console."""
        print("\n" + "=" * 65)
        print("  ERROR ANALYSIS SUMMARY")
        print("=" * 65)
        for h in sorted(self._residuals.keys()):
            s = self._report["residual_stats"].get(h, {})
            dw = self._report.get("durbin_watson", {}).get(h, float("nan"))
            print(
                f"  +{h}min: MAE={s.get('mae','?'):>7} °C | "
                f"RMSE={s.get('rmse','?'):>7} °C | "
                f"R²={s.get('r2','?'):>6} | "
                f"DW={dw:>5.3f} | "
                f"skew={s.get('skewness','?'):>6}"
            )

        if "rapid_change" in self._report:
            rc = self._report["rapid_change"]
            print(f"\n  Rapid change (|ΔT|>{rc.get('threshold_C_per_min',0)}°C/min): "
                  f"{rc.get('pct_rapid_change', 0):.1f}% mẫu")
        print()


# ---------------------------------------------------------------------------
# Helper: tạo y_pred từ các model joblib đã lưu (dùng kết nối với ML-03)
# ---------------------------------------------------------------------------
def predict_from_saved_model(
    model_name: str,
    horizon:    int,
    X_test:     pd.DataFrame,
    model_dir:  str,
) -> np.ndarray:
    """
    Load model .joblib đã lưu từ ML-03 và predict trên X_test.

    Args:
        model_name: 'Ridge', 'Lasso', 'RandomForest', hoặc 'XGBoost'.
        horizon:    10, 30 hoặc 60.
        X_test:     DataFrame test features.
        model_dir:  Đường dẫn thư mục chứa .joblib.

    Returns:
        y_pred: numpy array dự báo.
    """
    import joblib
    path = Path(model_dir) / f"{model_name}_h{horizon}min.joblib"
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy model: {path}")
    model = joblib.load(path)
    return model.predict(X_test)


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
    from ml.models_benchmark import TemperatureBenchmark, BenchmarkConfig

    print("=" * 65)
    print("  ML-05: Error Analysis & Diagnostics — Quick Test")
    print("=" * 65)

    # 1. Chuẩn bị dữ liệu 14 ngày
    print("\n[1/4] Tạo & tiền xử lý dữ liệu...")
    df_raw   = generate_sample_iot_data(n_minutes=60 * 24 * 14, seed=42)
    prep     = TimeSeriesPreprocessor(PreprocessingConfig())
    df_clean = prep.fit_transform(df_raw)

    feat_cfg = FeatureConfig(
        lag_steps=[1,2,3,6,10,30], delta_steps=[1,5,10],
        rolling_windows=[6,10,30,60], forecast_horizons=[10,30,60]
    )
    engineer    = TemperatureFeatureEngineer(feat_cfg)
    df_features = engineer.fit_transform(df_clean)
    X, y_dict   = engineer.get_Xy(df_features)
    X_train, X_val, X_test, _, _, _ = engineer.train_val_test_split(X, y_dict["y_10"])

    # 2. Lấy predictions từ model tốt nhất (Ridge)
    print("[2/4] Lấy predictions từ Ridge model...")
    ml_cfg    = BenchmarkConfig(rf_n_estimators=50, xgb_n_estimators=80,
                                horizons=[10,30,60], save_models=False)
    benchmark = TemperatureBenchmark(ml_cfg)
    benchmark.run(X_train, X_val, X_test, y_dict)

    # Collect y_true & y_pred cho từng horizon
    y_true_dict = {}
    y_pred_dict = {}
    for h in [10, 30, 60]:
        best_model, _ = benchmark.get_best_model(h)
        y_true_dict[h] = y_dict[f"y_{h}"].loc[X_test.index].values
        y_pred_dict[h] = best_model.predict(X_test)

    # 3. Phân tích sai số
    print("[3/4] Chạy Error Analysis...")
    analyzer = ErrorAnalyzer(ErrorAnalysisConfig())
    report   = analyzer.run(
        y_true_dict, y_pred_dict,
        df_test=df_clean.loc[X_test.index]    # DataFrame test có 'temperature'
    )

    # 4. Vẽ & xuất
    print("[4/4] Vẽ dashboard & xuất JSON...")
    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)

    analyzer.plot_full_dashboard(
        save_path=str(out_dir / "error_dashboard.png")
    )
    analyzer.export_report_json(str(out_dir / "error_report.json"))

    print(f"\n✅ ML-05 Error Analysis OK!")
    print(f"   - Dashboard: {out_dir / 'error_dashboard.png'}")
    print(f"   - JSON:      {out_dir / 'error_report.json'}")
