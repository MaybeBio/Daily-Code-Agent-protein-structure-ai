import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf

sys.path.append(str(Path(__file__).resolve().parents[1]))
from project_root import PROCESSED


try:
    import keras  # noqa: F401
    register_keras_serializable = keras.saving.register_keras_serializable
except Exception:
    register_keras_serializable = tf.keras.utils.register_keras_serializable


@register_keras_serializable(package="ProteinDynamics")
class TransformerBlock(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads, ff_dim, dropout, **kwargs):
        super().__init__(**kwargs)
        self.d_model = int(d_model)
        self.num_heads = int(num_heads)
        self.ff_dim = int(ff_dim)
        self.dropout = float(dropout)

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


def resolve_model_path(p: str) -> Path:
    raw = Path(p)
    project_root = Path(__file__).resolve().parents[1]
    candidates = [
        raw if raw.is_absolute() else (Path.cwd() / raw),
        project_root / raw,
        PROCESSED / "models" / raw.name,
        PROCESSED / (Path(*raw.parts[1:]) if raw.parts and raw.parts[0].lower() == "processed" else raw),
    ]
    for c in candidates:
        c = c.resolve()
        if c.exists():
            return c
    tried = "\n".join([f"  - {c.resolve()}" for c in candidates])
    raise FileNotFoundError(
        "Model file not found.\n"
        f"Provided --model_path: {p}\n"
        f"Working directory: {Path.cwd()}\n"
        f"Project root: {project_root}\n"
        f"PROCESSED: {PROCESSED}\n"
        f"Tried:\n{tried}"
    )


def load_arrays(window: int, use_denorm: bool):
    win_dir = PROCESSED / f"windows_w{window}_norm"
    splits_dir = PROCESSED / "splits" / f"splits_w{window}"

    x_path = win_dir / "X.npy"
    y_path = win_dir / "y.npy"
    stats_path = win_dir / "norm_stats.npz"
    test_idx_path = splits_dir / "test_idx.npy"

    if not x_path.exists() or not y_path.exists():
        raise FileNotFoundError(f"Missing X.npy or y.npy in {win_dir}")
    if not test_idx_path.exists():
        raise FileNotFoundError(f"Missing test_idx.npy in {splits_dir}")
    if use_denorm and not stats_path.exists():
        raise FileNotFoundError(f"Missing norm_stats.npz in {win_dir}")

    x = np.load(x_path, mmap_mode="r")
    y = np.load(y_path, mmap_mode="r")
    test_idx = np.load(test_idx_path)
    test_idx = test_idx[test_idx < x.shape[0]]

    stats = np.load(stats_path) if use_denorm else None
    return x, y, test_idx, stats


def predict_in_batches(model, x, idx, batch: int, out_dim: int) -> np.ndarray:
    pred = np.zeros((len(idx), out_dim), dtype=np.float32)
    for s in range(0, len(idx), batch):
        e = min(len(idx), s + batch)
        xb = np.asarray(x[idx[s:e]], dtype=np.float32)
        pred[s:e] = model.predict(xb, batch_size=batch, verbose=0)
    return pred


def denorm_if_needed(arr: np.ndarray, stats):
    if stats is None:
        return arr
    mean = stats["y_mean"].astype(np.float32)
    std = stats["y_std"].astype(np.float32)
    return arr * std[None, :] + mean[None, :]


def mse_block(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean((a - b) ** 2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=10)
    parser.add_argument("--model_path", type=str, required=True)
    parser.add_argument("--out_name", type=str, default="eval")
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--use_denorm", type=int, default=1)
    parser.add_argument("--save_arrays", type=int, default=1)
    args = parser.parse_args()

    window = args.window
    out_name = args.out_name
    batch = args.batch
    use_denorm = bool(args.use_denorm)
    save_arrays = bool(args.save_arrays)

    reports_dir = PROCESSED / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    x, y, test_idx, stats = load_arrays(window, use_denorm)
    dy = y.shape[1]

    model_path = resolve_model_path(args.model_path)

    print("X:", x.shape, "y:", y.shape, "test:", len(test_idx))
    print("Loading model:", model_path)

    model = tf.keras.models.load_model(
        model_path,
        compile=False,
        custom_objects={"TransformerBlock": TransformerBlock},
    )

    pred = predict_in_batches(model, x, test_idx, batch=batch, out_dim=dy)
    yt = np.asarray(y[test_idx], dtype=np.float32)

    pred_eval = denorm_if_needed(pred, stats)
    yt_eval = denorm_if_needed(yt, stats)
    y_label = "MSE (denormalized)" if use_denorm else "MSE (normalized)"

    coords_dim = 414
    vels_dim = 414

    mse_all = mse_block(pred_eval, yt_eval)
    mse_coords = mse_block(pred_eval[:, :coords_dim], yt_eval[:, :coords_dim])
    mse_vels = mse_block(
        pred_eval[:, coords_dim : coords_dim + vels_dim],
        yt_eval[:, coords_dim : coords_dim + vels_dim],
    )
    mse_forces = mse_block(
        pred_eval[:, coords_dim + vels_dim :],
        yt_eval[:, coords_dim + vels_dim :],
    )

    result = {
        "window": int(window),
        "model_path": str(model_path),
        "test_size": int(len(test_idx)),
        "batch": int(batch),
        "denorm_used": bool(use_denorm),
        "mse_all": float(mse_all),
        "mse_coords": float(mse_coords),
        "mse_vels": float(mse_vels),
        "mse_forces": float(mse_forces),
    }

    out_json = (reports_dir / f"{out_name}_w{window}.json").resolve()
    with open(out_json, "w") as f:
        json.dump(result, f, indent=2)
    print("Saved:", out_json)

    if save_arrays:
        pred_path = (reports_dir / f"{out_name}_w{window}_pred.npy").resolve()
        true_path = (reports_dir / f"{out_name}_w{window}_true.npy").resolve()
        np.save(pred_path, pred_eval)
        np.save(true_path, yt_eval)
        print("Saved:", pred_path)
        print("Saved:", true_path)

    plt.figure()
    plt.bar(["all", "coords", "vels", "forces"], [mse_all, mse_coords, mse_vels, mse_forces])
    plt.ylabel(y_label)
    plt.title(f"Test MSE blocks ({out_name}, w={window})")
    out_fig = (reports_dir / f"{out_name}_w{window}_mse_blocks.jpg").resolve()
    plt.savefig(out_fig, dpi=300, bbox_inches="tight")
    plt.close()
    print("Saved:", out_fig)


if __name__ == "__main__":
    main()
