"""Shared feature definitions for forecasts driven by station measurements."""
import numpy as np
import pandas as pd

SENSORS = ["temperature", "humidity", "pressure"]


def observation_features(current: pd.DataFrame, half_hour: pd.DataFrame, hour: pd.DataFrame) -> pd.DataFrame:
    features = current[["temperature", "humidity"]].copy()
    for name in SENSORS:
        # The station measures local pressure, while VVTS publishes QNH.
        # Use changes rather than substituting one absolute reference for the other.
        features[f"{name}_change_30m"] = current[name] - half_hour[name]
        features[f"{name}_change_60m"] = current[name] - hour[name]
    local = current.index.tz_convert("Asia/Ho_Chi_Minh")
    hours = local.hour + local.minute / 60
    features["local_hour_sin"] = np.sin(hours * np.pi / 12)
    features["local_hour_cos"] = np.cos(hours * np.pi / 12)
    return features


def station_features(measurements: pd.DataFrame) -> pd.DataFrame | None:
    """Build one row from measured samples near the current, -30 and -60m anchors."""
    frame = measurements[SENSORS].copy()
    frame.index = pd.to_datetime(measurements["timestamp"], utc=True, format="mixed")
    reference = frame.index.max()
    windows = []
    for minutes in (0, 30, 60):
        end = reference - pd.Timedelta(minutes=minutes)
        samples = frame.loc[(frame.index > end - pd.Timedelta(minutes=5)) & (frame.index <= end)]
        if samples.empty:
            return None
        windows.append(pd.DataFrame([samples.median()], index=pd.DatetimeIndex([reference])))
    return observation_features(*windows)
