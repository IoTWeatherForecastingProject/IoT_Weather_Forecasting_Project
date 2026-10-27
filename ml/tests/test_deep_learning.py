"""
Test nhanh ML-04 — LSTM/GRU Deep Learning
==========================================
Chay: python -X utf8 ml/tests/test_deep_learning.py
"""

import sys, os, io
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from pathlib import Path
import numpy as np
import pandas as pd
import torch

from ml.preprocessing import (
    TimeSeriesPreprocessor, PreprocessingConfig, generate_sample_iot_data
)
from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig
from ml.deep_learning import (
    DeepLearningConfig, DeepForecastModel, SlidingWindowDataset,
    DeepLearningExperiment, load_deep_model
)

PASSED = 0
FAILED = 0

def check(condition: bool, name: str) -> None:
    global PASSED, FAILED
    mark = "PASS" if condition else "FAIL"
    icon = "OK" if condition else "!!"
    print(f"  [{icon}] {mark}: {name}")
    if condition: PASSED += 1
    else: FAILED += 1

# ── Setup: 3 ngày dữ liệu (nhanh) ─────────────────────────────────────────
print("\n" + "=" * 58)
print("  Chuan bi du lieu (3 ngay)...")
print("=" * 58)

df_raw   = generate_sample_iot_data(n_minutes=60 * 24 * 3, seed=99)
prep     = TimeSeriesPreprocessor(PreprocessingConfig())
df_clean = prep.fit_transform(df_raw)

feat_cfg = FeatureConfig(lag_steps=[1,2,3,6], delta_steps=[1,5],
                          rolling_windows=[6,30], forecast_horizons=[10,30,60])
engineer    = TemperatureFeatureEngineer(feat_cfg)
df_features = engineer.fit_transform(df_clean)
X, y_dict   = engineer.get_Xy(df_features)
X_train, X_val, X_test, _, _, _ = engineer.train_val_test_split(X, y_dict["y_10"])
print(f"  Train={len(X_train)}, Val={len(X_val)}, Test={len(X_test)}")

# ── Test Group 1: SlidingWindowDataset ────────────────────────────────────
print("\n" + "=" * 58)
print("  TEST GROUP 1: SlidingWindowDataset")
print("=" * 58)

import numpy as np
N, F, W, H = 200, 10, 30, 3
dummy_X = np.random.randn(N, F).astype(np.float32)
dummy_y = np.random.randn(N, H).astype(np.float32)

ds = SlidingWindowDataset(dummy_X, dummy_y, window_size=W)
check(len(ds) == N - W,      f"Dataset length = N - W = {N - W}")
x0, y0 = ds[0]
check(x0.shape == (W, F),    f"Sample X shape = ({W}, {F})")
check(y0.shape == (H,),      f"Sample y shape = ({H},)")
check(x0.dtype == torch.float32, "X dtype = float32")
check(y0.dtype == torch.float32, "y dtype = float32")

# Edge: window_size = N-1 → 1 sample
ds_edge = SlidingWindowDataset(dummy_X, dummy_y, window_size=N-1)
check(len(ds_edge) == 1, "Edge case: window=N-1 cho 1 sample")

# ── Test Group 2: DeepForecastModel ───────────────────────────────────────
print("\n" + "=" * 58)
print("  TEST GROUP 2: DeepForecastModel (forward pass)")
print("=" * 58)

for model_type in ["LSTM", "GRU"]:
    cfg = DeepLearningConfig(
        model_type=model_type, window_size=W,
        hidden_size=32, n_layers=2, dropout=0.1,
        horizons=[10, 30, 60]
    )
    model = DeepForecastModel(n_features=F, n_horizons=H, config=cfg)
    model.eval()

    batch = torch.randn(8, W, F)   # batch_size=8
    with torch.no_grad():
        out = model(batch)
    check(out.shape == (8, H),   f"{model_type}: output shape = (8, {H})")
    check(not torch.isnan(out).any(), f"{model_type}: output không có NaN")
    check(not torch.isinf(out).any(), f"{model_type}: output không có Inf")

    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    check(n_params > 0, f"{model_type}: có tham số có thể train ({n_params:,})")

# ── Test Group 3: DeepLearningExperiment (LSTM nhanh) ─────────────────────
print("\n" + "=" * 58)
print("  TEST GROUP 3: DeepLearningExperiment — LSTM (10 epochs)")
print("=" * 58)

cfg_quick = DeepLearningConfig(
    model_type  = "LSTM",
    window_size = 20,
    hidden_size = 32,
    n_layers    = 1,
    dropout     = 0.0,
    epochs      = 10,
    batch_size  = 32,
    patience    = 5,
    horizons    = [10, 30, 60],
    save_model  = True,
    model_name  = "TestDL",
    seed        = 0,
)

exp    = DeepLearningExperiment(cfg_quick)
result = exp.run(X_train, X_val, X_test, y_dict, ml_results=None)

