import random
import subprocess
from pathlib import Path

import numpy as np
import torch
import yaml


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def get_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_config(*paths: str | Path) -> dict:
    """Merge yaml files left to right, so later files override earlier ones."""
    merged = {}
    for path in paths:
        merge(merged, yaml.safe_load(Path(path).read_text()))
    return merged


def merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def append_row(path: Path | str, row: dict) -> None:
    """Append one result row to a csv, writing the header if the file is new.

    If the row's columns differ from the file's header (a field was added or
    dropped), the file is rewritten with the union of columns so it stays
    parseable; missing values are left empty.
    """
    import pandas as pd

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([row])
    if not path.exists():
        new.to_csv(path, index=False)
        return
    existing_cols = list(pd.read_csv(path, nrows=0).columns)
    if list(new.columns) == existing_cols:
        new.to_csv(path, mode="a", header=False, index=False)
    elif set(new.columns) <= set(existing_cols):
        new.reindex(columns=existing_cols).to_csv(path, mode="a", header=False, index=False)
    else:
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
        columns = existing_cols + [c for c in new.columns if c not in existing_cols]
        merged = pd.concat([old, new.astype(str)], ignore_index=True).reindex(columns=columns)
        merged.to_csv(path, index=False)
