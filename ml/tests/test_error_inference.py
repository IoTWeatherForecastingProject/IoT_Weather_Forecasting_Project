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
check(forecast.confidence == "normal",             "confidence la 'normal' (model ML thuc te, khong phai fallback)")
check(forecast.model_used != "Persistence",        "model_used la ML model (XGBoost/Ridge/RF/Lasso)")
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
# TEST GROUP 9: Regression Tests — Khắc phục 5 điểm Review
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  TEST GROUP 9: Regression Tests — Review Fixes")
print("=" * 60)

from ml.inference_engine import predict_forecast

# 9.1: Kiểm tra API bàn giao predict_forecast() cho TV1 (BE-05)
pf_result = predict_forecast(df_input)
check(isinstance(pf_result, dict), "predict_forecast tra ve dict dung format BE-05")
check(pf_result["confidence"] == "normal", "predict_forecast confidence la 'normal'")
check(pf_result["model_used"] != "Persistence", "predict_forecast chay model ML that")

# 9.2: Dữ liệu IoT tần suất cao (5 giây/mẫu, 1200 hàng = 100 phút)
# Phải được resample về 1-minute grid và dự báo thành công (Review P1)
start_time = pd.Timestamp("2026-10-01 08:00:00", tz="UTC")
iot_5s_records = [
    {
        "timestamp": start_time + pd.Timedelta(seconds=5 * i),
        "temperature": 27.0 + 0.005 * i + np.random.randn() * 0.05,
        "humidity": 65.0 - 0.002 * i,
        "pressure": 1012.5,
        "rain_raw": 0.0,
    }
    for i in range(1200)   # 1200 * 5s = 6000s = 100 phút
]
forecast_5s = engine.predict(iot_5s_records)
check(forecast_5s.confidence == "normal", "IoT 5s: Resample 1min thanh cong va confidence='normal'")
check(forecast_5s.model_used != "Persistence", "IoT 5s: Chay model that tren du lieu 5s da resample")

# 9.3: Dữ liệu 90 hàng nhưng chỉ dài 7.5 phút (Review P1)
# 90 mẫu * 5s = 450s = 7.5 phút -> PHẢI kích hoạt fallback và ghi rõ lỗi thời gian
short_span_records = iot_5s_records[:90]
forecast_short = engine.predict(short_span_records)
check(forecast_short.confidence == "fallback", "90 mau 5s (7.5 phut): Kich hoat fallback")
check("Lịch sử dữ liệu chỉ dài" in (forecast_short.error_msg or "") or "không đủ" in (forecast_short.error_msg or ""), 
      "90 mau 5s: error_msg ghi ro thoi gian lich su khong du")

# 9.4: Kiểm tra tính toán Rolling Window không bị max(0, -w-1) bug (Review P2)
# Tạo chuỗi 100 phút: 94 phút đầu nhiệt độ 20°C, 6 phút cuối nhảy vọt lên 35°C
step_change_records = [
    {
        "timestamp": start_time + pd.Timedelta(minutes=i),
        "temperature": 20.0 if i < 94 else 35.0,
        "humidity": 70.0,
        "pressure": 1013.0,
        "rain_raw": 0.0,
    }
    for i in range(100)
]
df_step = pd.DataFrame(step_change_records).set_index("timestamp")
step_feat = engine._feature_engineer.transform_features(df_step)
last_row = step_feat.iloc[-1]
# Rolling 6m chỉ chứa các điểm 35°C (hoặc trung bình gần 35), trong khi rolling 60m chứa đa số 20°C
check(abs(last_row["T_roll_mean_6m"] - last_row["T_roll_mean_60m"]) > 5.0, 
      "Rolling 6m != Rolling 60m khi co step change (da sua bug max(0, -w-1))")

# 9.5: Dữ liệu gián đoạn (sensor drop out 10 phút giữa chuỗi)
discontinuous_records = [
    r for r in iot_5s_records[:1200]
    # Bỏ qua đoạn giữa phút 30 đến 40
    if not (start_time + pd.Timedelta(minutes=30) <= r["timestamp"] < start_time + pd.Timedelta(minutes=40))
]
forecast_disc = engine.predict(discontinuous_records)
check(forecast_disc.confidence == "normal", "Du lieu gian doan 10 phut: Noi suy thanh cong va confidence='normal'")

# ══════════════════════════════════════════════════════════════════════════════
# KET QUA TONG HOP
# ══════════════════════════════════════════════════════════════════════════════

# ============================================================
# TEST GROUP 10: Regression Tests -- Review Fix #2 & #4
# ============================================================
print("\n" + "=" * 60)
print("  TEST GROUP 10: Regression -- Interp Limit & Backend Contract")
print("=" * 60)

# -- 10.1: Noi suy khong gioi han -> degraded/fallback ----------
# Chi 2 diem cach nhau 2 tieng: KHONG duoc tra confidence="normal"
try:
    import pandas as pd
    from ml.inference_engine import TemperatureInferenceEngine
    eng_cov = TemperatureInferenceEngine()
    sparse_start = pd.Timestamp("2026-06-01 06:00:00", tz="UTC")
    sparse_records = [
        {"timestamp": sparse_start,
         "temperature": 28.0, "humidity": 70.0, "pressure": 1010.0, "rain_raw": 0.0},
        {"timestamp": sparse_start + pd.Timedelta(minutes=120),
         "temperature": 29.0, "humidity": 72.0, "pressure": 1009.0, "rain_raw": 0.0},
    ]
    result_sparse = eng_cov.predict(sparse_records)
    check(result_sparse.confidence != "normal",
          "[Fix#2] 2 diem cach 2 gio: confidence phai la degraded/fallback (got='%s')" % result_sparse.confidence)
    check(result_sparse.confidence in ("degraded", "fallback"),
          "[Fix#2] confidence phai la degraded hoac fallback (got='%s')" % result_sparse.confidence)
