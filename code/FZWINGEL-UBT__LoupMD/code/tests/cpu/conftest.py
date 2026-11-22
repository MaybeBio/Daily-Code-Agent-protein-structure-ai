"""The CPU tests: no GPU, no library, no torch. The engine is the fake of ``fake_core.py`` or a stand-in a test
writes itself; what a test starts as a child process sees no GPU either."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_gpu(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
