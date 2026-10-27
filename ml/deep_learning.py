"""
ML-04: LSTM / GRU Deep Learning Experimentation
================================================
Xây dựng, huấn luyện và đánh giá mạng nơ-ron hồi quy chuỗi thời gian
(LSTM và GRU) bằng PyTorch để dự báo nhiệt độ đa bước tại +10m, +30m, +60m.

Kiến trúc:
    - Input: Sliding window W bước × F đặc trưng
    - Encoder: LSTM hoặc GRU (n_layers, hidden_size, dropout)
    - Decoder: MLP head (hidden → output)
    - Multi-output: Dự báo đồng thời 3 horizon trong 1 lần forward

Pipeline:
    SlidingWindowDataset → DataLoader → DeepForecastModel (LSTM|GRU)
    → Trainer (early stopping, scheduler) → Evaluator → Comparator (vs ML-03)

Tác giả: TV2 — Time-Series AI Engineer
Dự án:   IoT Local Weather Forecasting
"""

from __future__ import annotations

import logging
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import Adam
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader, Dataset
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------
MODEL_SAVE_DIR = Path(__file__).parent / "models"
MODEL_SAVE_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
logger.info("PyTorch device: %s", DEVICE)


# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------
@dataclass
class DeepLearningConfig:
    """
    Toàn bộ siêu tham số cho thực nghiệm Deep Learning.
    Thay đổi tại đây — không sửa code logic.
    """
    # ── Mô hình ────────────────────────────────────────────────────────
    model_type: str = "LSTM"          # "LSTM" hoặc "GRU"
    window_size: int = 60             # Số bước lịch sử đưa vào (60 phút = 1 giờ)
    hidden_size: int = 128            # Số neurons ở hidden layer RNN
    n_layers: int = 2                 # Số lớp RNN stack
    dropout: float = 0.2              # Dropout giữa các lớp RNN
    mlp_hidden: int = 64              # Neurons của MLP head

    # ── Huấn luyện ─────────────────────────────────────────────────────
    epochs: int = 100
    batch_size: int = 64
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4        # L2 regularization
    patience: int = 15                # Early stopping patience
    min_delta: float = 1e-4           # Ngưỡng cải thiện tối thiểu

    # ── LR Scheduler ───────────────────────────────────────────────────
    lr_factor: float = 0.5            # Giảm LR còn lr * factor khi không cải thiện
    lr_patience: int = 7              # Số epoch chờ trước khi giảm LR

    # ── Horizon dự báo (multi-output) ──────────────────────────────────
    horizons: List[int] = field(default_factory=lambda: [10, 30, 60])

    # ── Loss weights theo horizon ────────────────────────────────────
    # Trọng số loss: +10m quan trọng hơn +60m
    horizon_weights: List[float] = field(default_factory=lambda: [1.0, 0.8, 0.6])

    # ── Xuất / lưu ─────────────────────────────────────────────────────
    save_model: bool = True
    model_dir: str = str(MODEL_SAVE_DIR)
    model_name: str = "DeepForecast"  # Prefix cho tên file lưu

    # ── Reproducibility ────────────────────────────────────────────────
    seed: int = 42


# ---------------------------------------------------------------------------
# Dataset: Sliding Window
# ---------------------------------------------------------------------------
class SlidingWindowDataset(Dataset):
    """
    PyTorch Dataset tạo các cặp (X_window, y_multi) theo cửa sổ trượt.

    Mỗi mẫu:
        X: [window_size, n_features]   — W bước lịch sử đã chuẩn hóa
        y: [n_horizons]                — Giá trị nhiệt độ tại t+10, t+30, t+60

    Args:
        features:    numpy array (T, F) — đặc trưng toàn chuỗi đã scale.
        targets:     numpy array (T, H) — target đa horizon đã chuẩn hóa.
        window_size: Số bước lịch sử W.
    """

    def __init__(
        self,
        features:    np.ndarray,
        targets:     np.ndarray,
        window_size: int,
    ) -> None:
        self.features    = torch.tensor(features,    dtype=torch.float32)
        self.targets     = torch.tensor(targets,     dtype=torch.float32)
        self.window_size = window_size

        # Số mẫu hợp lệ: từ index W-1 đến T-1
        self.n_samples = len(features) - window_size

        if self.n_samples <= 0:
            raise ValueError(
                f"Dữ liệu quá ngắn ({len(features)} bước) "
                f"so với window_size={window_size}."
            )

    def __len__(self) -> int:
        return self.n_samples

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        # Cửa sổ: bước [idx, idx+W)
        x = self.features[idx: idx + self.window_size]      # (W, F)
        y = self.targets[idx + self.window_size - 1]        # (H,)  tại bước cuối cửa sổ
        return x, y


