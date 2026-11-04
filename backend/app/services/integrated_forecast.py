"""Combine TV2 temperature artifacts and TV3 per-horizon rain predictions."""
from threading import Lock

import pandas as pd
from app.services.optional_providers import load_symbol

HORIZONS = (10, 30, 60)
_temperature_lock = Lock()


def predict_forecast(recent_data: pd.DataFrame, threshold: float = 0.70) -> dict:
    """Use independent providers so temperature persistence preserves valid rain."""
    if recent_data.empty:
        raise ValueError("recent_data must not be empty")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    if recent_data["device_id"].nunique() != 1:
        raise ValueError("recent_data must contain exactly one station")

    get_engine = load_symbol("ml.inference_engine", "get_engine")
    predict_rain = load_symbol("inference.unified_forecast", "predict_rain_forecast")
    # TV2's singleton keeps mutable coverage diagnostics. HTTP and the monitor
    # run in different threads, so serialize prediction and its model snapshot.
    with _temperature_lock:
        engine = get_engine()
        temperature = engine.predict(recent_data)
        health = engine.health_check()
        available = health["horizons_available"]
    rain = predict_rain(recent_data)
    latest = recent_data.iloc[-1]
    result = temperature.to_backend_response(
        device_id=str(latest["device_id"]),
        current_temperature=float(latest["temperature"]),
        current_humidity=float(latest["humidity"]),
        current_pressure=float(latest["pressure"]),
        rain_probability={h: rain[h]["rain_probability"] for h in HORIZONS},
        alert_threshold=threshold,
    )
    # A loaded engine can still return persistence for short/interrupted history.
    for horizon in HORIZONS:
        result[f"plus_{horizon}m"].update(rain[horizon])
        result[f"plus_{horizon}m"]["temperature_source"] = (
            "model" if temperature.confidence != "fallback" and horizon in available
            else "persistence"
        )
    missing = [str(h) for h in HORIZONS if h not in available]
    model_names = sorted({health["models_loaded"][h] for h in available})
    persistence_only = temperature.confidence == "fallback" or not available
    result.update(
        temperature_model="Persistence" if persistence_only else ",".join(model_names),
        temperature_confidence="fallback" if persistence_only else temperature.confidence,
        temperature_fallback_reason=temperature.error_msg or (
            "missing_temperature_models:" + ",".join(missing) if missing else None
        ),
    )
    return result
