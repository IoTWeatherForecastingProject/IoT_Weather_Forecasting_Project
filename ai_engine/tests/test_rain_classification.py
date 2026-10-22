"""
Unit test cho SA-01 / SA-02 (mô hình xác suất mưa, nhãn tương lai, calibration, artifact).

LƯU Ý: `make_synthetic_weather` sinh DỮ LIỆU TỔNG HỢP chỉ để kiểm tra tính đúng của pipeline.
Không dùng metric từ dữ liệu này làm kết quả thực nghiệm.
"""

import numpy as np
import pandas as pd
import pytest

from rain_classification.calibration import CalibratedRainModel
from rain_classification.evaluation import (
    assign_split,
    brier_skill_score,
    chronological_boundaries,
    probabilistic_metrics,
    reliability_table,
)
from rain_classification.features import (
    extract_rain_features,
    make_future_rain_labels,
    required_history_minutes,
    resample_to_grid,
)
from rain_classification.train_rain import (
    RainTrainConfig,
    load_artifact,
    save_artifact,
    train_rain_models,
)

FAST_RF = {"n_estimators": 20, "max_depth": 4, "min_samples_leaf": 5,
           "class_weight": "balanced", "random_state": 0, "n_jobs": 1}


def make_synthetic_weather(days: float = 6, rain_every_h: float = 7, rain_len_min: int = 40,
                           seed: int = 0, start: str = "2026-01-01T00:00:00Z") -> pd.DataFrame:
    """DỮ LIỆU TỔNG HỢP (synthetic): mưa định kỳ, trước mỗi trận áp suất tụt và độ ẩm tăng."""
    rng = np.random.default_rng(seed)
    n = int(days * 24 * 60)
    ts = pd.date_range(start, periods=n, freq="1min")
    minutes = np.arange(n)
    period = int(rain_every_h * 60)
    phase = minutes % period
    rain_start = period - rain_len_min
    rain = (phase >= rain_start).astype(int)
    pre = np.clip((phase - (rain_start - 60)) / 60.0, 0, 1)  # 0 -> 1 trong 60 phút trước mưa
    pre[rain == 1] = 1.0
    return pd.DataFrame({
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "device_id": "synthetic01",
        "temperature": 31 - 3 * pre + rng.normal(0, 0.2, n),
        "humidity": 65 + 25 * pre + rng.normal(0, 1.0, n),
        "pressure": 1009 - 2.5 * pre + rng.normal(0, 0.1, n),
        "rain_raw": np.where(rain == 1, 900, 2800) + rng.integers(-50, 50, n),
        "rain_detected": rain,
    })


def _grid_series(values, start="2026-01-01T00:00:00Z"):
    idx = pd.date_range(start, periods=len(values), freq="1min")
    return pd.Series(values, index=idx, dtype=float)


# ------------------------------------------------------------------------------
# Nhãn tương lai
# ------------------------------------------------------------------------------

def test_rain_now_does_not_label_itself():
    rain = _grid_series([0] * 10 + [1] + [0] * 19)
    y = make_future_rain_labels(rain, horizon_minutes=5)
    assert y.iloc[10] == 0  # mưa tại t không làm nhãn (t, t+5] = 1
    assert y.iloc[9] == 1


def test_rain_at_horizon_boundary():
    rain = _grid_series([0] * 10 + [1] + [0] * 19)
    y = make_future_rain_labels(rain, horizon_minutes=5)
    assert y.iloc[5] == 1  # mưa đúng tại t + h được tính
    assert y.iloc[4] == 0  # mưa tại t + h + 1 nằm ngoài cửa sổ


def test_tail_without_future_is_nan_not_negative():
    rain = _grid_series([0] * 30)
    y = make_future_rain_labels(rain, horizon_minutes=5)
    assert y.iloc[24] == 0  # vừa đủ 5 phút tương lai
    assert y.iloc[25:].isna().all()


def test_missing_sensor_value_is_not_no_rain():
    values = [0] * 30
    values[20] = np.nan
    y = make_future_rain_labels(_grid_series(values), horizon_minutes=5)
    assert y.iloc[15:20].isna().all()  # cửa sổ chứa mẫu thiếu, không thấy mưa -> chưa kết luận
    assert y.iloc[14] == 0
    values[18] = 1
    y = make_future_rain_labels(_grid_series(values), horizon_minutes=5)
    assert y.iloc[15] == 1  # đã thấy mưa trong cửa sổ thì là 1 dù có mẫu thiếu


def test_labels_reject_irregular_index():
    rain = pd.Series([0, 0, 1], index=pd.to_datetime(
        ["2026-01-01T00:00Z", "2026-01-01T00:01Z", "2026-01-01T00:05Z"]))
    with pytest.raises(ValueError):
        make_future_rain_labels(rain, horizon_minutes=1)


