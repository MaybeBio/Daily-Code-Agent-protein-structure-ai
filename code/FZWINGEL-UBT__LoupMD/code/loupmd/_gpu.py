"""What nvidia-smi says about the GPUs. Used by ``runtime_info``, ``loupmd doctor`` and ``loupmd bench``; imports
nothing of the package and needs neither the library nor torch."""
from __future__ import annotations

import os
import shutil
import subprocess

_WSL_PATH = "/usr/lib/wsl/lib/nvidia-smi"      # where WSL2 puts it; not always on the PATH


def nvidia_smi():
    """The nvidia-smi executable, or ``None``."""
    exe = shutil.which("nvidia-smi")
    if exe is None and os.path.isfile(_WSL_PATH):
        exe = _WSL_PATH
    return exe


def query_gpus():
    """``[(name, driver, compute capability as major * 10 + minor)]``, one per GPU in index order. Raises
    ``OSError`` when nvidia-smi is missing or fails."""
    exe = nvidia_smi()
    if exe is None:
        raise OSError("nvidia-smi was not found on the PATH")
    try:
        done = subprocess.run([exe, "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=30)
    except subprocess.SubprocessError as exc:
        raise OSError(f"nvidia-smi did not answer: {exc}") from None
    if done.returncode != 0:
        raise OSError((done.stderr or done.stdout).strip() or f"nvidia-smi ended with status {done.returncode}")
    gpus = []
    for line in done.stdout.strip().splitlines():
        name, driver, cap = [part.strip() for part in line.split(",")]
        major, _, minor = cap.partition(".")
        gpus.append((name, driver, int(major) * 10 + int(minor or 0)))
    return gpus
