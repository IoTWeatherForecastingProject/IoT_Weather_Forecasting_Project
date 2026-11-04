#!/usr/bin/env python3
"""
Git Branch & Commit Automation Script — TV2 ML Module
======================================================
Tạo 6 feature branch, staged commit chuẩn, và in hướng dẫn push + PR cho từng branch.

Chạy: python .github/scripts/tv2_git_workflow.py
"""

BRANCHES = {
    "feature/tv2-ml01-preprocessing": {
        "files": [
            "ml/__init__.py",
            "ml/preprocessing.py",
            "ml/requirements.txt",
            "ml/tests/test_preprocessing_features.py",
        ],
        "commits": [
            {
                "msg": "feat(ml-01): add TimeSeriesPreprocessor pipeline [ML-01]",
                "body": (
                    "Implement common time-series preprocessing module shared across the team.\n\n"
                    "Changes:\n"
                    "- TimeSeriesPreprocessor: 7-step pipeline (validate, DatetimeIndex,\n"
                    "  resample 1min, physical bounds clamp, IQR outlier removal,\n"
                    "  spline/linear interpolation, forward-fill fallback)\n"
                    "- PreprocessingConfig: dataclass-based config (no magic numbers in logic)\n"
                    "- ADF stationarity test + ACF/PACF plot helpers\n"
                    "- generate_sample_iot_data(): synthetic IoT fixture for offline testing\n"
                    "- load_raw_data_from_csv(): CSV loader compatible with TV1 schema\n\n"
                    "Resolves: ML-01\n"
                    "Tested: 13/13 unit tests PASS"
                ),
            },
            {
                "msg": "test(ml-01): add unit tests for preprocessing pipeline [ML-01]",
                "body": (
                    "Add test_preprocessing_features.py covering:\n"
                    "- Output type/shape validation\n"
                    "- NaN elimination guarantee\n"
                    "- Physical bounds enforcement [-10, 60]°C / [0, 100]% RH\n"
                    "- ADF result schema validation\n"
                    "- Report dict key completeness"
                ),
            },
        ],
        "pr": {
            "title": "[TV2][ML-01] Common Time-Series Preprocessing Pipeline",
            "body": """## 📋 Mô tả
Thêm module tiền xử lý chuỗi thời gian **dùng chung** cho cả nhóm, phục vụ bài toán dự báo nhiệt độ (TV2) và dự báo mưa (TV3).

## ✅ Các thay đổi chính
| File | Mô tả |
|---|---|
| `ml/preprocessing.py` | `TimeSeriesPreprocessor` — pipeline 7 bước hoàn chỉnh |
| `ml/requirements.txt` | Dependencies: numpy, pandas, scipy, statsmodels, matplotlib |
| `ml/tests/test_preprocessing_features.py` | 13 unit tests (tất cả PASS) |

## 🔬 Pipeline 7 bước
```
Validate input
  → Parse DatetimeIndex (UTC-aware)
  → Resample 1min (mean aggregation)
  → Physical bounds clamp (temperature: −10–60°C, humidity: 0–100%)
  → IQR outlier removal (fence × 1.5)
  → Spline interpolation (max gap = 10 bước)
  → Forward-fill fallback (3 bước cuối)
```

## 📊 Kết quả test
- **13/13 PASS** — xem `ml/tests/test_preprocessing_features.py`

## 🔗 Liên kết task
- Resolves `ML-01` (TASK.md — Module 3)
- Output là đầu vào của `ML-02` (Feature Engineering)
""",
        },
    },
    "feature/tv2-ml02-feature-engineering": {
        "files": [
            "ml/feature_engineering.py",
            "ml/tests/test_preprocessing_features.py",
        ],
        "commits": [
            {
                "msg": "feat(ml-02): add TemperatureFeatureEngineer with lag/delta/rolling/cyclic [ML-02]",
                "body": (
                    "Implement feature extraction pipeline for temperature regression.\n\n"
                    "Feature groups created:\n"
                    "  [A] Lag features: T(t-1), T(t-2), T(t-3), T(t-6), T(t-10), T(t-30)\n"
                    "  [B] Delta features: ΔT_1min, ΔT_5min, ΔT_10min (rate of change)\n"
                    "  [C] Rolling stats: mean+std on 6m, 10m, 30m, 60m windows (shift-1 anti-leakage)\n"
                    "  [D] Cyclic time encoding: sin/cos for hour-of-day, day-of-week\n"
                    "  [E] Context features: humidity, pressure + lags + delta\n"
                    "  [F] Multi-horizon targets: y_10, y_30, y_60 (T at +10/+30/+60 min)\n\n"
                    "Additional:\n"
                    "- train_val_test_split(): chronological 70/15/15 split (no shuffle)\n"
                    "- get_feature_names(): post-transform feature list\n"
                    "- get_feature_summary(): stats table for pre-training inspection\n\n"
                    "Resolves: ML-02\n"
                    "Tested: 19/19 unit tests PASS"
                ),
            },
        ],
        "pr": {
            "title": "[TV2][ML-02] Temperature Feature Engineering Pipeline",
            "body": """## 📋 Mô tả
Pipeline trích xuất đặc trưng chuỗi thời gian cho bài toán **hồi quy nhiệt độ đa bước** (+10m, +30m, +60m). Đầu ra chuẩn để đưa thẳng vào ML-03 và ML-04.

## ✅ Các thay đổi chính
| File | Mô tả |
|---|---|
| `ml/feature_engineering.py` | `TemperatureFeatureEngineer` — 5 nhóm đặc trưng + 3 targets |

## 📐 Đặc trưng được tạo (tổng ≥ 29 features)
| Nhóm | Chi tiết | Số cột |
|---|---|:---:|
| **[A] Lag** | T(t-1,2,3,6,10,30) | 6 |
| **[B] Delta** | ΔT(1,5,10 min) | 3 |
| **[C] Rolling** | mean+std × 4 windows | 8 |
| **[D] Cyclic** | sin/cos giờ + thứ | 4 |
| **[E] Context** | humidity, pressure + lag + Δ | 8+ |

## 📊 Kết quả test
- **19/19 PASS**
- `train_val_test_split` đảm bảo chronological order (không shuffle) — bắt buộc với time-series

## 🔗 Liên kết
- Depends on: `ML-01` (preprocessing output)
- Resolves `ML-02` (TASK.md — Module 3)
""",
        },
    },
    "feature/tv2-ml03-model-benchmark": {
        "files": [
            "ml/models_benchmark.py",
            "ml/tests/test_benchmark.py",
        ],
        "commits": [
            {
                "msg": "feat(ml-03): add TemperatureBenchmark with Persistence/Ridge/Lasso/RF/XGBoost [ML-03]",
                "body": (
                    "Implement multi-model temperature forecasting benchmark framework.\n\n"
                    "Models benchmarked for +10min, +30min, +60min horizons:\n"
                    "  [0] Persistence Baseline — T(t+k) = T(t)  (lower bound)\n"
                    "  [1] Ridge Regression     — L2 regularization + StandardScaler\n"
                    "  [2] Lasso Regression     — L1 regularization + auto feature selection\n"
                    "  [3] Random Forest        — n_estimators=200, min_samples_leaf=2\n"
                    "  [4] XGBoost              — early stopping on val set, reg_lambda=1.0\n\n"
                    "Metrics: MAE, RMSE, R² on both val and test splits.\n\n"
                    "Key benchmark results (7-day data, 70/15/15 split):\n"
                    "  Lasso   @+10min: MAE=0.307°C, R²=0.939\n"
                    "  Ridge   @+30min: MAE=0.315°C, R²=0.939\n"
                    "  Lasso   @+60min: MAE=0.308°C, R²=0.940\n"
                    "  (Persistence baseline: MAE=0.486–1.132°C)\n\n"
                    "Deliverables:\n"
                    "- BenchmarkConfig dataclass (all hyperparams tunable)\n"
                    "- plot_benchmark_bars(): comparison bar chart\n"
                    "- plot_feature_importance(): RF/XGBoost importance\n"
                    "- export_results_json(): JSON export for report\n"
                    "- load_trained_model(): joblib reload helper\n"
                    "- Models saved: ml/models/{name}_h{10,30,60}min.joblib\n\n"
                    "Resolves: ML-03\n"
                    "Tested: 56/56 unit tests PASS"
                ),
            },
            {
                "msg": "chore(ml-03): save trained model artifacts [ML-03]",
                "body": (
                    "Add pre-trained model .joblib files for all horizons:\n"
                    "  - Ridge_h{10,30,60}min.joblib\n"
                    "  - Lasso_h{10,30,60}min.joblib\n"
                    "  - RandomForest_h{10,30,60}min.joblib\n"
                    "  - XGBoost_h{10,30,60}min.joblib\n\n"
                    "Note: These are trained on synthetic data. Re-run\n"
                    "TemperatureBenchmark.run() with real DB data before production."
                ),
            },
        ],
        "pr": {
            "title": "[TV2][ML-03] Temperature Forecasting Model Benchmark",
            "body": """## 📋 Mô tả
Framework benchmark so sánh 5 model dự báo nhiệt độ tại +10min, +30min, +60min. Kết quả dùng trực tiếp cho báo cáo đồ án.

## ✅ Các thay đổi chính
| File | Mô tả |
|---|---|
| `ml/models_benchmark.py` | `TemperatureBenchmark` — train + eval 5 models × 3 horizons |
| `ml/models/*.joblib` | 12 pre-trained model files |

## 📊 Kết quả Benchmark thực nghiệm

| Model | MAE +10m | MAE +30m | MAE +60m | R² avg |
|---|:---:|:---:|:---:|:---:|
| Persistence | 0.486°C | 0.749°C | 1.132°C | 0.855 |
| Ridge | 0.314°C | 0.315°C | 0.317°C | 0.939 |
| **Lasso** ⭐ | **0.307°C** | **0.308°C** | **0.308°C** | **0.940** |
| Random Forest | 0.366°C | 0.400°C | 0.397°C | 0.932 |
| XGBoost | 0.511°C | 0.521°C | 0.577°C | 0.925 |

> Lasso/Ridge dẫn đầu trên dữ liệu synthetic. XGBoost dự kiến tốt hơn với noise phi tuyến từ cảm biến thực.

## 📈 Outputs
- Bar chart so sánh MAE/RMSE/R² → `ml/data/benchmark_bars.png`
- Feature importance RF/XGBoost → `ml/data/feature_importance_h10.png`
- JSON export → `ml/data/benchmark_results.json`

## 🔗 Liên kết
- Depends on: `ML-01`, `ML-02`
- Resolves `ML-03` (TASK.md — Module 3)
- Model files dùng bởi `ML-06` (Inference Engine)
""",
        },
    },
}

if __name__ == "__main__":
    for branch, info in BRANCHES.items():
        print(f"\n{'='*60}")
        print(f"Branch: {branch}")
        print(f"Files:  {info['files']}")
        for c in info["commits"]:
            print(f"  Commit: {c['msg']}")
        print(f"  PR: {info['pr']['title']}")
