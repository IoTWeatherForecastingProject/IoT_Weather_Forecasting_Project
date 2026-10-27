"""Evaluate fresh stations periodically, independent of Dashboard polling."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging

from app.config import settings
from app.db.models import WeatherMeasurement
from app.db.session import get_db_context
from app.services.weather_forecast import build_forecast, NoRecentMeasurements

logger = logging.getLogger(__name__)


class ForecastMonitor:
    def __init__(self, mqtt_client):
        self.mqtt_client = mqtt_client
        self._stop = asyncio.Event()

    def stop(self):
        self._stop.set()

    def run_once(self):
        now = datetime.now(timezone.utc)
        with get_db_context() as db:
            devices = db.query(WeatherMeasurement.device_id).filter(
                WeatherMeasurement.timestamp >= now - timedelta(seconds=settings.ALERT_MAX_DATA_AGE_SECONDS),
                WeatherMeasurement.timestamp <= now,
            ).distinct().all()
        for (device_id,) in devices:
            if self._stop.is_set():
                break
            try:
                with get_db_context() as db:
                    build_forecast(db, device_id=device_id, mqtt_client=self.mqtt_client)
            except NoRecentMeasurements:
                logger.info("[ALERT MONITOR] Khong con mau gan day: %s", device_id)
            except Exception:
                logger.exception("[ALERT MONITOR] Loi danh gia tram %s", device_id)

    async def run(self):
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                logger.exception("[ALERT MONITOR] Loi chu ky danh gia; se thu lai")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.ALERT_EVALUATION_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue
