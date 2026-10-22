"""
==============================================================================
MODULE 4: HUẤN LUYỆN VÀ HIỆU CHUẨN MÔ HÌNH XÁC SUẤT MƯA
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-01, SA-02 (TASK.md)
==============================================================================

Quy trình cho từng horizon h (10, 30, 60 phút):
1. Lưới thời gian nhân quả + feature chỉ dùng dữ liệu <= t (rain_classification/features.py).
2. Nhãn: có mưa trong (t, t + h]; thiếu dữ liệu tương lai -> loại mẫu.
3. Chia train / calibration / test 70/15/15 theo thời gian, loại mẫu ở ranh giới
   có cửa sổ nhãn lấn sang tập kế tiếp.
4. Fit RandomForest trên train; fit calibrator (sigmoid / isotonic) trên calibration.
5. Đánh giá trên test: Brier, ROC-AUC, PR-AUC, baseline climatology & persistence,
   Brier Skill Score, reliability diagram.

Chạy:  python rain_classification/train_rain.py [--data PATH] [--calibration sigmoid|isotonic]
"""

import argparse
import json
import logging
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from rain_classification.calibration import CALIBRATORS, CalibratedRainModel
from rain_classification.evaluation import (
    assign_split,
    brier_skill_score,
    chronological_boundaries,
    plot_reliability,
    probabilistic_metrics,
    reliability_table,
    set_summary,
)
from rain_classification.features import build_rain_dataset, required_history_minutes

logger = logging.getLogger(__name__)

ARTIFACT_VERSION = 2
DEFAULT_DATA_PATH = BASE_DIR / "data" / "sample" / "sample_weather_data.csv"
DEFAULT_MODEL_PATH = BASE_DIR / "saved_models" / "rain_classifier_models.joblib"
DEFAULT_REPORT_DIR = BASE_DIR / "reports" / "rain_classification"
# Khoảng dự phòng khuyến nghị cho backend khi truy vấn lịch sử (mất mẫu, lệch bin resample)
HISTORY_BUFFER_MINUTES = 15


@dataclass
class RainTrainConfig:
    horizons: Tuple[int, ...] = (10, 30, 60)
    freq: str = "1min"
    ffill_limit: int = 2
    include_rain_state: bool = True
    split_ratios: Tuple[float, float, float] = (0.70, 0.15, 0.15)
    calibration_method: str = "sigmoid"
    # Mặc định KHÔNG triển khai xác suất chưa hiệu chuẩn cho inference
    allow_uncalibrated: bool = False
    min_class_count_train: int = 5
    min_class_count_calibration: int = 5
    min_samples_isotonic: int = 100
    reliability_bins: int = 10
    # Dưới ngưỡng này kết quả chỉ mang tính kiểm tra kỹ thuật
    min_days_for_quality_claim: float = 7.0
    rf_params: Dict[str, Any] = field(default_factory=lambda: {
        "n_estimators": 200,
        "max_depth": 5,
        "min_samples_leaf": 5,
        "class_weight": "balanced",
        "random_state": 42,
        "n_jobs": -1,
    })

    def __post_init__(self) -> None:
        if self.calibration_method not in CALIBRATORS:
            raise ValueError(f"calibration_method phai thuoc {sorted(CALIBRATORS)}")


def _library_versions() -> Dict[str, str]:
    return {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "joblib": joblib.__version__,
    }


def _select_device(raw_df: pd.DataFrame, device_id: Optional[str]) -> pd.DataFrame:
    if "device_id" not in raw_df.columns:
        return raw_df
    if device_id is not None:
        subset = raw_df[raw_df["device_id"] == device_id]
        if subset.empty:
            raise ValueError(f"Khong co du lieu cho device_id={device_id}")
        return subset
    devices = raw_df["device_id"].dropna().unique()
    if len(devices) > 1:
        raise ValueError(f"Du lieu co nhieu tram {list(devices)}; hay chon device_id de khong tron chuoi thoi gian")
    return raw_df


def _class_counts(y: np.ndarray) -> Tuple[int, int]:
    y = np.asarray(y, dtype=int)
    return int((y == 0).sum()), int((y == 1).sum())


