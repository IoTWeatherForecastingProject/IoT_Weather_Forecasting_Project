"""
Test nhanh ML-05 & ML-06 — Error Analysis + Inference Engine
=============================================================
Chay: python -X utf8 ml/tests/test_error_inference.py
"""

import sys, os, io
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import json
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd

from ml.preprocessing import (
    TimeSeriesPreprocessor, PreprocessingConfig, generate_sample_iot_data
)
from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig
from ml.models_benchmark import TemperatureBenchmark, BenchmarkConfig
from ml.error_analysis import ErrorAnalyzer, ErrorAnalysisConfig
from ml.inference_engine import (
    TemperatureInferenceEngine, TemperatureForecast, CombinedForecast,
    predict_temperature_forecast, predict_combined_forecast
)

PASSED = 0
FAILED = 0

def check(cond: bool, name: str) -> None:
    global PASSED, FAILED
    icon = "[OK]" if cond else "[!!]"
    mark = "PASS" if cond else "FAIL"
    print(f"  {icon} {mark}: {name}")
    if cond: PASSED += 1
    else: FAILED += 1

# ── Setup chung ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  Setup: tao du lieu 7 ngay...")
print("=" * 60)

df_raw   = generate_sample_iot_data(n_minutes=60 * 24 * 7, seed=42)
prep     = TimeSeriesPreprocessor(PreprocessingConfig())
df_clean = prep.fit_transform(df_raw)

feat_cfg = FeatureConfig(lag_steps=[1,2,3,6,10,30], delta_steps=[1,5,10],
                          rolling_windows=[6,10,30,60], forecast_horizons=[10,30,60])
engineer    = TemperatureFeatureEngineer(feat_cfg)
df_features = engineer.fit_transform(df_clean)
X, y_dict   = engineer.get_Xy(df_features)
X_train, X_val, X_test, _, _, _ = engineer.train_val_test_split(X, y_dict["y_10"])
print(f"  Train={len(X_train)}, Val={len(X_val)}, Test={len(X_test)}")

# Chay benchmark nhanh de lay predictions
ml_cfg    = BenchmarkConfig(rf_n_estimators=30, xgb_n_estimators=50,
                             horizons=[10,30,60], save_models=True)
benchmark = TemperatureBenchmark(ml_cfg)
benchmark.run(X_train, X_val, X_test, y_dict)

y_true_dict, y_pred_dict = {}, {}
for h in [10, 30, 60]:
    best_model, _ = benchmark.get_best_model(h)
    y_true_dict[h] = y_dict[f"y_{h}"].loc[X_test.index].values
    y_pred_dict[h] = best_model.predict(X_test)

df_test_ctx = df_clean.loc[X_test.index]

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 1: ML-05 ErrorAnalyzer — co ban
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 1: ML-05 ErrorAnalyzer — co ban")
print("=" * 60)

cfg_ea = ErrorAnalysisConfig(rapid_change_threshold=0.3, acf_nlags=20)
analyzer = ErrorAnalyzer(cfg_ea)
report   = analyzer.run(y_true_dict, y_pred_dict, df_test=df_test_ctx)

check(isinstance(report, dict),             "report la dict")
check("residual_stats"      in report,      "report co residual_stats")
check("horizon_degradation" in report,      "report co horizon_degradation")
check("durbin_watson"       in report,      "report co durbin_watson")

# Kiem tra residual_stats cho tung horizon
for h in [10, 30, 60]:
    s = report["residual_stats"].get(h, {})
    check(len(s) > 0,                          f"residual_stats[{h}] khong rong")
    check("mae"  in s and s["mae"]  >= 0,      f"residual_stats[{h}]: MAE >= 0")
    check("rmse" in s and s["rmse"] >= 0,      f"residual_stats[{h}]: RMSE >= 0")
    check("skewness" in s,                     f"residual_stats[{h}]: co skewness")
    check("pct_over_1C" in s,                  f"residual_stats[{h}]: co pct_over_1C")
    check(0 <= s.get("pct_over_1C", -1) <= 100,f"residual_stats[{h}]: 0<=pct<=100")

# Kiem tra horizon_degradation
deg = report["horizon_degradation"]
check(10 in deg and 30 in deg and 60 in deg,   "horizon_degradation co ca 3 horizon")
check(deg[10]["mae"] <= deg[60]["mae"] * 1.5,  "MAE+10 khong qua lon so voi MAE+60")

# Durbin-Watson
dw = report["durbin_watson"]
check(10 in dw and 30 in dw and 60 in dw,      "durbin_watson co ca 3 horizon")
for h in [10, 30, 60]:
    check(0 <= dw[h] <= 4, f"DW[{h}] trong [0, 4]")

# Conditional + rapid change (chi co khi truyen df_test)
check("conditional_error" in report,           "report co conditional_error")
check("rapid_change"      in report,           "report co rapid_change")

rc = report["rapid_change"]
check("pct_rapid_change" in rc,                "rapid_change co pct_rapid_change")
check(0 <= rc["pct_rapid_change"] <= 100,      "pct_rapid_change trong [0,100]")

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 2: ML-05 ErrorAnalyzer — export JSON
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 2: ML-05 — export_report_json")
print("=" * 60)

with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
    tmp_json = f.name
analyzer.export_report_json(tmp_json)
check(Path(tmp_json).exists(),     "File JSON duoc tao")
with open(tmp_json, encoding="utf-8") as f:
    j = json.load(f)
check("residual_stats"      in j,  "JSON co residual_stats")
check("horizon_degradation" in j,  "JSON co horizon_degradation")
check("durbin_watson"       in j,  "JSON co durbin_watson")
os.unlink(tmp_json)

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 3: ML-06 TemperatureInferenceEngine — khoi tao & health check
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 3: ML-06 InferenceEngine — khoi tao")
print("=" * 60)

