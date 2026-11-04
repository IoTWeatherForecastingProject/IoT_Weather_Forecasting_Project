"""
Unit test cho SA-04b (phân tích sai số IoT vs tham chiếu).

LƯU Ý: dữ liệu trong file này là DỮ LIỆU TỔNG HỢP chỉ để kiểm tra tính đúng của thuật toán.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from openweather_benchmark.bias_analysis import (
    align_series,
    build_report,
    compute_metrics,
    diurnal_bias,
    main,
    save_outputs,
)

START = "2026-10-01T00:00:00Z"


def make_reference(hours=72, start=START):
    """DỮ LIỆU TỔNG HỢP: chuỗi tham chiếu theo giờ có dao động ngày đêm."""
    ts = pd.date_range(start, periods=hours, freq="1h")
    phase = 2 * np.pi * np.arange(hours) / 24
    return pd.DataFrame({
        "timestamp": ts,
        "temperature": 29 + 3 * np.sin(phase),
        "humidity": 75 - 10 * np.sin(phase),
        "pressure": 1008 + 1.5 * np.cos(2 * phase),
    })


def make_iot(ref, step_s=10, bias=(1.5, -4.0, 2.0), noise=0.1, seed=0):
    """DỮ LIỆU TỔNG HỢP: IoT = tham chiếu nội suy + bias cố định + nhiễu."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(ref["timestamp"].iloc[0], ref["timestamp"].iloc[-1],
                       freq=f"{step_s}s")
    x_ref = ref["timestamp"].astype("int64").to_numpy()
    x = ts.astype("int64").to_numpy()
    out = {"timestamp": ts}
    for var, b in zip(("temperature", "humidity", "pressure"), bias):
        out[var] = (np.interp(x, x_ref, ref[var].to_numpy()) + b
                    + rng.normal(0, noise, len(ts)))
    return pd.DataFrame(out)


def test_known_bias_recovered():
    ref = make_reference()
    aligned = align_series(make_iot(ref), ref)
    m = compute_metrics(aligned)
    for var, bias in (("temperature", 1.5), ("humidity", -4.0), ("pressure", 2.0)):
        assert m[var]["mbe"] == pytest.approx(bias, abs=0.05)
        assert m[var]["rmse"] == pytest.approx(abs(bias), abs=0.05)
        assert m[var]["mbe_corrected_check"] == pytest.approx(0, abs=1e-6)
        assert m[var]["pearson_r"] > 0.99
    fit = m["temperature"]["linear_fit"]
    assert fit["slope"] == pytest.approx(1, abs=0.02)
    assert fit["intercept"] == pytest.approx(-1.5, abs=0.6)


def test_align_closed_window_and_min_samples():
    ref = pd.DataFrame({"timestamp": pd.to_datetime([START], utc=True),
                        "temperature": [30.0], "humidity": [70.0], "pressure": [1008.0]})
    t = pd.Timestamp(START)
    iot = pd.DataFrame({
        "timestamp": [t - pd.Timedelta(minutes=5), t, t + pd.Timedelta(minutes=5),
                      t + pd.Timedelta(minutes=5, seconds=1)],
        "temperature": [31.0, 32.0, 33.0, 99.0],
        "humidity": [70.0, np.nan, 70.0, 70.0],
        "pressure": [1008.0, 1008.0, 1008.0, 1008.0],
    })
    out = align_series(iot, ref, tolerance_minutes=5, min_samples=3)
    assert out.loc[0, "iot_temperature"] == pytest.approx(32.0)   # biên ±5 phút được tính
    assert np.isnan(out.loc[0, "iot_humidity"])                    # chỉ 2 mẫu hợp lệ
    assert out.loc[0, "iot_pressure"] == pytest.approx(1008.0)     # biến khác không bị mất
    assert out.loc[0, "n_iot"] == 3


def test_align_handles_local_timezone():
    ref = make_reference(hours=3)
    iot = make_iot(ref, bias=(1.0, 0.0, 0.0), noise=0.0)
    iot["timestamp"] = iot["timestamp"].dt.tz_convert("Asia/Ho_Chi_Minh").astype(str)
    m = compute_metrics(align_series(iot, ref))
    # lệch rất nhỏ do lấy trung bình ±5 phút trên đường cong, không do múi giờ
    assert m["temperature"]["mbe"] == pytest.approx(1.0, abs=0.01)
    assert m["temperature"]["n"] == 3


