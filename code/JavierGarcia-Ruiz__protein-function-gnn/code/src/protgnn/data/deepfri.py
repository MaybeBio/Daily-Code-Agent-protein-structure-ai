"""Loading, downloading, and partitioning of the PDB Enzyme Commission benchmark."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

from protgnn.data.constants import EC_CLASSES, EC_TO_IDX


def parse_ec_labels(ec_string: str) -> list[str]:
    """Parse comma/semicolon/space-separated EC labels."""
    if not isinstance(ec_string, str) or not ec_string.strip():
        return []
    raw = ec_string.replace(";", " ").replace(",", " ").split()
    # Match prefixes or exact classes
    valid = []
    for r in raw:
        r_clean = r.strip()
        if r_clean in EC_TO_IDX:
            valid.append(r_clean)
        else:
            # Check if 3-level prefix matches (e.g., 1.1.1.1 -> 1.1.1)
            parts = r_clean.split(".")
            if len(parts) >= 3:
                prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
                if prefix in EC_TO_IDX and prefix not in valid:
                    valid.append(prefix)
    return valid


def create_label_vector(ec_list: list[str]) -> np.ndarray:
    """Create a multi-label binary indicator vector (len(EC_CLASSES),) for a protein."""
    vec = np.zeros(len(EC_CLASSES), dtype=np.float32)
    for ec in ec_list:
        idx = EC_TO_IDX.get(ec)
        if idx is not None:
            vec[idx] = 1.0
    return vec


def load_ec_benchmark(raw_dir: str | Path) -> pd.DataFrame:
    """Load the PDB EC benchmark splits dataframe."""
    p = Path(raw_dir) / "ec_pdb_splits.csv"
    if not p.exists():
        raise FileNotFoundError(f"PDB EC benchmark file not found at {p}. Please run scripts/download_data.py first.")
    df = pd.read_csv(p)
    return df