def _train_one_horizon(h: int, X: pd.DataFrame, y: pd.Series, persistence: pd.Series,
                       split: pd.Series, feature_cols, cfg: RainTrainConfig,
                       report_dir: Optional[Path]) -> Tuple[Optional[CalibratedRainModel], Dict[str, Any]]:
    res: Dict[str, Any] = {"status": None, "reason": None}
    masks = {name: (split == name).to_numpy() for name in ("train", "calibration", "test")}
    res["sets"] = {name: set_summary(X.index[m], y.to_numpy()[m]) for name, m in masks.items()}
    res["sets"]["purged_at_boundaries"] = int((split == "purged").sum())

    y_tr = y[masks["train"]].to_numpy(dtype=int)
    n_neg, n_pos = _class_counts(y_tr)
    if min(n_neg, n_pos) < cfg.min_class_count_train:
        res["status"] = "skipped_insufficient_train"
        res["reason"] = (f"Tap train co {n_pos} mau mua / {n_neg} mau khong mua; "
                         f"can toi thieu {cfg.min_class_count_train} moi lop")
        logger.warning("[RAIN TRAIN] +%dm: %s", h, res["reason"])
        return None, res

    clf = RandomForestClassifier(**cfg.rf_params)
    clf.fit(X[masks["train"]], y_tr)
    model = CalibratedRainModel(clf, feature_cols, h)

    # --- Calibration: chỉ dùng tập calibration ---
    X_cal, y_cal = X[masks["calibration"]], y[masks["calibration"]].to_numpy(dtype=int)
    p_cal_raw = model.predict_proba_raw(X_cal) if len(y_cal) else np.array([])
    c_neg, c_pos = _class_counts(y_cal)
    calibrators: Dict[str, Any] = {}
    calib_info: Dict[str, Any] = {}
    for method, cls in CALIBRATORS.items():
        if min(c_neg, c_pos) < cfg.min_class_count_calibration:
            calib_info[method] = {"fitted": False, "reason": (
                f"Tap calibration co {c_pos} mau mua / {c_neg} mau khong mua; "
                f"can toi thieu {cfg.min_class_count_calibration} moi lop")}
            continue
        if method == "isotonic" and len(y_cal) < cfg.min_samples_isotonic:
            calib_info[method] = {"fitted": False, "reason": (
                f"Isotonic can >= {cfg.min_samples_isotonic} mau calibration, hien co {len(y_cal)}")}
            continue
        calibrators[method] = cls().fit(p_cal_raw, y_cal)
        calib_info[method] = {"fitted": True, "reason": None}

    chosen = cfg.calibration_method
    if chosen in calibrators:
        model.calibrator = calibrators[chosen]
        res["status"] = "deployed"
    elif cfg.allow_uncalibrated:
        res["status"] = "deployed_uncalibrated"
        res["reason"] = f"Khong fit duoc calibrator '{chosen}': {calib_info[chosen]['reason']}"
        logger.warning("[RAIN TRAIN] +%dm: trien khai xac suat CHUA hieu chuan (--allow-uncalibrated)", h)
    else:
        res["status"] = "not_deployed_calibration_unavailable"
        res["reason"] = f"Khong fit duoc calibrator '{chosen}': {calib_info[chosen]['reason']}"
        logger.warning("[RAIN TRAIN] +%dm: %s -> khong dua vao artifact", h, res["reason"])
    res["calibration"] = {"requested_method": chosen, "deployed_method": model.calibration_method,
                          "methods": calib_info}

    # --- Đánh giá trên test (không dùng để chọn phương pháp / ngưỡng) ---
    X_te, y_te = X[masks["test"]], y[masks["test"]].to_numpy(dtype=int)
    p_train_rate = float(y_tr.mean())
    preds: Dict[str, np.ndarray] = {}
    if len(y_te):
        p_raw = model.predict_proba_raw(X_te)
        preds = {
            "climatology": np.full(len(y_te), p_train_rate),
            "persistence": persistence[masks["test"]].to_numpy(dtype=float),
            "uncalibrated": p_raw,
        }
        for method, cal in calibrators.items():
            preds[method] = np.clip(cal.predict(p_raw), 0.0, 1.0)

    metrics = {name: probabilistic_metrics(y_te, p) for name, p in preds.items()}
    res["test_metrics"] = metrics
    res["baselines"] = {
        "climatology": f"P = ty le mua tap train cho horizon nay = {p_train_rate:.4f}",
        "persistence": "P = 1 neu rain_detected tai t = 1, nguoc lai 0 (xac suat nhi phan)",
    }
    res["brier_skill"] = {
        ref: {name: brier_skill_score(m["brier"], metrics[ref]["brier"])
              for name, m in metrics.items() if name not in ("climatology", "persistence")}
        for ref in ("climatology", "persistence") if ref in metrics
    }
    if len(y_te) and len(np.unique(y_te)) < 2:
        for scores in res["brier_skill"].values():
            for s in scores.values():
                if s["value"] is not None:
                    s["note"] = "test chi co 1 lop: BSS khong phan anh kha nang phat hien mua"

    model_preds = {k: v for k, v in preds.items() if k not in ("climatology", "persistence")}
    res["reliability_test"] = {name: reliability_table(y_te, p, cfg.reliability_bins)
                               for name, p in model_preds.items()}
    res["reliability_plot"] = None
    if report_dir is not None and model_preds:
        out = report_dir / f"reliability_rain_{h}m.png"
        title = f"Reliability +{h}m (test, n={len(y_te)}, so mau mua={int(y_te.sum())})"
        if plot_reliability(res["reliability_test"], title, out):
            res["reliability_plot"] = out.name

    deployable = res["status"] in ("deployed", "deployed_uncalibrated")
    return (model if deployable else None), res


