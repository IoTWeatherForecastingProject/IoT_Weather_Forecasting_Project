"""
Ghép chuỗi IoT với chuỗi tham chiếu theo thời gian (SA-04).

Chỉ dùng numpy/pandas, không phụ thuộc crawler hay requests, để Backend
import được khi chỉ cài dependencies của Backend.
"""

import numpy as np
import pandas as pd

VARIABLES = ("temperature", "humidity", "pressure")


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Chuẩn hóa timestamp UTC, ép kiểu số, sắp xếp; giữ đúng các cột cần."""
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for var in VARIABLES:
        df[var] = pd.to_numeric(df[var], errors="coerce") if var in df else np.nan
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    return df[["timestamp", *VARIABLES]].reset_index(drop=True)


def align_series(iot_df: pd.DataFrame, ref_df: pd.DataFrame,
                 tolerance_minutes: float = 5, min_samples: int = 3) -> pd.DataFrame:
    """
    Ghép mỗi mốc tham chiếu t với trung bình IoT trong [t - tol, t + tol].

    Tính riêng từng biến (bỏ NaN của biến đó); biến có < min_samples mẫu thì NaN.
    Dùng searchsorted + tổng tích lũy: O((N_iot + N_ref) log N_iot), không lặp
    Python trên từng mẫu IoT.
    """
    iot = _normalize_frame(iot_df)
    ref = _normalize_frame(ref_df)
    columns = ["timestamp", "n_iot"] + [
        f"{side}_{var}" for var in VARIABLES for side in ("iot", "ref")
    ]
    if iot.empty or ref.empty:
        return pd.DataFrame(columns=columns)

    tol = np.int64(pd.Timedelta(minutes=tolerance_minutes).value)
    ref_ns = ref["timestamp"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    out = {"timestamp": ref["timestamp"]}

    all_ns = iot["timestamp"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    lo = np.searchsorted(all_ns, ref_ns - tol, side="left")
    hi = np.searchsorted(all_ns, ref_ns + tol, side="right")
    out["n_iot"] = hi - lo

    for var in VARIABLES:
        valid = iot[var].notna().to_numpy()
        times = all_ns[valid]
        values = iot[var].to_numpy(dtype=float)[valid]
        lo = np.searchsorted(times, ref_ns - tol, side="left")
        hi = np.searchsorted(times, ref_ns + tol, side="right")
        count = hi - lo
        cumsum = np.concatenate(([0.0], np.cumsum(values)))
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = (cumsum[hi] - cumsum[lo]) / count
        mean[count < min_samples] = np.nan
        out[f"iot_{var}"] = mean
        out[f"ref_{var}"] = ref[var].to_numpy(dtype=float)

    aligned = pd.DataFrame(out)[columns]
    pair_ok = np.zeros(len(aligned), dtype=bool)
    for var in VARIABLES:
        pair_ok |= (aligned[f"iot_{var}"].notna()
                    & aligned[f"ref_{var}"].notna()).to_numpy()
    return aligned[pair_ok].reset_index(drop=True)
