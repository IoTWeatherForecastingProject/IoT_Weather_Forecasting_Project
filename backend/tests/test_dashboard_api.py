from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
import re
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


def test_rain_history_groups_by_vietnam_date_and_preserves_gaps(context, monkeypatch):
    from app.api import endpoints
    from app.services import rain_history as service

    # The two wet periods begin on opposite sides of midnight in Vietnam.
    midnight = datetime(2026, 10, 26, 17, tzinfo=timezone.utc)
    monkeypatch.setattr(endpoints, "rain_history", lambda db, device: service.rain_history(db, device, NOW))
    for base, samples in [
        (midnight, [(-15, 0, 29), (-10, 1, 30.2), (0, 1, 32), (5, 0, 31),
                    (10, 1, 31.5), (60, 1, 33), (65, 0, 32)]),
        (midnight - timedelta(days=7), [(10, 1, 20)]),
    ]:
        for seconds, wet, temperature in samples:
            age = (NOW - (base + timedelta(seconds=seconds))).total_seconds()
            context.add(age, rain_detected=wet, temperature=temperature)
    context.add(device_id="other", rain_detected=1)
    context.add(-1, rain_detected=1)
    context.db.commit()

    response = context.client.get("/api/weather/rain-history", params={"device_id": "target"})
    assert response.status_code == 200
    result = response.json()
    assert result["has_readings"] is True
    newer, older = result["days"]
    assert (newer["date"], older["date"]) == ("2026-10-27", "2026-10-26")
    assert [event["status"] for event in newer["events"]] == ["dry", "unknown_end"]
    assert newer["events"][0]["confirmed_start"] is False
    assert newer["events"][1]["dry_at"] is None
    first = older["events"][0]
    assert first["temperature"] == 30.2
    assert first["confirmed_start"] is True
    assert first["dry_at"].startswith("2026-10-26T17:00:05")


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


@pytest.mark.integrated_model
def test_live_crawler_records_are_visible_to_dashboard(context, monkeypatch):
    """Exercise the crawler -> DB -> actual dashboard source -> API contract."""
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root))
    from ai_engine.openweather_benchmark import crawler

    payload = {"current": {
        "time": "2026-10-27T11:45", "temperature_2m": 30.5,
        "relative_humidity_2m": 72, "surface_pressure": 1008.5, "precipitation": 0,
    }}
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(crawler.requests, "get", Mock(return_value=response))
    record, = crawler.WeatherBenchmarkCrawler().fetch_open_meteo_current()
    context.db.add(ReferenceWeather(
        id=1000, source=record.source, timestamp=record.timestamp,
        lat=record.lat, lon=record.lon, temperature=record.temperature,
        humidity=record.humidity, pressure=record.pressure,
        precipitation=record.precipitation,
    ))
    context.db.flush()
    dashboard = (root / "dashboard/js/app.js").read_text(encoding="utf-8")
    source = re.search(r'REF_SOURCE:\s*"([^"]+)"', dashboard).group(1)

    result = context.client.get("/api/weather/benchmark", params={"source": source})

    assert result.status_code == 200
    assert result.json()["source"] == record.source
    assert len(result.json()["reference"]) == 1
    assert result.json()["reference"][0]["temperature"] == 30.5


@pytest.mark.parametrize("source,temperature", [
    ("open-meteo", 30), ("open-meteo-15min", 31), ("openweather", 32),
])
def test_benchmark_preserves_separate_hourly_live_and_openweather_sources(context, source, temperature):
    # Identical timestamps must not mix hourly backfill with live observations.
    for name, value in (("open-meteo", 30), ("open-meteo-15min", 31), ("openweather", 32)):
        context.ref(source=name, temperature=value)
    result = context.client.get("/api/weather/benchmark", params={"source": source})
    assert result.status_code == 200
    assert [point["temperature"] for point in result.json()["reference"]] == [temperature]
    # Keep the existing API default for clients consuming hourly backfill.
    default = context.client.get("/api/weather/benchmark").json()
    assert default["source"] == "open-meteo"
    assert [point["temperature"] for point in default["reference"]] == [30]


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
