"""
Unit test cho SA-03 (Sensor Anomaly & Drift Detection).

LƯU Ý: dữ liệu trong file này là DỮ LIỆU TỔNG HỢP chỉ để kiểm tra logic thuật toán.
"""

import numpy as np
import pandas as pd
import pytest

from sensor_analytics.anomaly_detector import AnomalyConfig, SensorAnomalyDetector as D


def rec(ts="2026-10-01T00:00:00Z", t=30.0, h=70.0, p=1008.0, **extra):
    return {"timestamp": ts, "temperature": t, "humidity": h, "pressure": p, **extra}


def make_history(minutes: float, step_s: int = 10, seed: int = 0, rain=0, humidity=70.0,
                 start="2026-10-01T00:00:00Z") -> pd.DataFrame:
    """DỮ LIỆU TỔNG HỢP: chuỗi đo bình thường có nhiễu nhỏ, chu kỳ `step_s` giây."""
    rng = np.random.default_rng(seed)
    n = int(minutes * 60 / step_s) + 1
    ts = pd.date_range(start, periods=n, freq=f"{step_s}s")
    return pd.DataFrame({
        "timestamp": ts,
        "temperature": 30 + rng.normal(0, 0.05, n),
        "humidity": humidity + rng.normal(0, 0.3, n),
        "pressure": 1008 + rng.normal(0, 0.03, n),
        "rain_raw": np.where(np.asarray(rain) == 1, 900, 2800),
        "rain_detected": rain,
    })


# --- check_measurement ---------------------------------------------------------

def test_normal_record_is_valid():
    out = D.check_measurement(rec(), rec(ts="2026-09-30T23:59:50Z", t=30.1))
    assert out == {"is_valid": True, "has_anomaly": False, "anomaly_list": [], "anomalies": []}


@pytest.mark.parametrize("field,value", [("temperature", 60.0), ("humidity", 5.0), ("pressure", 900.0)])
def test_out_of_range(field, value):
    out = D.check_measurement(rec(**{"t": 30.0}) | {field: value})
    assert not out["is_valid"]
    assert [(a["type"], a["sensor"]) for a in out["anomalies"]] == [("OUT_OF_RANGE", field)]


@pytest.mark.parametrize("value", [None, "abc", float("nan")])
def test_missing_value_does_not_crash_and_is_not_out_of_range(value):
    out = D.check_measurement(rec() | {"humidity": value})
    assert [a["type"] for a in out["anomalies"]] == ["MISSING_VALUE"]


def test_missing_field():
    data = rec()
    del data["pressure"]
    out = D.check_measurement(data)
    assert [(a["type"], a["sensor"]) for a in out["anomalies"]] == [("MISSING_VALUE", "pressure")]


def test_spike_detected_within_one_minute():
    prev = rec(ts="2026-10-01T00:00:00Z", t=30.0)
    cur = rec(ts="2026-10-01T00:00:10Z", t=34.0)
    out = D.check_measurement(cur, prev)
    assert [(a["type"], a["sensor"]) for a in out["anomalies"]] == [("SPIKE", "temperature")]


def test_small_jump_at_short_interval_is_not_spike():
    # 0.4°C sau 5 s: nếu chia thẳng cho dt sẽ thành 4.8°C/phút -> spike giả
    prev = rec(ts="2026-10-01T00:00:00Z", t=30.0)
    cur = rec(ts="2026-10-01T00:00:05Z", t=30.4)
    assert D.check_measurement(cur, prev)["is_valid"]


def test_gradual_change_over_long_interval_is_not_spike():
    prev = rec(ts="2026-10-01T00:00:00Z", t=30.0, p=1008.0)
    cur = rec(ts="2026-10-01T00:05:00Z", t=34.0, p=1002.0)  # 0.8°C/phút, 1.2 hPa/phút
    assert D.check_measurement(cur, prev)["is_valid"]


def test_gap_too_long_skips_spike_check():
    prev = rec(ts="2026-10-01T00:00:00Z", t=30.0)
    cur = rec(ts="2026-10-01T01:00:00Z", t=40.0)
    assert D.check_measurement(cur, prev)["is_valid"]


