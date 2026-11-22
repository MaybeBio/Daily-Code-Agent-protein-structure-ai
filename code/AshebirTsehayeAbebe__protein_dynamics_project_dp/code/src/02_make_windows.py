import numpy as np
from pathlib import Path
import sys
import argparse

# importing project_root.py
sys.path.append(str(Path(__file__).resolve().parents[1]))
from project_root import PROCESSED

def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "1"):
        return True
    if v.lower() in ("no", "false", "f", "0"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected.")

# -----------------------
# Args
# -----------------------
parser = argparse.ArgumentParser()
parser.add_argument("--window", type=int, default=25)
parser.add_argument(
    "--include_forces_in_input",
    type=str2bool,
    default=True,
    help="Include forces in input X windows (true/false, default: false)"
)
args = parser.parse_args()

WINDOW = args.window
INCLUDE_FORCES_IN_X = args.include_forces_in_input
SAVE_FLOAT32 = True

# output folder name depends on WINDOW
WINDOWS = PROCESSED / f"windows_w{WINDOW}"
ALIGNED_DIR = PROCESSED / "aligned"

# -----------------------
# Load aligned arrays
# -----------------------
print("Loading aligned arrays...")

coords = np.load(ALIGNED_DIR / "coords_aligned.npy")   # (T, 138, 3)
vels   = np.load(ALIGNED_DIR / "vels_aligned.npy")     # (T, 138, 3)
forces = np.load(ALIGNED_DIR / "forces_aligned.npy")   # (T, 138, 3)

print("Shapes:")
print("coords :", coords.shape)
print("vels   :", vels.shape)
print("forces :", forces.shape)

T = coords.shape[0]

# -----------------------
# Flatten per timestep
# -----------------------
coords_f = coords.reshape(T, -1)   # (T, 414)
vels_f   = vels.reshape(T, -1)     # (T, 414)
forces_f = forces.reshape(T, -1)   # (T, 414)
print("coords_f: ", coords_f)
# X = window of inputs
if INCLUDE_FORCES_IN_X:
    X_source = np.concatenate([coords_f, vels_f, forces_f], axis=1)  # (T, 1242)
else:
    X_source = np.concatenate([coords_f, vels_f], axis=1)            # (T, 828)

# y = next-step targets (ALL THREE)
y_source = np.concatenate([coords_f, vels_f, forces_f], axis=1)      # (T, 1242)

print("Per-timestep feature dims:")
print("X_source:", X_source.shape, "(per step:", X_source.shape[1], ")")
print("y_source:", y_source.shape, "(per step:", y_source.shape[1], ")")

# -----------------------
# Build sliding windows
# -----------------------
print("Building sliding windows...")

N = T - WINDOW
dtype = np.float32 if SAVE_FLOAT32 else np.float64

X = np.zeros((N, WINDOW, X_source.shape[1]), dtype=dtype)
y = np.zeros((N, y_source.shape[1]), dtype=dtype)

for i in range(N):
    X[i] = X_source[i:i+WINDOW]
    y[i] = y_source[i+WINDOW]  # predict the NEXT timestep

print("DONE.")
print("X shape:", X.shape)
print("y shape:", y.shape)

# -----------------------
# Save
# -----------------------
WINDOWS.mkdir(parents=True, exist_ok=True)

np.save(WINDOWS / "X.npy", X)
np.save(WINDOWS / "y.npy", y)

meta = {
    "WINDOW": WINDOW,
    "INCLUDE_FORCES_IN_X": INCLUDE_FORCES_IN_X,
    "X_dim": int(X.shape[2]),
    "y_dim": int(y.shape[1]),
    "target_order": "coords, vels, forces (flattened each)"
}
np.save(WINDOWS / "meta.npy", meta)

print("Saved to:", WINDOWS)
