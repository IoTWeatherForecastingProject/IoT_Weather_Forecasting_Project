"""Evaluate a pair of temperature and rain models for one forecast horizon."""


def empty_horizon() -> dict:
    return {"temperature_c": None, "temperature_source": "unavailable", "rain_probability": None,
                "rain_level": None, "rain_source": "unavailable", "valid_at": None}


def predict_horizon(models, features, temperature_base, valid_at) -> dict:
    point = empty_horizon()
    point["valid_at"] = valid_at
    if models["temperature"] is not None:
        change = models["temperature"].predict(features)[0]
        point.update(temperature_c=round(float(temperature_base + change), 2), temperature_source="model")
    else:
        point.update(temperature_c=round(float(temperature_base), 2), temperature_source="persistence")
    if models["rain"] is not None:
        classifier, calibrator = models["rain"]
        probability = round(float(calibrator.predict(classifier.predict_proba(features)[:, 1])[0]), 4)
        point.update(rain_probability=probability, rain_source="model",
                     rain_level="High" if probability >= .70 else "Medium" if probability >= .30 else "Low")
    return point
