"""The GPU tests: fixtures, and the three tiers.

They need a GPU, ``libloupmd.so`` and the model files in the folder ``LOUPMD_MODELS`` names (a test whose file
is not there skips). ``LOUPMD_TEST_MODEL`` names the file the shared fixtures use (default: MACE-OMAT-0 medium).

Tiers, by marker:

- ``fast``: every test here that is not marked otherwise. ``pytest tests/gpu -m fast``, under ten minutes.
- ``full``: long runs, statistics, step costs, the model families. ``pytest tests/gpu -m "not acceptance"`` runs
  fast and full.
- ``acceptance``: the accuracy gate per model family (exports and float64 references).
  ``pytest tests/gpu -m acceptance``; ``pytest tests/gpu`` runs all three.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from gpu_support import DEFAULT_MODEL, ROOT, TEST_MODEL_VARIABLE, find_model

sys.path.insert(0, str(ROOT / "tools" / "dev"))  # the developer scripts some tests import (test_gate.py)
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

from loupmd import LoupEngine, ensure_loup_bundle  # noqa: E402

HERE = Path(__file__).resolve().parent


def _no_gpu():
    """Why the GPU tests cannot run here, or None."""
    if os.environ.get("CUDA_VISIBLE_DEVICES") == "":
        return "CUDA_VISIBLE_DEVICES hides every GPU"
    from loupmd import _gpu

    try:
        return None if _gpu.query_gpus() else "nvidia-smi lists no GPU"
    except OSError as error:
        return f"no GPU: {error}"


def pytest_collection_modifyitems(config, items):
    own = [item for item in items if HERE in Path(str(item.fspath)).resolve().parents]
    if not own:
        return
    reason = _no_gpu()
    for item in own:
        if not (item.get_closest_marker("full") or item.get_closest_marker("acceptance")):
            item.add_marker(pytest.mark.fast)
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def model_path() -> str:
    return find_model(os.environ.get(TEST_MODEL_VARIABLE) or DEFAULT_MODEL)


@pytest.fixture(scope="session")
def sto_bundle(model_path):
    """The test model (MACE-OMAT-0 medium unless LOUPMD_TEST_MODEL names another)."""
    return ensure_loup_bundle(model_path, [8, 22, 38])


@pytest.fixture
def sto_engine(sto_bundle):
    return LoupEngine(sto_bundle, device_id=0)
