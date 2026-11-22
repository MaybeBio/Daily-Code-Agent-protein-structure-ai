"""Project path configuration.

This project is used in multiple environments:
- Local machine
- Google Colab (optionally with Google Drive mounted)
- Kaggle (dataset is read-only under /kaggle/input; outputs must go to /kaggle/working)

Import the path constants from here everywhere in your notebooks/scripts.

Key rule for Kaggle:
  - READ inputs from DATA_RAW (inside the dataset mount)
  - WRITE all generated artifacts to PROCESSED / NORMALIZED (under /kaggle/working)
"""

from __future__ import annotations

import os
from pathlib import Path


def _is_kaggle() -> bool:
    # Common Kaggle signals
    if Path("/kaggle/input").exists() and Path("/kaggle/working").exists():
        return True
    # Environment variable sometimes present
    return bool(os.environ.get("KAGGLE_KERNEL_RUN_TYPE"))


def _get_input_root() -> Path:
    # Where this repository lives (read-only on Kaggle)
    return Path(__file__).resolve().parent


def _get_root() -> Path:
    # Backward-compatible: prefer Colab Drive path if it exists (your original setup)
    colab_root = Path("/content/drive/MyDrive/Deep Learning/protein_dynamics_project")
    if colab_root.exists():
        return colab_root
    return _get_input_root()


# -----------------------
# Roots
# -----------------------
ROOT: Path = _get_root()

# Kaggle rule: never write into the dataset mount (ROOT). Use /kaggle/working instead.
if _is_kaggle():
    WORK_ROOT: Path = Path("/kaggle/working") / "protein_dynamics_project"
else:
    # Local/Colab: write next to the project by default
    WORK_ROOT = ROOT


# -----------------------
# Read paths
# -----------------------
DATA_RAW: Path = ROOT / "data" / "raw"


# -----------------------
# Write paths (safe on Kaggle)
# -----------------------
PROCESSED: Path = WORK_ROOT / "processed"


WINDOWS: Path = PROCESSED / "windows"
SPLITS: Path = PROCESSED / "splits"
MODELS: Path = PROCESSED / "models"
ALIGNED: Path = PROCESSED / "aligned"



def ensure_working_tree() -> None:
    """Create all writable directories (no-op if they already exist)."""
    for p in [PROCESSED, ALIGNED, WINDOWS, SPLITS, MODELS]:
        p.mkdir(parents=True, exist_ok=True)


def processed_file(name: str) -> Path:
    """Return a path to a processed artifact.

    On Kaggle, prefer the file generated in /kaggle/working if present.
    Otherwise, fall back to a file packaged inside the dataset mount (if you uploaded one).
    """
    work_p = PROCESSED / name
    if work_p.exists():
        return work_p
    input_p = ROOT / "processed" / name
    if input_p.exists():
        return input_p
    return work_p
