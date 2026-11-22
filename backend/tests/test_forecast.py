"""BE-05 contract tests on an isolated DB; no model artifacts or running services needed."""
import json
from datetime import datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import endpoints
from app.config import settings
from app.db.models import ForecastSnapshot, ForecastTestPeriod, SystemConfig, WeatherMeasurement
from app.db.session import Base, get_db
from app.main import app
from app.services import forecast_client
from app.services.forecast_client import ForecastClient
from app.services.alert_service import AlertService

NOW = datetime(2026, 10, 27, 11, 0, tzinfo=timezone.utc)
HORIZONS = ("plus_10m", "plus_30m", "plus_60m")


@pytest.fixture
def context(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        WeatherMeasurement.__table__, SystemConfig.__table__,
        ForecastSnapshot.__table__, ForecastTestPeriod.__table__,
    ])
    db = Session(engine)
    ids = count(1)

    def add(device_id="target", age_minutes=0):
        row = WeatherMeasurement(
            id=next(ids), device_id=device_id,
            timestamp=NOW - timedelta(minutes=age_minutes),
            temperature=31.5, humidity=75.0, pressure=1008.0,
            rain_raw=750, rain_detected=0,
        )
        db.add(row)
        return row

    def override_db():
        yield db

    def predict(frame, threshold):
        latest = frame.iloc[-1]
        return {
            "device_id": latest["device_id"], "generated_at": NOW.isoformat(),
            "current_temperature": float(latest["temperature"]),
            "current_humidity": float(latest["humidity"]),
            "current_pressure": float(latest["pressure"]),
            **{
                horizon: {"temperature_c": 31.0, "rain_probability": probability,
                          "rain_level": "Medium", "rain_source": source}
                for horizon, probability, source in zip(
                    HORIZONS, (0.5, 0.6, 0.65), ("model", "heuristic", "model")
                )
            },
            "alert_triggered": 0.65 >= threshold,
            "alert_message": "rain" if 0.65 >= threshold else None,
        }

    clock = Mock(wraps=datetime)
    clock.now.return_value = NOW
    predictor, trigger = Mock(side_effect=predict), Mock(return_value=False)
    monkeypatch.setattr(endpoints, "datetime", clock)
    monkeypatch.setattr(settings, "RAIN_ALERT_THRESHOLD", 0.70)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    monkeypatch.setattr(settings, "FORECAST_ENGINE_MODE", "auto")
    monkeypatch.setattr(forecast_client, "load_forecast_predictor", Mock(return_value=predictor))
    monkeypatch.setattr(AlertService, "evaluate_and_trigger", trigger)
    yield SimpleNamespace(db=db, add=add, predictor=predictor, trigger=trigger,
                          client=TestClient(app))
    db.close()
    engine.dispose()


def test_forecast_uses_full_time_window_and_preserves_per_horizon_sources(context):
    # 241 samples cover 120 minutes; TV2 needs at least 90 actual minutes.
    for index in reversed(range(241)):
        context.add(age_minutes=index / 2)
    context.add(age_minutes=120.001)
    context.add(age_minutes=-0.001)
    context.add(device_id="other", age_minutes=1)

    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    result = response.json()
    frame = context.predictor.call_args.args[0]
    assert len(frame) == 241
    assert set(frame["device_id"]) == {"target"}
    assert frame["timestamp"].is_monotonic_increasing
    assert frame["timestamp"].iloc[0].replace(tzinfo=timezone.utc) == NOW - timedelta(minutes=120)
    assert frame["timestamp"].iloc[-1].replace(tzinfo=timezone.utc) == NOW
    assert frame["rain_raw"].eq(750).all()
    assert result["history_measurements"] == 241
    assert result["history_window_minutes"] == 120
    assert result["history_span_minutes"] == 120
    assert [result[h]["rain_source"] for h in HORIZONS] == ["model", "heuristic", "model"]


def test_omitted_device_selects_only_latest_recent_station(context):
    context.add(device_id="older", age_minutes=2)
    context.add(device_id="older", age_minutes=1)
    context.add(device_id="newer", age_minutes=3)
    context.add(device_id="newer", age_minutes=0.5)
    context.add(device_id="future", age_minutes=-1)

    response = context.client.get("/api/weather/forecast")
    assert response.status_code == 200
    assert response.json()["device_id"] == "newer"
    frame = context.predictor.call_args.args[0]
    assert set(frame["device_id"]) == {"newer"}
    assert len(frame) == 2


