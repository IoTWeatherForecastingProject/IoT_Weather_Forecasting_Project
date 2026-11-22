"""Download collocated historical Singapore NEA observations for the 10-minute benchmark."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

URL = "https://api.data.gov.sg/v1/environment/"
CHANNELS = {"air-temperature": "temperature", "relative-humidity": "humidity", "rainfall": "rain_mm"}


def download_channel(client, day, channel):
    response = client.get(URL + channel, params={"date": day})
    response.raise_for_status()
    items = response.json()["items"]
    rows = [(item["timestamp"], reading["station_id"], reading["value"])
            for item in items for reading in item["readings"]]
    name = CHANNELS[channel]
    data = pd.DataFrame(rows, columns=["timestamp", "station_id", name])
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    return data.drop_duplicates(["station_id", "timestamp"], keep="last")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    days = [f"{year}-{month:02d}-15" for year in (2022, 2023) for month in range(1, 13)]
    keys = ["station_id", "timestamp"]
    batches = []
    with (
        httpx.Client(timeout=40, transport=httpx.HTTPTransport(retries=2)) as client,
        ThreadPoolExecutor(6) as pool,
    ):
        pending = {day: [pool.submit(download_channel, client, day, channel) for channel in CHANNELS]
                   for day in days}
        for day, jobs in pending.items():
            temperature, humidity, rain = (job.result() for job in jobs)
            collocated = set(temperature.station_id) & set(humidity.station_id) & set(rain.station_id)
            weather = temperature.merge(humidity, on=keys, how="outer")
            data = weather.merge(rain, on=keys, how="outer")
            batches.append(data[data.station_id.isin(collocated)])
            print(day, len(collocated), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(batches, ignore_index=True).to_csv(args.output, index=False, compression="infer")


if __name__ == "__main__":
    main()
