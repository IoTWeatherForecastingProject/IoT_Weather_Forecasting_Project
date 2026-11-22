"""Inputs shared by the 10-minute training and station inference paths."""
import pandas as pd

COLUMNS = ["temperature", "humidity"]
LOOKBACKS = (5, 10, 30)


def short_features(grid: pd.DataFrame) -> pd.DataFrame:
    result = grid[COLUMNS].copy()
    for minutes in LOOKBACKS:
        for sensor in COLUMNS:
            result[f"{sensor}_change_{minutes}m"] = grid[sensor].diff(minutes // 5)
    return result


def station_short_features(measurements: pd.DataFrame, reference: pd.Timestamp) -> pd.DataFrame:
    samples = measurements.set_index(pd.to_datetime(measurements["timestamp"], utc=True, format="mixed"))
    anchors = pd.date_range(end=reference, periods=max(LOOKBACKS) // 5 + 1, freq="5min")
    grid = pd.DataFrame(
        [samples.loc[(samples.index > at - pd.Timedelta(minutes=5)) & (samples.index <= at), COLUMNS].median()
         for at in anchors],
        index=anchors,
    )
    return short_features(grid).iloc[[-1]]
