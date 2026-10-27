import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import threading
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import WeatherMeasurement
from app.db.session import Base
from app import main
from app.services import forecast_monitor
from app.services.forecast_monitor import ForecastMonitor

NOW = datetime(2026, 10, 27, 11, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_context(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[WeatherMeasurement.__table__])

    @contextmanager
    def connect():
        with Session(engine) as db:
            yield db

    def add(device_id, age_seconds, row_id):
        with connect() as db:
            db.add(WeatherMeasurement(
                id=row_id, device_id=device_id, timestamp=NOW - timedelta(seconds=age_seconds),
                temperature=31.5, humidity=90, pressure=1000, rain_raw=200, rain_detected=1,
            ))
            db.commit()

    clock = Mock(wraps=datetime)
    clock.now.return_value = NOW
    monkeypatch.setattr(forecast_monitor, "datetime", clock)
    monkeypatch.setattr(forecast_monitor, "get_db_context", connect)
    monkeypatch.setattr(settings, "ALERT_MAX_DATA_AGE_SECONDS", 120)
    yield add
    engine.dispose()


def test_monitor_only_evaluates_distinct_fresh_stations(db_context, monkeypatch):
    db_context("fresh", 5, 1)
    db_context("fresh", 60, 2)
    db_context("stale", 121, 3)
    db_context("future", -1, 4)
    build = Mock()
    monkeypatch.setattr(forecast_monitor, "build_forecast", build)
    mqtt_client = Mock()
    ForecastMonitor(mqtt_client).run_once()
    build.assert_called_once()
    assert build.call_args.kwargs == {"device_id": "fresh", "mqtt_client": mqtt_client}


def test_station_failure_does_not_skip_other_stations(db_context, monkeypatch):
    db_context("broken", 5, 1)
    db_context("good", 5, 2)

    def build(db, device_id, mqtt_client):
        if device_id == "broken":
            raise RuntimeError("inference failed")
    predictor = Mock(side_effect=build)
    monkeypatch.setattr(forecast_monitor, "build_forecast", predictor)
    ForecastMonitor(Mock()).run_once()
    assert {call.kwargs["device_id"] for call in predictor.call_args_list} == {"broken", "good"}


@pytest.mark.asyncio
async def test_monitor_retries_after_failed_cycle(monkeypatch):
    monkeypatch.setattr(settings, "ALERT_EVALUATION_INTERVAL_SECONDS", 0.01)
    monitor = ForecastMonitor(Mock())

    def cycle():
        if monitor.run_once.call_count == 1:
            raise RuntimeError("database temporarily unavailable")
        monitor.stop()
    monitor.run_once = Mock(side_effect=cycle)
    await asyncio.wait_for(monitor.run(), timeout=2)
    assert monitor.run_once.call_count == 2


@pytest.mark.asyncio
async def test_db_inference_work_does_not_block_the_event_loop():
    monitor = ForecastMonitor(Mock())
    entered, release = threading.Event(), threading.Event()

    def cycle():
        entered.set()
        assert release.wait(timeout=1), "event loop blocked while inference was running"
        monitor.stop()

    async def heartbeat():
        while not entered.is_set():
            await asyncio.sleep(0)
        release.set()

    monitor.run_once = Mock(side_effect=cycle)
    await asyncio.wait_for(asyncio.gather(monitor.run(), heartbeat()), timeout=2)
    monitor.run_once.assert_called_once()


@pytest.mark.asyncio
async def test_stop_wakes_monitor_without_waiting_for_long_interval(monkeypatch):
    monkeypatch.setattr(settings, "ALERT_EVALUATION_INTERVAL_SECONDS", 60)
    monitor = ForecastMonitor(Mock())
    monitor.run_once = Mock()
    task = asyncio.create_task(monitor.run())
    await asyncio.sleep(0.02)
    monitor.stop()
    await asyncio.wait_for(task, timeout=1)
    monitor.run_once.assert_called_once()


@pytest.mark.parametrize("enabled", [True, False])
def test_lifespan_owns_worker_and_monitor_and_cleans_up(monkeypatch, enabled):
    monkeypatch.setattr(settings, "ALERT_MONITOR_ENABLED", enabled)
    worker = Mock()
    worker.client.is_connected.return_value = True
    monkeypatch.setattr(main, "MQTTIngestionWorker", Mock(return_value=worker))
    monkeypatch.setattr(main, "check_db_connection", Mock(return_value=True))

    class Monitor:
        def __init__(self):
            self.stopped = False
            self.event = asyncio.Event()

        async def run(self):
            await self.event.wait()

        def stop(self):
            self.stopped = True
            self.event.set()

    monitor = Monitor()
    factory = Mock(return_value=monitor)
    monkeypatch.setattr(main, "ForecastMonitor", factory)
    with TestClient(main.app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["alert_monitor_running"] is enabled
        assert main.app.state.mqtt_worker is worker
        worker.start.assert_called_once()
        factory.assert_called_once_with(worker.client)
    assert monitor.stopped
    worker.stop.assert_called_once()
    assert main.mqtt_worker is None
    assert main.app.state.alert_monitor_task is None
