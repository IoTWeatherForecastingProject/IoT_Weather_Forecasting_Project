"""
==============================================================================
MODULE 4: PHÂN TÍCH SAI SỐ CẢM BIẾN IoT SO VỚI DỮ LIỆU THAM CHIẾU
Phụ trách: TV3 (AI + Analytics + Frontend Engineer)
Các Task: SA-04 (TASK.md)
==============================================================================

Quy trình:
1. Đọc chuỗi IoT (weather_measurements / CSV) và chuỗi tham chiếu
   (reference_weather / CSV do crawler.py thu thập).
2. Ghép theo thời gian: với mỗi mốc tham chiếu t, lấy trung bình mẫu IoT trong
   khoảng đóng [t - tol, t + tol], riêng cho từng biến.
3. Tính MBE, MAE, RMSE, độ lệch chuẩn sai số, Pearson r, hồi quy hiệu chỉnh
   ref ≈ a·iot + b và MBE theo giờ trong ngày (giờ địa phương).
4. Xuất JSON + CSV cặp đã ghép + biểu đồ cho báo cáo.

Sai số luôn được định nghĩa là IoT - tham chiếu.
"""

import argparse
import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from openweather_benchmark.alignment import VARIABLES, _normalize_frame, align_series
from openweather_benchmark.crawler import (
    describe_db_error,
    get_database_url,
    normalize_database_url,
)

logger = logging.getLogger(__name__)

UNITS = {"temperature": "°C", "humidity": "%", "pressure": "hPa"}
LOCAL_TZ = "Asia/Ho_Chi_Minh"
DEFAULT_OUT_ROOT = Path(__file__).resolve().parents[1] / "reports" / "benchmark"
NOTES = [
    "Sai số được tính là IoT - tham chiếu.",
    ("Áp suất IoT là áp suất tại trạm (BME280) và được so với surface_pressure; "
     "độ lệch cố định có thể do chênh lệch độ cao."),
    ("Open-Meteo là dữ liệu mô hình (reanalysis/forecast) độ phân giải km, "
     "không phải phép đo tại chỗ."),
]


# --- Đọc dữ liệu ----------------------------------------------------------------

def _filter_time(df: pd.DataFrame, start, end) -> pd.DataFrame:
    if start is not None:
        df = df[df["timestamp"] >= start]
    if end is not None:
        df = df[df["timestamp"] <= end]
    return df.reset_index(drop=True)


