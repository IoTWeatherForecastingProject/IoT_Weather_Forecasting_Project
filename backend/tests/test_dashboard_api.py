from datetime import datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import ReferenceWeather, WeatherMeasurement, SystemConfig
from app.db.session import Base, get_db
from app.main import app
from app.services import analytics

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


@pytest.fixture
def context(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[WeatherMeasurement.__table__, ReferenceWeather.__table__, SystemConfig.__table__])
    db = Session(engine)
    ids = count(1)

    def override():
        yield db

    def add(age_seconds=0, device_id="target", **values):
        row = WeatherMeasurement(**dict(
            {"id": next(ids), "device_id": device_id, "timestamp": NOW - timedelta(seconds=age_seconds),
             "temperature": 32, "humidity": 75, "pressure": 1008, "rain_detected": 0, "rain_raw": 750}, **values))
        db.add(row)
        return row

    def ref(age_seconds=60, source="open-meteo", **values):
        row = ReferenceWeather(**dict(
            {"id": next(ids), "source": source, "timestamp": NOW - timedelta(seconds=age_seconds),
             "lat": 10.85, "lon": 106.78, "temperature": 30, "humidity": 70, "pressure": 1000}, **values))
        db.add(row)

    clock = Mock(wraps=datetime)
    clock.now.return_value = NOW
    monkeypatch.setattr(analytics, "datetime", clock)
    # Stub only the hand-off interface; TV3 algorithms are not tested/imported here.
    detector = SimpleNamespace(analyze=Mock(return_value={'status':'OK', 'anomalies':[]}))
    bias = Mock(return_value=({'reason':'no_overlap', 'metrics':{}, 'meta':{'notes':[]}}, pd.DataFrame()))
    loader = Mock(side_effect=lambda module, symbol: detector if symbol == 'SensorAnomalyDetector' else bias)
    monkeypatch.setattr(analytics, 'load_symbol', loader)
    monkeypatch.setattr(settings, 'ANALYTICS_ENGINE_MODE', 'auto')
    monkeypatch.setitem(app.dependency_overrides, get_db, override)
    yield SimpleNamespace(db=db, add=add, ref=ref, client=TestClient(app), detector=detector, bias=bias, loader=loader)
    db.close()
    engine.dispose()


def test_threshold_read_fallback_update_and_read_back(context, monkeypatch):
    monkeypatch.setattr(settings, "RAIN_ALERT_THRESHOLD", 0.72)
    assert context.client.get("/api/weather/alerts/threshold").json() == {"threshold": 0.72, "source": "default", "updated_at": None}
    assert context.client.post("/api/weather/alerts/threshold", json={"threshold": 0.65}).status_code == 200
    saved = context.client.get("/api/weather/alerts/threshold").json()
    assert saved["threshold"] == 0.65 and saved["source"] == "db" and saved["updated_at"]


@pytest.mark.parametrize("value", ["invalid", "NaN", "Infinity", "1.5", "-0.1"])
def test_invalid_threshold_uses_shared_default(context, monkeypatch, value):
    from app.services.rain_threshold import resolve_rain_threshold
    monkeypatch.setattr(settings, "RAIN_ALERT_THRESHOLD", 0.85)
    context.db.add(SystemConfig(config_key="rain_alert_threshold", config_value=value))
    context.db.commit()
    response = context.client.get("/api/weather/alerts/threshold")
    assert response.status_code == 200
    assert response.json() == {"threshold": 0.85, "source": "default", "updated_at": None}
    assert resolve_rain_threshold(context.db) == (0.85, "default", None)


def test_no_duplicate_api_handlers():
    from app.api.endpoints import router
    from collections import Counter
    counts = Counter((route.path, tuple(sorted(route.methods))) for route in router.routes)
    assert all(count == 1 for count in counts.values())


def test_health_empty_is_unknown(context):
    response = context.client.get("/api/weather/sensor-health", params={"device_id": "target"})
    assert response.status_code == 200
    assert response.json()["status"] == "UNKNOWN"
    assert response.json()["reason"] == "no_data"
    assert response.json()["anomalies"] == []


def test_health_preserves_anomalies_and_filters_station_and_future(context):
    context.add(humidity=125)
    context.add(age_seconds=-10)
    context.add(device_id="other")
    context.detector.analyze.return_value = {'status':'FAULT', 'anomalies':[{'type':'OUT_OF_RANGE', 'sensor':'humidity', 'message':'test provider anomaly'}]}
    result = context.client.get("/api/weather/sensor-health", params={"device_id": "target"}).json()
    assert result["status"] == "FAULT"
    assert any(a["type"] == "OUT_OF_RANGE" and a["sensor"] == "humidity" for a in result["anomalies"])
    assert result["checked_at"].endswith("+00:00")
    assert len(context.detector.analyze.call_args.args[0]) == 1


