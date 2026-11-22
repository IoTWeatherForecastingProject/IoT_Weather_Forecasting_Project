"""Features shared by archived and live scheduled Tân Sơn Nhất METARs."""
import re

import numpy as np
import pandas as pd

FREQ = "30min"
HEADER = re.compile(r"^(?:(?:METAR|SPECI)\s+)?VVTS\s+\d{6}Z\b")
TEMPERATURE = re.compile(r"(?:^|\s)(M?\d{2})/(M?\d{2})(?=\s|$)")
QNH = re.compile(r"(?:^|\s)Q(\d{4})(?=\s|$)")
RAIN = re.compile(r"(?:^|\s)[+-]?(?:SH|TS|FZ)?(?:RA(?:DZ)?|DZRA|DZ)(?=\s|$)")
TREND = re.compile(r"\s(?:RMK|NOSIG|BECMG|TEMPO|PROB\d{2})(?:\s|$)")


def extract_observation(report: str):
    if not HEADER.match(report):
        return None
    current = TREND.split(report, maxsplit=1)[0]
    temperature = TEMPERATURE.search(current)
    qnh = QNH.search(current)
    if not temperature or not qnh:
        return None
    temp, dewpoint = (int(value.replace("M", "-")) for value in temperature.groups())
    pressure = int(qnh[1])
    if not -20 <= dewpoint <= temp <= 55 or not 930 <= pressure <= 1060:
        return None
    return temp, dewpoint, pressure, int(bool(RAIN.search(current)))


def build_features(reports: pd.DataFrame) -> pd.DataFrame:
    data = reports.loc[reports["station"].eq("VVTS"), ["valid", "metar"]].copy()
    data.index = pd.to_datetime(data["valid"], utc=True, errors="coerce", format="mixed")
    data = data.loc[data.index.notna() & (data.index == data.index.floor(FREQ))].sort_index(kind="stable")
    rows = []
    for timestamp, report in data["metar"].items():
        observation = extract_observation(str(report).strip())
        if observation is not None:
            rows.append((timestamp, *observation))
    columns = ["valid", "temperature", "dewpoint", "qnh", "rain_now"]
    grid = pd.DataFrame(rows, columns=columns).set_index("valid")
    if grid.empty:
        return grid
    grid = grid.loc[~grid.index.duplicated(keep="last")].asfreq(FREQ)
    features = grid.copy()
    for column in ("temperature", "dewpoint", "qnh"):
        features[f"{column}_change_30m"] = grid[column].diff()
        features[f"{column}_change_60m"] = grid[column].diff(2)
    hour = grid.index.tz_convert("Asia/Ho_Chi_Minh").hour + grid.index.minute / 60
    features["local_hour_sin"] = np.sin(hour * np.pi / 12)
    features["local_hour_cos"] = np.cos(hour * np.pi / 12)
    return features