# ---------------------------------------------------------------------------
# Mô hình Deep Learning
# ---------------------------------------------------------------------------
class DeepForecastModel(nn.Module):
    """
    Mô hình LSTM/GRU multi-output dự báo nhiệt độ đa horizon.

    Kiến trúc:
        Input (W, F)
          → RNN encoder (LSTM|GRU, n_layers, hidden)
          → Lấy hidden state cuối: (batch, hidden)
          → MLP head: hidden → mlp_hidden → n_horizons
          → Output (n_horizons,)

    Args:
        n_features:  Số đặc trưng đầu vào F.
        n_horizons:  Số horizon dự báo đồng thời.
        config:      DeepLearningConfig.
    """

    def __init__(
        self,
        n_features:  int,
        n_horizons:  int,
        config:      DeepLearningConfig,
    ) -> None:
        super().__init__()
        self.config     = config
        self.n_horizons = n_horizons
        rnn_cls = nn.LSTM if config.model_type.upper() == "LSTM" else nn.GRU

        # RNN Encoder
        self.rnn = rnn_cls(
            input_size   = n_features,
            hidden_size  = config.hidden_size,
            num_layers   = config.n_layers,
            dropout      = config.dropout if config.n_layers > 1 else 0.0,
            batch_first  = True,
        )

        # MLP Decoder head
        self.head = nn.Sequential(
            nn.Linear(config.hidden_size, config.mlp_hidden),
            nn.ReLU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.mlp_hidden, n_horizons),
        )

        # Khởi tạo trọng số (Xavier uniform — ổn định hơn default)
        self._init_weights()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (batch, window_size, n_features)

        Returns:
            out: (batch, n_horizons) — dự báo nhiệt độ đã chuẩn hóa
        """
        rnn_out, hidden = self.rnn(x)
        # Lấy hidden state của bước cuối (last timestep)
        last_hidden = rnn_out[:, -1, :]      # (batch, hidden)
        out = self.head(last_hidden)          # (batch, n_horizons)
        return out

    def _init_weights(self) -> None:
        """Khởi tạo weights RNN bằng orthogonal, bias = 0."""
        for name, param in self.rnn.named_parameters():
            if "weight_ih" in name:
                nn.init.xavier_uniform_(param.data)
            elif "weight_hh" in name:
                nn.init.orthogonal_(param.data)
            elif "bias" in name:
                param.data.fill_(0)
        for layer in self.head:
            if isinstance(layer, nn.Linear):
                nn.init.xavier_uniform_(layer.weight)
                nn.init.zeros_(layer.bias)


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------
class DeepForecastTrainer:
    """
    Trainer khép kín cho DeepForecastModel.

    Tính năng:
        - Mixed-horizon loss (weighted MSE trên 3 output)
        - Early stopping dựa trên val loss
        - ReduceLROnPlateau scheduler
        - Ghi lịch sử loss/MAE theo epoch

    Ví dụ:
    ------
    >>> trainer = DeepForecastTrainer(model, config)
    >>> history = trainer.fit(train_loader, val_loader)
    """

    def __init__(
        self,
        model:  DeepForecastModel,
        config: DeepLearningConfig,
        device: torch.device = DEVICE,
    ) -> None:
        self.model  = model.to(device)
        self.config = config
        self.device = device

        self.optimizer = Adam(
            model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )
        self.scheduler = ReduceLROnPlateau(
            self.optimizer,
            mode="min",
            factor=config.lr_factor,
            patience=config.lr_patience,
        )

        # Trọng số loss theo horizon (tensor trên device)
        w = torch.tensor(config.horizon_weights, dtype=torch.float32).to(device)
        self._horizon_weights = w / w.sum()   # Normalize

        self.history: Dict[str, List[float]] = {
            "train_loss": [], "val_loss": [],
            "train_mae":  [], "val_mae":  [],
            "lr":         [],
        }

    def fit(
        self,
        train_loader: DataLoader,
        val_loader:   DataLoader,
    ) -> Dict[str, List[float]]:
        """
        Huấn luyện model với early stopping.

        Returns:
            history dict: {train_loss, val_loss, train_mae, val_mae, lr}
        """
        best_val_loss = float("inf")
        patience_counter = 0
        best_state = None

        t0 = time.time()
        logger.info(
            "Bắt đầu huấn luyện %s | epochs=%d | device=%s | batch=%d",
            self.config.model_type, self.config.epochs,
            self.device, self.config.batch_size
        )

        for epoch in range(1, self.config.epochs + 1):
            # ── Train ─────────────────────────────────────────────────
            train_loss, train_mae = self._train_epoch(train_loader)

            # ── Validation ────────────────────────────────────────────
            val_loss, val_mae = self._eval_epoch(val_loader)

            # ── LR scheduler ──────────────────────────────────────────
            self.scheduler.step(val_loss)
            current_lr = self.optimizer.param_groups[0]["lr"]

            # ── Ghi history ───────────────────────────────────────────
            self.history["train_loss"].append(train_loss)
            self.history["val_loss"].append(val_loss)
            self.history["train_mae"].append(train_mae)
            self.history["val_mae"].append(val_mae)
            self.history["lr"].append(current_lr)

            # ── Log mỗi 10 epoch ──────────────────────────────────────
            if epoch % 10 == 0 or epoch == 1:
                elapsed = time.time() - t0
                logger.info(
                    "Epoch %3d/%d | train_loss=%.5f | val_loss=%.5f "
                    "| val_MAE=%.4f | lr=%.2e | %.1fs",
                    epoch, self.config.epochs,
                    train_loss, val_loss, val_mae, current_lr, elapsed
                )

            # ── Early stopping ────────────────────────────────────────
            if val_loss < best_val_loss - self.config.min_delta:
                best_val_loss    = val_loss
                patience_counter = 0
                best_state       = {
                    k: v.clone() for k, v in self.model.state_dict().items()
                }
            else:
                patience_counter += 1
                if patience_counter >= self.config.patience:
                    logger.info(
                        "Early stopping tại epoch %d (val_loss không giảm sau %d epochs).",
                        epoch, self.config.patience
                    )
                    break

        # Khôi phục trọng số tốt nhất
        if best_state is not None:
            self.model.load_state_dict(best_state)
            logger.info(
                "Đã khôi phục best model (val_loss=%.5f). "
                "Tổng thời gian: %.1fs",
                best_val_loss, time.time() - t0
            )
        return self.history

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _train_epoch(self, loader: DataLoader) -> Tuple[float, float]:
        """Một epoch train — trả về (avg_loss, avg_mae)."""
        self.model.train()
        total_loss = 0.0
        total_mae  = 0.0
        n_batches  = 0

        for x_batch, y_batch in loader:
            x_batch = x_batch.to(self.device)
            y_batch = y_batch.to(self.device)

            self.optimizer.zero_grad()
            y_pred = self.model(x_batch)              # (B, H)

            # Weighted MSE trên từng horizon
            mse_per_horizon = ((y_pred - y_batch) ** 2).mean(dim=0)   # (H,)
            loss = (mse_per_horizon * self._horizon_weights).sum()

            loss.backward()
            # Gradient clipping để tránh exploding gradient trong RNN
            nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            # MAE trung bình trên tất cả horizon
            mae = (y_pred - y_batch).abs().mean().item()

            total_loss += loss.item()
            total_mae  += mae
            n_batches  += 1

        return total_loss / n_batches, total_mae / n_batches

    def _eval_epoch(self, loader: DataLoader) -> Tuple[float, float]:
        """Một epoch evaluation — trả về (avg_loss, avg_mae)."""
        self.model.eval()
        total_loss = 0.0
        total_mae  = 0.0
        n_batches  = 0

        with torch.no_grad():
            for x_batch, y_batch in loader:
                x_batch = x_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                y_pred = self.model(x_batch)

                mse_per_horizon = ((y_pred - y_batch) ** 2).mean(dim=0)
                loss = (mse_per_horizon * self._horizon_weights).sum()
                mae  = (y_pred - y_batch).abs().mean().item()

                total_loss += loss.item()
                total_mae  += mae
                n_batches  += 1

        return total_loss / n_batches, total_mae / n_batches


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------
class DeepForecastEvaluator:
    """
    Đánh giá model đã huấn luyện trên test set và so sánh với kết quả ML-03.

    Ví dụ:
    ------
    >>> evaluator = DeepForecastEvaluator(model, scaler_y, config)
    >>> metrics   = evaluator.evaluate(test_loader, y_test_raw)
    >>> evaluator.compare_with_ml(benchmark_results)
    """

    def __init__(
        self,
        model:    DeepForecastModel,
        scaler_y: StandardScaler,
        config:   DeepLearningConfig,
        device:   torch.device = DEVICE,
    ) -> None:
        self.model    = model.to(device)
        self.scaler_y = scaler_y
        self.config   = config
        self.device   = device

    def predict(self, loader: DataLoader) -> np.ndarray:
        """
        Chạy inference trên DataLoader.

        Returns:
            y_pred: numpy (N, H) — đã inverse_transform về °C gốc.
        """
        self.model.eval()
        preds = []

        with torch.no_grad():
            for x_batch, _ in loader:
                x_batch = x_batch.to(self.device)
                out = self.model(x_batch).cpu().numpy()
                preds.append(out)

        y_pred_scaled = np.vstack(preds)                          # (N, H)
        y_pred = self.scaler_y.inverse_transform(y_pred_scaled)   # (N, H) °C
        return y_pred

    def evaluate(
        self,
        loader:      DataLoader,
        y_true_raw:  np.ndarray,   # (N, H) — °C gốc (không scale)
    ) -> Dict[str, Dict[str, float]]:
        """
        Tính MAE, RMSE, R² cho từng horizon.

        Returns:
            metrics: {'h10': {mae, rmse, r2}, 'h30': ..., 'h60': ...}
        """
        y_pred = self.predict(loader)     # (N, H)

        # Cắt y_true về cùng N với y_pred (do sliding window cắt đầu chuỗi)
        n = min(len(y_pred), len(y_true_raw))
        y_pred    = y_pred[:n]
        y_true    = y_true_raw[-n:]       # Lấy đoạn cuối tương ứng

        metrics: Dict[str, Dict[str, float]] = {}
        for i, h in enumerate(self.config.horizons):
            yt = y_true[:, i]
            yp = y_pred[:, i]
            metrics[f"h{h}"] = {
                "mae":  float(mean_absolute_error(yt, yp)),
                "rmse": float(np.sqrt(mean_squared_error(yt, yp))),
                "r2":   float(r2_score(yt, yp)),
            }
            logger.info(
                "[%s] +%dmin → MAE=%.4f | RMSE=%.4f | R²=%.4f",
                self.config.model_type, h,
                metrics[f"h{h}"]["mae"],
                metrics[f"h{h}"]["rmse"],
                metrics[f"h{h}"]["r2"],
            )
        return metrics

    def compare_with_ml(
        self,
        dl_metrics: Dict[str, Dict[str, float]],
        ml_results: Optional[Dict[int, pd.DataFrame]] = None,
    ) -> pd.DataFrame:
        """
        Tạo bảng so sánh Deep Learning vs các model ML từ ML-03.

        Args:
            dl_metrics:  Kết quả từ evaluate().
            ml_results:  Dict[horizon → DataFrame] từ TemperatureBenchmark.run().
                         Nếu None, chỉ hiển thị DL metrics.

        Returns:
            DataFrame bảng so sánh đầy đủ.
        """
        rows = []
        model_name = self.config.model_type

        for h in self.config.horizons:
            key = f"h{h}"
            m = dl_metrics.get(key, {})
            row = {
                "Horizon":  f"+{h}min",
                "Model":    model_name,
                "MAE (°C)": round(m.get("mae",  float("nan")), 4),
                "RMSE (°C)":round(m.get("rmse", float("nan")), 4),
                "R²":       round(m.get("r2",   float("nan")), 4),
            }

            # Thêm kết quả ML-03 nếu có
            if ml_results and h in ml_results:
                ml_df = ml_results[h]
                for ml_model in ml_df.index:
                    rows.append({
                        "Horizon":   f"+{h}min",
                        "Model":     ml_model,
                        "MAE (°C)":  ml_df.loc[ml_model, "MAE_test (°C)"],
                        "RMSE (°C)": ml_df.loc[ml_model, "RMSE_test (°C)"],
                        "R²":        ml_df.loc[ml_model, "R²_test"],
                    })

            rows.append(row)

        compare_df = pd.DataFrame(rows)
        return compare_df


# ---------------------------------------------------------------------------
# Lớp tổng hợp: chạy toàn bộ thực nghiệm DL
# ---------------------------------------------------------------------------
class DeepLearningExperiment:
    """
    Lớp orchestrator chạy toàn bộ thực nghiệm DL:
        1. Chuẩn hóa dữ liệu (StandardScaler riêng cho X và y)
        2. Tạo SlidingWindowDataset + DataLoader
        3. Khởi tạo model (LSTM hoặc GRU)
        4. Huấn luyện với DeepForecastTrainer
        5. Đánh giá với DeepForecastEvaluator
        6. Vẽ đồ thị Loss curve & So sánh với ML-03
        7. Lưu model

    Ví dụ sử dụng:
    --------------
    >>> exp = DeepLearningExperiment(config)
    >>> results = exp.run(X_train, X_val, X_test, y_dict, ml_benchmark_results)
    >>> exp.plot_loss_curves()
    >>> exp.plot_comparison_chart(results["compare_df"])
    """

    def __init__(self, config: Optional[DeepLearningConfig] = None) -> None:
        self.config  = config or DeepLearningConfig()
        self.model:   Optional[DeepForecastModel] = None
        self.trainer: Optional[DeepForecastTrainer] = None
        self.history: Dict = {}

        self.scaler_X = StandardScaler()
        self.scaler_y = StandardScaler()

        # Cố định seed để reproducibility
        self._set_seed(self.config.seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        X_train: pd.DataFrame,
        X_val:   pd.DataFrame,
        X_test:  pd.DataFrame,
        y_dict:  Dict[str, pd.Series],
        ml_results: Optional[Dict[int, pd.DataFrame]] = None,
    ) -> Dict:
        """
        Chạy toàn bộ thực nghiệm DL.

        Args:
            X_train/val/test: Ma trận đặc trưng đã split (output của ML-02).
            y_dict:           {'y_10': Series, 'y_30': Series, 'y_60': Series}.
            ml_results:       Kết quả benchmark từ ML-03 (để so sánh).

        Returns:
            Dict với keys: metrics, compare_df, history, model
        """
        logger.info("=" * 60)
        logger.info("BẮT ĐẦU THỰC NGHIỆM DEEP LEARNING — %s", self.config.model_type)
        logger.info("=" * 60)

        # ── 1. Chuẩn bị dữ liệu ──────────────────────────────────────
        X_tr_sc, X_val_sc, X_te_sc, y_tr, y_val, y_te = \
            self._prepare_data(X_train, X_val, X_test, y_dict)

        # ── 2. DataLoader ────────────────────────────────────────────
        train_loader, val_loader, test_loader = self._build_dataloaders(
            X_tr_sc, X_val_sc, X_te_sc, y_tr, y_val, y_te
        )

        # ── 3. Khởi tạo model ────────────────────────────────────────
        n_features  = X_tr_sc.shape[1]
        n_horizons  = len(self.config.horizons)
        self.model  = DeepForecastModel(n_features, n_horizons, self.config)
        n_params    = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        logger.info(
            "Mô hình %s: %d parameters | hidden=%d | layers=%d | window=%d",
            self.config.model_type, n_params,
            self.config.hidden_size, self.config.n_layers, self.config.window_size
        )

        # ── 4. Huấn luyện ────────────────────────────────────────────
        self.trainer = DeepForecastTrainer(self.model, self.config)
        self.history = self.trainer.fit(train_loader, val_loader)

        # ── 5. Đánh giá ──────────────────────────────────────────────
        # y_test raw: (N_test, H) — giá trị °C gốc (chưa scale)
        y_te_raw = self.scaler_y.inverse_transform(y_te)
        evaluator = DeepForecastEvaluator(self.model, self.scaler_y, self.config)
        dl_metrics = evaluator.evaluate(test_loader, y_te_raw)

        # ── 6. So sánh với ML-03 ─────────────────────────────────────
        compare_df = evaluator.compare_with_ml(dl_metrics, ml_results)
        self._print_comparison(compare_df)

        # ── 7. Lưu model ─────────────────────────────────────────────
        if self.config.save_model:
            self._save(evaluator)

        return {
            "metrics":    dl_metrics,
            "compare_df": compare_df,
            "history":    self.history,
            "model":      self.model,
        }

    def plot_loss_curves(
        self,
        figsize: Tuple[int, int] = (14, 5),
        save_path: Optional[str] = None,
    ) -> plt.Figure:
        """
        Vẽ đồ thị train/val Loss và MAE theo epoch.
        Bao gồm annotation điểm dừng (early stopping epoch).
        """
        if not self.history:
            raise RuntimeError("Chạy .run() trước khi vẽ biểu đồ.")

        epochs_ran  = len(self.history["train_loss"])
        x           = range(1, epochs_ran + 1)
        best_epoch  = int(np.argmin(self.history["val_loss"])) + 1

        fig, axes = plt.subplots(1, 3, figsize=figsize)
        model_name = self.config.model_type

        # ── Loss ──────────────────────────────────────────────────────
        axes[0].plot(x, self.history["train_loss"], label="Train Loss",
                     color="steelblue", linewidth=1.3)
        axes[0].plot(x, self.history["val_loss"],   label="Val Loss",
                     color="tomato",    linewidth=1.3)
        axes[0].axvline(best_epoch, color="gold", linestyle="--",
                        linewidth=1.2, label=f"Best Epoch ({best_epoch})")
        axes[0].set_title(f"{model_name} — Loss (Weighted MSE)", fontweight="bold")
        axes[0].set_xlabel("Epoch"); axes[0].set_ylabel("Loss")
        axes[0].legend(fontsize=8); axes[0].grid(True, alpha=0.3)

        # ── MAE ───────────────────────────────────────────────────────
        axes[1].plot(x, self.history["train_mae"], label="Train MAE",
                     color="steelblue", linewidth=1.3)
        axes[1].plot(x, self.history["val_mae"],   label="Val MAE",
                     color="tomato",    linewidth=1.3)
        axes[1].axvline(best_epoch, color="gold", linestyle="--",
                        linewidth=1.2, label=f"Best Epoch ({best_epoch})")
        axes[1].set_title(f"{model_name} — MAE (scaled)", fontweight="bold")
        axes[1].set_xlabel("Epoch"); axes[1].set_ylabel("MAE")
        axes[1].legend(fontsize=8); axes[1].grid(True, alpha=0.3)

        # ── Learning Rate ─────────────────────────────────────────────
        axes[2].plot(x, self.history["lr"], color="purple", linewidth=1.3)
        axes[2].set_title(f"{model_name} — Learning Rate", fontweight="bold")
        axes[2].set_xlabel("Epoch"); axes[2].set_ylabel("LR")
        axes[2].set_yscale("log"); axes[2].grid(True, alpha=0.3)

        plt.suptitle(f"Training Curves — {model_name}", fontsize=13,
                     fontweight="bold")
        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Đã lưu loss curves → %s", save_path)
        return fig

    def plot_comparison_chart(
        self,
        compare_df: pd.DataFrame,
        metric: str = "MAE (°C)",
        figsize: Tuple[int, int] = (15, 5),
        save_path: Optional[str] = None,
    ) -> plt.Figure:
        """
        Vẽ biểu đồ so sánh DL vs ML theo từng horizon.
        DL bar được tô màu nổi bật.
        """
        horizons = compare_df["Horizon"].unique()
        n_h = len(horizons)

        fig, axes = plt.subplots(1, n_h, figsize=figsize, sharey=False)
        if n_h == 1:
            axes = [axes]

        palette = {
            "Persistence": "#aec6cf",
            "Ridge":       "#90ee90",
            "Lasso":       "#77dd77",
            "RandomForest":"#fdfd96",
            "XGBoost":     "#ffb347",
            "LSTM":        "#c23b22",
            "GRU":         "#c23b22",
        }

        for ax, h_label in zip(axes, horizons):
            sub = compare_df[compare_df["Horizon"] == h_label].copy()
            sub = sub.sort_values(metric)
            colors = [palette.get(m, "#cccccc") for m in sub["Model"]]

            bars = ax.bar(sub["Model"], sub[metric], color=colors,
                          edgecolor="white", width=0.6)

            # Ghi giá trị lên cột
            for bar in bars:
                h = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2,
                        h * 1.01, f"{h:.3f}",
                        ha="center", va="bottom", fontsize=8)

            ax.set_title(f"Horizon {h_label}", fontsize=10, fontweight="bold")
            ax.set_xlabel("Model")
            ax.set_ylabel(metric)
            ax.set_xticklabels(sub["Model"], rotation=30, ha="right", fontsize=8)
            ax.grid(axis="y", alpha=0.3, linestyle="--")
            ax.spines[["top", "right"]].set_visible(False)

        dl_model = self.config.model_type
        plt.suptitle(
            f"So sánh {dl_model} vs ML Models — {metric}",
            fontsize=12, fontweight="bold"
        )
        plt.tight_layout()

        if save_path:
            fig.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Đã lưu biểu đồ so sánh → %s", save_path)
        return fig

    def save_scalers(self, path_prefix: str) -> None:
        """Lưu scaler_X và scaler_y để dùng trong inference engine (ML-06)."""
        joblib.dump(self.scaler_X, f"{path_prefix}_scaler_X.joblib")
        joblib.dump(self.scaler_y, f"{path_prefix}_scaler_y.joblib")
        logger.info("Đã lưu scalers → %s_scaler_[X|y].joblib", path_prefix)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _prepare_data(
        self,
        X_train: pd.DataFrame,
        X_val:   pd.DataFrame,
        X_test:  pd.DataFrame,
        y_dict:  Dict[str, pd.Series],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray,
               np.ndarray, np.ndarray, np.ndarray]:
        """
        Scale X và y rồi stack y theo từng horizon thành ma trận (N, H).

        Lưu ý: fit scaler chỉ trên train set, transform cả 3 split.
        """
        # Stack targets: (N, H) với H = số horizon
        def stack_y(X_split: pd.DataFrame) -> np.ndarray:
            arrs = []
            for h in self.config.horizons:
                key = f"y_{h}"
                if key not in y_dict:
                    raise KeyError(f"Thiếu target '{key}'.")
                arrs.append(y_dict[key].loc[X_split.index].values)
            return np.stack(arrs, axis=1)    # (N, H)

        y_tr  = stack_y(X_train)
        y_val = stack_y(X_val)
        y_te  = stack_y(X_test)

        # Scale X
        X_tr_sc  = self.scaler_X.fit_transform(X_train.values)
        X_val_sc = self.scaler_X.transform(X_val.values)
        X_te_sc  = self.scaler_X.transform(X_test.values)

        # Scale y (chỉ scale nhiệt độ — đơn vị °C)
        # scaler_y fit trên shape (N, H) → inverse_transform dùng lại
        y_tr_sc  = self.scaler_y.fit_transform(y_tr)
        y_val_sc = self.scaler_y.transform(y_val)
        y_te_sc  = self.scaler_y.transform(y_te)

        logger.info(
            "Dữ liệu DL: train=%d | val=%d | test=%d | features=%d | horizons=%d",
            len(X_tr_sc), len(X_val_sc), len(X_te_sc),
            X_tr_sc.shape[1], y_tr_sc.shape[1]
        )
        return X_tr_sc, X_val_sc, X_te_sc, y_tr_sc, y_val_sc, y_te_sc

    def _build_dataloaders(
        self,
        X_tr:  np.ndarray, X_val: np.ndarray, X_te:  np.ndarray,
        y_tr:  np.ndarray, y_val: np.ndarray, y_te:  np.ndarray,
    ) -> Tuple[DataLoader, DataLoader, DataLoader]:
        """Tạo SlidingWindowDataset và wrap vào DataLoader."""
        W = self.config.window_size
        B = self.config.batch_size

        train_ds = SlidingWindowDataset(X_tr,  y_tr,  W)
        val_ds   = SlidingWindowDataset(X_val, y_val, W)
        test_ds  = SlidingWindowDataset(X_te,  y_te,  W)

        # Số worker=0 trên Windows để tránh lỗi multiprocessing
        n_workers = 0

        train_loader = DataLoader(train_ds, batch_size=B, shuffle=False,
                                  num_workers=n_workers, pin_memory=False)
        val_loader   = DataLoader(val_ds,   batch_size=B, shuffle=False,
                                  num_workers=n_workers, pin_memory=False)
        test_loader  = DataLoader(test_ds,  batch_size=B, shuffle=False,
                                  num_workers=n_workers, pin_memory=False)

        logger.info(
            "DataLoader: train=%d | val=%d | test=%d mẫu (window=%d)",
            len(train_ds), len(val_ds), len(test_ds), W
        )
        return train_loader, val_loader, test_loader

    def _save(self, evaluator: DeepForecastEvaluator) -> None:
        """Lưu model weights (PyTorch) và scalers (joblib)."""
        save_dir  = Path(self.config.model_dir)
        name      = f"{self.config.model_name}_{self.config.model_type}"
        pt_path   = save_dir / f"{name}.pt"
        sc_prefix = str(save_dir / name)

        torch.save(self.model.state_dict(), pt_path)
        logger.info("Đã lưu model weights → %s", pt_path)

        evaluator.scaler_y  # đảm bảo scaler đã fit
        self.save_scalers(sc_prefix)

    @staticmethod
    def _print_comparison(df: pd.DataFrame) -> None:
        """In bảng so sánh đẹp ra console."""
        print("\n" + "=" * 65)
        print("  SO SÁNH DEEP LEARNING vs ML MODELS")
        print("=" * 65)
        for h in df["Horizon"].unique():
            print(f"\n  Horizon {h}:")
            sub = df[df["Horizon"] == h].set_index("Model")
            print(sub.to_string())
        print()

    @staticmethod
    def _set_seed(seed: int) -> None:
        """Cố định seed cho reproducibility."""
        torch.manual_seed(seed)
        np.random.seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)


# ---------------------------------------------------------------------------
# Hàm tiện ích: load model đã lưu để inference
# ---------------------------------------------------------------------------
def load_deep_model(
    n_features:  int,
    n_horizons:  int,
    config:      DeepLearningConfig,
    model_dir:   str = str(MODEL_SAVE_DIR),
) -> DeepForecastModel:
    """
    Load model PyTorch đã lưu từ file .pt.

    Args:
        n_features: Số đặc trưng đầu vào.
        n_horizons: Số horizon.
        config:     Config phải khớp với lúc huấn luyện.
        model_dir:  Thư mục chứa file .pt.

    Returns:
        DeepForecastModel đã load weights, ở eval mode.
    """
    name   = f"{config.model_name}_{config.model_type}"
    path   = Path(model_dir) / f"{name}.pt"

    if not path.exists():
        raise FileNotFoundError(f"Model file không tìm thấy: {path}")

    model = DeepForecastModel(n_features, n_horizons, config)
    model.load_state_dict(torch.load(path, map_location="cpu"))
    model.eval()
    logger.info("Đã load DL model: %s", path)
    return model


# ---------------------------------------------------------------------------
# Script chạy thử nhanh
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from ml.preprocessing import (
        TimeSeriesPreprocessor, PreprocessingConfig, generate_sample_iot_data
    )
    from ml.feature_engineering import TemperatureFeatureEngineer, FeatureConfig
    from ml.models_benchmark import TemperatureBenchmark, BenchmarkConfig

    print("=" * 65)
    print("  ML-04: Deep Learning (LSTM/GRU) — Quick Test")
    print("=" * 65)

    # 1. Dữ liệu 14 ngày (đủ để DL học được chu kỳ ngày đêm)
    print("\n[1/6] Tạo dữ liệu 14 ngày...")
    df_raw  = generate_sample_iot_data(n_minutes=60 * 24 * 14, seed=42)
    prep    = TimeSeriesPreprocessor(PreprocessingConfig())
    df_clean = prep.fit_transform(df_raw)

    # 2. Feature Engineering
    print("[2/6] Feature Engineering...")
    feat_cfg = FeatureConfig(
        lag_steps=[1, 2, 3, 6, 10, 30],
        delta_steps=[1, 5, 10],
        rolling_windows=[6, 10, 30, 60],
        forecast_horizons=[10, 30, 60],
    )
    engineer    = TemperatureFeatureEngineer(feat_cfg)
    df_features = engineer.fit_transform(df_clean)
    X, y_dict   = engineer.get_Xy(df_features)
    X_train, X_val, X_test, _, _, _ = engineer.train_val_test_split(X, y_dict["y_10"])
    print(f"     Train={len(X_train)}, Val={len(X_val)}, Test={len(X_test)}")

    # 3. ML-03 Benchmark (để so sánh)
    print("[3/6] Chạy ML-03 Benchmark (để lấy baseline so sánh)...")
    ml_cfg    = BenchmarkConfig(rf_n_estimators=50, xgb_n_estimators=80,
                                horizons=[10, 30, 60], save_models=False)
    benchmark = TemperatureBenchmark(ml_cfg)
    ml_tables = benchmark.run(X_train, X_val, X_test, y_dict)

    # 4. LSTM Experiment
    print("\n[4/6] Huấn luyện LSTM...")
    lstm_cfg = DeepLearningConfig(
        model_type   = "LSTM",
        window_size  = 30,    # 30 phút nhìn lại
        hidden_size  = 64,
        n_layers     = 2,
        dropout      = 0.2,
        epochs       = 60,
        batch_size   = 64,
        patience     = 10,
        horizons     = [10, 30, 60],
        save_model   = True,
        model_name   = "DeepForecast",
    )
    lstm_exp    = DeepLearningExperiment(lstm_cfg)
    lstm_result = lstm_exp.run(X_train, X_val, X_test, y_dict, ml_results=ml_tables)

    # 5. GRU Experiment
    print("\n[5/6] Huấn luyện GRU...")
    gru_cfg = DeepLearningConfig(
        model_type   = "GRU",
        window_size  = 30,
        hidden_size  = 64,
        n_layers     = 2,
        dropout      = 0.2,
        epochs       = 60,
        batch_size   = 64,
        patience     = 10,
        horizons     = [10, 30, 60],
        save_model   = True,
        model_name   = "DeepForecast",
    )
    gru_exp    = DeepLearningExperiment(gru_cfg)
    gru_result = gru_exp.run(X_train, X_val, X_test, y_dict, ml_results=ml_tables)

    # 6. Vẽ đồ thị
    print("\n[6/6] Vẽ biểu đồ...")
    out_dir = Path(__file__).parent / "data"
    out_dir.mkdir(exist_ok=True)

    lstm_exp.plot_loss_curves(save_path=str(out_dir / "lstm_loss_curves.png"))
    gru_exp.plot_loss_curves( save_path=str(out_dir / "gru_loss_curves.png"))
    lstm_exp.plot_comparison_chart(
        lstm_result["compare_df"],
        save_path=str(out_dir / "dl_vs_ml_comparison.png")
    )

    print(f"\n✅ ML-04 Deep Learning pipeline OK!")
    print(f"   - Loss curves: {out_dir / 'lstm_loss_curves.png'}")
    print(f"   - So sánh:     {out_dir / 'dl_vs_ml_comparison.png'}")
    print(f"   - Models:      {Path(lstm_cfg.model_dir)}/")
