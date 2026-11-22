"""Small helpers to copy files to and from the Modal Volume from your computer.

These just run the same `modal volume get/put` commands you could type yourself.
"""
import os
import subprocess
import sys

from modal_app import RUNS_VOLUME_NAME


def run_modal(*args, check=True):
    """Run `python -m modal <args>`. PYTHONUTF8 stops Modal crashing on Windows consoles."""
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, "-m", "modal", *args],
        env=env, check=check, capture_output=True, text=True,
    )


def volume_get(remote_path, local_path):
    """Download one file from the runs Volume. Returns True if it was found."""
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    result = run_modal("volume", "get", RUNS_VOLUME_NAME, remote_path, local_path, "--force", check=False)
    return result.returncode == 0 and os.path.exists(local_path)


def volume_put(local_path, remote_path):
    """Upload one file to the runs Volume, replacing any existing copy."""
    run_modal("volume", "put", RUNS_VOLUME_NAME, local_path, remote_path, "--force")
