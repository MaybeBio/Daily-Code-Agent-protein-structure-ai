import numpy as np
from pathlib import Path
import sys
import argparse

# allow importing project_root.py
sys.path.append(str(Path(__file__).resolve().parents[1]))
from project_root import PROCESSED

# -----------------------
# Args
# -----------------------
parser = argparse.ArgumentParser()
parser.add_argument("--window", type=int, default=10)
args = parser.parse_args()

WINDOW = args.window

# -----------------------
# Config
# -----------------------
EPS = 1e-8

WIN_DIR = PROCESSED / f"windows_w{WINDOW}"
OUT_DIR = PROCESSED / f"windows_w{WINDOW}_norm"

# Split structure:
SPLITS = PROCESSED / "splits" / f"splits_w{WINDOW}"

def compute_mean_std(data_2d: np.ndarray, idx: np.ndarray, eps: float = 1e-8):
    """Feature-wise mean/std using only rows in idx."""
    subset = data_2d[idx]
    mean = subset.mean(axis=0)
    std = subset.std(axis=0)
    std = np.where(std < eps, 1.0, std)
    return mean, std

print("Loading windows...")
X = np.load(WIN_DIR / "X.npy", mmap_mode="r")   # (N, W, Dx)
y = np.load(WIN_DIR / "y.npy", mmap_mode="r")   # (N, Dy)

print("Loading splits...")
train_idx = np.load(SPLITS / "train_idx.npy")
val_idx   = np.load(SPLITS / "val_idx.npy")
test_idx  = np.load(SPLITS / "test_idx.npy")

N, W, Dx = X.shape
Dy = y.shape[1]

print(f"X: {X.shape}  y: {y.shape}")
print(f"Train/Val/Test: {len(train_idx)}/{len(val_idx)}/{len(test_idx)}")

# -----------------------
# Compute stats (train only)
# -----------------------
print("Computing train-only normalization stats...")

# compute mean/std per feature using all timesteps from train windows
X_train = np.asarray(X[train_idx], dtype=np.float32).reshape(-1, Dx)  # (len(train)*W, Dx)
X_mean = X_train.mean(axis=0)
X_std  = X_train.std(axis=0)
X_std  = np.where(X_std < EPS, 1.0, X_std)

y_train = np.asarray(y[train_idx], dtype=np.float32)                  # (len(train), Dy)
y_mean, y_std = compute_mean_std(y_train, np.arange(y_train.shape[0]), eps=EPS)

# -----------------------
# Apply normalization
# -----------------------
print("Applying normalization and saving...")

OUT_DIR.mkdir(parents=True, exist_ok=True)

Xn_path = OUT_DIR / "X.npy"
yn_path = OUT_DIR / "y.npy"

chunk = 2048

Xn = np.lib.format.open_memmap(Xn_path, mode="w+", dtype=np.float32, shape=(N, W, Dx))
yn = np.lib.format.open_memmap(yn_path, mode="w+", dtype=np.float32, shape=(N, Dy))

for start in range(0, N, chunk):
    end = min(N, start + chunk)
    X_block = np.asarray(X[start:end], dtype=np.float32)   # (b, W, Dx)
    y_block = np.asarray(y[start:end], dtype=np.float32)   # (b, Dy)

    Xn[start:end] = (X_block - X_mean[None, None, :]) / X_std[None, None, :]
    yn[start:end] = (y_block - y_mean[None, :]) / y_std[None, :]

np.savez(OUT_DIR / "norm_stats.npz", X_mean=X_mean, X_std=X_std, y_mean=y_mean, y_std=y_std)

meta = {
    "WINDOW": int(WINDOW),
    "source_windows_dir": str(WIN_DIR),
    "normalized_windows_dir": str(OUT_DIR),
    "splits_dir": str(SPLITS),
    "X_dim": int(Dx),
    "y_dim": int(Dy),
    "eps": float(EPS),
    "note": "Stats computed from TRAIN split only. X stats use all timesteps in train windows."
}
np.save(OUT_DIR / "meta.npy", meta)

print("DONE.")
print("Saved normalized windows to:", OUT_DIR)
print("Saved stats to:", OUT_DIR / "norm_stats.npz")
