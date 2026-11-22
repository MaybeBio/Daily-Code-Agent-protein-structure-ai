from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .config import get


def available(cfg: dict[str, Any]) -> bool:
    python = get(cfg, "tmol.python")
    return bool(python) and Path(python).is_file()


def run_tmol(
    cfg: dict[str, Any],
    structures: list[Path],
    outdir: Path,
    log_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Score structures with tmol and return {structure_path: metrics}."""
    if not structures or not available(cfg):
        return {}
    outdir.mkdir(parents=True, exist_ok=True)
    python = get(cfg, "tmol.python")
    runner = Path(__file__).resolve().parent / "_tmol_runner.py"
    command = [
        python,
        str(runner),
        "--output-dir",
        str(outdir),
        "--mode",
        str(get(cfg, "tmol.mode", "score")),
        "--device",
        str(get(cfg, "tmol.device", "cuda")),
        "--num-repeats",
        str(get(cfg, "tmol.num_repeats", 2)),
    ]
    for path in structures:
        command += ["--input", str(path)]
    log = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
    try:
        result = subprocess.run(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    finally:
        if log_path:
            log.close()
    if result.returncode != 0:
        return {}
    metrics: dict[str, dict[str, Any]] = {}
    for path in outdir.glob("*.metrics.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "input_path" in payload:
            metrics[payload["input_path"]] = payload
    return metrics
