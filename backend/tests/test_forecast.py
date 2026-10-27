"""BE-05 contract tests on an isolated DB; no model artifacts or running services needed."""
from datetime import datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import endpoints
from app.config import settings
from app.db.models import SystemConfig, WeatherMeasurement
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
    Base.metadata.create_all(engine, tables=[WeatherMeasurement.__table__, SystemConfig.__table__])
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
    # 153 samples cover 76 minutes; a count-based 30-row query must fail this test.
    for index in reversed(range(153)):
        context.add(age_minutes=index / 2)
    context.add(age_minutes=76.001)
    context.add(age_minutes=-0.001)
    context.add(device_id="other", age_minutes=1)

    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    result = response.json()
    frame = context.predictor.call_args.args[0]
    assert len(frame) == 153
    assert set(frame["device_id"]) == {"target"}
    assert frame["timestamp"].is_monotonic_increasing
    assert frame["timestamp"].iloc[0].replace(tzinfo=timezone.utc) == NOW - timedelta(minutes=76)
    assert frame["timestamp"].iloc[-1].replace(tzinfo=timezone.utc) == NOW
    assert frame["rain_raw"].eq(750).all()
    assert result["history_measurements"] == 153
    assert result["history_window_minutes"] == 76
    assert result["history_span_minutes"] == 76
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


@pytest.mark.parametrize("age_minutes", [None, 77, -1])
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
    monkeypatch.setattr(app.state, "mqtt_worker", SimpleNamespace(client=mqtt_client), raising=False)
    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    assert context.trigger.call_args.kwargs["mqtt_client"] is mqtt_client


def test_old_measurements_can_be_viewed_without_actuating_the_station(context):
    context.add(age_minutes=3)
    response = context.client.get("/api/weather/forecast", params={"device_id": "target"})
    assert response.status_code == 200
    context.trigger.assert_not_called()


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