def test_pearson_none_for_constant_reference():
    ref = make_reference(hours=10)
    ref["pressure"] = 1008.0
    m = compute_metrics(align_series(make_iot(ref), ref))
    assert m["pressure"]["pearson_r"] is None


@pytest.mark.parametrize("case,reason", [
    ("no_overlap", "no_overlap"), ("empty_iot", "no_iot_data"), ("empty_ref", "no_reference_data"),
])
def test_report_reasons_without_crash(tmp_path, case, reason):
    ref = make_reference(hours=5)
    iot = make_iot(ref)
    if case == "no_overlap":
        iot["timestamp"] = iot["timestamp"] + pd.Timedelta(days=10)
    elif case == "empty_iot":
        iot = iot.iloc[0:0]
    else:
        ref = ref.iloc[0:0]
    report, aligned = build_report(iot, ref, "station01", "open-meteo")
    assert report["reason"] == reason and report["metrics"] == {}
    files = save_outputs(report, aligned, tmp_path)
    assert [f.name for f in files] == ["bias_summary.json"]


def test_diurnal_uses_local_hour():
    ref = make_reference(hours=24)
    d = diurnal_bias(align_series(make_iot(ref), ref))
    temp = d[d["variable"] == "temperature"].set_index("hour")
    assert len(temp) == 24 and (temp["n"] == 1).all()
    # mốc UTC 00:00 rơi vào 07:00 giờ Việt Nam
    aligned = align_series(make_iot(ref.iloc[:1].copy()), ref.iloc[:1].copy(), min_samples=1)
    one = diurnal_bias(aligned)
    hours = one[(one["variable"] == "temperature") & (one["n"] > 0)]["hour"].tolist()
    assert hours == [7]


def _reject_nan(value):
    raise ValueError(f"NaN/Infinity in JSON: {value}")


def test_save_outputs_writes_valid_json_and_plots(tmp_path):
    ref = make_reference(hours=30)
    report, aligned = build_report(make_iot(ref), ref, "station01", "open-meteo")
    names = {f.name for f in save_outputs(report, aligned, tmp_path)}
    assert {"bias_summary.json", "aligned_pairs.csv", "diurnal_bias.png",
            "scatter_temperature.png", "timeseries_pressure.png"} <= names
    data = json.loads((tmp_path / "bias_summary.json").read_text(encoding="utf-8"),
                      parse_constant=_reject_nan)
    assert data["meta"]["n_aligned"] == 30
    assert (tmp_path / "scatter_temperature.png").stat().st_size > 10_000


def test_align_performance_500k_rows():
    ref = make_reference(hours=720)
    ts = pd.date_range(START, periods=500_000, freq="5s")
    iot = pd.DataFrame({"timestamp": ts, "temperature": 30.0,
                        "humidity": 70.0, "pressure": 1008.0})
    t0 = time.perf_counter()
    out = align_series(iot, ref)
    assert time.perf_counter() - t0 < 5
    assert len(out) > 0


def test_cli_with_csv(tmp_path):
    ref = make_reference(hours=24)
    iot = make_iot(ref, step_s=60)
    iot["device_id"] = "station01"
    ref["source"] = "open-meteo"
    iot_csv, ref_csv = tmp_path / "iot.csv", tmp_path / "ref.csv"
    iot.to_csv(iot_csv, index=False)
    pd.concat([ref, ref.assign(source="open-meteo-15min", temperature=0)]).to_csv(
        ref_csv, index=False)
    out = tmp_path / "out"
    assert main(["--iot-csv", str(iot_csv), "--ref-csv", str(ref_csv),
                 "--out-dir", str(out)]) == 0
    data = json.loads((out / "bias_summary.json").read_text(encoding="utf-8"))
    # chỉ dùng source được chọn (dòng open-meteo-15min có temperature=0 bị loại)
    assert data["metrics"]["temperature"]["mbe"] == pytest.approx(1.5, abs=0.1)


def test_cli_missing_file_exits_1(tmp_path):
    assert main(["--iot-csv", str(tmp_path / "nope.csv"),
                 "--ref-csv", str(tmp_path / "nope.csv")]) == 1


def test_cli_rejects_bad_args():
    with pytest.raises(SystemExit):
        main(["--iot-csv", "a", "--ref-csv", "b", "--tolerance-minutes", "0"])


def test_alignment_has_no_crawler_dependency():
    """Backend chỉ cài dependencies của nó: alignment không được kéo theo requests."""
    code = (
        "import sys; sys.modules['requests'] = None; "
        "import openweather_benchmark.alignment; "
        "assert 'openweather_benchmark.crawler' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