def test_health_stale_is_unknown(context):
    context.add(age_seconds=121)
    result = context.client.get("/api/weather/sensor-health", params={"device_id": "target"}).json()
    assert result["status"] == "UNKNOWN" and result["reason"] == "stale_data"


def test_benchmark_empty_does_not_make_up_reference(context):
    response = context.client.get("/api/weather/benchmark", params={"device_id": "target"})
    assert response.status_code == 200
    assert response.json()["reference"] == []
    assert response.json()["latest_bias"] is None


def test_benchmark_matched_bias_uses_only_selected_source_and_device(context):
    for age in (120, 60, 0):
        context.add(age_seconds=age)
    context.add(device_id="other", temperature=55)
    context.ref()
    context.ref(source="openweather", temperature=10)
    context.ref(age_seconds=-10, temperature=10)
    context.bias.return_value = ({'metrics':{'temperature':{'mbe':2}}, 'meta':{'notes':[]}}, pd.DataFrame([{
        'timestamp':NOW-timedelta(seconds=60), 'n_iot':3,
        'iot_temperature':32, 'ref_temperature':30, 'iot_humidity':75, 'ref_humidity':70,
        'iot_pressure':1008, 'ref_pressure':1000,
    }]))
    result = context.client.get("/api/weather/benchmark", params={"device_id": "target"}).json()
    assert len(result["reference"]) == 1
    assert result["reason"] == "matched"
    assert result["latest_bias"]["temp_bias_c"] == 2
    assert result["latest_bias"]["humidity_bias_pct"] == 5
    assert result["latest_bias"]["pressure_bias_hpa"] == 8
    assert result["metrics"]["temperature"]["mbe"] == 2
    iot, reference, device, source = context.bias.call_args.args
    assert len(iot) == 3 and len(reference) == 1 and device == 'target' and source == 'open-meteo'


def test_benchmark_insufficient_pairs_returns_null_bias(context):
    context.add()
    context.ref()
    result = context.client.get("/api/weather/benchmark", params={"device_id": "target"}).json()
    assert len(result["reference"]) == 1 and result["latest_bias"] is None
    assert result["reason"] == "no_overlap"


@pytest.mark.parametrize("path,params", [
    ("sensor-health", {"window_minutes": 0}), ("sensor-health", {"window_minutes": 1441}),
    ("benchmark", {"hours": 0}), ("benchmark", {"source": "arbitrary"}),
])
def test_analytics_rejects_invalid_query(context, path, params):
    assert context.client.get(f"/api/weather/{path}", params=params).status_code == 422


def test_disabled_analytics_preserves_reference_without_claiming_analysis(context, monkeypatch):
    monkeypatch.setattr(settings, 'ANALYTICS_ENGINE_MODE', 'disabled')
    context.add()
    context.ref()
    health = context.client.get('/api/weather/sensor-health', params={'device_id':'target'}).json()
    bias = context.client.get('/api/weather/benchmark', params={'device_id':'target'}).json()
    assert health['status'] == 'UNKNOWN' and health['reason'] == 'analytics_not_integrated'
    assert bias['reason'] == 'analytics_not_integrated' and len(bias['reference']) == 1
    assert bias['latest_bias'] is None and bias['metrics'] == {}
    context.loader.assert_not_called()


@pytest.mark.parametrize('error,reason', [(ImportError('not merged'),'analytics_unavailable'), (RuntimeError('provider failed'),'analytics_failed')])
def test_missing_or_failed_provider_does_not_break_api(context, error, reason):
    context.add()
    context.ref()
    context.loader.side_effect = error
    health = context.client.get('/api/weather/sensor-health', params={'device_id':'target'})
    benchmark = context.client.get('/api/weather/benchmark', params={'device_id':'target'})
    assert health.status_code == benchmark.status_code == 200
    assert health.json()['status'] == 'UNKNOWN' and health.json()['reason'] == reason
    assert benchmark.json()['latest_bias'] is None and benchmark.json()['reason'] == reason


def test_malformed_analytics_does_not_report_sensor_ok(context):
    context.add()
    context.detector.analyze.return_value = {'status':'OK', 'anomalies':float('nan')}
    result = context.client.get('/api/weather/sensor-health', params={'device_id':'target'}).json()
    assert result['status'] == 'UNKNOWN' and result['reason'] == 'analytics_failed'


def test_integration_status_does_not_probe_unmerged_code(context, monkeypatch):
    monkeypatch.setattr(settings,'FORECAST_ENGINE_MODE','heuristic')
    monkeypatch.setattr(settings,'ANALYTICS_ENGINE_MODE','disabled')
    result = context.client.get('/api/weather/integrations').json()
    assert result['forecast']['status'] == 'local_heuristic'
    assert result['analytics']['status'] == 'not_integrated'
    context.loader.assert_not_called()
