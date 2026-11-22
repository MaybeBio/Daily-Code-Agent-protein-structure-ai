import sys
from pathlib import Path

# ============================================================
# Project root discovery
# ============================================================

def find_project_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for p in [start] + list(start.parents):
        if (p / "project_root.py").exists():
            return p
    raise FileNotFoundError(
        "Could not find project_root.py. "
        "Run this from inside the project folder (protein_dynamics_project) "
        "or `cd` to it first."
    )

PROJECT_ROOT = find_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_root import DATA_RAW, PROCESSED

PROCESSED.mkdir(parents=True, exist_ok=True)

print("DATA_RAW  =", DATA_RAW)
print("PROCESSED =", PROCESSED)

# Quick sanity: list raw files
raw_files = sorted([p.name for p in DATA_RAW.glob("*")])
print("\nFiles in data/raw:")
for f in raw_files[:50]:
    print(" -", f)
if len(raw_files) > 50:
    print(" ... (showing first 50)")

# ============================================================
# Imports
# ============================================================

import numpy as np
import pandas as pd


# ============================================================
# Robust reader: handles CSV/TSV/; and "single column with tabs inside"
# ============================================================

def read_table_auto(path: Path) -> pd.DataFrame:
    """
    Read a numeric table that may be separated by ';', '\\t', ',', or whitespace.
    """
    path = Path(path)

    # Peek at the file to check delimiter
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        sample = f.read(4096)

    if "\t" in sample:
        sep = "\t"
    elif ";" in sample:
        sep = ";"
    elif "," in sample:
        sep = ","
    else:
        sep = None

    # First read attempt
    if sep is None:
        df = pd.read_csv(path, header=None, sep=r"\s+", engine="python")
    else:
        df = pd.read_csv(path, header=None, sep=sep, engine="python")

    # Remove fully empty columns
    df = df.dropna(axis=1, how="all")

    # If we read everything into ONE column, split it manually
    if df.shape[1] == 1:
        col0 = df.iloc[:, 0].astype(str).str.strip()

        # Split by tab/semicolon/comma if they exist inside the string rows
        if col0.str.contains(r"[\t;,]").any():
            df = col0.str.split(r"[\t;,]+", expand=True)
        # Otherwise, split by whitespace
        elif col0.str.contains(r"\s+").any():
            df = col0.str.split(r"\s+", expand=True)

        # Clean empty strings -> NaN, then drop empty columns
        df = df.replace(r"^\s*$", np.nan, regex=True)
        df = df.dropna(axis=1, how="all")

    return df


def to_numeric_df(df: pd.DataFrame, name: str) -> pd.DataFrame:
    out = df.apply(pd.to_numeric, errors="coerce")
    n_bad = int(out.isna().sum().sum())
    if n_bad:
        bad_locs = np.argwhere(out.isna().to_numpy())
        r, c = bad_locs[0]
        raise ValueError(
            f"{name}: found {n_bad} non-numeric values after parsing. "
            f"Example at row {r}, col {c}: {df.iloc[r, c]!r}"
        )
    return out


# ============================================================
# File names
# ============================================================

COORDS_FILE = "coordinates.csv"
VELS_FILE = "velocity.csv"
FORCES_FILE = "forces.csv"

coords_path = DATA_RAW / COORDS_FILE
vels_path = DATA_RAW / VELS_FILE
forces_path = DATA_RAW / FORCES_FILE

for p in [coords_path, vels_path, forces_path]:
    if not p.exists():
        raise FileNotFoundError(
            f"Missing raw file: {p}.\n"
            f"Edit COORDS_FILE / VELS_FILE / FORCES_FILE to match your data/raw folder."
        )

print("\nUsing:")
print(" -", coords_path.name)
print(" -", vels_path.name)
print(" -", forces_path.name)

# ============================================================
# Read raw files
# ============================================================

