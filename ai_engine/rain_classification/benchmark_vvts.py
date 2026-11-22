"""Train Tân Sơn Nhất forecasts and score them on later METAR observations."""
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
from .evaluation import assign_split, probabilistic_metrics
from .features import make_future_rain_labels
from .station_observations import observation_features
from .vvts_observations import FREQ, build_features


def train_models(data: pd.DataFrame, calibration_start: pd.Timestamp, test_start: pd.Timestamp,
                 *, station_inputs: bool = False):
    features = build_features(data)
    if station_inputs:
        humidity = data.loc[data["station"].eq("VVTS"), ["valid", "relh"]].copy()
        humidity.index = pd.to_datetime(humidity["valid"], utc=True)
        humidity = humidity.loc[~humidity.index.duplicated(keep="last"), "relh"]
        humidity = pd.to_numeric(humidity, errors="coerce").reindex(features.index)
        sensors = features[["temperature", "qnh"]].rename(columns={"qnh": "pressure"})
        sensors["humidity"] = humidity.where(humidity.between(0, 100))
        inputs = observation_features(sensors, sensors.shift(), sensors.shift(2))
    else:
        inputs = features
    cols = inputs.columns.tolist()
    results, models = {}, {}
    for horizon in (30, 60):
        target = make_future_rain_labels(features["rain_now"], horizon, FREQ).rename("target")
        samples = inputs.assign(observed_rain=features["rain_now"]).join(target).dropna()
        split = assign_split(samples.index, calibration_start, test_start, horizon)
        train, calibration, test = (samples[split == name] for name in ("train", "calibration", "test"))
        for name, group in (("train", train), ("calibration", calibration), ("test", test)):
            if group["target"].nunique() != 2:
                raise ValueError(f"+{horizon} min requires rain and dry cases in {name}")
        model = RandomForestClassifier(
            n_estimators=200, max_depth=6, min_samples_leaf=15, random_state=42, n_jobs=1,
        )
        model.fit(train[cols], train["target"])
        p_cal = model.predict_proba(calibration[cols])[:, 1]
        calibrator = SigmoidCalibrator().fit(p_cal, calibration["target"].to_numpy())
        p_test = calibrator.predict(model.predict_proba(test[cols])[:, 1])
        dry = test["observed_rain"].eq(0).to_numpy()
        onset_climatology = train.loc[train["observed_rain"].eq(0), "target"].mean()
        metrics = {
            "model": probabilistic_metrics(test["target"].to_numpy(), p_test),
            "climatology": probabilistic_metrics(test["target"].to_numpy(), np.full(len(test), train["target"].mean())),
            "persistence": probabilistic_metrics(test["target"].to_numpy(), test["observed_rain"].to_numpy()),
            "model_when_dry": probabilistic_metrics(test["target"].to_numpy()[dry], p_test[dry]),
            "climatology_when_dry": probabilistic_metrics(
                test["target"].to_numpy()[dry], np.full(int(dry.sum()), onset_climatology),
            ),
        }
        rain_qualified = metrics["model"]["brier"] < metrics["climatology"]["brier"]
        if not station_inputs:
            rain_qualified = (rain_qualified and metrics["model"]["brier"] < metrics["persistence"]["brier"]
                              and metrics["model_when_dry"]["brier"] < metrics["climatology_when_dry"]["brier"])

        temperature_target = features["temperature"].shift(-(horizon // 30))
        temperature_samples = inputs.join(temperature_target.rename("target")).dropna()
        temperature_split = assign_split(temperature_samples.index, calibration_start, test_start, horizon)
        temperature_train = temperature_samples[temperature_split.isin(["train", "calibration"])]
        temperature_test = temperature_samples[temperature_split.eq("test")]
        temperature_model = HistGradientBoostingRegressor(
            loss="absolute_error", max_iter=120, max_leaf_nodes=15, min_samples_leaf=40, random_state=42,
        )
        temperature_model.fit(temperature_train[cols], temperature_train["target"] - temperature_train["temperature"])
        t_pred = temperature_test["temperature"] + temperature_model.predict(temperature_test[cols])
        t_mae = mean_absolute_error(temperature_test["target"], t_pred)
        baseline_mae = mean_absolute_error(temperature_test["target"], temperature_test["temperature"])
        if rain_qualified or t_mae < baseline_mae:
            models[horizon] = {
                "rain": (model, calibrator) if rain_qualified else None,
                "temperature": temperature_model if t_mae < baseline_mae else None,
            }
        results[horizon] = {
            "test_rows": len(test),
            "test_rain": int(test["target"].sum()),
            "rain": metrics,
            "rain_qualified": rain_qualified,
            "temperature_test_rows": len(temperature_test),
            "temperature_mae": t_mae,
            "temperature_persistence_mae": baseline_mae,
        }

    report = {
        "station": "VVTS",
        "source": "Iowa Environmental Mesonet METAR archive",
        "target": "Rain reported in the next one or two scheduled airport bulletins",
        "observation_minutes": 30,
        "runtime_inputs": "station_temperature_humidity_pressure" if station_inputs else "vvts_metar",
        "rain_bulletins": int(features["rain_now"].sum()),
        "usable_bulletins": int(features["rain_now"].notna().sum()),
        "calibration_start": calibration_start.isoformat(),
        "test_start": test_start.isoformat(),
        "horizons": results,
    }
    return {"format": 1, "station": "VVTS", "features": cols, "models": models,
            "runtime_inputs": report["runtime_inputs"]}, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--holdout", type=Path)
    parser.add_argument("--calibration-start", required=True)
    parser.add_argument("--test-start", required=True)
    parser.add_argument("--model-out", type=Path)
    parser.add_argument("--station-inputs", action="store_true")
    args = parser.parse_args()
    calibration_start = pd.to_datetime(args.calibration_start, utc=True)
    test_start = pd.to_datetime(args.test_start, utc=True)
    if calibration_start >= test_start:
        parser.error("calibration must start before the test period")
    paths = [args.data] + ([args.holdout] if args.holdout else [])
    frames = [pd.read_csv(path, keep_default_na=False) for path in paths]
    if args.holdout:
        if pd.to_datetime(frames[0]["valid"], utc=True).max() >= test_start:
            parser.error("training file overlaps the holdout period")
        if pd.to_datetime(frames[1]["valid"], utc=True).min() < test_start:
            parser.error("holdout file contains data before the test period")
    artifact, report = train_models(pd.concat(frames, ignore_index=True), calibration_start, test_start,
                                    station_inputs=args.station_inputs)
    report["data_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if args.model_out:
        if not artifact["models"]:
            parser.error("no model improved on its holdout baseline")
        args.model_out.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(artifact, args.model_out, compress=3)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
