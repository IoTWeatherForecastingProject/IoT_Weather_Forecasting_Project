"""Regression checks using the delivered TV2 artifacts, not an accepted fallback.

Run with backend/requirements-inference.txt installed. The default standalone
suite can collect these tests without importing optional model dependencies.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pandas as pd
import pytest
from app.api import endpoints
from app.config import settings
from app.db.models import SystemConfig, WeatherMeasurement
from app.db.session import Base, get_db
from app.main import app
from app.services.alert_service import AlertService
from app.services.optional_providers import load_symbol
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.integrated_model
NOW = datetime(2026, 11, 4, 6, tzinfo=timezone.utc)
HORIZONS = (10, 30, 60)


@pytest.fixture
def model_runtime(monkeypatch):
    pytest.importorskip("xgboost", reason="Install requirements-inference.txt")
    get_engine = load_symbol("ml.inference_engine", "get_engine")
    engine = get_engine()
    # A missing/unreadable artifact must fail this regression, not become a pass.
    assert engine.health_check()["horizons_available"] == list(HORIZONS)
    rain_module = __import__("inference.unified_forecast", fromlist=["predict_rain_forecast"])
    # Exercise the real TV3 boundary with independent per-horizon availability.
    monkeypatch.setattr(rain_module, "_rain_model_probs", lambda frame: {
        10: (0.81, None), 30: (None, "missing horizon"), 60: (0.92, None),
    })
    return engine, rain_module


@pytest.fixture
def context(monkeypatch, model_runtime):
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine, tables=[WeatherMeasurement.__table__, SystemConfig.__table__])
    db = Session(db_engine)

    def seed(minutes=121, step_seconds=5, reconnect=False):
        count = int(minutes * 60 / step_seconds)
        rows = []
        for index in range(count + 1):
            age = (count - index) * step_seconds
            if reconnect and 10 * 60 < age < 70 * 60:
                continue
            values = {
                "id": index + 1, "device_id": "model-test", "timestamp": NOW - timedelta(seconds=age),
                "temperature": 30 + index / max(count, 1), "humidity": 75 + index / max(count, 1),
                "pressure": 1008 - index / max(count, 1), "rain_raw": 800, "rain_detected": 0,
            }
            db.add(WeatherMeasurement(**values))
            rows.append(values)
        db.commit()
        return rows

    def override_db():
        yield db

    clock = Mock(wraps=datetime)
    clock.now.return_value = NOW
    monkeypatch.setattr(endpoints, "datetime", clock)
    monkeypatch.setattr(settings, "FORECAST_ENGINE_MODE", "auto")
    monkeypatch.setattr(settings, "RAIN_ALERT_THRESHOLD", 0.90)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    trigger = Mock(return_value=False)
    monkeypatch.setattr(AlertService, "evaluate_and_trigger", trigger)
    yield seed, TestClient(app), trigger
    db.close()
    db_engine.dispose()


def test_api_runs_real_models_with_5_second_history(context, model_runtime, monkeypatch):
    seed, client, trigger = context
    engine, _ = model_runtime
    seed()
    original_predict = engine.predict
    predict = Mock(wraps=original_predict)
    monkeypatch.setattr(engine, "predict", predict)
    response = client.get("/api/weather/forecast", params={"device_id": "model-test"})
    assert response.status_code == 200
    result = response.json()
    assert result["forecast_engine"] == "external"
    assert result["temperature_model"] == "XGBoost"
    assert result["temperature_confidence"] == "normal"
    assert result["temperature_fallback_reason"] is None
    assert result["history_window_minutes"] == 120
    assert result["history_span_minutes"] == 120
    frame = predict.call_args.args[0]
    assert len(frame) == 1441
    expected = original_predict(frame)
    for horizon in HORIZONS:
        assert result[f"plus_{horizon}m"]["temperature_source"] == "model"
        assert result[f"plus_{horizon}m"]["temperature_c"] == round(getattr(expected, f"t_plus_{horizon}min"), 2)
    assert [result[f"plus_{h}m"]["rain_source"] for h in HORIZONS] == ["model", "heuristic", "model"]
    assert result["plus_60m"]["rain_probability"] == 0.92
    assert result["rain_alert_threshold"] == 0.90 and result["alert_triggered"] is True
    assert trigger.call_args.kwargs["horizon_minutes"] == 60
    assert trigger.call_args.kwargs["threshold"] == 0.90


@pytest.mark.parametrize("kwargs", [
    {"minutes": 7.5},  # 91 rows at 5s are not 90 minutes.
    {"minutes": 121, "reconnect": True},  # Enough total span, but recent lags unavailable.
])
def test_temperature_persistence_keeps_valid_rain_and_exposes_reason(context, kwargs):
    seed, client, _ = context
    seed(**kwargs)
    response = client.get("/api/weather/forecast", params={"device_id": "model-test"})
    assert response.status_code == 200
    result = response.json()
    assert result["forecast_engine"] == "external"
    assert result["temperature_confidence"] == "fallback"
    assert result["temperature_model"] == "Persistence"
    assert result["temperature_fallback_reason"]
    for horizon in HORIZONS:
        assert result[f"plus_{horizon}m"]["temperature_source"] == "persistence"
        assert result[f"plus_{horizon}m"]["temperature_c"] == result["current_temperature"]
    assert result["plus_60m"]["rain_source"] == "model"
    assert result["plus_60m"]["rain_probability"] == 0.92


def test_rain_only_boundary_never_loads_legacy_temperature(model_runtime, monkeypatch, tmp_path):
    _, rain_module = model_runtime
    legacy = tmp_path / "legacy.joblib"
    legacy.write_bytes(b"obsolete artifact must not be read")
    monkeypatch.setattr(rain_module, "TEMP_MODEL_PATH", legacy)
    monkeypatch.setattr(rain_module, "_temp_payload", None)
    monkeypatch.setattr(rain_module, "RAIN_MODEL_PATH", tmp_path / "missing-rain.joblib")
    monkeypatch.setattr(rain_module, "_rain_payload", None)
    load = Mock(side_effect=AssertionError("legacy temperature artifact was loaded"))
    monkeypatch.setattr(rain_module.joblib, "load", load)
    frame = pd.DataFrame([
        {"device_id": "model-test", "timestamp": NOW, "temperature": 31, "humidity": 75, "pressure": 1008},
    ])
    rain = rain_module.predict_rain_forecast(frame)
    assert rain[60]["rain_probability"] == 0.92
    load.assert_not_called()


@pytest.mark.parametrize("missing", [(10,), (30,), HORIZONS])
def test_partial_temperature_artifacts_have_truthful_metadata(context, model_runtime, monkeypatch, missing):
    seed, client, _ = context
    engine, _ = model_runtime
    seed(step_seconds=60)
    monkeypatch.setattr(engine, "_models", {h: model for h, model in engine._models.items() if h not in missing})
    monkeypatch.setattr(engine, "_model_names", {h: name for h, name in engine._model_names.items() if h not in missing})
    result = client.get("/api/weather/forecast", params={"device_id": "model-test"}).json()
    for horizon in HORIZONS:
        assert result[f"plus_{horizon}m"]["temperature_source"] == (
            "persistence" if horizon in missing else "model"
        )
    assert result["temperature_model"] == ("Persistence" if missing == HORIZONS else "XGBoost")
    assert result["temperature_confidence"] == ("fallback" if missing == HORIZONS else "degraded")
    assert result["temperature_fallback_reason"] == "missing_temperature_models:" + ",".join(map(str, missing))
    assert result["plus_60m"]["rain_source"] == "model"
