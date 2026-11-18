"""Trainer for Graph Neural Networks on protein residue graphs with mixed precision."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader

from protgnn.evaluation.metrics import compute_ec_metrics, find_optimal_thresholds


class GNNTrainer:
    """Trainer for multi-label GNN protein function models."""

    def __init__(
        self,
        model: nn.Module,
        cfg: dict[str, Any],
        device: torch.device,
        logger: logging.Logger | None = None,
    ):
        self.model = model.to(device)
        self.cfg = cfg
        self.device = device
        self.logger = logger or logging.getLogger(__name__)

        train_cfg = cfg.get("training", {})
        self.epochs = train_cfg.get("epochs", 10)
        self.grad_clip = train_cfg.get("grad_clip", 1.0)
        self.patience = train_cfg.get("patience", 3)
        self.use_amp = train_cfg.get("amp", True) and device.type == "cuda"

        self.criterion = nn.BCEWithLogitsLoss()

        lr = train_cfg.get("learning_rate", 1e-3)
        weight_decay = train_cfg.get("weight_decay", 1e-4)

        self.optimizer = AdamW(self.model.parameters(), lr=lr, weight_decay=weight_decay)
        self.scheduler = CosineAnnealingLR(self.optimizer, T_max=self.epochs, eta_min=1e-6)

    def train_epoch(self, loader: DataLoader) -> dict[str, float]:
        self.model.train()
        total_loss = 0.0
        n_batches = 0

        for batch in loader:
            x = batch["x"].to(self.device)
            edge_index = batch["edge_index"].to(self.device)
            edge_attr = batch["edge_attr"].to(self.device)
            batch_vec = batch["batch"].to(self.device)
            y = batch["y"].to(self.device)

            self.optimizer.zero_grad()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=self.use_amp):
                out = self.model(x=x, edge_index=edge_index, edge_attr=edge_attr, batch=batch_vec)
                loss = self.criterion(out["logits"], y)

            loss.backward()
            if self.grad_clip > 0:
                nn.utils.clip_grad_norm_(self.model.parameters(), self.grad_clip)
            self.optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        self.scheduler.step()
        return {"loss": total_loss / max(n_batches, 1)}

    @torch.no_grad()
    def evaluate(
        self,
        loader: DataLoader,
        thresholds: float | np.ndarray = 0.5,
    ) -> dict[str, Any]:
        self.model.eval()
        all_true = []
        all_probs = []
        sample_embeddings = []
        sample_labels = []

        for batch in loader:
            x = batch["x"].to(self.device)
            edge_index = batch["edge_index"].to(self.device)
            edge_attr = batch["edge_attr"].to(self.device)
            batch_vec = batch["batch"].to(self.device)
            y = batch["y"]

            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=self.use_amp):
                out = self.model(x=x, edge_index=edge_index, edge_attr=edge_attr, batch=batch_vec)

            probs = out["probs"].cpu().float().numpy()
            all_probs.append(probs)
            all_true.append(y.numpy())

            if len(sample_embeddings) < 2500:
                pooled = out["pooled"].cpu().float().numpy()
                sample_embeddings.append(pooled)
                sample_labels.append(y.numpy())

        y_true = np.concatenate(all_true, axis=0)
        y_probs = np.concatenate(all_probs, axis=0)

        metrics = compute_ec_metrics(y_true=y_true, y_probs=y_probs, thresholds=thresholds)
        metrics["y_true"] = y_true
        metrics["y_probs"] = y_probs
        if sample_embeddings:
            metrics["sample_embeddings"] = np.concatenate(sample_embeddings, axis=0)
            metrics["sample_labels"] = np.concatenate(sample_labels, axis=0)

        return metrics

    def fit(
        self,
        train_loader: DataLoader,
        val_loader: DataLoader,
        save_path: Path | None = None,
    ) -> tuple[list[dict[str, float]], np.ndarray]:
        best_macro_f1 = -1.0
        patience_left = self.patience
        history: list[dict[str, float]] = []
        best_thresholds = np.full(self.cfg["model"].get("num_classes", 25), 0.5, dtype=np.float32)

        self.logger.info(f"Starting GNN training for {self.epochs} epochs on {self.device}...")
        for epoch in range(1, self.epochs + 1):
            t0 = time.time()
            tr_res = self.train_epoch(train_loader)

            # Evaluate with default threshold first
            val_res = self.evaluate(val_loader, thresholds=0.5)
            elapsed = time.time() - t0

            # Calibrate optimal per-class thresholds on validation set
            opt_th = find_optimal_thresholds(val_res["y_true"], val_res["y_probs"])
            cal_res = compute_ec_metrics(val_res["y_true"], val_res["y_probs"], thresholds=opt_th)

            macro_f1 = cal_res["macro_f1"]
            micro_f1 = cal_res["micro_f1"]
            macro_mcc = cal_res["macro_mcc"]

            entry = {
                "epoch": epoch,
                "train_loss": tr_res["loss"],
                "val_macro_f1": macro_f1,
                "val_micro_f1": micro_f1,
                "val_macro_mcc": macro_mcc,
                "val_lrap": cal_res["lrap"],
                "time_sec": elapsed,
            }
            history.append(entry)

            self.logger.info(
                f"Epoch {epoch:02d}/{self.epochs:02d} | Loss: {tr_res['loss']:.4f} | "
                f"Val Macro-F1: {macro_f1:.4f} | Micro-F1: {micro_f1:.4f} | Macro-MCC: {macro_mcc:.4f} | {elapsed:.1f}s"
            )

            if macro_f1 > best_macro_f1:
                best_macro_f1 = macro_f1
                best_thresholds = opt_th
                patience_left = self.patience
                if save_path is not None:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(self.model.state_dict(), save_path)
            else:
                patience_left -= 1
                if patience_left <= 0:
                    self.logger.info(f"Early stopping triggered at epoch {epoch}.")
                    break

        if save_path is not None and save_path.exists():
            self.model.load_state_dict(torch.load(save_path, map_location=self.device, weights_only=True))

        return history, best_thresholds