# ------------------------------------------------------------------------------
# Lưới thời gian & feature nhân quả
# ------------------------------------------------------------------------------

def test_irregular_timestamps_and_gaps():
    raw = pd.DataFrame({
        "timestamp": ["2026-01-01T00:00:10Z", "2026-01-01T00:00:50Z", "2026-01-01T00:01:00Z",
                      "2026-01-01T00:01:40Z", "2026-01-01T00:08:20Z", "2026-01-01T00:09:00Z"],
        "temperature": [30.0, 32.0, 34.0, 36.0, 40.0, 41.0],
        "humidity": [70.0] * 6, "pressure": [1008.0] * 6,
        "rain_detected": [0, 0, 1, 0, 0, 0],
    })
    grid = resample_to_grid(raw, freq="1min", ffill_limit=2)
    t = lambda s: pd.Timestamp(f"2026-01-01T{s}Z")
    # Bin (00:00, 00:01] gồm 00:00:10, 00:00:50, 00:01:00
    assert grid.loc[t("00:01"), "temperature"] == pytest.approx(32.0)
    assert grid.loc[t("00:01"), "rain_detected"] == 1
    assert grid.loc[t("00:02"), "temperature"] == pytest.approx(36.0)
    # Khoảng trống 00:03..00:08: fill tối đa 2 bước, còn lại NaN; nhãn nguồn không bị fill
    assert grid.loc[t("00:04"), "temperature"] == pytest.approx(36.0)
    assert np.isnan(grid.loc[t("00:05"), "temperature"])
    assert grid.loc[t("00:03"):t("00:08"), "rain_observed"].isna().all()
    y = make_future_rain_labels(grid["rain_observed"], horizon_minutes=2)
    assert y.loc[t("00:02"):t("00:07")].isna().all()  # không biến khoảng mất dữ liệu thành "không mưa"


def test_features_use_only_past_data():
    raw = make_synthetic_weather(days=0.2)
    cut = 150
    base = extract_rain_features(resample_to_grid(raw))
    changed = raw.copy()
    changed.loc[cut + 1:, ["temperature", "humidity", "pressure", "rain_raw"]] += 50.0
    changed.loc[cut + 1:, "rain_detected"] = 1
    after = extract_rain_features(resample_to_grid(changed))
    t_cut = pd.Timestamp(raw.loc[cut, "timestamp"])
    cols = [c for c in base.columns if c != "rain_observed"]
    pd.testing.assert_frame_equal(base.loc[:t_cut, cols], after.loc[:t_cut, cols])


def test_short_history_does_not_silently_drop_features():
    from rain_classification.features import ATMOSPHERIC_FEATURES, select_feature_columns
    feat = extract_rain_features(resample_to_grid(make_synthetic_weather(days=0.03)))
    assert feat["press_diff_60m"].isna().all()
    cols = select_feature_columns(feat)
    assert set(ATMOSPHERIC_FEATURES) <= set(cols)
    no_raw = select_feature_columns(feat.drop(columns=["rain_raw"]))
    assert not any(c.startswith("rain_raw") for c in no_raw)


def test_required_history_covers_longest_feature():
    raw = make_synthetic_weather(days=0.2)
    feat = extract_rain_features(resample_to_grid(raw))
    need = required_history_minutes("1min")
    first_complete = feat.drop(columns=["rain_observed"]).dropna().index.min()
    assert (first_complete - feat.index.min()) / pd.Timedelta(minutes=1) + 1 == need


# ------------------------------------------------------------------------------
# Chia dữ liệu theo thời gian
# ------------------------------------------------------------------------------

def test_label_windows_do_not_cross_split_boundaries():
    times = pd.date_range("2026-01-01", periods=1000, freq="1min", tz="UTC")
    t_cal, t_test = chronological_boundaries(times)
    for h in (10, 30, 60):
        split = assign_split(times, t_cal, t_test, h)
        gap = pd.Timedelta(minutes=h)
        assert (split[split == "train"].index + gap < t_cal).all()
        cal = split[split == "calibration"].index
        assert (cal >= t_cal).all() and (cal + gap < t_test).all()
        assert (split[split == "test"].index >= t_test).all()
        assert (split == "purged").sum() == 2 * h


def test_training_report_respects_boundaries():
    cfg = RainTrainConfig(rf_params=FAST_RF)
    _, report = train_rain_models(make_synthetic_weather(), cfg)
    t_cal = pd.Timestamp(report["split_boundaries"]["calibration_start"])
    t_test = pd.Timestamp(report["split_boundaries"]["test_start"])
    for h, res in report["horizons"].items():
        gap = pd.Timedelta(minutes=int(h))
        assert pd.Timestamp(res["sets"]["train"]["end"]) + gap < t_cal
        assert pd.Timestamp(res["sets"]["calibration"]["end"]) + gap < t_test


