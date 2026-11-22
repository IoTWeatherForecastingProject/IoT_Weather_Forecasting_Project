"""Apply models trained on public observations to recent IoT measurements."""
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd
from app.config import settings
from app.services.forecast_evaluation import HISTORY_REQUIRED
from app.services.forecast_model import empty_horizon, predict_horizon
from app.services.optional_providers import load_symbol

logger = logging.getLogger(__name__)
MODEL_PATH = Path(__file__).resolve().parents[3] / "ai_engine/saved_models/station_input_forecast.joblib"
SHORT_MODEL_PATH = MODEL_PATH.with_name("station_short_forecast.joblib")
HORIZONS = (10, 30, 60)


@lru_cache(maxsize=1)
def load_model():
    load = load_symbol("joblib", "load")
    artifact = load(MODEL_PATH)
    if (artifact["format"] != 1 or artifact["station"] != "VVTS"
            or artifact.get("runtime_inputs") != "station_temperature_humidity_pressure"
            or not artifact["models"] or not artifact["models"].keys() <= {30, 60}):
        raise ValueError("Invalid station input forecast artifact")
    return artifact


@lru_cache(maxsize=1)
def load_short_model():
    load = load_symbol("joblib", "load")
    artifact = load(SHORT_MODEL_PATH)
    if artifact["format"] != 1 or artifact["source"] != "NEA Singapore":
        raise ValueError("Invalid 10-minute station forecast artifact")
    return artifact


def predict_short(measurements: pd.DataFrame, reference: datetime, latest_temp: float) -> dict:
    valid_at = reference + timedelta(minutes=10)
    fallback = empty_horizon()
    fallback.update(temperature_c=latest_temp, temperature_source="persistence", valid_at=valid_at)
    try:
        artifact = load_short_model()
        build_features = load_symbol("ai_engine.rain_classification.short_station_features", "station_short_features")
        features = build_features(measurements, pd.Timestamp(reference)).loc[:, artifact["features"]]
        if features.isna().any(axis=None):
            return {**fallback, "issue": "observations_unavailable"}
        return predict_horizon(artifact["model"], features, features["temperature"].iloc[0], valid_at)
    except Exception:
        logger.exception("10-minute station forecast failed")
        return {**fallback, "issue": "model_unavailable"}


def add_readiness(result: dict, measurements: list[dict]) -> dict:
    # Use the contiguous tail for the progress indicator. Feature windows decide
    # readiness, and may be usable even when there are gaps between windows.
    latest = previous = measurements[-1]["timestamp"]
    for item in reversed(measurements[:-1]):
        timestamp = item["timestamp"]
        if previous - timestamp > timedelta(seconds=30):
            break
        previous = timestamp
    available = int((latest - previous).total_seconds() // 60)
    for horizon, required in HISTORY_REQUIRED.items():
        point = result[f"plus_{horizon}m"]
        point["history_required_minutes"] = required
        point["history_available_minutes"] = min(available, required)
        if point.get("issue") is None and (
            point["temperature_source"] != "model" or point["rain_source"] != "model"
        ):
            point["issue"] = "model_partial" if point["valid_at"] else result["forecast_issue"] or "model_unavailable"
    return result


def station_input_forecast(measurements: list[dict], now: datetime, threshold: float) -> dict:
    latest = measurements[-1]
    reference = latest["timestamp"]
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    result = {
        "device_id": latest["device_id"], "generated_at": now,
        "current_temperature": latest["temperature"], "current_humidity": latest["humidity"],
        "current_pressure": latest["pressure"], "temperature_model": None,
        "forecast_engine": "station_inputs", "forecast_scope": "station",
        "forecast_reference_at": reference, "forecast_issue": None,
        "rain_alert_threshold": threshold, "alert_triggered": False, "alert_message": None,
        **{f"plus_{h}m": empty_horizon() for h in HORIZONS},
    }
    if now - reference > timedelta(seconds=settings.ALERT_MAX_DATA_AGE_SECONDS):
        result["forecast_issue"] = "observations_stale"
        return add_readiness(result, measurements)
    frame = pd.DataFrame(measurements)
    result["plus_10m"] = predict_short(frame, reference, latest["temperature"])
    if result["plus_10m"]["temperature_source"] == "model":
        result["temperature_model"] = "HistGradientBoosting"
    try:
        artifact = load_model()
        build_features = load_symbol("ai_engine.rain_classification.station_observations", "station_features")
        features = build_features(frame)
        if features is None:
            result["forecast_issue"] = "observations_unavailable"
        else:
            features = features.loc[:, artifact["features"]]
            predictions = {
                f"plus_{horizon}m": predict_horizon(
                    models, features, features["temperature"].iloc[0], reference + timedelta(minutes=horizon),
                )
                for horizon, models in artifact["models"].items()
            }
            result.update(predictions)
            if any(point["temperature_source"] == "model" for point in predictions.values()):
                result["temperature_model"] = "HistGradientBoosting"
    except Exception:
        logger.exception("Station input forecast failed")
        result["forecast_issue"] = "model_unavailable"
    return add_readiness(result, measurements)
