"""Read Tân Sơn Nhất forecasts independently of the IoT measurement history."""
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import monotonic

import httpx
import pandas as pd
from app.services.forecast_model import empty_horizon, predict_horizon
from app.services.optional_providers import load_symbol

logger = logging.getLogger(__name__)
METAR_URL = "https://aviationweather.gov/api/data/metar"
MODEL_PATH = Path(__file__).resolve().parents[3] / "ai_engine/saved_models/vvts_forecast.joblib"
MAX_OBSERVATION_AGE = timedelta(minutes=45)
REFRESH_SECONDS = 90
_lock = Lock()
_next_fetch = 0.0
_observations = pd.DataFrame(columns=["station", "valid", "metar"])


@lru_cache(maxsize=1)
def load_model():
    load = load_symbol("joblib", "load")
    artifact = load(MODEL_PATH)
    if artifact["format"] != 1 or artifact["station"] != "VVTS" or not artifact["models"]:
        raise ValueError("Invalid VVTS forecast artifact")
    return artifact


def read_observations() -> pd.DataFrame:
    global _observations, _next_fetch
    with _lock:
        if monotonic() < _next_fetch:
            return _observations
        _next_fetch = monotonic() + REFRESH_SECONDS
        try:
            response = httpx.get(
                METAR_URL, params={"ids": "VVTS", "format": "json", "hours": 4},
                headers={"User-Agent": "IoTWeatherForecastingProject/1.0"},
                timeout=5.0,
            )
            response.raise_for_status()
            columns = ["station", "valid", "metar"]
            rows = [
                (row["icaoId"], datetime.fromtimestamp(row["obsTime"], timezone.utc), row["rawOb"])
                for row in response.json()
                if row.get("icaoId") == "VVTS" and row.get("obsTime") is not None and row.get("rawOb")
            ]
            if rows:
                _observations = pd.DataFrame(rows, columns=columns)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            logger.warning("Unable to refresh VVTS observations: %s", exc)
        return _observations


def regional_forecast(device_id: str, now: datetime, threshold: float) -> dict:
    result = {
        "device_id": device_id, "generated_at": now,
        "current_temperature": None, "current_humidity": None, "current_pressure": None,
        "temperature_model": None, "forecast_engine": "regional_vvts", "forecast_scope": "VVTS",
        "forecast_reference_at": None, "forecast_issue": None,
        "history_window_minutes": 240, "history_span_minutes": 0, "history_measurements": 0,
        "rain_alert_threshold": threshold, "alert_triggered": False,
        "alert_message": None,
        **{f"plus_{h}m": empty_horizon() for h in (10, 30, 60)},
    }
    try:
        artifact = load_model()
        build_features = load_symbol("ai_engine.rain_classification.vvts_observations", "build_features")
    except Exception:
        logger.exception("Unable to load VVTS forecast model")
        return {**result, "forecast_issue": "model_unavailable"}

    observations = read_observations()
    observations = observations.loc[observations["valid"].le(now)]
    features = build_features(observations)
    if features.empty:
        return {**result, "forecast_issue": "observations_unavailable"}
    reference = features.index[-1].to_pydatetime()
    latest = features.iloc[-1]
    result["forecast_reference_at"] = reference
    if now - reference > MAX_OBSERVATION_AGE:
        return {**result, "forecast_issue": "observations_stale"}
    if latest[artifact["features"]].isna().any():
        return {**result, "forecast_issue": "observations_unavailable"}
    result.update(current_temperature=float(latest["temperature"]), current_pressure=float(latest["qnh"]),
                  history_span_minutes=60, history_measurements=3)
    features_now = features.iloc[[-1]][artifact["features"]]
    try:
        for horizon, models in artifact["models"].items():
            valid_at = reference + timedelta(minutes=horizon)
            if valid_at <= now:
                continue
            point = predict_horizon(models, features_now, latest["temperature"], valid_at)
            result[f"plus_{horizon}m"] = point
            if point["temperature_source"] == "model":
                result["temperature_model"] = "VVTS HistGradientBoosting"
    except Exception:
        logger.exception("VVTS prediction failed")
        return {**result, "forecast_issue": "model_unavailable",
                **{f"plus_{h}m": empty_horizon() for h in (10, 30, 60)}}
    return result
