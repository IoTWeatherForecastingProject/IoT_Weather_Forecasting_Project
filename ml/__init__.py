"""
ML Package — IoT Weather Forecasting
=====================================
Thành viên 2 (TV2) — Time-Series AI Engineer

Modules:
    preprocessing       — ML-01: Common Time-Series Preprocessing
    feature_engineering — ML-02: Feature Engineering for Temperature Regression
    models_benchmark    — ML-03: Temperature Forecasting & Model Benchmark
    deep_learning       — ML-04: LSTM/GRU Experimentation
    error_analysis      — ML-05: Error Analysis & Diagnostics
    inference_engine    — ML-06: Forecast Inference Engine
"""

from ml.preprocessing import (
    TimeSeriesPreprocessor,
    PreprocessingConfig,
    load_raw_data_from_csv,
    generate_sample_iot_data,
)

from ml.feature_engineering import (
    TemperatureFeatureEngineer,
    FeatureConfig,
)

from ml.models_benchmark import (
    TemperatureBenchmark,
    BenchmarkConfig,
    load_trained_model,
)

from ml.deep_learning import (
    DeepLearningConfig,
    DeepForecastModel,
    SlidingWindowDataset,
    DeepLearningExperiment,
    load_deep_model,
)

from ml.error_analysis import (
    ErrorAnalyzer,
    ErrorAnalysisConfig,
    predict_from_saved_model,
)

from ml.inference_engine import (
    TemperatureInferenceEngine,
    TemperatureForecast,
    CombinedForecast,
    get_engine,
    predict_temperature_forecast,
    predict_combined_forecast,
)

__version__ = "1.0.0"
__author__  = "TV2 — Time-Series AI Engineer"

__all__ = [
    # ML-01
    "TimeSeriesPreprocessor",
    "PreprocessingConfig",
    "load_raw_data_from_csv",
    "generate_sample_iot_data",
    # ML-02
    "TemperatureFeatureEngineer",
    "FeatureConfig",
    # ML-03
    "TemperatureBenchmark",
    "BenchmarkConfig",
    "load_trained_model",
    # ML-04
    "DeepLearningConfig",
    "DeepForecastModel",
    "SlidingWindowDataset",
    "DeepLearningExperiment",
    "load_deep_model",
    # ML-05
    "ErrorAnalyzer",
    "ErrorAnalysisConfig",
    "predict_from_saved_model",
    # ML-06
    "TemperatureInferenceEngine",
    "TemperatureForecast",
    "CombinedForecast",
    "get_engine",
    "predict_temperature_forecast",
    "predict_combined_forecast",
]
