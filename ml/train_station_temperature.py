"""Train a temperature model for a station that does not report analog rain."""
import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml.feature_engineering import TemperatureFeatureEngineer
from ml.inference_engine import HORIZONS

FEATURES = [
    "temperature", "T_roll_mean_6m", "T_roll_mean_30m", "dT_5min",
    "humidity", "pressure", "dhumidity_1min", "dpressure_1min",
]


def train(data: pd.DataFrame, test_start: pd.Timestamp):
    """Compare Ridge to persistence on later measured temperatures."""
    if "device_id" in data and data["device_id"].nunique() != 1:
        raise ValueError("Supply observations from one station.")
    timestamp = pd.to_datetime(data["timestamp"], utc=True)
    readings = data[["temperature", "humidity", "pressure"]].apply(pd.to_numeric)
    readings.index = timestamp
    grid = readings.sort_index().resample("1min").mean()
    features = TemperatureFeatureEngineer().transform_features(grid)[FEATURES]

    models, metrics = {}, {}
    for horizon in HORIZONS:
        # Use measured targets and keep training targets before the test boundary.
        target = grid["temperature"].shift(-horizon).rename("target")
        pairs = features.join(target).dropna()
        train_set = pairs[pairs.index + pd.Timedelta(minutes=horizon) < test_start]
        test_set = pairs[pairs.index >= test_start]
        metrics[horizon] = {"train_rows": len(train_set), "test_rows": len(test_set)}
        if train_set.empty or test_set.empty:
            metrics[horizon]["status"] = "insufficient_data"
            continue
        model = make_pipeline(StandardScaler(), Ridge(alpha=10))
        model.fit(train_set[FEATURES], train_set["target"])
        model_mae = mean_absolute_error(test_set["target"], model.predict(test_set[FEATURES]))
        baseline_mae = mean_absolute_error(test_set["target"], test_set["temperature"])
        metrics[horizon].update(model_mae=model_mae, persistence_mae=baseline_mae)
        if model_mae < baseline_mae:
            models[horizon] = model
    return models, metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path, help="CSV with real station readings; exclude hardware tests")
    parser.add_argument("--test-start", required=True, help="ISO timestamp with timezone for the held-out data")
    parser.add_argument("--candidate-dir", type=Path, help="New directory for candidates that beat persistence")
    args = parser.parse_args()
    test_start = pd.Timestamp(args.test_start)
    if test_start.tzinfo is None:
        parser.error("--test-start must have a timezone")

    models, metrics = train(pd.read_csv(args.data), test_start.tz_convert("UTC"))
    print(json.dumps({"metrics": metrics, "candidate_horizons": list(models)}, indent=2))
    if models and args.candidate_dir:
        args.candidate_dir.mkdir(parents=True, exist_ok=False)
        (args.candidate_dir / "feature_schema.json").write_text(
            json.dumps({"feature_names": FEATURES, "horizons": list(models)}, indent=2) + "\n",
            encoding="utf-8",
        )
        for horizon, model in models.items():
            joblib.dump(model, args.candidate_dir / f"Ridge_h{horizon}min.joblib")


if __name__ == "__main__":
    main()
