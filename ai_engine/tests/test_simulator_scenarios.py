"""SYS-02: dữ liệu tổng hợp từ simulator, kiểm tra detector không cần broker."""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from sensor_analytics.anomaly_detector import SensorAnomalyDetector

SIMULATOR_PATH = Path(__file__).resolve().parents[2] / "integration_tests/simulate_iot_device.py"
spec = importlib.util.spec_from_file_location("sys02_simulator", SIMULATOR_PATH)
simulator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulator)
make_sample = simulator.make_sample
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize("scenario,minutes,status,expected_type", [
    ("normal", 40, "OK", None),
    ("spike", 10, "FAULT", "OUT_OF_RANGE"),
    ("frozen", 35, "WARNING", "FROZEN_VALUE"),
    ("stuck-wet", 370, "WARNING", "WATER_STAGNATION_DRIFT"),
    ("unplugged", 5, "FAULT", "OUT_OF_RANGE"),
    ("offline", 30, "FAULT", "STALE_DATA"),
])
def test_scenarios_match_detector(scenario, minutes, status, expected_type):
    """Phủ cùng lịch sử, chu kỳ 10 giây và kỳ vọng như script kiểm thử thật."""
    end = NOW - timedelta(minutes=20) if scenario == "offline" else NOW
    if scenario in ("spike", "unplugged"):
        end -= timedelta(seconds=10)
    start = end - timedelta(minutes=minutes)
    history_scenario = scenario if scenario in ("frozen", "stuck-wet") else "normal"
    state = {"device_id": f"sys02-{scenario}-test", "seed": 2}
    samples = [make_sample(history_scenario, index + 1, state, start + timedelta(seconds=index * 10))
               for index in range(minutes * 6 + 1)]
    if scenario in ("spike", "unplugged"):
        latest = make_sample(scenario, 5, state, NOW)
        if scenario == "unplugged":
            assert all(latest[field] is None for field in ("temperature", "humidity", "pressure"))
            assert all(json.loads(json.dumps(latest))[field] is None
                       for field in ("temperature", "humidity", "pressure"))
            # Fallback đúng theo MQTTIngestionWorker khi ArduinoJson gửi NaN thành null.
            latest.update(temperature=0.0, humidity=0.0, pressure=1013.25)
        samples.append(latest)

    report = SensorAnomalyDetector.analyze(pd.DataFrame(samples), now=NOW)
    assert report["status"] == status
    if expected_type is None:
        assert report["anomalies"] == []
    else:
        assert expected_type in {a["type"] for a in report["anomalies"]}
    if scenario == "frozen":
        assert {"temperature", "pressure"}.issubset(report["frozen_sensors"])
        for field in ("temperature", "humidity", "pressure"):
            assert len({sample[field] for sample in samples}) == 1
    elif scenario == "stuck-wet":
        assert report["rain_drift"] is True
        assert all(sample["rain_detected"] == 1 and 800 <= sample["rain_raw"] <= 1000
                   and 50 <= sample["humidity"] <= 60 and 1007.9 <= sample["pressure"] <= 1008.1
                   for sample in samples)
    elif scenario == "offline":
        stale = next(a for a in report["anomalies"] if a["type"] == "STALE_DATA")
        assert stale["age_minutes"] == 20.0


def test_rain_scenario_keeps_legacy_progression():
    samples = [make_sample("rain", step, {}, NOW + timedelta(seconds=step * 5))
               for step in range(1, 11)]
    assert samples[0]["rain_detected"] == 0
    assert samples[2]["rain_detected"] == 1
    assert samples[-1]["temperature"] == 29.5
    assert samples[-1]["humidity"] == 90
    assert samples[-1]["pressure"] == 1004
    assert all(700 <= sample["rain_raw"] <= 1100 for sample in samples)
    assert SensorAnomalyDetector.analyze(pd.DataFrame(samples), now=NOW + timedelta(seconds=50))["status"] == "OK"


def test_make_sample_is_pure_and_keeps_station_default():
    state = {"seed": 42}
    original = state.copy()
    sample = make_sample("normal", 1, state, NOW)
    assert sample == make_sample("normal", 1, state, NOW)
    assert state == original
    assert sample["device_id"] == "station01"
    assert sample["timestamp"] == NOW.isoformat()