print("\nReading raw files...")
coords_raw = read_table_auto(coords_path)
vels_raw = read_table_auto(vels_path)
forces_raw = read_table_auto(forces_path)

# Optional debug
print("\nParsed shapes (including time column):")
print("coords_raw :", coords_raw.head())
print("vels_raw   :", vels_raw.shape)
print("forces_raw :", forces_raw.shape)

# ============================================================
# Convert to numeric (will throw a clear error if still dirty)
# ============================================================

coords_raw = to_numeric_df(coords_raw, "coords")
vels_raw = to_numeric_df(vels_raw, "vels")
forces_raw = to_numeric_df(forces_raw, "forces")

# ============================================================
# Extract time and values
# ============================================================

t_coords = coords_raw.iloc[:, 0].to_numpy(dtype=np.float64)
t_vels = vels_raw.iloc[:, 0].to_numpy(dtype=np.float64)
t_forces = forces_raw.iloc[:, 0].to_numpy(dtype=np.float64)

coords_vals = coords_raw.iloc[:, 1:].to_numpy(dtype=np.float32)
vels_vals = vels_raw.iloc[:, 1:].to_numpy(dtype=np.float32)
forces_vals = forces_raw.iloc[:, 1:].to_numpy(dtype=np.float32)

print("\nRaw shapes (rows, cols_without_time):")
print("coords :", coords_vals.shape)
print("vels   :", vels_vals.shape)
print("forces :", forces_vals.shape)

# ============================================================
# Align by shortest length
# ============================================================

min_len = min(
    len(t_coords), len(t_vels), len(t_forces),
    coords_vals.shape[0], vels_vals.shape[0], forces_vals.shape[0]
)

t_coords = t_coords[:min_len]
t_vels = t_vels[:min_len]
t_forces = t_forces[:min_len]

coords_vals = coords_vals[:min_len]
vels_vals = vels_vals[:min_len]
forces_vals = forces_vals[:min_len]

# Verify time matches (tolerant)
if not (np.allclose(t_coords, t_vels) and np.allclose(t_coords, t_forces)):
    raise AssertionError("Time columns do not match after trimming. Check your raw files.")

# Verify same feature dims
if not (coords_vals.shape[1] == vels_vals.shape[1] == forces_vals.shape[1]):
    raise AssertionError(
        f"Feature column counts differ: coords={coords_vals.shape[1]}, "
        f"vels={vels_vals.shape[1]}, forces={forces_vals.shape[1]}"
    )

D = coords_vals.shape[1]
if D % 3 != 0:
    raise AssertionError(f"Feature dimension {D} is not divisible by 3. Expected xyz per atom.")
n_atoms = D // 3

print("\nAligned length:", min_len)
print("n_atoms inferred:", n_atoms)

# ============================================================
# Reshape to (T, n_atoms, 3) and save aligned arrays
# ============================================================

T = coords_vals.shape[0]

coords_arr = coords_vals.reshape(T, n_atoms, 3)
vels_arr = vels_vals.reshape(T, n_atoms, 3)
forces_arr = forces_vals.reshape(T, n_atoms, 3)

print("\nFinal shapes:")
print("coords :", coords_arr.shape)
print("vels   :", vels_arr.shape)
print("forces :", forces_arr.shape)

ALIGNED_DIR = PROCESSED / "aligned"
ALIGNED_DIR.mkdir(parents=True, exist_ok=True)  #Ensure directory exists

np.save(ALIGNED_DIR / "coords_aligned.npy", coords_arr.astype(np.float32))
np.save(ALIGNED_DIR / "vels_aligned.npy", vels_arr.astype(np.float32))
np.save(ALIGNED_DIR / "forces_aligned.npy", forces_arr.astype(np.float32))

print("\nSaved:")
print(" -", ALIGNED_DIR / "coords_aligned.npy")
print(" -", ALIGNED_DIR / "vels_aligned.npy")
print(" -", ALIGNED_DIR / "forces_aligned.npy")
