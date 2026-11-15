"""TV2 forecasting package, with optional training tools loaded on demand.

Importing the inference engine must not also import PyTorch, plotting libraries,
or the training pipeline. Public ``from ml import ...`` exports stay compatible.
"""
from importlib import import_module

__version__ = "1.0.0"
__author__ = "TV2 — Time-Series AI Engineer"

_EXPORTS = {
    "preprocessing": (
        "TimeSeriesPreprocessor", "PreprocessingConfig", "load_raw_data_from_csv",
        "generate_sample_iot_data",
    ),
    "feature_engineering": ("TemperatureFeatureEngineer", "FeatureConfig"),
    "models_benchmark": ("TemperatureBenchmark", "BenchmarkConfig", "load_trained_model"),
    "deep_learning": (
        "DeepLearningConfig", "DeepForecastModel", "SlidingWindowDataset",
        "DeepLearningExperiment", "load_deep_model",
    ),
    "error_analysis": ("ErrorAnalyzer", "ErrorAnalysisConfig", "predict_from_saved_model"),
    "inference_engine": (
        "TemperatureInferenceEngine", "TemperatureForecast", "CombinedForecast",
        "get_engine", "predict_forecast", "predict_temperature_forecast",
        "predict_combined_forecast", "predict_forecast_for_backend",
    ),
}
_MODULE_FOR_EXPORT = {name: module for module, names in _EXPORTS.items() for name in names}
__all__ = list(_MODULE_FOR_EXPORT)


def __getattr__(name):
    module = _MODULE_FOR_EXPORT.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
