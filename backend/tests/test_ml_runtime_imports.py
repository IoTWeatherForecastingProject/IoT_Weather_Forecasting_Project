"""Keep the API inference path independent of training-only dependencies."""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integrated_model


ROOT = Path(__file__).resolve().parents[2]


def test_package_and_feature_exports_do_not_import_training_dependencies():
    script = """
import importlib.abc
import sys

class NoTrainingDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'matplotlib', 'seaborn', 'statsmodels', 'scipy', 'sklearn', 'joblib', 'xgboost'}:
            raise AssertionError('Unexpected training/runtime import: ' + fullname)

sys.meta_path.insert(0, NoTrainingDependencies())
import ml
assert 'FeatureConfig' in dir(ml)
from ml import FeatureConfig, TemperatureFeatureEngineer
from ml.feature_engineering import FeatureConfig as DirectFeatureConfig
assert FeatureConfig is DirectFeatureConfig
assert TemperatureFeatureEngineer(FeatureConfig()) is not None
assert 'ml.deep_learning' not in sys.modules
assert 'ml.preprocessing' not in sys.modules
try:
    ml.unknown_export
except AttributeError:
    pass
else:
    raise AssertionError('Unknown exports must raise AttributeError')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_delivered_models_predict_without_training_dependencies():
    script = """
import importlib.abc
import sys

blocked = {'torch', 'matplotlib', 'seaborn', 'statsmodels'}

class NoTrainingDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise AssertionError('Unexpected training import: ' + fullname)

sys.meta_path.insert(0, NoTrainingDependencies())
import pandas as pd
from ml import TemperatureInferenceEngine

engine = TemperatureInferenceEngine()
frame = pd.DataFrame({
    'timestamp': pd.date_range('2026-11-04T01:00:00Z', periods=121, freq='min'),
    'temperature': [30 + index / 100 for index in range(121)],
    'humidity': 70., 'pressure': 1005., 'rain_raw': 700.,
})
forecast = engine.predict(frame)
assert engine.health_check()['horizons_available'] == [10, 30, 60]
assert forecast.confidence == 'normal', forecast.to_dict()
assert forecast.model_used == 'XGBoost', forecast.to_dict()
assert not (blocked & set(sys.modules))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