engine = TemperatureInferenceEngine()
hc = engine.health_check()

check(isinstance(hc, dict),                    "health_check tra ve dict")
check("status"             in hc,              "hc co key 'status'")
check("models_loaded"      in hc,              "hc co key 'models_loaded'")
check("horizons_available" in hc,              "hc co key 'horizons_available'")
check("min_history_steps"  in hc,              "hc co key 'min_history_steps'")
check(hc["status"] in ("ok", "degraded"),      "status la 'ok' hoac 'degraded'")

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 4: ML-06 — predict() tu DataFrame du lieu du
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 4: ML-06 — predict() tu DataFrame")
print("=" * 60)

# Tao 120 phut du lieu mau (du > MIN_HISTORY_STEPS=90)
df_input = generate_sample_iot_data(n_minutes=120, seed=5)
df_input = df_input.set_index("timestamp")

forecast = engine.predict(df_input)

check(isinstance(forecast, TemperatureForecast),   "predict() tra ve TemperatureForecast")
check(-10 <= forecast.t_plus_10min <= 60,          "t_plus_10min trong [-10, 60] C")
check(-10 <= forecast.t_plus_30min <= 60,          "t_plus_30min trong [-10, 60] C")
check(-10 <= forecast.t_plus_60min <= 60,          "t_plus_60min trong [-10, 60] C")
check(forecast.latency_ms >= 0,                    "latency_ms >= 0")
check(forecast.confidence in ("normal","fallback"),"confidence hop le")
check(isinstance(forecast.model_used, str),        "model_used la string")
check(len(forecast.model_used) > 0,                "model_used khong rong")

# to_dict()
d = forecast.to_dict()
check("temperature_forecast" in d,                 "to_dict() co 'temperature_forecast'")
check("model_used"  in d,                          "to_dict() co 'model_used'")
check("latency_ms"  in d,                          "to_dict() co 'latency_ms'")
check("confidence"  in d,                          "to_dict() co 'confidence'")
tf = d["temperature_forecast"]
check("t_plus_10min" in tf,                        "temperature_forecast co t_plus_10min")
check("t_plus_30min" in tf,                        "temperature_forecast co t_plus_30min")
check("t_plus_60min" in tf,                        "temperature_forecast co t_plus_60min")

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 5: ML-06 — predict() tu list[dict]
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 5: ML-06 — predict() tu list[dict]")
print("=" * 60)

list_input = [
    {
        "timestamp":   pd.Timestamp("2026-10-01") + pd.Timedelta(minutes=i),
        "temperature": 28.0 + 0.01 * i + np.random.randn() * 0.1,
        "humidity":    70.0 - 0.005 * i,
        "pressure":    1013.0,
    }
    for i in range(100)
]

forecast_list = engine.predict(list_input)
check(isinstance(forecast_list, TemperatureForecast), "predict(list) tra ve TemperatureForecast")
check(-10 <= forecast_list.t_plus_10min <= 60,        "list: t_plus_10min hop le")
check(forecast_list.latency_ms >= 0,                  "list: latency_ms >= 0")

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 6: ML-06 — Fallback khi data qua it
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 6: ML-06 — Fallback khi data qua it")
print("=" * 60)

tiny = generate_sample_iot_data(n_minutes=10, seed=1)
tiny = tiny.set_index("timestamp")

fallback_result = engine.predict(tiny)
check(fallback_result.confidence == "fallback",    "fallback: confidence = 'fallback'")
check(fallback_result.error_msg is not None,       "fallback: co error_msg")
check(-10 <= fallback_result.t_plus_10min <= 60,   "fallback: gia tri nhiet do hop le")

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 7: ML-06 — predict_combined() va CombinedForecast
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 7: ML-06 — predict_combined()")
print("=" * 60)

rain_prob = {"p_10min": 0.2, "p_30min": 0.45, "p_60min": 0.7}
combined  = engine.predict_combined(df_input, rain_prob)

check(isinstance(combined, CombinedForecast),     "predict_combined tra ve CombinedForecast")
check(combined.rain_probability == rain_prob,     "rain_probability duoc giu nguyen")
check(len(combined.generated_at) > 0,             "generated_at co gia tri")

cd = combined.to_dict()
check("temperature_forecast" in cd,               "combined.to_dict() co temperature_forecast")
check("rain_probability"     in cd,               "combined.to_dict() co rain_probability")
check("generated_at"         in cd,               "combined.to_dict() co generated_at")
check(cd["rain_probability"]["p_30min"] == 0.45,  "rain_probability p_30min chinh xac")

# ══════════════════════════════════════════════════════════════════════════════
# TEST GROUP 8: predict_temperature_forecast() ham tien ich
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 8: ML-06 — ham tien ich cap cao")
print("=" * 60)

result_dict = predict_temperature_forecast(df_input)
check(isinstance(result_dict, dict),              "predict_temperature_forecast tra ve dict")
check("temperature_forecast" in result_dict,      "co key 'temperature_forecast'")
check("model_used"           in result_dict,      "co key 'model_used'")

combined_dict = predict_combined_forecast(df_input, rain_prob)
check(isinstance(combined_dict, dict),            "predict_combined_forecast tra ve dict")
check("rain_probability" in combined_dict,        "combined_dict co rain_probability")

# ══════════════════════════════════════════════════════════════════════════════
# KET QUA TONG HOP
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"  KET QUA: {PASSED} PASS -- {FAILED} FAIL")
print("=" * 60)

if FAILED == 0:
    print("\n  Tat ca test PASS! ML-05 & ML-06 san sang.")
else:
    print(f"\n  {FAILED} test that bai. Kiem tra lai code.")
    sys.exit(1)