def train_rain_models(raw_df: pd.DataFrame, cfg: Optional[RainTrainConfig] = None,
                      device_id: Optional[str] = None, report_dir: Optional[Path] = None,
                      data_source: str = "dataframe") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Huấn luyện + hiệu chuẩn + đánh giá. Trả về (artifact payload, báo cáo đánh giá)."""
    cfg = cfg or RainTrainConfig()
    raw_df = _select_device(raw_df, device_id)
    if "rain_detected" not in raw_df.columns:
        raise ValueError("Du lieu thieu cot rain_detected de tao nhan")

    ds = build_rain_dataset(raw_df, list(cfg.horizons), freq=cfg.freq, ffill_limit=cfg.ffill_limit,
                            include_rain_state=cfg.include_rain_state)
    feat_df, feature_cols, labels = ds["features"], ds["feature_cols"], ds["labels"]
    if not feature_cols:
        raise ValueError("Khong co feature nao kha dung")

    valid = feat_df[feature_cols].notna().all(axis=1) & feat_df["rain_detected"].notna()
    valid_times = feat_df.index[valid]
    if len(valid_times) < 3:
        raise ValueError(f"Chi co {len(valid_times)} moc du lich su feature; khong du de huan luyen")
    t_cal, t_test = chronological_boundaries(valid_times, cfg.split_ratios)

    ts = pd.to_datetime(raw_df["timestamp"], utc=True, errors="coerce").dropna()
    span_days = (ts.max() - ts.min()) / pd.Timedelta(days=1)
    technical_only = bool(span_days < cfg.min_days_for_quality_claim)

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "source": data_source,
            "n_raw_rows": int(len(raw_df)),
            "start": ts.min().isoformat(),
            "end": ts.max().isoformat(),
            "span_days": round(float(span_days), 3),
            "n_grid_rows": int(len(feat_df)),
            "n_rows_with_full_features": int(valid.sum()),
            "technical_check_only": technical_only,
            "note": (f"Du lieu chi {span_days:.2f} ngay (< {cfg.min_days_for_quality_claim} ngay): "
                     "ket qua chi phuc vu kiem tra ky thuat, CHUA chung minh chat luong du bao")
            if technical_only else None,
        },
        "config": asdict(cfg),
        "feature_cols": feature_cols,
        "split_boundaries": {"calibration_start": t_cal.isoformat(), "test_start": t_test.isoformat()},
        "horizons": {},
    }

    models: Dict[str, CalibratedRainModel] = {}
    calibration_meta: Dict[str, Any] = {}
    persistence_all = feat_df["rain_detected"].clip(0, 1)
    for h in cfg.horizons:
        y_all = labels[h]
        mask = valid & y_all.notna()
        split = assign_split(feat_df.index[mask], t_cal, t_test, h)
        model, res = _train_one_horizon(
            h, feat_df.loc[mask, feature_cols], y_all[mask].astype(int), persistence_all[mask],
            split, feature_cols, cfg, report_dir)
        report["horizons"][str(h)] = res
        calibration_meta[f"rain_{h}m"] = {"status": res["status"], "reason": res["reason"],
                                          "method": model.calibration_method if model else None}
        if model is not None:
            models[f"rain_{h}m"] = model

    min_hist = required_history_minutes(cfg.freq)
    payload = {
        "artifact_version": ARTIFACT_VERSION,
        # --- Các khóa tương thích với inference/unified_forecast.py hiện tại ---
        "models": models,
        "feature_cols": feature_cols,
        "horizons": list(cfg.horizons),
        # --- Metadata bổ sung ---
        "deployed_horizons": [int(k.split("_")[1][:-1]) for k in models],
        "target_definition": "1 neu co rain_detected=1 trong (t, t + h], khong tinh t",
        "freq": cfg.freq,
        "ffill_limit_steps": cfg.ffill_limit,
        "min_history_minutes": min_hist,
        "recommended_history_minutes": min_hist + HISTORY_BUFFER_MINUTES,
        "input_columns": ["timestamp", "temperature", "humidity", "pressure", "rain_detected"]
                         + (["rain_raw"] if "rain_raw" in feature_cols else []),
        "calibration": calibration_meta,
        "training_config": asdict(cfg),
        "data_summary": report["data"],
        "split_boundaries": report["split_boundaries"],
        "library_versions": _library_versions(),
        "created_at": report["generated_at"],
    }
    return payload, report


def save_artifact(payload: Dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, path)


def load_artifact(path: Path) -> Dict[str, Any]:
    payload = joblib.load(path)
    for key in ("models", "feature_cols", "horizons"):
        if key not in payload:
            raise ValueError(f"Artifact mo hinh mua thieu khoa '{key}'")
    versions = payload.get("library_versions", {})
    if versions.get("scikit-learn") and versions["scikit-learn"] != sklearn.__version__:
        logger.warning("[RAIN MODEL] Artifact train voi scikit-learn %s, dang chay %s",
                       versions["scikit-learn"], sklearn.__version__)
    return payload


def _log_summary(report: Dict[str, Any]) -> None:
    logger.info("=" * 96)
    logger.info("%-8s %-36s %-14s %-9s %-9s %-9s %-9s", "Horizon", "Trang thai", "Model", "Brier",
                "ROC-AUC", "PR-AUC", "BSS(clim)")
    logger.info("-" * 96)
    fmt = lambda v: f"{v:.4f}" if isinstance(v, float) else "n/a"
    for h, res in report["horizons"].items():
        metrics = res.get("test_metrics") or {}
        if not metrics:
            logger.info("+%-7s %-36s %s", f"{h}m", res["status"], res.get("reason") or "")
            continue
        bss = res.get("brier_skill", {}).get("climatology", {})
        for name, m in metrics.items():
            logger.info("+%-7s %-36s %-14s %-9s %-9s %-9s %-9s", f"{h}m", res["status"], name, fmt(m["brier"]),
                        fmt(m["roc_auc"]), fmt(m["pr_auc"]), fmt(bss.get(name, {}).get("value")))
        test = res["sets"]["test"]
        logger.info("         test: n=%s, so mau mua=%s. %s", test["n_samples"], test["n_rain"],
                    next((m["note"] for m in metrics.values() if m["note"]), ""))
    logger.info("=" * 96)
    if report["data"]["note"]:
        logger.warning("[RAIN TRAIN] %s", report["data"]["note"])


def run(data_path: Path = DEFAULT_DATA_PATH, model_path: Path = DEFAULT_MODEL_PATH,
        report_dir: Path = DEFAULT_REPORT_DIR, cfg: Optional[RainTrainConfig] = None,
        device_id: Optional[str] = None) -> Dict[str, Any]:
    logger.info("[RAIN TRAIN] Nap du lieu: %s", data_path)
    raw_df = pd.read_csv(data_path)
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    payload, report = train_rain_models(raw_df, cfg, device_id=device_id, report_dir=report_dir,
                                        data_source=str(data_path))
    save_artifact(payload, model_path)
    report["artifact_path"] = str(model_path)
    report["deployed_horizons"] = payload["deployed_horizons"]
    with open(report_dir / "evaluation_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    _log_summary(report)
    logger.info("[RAIN TRAIN] Artifact: %s (horizon trien khai: %s)", model_path, payload["deployed_horizons"])
    logger.info("[RAIN TRAIN] Bao cao danh gia: %s", report_dir / "evaluation_report.json")
    return report


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Huan luyen & hieu chuan mo hinh xac suat mua (SA-01/SA-02)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--device-id", default=None)
    parser.add_argument("--calibration", choices=sorted(CALIBRATORS), default="sigmoid")
    parser.add_argument("--exclude-rain-state", action="store_true",
                        help="Bo rain_detected/rain_raw hien tai khoi feature (thi nghiem ablation)")
    parser.add_argument("--allow-uncalibrated", action="store_true",
                        help="Van dua model chua hieu chuan vao artifact (chi dung de demo ky thuat)")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    cfg = RainTrainConfig(calibration_method=args.calibration,
                          include_rain_state=not args.exclude_rain_state,
                          allow_uncalibrated=args.allow_uncalibrated)
    run(args.data, args.model_out, args.report_dir, cfg, device_id=args.device_id)


if __name__ == "__main__":
    main()
