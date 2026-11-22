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
parser.add_argument("--window", type=int, default=10,
                    help="Window size used to select windows_w{W}")
parser.add_argument("--train_frac", type=float, default=0.8,
                    help="Fraction of samples used for training (default=0.8)")
parser.add_argument("--val_frac", type=float, default=0.1,
                    help="Fraction of samples used for validation (default=0.1)")
args = parser.parse_args()

WINDOW = args.window
train_frac = args.train_frac
val_frac   = args.val_frac

if train_frac + val_frac >= 1.0:
    raise ValueError("train_frac + val_frac must be < 1.0")

# -----------------------
# Paths
# -----------------------
WIN_DIR = PROCESSED / f"windows_w{WINDOW}"

SPLITS_ROOT = PROCESSED / "splits"
SPLITS_DIR = SPLITS_ROOT / f"splits_w{WINDOW}"
SPLITS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------
# Load windows
# -----------------------
print("Loading X.npy from:", WIN_DIR)
X = np.load(WIN_DIR / "X.npy", mmap_mode="r")

N = X.shape[0]
print("Total samples:", N)

# -----------------------
# Chronological split
# -----------------------
n_train = int(N * train_frac)
n_val   = int(N * val_frac)

train_idx = np.arange(0, n_train)
val_idx   = np.arange(n_train, n_train + n_val)
test_idx  = np.arange(n_train + n_val, N)

# -----------------------
# Save
# -----------------------
np.save(SPLITS_DIR / "train_idx.npy", train_idx)
np.save(SPLITS_DIR / "val_idx.npy", val_idx)
np.save(SPLITS_DIR / "test_idx.npy", test_idx)

print("\nSplit fractions:")
print("train_frac =", train_frac)
print("val_frac   =", val_frac)
print("test_frac  =", round(1.0 - train_frac - val_frac, 3))

print("\nTrain / Val / Test sizes:")
print(len(train_idx), len(val_idx), len(test_idx))
print("Saved index files to:", SPLITS_DIR)