def _read_sql(database_url: str, query: str, params: dict) -> pd.DataFrame:
    from sqlalchemy import create_engine, text

    engine = create_engine(normalize_database_url(database_url),
                           connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            return pd.read_sql(text(query), connection, params=params)
    finally:
        engine.dispose()


def load_iot(csv_path=None, database_url=None, device_id="station01",
             start=None, end=None) -> pd.DataFrame:
    """Đọc chuỗi IoT của một trạm từ CSV hoặc bảng weather_measurements."""
    if csv_path is not None:
        df = pd.read_csv(csv_path)
        if "device_id" in df:
            df = df[df["device_id"].astype(str) == str(device_id)]
    else:
        df = _read_sql(database_url, (
            "SELECT timestamp, temperature, humidity, pressure "
            "FROM weather_measurements WHERE device_id = :device_id "
            "AND (CAST(:start AS timestamptz) IS NULL OR timestamp >= :start) "
            "AND (CAST(:end AS timestamptz) IS NULL OR timestamp <= :end) "
            "ORDER BY timestamp"
        ), {"device_id": device_id, "start": start, "end": end})
    return _filter_time(_normalize_frame(df), start, end)


def load_reference(csv_path=None, database_url=None, ref_source="open-meteo",
                   start=None, end=None) -> pd.DataFrame:
    """Đọc chuỗi tham chiếu của một nguồn từ CSV hoặc bảng reference_weather."""
    if csv_path is not None:
        df = pd.read_csv(csv_path)
        if "source" in df:
            df = df[df["source"].astype(str) == ref_source]
    else:
        df = _read_sql(database_url, (
            "SELECT timestamp, temperature, humidity, pressure "
            "FROM reference_weather WHERE source = :source "
            "AND (CAST(:start AS timestamptz) IS NULL OR timestamp >= :start) "
            "AND (CAST(:end AS timestamptz) IS NULL OR timestamp <= :end) "
            "ORDER BY timestamp"
        ), {"source": ref_source, "start": start, "end": end})
    return _filter_time(_normalize_frame(df), start, end)


# --- Ghép chuỗi & chỉ số ----------------------------------------------------------

def _pairs(aligned: pd.DataFrame, var: str) -> tuple[np.ndarray, np.ndarray]:
    sub = aligned[[f"iot_{var}", f"ref_{var}"]].dropna()
    return sub[f"iot_{var}"].to_numpy(float), sub[f"ref_{var}"].to_numpy(float)


def compute_metrics(aligned: pd.DataFrame) -> dict:
    """Chỉ số sai số cho từng biến; biến không có cặp nào thì bỏ qua."""
    metrics = {}
    for var in VARIABLES:
        if f"iot_{var}" not in aligned:
            continue
        iot, ref = _pairs(aligned, var)
        n = len(iot)
        if n == 0:
            continue
        err = iot - ref
        item = {
            "unit": UNITS[var],
            "n": int(n),
            "mbe": float(err.mean()),
            "mae": float(np.abs(err).mean()),
            "rmse": float(np.sqrt((err ** 2).mean())),
            "std_error": float(err.std(ddof=1)) if n >= 2 else None,
            "pearson_r": None,
            "linear_fit": None,
            "mbe_corrected_check": None,
        }
        if n >= 3 and iot.std() > 0 and ref.std() > 0:
            item["pearson_r"] = float(np.corrcoef(iot, ref)[0, 1])
        if n >= 3 and iot.std() > 0:
            slope, intercept = np.polyfit(iot, ref, 1)
            item["linear_fit"] = {"slope": float(slope),
                                  "intercept": float(intercept)}
            item["mbe_corrected_check"] = float(
                (slope * iot + intercept - ref).mean())
        metrics[var] = item
    return metrics


def diurnal_bias(aligned: pd.DataFrame, tz: str = LOCAL_TZ) -> pd.DataFrame:
    """MBE theo giờ trong ngày (giờ địa phương), đủ 24 giờ cho mỗi biến."""
    rows = []
    hours = (pd.to_datetime(aligned["timestamp"], utc=True).dt.tz_convert(tz).dt.hour
             if len(aligned) else pd.Series(dtype=int))
    for var in VARIABLES:
        err = aligned.get(f"iot_{var}", pd.Series(dtype=float)) \
            - aligned.get(f"ref_{var}", pd.Series(dtype=float))
        frame = pd.DataFrame({"hour": hours, "err": err}).dropna()
        grouped = frame.groupby("hour")["err"].agg(["count", "mean"])
        for hour in range(24):
            if hour in grouped.index:
                n, mbe = int(grouped.at[hour, "count"]), float(grouped.at[hour, "mean"])
            else:
                n, mbe = 0, math.nan
            rows.append({"hour": hour, "variable": var, "n": n, "mbe": mbe})
    return pd.DataFrame(rows, columns=["hour", "variable", "n", "mbe"])


# --- Báo cáo ----------------------------------------------------------------------

def _clean(value, digits: int = 4):
    """Làm tròn số và thay NaN/inf bằng None để JSON hợp lệ."""
    if isinstance(value, dict):
        return {k: _clean(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, digits) for v in value]
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return round(value, digits) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def build_report(iot_df: pd.DataFrame, ref_df: pd.DataFrame, device_id: str,
                 ref_source: str, tolerance_minutes: float = 5,
                 min_samples: int = 3) -> tuple[dict, pd.DataFrame]:
    """Ghép chuỗi, tính chỉ số và trả (report, aligned)."""
    aligned = align_series(iot_df, ref_df, tolerance_minutes, min_samples)
    meta = {
        "device_id": device_id,
        "ref_source": ref_source,
        "start": aligned["timestamp"].min() if len(aligned) else None,
        "end": aligned["timestamp"].max() if len(aligned) else None,
        "tolerance_minutes": tolerance_minutes,
        "min_samples": min_samples,
        "n_iot_rows": len(iot_df),
        "n_ref_rows": len(ref_df),
        "n_aligned": len(aligned),
        "generated_at": datetime.now(UTC).isoformat(),
        "notes": NOTES,
    }
    report = {"meta": meta, "metrics": {}, "diurnal": []}
    if iot_df.empty:
        report["reason"] = "no_iot_data"
    elif ref_df.empty:
        report["reason"] = "no_reference_data"
    elif aligned.empty:
        report["reason"] = "no_overlap"
    else:
        report["metrics"] = compute_metrics(aligned)
        report["diurnal"] = diurnal_bias(aligned).to_dict("records")
    return _clean(report), aligned


def default_out_dir(device_id: str, ref_source: str) -> Path:
    return DEFAULT_OUT_ROOT / f"{device_id}_{ref_source}"


def save_outputs(report: dict, aligned: pd.DataFrame, out_dir) -> list[Path]:
    """Ghi JSON, CSV cặp đã ghép và các biểu đồ; trả danh sách file đã ghi."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    summary = out_dir / "bias_summary.json"
    summary.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                  allow_nan=False), encoding="utf-8")
    written.append(summary)
    if aligned.empty:
        return written

    pairs_csv = out_dir / "aligned_pairs.csv"
    aligned.to_csv(pairs_csv, index=False)
    written.append(pairs_csv)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metrics = report.get("metrics", {})
    for var, item in metrics.items():
        iot, ref = _pairs(aligned, var)
        unit = UNITS[var]

        fig, ax = plt.subplots(figsize=(5.5, 5))
        ax.scatter(iot, ref, s=12, alpha=0.6, label="Cặp đo")
        lims = [min(iot.min(), ref.min()), max(iot.max(), ref.max())]
        ax.plot(lims, lims, "k--", linewidth=1, label="y = x")
        if item.get("linear_fit"):
            fit = item["linear_fit"]
            xs = np.array(lims)
            ax.plot(xs, fit["slope"] * xs + fit["intercept"], "r-", linewidth=1,
                    label=f"ref = {fit['slope']:.3f}·iot + {fit['intercept']:.2f}")
        ax.set_xlabel(f"IoT ({unit})")
        ax.set_ylabel(f"{report['meta']['ref_source']} ({unit})")
        ax.set_title(f"{var}: n={item['n']}, MBE={item['mbe']:+.2f}, "
                     f"RMSE={item['rmse']:.2f}")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        written.append(_save_fig(fig, out_dir / f"scatter_{var}.png", plt))

        sub = aligned[["timestamp", f"iot_{var}", f"ref_{var}"]].dropna()
        fig, ax = plt.subplots(figsize=(10, 3.5))
        ax.plot(sub["timestamp"], sub[f"iot_{var}"], label="IoT", linewidth=1)
        ax.plot(sub["timestamp"], sub[f"ref_{var}"], label="Tham chiếu", linewidth=1)
        ax.set_ylabel(f"{var} ({unit})")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()
        written.append(_save_fig(fig, out_dir / f"timeseries_{var}.png", plt))

    diurnal = pd.DataFrame(report.get("diurnal", []))
    if not diurnal.empty and metrics:
        fig, axes = plt.subplots(len(metrics), 1, figsize=(8, 2.6 * len(metrics)),
                                 sharex=True, squeeze=False)
        for ax, var in zip(axes[:, 0], metrics):
            sub = diurnal[diurnal["variable"] == var]
            ax.bar(sub["hour"], sub["mbe"].astype(float))
            ax.axhline(0, color="k", linewidth=0.8)
            ax.set_ylabel(f"MBE {var} ({UNITS[var]})")
            ax.grid(alpha=0.3)
        axes[-1, 0].set_xlabel(f"Giờ trong ngày ({LOCAL_TZ})")
        axes[-1, 0].set_xticks(range(24))
        written.append(_save_fig(fig, out_dir / "diurnal_bias.png", plt))
    return written


def _save_fig(fig, path: Path, plt) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# --- CLI --------------------------------------------------------------------------

def _parse_time(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Phan tich sai so IoT vs tham chieu")
    parser.add_argument("--device-id", default="station01")
    parser.add_argument("--source", default="open-meteo",
                        help="source trong reference_weather / CSV tham chieu")
    parser.add_argument("--iot-csv", type=Path)
    parser.add_argument("--ref-csv", type=Path)
    parser.add_argument("--start", type=_parse_time)
    parser.add_argument("--end", type=_parse_time)
    parser.add_argument("--tolerance-minutes", type=float, default=5.0)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    if args.tolerance_minutes <= 0 or args.min_samples < 1:
        parser.error("--tolerance-minutes must be > 0 and --min-samples >= 1")
    if args.start is not None and args.end is not None and args.start > args.end:
        parser.error("--start must be before --end")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    database_url = None
    try:
        if args.iot_csv is None or args.ref_csv is None:
            database_url = get_database_url()
        iot = load_iot(args.iot_csv, database_url, args.device_id,
                       args.start, args.end)
        ref = load_reference(args.ref_csv, database_url, args.source,
                             args.start, args.end)
    except Exception as exc:  # noqa: BLE001 - log nguyên nhân rồi exit 1
        reason = (describe_db_error(exc, database_url) if database_url
                  else f"{type(exc).__name__}: {exc}")
        logger.error("Cannot load data: %s", reason)
        return 1

    report, aligned = build_report(iot, ref, args.device_id, args.source,
                                   args.tolerance_minutes, args.min_samples)
    out_dir = args.out_dir or default_out_dir(args.device_id, args.source)
    written = save_outputs(report, aligned, out_dir)
    if report.get("reason"):
        logger.warning("No bias metrics (%s): iot rows=%d, reference rows=%d",
                       report["reason"], len(iot), len(ref))
    for var, item in report["metrics"].items():
        logger.info("%s: n=%d MBE=%+.3f MAE=%.3f RMSE=%.3f", var, item["n"],
                    item["mbe"], item["mae"], item["rmse"])
    logger.info("Wrote %d files to %s", len(written), out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