@pytest.mark.parametrize("age_minutes", [None, 121, -1])
@pytest.mark.parametrize("explicit_device", [True, False])
def test_absent_stale_or_future_measurements_do_not_create_forecasts(context, age_minutes, explicit_device):
    if age_minutes is not None:
        context.add(age_minutes=age_minutes)
    params = {"device_id": "target"} if explicit_device else {}
    response = context.client.get("/api/weather/forecast", params=params)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_recent_measurements"
    context.predictor.assert_not_called()
    context.trigger.assert_not_called()


@pytest.mark.parametrize("threshold,expected_alert", [(0.0, True), (0.65, True), (0.66, False), (1.0, False)])
def test_threshold_update_reaches_inference_response_and_alert_service(context, threshold, expected_alert):
    context.add()
    updated = context.client.post("/api/weather/alerts/threshold", json={"threshold": threshold})
    assert updated.status_code == 200
    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    assert context.predictor.call_args.kwargs["threshold"] == threshold
    assert context.trigger.call_args.kwargs["threshold"] == threshold
    assert response.json()["rain_alert_threshold"] == threshold
    assert response.json()["alert_triggered"] is expected_alert


def test_missing_db_threshold_uses_environment_setting(context, monkeypatch):
    context.add()
    monkeypatch.setattr(settings, "RAIN_ALERT_THRESHOLD", 0.42)
    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    assert context.predictor.call_args.kwargs["threshold"] == 0.42
    assert response.json()["rain_alert_threshold"] == 0.42


def test_short_history_is_exposed_without_claiming_full_history(context):
    context.add(age_minutes=2)
    context.add(age_minutes=0)
    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    assert response.json()["history_span_minutes"] == 2
    assert response.json()["history_measurements"] == 2


def test_invalid_device_id_is_rejected(context):
    response = context.client.get("/api/weather/forecast", params={"device_id": ""})
    assert response.status_code == 422
    context.predictor.assert_not_called()


def test_forecast_passes_running_worker_client_to_actuation(context, monkeypatch):
    context.add()
    mqtt_client = Mock()
    mqtt_client.is_connected.return_value = True
    monkeypatch.setattr(app.state, "mqtt_worker", SimpleNamespace(client=mqtt_client), raising=False)
    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    assert context.trigger.call_args.kwargs["mqtt_client"] is mqtt_client
    topic, payload = mqtt_client.publish.call_args.args
    assert topic == f"{settings.MQTT_TOPIC_PREFIX}/target/forecast"
    assert json.loads(payload) == {
        "type": "rain_forecast", "device_id": "target",
        "horizon_minutes": 60, "probability_pct": 65, "threshold_reached": False,
    }
    assert mqtt_client.publish.call_args.kwargs == {"qos": 0, "retain": False}