def test_spike_every_fifth_sample_and_combined_legacy_rain():
    normal = make_sample("spike", 4, {}, NOW)
    spike = make_sample("spike", 5, {}, NOW)
    assert normal["rain_detected"] == 0 and normal["temperature"] < 32
    assert spike["temperature"] == 62 and spike["pressure"] == 880
    wet = make_sample("spike", 4, {"simulate_rain": True}, NOW)
    assert wet["rain_detected"] == 1 and wet["temperature"] == 30.7


def test_backfill_uses_requested_timestamps_and_device():
    samples = list(simulator.history_samples("normal", 1, 10, {"device_id": "sys02-custom"}, NOW))
    assert len(samples) == 7
    timestamps = [datetime.fromisoformat(sample["timestamp"]) for sample in samples]
    assert timestamps[0] == NOW - timedelta(minutes=1)
    assert timestamps[-1] == NOW
    assert all((right - left).total_seconds() == 10 for left, right in pairwise(timestamps))
    assert all(sample["device_id"] == "sys02-custom" for sample in samples)


@pytest.fixture
def fault_script(monkeypatch):
    """Import script chạy tay mà không kết nối broker hay khởi động backend."""
    monkeypatch.syspath_prepend(str(SIMULATOR_PATH.parent))
    spec = importlib.util.spec_from_file_location(
        "sys02_fault_script", SIMULATOR_PATH.with_name("test_fault_tolerance.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("scenario,expected_count", [
    ("normal", 241), ("spike", 62), ("frozen", 211),
    ("stuck-wet", 2221), ("unplugged", 32), ("offline", 181),
])
def test_manual_script_uses_matching_data_and_expectations(fault_script, scenario, expected_count):
    """Kiểm chứng chính chuỗi publish của script và bộ đánh giá PASS/FAIL của nó."""
    samples = fault_script.scenario_samples(scenario, NOW, "sys02-script-test")
    assert len(samples) == expected_count
    assert all(sample["device_id"] == "sys02-script-test" for sample in samples)
    assert datetime.fromisoformat(samples[-1]["timestamp"]) == (
        NOW - timedelta(minutes=20) if scenario == "offline" else NOW
    )
    if scenario == "unplugged":
        samples[-1].update(temperature=0.0, humidity=0.0, pressure=1013.25)
    report = SensorAnomalyDetector.analyze(pd.DataFrame(samples), now=NOW)
    assert fault_script.matches_expectation(scenario, report)
    assert not fault_script.matches_expectation(scenario, {"status": "UNKNOWN", "anomalies": []})


def test_manual_script_polls_until_all_records_arrive(fault_script, monkeypatch):
    pytest.importorskip("httpx")
    responses = iter([{"n_records": 1, "status": "OK"}, {"n_records": 3, "status": "FAULT"}])
    calls = []

    def get(path, **kwargs):
        calls.append((path, kwargs))
        data = next(responses)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)

    monkeypatch.setattr(fault_script, "time", SimpleNamespace(monotonic=lambda: 0, sleep=lambda _: None))
    result = fault_script.poll_health(SimpleNamespace(get=get), "sys02-poll", 60, 3)
    assert result["status"] == "FAULT"
    assert len(calls) == 2
    assert calls[0][1]["params"] == {"device_id": "sys02-poll", "window_minutes": 60}


def test_manual_script_timeout_cannot_pass_partial_history(fault_script, monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    ticks = iter([0, 0, 0, 0.6, 1.1])
    monkeypatch.setattr(fault_script, "time", SimpleNamespace(
        monotonic=lambda: next(ticks), sleep=lambda _: None,
    ))
    http = SimpleNamespace(get=lambda *args, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"n_records": 1, "status": "OK"},
    ))
    with pytest.raises(TimeoutError, match="n_records=1/3"):
        fault_script.poll_health(http, "sys02-timeout", 60, 3, timeout=1)
    report_path = tmp_path / "results.md"
    fault_script.write_report(report_path, [{
        "scenario": "offline", "device_id": "sys02-offline-test", "data": "synthetic",
        "expected": "FAULT", "actual": "timeout | insufficient records",
        "passed": False, "elapsed": 1.0,
    }], NOW)
    report = report_path.read_text(encoding="utf-8")
    assert "dữ liệu tổng hợp từ simulator" in report
    assert NOW.isoformat() in report
    assert "| FAIL | 1.00 s |" in report
    assert "timeout \\| insufficient records" in report