# ------------------------------------------------------------------------------
# Trường hợp ít mẫu / một lớp
# ------------------------------------------------------------------------------

def test_single_class_training_is_skipped_without_crash():
    raw = make_synthetic_weather(days=2)
    raw["rain_detected"] = 0
    payload, report = train_rain_models(raw, RainTrainConfig(rf_params=FAST_RF))
    assert payload["models"] == {}
    assert all(r["status"] == "skipped_insufficient_train" for r in report["horizons"].values())


def test_no_rain_after_train_period_is_not_deployed():
    raw = make_synthetic_weather(days=2)
    raw.loc[int(len(raw) * 0.6):, "rain_detected"] = 0  # cal/test không có mưa
    payload, report = train_rain_models(raw, RainTrainConfig(rf_params=FAST_RF))
    assert payload["models"] == {}
    for res in report["horizons"].values():
        assert res["status"] == "not_deployed_calibration_unavailable"
        assert res["test_metrics"]["uncalibrated"]["roc_auc"] is None
        assert res["test_metrics"]["uncalibrated"]["note"]
    payload, _ = train_rain_models(raw, RainTrainConfig(rf_params=FAST_RF, allow_uncalibrated=True))
    assert all(m.calibration_method == "none" for m in payload["models"].values())


def test_too_little_history_raises_clear_error():
    with pytest.raises(ValueError, match="lich su"):
        train_rain_models(make_synthetic_weather(days=0.03), RainTrainConfig(rf_params=FAST_RF))


def test_multiple_devices_require_explicit_device():
    raw = pd.concat([make_synthetic_weather(days=1), make_synthetic_weather(days=1).assign(device_id="b")])
    with pytest.raises(ValueError, match="device_id"):
        train_rain_models(raw, RainTrainConfig(rf_params=FAST_RF))


def test_metrics_single_class_and_empty():
    m = probabilistic_metrics(np.zeros(5), np.full(5, 0.1))
    assert m["brier"] == pytest.approx(0.01) and m["roc_auc"] is None and m["pr_auc"] is None
    assert probabilistic_metrics(np.array([]), np.array([]))["brier"] is None
    assert brier_skill_score(0.1, 0.0)["value"] is None
    assert brier_skill_score(0.05, 0.1)["value"] == pytest.approx(0.5)


def test_reliability_table_counts():
    y = np.array([0, 0, 1, 1, 1])
    p = np.array([0.05, 0.15, 0.55, 0.95, 1.0])
    rows = reliability_table(y, p, n_bins=10)
    assert sum(r["count"] for r in rows) == len(y)
    assert rows[9]["count"] == 2 and rows[9]["observed_frequency"] == 1.0
    assert rows[3]["count"] == 0 and rows[3]["mean_predicted"] is None


# ------------------------------------------------------------------------------
# Calibration & artifact
# ------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def trained():
    cfg = RainTrainConfig(rf_params=FAST_RF)
    return train_rain_models(make_synthetic_weather(), cfg)


def test_synthetic_pipeline_deploys_calibrated_models(trained):
    payload, report = trained
    assert sorted(payload["deployed_horizons"]) == [10, 30, 60]
    for h, res in report["horizons"].items():
        assert res["status"] == "deployed"
        assert res["calibration"]["deployed_method"] == "sigmoid"
        assert {"climatology", "persistence", "uncalibrated", "sigmoid", "isotonic"} <= set(res["test_metrics"])
        assert res["test_metrics"]["sigmoid"]["roc_auc"] is not None


def test_artifact_roundtrip_predicts_valid_probabilities(trained, tmp_path):
    payload, _ = trained
    path = tmp_path / "rain.joblib"
    save_artifact(payload, path)
    loaded = load_artifact(path)
    for key in ("feature_cols", "horizons", "freq", "min_history_minutes", "recommended_history_minutes",
                "calibration", "library_versions", "training_config", "artifact_version"):
        assert key in loaded

    feat = extract_rain_features(resample_to_grid(make_synthetic_weather(days=1, seed=1)))
    X = feat[loaded["feature_cols"]].dropna()
    for name, model in loaded["models"].items():
        proba = model.predict_proba(X)
        assert proba.shape == (len(X), 2)
        assert np.all((proba >= 0) & (proba <= 1))
        np.testing.assert_allclose(proba.sum(axis=1), 1.0)
        np.testing.assert_allclose(proba, payload["models"][name].predict_proba(X))


