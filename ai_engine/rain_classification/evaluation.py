"""
==============================================================================
MODULE 4: CHIA DỮ LIỆU THEO THỜI GIAN, BASELINE & METRIC CHO MÔ HÌNH MƯA
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-01, SA-02 (TASK.md)
==============================================================================
"""

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Chia train / calibration / test theo thời gian
# ------------------------------------------------------------------------------

def chronological_boundaries(times: pd.DatetimeIndex, ratios: Sequence[float] = (0.70, 0.15, 0.15)
                             ) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """
    Trả về (t_cal_start, t_test_start) cắt chuỗi `times` (đã sắp xếp) theo tỷ lệ số mẫu.
    Ranh giới dùng chung cho mọi horizon để các horizon được đánh giá trên cùng giai đoạn.
    """
    if len(ratios) != 3 or not np.isclose(sum(ratios), 1.0) or min(ratios) <= 0:
        raise ValueError("ratios phai gom 3 phan duong co tong bang 1")
    times = pd.DatetimeIndex(times).sort_values()
    if len(times) < 3:
        raise ValueError("Can it nhat 3 moc thoi gian de chia train/calibration/test")
    i_cal = int(len(times) * ratios[0])
    i_test = int(len(times) * (ratios[0] + ratios[1]))
    i_test = max(i_test, i_cal + 1)
    return times[i_cal], times[min(i_test, len(times) - 1)]


def assign_split(times: pd.DatetimeIndex, t_cal_start: pd.Timestamp, t_test_start: pd.Timestamp,
                 horizon_minutes: int) -> pd.Series:
    """
    Gán 'train' / 'calibration' / 'test' / 'purged' cho từng mốc t.

    Nhãn tại t phụ thuộc khoảng (t, t + h], nên mẫu cuối mỗi tập có t + h >= ranh giới kế tiếp
    bị loại ('purged') để cửa sổ nhãn không lấn sang tập sau.
    """
    times = pd.DatetimeIndex(times)
    label_end = times + pd.Timedelta(minutes=horizon_minutes)
    split = np.full(len(times), "purged", dtype=object)
    split[label_end < t_cal_start] = "train"
    split[(times >= t_cal_start) & (label_end < t_test_start)] = "calibration"
    split[times >= t_test_start] = "test"
    return pd.Series(split, index=times, name="split")


def set_summary(times: pd.DatetimeIndex, y: np.ndarray) -> Dict[str, Any]:
    y = np.asarray(y)
    n = int(len(y))
    return {
        "n_samples": n,
        "n_rain": int(y.sum()) if n else 0,
        "rain_rate": float(y.mean()) if n else None,
        "start": times.min().isoformat() if n else None,
        "end": times.max().isoformat() if n else None,
    }


# ------------------------------------------------------------------------------
# Metric
# ------------------------------------------------------------------------------

def probabilistic_metrics(y: np.ndarray, p: np.ndarray) -> Dict[str, Any]:
    """
    Brier luôn tính được khi có mẫu. ROC-AUC và PR-AUC chỉ tính khi đủ 2 lớp.
    PR-AUC = average precision (sklearn.metrics.average_precision_score): tổng có trọng số
    precision theo bước tăng recall, không nội suy hình thang.
    """
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    out: Dict[str, Any] = {"n": int(len(y)), "brier": None, "roc_auc": None, "pr_auc": None, "note": None}
    if len(y) == 0:
        out["note"] = "khong co mau"
        return out
    out["brier"] = float(brier_score_loss(y, p))
    if len(np.unique(y)) < 2:
        out["note"] = "chi co 1 lop trong tap danh gia: khong tinh ROC-AUC/PR-AUC"
        return out
    out["roc_auc"] = float(roc_auc_score(y, p))
    out["pr_auc"] = float(average_precision_score(y, p))
    return out


def brier_skill_score(brier: Optional[float], brier_ref: Optional[float]) -> Dict[str, Any]:
    """BSS = 1 - BS / BS_ref. Không xác định khi BS_ref = 0 (baseline đã hoàn hảo) hoặc thiếu."""
    if brier is None or brier_ref is None:
        return {"value": None, "note": "thieu Brier score"}
    if brier_ref == 0:
        return {"value": None, "note": "Brier baseline = 0: BSS khong xac dinh"}
    return {"value": float(1.0 - brier / brier_ref), "note": None}


def reliability_table(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> List[Dict[str, Any]]:
    """
    Bảng reliability (bin đều trên [0, 1]) kèm số mẫu từng bin.
    Bin rỗng vẫn được giữ (count = 0) để người đọc thấy vùng xác suất không có dữ liệu.
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_ids = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        mask = bin_ids == b
        count = int(mask.sum())
        rows.append({
            "bin_lower": float(edges[b]),
            "bin_upper": float(edges[b + 1]),
            "count": count,
            "mean_predicted": float(p[mask].mean()) if count else None,
            "observed_frequency": float(y[mask].mean()) if count else None,
        })
    return rows


def plot_reliability(tables: Dict[str, List[Dict[str, Any]]], title: str, out_path) -> bool:
    """Vẽ reliability diagram (trên) + histogram số mẫu theo bin (dưới). Trả False nếu thiếu matplotlib."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("[RAIN EVAL] Chua cai matplotlib, bo qua ve reliability diagram")
        return False

    fig, (ax, ax_hist) = plt.subplots(2, 1, figsize=(6, 7), sharex=True,
                                      gridspec_kw={"height_ratios": [3, 1]})
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", label="Hieu chuan ly tuong")
    n_series = max(len(tables), 1)
    width = 0.1 / n_series
    for i, (name, rows) in enumerate(tables.items()):
        pts = [(r["mean_predicted"], r["observed_frequency"]) for r in rows if r["count"]]
        if pts:
            xs, ys = zip(*pts)
            ax.plot(xs, ys, marker="o", label=name)
        centers = [(r["bin_lower"] + r["bin_upper"]) / 2 for r in rows]
        ax_hist.bar([c - 0.05 + width * (i + 0.5) for c in centers], [r["count"] for r in rows],
                    width=width, label=name)
    ax.set_ylabel("Tan suat mua quan sat")
    ax.set_title(title)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left", fontsize=8)
    ax_hist.set_xlabel("Xac suat du bao")
    ax_hist.set_ylabel("So mau / bin")
    ax_hist.set_yscale("symlog")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return True
