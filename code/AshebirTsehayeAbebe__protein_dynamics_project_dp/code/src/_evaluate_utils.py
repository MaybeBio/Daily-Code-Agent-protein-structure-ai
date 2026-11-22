# src/_evaluate_utils.py
# Shared utilities for evaluation + plotting (supports your splits folder format)

import sys
from pathlib import Path

import numpy as np
import tensorflow as tf

# Make sure project_root.py is importable
sys.path.append(str(Path(__file__).resolve().parents[1]))
from project_root import PROCESSED  # noqa: E402


# --- Keras serialization helper (works across keras/tf versions) ---
try:
    import keras  # noqa: F401

    register_keras_serializable = keras.saving.register_keras_serializable
except Exception:
    register_keras_serializable = tf.keras.utils.register_keras_serializable


@register_keras_serializable(package="ProteinDynamics")
class TransformerBlock(tf.keras.layers.Layer):
    """
    Minimal Transformer block definition used ONLY so load_model() can deserialize
    models that include this custom layer.

    If your training code used a different TransformerBlock signature/structure,
    you MUST mirror it here exactly.
    """

    def __init__(self, d_model, num_heads, ff_dim, dropout, **kwargs):
        super().__init__(**kwargs)
        self.d_model = int(d_model)
        self.num_heads = int(num_heads)
        self.ff_dim = int(ff_dim)
        self.dropout = float(dropout)

        # key_dim must be per-head dimension
        self.mha = tf.keras.layers.MultiHeadAttention(
            num_heads=self.num_heads,
            key_dim=max(1, self.d_model // self.num_heads),
        )
        self.ffn = tf.keras.Sequential(
            [
                tf.keras.layers.Dense(self.ff_dim, activation="relu"),
                tf.keras.layers.Dense(self.d_model),
            ]
        )
        self.norm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.norm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.drop1 = tf.keras.layers.Dropout(self.dropout)
        self.drop2 = tf.keras.layers.Dropout(self.dropout)

    def call(self, x, training=False):
        attn = self.mha(x, x, training=training)
        x = self.norm1(x + self.drop1(attn, training=training))
        ffn = self.ffn(x, training=training)
        x = self.norm2(x + self.drop2(ffn, training=training))
        return x

    def get_config(self):
        cfg = super().get_config()
        cfg.update(
            {
                "d_model": self.d_model,
                "num_heads": self.num_heads,
                "ff_dim": self.ff_dim,
                "dropout": self.dropout,
            }
        )
        return cfg


def resolve_model_path(model_path: str) -> Path:
    """
    Accepts either an absolute path or a path relative to PROCESSED.
    Example:
      --model_path models/best_transformer.keras
    """
    p = Path(model_path)
    if p.is_absolute():
        return p
    return (PROCESSED / p).resolve()


def load_arrays(window: int, use_denorm: bool):
    """
    Robust loader that supports BOTH formats:

    Your format (from screenshot):
      processed/splits/splits_w{window}/test_idx.npy

    Fallback old format:
      processed/split_w{window}.npz  (contains test_idx)

    Data arrays:
      processed/windows_w{window}/X.npy
      processed/windows_w{window}/y.npy

    Optional normalization stats:
      processed/stats_w{window}.npz  (y_mean, y_std)
    """
    win_dir = PROCESSED / f"windows_w{window}"

    X_path = win_dir / "X.npy"
    y_path = win_dir / "y.npy"

    if not X_path.exists():
        raise FileNotFoundError(f"Missing file: {X_path}")
    if not y_path.exists():
        raise FileNotFoundError(f"Missing file: {y_path}")

    X = np.load(X_path)  # (N, W, dx)
    y = np.load(y_path)  # (N, dy)

    # --- preferred split format (folder-based) ---
    split_dir = PROCESSED / "splits" / f"splits_w{window}"
    test_idx_path = split_dir / "test_idx.npy"

    if test_idx_path.exists():
        test_idx = np.load(test_idx_path).astype(int)
    else:
        # --- fallback split format (npz-based) ---
        split_npz = PROCESSED / f"split_w{window}.npz"
        if not split_npz.exists():
            raise FileNotFoundError(
                "Could not find test split.\n"
                f"Tried:\n - {test_idx_path}\n - {split_npz}\n\n"
                "Fix: ensure you have processed/splits/splits_wXX/test_idx.npy "
                "or provide processed/split_wXX.npz."
            )
        split = np.load(split_npz, allow_pickle=True)
        if "test_idx" not in split:
            raise KeyError(f"'test_idx' not found inside {split_npz}")
        test_idx = split["test_idx"].astype(int)

    stats = None
    stats_path = PROCESSED / f"stats_w{window}.npz"
    if use_denorm and stats_path.exists():
        st = np.load(stats_path)
        if "y_mean" in st and "y_std" in st:
            stats = {"y_mean": st["y_mean"], "y_std": st["y_std"]}

    return X, y, test_idx, stats


def denorm_if_needed(arr: np.ndarray, stats):
    """
    arr: (N, dy) or (dy,)
    stats: {"y_mean": (dy,), "y_std": (dy,)}
    """
    if stats is None:
        return arr
    mean = stats["y_mean"].astype(np.float32)
    std = stats["y_std"].astype(np.float32)

    if arr.ndim == 1:
        return arr * std + mean
    return arr * std[None, :] + mean[None, :]


def predict_one_step(model, x_window: np.ndarray) -> np.ndarray:
    """
    x_window: (W, dx)
    returns: (dy,)
    """
    x_in = x_window[None, :, :].astype(np.float32)
    yhat = model(x_in, training=False).numpy()[0]
    return yhat.astype(np.float32)
