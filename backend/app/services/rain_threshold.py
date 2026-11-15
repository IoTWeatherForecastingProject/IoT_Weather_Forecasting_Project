"""Shared threshold resolution for the API and scheduled alert path."""
import logging
import math
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.config import settings
from app.db.models import SystemConfig

logger = logging.getLogger(__name__)


def resolve_rain_threshold(db: Session) -> Tuple[float, str, Optional[datetime]]:
    """Trả (threshold, source, updated_at); dùng chung cho GET ngưỡng và /forecast."""
    config = (
        db.query(SystemConfig)
        .filter(SystemConfig.config_key == "rain_alert_threshold")
        .first()
    )
    if config is not None:
        try:
            threshold = float(config.config_value)
            if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
                raise ValueError("threshold outside [0, 1]")
        except (TypeError, ValueError):
            logger.warning("[CONFIG] Invalid rain_alert_threshold; using default")
        else:
            return threshold, "db", config.updated_at
    return settings.RAIN_ALERT_THRESHOLD, "default", None
