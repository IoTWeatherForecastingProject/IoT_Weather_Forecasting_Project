"""Lazy boundaries to modules owned by TV2/TV3; never required for API startup."""
import importlib
from pathlib import Path
import sys

from app.config import settings


def load_symbol(module, symbol):
    root = str(Path(__file__).resolve().parents[3] / "ai_engine")
    if root not in sys.path:
        sys.path.append(root)
    return getattr(importlib.import_module(module), symbol)


def integration_status():
    """Report configuration, not a claim that unmerged providers/weights are ready."""
    return {
        "forecast": {
            "owner": "TV2/TV3", "mode": settings.FORECAST_ENGINE_MODE,
            "status": "local_heuristic" if settings.FORECAST_ENGINE_MODE == "heuristic" else "external_opt_in_unverified",
        },
        "analytics": {
            "owner": "TV3", "mode": settings.ANALYTICS_ENGINE_MODE,
            "status": "not_integrated" if settings.ANALYTICS_ENGINE_MODE == "disabled" else "external_opt_in_unverified",
        },
        "model_accuracy_verified": False,
    }