def test_model_rejects_incomplete_features(trained):
    payload, _ = trained
    model = payload["models"]["rain_30m"]
    feat = extract_rain_features(resample_to_grid(make_synthetic_weather(days=0.02)))
    with pytest.raises(ValueError, match="NaN"):
        model.predict_proba(feat[payload["feature_cols"]].iloc[[-1]])
    with pytest.raises(ValueError, match="Thieu feature"):
        model.predict_proba(feat[payload["feature_cols"][:-1]].iloc[[-1]])


# ------------------------------------------------------------------------------
# Tích hợp inference/unified_forecast.py
# ------------------------------------------------------------------------------

@pytest.fixture
def uf_with_rain(trained, monkeypatch, tmp_path):
    """unified_forecast với artifact mưa tổng hợp, không có model nhiệt độ."""
    import inference.unified_forecast as uf

    payload, _ = trained
    monkeypatch.setattr(uf, "TEMP_MODEL_PATH", tmp_path / "missing_temp.joblib")
    monkeypatch.setattr(uf, "RAIN_MODEL_PATH", tmp_path / "missing_rain.joblib")
    monkeypatch.setattr(uf, "_temp_payload", None)
    monkeypatch.setattr(uf, "_rain_payload", payload)
    return uf, payload


def _expected_model_prob(payload, recent, h):
    feat = extract_rain_features(resample_to_grid(recent))
    X = feat[payload["feature_cols"]].iloc[[-1]]
    return round(float(payload["models"][f"rain_{h}m"].predict_proba(X)[0, 1]), 2)


def test_unified_forecast_uses_training_feature_pipeline(uf_with_rain):
    uf, payload = uf_with_rain
    recent = make_synthetic_weather(days=1, seed=2).tail(payload["recommended_history_minutes"])
    result = uf.predict_forecast(recent)
    for h in (10, 30, 60):
        assert result[f"plus_{h}m"]["rain_source"] == "model"
        assert result[f"plus_{h}m"]["rain_probability"] == _expected_model_prob(payload, recent, h)


def test_unified_forecast_keeps_valid_horizons_when_one_is_missing(uf_with_rain, monkeypatch):
    uf, payload = uf_with_rain
    partial = dict(payload, models={k: v for k, v in payload["models"].items() if k != "rain_10m"})
    monkeypatch.setattr(uf, "_rain_payload", partial)
    recent = make_synthetic_weather(days=1, seed=2).tail(payload["recommended_history_minutes"])
    result = uf.predict_forecast(recent)
    assert result["plus_10m"]["rain_source"] == "heuristic"
    for h in (30, 60):
        assert result[f"plus_{h}m"]["rain_source"] == "model"
        assert result[f"plus_{h}m"]["rain_probability"] == _expected_model_prob(payload, recent, h)


def test_unified_forecast_short_history_falls_back_without_crash(uf_with_rain, caplog):
    uf, _ = uf_with_rain
    recent = make_synthetic_weather(days=1, seed=2).tail(30)  # 30 phút < min_history_minutes
    result = uf.predict_forecast(recent)
    for h in (10, 30, 60):
        assert result[f"plus_{h}m"]["rain_source"] == "heuristic"
        assert 0.0 <= result[f"plus_{h}m"]["rain_probability"] <= 1.0
    assert "NaN" in caplog.text


def test_unified_forecast_alert_uses_threshold(uf_with_rain):
    uf, payload = uf_with_rain
    recent = make_synthetic_weather(days=1, seed=2).tail(payload["recommended_history_minutes"])
    max_prob = max(uf.predict_forecast(recent)[f"plus_{h}m"]["rain_probability"] for h in (10, 30, 60))
    assert uf.predict_forecast(recent, threshold=0.0)["alert_triggered"] is True
    if max_prob < 1.0:
        assert uf.predict_forecast(recent, threshold=1.0)["alert_triggered"] is False
    with pytest.raises(ValueError, match="threshold"):
        uf.predict_forecast(recent, threshold=1.5)


def test_unified_forecast_uses_only_latest_device(uf_with_rain):
    uf, payload = uf_with_rain
    recent = make_synthetic_weather(days=1, seed=2).tail(payload["recommended_history_minutes"])
    other = make_synthetic_weather(days=1, seed=3).tail(payload["recommended_history_minutes"])
    other = other.assign(device_id="other01", pressure=other["pressure"] - 50)
    mixed = pd.concat([other, recent]).sort_values("timestamp", kind="stable")
    result = uf.predict_forecast(mixed)
    assert result["device_id"] == "synthetic01"
    for h in (10, 30, 60):
        assert result[f"plus_{h}m"]["rain_probability"] == _expected_model_prob(payload, recent, h)
