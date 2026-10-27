"""
Test nhanh ML-03 — Temperature Forecasting & Benchmark
=======================================================
Chay: python -X utf8 ml/tests/test_benchmark.py
"""

import sys, os, io
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pathlib import Path
import numpy as np
import pandas as pd

from ml.preprocessing import TimeSeriesPreprocessor, PreprocessingConfig, generate_sample_iot_data
from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig
from ml.models_benchmark import TemperatureBenchmark, BenchmarkConfig, load_trained_model

PASSED = 0
FAILED = 0

def check(condition: bool, name: str) -> None:
    global PASSED, FAILED
    status = "PASS" if condition else "FAIL"
    mark   = "✅" if condition else "❌"
    print(f"  {mark} {status}: {name}")
    if condition: PASSED += 1
    else: FAILED += 1

# ── Setup: tạo dữ liệu 5 ngày ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("  Chuẩn bị dữ liệu (5 ngày)...")
print("=" * 60)

df_raw  = generate_sample_iot_data(n_minutes=60 * 24 * 5, seed=7)
prep    = TimeSeriesPreprocessor(PreprocessingConfig())
df_clean = prep.fit_transform(df_raw)

feat_cfg = FeatureConfig(lag_steps=[1,2,3,6], delta_steps=[1,5],
                          rolling_windows=[6,30], forecast_horizons=[10,30,60])
engineer    = TemperatureFeatureEngineer(feat_cfg)
df_features = engineer.fit_transform(df_clean)
X, y_dict   = engineer.get_Xy(df_features)
X_train, X_val, X_test, y_tr, y_v, y_te = engineer.train_val_test_split(X, y_dict["y_10"])
print(f"  Train={len(X_train)}, Val={len(X_val)}, Test={len(X_test)}")

# ── Benchmark nhẹ (ít cây hơn để test nhanh) ──────────────────────────────
cfg = BenchmarkConfig(rf_n_estimators=30, xgb_n_estimators=50,
                      horizons=[10, 30, 60], save_models=True)
bench = TemperatureBenchmark(cfg)
tables = bench.run(X_train, X_val, X_test, y_dict)

# ── Test Group 1: Kết quả benchmark ───────────────────────────────────────
print("\n" + "=" * 60)
print("  TEST GROUP 1: Kết quả benchmark")
print("=" * 60)

check(len(tables) == 3, "Có đủ 3 bảng kết quả (horizon 10/30/60)")

for h in [10, 30, 60]:
    df = tables[h]
    check(isinstance(df, pd.DataFrame),       f"Horizon +{h}m: trả về DataFrame")
    check(len(df) == 5,                        f"Horizon +{h}m: có đủ 5 model")
    check("MAE_test (°C)" in df.columns,      f"Horizon +{h}m: có cột MAE_test")
    check("RMSE_test (°C)" in df.columns,     f"Horizon +{h}m: có cột RMSE_test")
    check("R²_test" in df.columns,            f"Horizon +{h}m: có cột R²_test")
    check(df["MAE_test (°C)"].isna().sum()==0,f"Horizon +{h}m: không có NaN trong MAE")
    check((df["R²_test"] <= 1.0).all(),       f"Horizon +{h}m: R² ≤ 1.0")
    # XGBoost phải tốt hơn Persistence ít nhất về MAE
    mae_xgb  = df.loc["XGBoost", "MAE_test (°C)"]
    mae_pers = df.loc["Persistence", "MAE_test (°C)"]
    check(mae_xgb <= mae_pers * 1.5,         f"Horizon +{h}m: XGBoost MAE <= 1.5x Persistence")

# ── Test Group 2: get_best_model ──────────────────────────────────────────
print("\n" + "=" * 60)
print("  TEST GROUP 2: get_best_model")
print("=" * 60)

for h in [10, 30, 60]:
    model_obj, model_name = bench.get_best_model(horizon=h)
    check(model_obj is not None,              f"+{h}m: best_model không None")
    check(isinstance(model_name, str),        f"+{h}m: best_model_name là string")
    check(len(model_name) > 0,               f"+{h}m: best_model_name không rỗng")

# ── Test Group 3: Model files đã lưu ─────────────────────────────────────
print("\n" + "=" * 60)
print("  TEST GROUP 3: Model files (.joblib)")
print("=" * 60)

model_dir = Path(cfg.model_dir)
for h in [10, 30, 60]:
    for name in ["Ridge", "Lasso", "RandomForest", "XGBoost"]:
        fpath = model_dir / f"{name}_h{h}min.joblib"
        check(fpath.exists(), f"{name}_h{h}min.joblib tồn tại")

# Load lại model và test predict
for h in [10, 30, 60]:
    m = load_trained_model("XGBoost", horizon=h)
    check(m is not None, f"Load XGBoost h{h}: OK")
    try:
        preds = m.predict(X_test.iloc[:5])
        check(len(preds) == 5, f"XGBoost h{h}: predict 5 điểm thành công")
    except Exception as e:
        check(False, f"XGBoost h{h}: predict thất bại — {e}")

# ── Test Group 4: Export JSON ────────────────────────────────────────────
print("\n" + "=" * 60)
print("  TEST GROUP 4: export_results_json")
print("=" * 60)

import json, tempfile
with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
    tmp_path = f.name

bench.export_results_json(tmp_path)
check(Path(tmp_path).exists(), "File JSON đã được tạo")

with open(tmp_path, encoding="utf-8") as f:
    data = json.load(f)
check("horizon_10min" in data,  "JSON có key 'horizon_10min'")
check("XGBoost" in data["horizon_10min"], "JSON có kết quả XGBoost")
check("mae_test" in data["horizon_10min"]["XGBoost"], "JSON có trường mae_test")
os.unlink(tmp_path)

# ── Kết quả ──────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"  KẾT QUẢ: {PASSED} PASS — {FAILED} FAIL")
print("=" * 60)

bench.print_report()

if FAILED == 0:
    print("\n🎉 Tất cả test PASS! ML-03 sẵn sàng.")
else:
    print(f"\n⚠️  {FAILED} test thất bại.")
    sys.exit(1)