except Exception as e:
    print("  [EXCEPTION] 10.1 interp limit: %s" % e)
    FAILED += 1

# -- 10.2: Mat du lieu keo dai (60+ phut) giua chuoi ------------
try:
    import numpy as np
    import pandas as pd
    from ml.inference_engine import TemperatureInferenceEngine
    eng_gap2 = TemperatureInferenceEngine()
    base = pd.Timestamp("2026-06-01 00:00:00", tz="UTC")
    records_before = [
        {"timestamp": base + pd.Timedelta(minutes=i),
         "temperature": 27.0 + 0.01*i, "humidity": 70.0, "pressure": 1012.0, "rain_raw": 0.0}
        for i in range(30)
    ]
    records_after = [
        {"timestamp": base + pd.Timedelta(minutes=90+i),
         "temperature": 27.5 + 0.01*i, "humidity": 71.0, "pressure": 1012.0, "rain_raw": 0.0}
        for i in range(70)
    ]
    result_gap60 = eng_gap2.predict(records_before + records_after)
    # coverage thuc = (30+70)/160 = 62.5% < COVERAGE_DEGRADED_THRESHOLD (70%)
    check(result_gap60.confidence in ("degraded", "fallback"),
          "[Fix#2] Mat du lieu 60 phut: confidence phai degraded/fallback (got='%s')" % result_gap60.confidence)
except Exception as e:
    print("  [EXCEPTION] 10.2 long gap: %s" % e)
    FAILED += 1

# -- 10.3: Contract test -- predict_forecast_for_backend() khop TV1 --
try:
    import numpy as np
    import pandas as pd
    from ml.inference_engine import predict_forecast_for_backend
    base_b = pd.Timestamp("2026-06-01 08:00:00", tz="UTC")
    records_b = [
        {
            "timestamp":   base_b + pd.Timedelta(minutes=i),
            "temperature": 27.0 + 0.01*i + np.random.randn()*0.05,
            "humidity":    68.0,
            "pressure":    1012.0,
            "rain_raw":    0.0,
        }
        for i in range(100)
    ]
    result_b = predict_forecast_for_backend(
        records_b,
        device_id="station01",
        rain_probability={10: 0.15, 30: 0.30, 60: 0.50},
        rain_source="model",
    )
    required_keys = [
        "device_id", "generated_at", "current_temperature",
        "current_humidity", "current_pressure",
        "plus_10m", "plus_30m", "plus_60m",
        "alert_triggered", "alert_message",
    ]
    for k in required_keys:
        check(k in result_b, "[Fix#4] ForecastResponse co truong '%s'" % k)
    horizon_keys = ["temperature_c", "rain_probability", "rain_level", "rain_source"]
    for k in horizon_keys:
        check(k in result_b["plus_10m"], "[Fix#4] plus_10m co truong '%s'" % k)
    check(result_b["device_id"] == "station01", "[Fix#4] device_id dung")
    check(isinstance(result_b["alert_triggered"], bool), "[Fix#4] alert_triggered la bool")
    check(result_b["plus_10m"]["rain_source"] == "model", "[Fix#4] rain_source=model duoc giu nguyen")
except Exception as e:
    print("  [EXCEPTION] 10.3 backend contract: %s" % e)
    FAILED += 1

# -- 10.4: to_backend_response() tren TemperatureForecast truc tiep --
try:
    from ml.inference_engine import TemperatureForecast
    tf = TemperatureForecast(
        t_plus_10min=28.5,
        t_plus_30min=29.0,
        t_plus_60min=30.1,
        model_used="XGBoost",
        latency_ms=12.5,
        confidence="normal",
    )
    resp = tf.to_backend_response(
        device_id="station_test",
        current_temperature=28.0,
        current_humidity=65.0,
        current_pressure=1011.0,
        rain_probability={10: 0.20, 30: 0.45, 60: 0.72},
        alert_threshold=0.70,
    )
    check(resp["device_id"] == "station_test",         "[Fix#4] to_backend_response device_id")
    check(resp["current_temperature"] == 28.0,         "[Fix#4] to_backend_response current_temperature")
    check(resp["plus_10m"]["temperature_c"] == 28.5,   "[Fix#4] plus_10m.temperature_c = t_plus_10min")
    check(resp["plus_60m"]["rain_probability"] == 0.72,"[Fix#4] plus_60m rain_probability")
    check(resp["alert_triggered"] is True,             "[Fix#4] alert khi rain_prob >= 0.70")
    check(resp["plus_60m"]["rain_level"] == "High",    "[Fix#4] rain_level=High khi prob>=0.70")
    check("alert_message" in resp,                     "[Fix#4] alert_message key ton tai")
except Exception as e:
    print("  [EXCEPTION] 10.4 to_backend_response: %s" % e)
    FAILED += 1

print("\n" + "=" * 60)
print(f"  KET QUA: {PASSED} PASS -- {FAILED} FAIL")
print("=" * 60)

if FAILED == 0:
    print("\n  Tat ca test PASS! ML-05 & ML-06 san sang.")
else:
    print(f"\n  {FAILED} test that bai. Kiem tra lai code.")
    sys.exit(1)