check("metrics"    in result, "result có key 'metrics'")
check("history"    in result, "result có key 'history'")
check("compare_df" in result, "result có key 'compare_df'")
check("model"      in result, "result có key 'model'")

metrics = result["metrics"]
check("h10" in metrics and "h30" in metrics and "h60" in metrics,
      "Có metrics cho cả 3 horizon")

for h_key in ["h10", "h30", "h60"]:
    m = metrics[h_key]
    check("mae"  in m and m["mae"]  >= 0,   f"{h_key}: MAE >= 0")
    check("rmse" in m and m["rmse"] >= 0,   f"{h_key}: RMSE >= 0")
    check("r2"   in m and m["r2"]   <= 1.0, f"{h_key}: R2 <= 1.0")

history = result["history"]
check(len(history["train_loss"]) > 0,  "History có train_loss")
check(len(history["val_loss"])   > 0,  "History có val_loss")
check(len(history["train_mae"])  > 0,  "History có train_mae")
check(all(v >= 0 for v in history["val_loss"]),  "Val loss luôn >= 0")

# ── Test Group 4: DeepLearningExperiment — GRU ────────────────────────────
print("\n" + "=" * 58)
print("  TEST GROUP 4: DeepLearningExperiment — GRU (10 epochs)")
print("=" * 58)

cfg_gru = DeepLearningConfig(
    model_type  = "GRU",
    window_size = 20,
    hidden_size = 32,
    n_layers    = 1,
    dropout     = 0.0,
    epochs      = 10,
    batch_size  = 32,
    patience    = 5,
    horizons    = [10, 30, 60],
    save_model  = True,
    model_name  = "TestDL",
    seed        = 0,
)

gru_exp    = DeepLearningExperiment(cfg_gru)
gru_result = gru_exp.run(X_train, X_val, X_test, y_dict, ml_results=None)

gru_metrics = gru_result["metrics"]
check("h10" in gru_metrics, "GRU: có metrics h10")
check(gru_metrics["h10"]["mae"] >= 0, "GRU: MAE h10 >= 0")

# ── Test Group 5: Lưu & Load model ────────────────────────────────────────
print("\n" + "=" * 58)
print("  TEST GROUP 5: Save & Load model")
print("=" * 58)

model_dir  = Path(cfg_quick.model_dir)
lstm_pt    = model_dir / "TestDL_LSTM.pt"
gru_pt     = model_dir / "TestDL_GRU.pt"

check(lstm_pt.exists(), f"TestDL_LSTM.pt tồn tại")
check(gru_pt.exists(),  f"TestDL_GRU.pt tồn tại")

# Scaler files
lstm_sx = model_dir / "TestDL_LSTM_scaler_X.joblib"
lstm_sy = model_dir / "TestDL_LSTM_scaler_y.joblib"
check(lstm_sx.exists(), "LSTM scaler_X.joblib tồn tại")
check(lstm_sy.exists(), "LSTM scaler_y.joblib tồn tại")

# Load lại và thử predict
n_features = X_train.shape[1]
n_horizons = 3
try:
    loaded_lstm = load_deep_model(n_features, n_horizons, cfg_quick)
    loaded_lstm.eval()
    dummy_batch = torch.randn(4, cfg_quick.window_size, n_features)
    with torch.no_grad():
        preds = loaded_lstm(dummy_batch)
    check(preds.shape == (4, n_horizons), f"Load LSTM: predict shape = (4, {n_horizons})")
    check(not torch.isnan(preds).any(),   "Load LSTM: predict không có NaN")
except Exception as e:
    check(False, f"Load LSTM thất bại: {e}")

# ── Test Group 6: Compare DataFrame ───────────────────────────────────────
print("\n" + "=" * 58)
print("  TEST GROUP 6: compare_df structure")
print("=" * 58)

compare_df = result["compare_df"]
check(isinstance(compare_df, pd.DataFrame),  "compare_df là DataFrame")
check("Horizon"   in compare_df.columns,     "compare_df có cột Horizon")
check("Model"     in compare_df.columns,     "compare_df có cột Model")
check("MAE (°C)"  in compare_df.columns,     "compare_df có cột MAE (°C)")
check("RMSE (°C)" in compare_df.columns,     "compare_df có cột RMSE (°C)")
check("R²"        in compare_df.columns,     "compare_df có cột R²")
check(len(compare_df) == 3, f"compare_df có 3 hàng (3 horizons, chỉ DL)")

# ── Kết quả ───────────────────────────────────────────────────────────────
print("\n" + "=" * 58)
print(f"  KET QUA: {PASSED} PASS -- {FAILED} FAIL")
print("=" * 58)

if FAILED == 0:
    print("\n  Tat ca test PASS! ML-04 san sang.")
else:
    print(f"\n  {FAILED} test that bai.")
    sys.exit(1)