def test_spike_without_timestamps_uses_absolute_jump():
    prev = {"temperature": 30.0, "humidity": 70.0, "pressure": 1008.0}
    cur = {"temperature": 30.0, "humidity": 85.0, "pressure": 1008.0}
    out = D.check_measurement(cur, prev)
    assert [(a["type"], a["sensor"]) for a in out["anomalies"]] == [("SPIKE", "humidity")]


def test_accepts_datetime_timestamps_from_backend():
    prev = rec(ts=pd.Timestamp("2026-10-01T00:00:00Z").to_pydatetime(), t=30.0)
    cur = rec(ts=pd.Timestamp("2026-10-01T00:00:10Z").to_pydatetime(), t=35.0)
    assert not D.check_measurement(cur, prev)["is_valid"]


# --- detect_frozen_values ------------------------------------------------------

def test_normal_history_not_frozen():
    out = D.detect_frozen_values(make_history(40))
    assert not out["frozen_detected"]


def test_frozen_temperature_detected():
    df = make_history(40)
    df["temperature"] = 29.87
    out = D.detect_frozen_values(df)
    assert out["frozen_sensors"] == ["temperature"]
    assert out["anomalies"][0]["type"] == "FROZEN_VALUE"


def test_frozen_only_counts_recent_window():
    df = make_history(60)
    df.loc[df["timestamp"] < df["timestamp"].iloc[0] + pd.Timedelta(minutes=25), "pressure"] = 1000.0
    assert not D.detect_frozen_values(df)["frozen_detected"]


def test_saturated_humidity_is_not_frozen():
    df = make_history(40)
    df["humidity"] = 100.0
    assert not D.detect_frozen_values(df)["frozen_detected"]


def test_frozen_needs_full_window():
    df = make_history(10)
    df["temperature"] = 29.87
    out = D.detect_frozen_values(df)
    assert not out["frozen_detected"] and out["reason"] == "Insufficient history"


# --- detect_rain_sensor_drift --------------------------------------------------

def test_water_stagnation_detected_after_6h():
    df = make_history(370, step_s=60, rain=1, humidity=55.0)
    out = D.detect_rain_sensor_drift(df)
    assert out["drift_detected"] and out["anomaly_type"] == "WATER_STAGNATION_DRIFT"


def test_window_is_time_based_not_row_based():
    # 200 phút ướt ở chu kỳ 10 s = 1200 dòng (> 360) nhưng chưa đủ 6 giờ
    df = make_history(200, step_s=10, rain=1, humidity=55.0)
    out = D.detect_rain_sensor_drift(df)
    assert not out["drift_detected"] and out["reason"] == "Insufficient history"


def test_real_rain_with_high_humidity_is_not_drift():
    df = make_history(370, step_s=60, rain=1, humidity=92.0)
    assert not D.detect_rain_sensor_drift(df)["drift_detected"]


def test_dry_period_inside_window_is_not_drift():
    df = make_history(370, step_s=60, rain=1, humidity=55.0)
    df.loc[100, "rain_detected"] = 0
    assert not D.detect_rain_sensor_drift(df)["drift_detected"]


def test_falling_pressure_is_not_drift():
    df = make_history(370, step_s=60, rain=1, humidity=55.0)
    df["pressure"] = np.linspace(1010, 1007, len(df))
    assert not D.detect_rain_sensor_drift(df)["drift_detected"]


# --- analyze -------------------------------------------------------------------

def test_analyze_ok_on_normal_data():
    out = D.analyze(make_history(40))
    assert out["status"] == "OK" and out["anomalies"] == []


def test_analyze_fault_on_latest_spike():
    df = make_history(40)
    df.loc[df.index[-1], "temperature"] = 45.0
    out = D.analyze(df)
    assert out["status"] == "FAULT"
    assert out["anomalies"][0]["type"] == "SPIKE"


def test_analyze_warning_on_frozen():
    df = make_history(40)
    df["pressure"] = 1008.0
    out = D.analyze(df)
    assert out["status"] == "WARNING" and out["frozen_sensors"] == ["pressure"]


def test_analyze_empty():
    empty = pd.DataFrame(columns=["timestamp", "temperature", "humidity", "pressure", "rain_detected"])
    assert D.analyze(empty)["status"] == "UNKNOWN"


def test_custom_config():
    cfg = AnomalyConfig(temp_max=35.0)
    assert not D.check_measurement(rec(t=36.0), config=cfg)["is_valid"]
