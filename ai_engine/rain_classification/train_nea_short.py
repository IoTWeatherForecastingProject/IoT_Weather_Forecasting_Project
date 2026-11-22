"""Fit +10 minute forecasts from Singapore NEA gauges and collocated sensors."""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestClassifier
from sklearn.metrics import mean_absolute_error

from .calibration import SigmoidCalibrator
from .evaluation import probabilistic_metrics
from .features import make_future_rain_labels
from .short_station_features import COLUMNS, short_features

HOLDOUT_STATIONS = {"S24", "S104", "S107"}


def build_dataset(data):
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data.sort_values("timestamp").set_index("timestamp")
    data["temperature"] = data["temperature"].where(data["temperature"].between(15, 45))
    data["humidity"] = data["humidity"].where(data["humidity"].between(0, 100))
    batches = []
    days = data.index.tz_convert("Asia/Singapore").normalize()
    for (station, _), block in data.groupby(["station_id", days]):
        grid = block[COLUMNS].resample("5min", closed="right", label="right").median()
        rain = block.loc[block.index == block.index.floor("5min"), "rain_mm"].reindex(grid.index)
        rain = rain.gt(0).astype(float).where(rain.notna() & (rain >= 0))
        rain_target = make_future_rain_labels(rain, 10, "5min")
        batches.append(short_features(grid).assign(
            station_id=station, rain_now=rain, rain_target=rain_target,
            temperature_target=grid["temperature"].shift(-2),
        ))
    return pd.concat(batches)


def fit(data):
    features = [col for col in data if col not in ("station_id", "rain_now", "rain_target", "temperature_target")]
    time = data.index.tz_convert("Asia/Singapore")
    held_out = data.station_id.isin(HOLDOUT_STATIONS)
    train = data.loc[(time.year == 2022) & ~held_out].dropna(subset=features)
    cal = data.loc[(time.year == 2023) & (time.month <= 6) & ~held_out].dropna(subset=features)
    test = data.loc[(time.year == 2023) & (time.month >= 7) & held_out].dropna(subset=features)

    train_rain, cal_rain, test_rain = [d.dropna(subset=["rain_now", "rain_target"]) for d in (train, cal, test)]
    if not all(d["rain_target"].nunique() == 2 for d in (train_rain, cal_rain, test_rain)):
        raise ValueError("Rain and dry labels required in all data splits")
    classifier = RandomForestClassifier(n_estimators=160, max_depth=7, min_samples_leaf=20, random_state=42, n_jobs=1)
    classifier.fit(train_rain[features], train_rain.rain_target)
    calibration = SigmoidCalibrator().fit(classifier.predict_proba(cal_rain[features])[:, 1], cal_rain.rain_target)
    prediction = calibration.predict(classifier.predict_proba(test_rain[features])[:, 1])
    dry = test_rain.rain_now.eq(0)
    onset_base = train_rain.loc[train_rain.rain_now.eq(0), "rain_target"].mean()
    baseline = np.full(len(test_rain), train_rain.rain_target.mean())
    rain_model = probabilistic_metrics(test_rain.rain_target, prediction)
    rain_baseline = probabilistic_metrics(test_rain.rain_target, baseline)
    dry_model = probabilistic_metrics(test_rain.loc[dry, "rain_target"], prediction[dry])
    dry_baseline = probabilistic_metrics(test_rain.loc[dry, "rain_target"], np.full(int(dry.sum()), onset_base))
    qualified = rain_model["brier"] < rain_baseline["brier"] and dry_model["brier"] < dry_baseline["brier"]

    train_temp, test_temp = (d.dropna(subset=["temperature_target"]) for d in (train, test))
    regressor = HistGradientBoostingRegressor(
        loss="absolute_error", max_iter=100, max_leaf_nodes=12, min_samples_leaf=40, random_state=42,
    )
    regressor.fit(train_temp[features], train_temp.temperature_target - train_temp.temperature)
    temperature = test_temp.temperature + regressor.predict(test_temp[features])
    mae = mean_absolute_error(test_temp.temperature_target, temperature)
    persistence_mae = mean_absolute_error(test_temp.temperature_target, test_temp.temperature)
    artifact = {"format": 1, "source": "NEA Singapore", "features": features, "model": {
        "temperature": regressor if mae < persistence_mae else None,
        "rain": (classifier, calibration) if qualified else None,
    }}
    report = {
        "source": "NEA Singapore 5-minute rain gauge readings and collocated 1-minute temperature and humidity",
        "training": "2022, excluding holdout stations",
        "calibration": "January–June 2023, excluding holdout stations",
        "test": "July–December 2023, holdout stations only",
        "holdout_stations": sorted(test.station_id.unique()),
        "rain_training_rows": len(train_rain), "rain_calibration_rows": len(cal_rain),
        "rain_test_rows": len(test_rain), "rain_test_positive": int(test_rain.rain_target.sum()),
        "rain_test_model": rain_model, "rain_test_baseline": rain_baseline,
        "rain_test_dry_model": dry_model, "rain_test_dry_baseline": dry_baseline,
        "rain_qualified": bool(qualified),
        "temperature_test_rows": len(test_temp), "temperature_mae": mae, "temperature_persistence_mae": persistence_mae,
    }
    return artifact, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--model-out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    artifact, report = fit(build_dataset(pd.read_csv(args.csv)))
    report["data_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    joblib.dump(artifact, args.model_out, compress=3)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