def test_regional_forecast_displays_without_using_iot_data_or_triggering_alarm(context, monkeypatch):
    from app.services import regional_forecast

    monkeypatch.setattr(settings, "FORECAST_ENGINE_MODE", "regional_vvts")
    monkeypatch.setattr(settings, "REGIONAL_FORECAST_DEVICE_ID", "station01")
    mqtt = Mock()
    monkeypatch.setattr(app.state, "mqtt_worker", SimpleNamespace(client=mqtt), raising=False)
    classifier = Mock()
    classifier.predict_proba.return_value = np.array([[0.1, 0.9]])
    monkeypatch.setattr(regional_forecast, "load_model", Mock(return_value={
        "features": ["temperature", "rain_now"],
        "models": {
            30: {"temperature": Mock(predict=Mock(return_value=[0.5])),
                 "rain": (classifier, Mock(predict=Mock(return_value=[0.9])))},
        },
    }))
    observations = pd.DataFrame([
        {"station": "VVTS", "valid": NOW, "metar": "METAR VVTS 271100Z 9999 30/25 Q1008 TEMPO -RA"},
    ])
    monkeypatch.setattr(regional_forecast, "read_observations", lambda: observations)

    response = context.client.get("/api/weather/forecast", params={"device_id": "station01"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["forecast_scope"] == "VVTS"
    assert result["plus_10m"]["rain_probability"] is None
    assert result["plus_30m"]["rain_probability"] == 0.9
    assert result["plus_30m"]["temperature_c"] == 30.5
    assert classifier.predict_proba.call_args.args[0]["rain_now"].iloc[0] == 0
    assert result["alert_triggered"] is False
    context.trigger.assert_not_called()
    assert json.loads(mqtt.publish.call_args.args[1])["threshold_reached"] is False

    mqtt.reset_mock()
    observations["valid"] = NOW - timedelta(hours=2)
    result = context.client.get("/api/weather/forecast", params={"device_id": "station01"}).json()
    assert result["forecast_issue"] == "observations_stale"
    assert result["plus_30m"]["rain_probability"] is None
    mqtt.publish.assert_not_called()


def test_station_model_receives_only_measurements_from_requested_device(context, monkeypatch):
    from app.services import regional_forecast, station_input_forecast

    monkeypatch.setattr(settings, "FORECAST_ENGINE_MODE", "station_inputs")
    monkeypatch.setattr(regional_forecast, "read_observations", Mock(side_effect=AssertionError("airport feed")))
    context.add("station01", age_minutes=60).pressure = 1007
    context.add("station01", age_minutes=30).humidity = 72
    context.add("station01").temperature = 32
    context.add("other").temperature = 45
    mqtt = Mock()
    monkeypatch.setattr(app.state, "mqtt_worker", SimpleNamespace(client=mqtt), raising=False)
    classifier = Mock()
    classifier.predict_proba.return_value = np.array([[0.1, 0.9]])
    temperature = Mock()
    temperature.predict.return_value = [0.5]
    monkeypatch.setattr(station_input_forecast, "load_model", Mock(return_value={
        "features": ["temperature", "humidity_change_30m", "pressure_change_60m"],
        "models": {30: {"temperature": temperature, "rain": (classifier, Mock(predict=Mock(return_value=[0.9])))}},
    }))
    short_classifier = Mock()
    short_classifier.predict_proba.return_value = np.array([[0.8, 0.2]])
    monkeypatch.setattr(station_input_forecast, "load_short_model", Mock(return_value={
        "features": ["temperature", "humidity_change_10m"],
        "model": {"temperature": None, "rain": (short_classifier, Mock(predict=Mock(return_value=[0.2])))},
    }))
    context.add("station01", age_minutes=10).humidity = 71

    response = context.client.get("/api/weather/forecast", params={"device_id": "station01"})
    assert response.status_code == 200, response.text
    result = response.json()
    expected = {"temperature": 32, "humidity_change_30m": 3, "pressure_change_60m": 1}
    assert temperature.predict.call_args.args[0].iloc[0].to_dict() == expected
    assert classifier.predict_proba.call_args.args[0].iloc[0].to_dict() == expected
    assert result["forecast_engine"] == "station_inputs" and result["forecast_scope"] == "station"
    assert short_classifier.predict_proba.call_args.args[0].iloc[0].to_dict() == {
        "temperature": 32, "humidity_change_10m": 4,
    }
    assert result["plus_10m"]["rain_probability"] == 0.2
    assert result["plus_30m"]["temperature_c"] == 32.5
    assert result["plus_30m"]["rain_probability"] == 0.9
    assert result["alert_triggered"] is True
    context.trigger.assert_called_once_with(
        device_id="station01", rain_probability=0.9, horizon_minutes=30,
        mqtt_client=mqtt, threshold=0.7,
    )
    context.predictor.assert_not_called()
    assert json.loads(mqtt.publish.call_args.args[1])["threshold_reached"] is True

    context.trigger.reset_mock()
    monkeypatch.setattr(settings, "RAIN_ALERT_THRESHOLD", 0.95)
    below_threshold = context.client.get("/api/weather/forecast", params={"device_id": "station01"}).json()
    assert below_threshold["alert_triggered"] is False
    context.trigger.assert_not_called()
    assert json.loads(mqtt.publish.call_args.args[1])["threshold_reached"] is False
    saved = context.db.query(ForecastSnapshot).order_by(ForecastSnapshot.horizon_minutes).all()
    assert [point.horizon_minutes for point in saved] == [10, 30]
    assert float(saved[1].rain_threshold) == 0.7

    mqtt.reset_mock()
    missing = context.client.get("/api/weather/forecast", params={"device_id": "other"}).json()
    assert missing["forecast_issue"] == "observations_unavailable"
    assert missing["plus_10m"]["temperature_source"] == "persistence"
    assert missing["plus_10m"]["issue"] == "observations_unavailable"
    assert missing["plus_10m"]["history_required_minutes"] == 30
    assert missing["plus_10m"]["history_available_minutes"] == 0
    assert missing["plus_10m"]["rain_probability"] is None
    assert missing["plus_30m"]["rain_probability"] is None
    mqtt.publish.assert_not_called()


def test_station_short_model_can_alert_before_long_history_is_ready(context, monkeypatch):
    from app.services import station_input_forecast

    monkeypatch.setattr(settings, "FORECAST_ENGINE_MODE", "station_inputs")
    for age in range(0, 36, 5):
        context.add("station01", age_minutes=age)
    classifier = Mock()
    classifier.predict_proba.return_value = np.array([[0.1, 0.9]])
    monkeypatch.setattr(station_input_forecast, "load_short_model", Mock(return_value={
        "features": ["temperature"],
        "model": {"temperature": None, "rain": (classifier, Mock(predict=Mock(return_value=[0.9])))},
    }))
    monkeypatch.setattr(station_input_forecast, "load_model", Mock(return_value={"features": [], "models": {}}))
    mqtt = Mock()
    monkeypatch.setattr(app.state, "mqtt_worker", SimpleNamespace(client=mqtt), raising=False)

    forecast = context.client.get("/api/weather/forecast", params={"device_id": "station01"}).json()
    assert forecast["forecast_issue"] == "observations_unavailable"
    assert forecast["plus_10m"]["rain_probability"] == 0.9
    assert forecast["plus_30m"]["rain_probability"] is None
    assert forecast["plus_30m"]["issue"] == "observations_unavailable"
    assert forecast["alert_triggered"] is True
    context.trigger.assert_called_once()
    assert context.trigger.call_args.kwargs["horizon_minutes"] == 10
    assert json.loads(mqtt.publish.call_args.args[1])["threshold_reached"] is True


def test_station_model_does_not_alert_from_stale_measurements(context, monkeypatch):
    monkeypatch.setattr(settings, "FORECAST_ENGINE_MODE", "station_inputs")
    for age in (3, 33, 63):
        context.add("station01", age_minutes=age)
    mqtt = Mock()
    monkeypatch.setattr(app.state, "mqtt_worker", SimpleNamespace(client=mqtt), raising=False)

    forecast = context.client.get("/api/weather/forecast", params={"device_id": "station01"}).json()
    assert forecast["forecast_issue"] == "observations_stale"
    assert all(forecast[h]["issue"] == "observations_stale" for h in HORIZONS)
    assert forecast["alert_triggered"] is False
    context.trigger.assert_not_called()
    mqtt.publish.assert_not_called()


def test_evaluation_scores_completed_forecasts_and_excludes_test_intervals(context):
    for horizon in (10, 30, 60):
        context.db.add(ForecastSnapshot(
            device_id="station01", slot_at=NOW, horizon_minutes=horizon,
            issued_at=NOW, reference_at=NOW, valid_at=NOW + timedelta(minutes=horizon),
            temperature_c=31, baseline_temperature_c=28, rain_probability=0.8, rain_threshold=0.75,
        ))
    for seconds in (-30, -15, 0, 15, 30):
        context.add("station01", age_minutes=-10 - seconds / 60).temperature = 30
    context.add("station01", age_minutes=-5).rain_detected = 1
    context.db.commit()
    endpoints.datetime.now.return_value = NOW + timedelta(minutes=40)
    path = "/api/weather/forecast/evaluation"
    result = context.client.get(path).json()
    short, medium, long = result["horizons"]
    assert short["temperature_mae_c"] == 1
    assert short["baseline_mae_c"] == 2
    assert short["rain_brier"] == 0.04 and short["hits"] == 1
    assert medium["rain_samples"] == 1 and medium["rain_events"] == 1
    assert long["pending"] == 1 and long["rain_samples"] == 0

    # A wet reading is positive evidence. Without it, a gap must not count as dry.
    wet = context.db.query(WeatherMeasurement).filter_by(rain_detected=1).one()
    wet.rain_detected = 0
    context.db.commit()
    assert context.client.get(path).json()["horizons"][0]["rain_samples"] == 0
    test_period = {
        "device_id": "station01",
        "starts_at": (NOW - timedelta(minutes=4)).isoformat(),
        "ends_at": (NOW - timedelta(minutes=3)).isoformat(),
    }
    assert context.client.post(path + "/test-periods", json=test_period).status_code == 200
    assert context.client.post(path + "/test-periods", json=test_period).status_code == 200
    result = context.client.get(path).json()
    assert result["test_periods"] == 1
    assert all(row["excluded"] == 1 and row["temperature_samples"] == 0 for row in result["horizons"])


def test_old_measurements_can_be_viewed_without_actuating_the_station(context, monkeypatch):
    context.add(age_minutes=3)
    mqtt_client = Mock()
    mqtt_client.is_connected.return_value = True
    monkeypatch.setattr(app.state, "mqtt_worker", SimpleNamespace(client=mqtt_client), raising=False)
    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    context.trigger.assert_not_called()
    mqtt_client.publish.assert_not_called()


def test_invalid_latest_measurement_does_not_reach_inference_or_actuation(context):
    context.add().humidity = 125
    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sensor_data_unusable"
    context.predictor.assert_not_called()
    context.trigger.assert_not_called()


@pytest.mark.parametrize("engine_available", [False, True])
@pytest.mark.parametrize("threshold,expected_alert", [(0.18, True), (0.181, False)])
def test_local_fallback_labels_sources_and_uses_inclusive_configured_threshold(
    monkeypatch, engine_available, threshold, expected_alert
):
    monkeypatch.setattr(settings, "FORECAST_ENGINE_MODE", "auto")
    predictor = Mock(side_effect=RuntimeError("engine failed"))
    loader = Mock(return_value=predictor) if engine_available else Mock(side_effect=ImportError("not merged"))
    monkeypatch.setattr(forecast_client, "load_forecast_predictor", loader)
    result = ForecastClient.get_forecast([
        {"device_id": "target", "timestamp": NOW, "temperature": 31.5,
         "humidity": 75, "pressure": 1008, "rain_raw": 750, "rain_detected": 0}
    ], threshold=threshold)
    assert result["device_id"] == "target"
    assert result["alert_triggered"] is expected_alert
    assert (result["alert_message"] is not None) is expected_alert
    for horizon in HORIZONS:
        assert result[horizon]["rain_source"] == "heuristic"
        assert result[horizon]["temperature_source"] == "persistence"
        assert result[horizon]["temperature_c"] == 31.5
    assert max(result[h]["rain_probability"] for h in HORIZONS) == 0.18


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_client_rejects_invalid_threshold(threshold):
    with pytest.raises(ValueError, match="threshold"):
        ForecastClient.get_forecast([{"temperature": 31.5}], threshold=threshold)


def test_client_rejects_empty_input():
    with pytest.raises(ValueError, match="recent_measurements"):
        ForecastClient.get_forecast([])


def test_standalone_does_not_import_or_call_unmerged_engine(context, monkeypatch):
    monkeypatch.setattr(settings, "FORECAST_ENGINE_MODE", "heuristic")
    context.add()
    result = context.client.get('/api/weather/forecast', params={'device_id': 'target'}).json()
    forecast_client.load_forecast_predictor.assert_not_called()
    assert result['forecast_engine'] == 'local_heuristic'
    assert result['fallback_reason'] == 'standalone_mode'


@pytest.mark.parametrize('field,value', [
    ('rain_probability', -0.1), ('rain_probability', 1.01),
    ('rain_probability', float('nan')), ('rain_probability', float('inf')),
    ('rain_probability', True), ('rain_probability', '0.9'),
    ('temperature_c', float('nan')), ('rain_source', 'unknown'), ('rain_level', 'storm'),
])
def test_bad_provider_horizon_is_replaced_before_actuation(context, field, value):
    context.add()
    def invalid(frame, threshold):
        result = context.predictor.side_effect_original(frame, threshold)
        result['plus_30m'][field] = value
        return result
    context.predictor.side_effect_original = context.predictor.side_effect
    context.predictor.side_effect = invalid
    result = context.client.get('/api/weather/forecast', params={'device_id':'target'})
    assert result.status_code == 200
    assert result.json()['fallback_reason'] == 'invalid_engine_output'
    assert result.json()['forecast_engine'] == 'local_heuristic'
    assert result.json()['alert_triggered'] is False
    assert context.trigger.call_args.kwargs['rain_probability'] == 0.18


@pytest.mark.parametrize('mutation', ['wrong_device', 'missing_horizon', 'naive_time', 'bad_current'])
def test_provider_top_level_contract_is_checked(context, mutation):
    context.add()
    original = context.predictor.side_effect
    def invalid(frame, threshold):
        result = original(frame, threshold)
        if mutation == 'wrong_device': result['device_id'] = 'other'
        if mutation == 'missing_horizon': del result['plus_60m']
        if mutation == 'naive_time': result['generated_at'] = '2026-10-27T11:00:00'
        if mutation == 'bad_current': result['current_pressure'] = float('inf')
        return result
    context.predictor.side_effect = invalid
    result = context.client.get('/api/weather/forecast', params={'device_id':'target'})
    assert result.status_code == 200 and result.json()['fallback_reason'] == 'invalid_engine_output'


def test_provider_cannot_override_threshold_decision(context):
    context.add()
    original = context.predictor.side_effect
    def incorrect_flag(frame, threshold):
        result = original(frame, threshold)
        result['alert_triggered'] = True
        return result
    context.predictor.side_effect = incorrect_flag
    result = context.client.get('/api/weather/forecast', params={'device_id':'target'}).json()
    assert result['forecast_engine'] == 'external'
    assert result['alert_triggered'] is False and result['alert_message'] is None
